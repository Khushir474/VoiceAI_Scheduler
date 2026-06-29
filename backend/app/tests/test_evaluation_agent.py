"""Tests for EvaluationAgent — scoring, hallucination detection, and persistence."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.agents.evaluation_agent import EvaluationAgent, EvaluationScores, _PASS_THRESHOLD
from app.agents.state import (
    AgentState,
    DailyPlanData,
    CalendarEvent,
    WeatherData,
    CommuteData,
    WorkoutRecommendation,
)
from app.services.logger import DebugLogger


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def debug_logger():
    logger = MagicMock(spec=DebugLogger)
    logger.log_event = AsyncMock()
    logger.log_agent_start = AsyncMock()
    logger.log_agent_end = AsyncMock()
    return logger


@pytest.fixture
def agent(debug_logger):
    return EvaluationAgent(debug_logger=debug_logger)


@pytest.fixture
def full_plan():
    """Plan with all data sources populated."""
    now = datetime.now(timezone.utc)
    return DailyPlanData(
        calendar_events=[
            CalendarEvent(
                source="google_calendar",
                title="Team standup",
                start_time=now.replace(hour=9, minute=0, second=0, microsecond=0),
                end_time=now.replace(hour=9, minute=30, second=0, microsecond=0),
            )
        ],
        calendar_summary="You have 1 meeting today",
        weather=WeatherData(
            temperature_high=72,
            temperature_low=58,
            condition="sunny",
            humidity=55,
            wind_speed_mph=7,
            precipitation_probability=5,
            sunrise=now.replace(hour=6, minute=30, second=0, microsecond=0),
            sunset=now.replace(hour=19, minute=45, second=0, microsecond=0),
        ),
        weather_summary="Sunny and mild, no jacket needed",
        commute=CommuteData(
            from_address="Home",
            to_address="Office",
            estimated_duration_minutes=30,
            traffic_condition="light",
        ),
        commute_summary="30 minute commute, traffic is light",
        workout_recommendation=WorkoutRecommendation(
            duration_minutes=45,
            recommended_time="morning",
        ),
        leave_time=now.replace(hour=8, minute=15, second=0, microsecond=0),
        carry_items=["laptop", "water bottle"],
        final_summary="Good day ahead. Leave by 8:15 AM for your 9:00 standup.",
    )


@pytest.fixture
def full_state(full_plan):
    state = AgentState(run_id="run_test", user_id="user_test", plan=full_plan)
    state.user_input = "Sounds good, thank you!"
    state.stt_attempts = 1
    state.stt_low_confidence_count = 0
    state.transcript = [
        {"role": "assistant", "content": "Good morning! Here's your plan."},
        {"role": "user", "content": "Sounds good, thank you!"},
    ]
    return state


@pytest.fixture
def empty_state():
    return AgentState(run_id="run_empty", user_id="user_test")


# ─── EvaluationScores ──────────────────────────────────────────────────────────

class TestEvaluationScores:
    def test_compute_overall_averages_dimensions(self):
        s = EvaluationScores()
        s.data_coverage = 1.0
        s.plan_completeness = 0.8
        s.conversation_quality = 0.6
        s.user_engagement = 0.4
        overall = s.compute_overall()
        assert overall == pytest.approx(0.7, abs=0.01)

    def test_compute_overall_caps_at_1(self):
        s = EvaluationScores()
        s.data_coverage = 1.0
        s.plan_completeness = 1.0
        s.conversation_quality = 1.0
        s.user_engagement = 1.0
        assert s.compute_overall() == 1.0

    def test_usefulness_score_is_coverage_completeness_average(self):
        s = EvaluationScores()
        s.data_coverage = 0.8
        s.plan_completeness = 0.6
        s.conversation_quality = 0.5
        s.user_engagement = 0.5
        s.compute_overall()
        assert s.usefulness_score == pytest.approx(0.7, abs=0.01)

    def test_correctness_score_equals_conversation_quality(self):
        s = EvaluationScores()
        s.data_coverage = 0.5
        s.plan_completeness = 0.5
        s.conversation_quality = 0.75
        s.user_engagement = 0.5
        s.compute_overall()
        assert s.correctness_score == pytest.approx(0.75, abs=0.01)

    def test_to_dict_has_all_keys(self):
        s = EvaluationScores()
        s.compute_overall()
        d = s.to_dict()
        for key in ["data_coverage", "plan_completeness", "conversation_quality",
                    "user_engagement", "overall", "usefulness_score", "correctness_score"]:
            assert key in d


# ─── Data coverage scoring ─────────────────────────────────────────────────────

class TestDataCoverage:
    def test_full_coverage_scores_1(self, agent, full_state):
        score, checks = agent._score_data_coverage(full_state)
        assert score == 1.0
        assert all(checks.values())

    def test_no_plan_scores_0(self, agent, empty_state):
        score, checks = agent._score_data_coverage(empty_state)
        assert score == 0.0
        assert checks == {}

    def test_missing_weather_loses_quarter(self, agent, full_state):
        full_state.plan.weather = None
        score, checks = agent._score_data_coverage(full_state)
        assert score == pytest.approx(0.75, abs=0.01)
        assert not checks["has_weather"]

    def test_no_calendar_events_loses_quarter(self, agent, full_state):
        full_state.plan.calendar_events = []
        score, checks = agent._score_data_coverage(full_state)
        assert score == pytest.approx(0.75, abs=0.01)
        assert not checks["has_calendar_events"]

    def test_empty_plan_scores_0(self, agent):
        state = AgentState(run_id="r", user_id="u", plan=DailyPlanData())
        score, _ = agent._score_data_coverage(state)
        assert score == 0.0


# ─── Plan completeness scoring ─────────────────────────────────────────────────

class TestPlanCompleteness:
    def test_full_plan_scores_1(self, agent, full_state):
        score, checks = agent._score_plan_completeness(full_state)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_no_plan_scores_0(self, agent, empty_state):
        score, checks = agent._score_plan_completeness(empty_state)
        assert score == 0.0

    def test_empty_final_summary_penalised(self, agent, full_state):
        full_state.plan.final_summary = ""
        score, checks = agent._score_plan_completeness(full_state)
        assert score < 1.0
        assert not checks["final_summary_filled"]

    def test_trivially_short_summary_penalised(self, agent, full_state):
        full_state.plan.calendar_summary = "ok"  # < 10 chars
        score, checks = agent._score_plan_completeness(full_state)
        assert not checks["calendar_summary_filled"]

    def test_no_leave_time_loses_01(self, agent, full_state):
        full_state.plan.leave_time = None
        score_with, _ = agent._score_plan_completeness(full_state)
        full_state.plan.leave_time = datetime.now(timezone.utc)
        score_without, _ = agent._score_plan_completeness(full_state)
        # leave_time contributes 0.1
        assert abs(score_without - score_with) <= 0.11

    def test_no_carry_items_loses_01(self, agent, full_state):
        full_state.plan.carry_items = []
        score, checks = agent._score_plan_completeness(full_state)
        assert not checks["carry_items_set"]


# ─── Conversation quality scoring ──────────────────────────────────────────────

class TestConversationQuality:
    def test_clean_run_scores_1(self, agent, full_state):
        score, _ = agent._score_conversation_quality(full_state)
        assert score == 1.0

    def test_one_error_deducts_015(self, agent, full_state):
        full_state.error_count = 1
        score, _ = agent._score_conversation_quality(full_state)
        assert score == pytest.approx(0.85, abs=0.01)

    def test_three_errors_deducts_045(self, agent, full_state):
        full_state.error_count = 3
        score, _ = agent._score_conversation_quality(full_state)
        assert score == pytest.approx(0.55, abs=0.01)

    def test_many_errors_capped_at_3(self, agent, full_state):
        full_state.error_count = 10
        score_10, _ = agent._score_conversation_quality(full_state)
        full_state.error_count = 3
        score_3, _ = agent._score_conversation_quality(full_state)
        assert score_10 == score_3

    def test_no_transcript_deducts_03(self, agent, full_state):
        full_state.transcript = []
        score, _ = agent._score_conversation_quality(full_state)
        assert score == pytest.approx(0.70, abs=0.01)

    def test_single_turn_transcript_deducts_02(self, agent, full_state):
        full_state.transcript = [{"role": "assistant", "content": "hi"}]
        score, _ = agent._score_conversation_quality(full_state)
        assert score == pytest.approx(0.80, abs=0.01)

    def test_high_recovery_deducts_01(self, agent, full_state):
        full_state.error_recovery_attempts = 5
        score, _ = agent._score_conversation_quality(full_state)
        assert score == pytest.approx(0.90, abs=0.01)

    def test_score_never_negative(self, agent, full_state):
        full_state.error_count = 100
        full_state.transcript = []
        score, _ = agent._score_conversation_quality(full_state)
        assert score >= 0.0


# ─── User engagement scoring ───────────────────────────────────────────────────

class TestUserEngagement:
    def test_full_engagement_scores_1(self, agent, full_state):
        score, _ = agent._score_user_engagement(full_state)
        assert score == 1.0

    def test_no_user_input_loses_05(self, agent, full_state):
        full_state.user_input = ""
        score, _ = agent._score_user_engagement(full_state)
        assert score <= 0.5

    def test_no_user_turn_in_transcript_loses_03(self, agent, full_state):
        full_state.transcript = [{"role": "assistant", "content": "Good morning!"}]
        score, _ = agent._score_user_engagement(full_state)
        assert score <= 0.70

    def test_stt_low_confidence_loses_02(self, agent, full_state):
        """Having STT attempts but low confidence means no 0.2 bonus → 0.8 total."""
        full_state.stt_attempts = 3
        full_state.stt_low_confidence_count = 2
        score, _ = agent._score_user_engagement(full_state)
        assert score == pytest.approx(0.80, abs=0.01)

    def test_no_engagement_at_all_scores_0(self, agent, empty_state):
        """No user input, no transcript, no STT attempts → 0.0 (STT bonus requires attempts)."""
        score, _ = agent._score_user_engagement(empty_state)
        assert score == 0.0

    def test_stt_bonus_requires_actual_attempts(self, agent, empty_state):
        """Zero STT failures when there were no attempts should not award the 0.2 bonus."""
        empty_state.stt_low_confidence_count = 0
        empty_state.stt_attempts = 0
        score, _ = agent._score_user_engagement(empty_state)
        assert score == 0.0


# ─── Hallucination detection ───────────────────────────────────────────────────

class TestHallucinationDetection:
    def test_clean_plan_no_hallucinations(self, agent, full_state):
        found = agent._detect_hallucinations(full_state)
        assert found == []

    def test_detects_ai_filler_phrase(self, agent, full_state):
        full_state.plan.final_summary = "As an AI I cannot guarantee the weather."
        found = agent._detect_hallucinations(full_state)
        assert any("AI self-referential" in f for f in found)

    def test_detects_placeholder_text(self, agent, full_state):
        full_state.plan.calendar_summary = "You have [INSERT_EVENTS] today"
        found = agent._detect_hallucinations(full_state)
        assert any("Placeholder" in f for f in found)

    def test_detects_todo_text(self, agent, full_state):
        full_state.plan.weather_summary = "TODO: add weather info"
        found = agent._detect_hallucinations(full_state)
        assert any("Placeholder" in f for f in found)

    def test_detects_previous_day_leave_time(self, agent, full_state):
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        full_state.plan.leave_time = yesterday.replace(hour=8, minute=0)
        found = agent._detect_hallucinations(full_state)
        assert any("previous day" in f for f in found)

    def test_detects_midnight_leave_time(self, agent, full_state):
        full_state.plan.leave_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0
        )
        found = agent._detect_hallucinations(full_state)
        assert any("midnight" in f for f in found)

    def test_detects_suspiciously_short_final_summary(self, agent, full_state):
        full_state.plan.final_summary = "ok"
        found = agent._detect_hallucinations(full_state)
        assert any("suspiciously short" in f for f in found)

    def test_no_plan_returns_empty(self, agent, empty_state):
        found = agent._detect_hallucinations(empty_state)
        assert found == []


# ─── Issue collection ──────────────────────────────────────────────────────────

class TestIssueCollection:
    def test_clean_run_no_issues(self, agent, full_state):
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert issues == []

    def test_missing_calendar_flagged(self, agent, full_state):
        full_state.plan.calendar_events = []
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert any("calendar" in i.lower() for i in issues)

    def test_missing_weather_flagged(self, agent, full_state):
        full_state.plan.weather = None
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert any("weather" in i.lower() for i in issues)

    def test_agent_error_flagged(self, agent, full_state):
        full_state.error = "LLM timeout"
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert any("LLM timeout" in i for i in issues)

    def test_empty_transcript_flagged(self, agent, full_state):
        full_state.transcript = []
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert any("transcript" in i.lower() for i in issues)

    def test_high_recovery_attempts_flagged(self, agent, full_state):
        full_state.error_recovery_attempts = 4
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert any("recovery" in i.lower() or "unstable" in i.lower() for i in issues)

    def test_stt_failures_flagged(self, agent, full_state):
        full_state.stt_low_confidence_count = 3
        _, coverage = agent._score_data_coverage(full_state)
        _, completeness = agent._score_plan_completeness(full_state)
        issues = agent._collect_issues(full_state, coverage, completeness)
        assert any("STT" in i for i in issues)


# ─── run() integration ─────────────────────────────────────────────────────────

class TestEvaluationAgentRun:
    @pytest.mark.asyncio
    async def test_run_full_state_passes(self, agent, full_state, debug_logger):
        result = await agent.run(full_state)

        assert result.evaluation_score is not None
        assert result.evaluation_score >= _PASS_THRESHOLD
        assert result.debug_summary["pass_fail"] is True
        debug_logger.log_agent_end.assert_called_with("EvaluationAgent", success=True)

    @pytest.mark.asyncio
    async def test_run_empty_state_fails(self, agent, empty_state):
        result = await agent.run(empty_state)

        assert result.evaluation_score is not None
        assert result.evaluation_score < _PASS_THRESHOLD
        assert result.debug_summary["pass_fail"] is False

    @pytest.mark.asyncio
    async def test_run_populates_debug_summary(self, agent, full_state):
        result = await agent.run(full_state)

        summary = result.debug_summary
        for key in ["scores", "pass_fail", "hallucinations", "issues",
                    "coverage_checks", "completeness_checks"]:
            assert key in summary

    @pytest.mark.asyncio
    async def test_run_sets_hallucinations_detected(self, agent, full_state):
        full_state.plan.final_summary = "As an AI I suggest this plan."
        result = await agent.run(full_state)

        assert len(result.hallucinations_detected) > 0

    @pytest.mark.asyncio
    async def test_run_no_plan_still_completes(self, agent, empty_state, debug_logger):
        result = await agent.run(empty_state)

        assert result.evaluation_score is not None
        assert result.error is None
        debug_logger.log_agent_end.assert_called_with("EvaluationAgent", success=True)

    @pytest.mark.asyncio
    async def test_run_persists_to_supabase(self, debug_logger, full_state):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute = AsyncMock()

        agent = EvaluationAgent(debug_logger=debug_logger, supabase_client=mock_supabase)
        await agent.run(full_state)

        mock_supabase.table.assert_called_with("evaluation_scores")
        mock_supabase.table.return_value.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_skips_supabase_when_not_configured(self, agent, full_state):
        """No supabase client — should still succeed without error."""
        assert agent.supabase is None
        result = await agent.run(full_state)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_run_supabase_error_does_not_crash(self, debug_logger, full_state):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute = AsyncMock(
            side_effect=Exception("DB unavailable")
        )

        agent = EvaluationAgent(debug_logger=debug_logger, supabase_client=mock_supabase)
        result = await agent.run(full_state)

        assert result.error is None  # persist failure should not propagate

    @pytest.mark.asyncio
    async def test_run_scores_dict_has_correct_keys(self, agent, full_state):
        result = await agent.run(full_state)
        scores = result.debug_summary["scores"]
        for key in ["data_coverage", "plan_completeness", "conversation_quality",
                    "user_engagement", "overall"]:
            assert key in scores
            assert 0.0 <= scores[key] <= 1.0

    @pytest.mark.asyncio
    async def test_run_with_errors_lowers_score(self, agent, full_state):
        result_clean = await agent.run(full_state)
        clean_score = result_clean.evaluation_score

        full_state.error_count = 3
        full_state.error_recovery_attempts = 5
        full_state.transcript = []
        result_dirty = await agent.run(full_state)

        assert result_dirty.evaluation_score < clean_score
