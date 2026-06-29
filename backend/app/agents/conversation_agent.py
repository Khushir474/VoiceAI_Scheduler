"""Conversation Agent: Manages voice/text interaction with user using LLM."""

import asyncio
import json
import time
from typing import Any
from datetime import datetime

from anthropic import Anthropic, APITimeoutError, APIError
from openai import AsyncOpenAI, APITimeoutError as OpenAITimeoutError

from app.agents.state import AgentState, DailyPlanData, WorkoutRecommendation
from app.agents.prompts import PlanGenerationPrompt
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer
from app.config import get_settings


class ConversationAgent:
    """Conversation Agent: Generates plan using LLM, manages interaction."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        langfuse_tracer: LangfuseTracer | None = None,
        provider: str = "anthropic",
    ):
        self.debug_logger = debug_logger
        self.langfuse_tracer = langfuse_tracer
        self.provider = provider
        self.settings = get_settings()

        # Initialize LLM clients based on provider
        if self.provider == "anthropic":
            self.llm_client = Anthropic(api_key=self.settings.anthropic_api_key)
            self.model = "claude-3-5-sonnet-20241022"
        else:
            self.llm_client = AsyncOpenAI(api_key=self.settings.openai_api_key)
            self.model = "gpt-4-turbo-preview"

    async def _call_claude(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_retries: int = 2,
    ) -> tuple[str, int]:
        """Call Claude API with retry logic (sync wrapper for async context).

        Returns:
            (response_text, latency_ms)
        """
        for attempt in range(max_retries + 1):
            try:
                start_time = time.time()

                message = self.llm_client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    temperature=temperature,
                )

                latency_ms = int((time.time() - start_time) * 1000)
                return message.content[0].text, latency_ms

            except APITimeoutError as e:
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise Exception(f"Claude API timeout after {max_retries + 1} attempts: {str(e)}")
            except APIError as e:
                if attempt < max_retries and e.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise Exception(f"Claude API error: {str(e)}")

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_retries: int = 2,
    ) -> tuple[str, int]:
        """Call OpenAI API with retry logic.

        Returns:
            (response_text, latency_ms)
        """
        for attempt in range(max_retries + 1):
            try:
                start_time = time.time()

                response = await self.llm_client.chat.completions.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                )

                latency_ms = int((time.time() - start_time) * 1000)
                return response.choices[0].message.content, latency_ms

            except OpenAITimeoutError as e:
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise Exception(f"OpenAI API timeout after {max_retries + 1} attempts: {str(e)}")
            except Exception as e:
                if attempt < max_retries and "429" in str(e):
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise Exception(f"OpenAI API error: {str(e)}")

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ) -> tuple[str, int]:
        """Call LLM with fallback to OpenAI if Claude fails."""
        try:
            if self.provider == "anthropic":
                return await self._call_claude(system_prompt, user_prompt, temperature)
            else:
                return await self._call_openai(system_prompt, user_prompt, temperature)
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="llm_call_error",
                level="error",
                message=f"LLM call failed: {str(e)}",
                error=str(e),
            )
            raise

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """Parse JSON response from LLM, handling markdown formatting.

        Raises:
            ValueError if JSON is invalid
        """
        # Remove markdown code blocks if present
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1]) if len(lines) > 2 else response
        response = response.strip()

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {str(e)}\nResponse: {response}")

    async def _generate_plan_with_llm(self, state: AgentState) -> dict[str, Any]:
        """Use LLM to generate structured daily plan.

        Returns:
            Dictionary with plan data
        """
        system_prompt = PlanGenerationPrompt.system_prompt()
        user_prompt = PlanGenerationPrompt.generate_plan_prompt(state)

        start_time = time.time()
        response_text, latency_ms = await self._call_llm(system_prompt, user_prompt, temperature=0.5)
        total_latency = int((time.time() - start_time) * 1000)

        # Log LLM call to Langfuse
        if self.langfuse_tracer:
            trace = self.langfuse_tracer.trace_llm_call(
                model=self.model,
                messages=[{"role": "user", "content": user_prompt}],
                run_id=state.run_id,
            )
            trace.end(completion=response_text, tokens_prompt=None, tokens_completion=None)

        # Parse response
        plan_data = self._parse_json_response(response_text)

        await self.debug_logger.log_event(
            agent_name="ConversationAgent",
            event_type="llm_plan_generation",
            message="Plan generated via LLM",
            output_payload={"latency_ms": total_latency, "response_length": len(response_text)},
            latency_ms=total_latency,
        )

        return plan_data

    def _update_plan_from_llm_response(self, state: AgentState, plan_data: dict[str, Any]) -> None:
        """Update the AgentState.plan with LLM-generated data."""
        if not state.plan:
            return

        # Update summaries
        state.plan.calendar_summary = plan_data.get("calendar_summary", state.plan.calendar_summary)
        state.plan.weather_summary = plan_data.get("weather_summary", state.plan.weather_summary)
        state.plan.commute_summary = plan_data.get("commute_summary", state.plan.commute_summary)
        state.plan.final_summary = plan_data.get("final_summary", state.plan.final_summary)

        # Update leave time
        leave_time_str = plan_data.get("leave_time")
        if leave_time_str:
            try:
                state.plan.leave_time = datetime.fromisoformat(leave_time_str)
            except (ValueError, TypeError):
                pass

        # Update carry items
        state.plan.carry_items = plan_data.get("carry_items", [])

        # Update workout recommendation
        workout_data = plan_data.get("workout_recommendation")
        if workout_data:
            try:
                start_time_str = workout_data.get("start_time")
                end_time_str = workout_data.get("end_time")

                state.plan.workout_recommendation = WorkoutRecommendation(
                    duration_minutes=workout_data.get("duration_minutes", 30),
                    recommended_time=workout_data.get("recommended_time", "flexible"),
                    start_time=datetime.fromisoformat(start_time_str) if start_time_str else None,
                    end_time=datetime.fromisoformat(end_time_str) if end_time_str else None,
                    notes=workout_data.get("notes"),
                )
            except (ValueError, TypeError, KeyError):
                pass

    def _format_plan_for_speech(self, plan: DailyPlanData) -> str:
        """Convert plan to natural speech text."""
        lines = []

        # Use final summary if available
        if plan.final_summary:
            return plan.final_summary

        # Fallback to detailed format
        if plan.calendar_events:
            lines.append(f"Calendar: {plan.calendar_summary}")
        else:
            lines.append("Calendar: You have no events today.")

        if plan.weather:
            lines.append(f"Weather: {plan.weather_summary}")

        if plan.commute:
            lines.append(f"Commute: {plan.commute_summary}")

        if plan.workout_recommendation:
            lines.append(
                f"Workout: {plan.workout_recommendation.duration_minutes} minutes "
                f"recommended in the {plan.workout_recommendation.recommended_time}."
            )

        if plan.leave_time:
            lines.append(f"Leave by: {plan.leave_time.strftime('%I:%M %p')}")

        if plan.carry_items:
            items_str = ", ".join(plan.carry_items)
            lines.append(f"Bring: {items_str}")

        return " ".join(lines)

    async def run(self, state: AgentState) -> AgentState:
        """Execute conversation agent with LLM-powered plan generation."""
        await self.debug_logger.log_agent_start("ConversationAgent")

        trace = (
            self.langfuse_tracer.trace_agent("ConversationAgent", state.run_id, state.user_id)
            if self.langfuse_tracer
            else None
        )

        try:
            if not state.plan:
                raise ValueError("No plan to present")

            # Generate plan using LLM
            start_time = time.time()
            plan_data = await self._generate_plan_with_llm(state)
            llm_latency = int((time.time() - start_time) * 1000)

            # Update state.plan with LLM-generated data
            self._update_plan_from_llm_response(state, plan_data)

            if trace:
                trace.span(
                    "generate_plan_llm",
                    output_data={"has_final_summary": bool(state.plan.final_summary)},
                    latency_ms=llm_latency,
                )

            # Format plan for speech
            start_time = time.time()
            speech_text = self._format_plan_for_speech(state.plan)
            format_latency = int((time.time() - start_time) * 1000)

            if trace:
                trace.span(
                    "format_plan",
                    output_data={"speech_length": len(speech_text)},
                    latency_ms=format_latency,
                )

            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="plan_presented",
                message="Plan formatted for speech",
                output_payload={"speech_length": len(speech_text)},
            )

            # Update transcript
            state.transcript.append(
                {
                    "role": "assistant",
                    "content": speech_text,
                }
            )

            # In production: Listen for user input via Vapi, update state.user_input
            # For MVP: user_input remains empty (will be filled by Vapi webhook)

            if state.user_input:
                state.transcript.append(
                    {
                        "role": "user",
                        "content": state.user_input,
                    }
                )

                if trace:
                    trace.span(
                        "user_input",
                        input_data={"user_input": state.user_input},
                    )

                await self.debug_logger.log_event(
                    agent_name="ConversationAgent",
                    event_type="user_input_received",
                    message=f"User said: {state.user_input}",
                    input_payload={"user_input": state.user_input},
                )

            if trace:
                trace.end(output_data={"transcript_length": len(state.transcript)})

            await self.debug_logger.log_agent_end("ConversationAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="error",
                level="error",
                message=f"Conversation error: {str(e)}",
                error=str(e),
            )

            if trace:
                trace.end(error=str(e))

            await self.debug_logger.log_agent_end("ConversationAgent", success=False)
            state.error = str(e)

        return state
