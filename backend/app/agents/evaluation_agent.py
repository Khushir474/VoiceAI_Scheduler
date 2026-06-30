"""Evaluation & Debug Agent: Scores run quality and flags issues.

Scoring dimensions (each 0.0–1.0, equally weighted):
  1. data_coverage      — did we fetch calendar, weather, commute, workout?
  2. plan_completeness  — are summaries filled in and non-trivial?
  3. conversation_quality — clean conversation (low errors, transcript exists)
  4. user_engagement    — did the user respond and was their input processed?

Overall score = average of four dimensions, capped at 1.0.
A run passes (pass_fail=True) when overall >= 0.6.

Scores are persisted to the `evaluation_scores` Supabase table.
"""

import re
import time
from datetime import datetime
from typing import Optional

from app.agents.state import AgentState
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer, observe, propagate_attributes


# Patterns that indicate placeholder or AI-generated filler in plan text
_PLACEHOLDER_PATTERNS = re.compile(
    r"\[INSERT|TODO|PLACEHOLDER|lorem ipsum|<YOUR|N/A\b",
    re.IGNORECASE,
)
_AI_FILLER_PATTERNS = re.compile(
    r"\bAI-generated\b|\bas an AI\b|\bI cannot\b|\bI'm an AI\b",
    re.IGNORECASE,
)

# Minimum character count for a summary to be considered non-trivial
_MIN_SUMMARY_CHARS = 10

# Score threshold for pass/fail
_PASS_THRESHOLD = 0.6


class EvaluationScores:
    """Container for all evaluation dimension scores."""

    def __init__(self):
        self.data_coverage: float = 0.0
        self.plan_completeness: float = 0.0
        self.conversation_quality: float = 0.0
        self.user_engagement: float = 0.0
        self.overall: float = 0.0

        # Maps to DB columns
        self.usefulness_score: float = 0.0    # data_coverage + plan_completeness
        self.correctness_score: float = 0.0   # conversation_quality (low errors)

    def compute_overall(self) -> float:
        dims = [
            self.data_coverage,
            self.plan_completeness,
            self.conversation_quality,
            self.user_engagement,
        ]
        self.overall = min(1.0, sum(dims) / len(dims))
        self.usefulness_score = min(1.0, (self.data_coverage + self.plan_completeness) / 2)
        self.correctness_score = self.conversation_quality
        return self.overall

    def to_dict(self) -> dict:
        return {
            "data_coverage": round(self.data_coverage, 3),
            "plan_completeness": round(self.plan_completeness, 3),
            "conversation_quality": round(self.conversation_quality, 3),
            "user_engagement": round(self.user_engagement, 3),
            "overall": round(self.overall, 3),
            "usefulness_score": round(self.usefulness_score, 3),
            "correctness_score": round(self.correctness_score, 3),
        }


class EvaluationAgent:
    """Evaluation & Debug Agent: Quality checks, scoring, and persistence."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        langfuse_tracer: Optional[LangfuseTracer] = None,
        supabase_client=None,
    ):
        self.debug_logger = debug_logger
        self.langfuse_tracer = langfuse_tracer
        self.supabase = supabase_client

    # ─── Dimension scorers ────────────────────────────────────────────────────

    def _score_data_coverage(self, state: AgentState) -> tuple[float, dict]:
        """Score whether all data sources were successfully fetched.

        Each of 4 sources is worth 0.25 points.
        Returns (score, breakdown_dict).
        """
        if not state.plan:
            return 0.0, {}

        checks = {
            "has_calendar_events": len(state.plan.calendar_events) > 0,
            "has_weather": state.plan.weather is not None,
            "has_commute": state.plan.commute is not None,
            "has_workout_recommendation": state.plan.workout_recommendation is not None,
        }
        score = sum(checks.values()) / len(checks)
        return score, checks

    def _score_plan_completeness(self, state: AgentState) -> tuple[float, dict]:
        """Score how complete and substantive the plan text is.

        Checks:
          - calendar_summary non-trivial      0.2
          - weather_summary non-trivial       0.2
          - commute_summary non-trivial       0.2
          - final_summary non-trivial         0.2
          - leave_time set                    0.1
          - carry_items non-empty             0.1
        """
        if not state.plan:
            return 0.0, {}

        plan = state.plan

        def _non_trivial(text: str) -> bool:
            return bool(text) and len(text.strip()) >= _MIN_SUMMARY_CHARS

        checks = {
            "calendar_summary_filled": _non_trivial(plan.calendar_summary),
            "weather_summary_filled": _non_trivial(plan.weather_summary),
            "commute_summary_filled": _non_trivial(plan.commute_summary),
            "final_summary_filled": _non_trivial(plan.final_summary),
            "leave_time_set": plan.leave_time is not None,
            "carry_items_set": len(plan.carry_items) > 0,
        }
        weights = {
            "calendar_summary_filled": 0.2,
            "weather_summary_filled": 0.2,
            "commute_summary_filled": 0.2,
            "final_summary_filled": 0.2,
            "leave_time_set": 0.1,
            "carry_items_set": 0.1,
        }
        score = sum(weights[k] for k, v in checks.items() if v)
        return score, checks

    def _score_conversation_quality(self, state: AgentState) -> tuple[float, dict]:
        """Score conversation cleanliness and error rate.

        Starts at 1.0 and deducts for:
          - Each error in state.error_count          -0.15 each (max -0.45)
          - High error_recovery_attempts (>2)        -0.1
          - Very short transcript (<2 turns)         -0.2
          - No transcript at all                     -0.3
        """
        score = 1.0
        details = {
            "error_count": state.error_count,
            "error_recovery_attempts": state.error_recovery_attempts,
            "transcript_turns": len(state.transcript),
            "has_error": state.error is not None,
        }

        # Penalise errors (cap at 3)
        error_penalty = min(state.error_count, 3) * 0.15
        score -= error_penalty

        # Penalise many recovery attempts
        if state.error_recovery_attempts > 2:
            score -= 0.10

        # Penalise thin transcript
        if len(state.transcript) == 0:
            score -= 0.30
        elif len(state.transcript) < 2:
            score -= 0.20

        score = max(0.0, score)
        return score, details

    def _score_user_engagement(self, state: AgentState) -> tuple[float, dict]:
        """Score whether the user responded and input was processed.

        Points:
          - User provided input                    0.5
          - Input appears in transcript as "user"  0.3
          - No STT failures (low_confidence==0)    0.2
        """
        score = 0.0
        details = {
            "has_user_input": bool(state.user_input),
            "user_turn_in_transcript": any(
                t.get("role") == "user" for t in state.transcript
            ),
            "stt_low_confidence_count": state.stt_low_confidence_count,
            "stt_attempts": state.stt_attempts,
        }

        if details["has_user_input"]:
            score += 0.50
        if details["user_turn_in_transcript"]:
            score += 0.30
        if state.stt_attempts > 0 and state.stt_low_confidence_count == 0:
            score += 0.20

        return score, details

    # ─── Hallucination detection ───────────────────────────────────────────────

    def _detect_hallucinations(self, state: AgentState) -> list[str]:
        """Flag suspicious content in the generated plan.

        Checks:
          - AI-generated phrasing ("as an AI", "I cannot", etc.)
          - Placeholder text ([INSERT_X], TODO, etc.)
          - Impossible leave time (in the past or midnight)
          - Final summary is suspiciously short (<10 chars) yet marked complete
        """
        found: list[str] = []

        if not state.plan:
            return found

        plan = state.plan
        all_text = " ".join(filter(None, [
            plan.calendar_summary,
            plan.weather_summary,
            plan.commute_summary,
            plan.final_summary,
        ]))

        if _AI_FILLER_PATTERNS.search(all_text):
            found.append("AI self-referential phrasing detected in plan text")

        if _PLACEHOLDER_PATTERNS.search(all_text):
            found.append("Placeholder or TODO text detected in plan summaries")

        # Suspicious leave time — flag only if it's from a previous day, not just
        # earlier today (morning plans running past their leave time are expected)
        if plan.leave_time:
            now = datetime.utcnow()
            leave_naive = plan.leave_time.replace(tzinfo=None)
            if leave_naive.date() < now.date():
                found.append(
                    f"Leave time {plan.leave_time.isoformat()} is from a previous day"
                )
            if plan.leave_time.hour == 0 and plan.leave_time.minute == 0:
                found.append("Leave time is exactly midnight — likely a placeholder")

        # Final summary present but content-free
        if plan.final_summary and len(plan.final_summary.strip()) < _MIN_SUMMARY_CHARS:
            found.append("final_summary is present but suspiciously short")

        return found

    # ─── Issue collection ─────────────────────────────────────────────────────

    def _collect_issues(
        self,
        state: AgentState,
        coverage_checks: dict,
        completeness_checks: dict,
    ) -> list[str]:
        """Collect human-readable issue descriptions for the debug summary."""
        issues: list[str] = []

        # Data coverage gaps
        if not coverage_checks.get("has_calendar_events"):
            issues.append("No calendar events fetched — calendar adapter may have failed")
        if not coverage_checks.get("has_weather"):
            issues.append("Weather data missing — weather adapter may have failed")
        if not coverage_checks.get("has_commute"):
            issues.append("Commute data missing — maps adapter may have failed")
        if not coverage_checks.get("has_workout_recommendation"):
            issues.append("No workout recommendation generated")

        # Plan completeness gaps
        if not completeness_checks.get("final_summary_filled"):
            issues.append("final_summary is empty or too short")
        if not completeness_checks.get("leave_time_set"):
            issues.append("No leave time calculated")

        # Runtime errors
        if state.error:
            issues.append(f"Agent error: {state.error}")
        if state.error_count > 0:
            issues.append(f"{state.error_count} error(s) occurred during run")
        if state.error_recovery_attempts > 2:
            issues.append(
                f"High recovery attempts ({state.error_recovery_attempts}) — "
                "call may have been unstable"
            )

        # Conversation gaps
        if not state.transcript:
            issues.append("No transcript recorded")
        if state.stt_low_confidence_count > 1:
            issues.append(
                f"STT low-confidence ({state.stt_low_confidence_count}x) — "
                "audio quality may be poor"
            )

        return issues

    # ─── Persistence ──────────────────────────────────────────────────────────

    async def _persist_scores(
        self,
        state: AgentState,
        scores: EvaluationScores,
        hallucinations: list[str],
        debug_summary: dict,
    ) -> None:
        """Write evaluation results to the evaluation_scores table."""
        if not self.supabase:
            return

        try:
            row = {
                "run_id": state.run_id,
                "user_id": state.user_id,
                "usefulness_score": round(scores.usefulness_score, 2),
                "correctness_score": round(scores.correctness_score, 2),
                "hallucination_detected": len(hallucinations) > 0,
                "hallucination_details": "; ".join(hallucinations) if hallucinations else None,
                "overall_score": round(scores.overall, 2),
                "debug_summary": debug_summary,
            }
            await self.supabase.table("evaluation_scores").insert(row).execute()
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="EvaluationAgent",
                event_type="persist_error",
                level="warning",
                message=f"Failed to persist evaluation scores: {e}",
                error=str(e),
            )

    # ─── Main entry point ─────────────────────────────────────────────────────

    @observe(name="evaluation-agent", capture_input=False, capture_output=False)
    async def run(self, state: AgentState) -> AgentState:
        """Execute evaluation: score, flag issues, persist, update state."""
        await self.debug_logger.log_agent_start("EvaluationAgent")

        with propagate_attributes(user_id=state.user_id, session_id=state.run_id):
            return await self._run_inner(state)

    async def _run_inner(self, state: AgentState) -> AgentState:
        try:
            scores = EvaluationScores()

            # --- Data coverage ---
            scores.data_coverage, coverage_checks = self._score_data_coverage(state)

            # --- Plan completeness ---
            scores.plan_completeness, completeness_checks = self._score_plan_completeness(state)

            # --- Conversation quality ---
            scores.conversation_quality, quality_details = self._score_conversation_quality(state)

            # --- User engagement ---
            scores.user_engagement, engagement_details = self._score_user_engagement(state)

            # --- Aggregate ---
            overall = scores.compute_overall()

            # --- Hallucinations ---
            hallucinations = self._detect_hallucinations(state)
            state.hallucinations_detected = hallucinations

            # --- Issues ---
            issues = self._collect_issues(state, coverage_checks, completeness_checks)

            # --- Build debug summary ---
            debug_summary = {
                "scores": scores.to_dict(),
                "pass_fail": overall >= _PASS_THRESHOLD,
                "pass_threshold": _PASS_THRESHOLD,
                "hallucinations": hallucinations,
                "issues": issues,
                "coverage_checks": coverage_checks,
                "completeness_checks": completeness_checks,
                "conversation_details": quality_details,
                "engagement_details": engagement_details,
                "transcript_turns": len(state.transcript),
            }
            state.debug_summary = debug_summary
            state.evaluation_score = overall

            # --- Persist to Supabase ---
            await self._persist_scores(state, scores, hallucinations, debug_summary)

            await self.debug_logger.log_event(
                agent_name="EvaluationAgent",
                event_type="evaluation_complete",
                message=(
                    f"Score: {overall:.2f} ({'PASS' if overall >= _PASS_THRESHOLD else 'FAIL'}), "
                    f"issues: {len(issues)}, hallucinations: {len(hallucinations)}"
                ),
                output_payload=debug_summary,
            )

            await self.debug_logger.log_agent_end("EvaluationAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="EvaluationAgent",
                event_type="error",
                level="error",
                message=f"Evaluation error: {e}",
                error=str(e),
            )
            await self.debug_logger.log_agent_end("EvaluationAgent", success=False)
            state.error = str(e)

        return state
