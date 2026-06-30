"""Conversation Agent: Manages voice/text interaction with user using LLM."""

import asyncio
import json
import time
from typing import Any
from datetime import datetime

from anthropic import Anthropic, APITimeoutError, APIError
from openai import AsyncOpenAI, APITimeoutError as OpenAITimeoutError

from app.agents.state import AgentState, DailyPlanData, WorkoutRecommendation
from app.agents.prompts import PlanGenerationPrompt, ConversationPrompt, PostCallSummaryPrompt
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer, observe, propagate_attributes
from app.config import get_settings

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.adapters.voice.vapi import VapiAdapter
    from app.adapters.messaging.base import MessageAdapter
    from app.adapters.calendar.base import CalendarAdapter

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

    @observe(name="llm-claude", as_type="generation", capture_input=False, capture_output=False)
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

    @observe(name="llm-openai", as_type="generation", capture_input=False, capture_output=False)
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

        response_text, latency_ms = await self._call_llm(system_prompt, user_prompt, temperature=0.5)

        # Parse response
        plan_data = self._parse_json_response(response_text)

        await self.debug_logger.log_event(
            agent_name="ConversationAgent",
            event_type="llm_plan_generation",
            message="Plan generated via LLM",
            output_payload={"latency_ms": latency_ms, "response_length": len(response_text)},
            latency_ms=latency_ms,
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

        # Capture ad-hoc events so the webhook handler can write them to the calendar (DOPS-8)
        if action == "add_event":
            new_event_dict = result.get("new_event") or {}
            if new_event_dict.get("title"):
                state.ad_hoc_events.append(new_event_dict)

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

    async def create_calendar_events_from_state(
        self,
        state: AgentState,
        calendar_adapters: "list[CalendarAdapter]",
    ) -> "list[CalendarEvent]":
        """Create all ad-hoc events captured during the call in each configured adapter.

        For each raw event dict in state.ad_hoc_events, attempts creation on every
        adapter that reports is_configured(). Successfully created events are appended
        to state.plan.calendar_events so the post-call summary reflects them.

        Returns:
            List of CalendarEvent objects that were successfully created.
        """
        from app.agents.state import CalendarEvent as _CalendarEvent

        created: list[_CalendarEvent] = []

        for raw in state.ad_hoc_events:
            title = raw.get("title")
            if not title:
                continue

            # Parse times; default end = start + 1h
            start_time = None
            end_time = None
            try:
                if raw.get("start_time"):
                    start_time = datetime.fromisoformat(raw["start_time"])
                if raw.get("end_time"):
                    end_time = datetime.fromisoformat(raw["end_time"])
            except (ValueError, TypeError):
                pass

            if not start_time:
                await self.debug_logger.log_event(
                    agent_name="ConversationAgent",
                    event_type="calendar_event_skipped",
                    level="warning",
                    message=f"Skipping ad-hoc event '{title}': no parseable start_time",
                    input_payload=raw,
                )
                continue

            if not end_time:
                from datetime import timedelta as _td
                end_time = start_time + _td(hours=1)

            for adapter in calendar_adapters:
                source = "google_calendar" if "google" in type(adapter).__name__.lower() else "apple_ical"
                event_to_create = _CalendarEvent(
                    source=source,
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    location=raw.get("location"),
                )

                t0 = time.time()
                try:
                    if not await adapter.is_configured(state.user_id):
                        continue
                    result_event = await adapter.create_event(state.user_id, event_to_create)
                    latency_ms = int((time.time() - t0) * 1000)

                    if result_event:
                        created.append(result_event)
                        if state.plan:
                            state.plan.calendar_events.append(result_event)
                        await self.debug_logger.log_event(
                            agent_name="ConversationAgent",
                            event_type="calendar_event_created",
                            message=f"Created '{title}' via {type(adapter).__name__}",
                            output_payload={"title": title, "external_id": result_event.external_id,
                                            "adapter": type(adapter).__name__},
                            latency_ms=latency_ms,
                        )
                    else:
                        await self.debug_logger.log_event(
                            agent_name="ConversationAgent",
                            event_type="calendar_event_create_failed",
                            level="error",
                            message=f"Failed to create '{title}' via {type(adapter).__name__}",
                            input_payload=raw,
                            latency_ms=latency_ms,
                        )
                except Exception as e:
                    await self.debug_logger.log_event(
                        agent_name="ConversationAgent",
                        event_type="calendar_event_create_error",
                        level="error",
                        message=f"Exception creating '{title}' via {type(adapter).__name__}: {e}",
                        error=str(e),
                    )

        return created

    async def generate_post_call_summary(self, state: AgentState) -> str:
        """Generate a rich post-call summary from the full call context via LLM.

        Reads the complete transcript plus the original pre-call plan data so that
        user corrections and ad-hoc events mentioned during the call are reflected.
        Sets state.post_call_summary and overwrites state.plan.final_summary so that
        a subsequent send_summary() call will use this generated text.

        Returns:
            Generated summary text.
        """
        system_prompt = PostCallSummaryPrompt.system_prompt()
        user_prompt = PostCallSummaryPrompt.generate_summary_prompt(state)

        start_time = time.time()
        try:
            summary_text, _ = await self._call_llm(system_prompt, user_prompt, temperature=0.4)
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="post_call_summary_error",
                level="error",
                message=f"Failed to generate post-call summary via LLM: {e}",
                error=str(e),
            )
            # Fall back to pre-call plan summary so something still gets sent
            summary_text = (state.plan.final_summary if state.plan and state.plan.final_summary
                            else "Your daily summary is ready. Have a great day!")

        latency_ms = int((time.time() - start_time) * 1000)

        state.post_call_summary = summary_text
        if state.plan:
            state.plan.final_summary = summary_text

        await self.debug_logger.log_event(
            agent_name="ConversationAgent",
            event_type="post_call_summary_generated",
            message="Post-call summary generated",
            output_payload={
                "summary_length": len(summary_text),
                "transcript_turns": len(state.transcript),
                "latency_ms": latency_ms,
            },
            latency_ms=latency_ms,
        )

        return summary_text

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

    @observe(name="conversation-agent", capture_input=False, capture_output=False)
    async def run(self, state: AgentState) -> AgentState:
        """Execute conversation agent with LLM-powered plan generation."""
        await self.debug_logger.log_agent_start("ConversationAgent")

        with propagate_attributes(user_id=state.user_id, session_id=state.run_id):
            return await self._run_inner(state)

    async def _run_inner(self, state: AgentState) -> AgentState:
        try:
            if not state.plan:
                raise ValueError("No plan to present")

            # Generate plan using LLM
            plan_data = await self._generate_plan_with_llm(state)

            # Update state.plan with LLM-generated data
            self._update_plan_from_llm_response(state, plan_data)

            # Format plan for speech
            speech_text = self._format_plan_for_speech(state.plan)

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
                # Patch the assistant with static persona + live-fetch tool
                tool_url = getattr(self.settings, "vapi_tool_server_url", None)
                await self.vapi_adapter.configure_assistant(
                    system_prompt=build_system_prompt(),
                    server_tool_url=tool_url,
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

                await self.debug_logger.log_event(
                    agent_name="ConversationAgent",
                    event_type="user_input_processed",
                    message=f"User action: {action}",
                    input_payload={"user_input": state.user_input},
                    output_payload={"action": action},
                )

            await self.debug_logger.log_agent_end("ConversationAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="ConversationAgent",
                event_type="error",
                level="error",
                message=f"Conversation error: {str(e)}",
                error=str(e),
            )
            await self.debug_logger.log_agent_end("ConversationAgent", success=False)
            state.error = str(e)

        return state
