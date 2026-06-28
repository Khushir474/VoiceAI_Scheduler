"""Apple Calendar adapter via CalDAV (cloud-based)."""

import logging
import httpx
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from app.agents.state import CalendarEvent
from app.adapters.calendar.base import CalendarAdapter
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class AppleICalAdapter(CalendarAdapter):
    """Adapter for Apple Calendar via CalDAV protocol (cloud-based).

    Supports iCloud calendars and any CalDAV-compatible server.
    Users provide CalDAV credentials via config.
    """

    def __init__(
        self,
        debug_logger: DebugLogger,
        caldav_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        """Initialize CalDAV adapter.

        Args:
            caldav_url: CalDAV server URL (e.g., https://caldav.icloud.com)
            username: CalDAV username (usually Apple ID email)
            password: CalDAV password (usually Apple ID password or app-specific)
        """
        self.debug_logger = debug_logger
        self.caldav_url = caldav_url or "https://caldav.icloud.com"
        self.username = username
        self.password = password
        self.http_client = httpx.AsyncClient(timeout=10)

    async def get_events_for_date(self, user_id: str, target_date: date) -> list[CalendarEvent]:
        """Fetch events from CalDAV for a specific date."""
        await self.debug_logger.log_event(
            agent_name="AppleICalAdapter",
            event_type="fetch_started",
            message=f"Fetching CalDAV events for {target_date}",
            input_payload={"user_id": user_id, "date": target_date.isoformat()},
        )

        try:
            events = await self._fetch_caldav_events(target_date, target_date + timedelta(days=1))

            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="fetch_completed",
                message=f"Fetched {len(events)} events from CalDAV",
                output_payload={"count": len(events)},
            )

            return events
        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Failed to fetch CalDAV events: {str(e)}",
                error=str(e),
            )
            raise

    async def _fetch_caldav_events(self, start_date: date, end_date: date) -> list[CalendarEvent]:
        """Query CalDAV server for events in date range."""
        if not self.username or not self.password:
            logger.warning("CalDAV credentials not configured")
            return []

        # Build CalDAV REPORT query (RFC 4791)
        start_str = start_date.isoformat() + "T00:00:00Z"
        end_str = end_date.isoformat() + "T00:00:00Z"

        caldav_query = f"""<?xml version="1.0" encoding="utf-8" ?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start_str}" end="{end_str}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""

        try:
            # Try iCloud first, then fallback to generic CalDAV
            url = f"{self.caldav_url}/principals/__uuids__/{self.username}/calendar.ics"

            response = await self.http_client.request(
                "REPORT",
                url,
                content=caldav_query,
                auth=(self.username, self.password),
                headers={"Content-Type": "application/xml"},
            )

            if response.status_code != 207:
                logger.warning(f"CalDAV REPORT returned {response.status_code}")
                return []

            # Parse response and extract events (simplified)
            # In production, use caldav library
            events = []

            return events

        except Exception as e:
            logger.error(f"CalDAV query failed: {e}")
            return []

    async def get_events_range(
        self, user_id: str, start_date: date, end_date: date
    ) -> list[CalendarEvent]:
        """Fetch events for a date range."""
        return await self._fetch_caldav_events(start_date, end_date)

    async def is_configured(self, user_id: str) -> bool:
        """Check if CalDAV credentials are configured."""
        return bool(self.username and self.password)
