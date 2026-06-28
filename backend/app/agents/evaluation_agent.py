"""Evaluation & Debug Agent: Scores run and flags issues."""

import time
from app.agents.state import AgentState
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer


class EvaluationAgent:
    """Evaluation & Debug Agent: Quality checks and scoring."""

    def __init__(self, debug_logger: DebugLogger, langfuse_tracer: LangfuseTracer | None = None):
        self.debug_logger = debug_logger
        self.langfuse_tracer = langfuse_tracer

    async def _check_tool_usage(self, state: AgentState) -> dict:
        """Check if tools were actually used in the plan."""
        checks = {
            "has_calendar_events": len(state.plan.calendar_events) > 0 if state.plan else False,
            "has_weather": state.plan and state.plan.weather is not None,
            "has_commute": state.plan and state.plan.commute is not None,
            "has_workout_rec": state.plan and state.plan.workout_recommendation is not None,
        }
        return checks

    async def _detect_hallucinations(self, state: AgentState) -> list[str]:
        """Flag suspicious or contradictory statements in plan."""
        hallucinations = []

        if state.plan:
            # Check for logical inconsistencies
            if state.plan.leave_time and state.plan.commute:
                # In real impl: verify leave time makes sense given commute
                pass

            # Check for unsupported claims
            if "AI-generated" in state.plan.final_summary:
                hallucinations.append("Detected AI-generated phrasing in summary")

        return hallucinations

    async def _calculate_score(self, state: AgentState, tool_checks: dict) -> float:
        """Calculate overall usefulness score (0-1)."""
        score = 0.5  # Base score

        # Boost for having calendar events
        if tool_checks["has_calendar_events"]:
            score += 0.1

        # Boost for having weather
        if tool_checks["has_weather"]:
            score += 0.1

        # Boost for having commute
        if tool_checks["has_commute"]:
            score += 0.1

        # Boost for having workout recommendation
        if tool_checks["has_workout_rec"]:
            score += 0.1

        # Boost for having user input
        if state.user_input:
            score += 0.1

        return min(score, 1.0)

    async def run(self, state: AgentState) -> AgentState:
        """Execute evaluation agent."""
        await self.debug_logger.log_agent_start("EvaluationAgent")

        trace = self.langfuse_tracer.trace_agent("EvaluationAgent", state.run_id, state.user_id) if self.langfuse_tracer else None

        try:
            # Check tool usage
            start_time = time.time()
            tool_checks = await self._check_tool_usage(state)
            checks_latency = int((time.time() - start_time) * 1000)

            if trace:
                trace.span(
                    "check_tool_usage",
                    output_data=tool_checks,
                    latency_ms=checks_latency,
                )

            # Detect hallucinations
            start_time = time.time()
            hallucinations = await self._detect_hallucinations(state)
            hallucin_latency = int((time.time() - start_time) * 1000)
            state.hallucinations_detected = hallucinations

            if trace:
                trace.span(
                    "detect_hallucinations",
                    output_data={"count": len(hallucinations)},
                    latency_ms=hallucin_latency,
                )

            # Calculate score
            start_time = time.time()
            score = await self._calculate_score(state, tool_checks)
            score_latency = int((time.time() - start_time) * 1000)
            state.evaluation_score = score

            if trace:
                trace.span(
                    "calculate_score",
                    output_data={"score": score},
                    latency_ms=score_latency,
                )

            # Build debug summary
            debug_summary = {
                "tool_checks": tool_checks,
                "hallucinations_detected": len(hallucinations),
                "hallucinations": hallucinations,
                "usefulness_score": score,
                "plan_sections": {
                    "has_calendar_summary": bool(state.plan and state.plan.calendar_summary),
                    "has_weather_summary": bool(state.plan and state.plan.weather_summary),
                    "has_commute_summary": bool(state.plan and state.plan.commute_summary),
                    "has_final_summary": bool(state.plan and state.plan.final_summary),
                },
                "transcript_length": len(state.transcript),
            }
            state.debug_summary = debug_summary

            await self.debug_logger.log_event(
                agent_name="EvaluationAgent",
                event_type="evaluation_complete",
                message=f"Run evaluated. Score: {score:.2f}, Hallucinations: {len(hallucinations)}",
                output_payload=debug_summary,
            )

            if trace:
                trace.end(output_data=debug_summary)

            await self.debug_logger.log_agent_end("EvaluationAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="EvaluationAgent",
                event_type="error",
                level="error",
                message=f"Evaluation error: {str(e)}",
                error=str(e),
            )

            if trace:
                trace.end(error=str(e))

            await self.debug_logger.log_agent_end("EvaluationAgent", success=False)
            state.error = str(e)

        return state
