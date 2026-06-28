"""Evaluation & Debug Agent: Scores run and flags issues."""

from app.agents.state import AgentState
from app.services.logger import DebugLogger


class EvaluationAgent:
    """Evaluation & Debug Agent: Quality checks and scoring."""

    def __init__(self, debug_logger: DebugLogger):
        self.debug_logger = debug_logger

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

        try:
            # Check tool usage
            tool_checks = await self._check_tool_usage(state)

            # Detect hallucinations
            hallucinations = await self._detect_hallucinations(state)
            state.hallucinations_detected = hallucinations

            # Calculate score
            score = await self._calculate_score(state, tool_checks)
            state.evaluation_score = score

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

            await self.debug_logger.log_agent_end("EvaluationAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="EvaluationAgent",
                event_type="error",
                level="error",
                message=f"Evaluation error: {str(e)}",
                error=str(e),
            )
            await self.debug_logger.log_agent_end("EvaluationAgent", success=False)
            state.error = str(e)

        return state
