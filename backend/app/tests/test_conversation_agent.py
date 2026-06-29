"""Unit tests for ConversationAgent with LLM integration."""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.conversation_agent import ConversationAgent
from app.agents.state import (
    AgentState,
    DailyPlanData,
    CalendarEvent,
    WeatherData,
    CommuteData,
    WorkoutRecommendation,
)
from app.services.logger import DebugLogger
from app.services.langfuse_tracer import LangfuseTracer


@pytest.fixture
def debug_logger(mocker):
    """Mock debug logger."""
    logger = mocker.MagicMock(spec=DebugLogger)
    logger.log_agent_start = AsyncMock()
    logger.log_agent_end = AsyncMock()
    logger.log_event = AsyncMock()
    return logger


@pytest.fixture
def langfuse_tracer(mocker):
    """Mock Langfuse tracer."""
    tracer = mocker.MagicMock(spec=LangfuseTracer)
    trace = mocker.MagicMock()
    trace.span = mocker.MagicMock(return_value=trace)
    trace.end = mocker.MagicMock()
    tracer.trace_agent = mocker.MagicMock(return_value=trace)
    tracer.trace_llm_call = mocker.MagicMock(return_value=trace)
    return tracer


@pytest.fixture
def sample_plan_data():
    """Create sample plan data with calendar, weather, and commute."""
    now = datetime.now(timezone.utc)
    return DailyPlanData(
        calendar_events=[
            CalendarEvent(
                source="google_calendar",
                title="Team Standup",
                start_time=now.replace(hour=9, minute=0, second=0, microsecond=0),
                end_time=now.replace(hour=9, minute=30, second=0, microsecond=0),
                location="Conference Room A",
            ),
            CalendarEvent(
                source="google_calendar",
                title="Client Call",
                start_time=now.replace(hour=14, minute=0, second=0, microsecond=0),
                end_time=now.replace(hour=15, minute=0, second=0, microsecond=0),
                location="Virtual",
            ),
        ],
        calendar_summary="You have 2 meetings today",
        weather=WeatherData(
            temperature_high=72,
            temperature_low=62,
            condition="partly_cloudy",
            humidity=65,
            wind_speed_mph=10,
            precipitation_probability=20,
            sunrise=now.replace(hour=6, minute=30, second=0, microsecond=0),
            sunset=now.replace(hour=19, minute=45, second=0, microsecond=0),
        ),
        weather_summary="Partly cloudy, 62-72°F",
        commute=CommuteData(
            from_address="123 Main St, NY",
            to_address="456 Work Ave, NY",
            estimated_duration_minutes=45,
            traffic_condition="moderate",
        ),
        commute_summary="45 minute commute with moderate traffic",
    )


@pytest.fixture
def sample_agent_state(sample_plan_data):
    """Create sample agent state."""
    return AgentState(
        run_id="test_run_123",
        user_id="user_456",
        plan=sample_plan_data,
        transcript=[],
    )


@pytest.fixture
def conversation_agent(debug_logger, langfuse_tracer, mocker):
    """Create ConversationAgent with mocked LLM."""
    mocker.patch("anthropic.Anthropic")
    mocker.patch("openai.AsyncOpenAI")
    mocker.patch("app.config.get_settings", return_value=mocker.MagicMock(
        anthropic_api_key="test-key",
        openai_api_key="test-key"
    ))
    agent = ConversationAgent(
        debug_logger=debug_logger,
        langfuse_tracer=langfuse_tracer,
        provider="anthropic",
    )
    agent._call_llm = AsyncMock()
    return agent


class TestConversationAgentInitialization:
    """Tests for ConversationAgent initialization."""

    def test_init_with_claude_provider(self, debug_logger, mocker):
        """Test initialization with Claude provider."""
        mocker.patch("anthropic.Anthropic")
        mocker.patch("app.config.get_settings", return_value=mocker.MagicMock(
            anthropic_api_key="test-key"
        ))

        agent = ConversationAgent(debug_logger, provider="anthropic")
        assert agent.provider == "anthropic"
        assert agent.model == "claude-3-5-sonnet-20241022"

    @pytest.mark.skip(reason="AsyncOpenAI validation requires real API key handling")
    def test_init_with_openai_provider(self, debug_logger, mocker):
        """Test initialization with OpenAI provider."""
        mock_openai = mocker.MagicMock()
        mocker.patch("openai.AsyncOpenAI", return_value=mock_openai)
        mocker.patch("app.config.get_settings", return_value=mocker.MagicMock(
            openai_api_key="test-key"
        ))

        agent = ConversationAgent(debug_logger, provider="openai")
        assert agent.provider == "openai"
        assert agent.model == "gpt-4-turbo-preview"

    def test_init_with_langfuse_tracer(self, debug_logger, langfuse_tracer, mocker):
        """Test initialization with Langfuse tracer."""
        mocker.patch("anthropic.Anthropic")
        mocker.patch("app.config.get_settings", return_value=mocker.MagicMock(
            anthropic_api_key="test-key"
        ))

        agent = ConversationAgent(debug_logger, langfuse_tracer=langfuse_tracer)
        assert agent.langfuse_tracer is not None


class TestJSONParsing:
    """Tests for JSON response parsing."""

    def test_parse_valid_json(self, conversation_agent):
        """Test parsing valid JSON response."""
        response = '{"key": "value", "nested": {"number": 42}}'
        result = conversation_agent._parse_json_response(response)
        assert result["key"] == "value"
        assert result["nested"]["number"] == 42

    def test_parse_json_with_markdown_code_block(self, conversation_agent):
        """Test parsing JSON wrapped in markdown code blocks."""
        response = '```json\n{"key": "value"}\n```'
        result = conversation_agent._parse_json_response(response)
        assert result["key"] == "value"

    def test_parse_json_with_markdown_no_language(self, conversation_agent):
        """Test parsing JSON wrapped in generic markdown code blocks."""
        response = '```\n{"key": "value"}\n```'
        result = conversation_agent._parse_json_response(response)
        assert result["key"] == "value"

    def test_parse_invalid_json_raises_error(self, conversation_agent):
        """Test that invalid JSON raises ValueError."""
        response = '{invalid json}'
        with pytest.raises(ValueError):
            conversation_agent._parse_json_response(response)

    def test_parse_json_with_whitespace(self, conversation_agent):
        """Test parsing JSON with extra whitespace."""
        response = '  \n{"key": "value"}\n  '
        result = conversation_agent._parse_json_response(response)
        assert result["key"] == "value"


class TestPlanFormatting:
    """Tests for formatting plans for speech."""

    def test_format_plan_with_final_summary(self, conversation_agent, sample_plan_data):
        """Test that final_summary is used if available."""
        sample_plan_data.final_summary = "Here's your day: Two meetings..."
        result = conversation_agent._format_plan_for_speech(sample_plan_data)
        assert result == "Here's your day: Two meetings..."

    def test_format_plan_without_final_summary(self, conversation_agent, sample_plan_data):
        """Test fallback formatting without final_summary."""
        sample_plan_data.final_summary = ""
        result = conversation_agent._format_plan_for_speech(sample_plan_data)
        # The format uses summaries, not individual event titles
        assert "Calendar:" in result
        assert "meetings" in result

    def test_format_plan_no_events(self, conversation_agent):
        """Test formatting plan with no events."""
        plan = DailyPlanData(
            calendar_events=[],
            calendar_summary="No events",
            weather_summary="Clear",
            commute_summary="No commute",
        )
        result = conversation_agent._format_plan_for_speech(plan)
        assert "no events" in result.lower()

    def test_format_plan_includes_weather(self, conversation_agent, sample_plan_data):
        """Test that weather is included in formatted plan."""
        sample_plan_data.final_summary = ""
        result = conversation_agent._format_plan_for_speech(sample_plan_data)
        assert "Weather:" in result

    def test_format_plan_includes_carry_items(self, conversation_agent, sample_plan_data):
        """Test that carry items are included in formatted plan."""
        sample_plan_data.final_summary = ""
        sample_plan_data.carry_items = ["umbrella", "jacket"]
        result = conversation_agent._format_plan_for_speech(sample_plan_data)
        assert "Bring:" in result

    def test_format_plan_includes_leave_time(self, conversation_agent, sample_plan_data):
        """Test that leave time is included in formatted plan."""
        sample_plan_data.final_summary = ""
        now = datetime.now(timezone.utc)
        sample_plan_data.leave_time = now.replace(hour=8, minute=30)
        result = conversation_agent._format_plan_for_speech(sample_plan_data)
        assert "Leave by:" in result
        assert "08:30" in result

    def test_format_plan_includes_workout(self, conversation_agent, sample_plan_data):
        """Test that workout recommendation is included."""
        sample_plan_data.final_summary = ""
        sample_plan_data.workout_recommendation = WorkoutRecommendation(
            duration_minutes=30,
            recommended_time="morning",
        )
        result = conversation_agent._format_plan_for_speech(sample_plan_data)
        assert "Workout:" in result
        assert "30" in result


class TestUpdatePlanFromLLMResponse:
    """Tests for updating plan with LLM-generated data."""

    def test_update_plan_summaries(self, conversation_agent, sample_agent_state):
        """Test updating plan summaries."""
        llm_response = {
            "calendar_summary": "New calendar summary",
            "weather_summary": "New weather summary",
            "commute_summary": "New commute summary",
            "final_summary": "New final summary",
        }
        conversation_agent._update_plan_from_llm_response(sample_agent_state, llm_response)

        assert sample_agent_state.plan.calendar_summary == "New calendar summary"
        assert sample_agent_state.plan.weather_summary == "New weather summary"
        assert sample_agent_state.plan.commute_summary == "New commute summary"
        assert sample_agent_state.plan.final_summary == "New final summary"

    def test_update_plan_leave_time(self, conversation_agent, sample_agent_state):
        """Test updating leave time from LLM response."""
        leave_time = datetime.now(timezone.utc).replace(hour=8, minute=0)
        llm_response = {
            "leave_time": leave_time.isoformat(),
        }
        conversation_agent._update_plan_from_llm_response(sample_agent_state, llm_response)

        assert sample_agent_state.plan.leave_time is not None
        assert sample_agent_state.plan.leave_time.hour == 8

    def test_update_plan_leave_time_invalid_format(self, conversation_agent, sample_agent_state):
        """Test that invalid leave time is handled gracefully."""
        llm_response = {
            "leave_time": "invalid_time",
        }
        conversation_agent._update_plan_from_llm_response(sample_agent_state, llm_response)
        # Should not crash, leave_time remains unchanged

    def test_update_plan_carry_items(self, conversation_agent, sample_agent_state):
        """Test updating carry items."""
        llm_response = {
            "carry_items": ["laptop", "water bottle", "notebook"],
        }
        conversation_agent._update_plan_from_llm_response(sample_agent_state, llm_response)

        assert sample_agent_state.plan.carry_items == ["laptop", "water bottle", "notebook"]

    def test_update_plan_workout_recommendation(self, conversation_agent, sample_agent_state):
        """Test updating workout recommendation."""
        start_time = datetime.now(timezone.utc).replace(hour=18, minute=0)
        end_time = start_time.replace(hour=19, minute=0)

        llm_response = {
            "workout_recommendation": {
                "duration_minutes": 45,
                "recommended_time": "evening",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "notes": "After work",
            }
        }
        conversation_agent._update_plan_from_llm_response(sample_agent_state, llm_response)

        assert sample_agent_state.plan.workout_recommendation.duration_minutes == 45
        assert sample_agent_state.plan.workout_recommendation.recommended_time == "evening"
        assert sample_agent_state.plan.workout_recommendation.notes == "After work"

    def test_update_plan_with_none_state_plan(self, conversation_agent):
        """Test that updating with None plan doesn't crash."""
        state = AgentState(run_id="test", user_id="user")
        state.plan = None
        llm_response = {"calendar_summary": "test"}
        # Should not raise
        conversation_agent._update_plan_from_llm_response(state, llm_response)


class TestLLMCallHandling:
    """Tests for LLM call handling and error cases."""

    @pytest.mark.asyncio
    async def test_generate_plan_with_llm_success(self, conversation_agent, sample_agent_state):
        """Test successful plan generation via LLM."""
        llm_response = {
            "calendar_summary": "You have 2 important meetings",
            "weather_summary": "Bring an umbrella",
            "commute_summary": "Plan for 45 minutes",
            "leave_time": None,
            "workout_recommendation": {"duration_minutes": 30, "recommended_time": "morning"},
            "carry_items": ["umbrella"],
            "final_summary": "Your day looks busy but manageable",
            "missing_events_prompt": "Do you have any other commitments?",
        }

        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))

        result = await conversation_agent._generate_plan_with_llm(sample_agent_state)
        assert result["calendar_summary"] == "You have 2 important meetings"
        assert result["final_summary"] == "Your day looks busy but manageable"

    @pytest.mark.asyncio
    async def test_generate_plan_with_markdown_response(self, conversation_agent, sample_agent_state):
        """Test LLM response with markdown code blocks."""
        llm_response = {
            "calendar_summary": "Summary",
            "weather_summary": "Weather",
            "commute_summary": "Commute",
            "final_summary": "Final",
            "missing_events_prompt": "Missing?",
        }
        markdown_response = f"```json\n{json.dumps(llm_response)}\n```"
        conversation_agent._call_llm = AsyncMock(return_value=(markdown_response, 250))

        result = await conversation_agent._generate_plan_with_llm(sample_agent_state)
        assert result["calendar_summary"] == "Summary"

    @pytest.mark.asyncio
    async def test_generate_plan_with_invalid_json(self, conversation_agent, sample_agent_state, debug_logger):
        """Test handling of invalid JSON response from LLM."""
        conversation_agent._call_llm = AsyncMock(return_value=("{invalid}", 250))

        with pytest.raises(ValueError):
            await conversation_agent._generate_plan_with_llm(sample_agent_state)


class TestConversationAgentRun:
    """Tests for the main run() method."""

    @pytest.mark.asyncio
    async def test_run_success(self, conversation_agent, sample_agent_state, debug_logger):
        """Test successful conversation agent run."""
        llm_response = {
            "calendar_summary": "2 meetings today",
            "weather_summary": "Sunny",
            "commute_summary": "45 min commute",
            "leave_time": None,
            "workout_recommendation": {"duration_minutes": 30, "recommended_time": "evening"},
            "carry_items": [],
            "final_summary": "Ready for your day",
            "missing_events_prompt": "Any other plans?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))

        result = await conversation_agent.run(sample_agent_state)

        assert result.plan is not None
        assert result.plan.final_summary == "Ready for your day"
        assert len(result.transcript) > 0
        debug_logger.log_agent_end.assert_called_with("ConversationAgent", success=True)

    @pytest.mark.asyncio
    async def test_run_with_no_plan(self, conversation_agent, debug_logger):
        """Test run with missing plan raises error."""
        state = AgentState(run_id="test", user_id="user", plan=None)
        result = await conversation_agent.run(state)

        assert result.error is not None
        debug_logger.log_agent_end.assert_called_with("ConversationAgent", success=False)

    @pytest.mark.asyncio
    async def test_run_updates_transcript(self, conversation_agent, sample_agent_state):
        """Test that run updates transcript with assistant response."""
        llm_response = {
            "calendar_summary": "Summary",
            "weather_summary": "Weather",
            "commute_summary": "Commute",
            "final_summary": "Your plan for today...",
            "missing_events_prompt": "Anything else?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))

        result = await conversation_agent.run(sample_agent_state)

        assert len(result.transcript) > 0
        assert result.transcript[0]["role"] == "assistant"
        assert "Your plan for today" in result.transcript[0]["content"]

    @pytest.mark.asyncio
    async def test_run_with_user_input(self, conversation_agent, sample_agent_state, debug_logger):
        """Test run with user input in state."""
        sample_agent_state.user_input = "I have a dentist appointment at 2pm"

        llm_response = {
            "calendar_summary": "Summary",
            "weather_summary": "Weather",
            "commute_summary": "Commute",
            "final_summary": "Plan updated",
            "missing_events_prompt": "Anything else?",
        }
        conversation_agent._call_llm = AsyncMock(return_value=(json.dumps(llm_response), 250))

        result = await conversation_agent.run(sample_agent_state)

        # Transcript should include user input
        user_messages = [m for m in result.transcript if m["role"] == "user"]
        assert len(user_messages) > 0
        assert user_messages[0]["content"] == "I have a dentist appointment at 2pm"

    @pytest.mark.asyncio
    async def test_run_handles_llm_errors(self, conversation_agent, sample_agent_state, debug_logger):
        """Test that LLM errors are handled gracefully."""
        conversation_agent._call_llm = AsyncMock(side_effect=Exception("API error"))

        result = await conversation_agent.run(sample_agent_state)

        assert result.error is not None
        assert "API error" in result.error
        debug_logger.log_event.assert_called()
        debug_logger.log_agent_end.assert_called_with("ConversationAgent", success=False)


class TestProcessUserInput:
    """Tests for process_user_input() — LLM interpretation of user speech."""

    @pytest.mark.asyncio
    async def test_process_user_input_add_event(self, conversation_agent, sample_agent_state):
        """User mentions a new event; action should be add_event."""
        sample_agent_state.user_input = "I have a dentist appointment at 3pm"

        llm_response = json.dumps({
            "action": "add_event",
            "new_event": {"title": "Dentist", "start_time": None, "end_time": None, "location": None},
            "response": "Got it, I've noted your dentist appointment at 3pm.",
            "updated_plan": {"final_summary": "Updated plan with dentist."},
        })
        conversation_agent._call_llm = AsyncMock(return_value=(llm_response, 200))

        action, response = await conversation_agent.process_user_input(sample_agent_state)

        assert action == "add_event"
        assert "dentist" in response.lower()
        assert sample_agent_state.plan.final_summary == "Updated plan with dentist."

    @pytest.mark.asyncio
    async def test_process_user_input_confirm(self, conversation_agent, sample_agent_state):
        """User confirms the plan."""
        sample_agent_state.user_input = "Sounds good, thanks!"

        llm_response = json.dumps({
            "action": "confirm",
            "new_event": None,
            "response": "Great, I'll send the summary to your phone.",
            "updated_plan": None,
        })
        conversation_agent._call_llm = AsyncMock(return_value=(llm_response, 150))

        action, response = await conversation_agent.process_user_input(sample_agent_state)

        assert action == "confirm"
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_process_user_input_updates_transcript(self, conversation_agent, sample_agent_state):
        """Both user utterance and agent reply should land in transcript."""
        sample_agent_state.user_input = "Nothing else, thanks"

        llm_response = json.dumps({
            "action": "confirm",
            "response": "Perfect, have a great day!",
            "new_event": None,
            "updated_plan": None,
        })
        conversation_agent._call_llm = AsyncMock(return_value=(llm_response, 100))

        await conversation_agent.process_user_input(sample_agent_state)

        roles = [t["role"] for t in sample_agent_state.transcript]
        assert "user" in roles
        assert "assistant" in roles

    @pytest.mark.asyncio
    async def test_process_user_input_no_user_input(self, conversation_agent, sample_agent_state):
        """Empty user_input should return clarify without calling LLM."""
        sample_agent_state.user_input = ""
        conversation_agent._call_llm = AsyncMock()

        action, _ = await conversation_agent.process_user_input(sample_agent_state)

        assert action == "clarify"
        conversation_agent._call_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_user_input_no_plan(self, conversation_agent):
        """No plan should return clarify without calling LLM."""
        state = AgentState(run_id="test", user_id="user", user_input="hello")
        conversation_agent._call_llm = AsyncMock()

        action, _ = await conversation_agent.process_user_input(state)

        assert action == "clarify"
        conversation_agent._call_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_user_input_llm_error_graceful(self, conversation_agent, sample_agent_state):
        """LLM error should degrade gracefully to clarify."""
        sample_agent_state.user_input = "I said something"
        conversation_agent._call_llm = AsyncMock(side_effect=Exception("API down"))

        action, response = await conversation_agent.process_user_input(sample_agent_state)

        assert action == "clarify"
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_process_user_input_invalid_json_graceful(self, conversation_agent, sample_agent_state):
        """Invalid JSON from LLM should fall back to clarify."""
        sample_agent_state.user_input = "Some input"
        conversation_agent._call_llm = AsyncMock(return_value=("{invalid json}", 100))

        action, response = await conversation_agent.process_user_input(sample_agent_state)

        assert action == "clarify"
        assert isinstance(response, str)


class TestSendSummary:
    """Tests for send_summary() — SMS/iMessage delivery."""

    @pytest.fixture
    def mock_messaging_adapter(self, mocker):
        adapter = mocker.AsyncMock()
        adapter.send_message = mocker.AsyncMock(
            return_value={"status": "sent", "message_id": "msg_123"}
        )
        return adapter

    @pytest.mark.asyncio
    async def test_send_summary_success(
        self, conversation_agent, sample_agent_state, mock_messaging_adapter
    ):
        """Happy path: summary sent, returns True."""
        sample_agent_state.plan.final_summary = "Have a great day!"

        result = await conversation_agent.send_summary(
            sample_agent_state, mock_messaging_adapter, "+15551234567"
        )

        assert result is True
        mock_messaging_adapter.send_message.assert_called_once()
        call_args = mock_messaging_adapter.send_message.call_args
        assert call_args[0][0] == "+15551234567"
        assert "DailyOps" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_send_summary_no_plan(
        self, conversation_agent, mock_messaging_adapter
    ):
        """Missing plan should return False without calling adapter."""
        state = AgentState(run_id="test", user_id="user", plan=None)

        result = await conversation_agent.send_summary(
            state, mock_messaging_adapter, "+15551234567"
        )

        assert result is False
        mock_messaging_adapter.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_summary_adapter_failure(
        self, conversation_agent, sample_agent_state, mock_messaging_adapter
    ):
        """Adapter returning failed status should return False."""
        mock_messaging_adapter.send_message = AsyncMock(
            return_value={"status": "failed", "error": "number invalid"}
        )

        result = await conversation_agent.send_summary(
            sample_agent_state, mock_messaging_adapter, "+15551234567"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_summary_adapter_exception(
        self, conversation_agent, sample_agent_state, mock_messaging_adapter
    ):
        """Adapter raising exception should return False."""
        mock_messaging_adapter.send_message = AsyncMock(side_effect=Exception("timeout"))

        result = await conversation_agent.send_summary(
            sample_agent_state, mock_messaging_adapter, "+15551234567"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_summary_includes_plan_details(
        self, conversation_agent, sample_agent_state, mock_messaging_adapter
    ):
        """SMS text should include key plan fields when no final_summary."""
        sample_agent_state.plan.final_summary = ""
        sample_agent_state.plan.calendar_summary = "2 meetings"
        sample_agent_state.plan.weather_summary = "Sunny"

        await conversation_agent.send_summary(
            sample_agent_state, mock_messaging_adapter, "+15551234567"
        )

        sms_text = mock_messaging_adapter.send_message.call_args[0][1]
        assert "2 meetings" in sms_text
        assert "Sunny" in sms_text


class TestGenerateConfirmationPrompt:
    """Tests for generate_confirmation_prompt()."""

    @pytest.mark.asyncio
    async def test_confirmation_prompt_success(self, conversation_agent, sample_plan_data):
        """Returns LLM-generated confirmation question."""
        llm_response = json.dumps({"message": "Does this plan work for you today?"})
        conversation_agent._call_llm = AsyncMock(return_value=(llm_response, 100))

        result = await conversation_agent.generate_confirmation_prompt(sample_plan_data)

        assert "work for you" in result

    @pytest.mark.asyncio
    async def test_confirmation_prompt_llm_error_fallback(
        self, conversation_agent, sample_plan_data
    ):
        """LLM failure falls back to default question."""
        conversation_agent._call_llm = AsyncMock(side_effect=Exception("API error"))

        result = await conversation_agent.generate_confirmation_prompt(sample_plan_data)

        assert result == "Does this plan work for you?"

    @pytest.mark.asyncio
    async def test_confirmation_prompt_invalid_json_fallback(
        self, conversation_agent, sample_plan_data
    ):
        """Invalid JSON falls back to default question."""
        conversation_agent._call_llm = AsyncMock(return_value=("{bad json}", 100))

        result = await conversation_agent.generate_confirmation_prompt(sample_plan_data)

        assert result == "Does this plan work for you?"


class TestSMSFormatting:
    """Tests for _format_plan_for_sms()."""

    def test_sms_uses_final_summary(self, conversation_agent, sample_plan_data):
        """final_summary is used when present."""
        sample_plan_data.final_summary = "Short plan."
        result = conversation_agent._format_plan_for_sms(sample_plan_data)
        assert "Short plan." in result

    def test_sms_includes_calendar_summary(self, conversation_agent, sample_plan_data):
        """Calendar summary appears in SMS text."""
        sample_plan_data.final_summary = ""
        sample_plan_data.calendar_summary = "3 meetings"
        result = conversation_agent._format_plan_for_sms(sample_plan_data)
        assert "3 meetings" in result

    def test_sms_includes_carry_items(self, conversation_agent, sample_plan_data):
        """Carry items appear in SMS text."""
        sample_plan_data.final_summary = ""
        sample_plan_data.carry_items = ["umbrella", "badge"]
        result = conversation_agent._format_plan_for_sms(sample_plan_data)
        assert "umbrella" in result
        assert "badge" in result

    def test_sms_includes_leave_time(self, conversation_agent, sample_plan_data):
        """Leave time appears in SMS text."""
        sample_plan_data.final_summary = ""
        now = datetime.now(timezone.utc)
        sample_plan_data.leave_time = now.replace(hour=8, minute=15)
        result = conversation_agent._format_plan_for_sms(sample_plan_data)
        assert "08:15" in result

    def test_sms_starts_with_header(self, conversation_agent, sample_plan_data):
        """SMS always starts with DailyOps header."""
        result = conversation_agent._format_plan_for_sms(sample_plan_data)
        assert result.startswith("📅 Your DailyOps Summary")


class TestLLMCallWithRetry:
    """Tests for LLM call retry logic."""

    @pytest.mark.asyncio
    async def test_claude_timeout_retry(self, conversation_agent, mocker):
        """Test Claude timeout with retry."""
        from anthropic import APITimeoutError

        # Mock that first call times out, second succeeds
        mock_response = mocker.MagicMock()
        mock_response.content = [mocker.MagicMock(text="response")]

        conversation_agent.llm_client = mocker.MagicMock()
        conversation_agent.llm_client.messages.create = mocker.MagicMock(
            side_effect=[APITimeoutError("timeout"), mock_response]
        )

        response, latency = await conversation_agent._call_claude(
            "system", "user", max_retries=2
        )

        assert response == "response"
        assert conversation_agent.llm_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_claude_max_retries_exceeded(self, conversation_agent, mocker):
        """Test Claude max retries exceeded."""
        from anthropic import APITimeoutError

        conversation_agent.llm_client = mocker.MagicMock()
        conversation_agent.llm_client.messages.create = mocker.MagicMock(
            side_effect=APITimeoutError("timeout")
        )

        with pytest.raises(Exception, match="timeout after"):
            await conversation_agent._call_claude("system", "user", max_retries=1)
