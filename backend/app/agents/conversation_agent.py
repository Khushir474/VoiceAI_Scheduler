"""Conversation Agent: Manages voice/text interaction with user using LLM."""

import asyncio
import json
import time
from typing import Any
from datetime import datetime

from anthropic import Anthropic, APITimeoutError, APIError
from openai import AsyncOpenAI, APITimeoutError as OpenAITimeoutError

from app.agents.state import AgentState, DailyPlanData, WorkoutRecommendation
from app.agents.prompts import PlanGenerationPrompt, ConversationPrompt
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer
from app.config import get_settings

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.adapters.voice.vapi import VapiAdapter
    from app.adapters.messaging.base import MessageAdapter

from app.adapters.voice.dailyops_prompt import build_system_prompt


class ConversationAgent:
    """Conversation Agent: Generates plan using LLM, manages interaction."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        langfuse_tracer: LangfuseTracer | None = None,
        provider: str = "anthropic",
        vapi_adapter: "VapiAdapter | None" = None,
        recipient_phone: str | None = None,
    ):
        self.debug_logger = debug_logger
        self.langfuse_tracer = langfuse_tracer
        self.provider = provider
        self.vapi_adapter = vapi_adapter
        self.recipient_phone = recipient_phone
        self.settings = get_settings()

        # Initialize LLM clients based on provider
        if self.provider == "anthropic":
            self.llm_client = Anthropic(api_key=self.settings.anthropic_api_key)
            self.model = "claude-3-5-sonnet-20241022"
        elif self.provider == "openrouter":
            self.llm_client = AsyncOpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            self.model = "anthropic/claude-haiku-4-5"
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

    async def process_user_input(self, state: AgentState) -> tuple[str, str]:
        """Interpret user's spoken response and update the plan if needed.

        Calls LLM to classify the input as one of:
          - "add_event"   user mentioned a new appointment
          - "confirm"     user approved the plan
          - "clarify"     user asked a question or needs more info
          - "decline"     user rejected a recommendation

        Appends both user utterance and agent response to state.transcript.

        Returns:
            (action, agent_response_text)
        """
        if not state.plan or not state.user_input:
            fallback = "Sorry, I didn't catch that. Could you say that again?"
            state.transcript.append({"role": "assistant", "content": fallback})
            return "clarify", fallback

        system_prompt = PlanGenerationPrompt.system_prompt()
        user_prompt = PlanGenerationPrompt.user_input_processing_prompt(
            state.user_input, state.plan
        )

        start_time = time.time()
        try:
            response_text, latency_ms = await self._call_llm(
                system_prompt, user_prompt, temperature=0.3
            )
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="user_input_llm_error",
                level="error",
                message=f"Failed to process user input: {e}",
                error=str(e),
            )
            fallback = "I had trouble processing that. Let me continue with your current plan."
            state.transcript.append({"role": "user", "content": state.user_input})
            state.transcript.append({"role": "assistant", "content": fallback})
            return "clarify", fallback

        latency_ms = int((time.time() - start_time) * 1000)

        try:
            result = self._parse_json_response(response_text)
        except ValueError:
            result = {"action": "clarify", "response": "Got it, let me note that."}

        action = result.get("action", "clarify")
        agent_response = result.get("response", "Got it.")

        # Apply plan update if LLM returned one
        updated_plan = result.get("updated_plan")
        if updated_plan and state.plan:
            new_summary = updated_plan.get("final_summary")
            if new_summary:
                state.plan.final_summary = new_summary

        state.transcript.append({"role": "user", "content": state.user_input})
        state.transcript.append({"role": "assistant", "content": agent_response})

        await self.debug_logger.log_event(
            agent_name="ConversationAgent",
            event_type="user_input_interpreted",
            message=f"User action: {action}",
            input_payload={"user_input": state.user_input},
            output_payload={"action": action, "response": agent_response},
            latency_ms=latency_ms,
        )

        return action, agent_response

    def _format_plan_for_sms(self, plan: DailyPlanData) -> str:
        """Format the daily plan as a concise SMS-friendly text."""
        lines = ["📅 Your DailyOps Summary"]

        if plan.final_summary:
            lines.append(plan.final_summary)
        else:
            if plan.calendar_summary:
                lines.append(f"📆 {plan.calendar_summary}")
            if plan.weather_summary:
                lines.append(f"🌤 {plan.weather_summary}")
            if plan.commute_summary:
                lines.append(f"🚗 {plan.commute_summary}")
            if plan.leave_time:
                lines.append(f"🕐 Leave by {plan.leave_time.strftime('%I:%M %p')}")
            if plan.carry_items:
                lines.append(f"🎒 Bring: {', '.join(plan.carry_items)}")
            if plan.workout_recommendation:
                wr = plan.workout_recommendation
                lines.append(
                    f"💪 Workout: {wr.duration_minutes} min in the {wr.recommended_time}"
                )

        return "\n".join(lines)

    async def send_summary(
        self,
        state: AgentState,
        messaging_adapter: "MessageAdapter",
        recipient: str,
    ) -> bool:
        """Send the final daily plan as an SMS/iMessage summary.

        Args:
            state: Current agent state with plan
            messaging_adapter: Configured MessageAdapter (Twilio or iMessage)
            recipient: Phone number to send to

        Returns:
            True if sent successfully, False otherwise
        """
        if not state.plan:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="summary_skipped",
                level="warning",
                message="No plan to send summary for",
            )
            return False

        summary_text = self._format_plan_for_sms(state.plan)

        start_time = time.time()
        try:
            result = await messaging_adapter.send_message(recipient, summary_text)
            latency_ms = int((time.time() - start_time) * 1000)

            success = result.get("status") in ("sent", "success")
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="summary_sent" if success else "summary_failed",
                level="info" if success else "error",
                message=f"Summary {'sent' if success else 'failed'} to {recipient}",
                output_payload=result,
                latency_ms=latency_ms,
            )
            return success

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="summary_error",
                level="error",
                message=f"Error sending summary: {e}",
                error=str(e),
            )
            return False

    async def generate_confirmation_prompt(self, plan: DailyPlanData) -> str:
        """Generate a natural confirmation question for the user.

        Returns:
            Text for the agent to speak asking the user to confirm the plan.
        """
        system_prompt = PlanGenerationPrompt.system_prompt()
        confirmation_prompt = ConversationPrompt.confirmation_prompt(plan)

        try:
            response_text, _ = await self._call_llm(
                system_prompt, confirmation_prompt, temperature=0.4
            )
            result = self._parse_json_response(response_text)
            return result.get("message", "Does this plan work for you?")
        except Exception:
            return "Does this plan work for you?"

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

            # Trigger the phone call via Vapi
            if self.vapi_adapter and self.recipient_phone:
                # Patch the assistant with today's plan before dialing
                await self.vapi_adapter.configure_assistant(
                    system_prompt=build_system_prompt(speech_text),
                )
                call_start = time.time()
                call_result = await self.vapi_adapter.initiate_call(
                    recipient_phone=self.recipient_phone,
                    run_id=state.run_id,
                )
                call_latency = int((time.time() - call_start) * 1000)
                await self.debug_logger.log_event(
                    agent_name="ConversationAgent",
                    event_type="call_triggered",
                    message=f"Vapi call initiated: {call_result.get('call_id', 'unknown')}",
                    output_payload=call_result,
                    latency_ms=call_latency,
                )

            # If user has already spoken, process it through LLM
            if state.user_input:
                action, response_text = await self.process_user_input(state)

                if trace:
                    trace.span(
                        "process_user_input",
                        input_data={"user_input": state.user_input},
                        output_data={"action": action, "response_length": len(response_text)},
                    )

                await self.debug_logger.log_event(
                    agent_name="ConversationAgent",
                    event_type="user_input_processed",
                    message=f"User action: {action}",
                    input_payload={"user_input": state.user_input},
                    output_payload={"action": action},
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
