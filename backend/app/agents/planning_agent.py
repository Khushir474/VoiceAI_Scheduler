"""Planning Agent: Fetches data and builds the daily plan."""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.agents.state import (
    AgentState,
    CalendarEvent,
    DailyPlanData,
    WeatherData,
    CommuteData,
    WorkoutRecommendation,
)
from app.adapters.calendar.base import CalendarAdapter
from app.adapters.weather import WeatherAdapter
from app.adapters.maps import MapsAdapter
from app.services.logger import DebugLogger
from app.services.calendar_merge import CalendarMerger
from app.services.langfuse_tracer import LangfuseTracer


class PlanningAgent:
    """Planning Agent: Gathers data and builds a daily plan."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        calendar_adapters: list[CalendarAdapter],
        weather_adapter: WeatherAdapter | None = None,
        maps_adapter: MapsAdapter | None = None,
        langfuse_tracer: LangfuseTracer | None = None,
    ):
        self.debug_logger = debug_logger
        self.calendar_adapters = calendar_adapters
        self.weather_adapter = weather_adapter
        self.maps_adapter = maps_adapter
        self.langfuse_tracer = langfuse_tracer
        self.calendar_merger = CalendarMerger(debug_logger)

    async def _fetch_calendar_events(self, user_id: str, target_date: date) -> list[CalendarEvent]:
        """Fetch calendar events from all configured adapters."""
        await self.debug_logger.log_agent_start("PlanningAgent.fetch_calendar")

        all_events = []

        for adapter in self.calendar_adapters:
            try:
                if await adapter.is_configured(user_id):
                    events = await adapter.get_events_for_date(user_id, target_date)
                    all_events.extend(events)
                    await self.debug_logger.log_event(
                        agent_name="PlanningAgent",
                        event_type="calendar_fetch",
                        message=f"Fetched {len(events)} events from {adapter.__class__.__name__}",
                        output_payload={"adapter": adapter.__class__.__name__, "count": len(events)},
                    )
            except Exception as e:
                await self.debug_logger.log_event(
                    agent_name="PlanningAgent",
                    event_type="calendar_fetch_error",
                    level="error",
                    message=f"Failed to fetch from {adapter.__class__.__name__}: {str(e)}",
                    error=str(e),
                )

        # Merge and deduplicate
        deduplicated_events, dedup_report = self.calendar_merger.merge(all_events)
        await self.calendar_merger.log_dedup_results(deduplicated_events, dedup_report)

        await self.debug_logger.log_agent_end("PlanningAgent.fetch_calendar", success=True)
        return deduplicated_events

    async def _fetch_weather(self, latitude: float = 40.7128, longitude: float = -74.0060) -> WeatherData | None:
        """Fetch weather via cloud API (default: NYC coordinates)."""
        if not self.weather_adapter:
            return None

        return await self.weather_adapter.get_weather(latitude, longitude)

    async def _fetch_commute(self, from_addr: str, to_addr: str) -> CommuteData | None:
        """Fetch commute via Google Maps API (cloud)."""
        if not self.maps_adapter:
            return None

        return await self.maps_adapter.get_commute(from_addr, to_addr)

    def _generate_calendar_summary(self, events: list[CalendarEvent]) -> str:
        """Generate text summary of calendar events."""
        event_titles = [e.title for e in events]
        if not event_titles:
            return "You have no events scheduled for today"
        return f"You have {len(event_titles)} events today: {', '.join(event_titles)}"

    async def run(self, state: AgentState) -> AgentState:
        """Execute the planning agent."""
        await self.debug_logger.log_agent_start("PlanningAgent")

        # Create Langfuse trace
        trace = self.langfuse_tracer.trace_agent("PlanningAgent", state.run_id, state.user_id) if self.langfuse_tracer else None

        try:
            target_date = date.today()

            # Fetch calendar events
            start_time = time.time()
            events = await self._fetch_calendar_events(state.user_id, target_date)
            calendar_latency = int((time.time() - start_time) * 1000)

            if trace:
                trace.span(
                    "fetch_calendar",
                    input_data={"user_id": state.user_id, "date": target_date.isoformat()},
                    output_data={"events_count": len(events)},
                    latency_ms=calendar_latency,
                )

            # Fetch weather
            start_time = time.time()
            weather = await self._fetch_weather()
            weather_latency = int((time.time() - start_time) * 1000)

            if trace:
                trace.span(
                    "fetch_weather",
                    output_data={"condition": weather.condition if weather else None},
                    latency_ms=weather_latency,
                )

            # Fetch commute (TODO: load from user preferences)
            start_time = time.time()
            commute = await self._fetch_commute("123 Main St, New York, NY", "456 Work Ave, New York, NY")
            commute_latency = int((time.time() - start_time) * 1000)

            if trace:
                trace.span(
                    "fetch_commute",
                    output_data={"duration_minutes": commute.estimated_duration_minutes if commute else None},
                    latency_ms=commute_latency,
                )

            # Generate summaries
            calendar_summary = self._generate_calendar_summary(events)
            weather_summary = f"{weather.condition} and {weather.temperature_high}°F" if weather else "Unable to fetch weather"
            commute_summary = f"{commute.estimated_duration_minutes} minute commute" if commute else "No commute data"

            # Build plan
            plan = DailyPlanData(
                calendar_events=events,
                calendar_summary=calendar_summary,
                weather=weather,
                weather_summary=weather_summary,
                commute=commute,
                commute_summary=commute_summary,
                workout_recommendation=WorkoutRecommendation(
                    duration_minutes=30,
                    recommended_time="morning",
                ),
            )

            state.plan = plan

            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="plan_generated",
                message="Daily plan generated successfully",
                output_payload={
                    "events_count": len(events),
                    "has_weather": weather is not None,
                    "has_commute": commute is not None,
                },
            )

            if trace:
                trace.end(output_data={
                    "events_count": len(events),
                    "has_weather": weather is not None,
                    "has_commute": commute is not None,
                })

            await self.debug_logger.log_agent_end("PlanningAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="plan_generation_failed",
                level="error",
                message=f"Failed to generate plan: {str(e)}",
                error=str(e),
            )

            if trace:
                trace.end(error=str(e))

            await self.debug_logger.log_agent_end("PlanningAgent", success=False)
            state.error = str(e)

        return state
