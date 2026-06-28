"""Apple iCal adapter implementation."""

import logging
import os
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.agents.state import CalendarEvent
from app.adapters.calendar.base import CalendarAdapter
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class AppleICalAdapter(CalendarAdapter):
    """Adapter for Apple Calendar via iCal files or AppleScript."""

    def __init__(self, debug_logger: DebugLogger, calendar_path: str | None = None):
        self.debug_logger = debug_logger
        self.calendar_path = calendar_path or os.path.expanduser("~/Library/Calendars")

    async def _run_applescript(self, script: str) -> str:
        """Execute AppleScript and return output."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("AppleScript execution timed out")
            raise
        except Exception as e:
            logger.error(f"AppleScript execution failed: {e}")
            raise

    async def get_events_for_date(self, user_id: str, target_date: date) -> list[CalendarEvent]:
        """Fetch events from Apple Calendar for a specific date."""
        await self.debug_logger.log_event(
            agent_name="AppleICalAdapter",
            event_type="fetch_started",
            message=f"Fetching Apple iCal events for {target_date}",
            input_payload={"user_id": user_id, "date": target_date.isoformat()},
        )

        try:
            # AppleScript to fetch Calendar events for a specific date
            date_str = target_date.strftime("%m/%d/%Y")
            script = f"""
            set result to ""
            tell application "Calendar"
                set allEvents to every event of calendar 1 whose start date >= date "{date_str}" and start date < date "{(target_date + timedelta(days=1)).strftime('%m/%d/%Y')}"
                repeat with evt in allEvents
                    set evtTitle to summary of evt
                    set evtStart to start date of evt
                    set evtEnd to end date of evt
                    set evtLocation to location of evt
                    set result to result & evtTitle & "|" & evtStart & "|" & evtEnd & "|" & evtLocation & "##"
                end repeat
            end tell
            result
            """

            # TODO: For MVP, use local .ics parsing instead of AppleScript
            # AppleScript is unreliable in headless/automated contexts

            events = []

            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="fetch_completed",
                message=f"Fetched {len(events)} events from Apple Calendar",
                output_payload={"count": len(events)},
            )

            return events
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Failed to fetch Apple iCal events: {str(e)}",
                error=str(e),
            )
            raise

    async def get_events_range(
        self, user_id: str, start_date: date, end_date: date
    ) -> list[CalendarEvent]:
        """Fetch events for a date range."""
        current = start_date
        all_events = []

        while current <= end_date:
            day_events = await self.get_events_for_date(user_id, current)
            all_events.extend(day_events)
            current += timedelta(days=1)

        return all_events

    async def is_configured(self, user_id: str) -> bool:
        """Check if Apple iCal is available."""
        # Check if Calendar.app is installed
        try:
            await self._run_applescript('tell application "Calendar" to version')
            return True
        except Exception:
            return False
