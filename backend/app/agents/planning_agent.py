"""Planning Agent: Fetches data and builds the daily plan."""

import json
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
from app.services.logger import DebugLogger
from app.services.calendar_merge import CalendarMerger


class PlanningAgent:
    """Planning Agent: Gathers data and builds a daily plan."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        calendar_adapters: list[CalendarAdapter],
    ):
        self.debug_logger = debug_logger
        self.calendar_adapters = calendar_adapters
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

    async def _fetch_weather(self, user_id: str, location: str) -> WeatherData | None:
        """Fetch weather for the day."""
        await self.debug_logger.log_event(
            agent_name="PlanningAgent",
            event_type="weather_fetch_start",
            message=f"Fetching weather for {location}",
            input_payload={"location": location},
        )

        # TODO: Implement weather API call
        # For MVP, return mock data
        try:
            weather = WeatherData(
                temperature_high=72,
                temperature_low=62,
                condition="sunny",
                humidity=65,
                wind_speed_mph=10,
                precipitation_probability=10,
                uv_index=6,
                sunrise=datetime.now(timezone.utc).replace(hour=6, minute=30),
                sunset=datetime.now(timezone.utc).replace(hour=19, minute=30),
            )

            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="weather_fetch_complete",
                message="Weather fetched successfully",
                output_payload=weather.model_dump(),
            )

            return weather
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="weather_fetch_error",
                level="error",
                message=f"Failed to fetch weather: {str(e)}",
                error=str(e),
            )
            return None

    async def _fetch_commute(self, from_addr: str, to_addr: str) -> CommuteData | None:
        """Fetch commute estimate."""
        await self.debug_logger.log_event(
            agent_name="PlanningAgent",
            event_type="commute_fetch_start",
            message="Fetching commute estimate",
            input_payload={"from": from_addr, "to": to_addr},
        )

        # TODO: Implement Google Maps API call
        # For MVP, return mock data
        try:
            commute = CommuteData(
                from_address=from_addr,
                to_address=to_addr,
                estimated_duration_minutes=30,
                traffic_condition="moderate",
                departure_time=None,
            )

            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="commute_fetch_complete",
                message=f"Commute estimate: {commute.estimated_duration_minutes} minutes",
                output_payload=commute.model_dump(),
            )

            return commute
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="PlanningAgent",
                event_type="commute_fetch_error",
                level="error",
                message=f"Failed to fetch commute: {str(e)}",
                error=str(e),
            )
            return None

    def _generate_plan_summary(self, plan: DailyPlanData) -> str:
        """Generate text summaries for different parts of the plan."""
        event_titles = [e.title for e in plan.calendar_events]
        return f"You have {len(event_titles)} events today: {', '.join(event_titles)}"

    async def run(self, state: AgentState) -> AgentState:
        """Execute the planning agent."""
        await self.debug_logger.log_agent_start("PlanningAgent")

        try:
            target_date = date.today()

            # Fetch calendar events
            events = await self._fetch_calendar_events(state.user_id, target_date)

            # Fetch weather
            weather = await self._fetch_weather(state.user_id, "New York")

            # Fetch commute (mock home address)
            commute = await self._fetch_commute("Home", "Work")

            # Build plan
            plan = DailyPlanData(
                calendar_events=events,
                calendar_summary=self._generate_plan_summary(DailyPlanData(calendar_events=events)),
                weather=weather,
                weather_summary=f"Sunny and {weather.temperature_high}°F" if weather else "Unable to fetch weather",
                commute=commute,
                commute_summary=f"{commute.estimated_duration_minutes} minute commute" if commute else "No commute data",
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
