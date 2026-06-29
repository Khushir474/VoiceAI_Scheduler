"""Integration tests for the full planning flow (planning + conversation + evaluation)."""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.planning_agent import PlanningAgent
from app.agents.conversation_agent import ConversationAgent
from app.agents.evaluation_agent import EvaluationAgent
from app.agents.state import (
    AgentState,
    CalendarEvent,
    WeatherData,
    CommuteData,
)
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer
from app.adapters.calendar.base import CalendarAdapter
from app.adapters.weather import WeatherAdapter
from app.adapters.maps import MapsAdapter


@pytest.fixture
def mock_debug_logger(mocker):
    """Mock debug logger."""
    logger = mocker.MagicMock(spec=DebugLogger)
    logger.log_agent_start = AsyncMock()
    logger.log_agent_end = AsyncMock()
    logger.log_event = AsyncMock()
    logger.log_tool_call = AsyncMock()
    return logger


@pytest.fixture
def mock_langfuse_tracer(mocker):
    """Mock Langfuse tracer."""
    tracer = mocker.MagicMock(spec=LangfuseTracer)
    trace = mocker.MagicMock()
    trace.span = mocker.MagicMock(return_value=trace)
    trace.end = mocker.MagicMock()
    tracer.trace_agent = mocker.MagicMock(return_value=trace)
    tracer.trace_llm_call = mocker.MagicMock(return_value=trace)
    tracer.flush = mocker.MagicMock()
    return tracer


@pytest.fixture
def mock_calendar_adapter(mocker):
    """Mock calendar adapter."""
    adapter = mocker.MagicMock(spec=CalendarAdapter)
    adapter.is_configured = AsyncMock(return_value=True)

    now = datetime.now(timezone.utc)
    adapter.get_events_for_date = AsyncMock(
        return_value=[
            CalendarEvent(
                source="google_calendar",
                external_id="event1",
                title="Team Standup",
                start_time=now.replace(hour=9, minute=0, second=0, microsecond=0),
                end_time=now.replace(hour=9, minute=30, second=0, microsecond=0),
                location="Conference Room A",
                attendees=["alice@example.com", "bob@example.com"],
            ),
        ]
    )
    return adapter


@pytest.fixture
def mock_weather_adapter(mocker):
    """Mock weather adapter."""
    adapter = mocker.MagicMock(spec=WeatherAdapter)
    now = datetime.now(timezone.utc)
    adapter.get_weather = AsyncMock(
        return_value=WeatherData(
            temperature_high=72,
            temperature_low=62,
            condition="partly_cloudy",
            humidity=65,
            wind_speed_mph=10,
            precipitation_probability=20,
            sunrise=now.replace(hour=6, minute=30, second=0, microsecond=0),
            sunset=now.replace(hour=19, minute=45, second=0, microsecond=0),
        )
    )
    return adapter


@pytest.fixture
def mock_maps_adapter(mocker):
    """Mock maps adapter."""
    adapter = mocker.MagicMock(spec=MapsAdapter)
    adapter.get_commute = AsyncMock(
        return_value=CommuteData(
            from_address="123 Main St, New York, NY",
            to_address="456 Work Ave, New York, NY",
            estimated_duration_minutes=45,
            traffic_condition="moderate",
        )
    )
    return adapter


@pytest.fixture
def planning_agent(mock_debug_logger, mock_calendar_adapter, mock_weather_adapter, mock_maps_adapter):
    """Create planning agent with mocked dependencies."""
    return PlanningAgent(
        debug_logger=mock_debug_logger,
        calendar_adapters=[mock_calendar_adapter],
        weather_adapter=mock_weather_adapter,
        maps_adapter=mock_maps_adapter,
    )


@pytest.fixture
def conversation_agent(mock_debug_logger, mocker):
    """Create conversation agent with mocked LLM."""
    with patch("app.agents.conversation_agent.Anthropic"):
        agent = ConversationAgent(
            debug_logger=mock_debug_logger,
            provider="anthropic",
        )
        agent._call_llm = AsyncMock()
        return agent


@pytest.fixture
def evaluation_agent(mock_debug_logger):
    """Create evaluation agent."""
    return EvaluationAgent(debug_logger=mock_debug_logger)


class TestFullPlanningFlow:
    """Integration tests for the full planning flow."""

    @pytest.mark.asyncio
    async def test_planning_to_conversation_flow(self, planning_agent, conversation_agent):
        """Test flow from planning agent to conversation agent."""
        # Initialize state
        state = AgentState(
            run_id="test_run_123",
            user_id="user_456",
        )

        # Run planning agent
        state = await planning_agent.run(state)
        assert state.plan is not None
        assert len(state.plan.calendar_events) > 0
        assert state.plan.weather is not None
        assert state.plan.commute is not None

        # Mock LLM response for conversation agent
        llm_response = {
            "calendar_summary": "You have 1 team standup",
            "weather_summary": "Partly cloudy, bring a light jacket",
            "commute_summary": "45 minute commute, plan to leave by 8:15am",
            "leave_time": None,
            "workout_recommendation": {"duration_minutes": 30, "recommended_time": "evening"},
            "carry_items": ["laptop", "light jacket"],
            "final_summary": "Your morning: Team standup at 9am, then heads-down work time",
            "missing_events_prompt": "Do you have any doctor's appointments or personal commitments?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))

        # Run conversation agent
        state = await conversation_agent.run(state)
        assert state.plan.final_summary == "Your morning: Team standup at 9am, then heads-down work time"
        assert len(state.transcript) > 0
        assert state.error is None

    @pytest.mark.asyncio
    async def test_planning_to_evaluation_flow(self, planning_agent, evaluation_agent):
        """Test flow from planning agent to evaluation agent."""
        # Initialize and run planning agent
        state = AgentState(
            run_id="test_run_123",
            user_id="user_456",
        )
        state = await planning_agent.run(state)

        # Run evaluation agent
        state = await evaluation_agent.run(state)
        assert state.evaluation_score is not None
        assert 0 <= state.evaluation_score <= 1.0
        assert isinstance(state.debug_summary, dict)

    @pytest.mark.asyncio
    async def test_full_three_agent_flow(self, planning_agent, conversation_agent, evaluation_agent):
        """Test complete flow through all three agents."""
        # Initialize state
        state = AgentState(
            run_id="test_run_123",
            user_id="user_456",
        )

        # Step 1: Planning
        state = await planning_agent.run(state)
        assert state.plan is not None
        assert state.error is None

        # Step 2: Conversation
        llm_response = {
            "calendar_summary": "1 meeting scheduled",
            "weather_summary": "Good weather",
            "commute_summary": "Normal commute",
            "leave_time": None,
            "workout_recommendation": {"duration_minutes": 30, "recommended_time": "evening"},
            "carry_items": [],
            "final_summary": "You're all set for the day",
            "missing_events_prompt": "Anything else planned?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))
        state = await conversation_agent.run(state)
        assert state.plan.final_summary == "You're all set for the day"
        assert state.error is None

        # Step 3: Evaluation
        state = await evaluation_agent.run(state)
        assert state.evaluation_score is not None
        assert state.debug_summary["tool_checks"]["has_calendar_events"] is True
        assert state.debug_summary["tool_checks"]["has_weather"] is True
        assert state.debug_summary["tool_checks"]["has_commute"] is True

    @pytest.mark.asyncio
    async def test_flow_with_user_input(self, planning_agent, conversation_agent, evaluation_agent):
        """Test full flow including user input in conversation."""
        state = AgentState(
            run_id="test_run_123",
            user_id="user_456",
        )

        # Planning
        state = await planning_agent.run(state)

        # Conversation with user input
        state.user_input = "I have a dentist appointment at 2pm"
        llm_response = {
            "calendar_summary": "2 events: Team standup and dentist",
            "weather_summary": "Good weather",
            "commute_summary": "Normal commute",
            "leave_time": None,
            "workout_recommendation": {"duration_minutes": 30, "recommended_time": "evening"},
            "carry_items": [],
            "final_summary": "Updated plan with dentist appointment",
            "missing_events_prompt": "Any other appointments?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))
        state = await conversation_agent.run(state)

        # Check transcript includes user input
        user_messages = [msg for msg in state.transcript if msg["role"] == "user"]
        assert len(user_messages) > 0
        assert "dentist" in user_messages[0]["content"].lower()

        # Evaluation
        state = await evaluation_agent.run(state)
        assert state.evaluation_score is not None

    @pytest.mark.asyncio
    async def test_flow_error_recovery(self, planning_agent, conversation_agent, evaluation_agent):
        """Test error handling during flow."""
        state = AgentState(
            run_id="test_run_123",
            user_id="user_456",
        )

        # Planning succeeds
        state = await planning_agent.run(state)
        assert state.error is None

        # Conversation fails due to LLM error
        conversation_agent._call_llm = AsyncMock(side_effect=Exception("API error"))
        state = await conversation_agent.run(state)
        assert state.error is not None
        assert "API error" in state.error

        # Evaluation still runs and marks the issue
        state = await evaluation_agent.run(state)
        assert state.debug_summary is not None

    @pytest.mark.asyncio
    async def test_flow_with_no_calendar_events(self, mock_debug_logger, conversation_agent, evaluation_agent, mocker):
        """Test flow when user has no calendar events."""
        # Create planning agent with empty calendar
        mock_calendar_adapter = mocker.MagicMock()
        mock_calendar_adapter.is_configured = AsyncMock(return_value=True)
        mock_calendar_adapter.get_events_for_date = AsyncMock(return_value=[])

        mock_weather_adapter = mocker.MagicMock()
        now = datetime.now(timezone.utc)
        mock_weather_adapter.get_weather = AsyncMock(
            return_value=WeatherData(
                temperature_high=72,
                temperature_low=62,
                condition="sunny",
                humidity=60,
                wind_speed_mph=5,
                precipitation_probability=0,
                sunrise=now.replace(hour=6, minute=30),
                sunset=now.replace(hour=19, minute=45),
            )
        )

        mock_maps_adapter = mocker.MagicMock()
        mock_maps_adapter.get_commute = AsyncMock(return_value=None)

        planning_agent_no_events = PlanningAgent(
            debug_logger=mock_debug_logger,
            calendar_adapters=[mock_calendar_adapter],
            weather_adapter=mock_weather_adapter,
            maps_adapter=mock_maps_adapter,
        )

        state = AgentState(run_id="test_run_123", user_id="user_456")
        state = await planning_agent_no_events.run(state)

        # Plan should exist but with no events
        assert state.plan is not None
        assert len(state.plan.calendar_events) == 0

        # Conversation still works
        llm_response = {
            "calendar_summary": "No events today",
            "weather_summary": "Perfect day for outdoor activity",
            "commute_summary": "No commute needed",
            "leave_time": None,
            "workout_recommendation": {"duration_minutes": 45, "recommended_time": "morning"},
            "carry_items": ["sunscreen"],
            "final_summary": "You have a free day - great for projects or exercise",
            "missing_events_prompt": "Anything planned?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))
        state = await conversation_agent.run(state)
        assert state.error is None
        assert "free day" in state.plan.final_summary.lower()


class TestConversationAgentLLMIntegration:
    """Test conversation agent LLM integration."""

    @pytest.mark.asyncio
    async def test_conversation_handles_missing_json_fields(self, conversation_agent):
        """Test conversation agent handles incomplete JSON responses."""
        # Simulate LLM response with missing optional fields
        incomplete_response = {
            "calendar_summary": "1 meeting",
            "weather_summary": "Sunny",
            "commute_summary": "30 min commute",
            # Missing other fields
        }

        state = AgentState(run_id="test", user_id="user")
        state.plan = AgentState(
            run_id="test",
            user_id="user",
        ).plan

        from app.agents.state import DailyPlanData

        state.plan = DailyPlanData()

        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(incomplete_response), 250))

        # Should not crash
        await conversation_agent._generate_plan_with_llm(state)

    @pytest.mark.asyncio
    async def test_conversation_llm_response_with_extra_fields(self, conversation_agent):
        """Test handling of extra fields in LLM response."""
        response = {
            "calendar_summary": "Summary",
            "weather_summary": "Weather",
            "commute_summary": "Commute",
            "final_summary": "Final",
            "missing_events_prompt": "Missing?",
            "extra_field": "should be ignored",
            "another_extra": 42,
        }

        state = AgentState(
            run_id="test",
            user_id="user",
            plan=AgentState(run_id="test", user_id="user").plan or None,
        )
        from app.agents.state import DailyPlanData

        state.plan = DailyPlanData()
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(response), 250))

        # Should not crash with extra fields
        result = await conversation_agent._generate_plan_with_llm(state)
        assert result["calendar_summary"] == "Summary"


class TestEvaluationAgentIntegration:
    """Test evaluation agent with full plan data."""

    @pytest.mark.asyncio
    async def test_evaluation_scores_complete_plan(self, mock_debug_logger):
        """Test evaluation of a complete plan."""
        evaluation_agent = EvaluationAgent(debug_logger=mock_debug_logger)

        now = datetime.now(timezone.utc)
        state = AgentState(
            run_id="test_run",
            user_id="user_123",
            plan=AgentState(
                run_id="test_run",
                user_id="user_123",
            ).plan,
        )

        from app.agents.state import DailyPlanData, CalendarEvent, WeatherData, CommuteData

        state.plan = DailyPlanData(
            calendar_events=[
                CalendarEvent(
                    source="google_calendar",
                    title="Meeting",
                    start_time=now,
                    end_time=now,
                )
            ],
            calendar_summary="1 meeting",
            weather=WeatherData(
                temperature_high=75,
                temperature_low=65,
                condition="sunny",
                humidity=60,
                wind_speed_mph=5,
                precipitation_probability=0,
                sunrise=now,
                sunset=now,
            ),
            weather_summary="Sunny",
            commute=CommuteData(
                from_address="home",
                to_address="work",
                estimated_duration_minutes=30,
                traffic_condition="light",
            ),
            commute_summary="30 min commute",
        )

        state = await evaluation_agent.run(state)

        assert state.evaluation_score is not None
        assert state.evaluation_score > 0.5  # Complete plan should score well
        assert state.debug_summary["tool_checks"]["has_calendar_events"] is True
        assert state.debug_summary["tool_checks"]["has_weather"] is True
        assert state.debug_summary["tool_checks"]["has_commute"] is True

    @pytest.mark.asyncio
    async def test_evaluation_minimal_plan(self, mock_debug_logger):
        """Test evaluation of a minimal plan."""
        evaluation_agent = EvaluationAgent(debug_logger=mock_debug_logger)

        state = AgentState(
            run_id="test_run",
            user_id="user_123",
            plan=AgentState(
                run_id="test_run",
                user_id="user_123",
            ).plan,
        )

        from app.agents.state import DailyPlanData

        state.plan = DailyPlanData(
            calendar_events=[],
            calendar_summary="No events",
            weather=None,
            weather_summary="No weather data",
            commute=None,
            commute_summary="No commute info",
        )

        state = await evaluation_agent.run(state)

        assert state.evaluation_score is not None
        assert state.evaluation_score <= 0.5  # Minimal plan should score lower
        assert state.debug_summary["tool_checks"]["has_calendar_events"] is False
        assert state.debug_summary["tool_checks"]["has_weather"] is False
