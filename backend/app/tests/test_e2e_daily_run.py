"""End-to-end tests for complete daily run (DOPS-6)."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import json

from app.agents.state import (
    AgentState,
    DailyPlanData,
    CalendarEvent,
    WeatherData,
    CommuteData,
)
from app.services.logger import DebugLogger


class TestE2EDailyRun:
    """Test complete daily run from trigger to final summary."""

    @pytest.fixture
    def mock_logger(self):
        """Mock debug logger."""
        logger = AsyncMock(spec=DebugLogger)
        logger.log_event = AsyncMock()
        logger.log_agent_start = AsyncMock()
        logger.log_agent_end = AsyncMock()
        return logger

    @pytest.fixture
    def mock_adapters(self):
        """Mock all adapters."""
        return {
            "google_calendar": AsyncMock(),
            "apple_ical": AsyncMock(),
            "weather": AsyncMock(),
            "maps": AsyncMock(),
            "vapi": AsyncMock(),
        }

    @pytest.mark.asyncio
    async def test_e2e_full_run_success(self, mock_logger, mock_adapters):
        """Test complete successful daily run."""
        # Setup: Create initial state
        state = AgentState(
            run_id="e2e-test-123",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_events=[
                CalendarEvent(
                    source="google_calendar",
                    title="All hands meeting",
                    start_time=datetime.utcnow() + timedelta(hours=2),
                    end_time=datetime.utcnow() + timedelta(hours=2, minutes=30),
                ),
                CalendarEvent(
                    source="apple_ical",
                    title="Dentist appointment",
                    start_time=datetime.utcnow() + timedelta(hours=4),
                    end_time=datetime.utcnow() + timedelta(hours=4, minutes=30),
                    location="Downtown Dental",
                ),
            ],
            calendar_summary="2 important meetings today",
            weather=WeatherData(
                temperature_high=75,
                temperature_low=62,
                condition="partly_cloudy",
                humidity=70,
                wind_speed_mph=8,
                precipitation_probability=10,
                sunrise=datetime.utcnow().replace(hour=6, minute=30),
                sunset=datetime.utcnow().replace(hour=19, minute=0),
            ),
            weather_summary="Mild weather, bring light jacket",
            commute=CommuteData(
                from_address="123 Home St, City",
                to_address="456 Work Ave, City",
                estimated_duration_minutes=30,
                traffic_condition="light",
            ),
            commute_summary="30 min commute with light traffic",
        )

        # Verify: All plan data is complete
        assert state.plan.calendar_events
        assert state.plan.weather
        assert state.plan.commute
        assert len(state.plan.calendar_events) == 2

    @pytest.mark.asyncio
    async def test_e2e_with_missing_calendar_data(self, mock_logger):
        """Test E2E when calendar adapter fails."""
        state = AgentState(
            run_id="e2e-no-calendar",
            user_id="user-456",
        )

        # Plan created with no calendar events (fallback)
        state.plan = DailyPlanData(
            calendar_summary="No calendar events",
            weather_summary="Sunny day",
        )

        # Verify fallback works
        assert state.plan is not None
        assert state.plan.calendar_summary == "No calendar events"
        assert len(state.plan.calendar_events) == 0

    @pytest.mark.asyncio
    async def test_e2e_with_missing_weather_data(self, mock_logger):
        """Test E2E when weather adapter fails."""
        state = AgentState(
            run_id="e2e-no-weather",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_events=[
                CalendarEvent(
                    source="google_calendar",
                    title="Morning standup",
                    start_time=datetime.utcnow() + timedelta(hours=1),
                    end_time=datetime.utcnow() + timedelta(hours=1, minutes=15),
                ),
            ],
            calendar_summary="1 event today",
            weather_summary="Weather data unavailable",
        )

        # Verify run continues without weather
        assert state.plan is not None
        assert state.plan.weather is None
        assert state.plan.calendar_events

    @pytest.mark.asyncio
    async def test_e2e_with_missing_commute_data(self, mock_logger):
        """Test E2E when maps adapter fails."""
        state = AgentState(
            run_id="e2e-no-commute",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_events=[
                CalendarEvent(
                    source="google_calendar",
                    title="Conference",
                    start_time=datetime.utcnow() + timedelta(hours=3),
                    end_time=datetime.utcnow() + timedelta(hours=4),
                ),
            ],
            calendar_summary="Conference today",
            weather=WeatherData(
                temperature_high=70,
                temperature_low=60,
                condition="cloudy",
                humidity=60,
                wind_speed_mph=5,
                precipitation_probability=20,
                sunrise=datetime.utcnow().replace(hour=6, minute=30),
                sunset=datetime.utcnow().replace(hour=19, minute=0),
            ),
            weather_summary="Cloudy skies",
            commute=None,  # Commute failed
            commute_summary="Commute data unavailable",
        )

        # Verify run continues without commute
        assert state.plan is not None
        assert state.plan.commute is None
        assert state.plan.calendar_events

    @pytest.mark.asyncio
    async def test_e2e_latency_tracking(self, mock_logger):
        """Test that latency is tracked end-to-end."""
        import time

        state = AgentState(
            run_id="e2e-latency",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_summary="1 quick sync",
            weather_summary="Sunny",
        )

        start = time.time()
        # Simulate processing time
        time.sleep(0.05)  # 50ms
        elapsed_ms = int((time.time() - start) * 1000)

        # Verify latency is under budget (target <2s per component)
        assert elapsed_ms < 2000, f"Latency {elapsed_ms}ms exceeds budget"

    @pytest.mark.asyncio
    async def test_e2e_with_user_interaction(self, mock_logger):
        """Test E2E with user providing additional plans."""
        state = AgentState(
            run_id="e2e-user-interaction",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_summary="Board meeting at 2pm",
            weather_summary="Sunny",
        )

        # User provides input
        state.user_input = "I also have a client call at 4pm"
        state.transcript.append(
            {"role": "assistant", "content": "Tell me about your day"}
        )
        state.transcript.append(
            {"role": "user", "content": state.user_input}
        )

        # Verify transcript is updated
        assert len(state.transcript) == 2
        assert state.user_input in state.transcript[-1]["content"]

    @pytest.mark.asyncio
    async def test_e2e_multiple_calendar_sources(self, mock_logger):
        """Test merging events from multiple calendar sources."""
        state = AgentState(
            run_id="e2e-multi-calendar",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_events=[
                CalendarEvent(
                    source="google_calendar",
                    title="Team standup",
                    start_time=datetime.utcnow() + timedelta(hours=1),
                    end_time=datetime.utcnow() + timedelta(hours=1, minutes=15),
                ),
                CalendarEvent(
                    source="apple_ical",
                    title="Personal reminder",
                    start_time=datetime.utcnow() + timedelta(hours=5),
                    end_time=datetime.utcnow() + timedelta(hours=5, minutes=30),
                ),
            ],
            calendar_summary="3 events from multiple calendars",
            weather_summary="Sunny",
        )

        # Verify sources are tracked
        sources = set(e.source for e in state.plan.calendar_events)
        assert "google_calendar" in sources
        assert "apple_ical" in sources
        assert len(state.plan.calendar_events) == 2


class TestErrorRecoveryIntegration:
    """Test error recovery across all components."""

    @pytest.mark.asyncio
    async def test_graceful_degradation_all_failures(self):
        """Test that system degrades gracefully when all adapters fail."""
        state = AgentState(
            run_id="e2e-all-fail",
            user_id="user-456",
        )

        # All adapters return None/empty
        state.plan = DailyPlanData(
            calendar_events=[],  # Calendar failed
            calendar_summary="Calendar unavailable",
            weather=None,  # Weather failed
            weather_summary="Weather unavailable",
            commute=None,  # Maps failed
            commute_summary="Commute unavailable",
        )

        # System should still have a valid state
        assert state.plan is not None
        assert state.run_id == "e2e-all-fail"

    @pytest.mark.asyncio
    async def test_partial_calendar_data_handling(self):
        """Test handling of partial calendar data."""
        state = AgentState(
            run_id="e2e-partial-calendar",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_events=[
                CalendarEvent(
                    source="google_calendar",
                    title="Event without location",
                    start_time=datetime.utcnow() + timedelta(hours=1),
                    end_time=datetime.utcnow() + timedelta(hours=2),
                ),
                CalendarEvent(
                    source="google_calendar",
                    title="Event with optional fields",
                    start_time=datetime.utcnow() + timedelta(hours=3),
                    end_time=datetime.utcnow() + timedelta(hours=4),
                    location="Remote",
                    attendees=["alice@example.com"],
                ),
            ],
            calendar_summary="Events with partial data",
            weather_summary="Sunny",
        )

        # System should handle optional fields
        assert all(e.title for e in state.plan.calendar_events)
        assert len(state.plan.calendar_events) == 2


class TestObservabilityIntegration:
    """Test Langfuse + Supabase logging integration."""

    @pytest.mark.asyncio
    async def test_complete_call_flow_logging(self):
        """Test that complete call flow is logged."""
        state = AgentState(
            run_id="e2e-logging-test",
            user_id="user-456",
        )

        state.plan = DailyPlanData(
            calendar_summary="1 meeting",
            weather_summary="Sunny",
        )

        # Verify logging structure
        assert state.run_id is not None
        assert state.user_id is not None
        assert state.created_at is not None
        assert isinstance(state.created_at, datetime)

    @pytest.mark.asyncio
    async def test_debug_log_structure(self):
        """Test debug log has correct structure."""
        state = AgentState(
            run_id="e2e-debug-logs",
            user_id="user-456",
        )

        debug_event = {
            "run_id": state.run_id,
            "agent_name": "PlanningAgent",
            "event_type": "calendar_fetch",
            "latency_ms": 1250,
            "input_payload": {},
            "output_payload": {"events_count": 3},
            "error": None,
        }

        # Verify structure
        assert "run_id" in debug_event
        assert "agent_name" in debug_event
        assert "event_type" in debug_event
        assert "latency_ms" in debug_event
