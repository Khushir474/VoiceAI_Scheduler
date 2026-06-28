"""Conversation Agent: Manages voice/text interaction with user."""

import time
from app.agents.state import AgentState, DailyPlanData
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer


class ConversationAgent:
    """Conversation Agent: Speaks plan, asks for input, confirms."""

    def __init__(self, debug_logger: DebugLogger, langfuse_tracer: LangfuseTracer | None = None):
        self.debug_logger = debug_logger
        self.langfuse_tracer = langfuse_tracer

    def _format_plan_for_speech(self, plan: DailyPlanData) -> str:
        """Convert plan to natural speech text."""
        lines = []

        # Calendar summary
        if plan.calendar_events:
            lines.append(f"Calendar: {plan.calendar_summary}")
        else:
            lines.append("Calendar: You have no events today.")

        # Weather
        if plan.weather:
            lines.append(f"Weather: {plan.weather_summary}")

        # Commute
        if plan.commute:
            lines.append(f"Commute: {plan.commute_summary}")

        # Workout
        if plan.workout_recommendation:
            lines.append(
                f"Workout: {plan.workout_recommendation.duration_minutes} minutes "
                f"recommended in the {plan.workout_recommendation.recommended_time}."
            )

        # Leave time
        if plan.leave_time:
            lines.append(f"Leave by: {plan.leave_time.strftime('%I:%M %p')}")

        # Carry items
        if plan.carry_items:
            items_str = ", ".join(plan.carry_items)
            lines.append(f"Bring: {items_str}")

        return " ".join(lines)

    async def run(self, state: AgentState) -> AgentState:
        """Execute conversation agent."""
        await self.debug_logger.log_agent_start("ConversationAgent")

        trace = self.langfuse_tracer.trace_agent("ConversationAgent", state.run_id, state.user_id) if self.langfuse_tracer else None

        try:
            if not state.plan:
                raise ValueError("No plan to present")

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

            # In MVP, we just format the text
            # In production, this would:
            # 1. Call Vapi to speak the text
            # 2. Listen for user response
            # 3. Parse response
            # 4. Update plan if needed

            # Mock user input (in real flow, comes from Vapi)
            state.user_input = ""  # User says: "I have a dentist appointment at 2pm"

            # Update transcript
            state.transcript.append({
                "role": "assistant",
                "content": speech_text,
            })

            if state.user_input:
                state.transcript.append({
                    "role": "user",
                    "content": state.user_input,
                })

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
