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
from app.services.langfuse_tracer import LangfuseTracer, observe, propagate_attributes
from app.services.daily_context import DailyContextService
from app.services.location import LocationService


class PlanningAgent:
    """Planning Agent: Gathers data and builds a daily plan."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        calendar_adapters: list[CalendarAdapter],
        weather_adapter: WeatherAdapter | None = None,
        maps_adapter: MapsAdapter | None = None,
        langfuse_tracer: LangfuseTracer | None = None,
        daily_context_service: DailyContextService | None = None,
        location_service: LocationService | None = None,
    ):
        self.debug_logger = debug_logger
        self.calendar_adapters = calendar_adapters
        self.weather_adapter = weather_adapter
        self.maps_adapter = maps_adapter
        self.langfuse_tracer = langfuse_tracer
        self.calendar_merger = CalendarMerger(debug_logger)
        self.daily_context_service = daily_context_service
        self.location_service = location_service or LocationService(debug_logger)

    @observe(name="fetch-calendar-events", capture_input=False)
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

    @observe(name="fetch-weather", capture_input=False)
    async def _fetch_weather(self, latitude: float, longitude: float) -> WeatherData | None:
        """Fetch weather via cloud API for the detected user coordinates."""
        if not self.weather_adapter:
            return None

        return await self.weather_adapter.get_weather(latitude, longitude)

    @observe(name="fetch-commute", capture_input=False)
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

    @observe(name="planning-agent", capture_input=False, capture_output=False)
    async def run(self, state: AgentState) -> AgentState:
        """Execute the planning agent."""
        await self.debug_logger.log_agent_start("PlanningAgent")

        with propagate_attributes(
            user_id=state.user_id,
            session_id=state.run_id,
            trace_name=f"dailyops-{state.run_id[:8]}",
        ):
            return await self._run_inner(state)

    async def _run_inner(self, state: AgentState) -> AgentState:
        try:
            # Detect location first — lat/lng feed weather; timezone feeds the LLM prompt
            location = await self.location_service.detect_with_fallback()
            target_date = date.today()

            # Fetch data concurrently once we have coordinates
            import asyncio
            events, weather, commute = await asyncio.gather(
                self._fetch_calendar_events(state.user_id, target_date),
                self._fetch_weather(location.lat, location.lng),
                self._fetch_commute(
                    from_addr=f"{location.city}, {location.region}",
                    to_addr=f"{location.city}, {location.region}",
                ),
            )

            # Generate summaries
            calendar_summary = self._generate_calendar_summary(events)
            weather_summary = f"{weather.condition} and {weather.temperature_high}°F" if weather else "Unable to fetch weather"
            commute_summary = f"{commute.estimated_duration_minutes} minute commute" if commute else "No commute data"

            # Build plan — location context stored here, not in settings
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
                user_timezone=location.timezone,
                user_city=location.display_name,
                user_lat=location.lat,
                user_lng=location.lng,
            )

            state.plan = plan

            # Persist to daily_context so the agent can fetch it live during calls
            if self.daily_context_service:
                try:
                    await self.daily_context_service.upsert(state.user_id, plan)
                except Exception as e:
                    await self.debug_logger.log_event(
                        agent_name="PlanningAgent",
                        event_type="daily_context_upsert_error",
                        level="warning",
                        message=f"Failed to persist daily_context: {e}",
                        error=str(e),
                    )

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

            await self.debug_logger.log_agent_end("PlanningAgent", success=True)

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="plan_generation_failed",
                level="error",
                message=f"Failed to generate plan: {str(e)}",
                error=str(e),
            )
            await self.debug_logger.log_agent_end("PlanningAgent", success=False)
            state.error = str(e)

        return state
