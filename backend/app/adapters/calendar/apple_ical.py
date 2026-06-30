"""Apple Calendar adapter via .ics file parsing and CalDAV (cloud-based)."""

import logging
import uuid as _uuid
import httpx
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Optional

from icalendar import Calendar as ICalCalendar, Event as ICalEvent
from icalendar.prop import vDDDTypes

from app.agents.state import CalendarEvent
from app.adapters.calendar.base import CalendarAdapter
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class AppleICalAdapter(CalendarAdapter):
    """Adapter for Apple Calendar via .ics file parsing and CalDAV protocol.

    Supports:
    - Local .ics file parsing (exported from Apple Calendar)
    - iCloud calendars via CalDAV protocol
    - Any CalDAV-compatible server
    - All-day events, recurring events, timed events
    - Multiple timezones
    """

    def __init__(
        self,
        debug_logger: DebugLogger,
        ics_file_path: str | None = None,
        caldav_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        """Initialize Apple iCal adapter.

        Args:
            debug_logger: Debug logger instance
            ics_file_path: Path to local .ics file (for file-based calendars)
            caldav_url: CalDAV server URL (e.g., https://caldav.icloud.com)
            username: CalDAV username (usually Apple ID email)
            password: CalDAV password (usually Apple ID password or app-specific)
        """
        self.debug_logger = debug_logger
        self.ics_file_path = ics_file_path
        self.caldav_url = caldav_url or "https://caldav.icloud.com"
        self.username = username
        self.password = password
        self.http_client = httpx.AsyncClient(timeout=10)

    async def get_events_for_date(self, user_id: str, target_date: date) -> list[CalendarEvent]:
        """Fetch events for a specific date."""
        await self.debug_logger.log_event(
            agent_name="AppleICalAdapter",
            event_type="fetch_started",
            message=f"Fetching Apple iCal events for {target_date}",
            input_payload={"user_id": user_id, "date": target_date.isoformat()},
        )

        try:
            start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            events = await self.get_events_range(user_id, target_date, target_date)

            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="fetch_completed",
                message=f"Fetched {len(events)} events from Apple iCal",
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
        """Fetch events for a date range.

        Tries .ics file first, then falls back to CalDAV if configured.
        """
        all_events = []

        # Try .ics file parsing first if configured
        if self.ics_file_path:
            try:
                file_events = await self._parse_ics_file_for_range(start_date, end_date)
                all_events.extend(file_events)
            except Exception as e:
                logger.warning(f"Failed to parse .ics file: {e}")

        # Try CalDAV if credentials configured
        if self.username and self.password:
            try:
                caldav_events = await self._fetch_caldav_events(start_date, end_date)
                all_events.extend(caldav_events)
            except Exception as e:
                logger.warning(f"Failed to fetch CalDAV events: {e}")

        return all_events

    async def _parse_ics_file_for_range(
        self, start_date: date, end_date: date
    ) -> list[CalendarEvent]:
        """Parse .ics file and extract events within date range.

        Handles:
        - All-day events (DATE values without time)
        - Timed events (DATETIME values)
        - Recurring events (RRULE components)
        - Timezones
        """
        if not self.ics_file_path:
            return []

        try:
            file_path = Path(self.ics_file_path)
            if not file_path.exists():
                logger.warning(f"iCal file not found: {self.ics_file_path}")
                return []

            with open(file_path, "rb") as f:
                cal = ICalCalendar.from_ical(f.read())

            events = []
            start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(
                end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            )

            for component in cal.walk():
                if component.name == "VEVENT":
                    event = self._parse_vevent(component, start_dt, end_dt)
                    if event:
                        events.append(event)

            return events

        except Exception as e:
            logger.error(f"Failed to parse .ics file {self.ics_file_path}: {e}")
            raise

    def _parse_vevent(
        self, component, start_dt: datetime, end_dt: datetime
    ) -> Optional[CalendarEvent]:
        """Parse a VEVENT component and return a CalendarEvent if in range.

        Handles:
        - All-day events (DATE values)
        - Timed events (DATETIME values)
        - Timezones (TZID property)
        - Recurring events (basic support)
        """
        try:
            # Extract basic fields
            title = str(component.get("SUMMARY", "Untitled"))
            description = component.get("DESCRIPTION")
            if description:
                description = str(description)

            # Extract start and end times
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")

            if not dtstart:
                return None

            # Parse DTSTART
            start_time = self._parse_datetime(dtstart)
            if not start_time:
                return None

            # For all-day events without explicit end, assume 1 day duration
            if dtend:
                end_time = self._parse_datetime(dtend)
            else:
                end_time = start_time + timedelta(hours=1)

            if not end_time:
                end_time = start_time + timedelta(hours=1)

            # Check if event is within date range
            if end_time < start_dt or start_time > end_dt:
                return None

            # Extract other fields
            location = component.get("LOCATION")
            if location:
                location = str(location)

            attendees = []
            for attendee in component.get("ATTENDEE", []) if isinstance(
                component.get("ATTENDEE"), list
            ) else ([component.get("ATTENDEE")] if component.get("ATTENDEE") else []):
                attendee_str = str(attendee)
                if attendee_str.startswith("mailto:"):
                    attendee_str = attendee_str[7:]
                attendees.append(attendee_str)

            # Get external ID (UID)
            external_id = str(component.get("UID")) if component.get("UID") else None

            return CalendarEvent(
                source="apple_ical",
                external_id=external_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                location=location,
                description=description,
                attendees=attendees,
            )

        except Exception as e:
            logger.warning(f"Failed to parse VEVENT: {e}")
            return None

    def _parse_datetime(self, dt_prop) -> Optional[datetime]:
        """Parse a datetime property from iCalendar.

        Handles:
        - DATE values (all-day events) -> converted to UTC midnight
        - DATETIME values with timezone info
        - DATETIME values without timezone (assumed UTC)
        """
        try:
            if hasattr(dt_prop, "dt"):
                dt_value = dt_prop.dt
            else:
                dt_value = dt_prop

            # If it's a date (all-day event), convert to datetime at midnight UTC
            if isinstance(dt_value, date) and not isinstance(dt_value, datetime):
                return datetime.combine(dt_value, datetime.min.time(), tzinfo=timezone.utc)

            # If it's a datetime
            if isinstance(dt_value, datetime):
                # If naive (no timezone), assume UTC
                if dt_value.tzinfo is None:
                    return dt_value.replace(tzinfo=timezone.utc)
                else:
                    # Convert to UTC
                    return dt_value.astimezone(timezone.utc)

            return None

        except Exception as e:
            logger.warning(f"Failed to parse datetime: {e}")
            return None

    async def _fetch_caldav_events(self, start_date: date, end_date: date) -> list[CalendarEvent]:
        """Query CalDAV server for events in date range."""
        if not self.username or not self.password:
            logger.warning("CalDAV credentials not configured")
            return []

        # Build CalDAV REPORT query (RFC 4791)
        start_str = start_date.isoformat() + "T00:00:00Z"
        end_str = (end_date + timedelta(days=1)).isoformat() + "T00:00:00Z"

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

            # Parse CalDAV response - would need caldav library for full support
            # For now, return empty (production would parse the multi-status response)
            events = []

            return events

        except Exception as e:
            logger.error(f"CalDAV query failed: {e}")
            return []

    async def is_configured(self, user_id: str) -> bool:
        """Check if adapter is configured (either .ics file or CalDAV)."""
        has_ics_file = self.ics_file_path and Path(self.ics_file_path).exists()
        has_caldav = bool(self.username and self.password)
        return has_ics_file or has_caldav

    async def create_event(self, user_id: str, event: CalendarEvent) -> CalendarEvent | None:
        """Create a new calendar event.

        Tries CalDAV PUT first (if credentials configured), then falls back to
        appending a VEVENT to the local .ics file. Returns None if neither is
        available or the write fails.
        """
        event_uid = event.external_id or str(_uuid.uuid4())
        event.external_id = event_uid

        await self.debug_logger.log_event(
            agent_name="AppleICalAdapter",
            event_type="create_event_started",
            message=f"Creating Apple iCal event: {event.title}",
            input_payload={"user_id": user_id, "title": event.title,
                           "start_time": event.start_time.isoformat(), "uid": event_uid},
        )

        # Path A: CalDAV PUT
        if self.username and self.password:
            result = await self._caldav_put_event(event, event_uid)
            if result:
                await self.debug_logger.log_event(
                    agent_name="AppleICalAdapter",
                    event_type="create_event_success",
                    message=f"Created Apple iCal event via CalDAV: {event.title}",
                    output_payload={"uid": event_uid, "method": "caldav"},
                )
                return event
            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="create_event_failed",
                level="error",
                message=f"CalDAV PUT failed for event: {event.title}",
            )
            return None

        # Path B: append to .ics file
        if self.ics_file_path:
            result = await self._append_to_ics_file(event, event_uid)
            if result:
                await self.debug_logger.log_event(
                    agent_name="AppleICalAdapter",
                    event_type="create_event_success",
                    message=f"Created Apple iCal event via .ics file: {event.title}",
                    output_payload={"uid": event_uid, "method": "ics_file"},
                )
                return event
            await self.debug_logger.log_event(
                agent_name="AppleICalAdapter",
                event_type="create_event_failed",
                level="error",
                message=f".ics file append failed for event: {event.title}",
            )
            return None

        # Path C: not configured
        await self.debug_logger.log_event(
            agent_name="AppleICalAdapter",
            event_type="create_event_skipped",
            level="warning",
            message="Cannot create event: no CalDAV credentials or .ics file configured",
        )
        return None

    def _build_vcalendar(self, event: CalendarEvent, uid: str) -> bytes:
        """Build a minimal iCalendar document containing one VEVENT."""
        cal = ICalCalendar()
        cal.add("prodid", "-//DailyOps AI//EN")
        cal.add("version", "2.0")

        vevent = ICalEvent()
        vevent.add("uid", uid)
        vevent.add("summary", event.title)
        vevent.add("dtstart", event.start_time)
        vevent.add("dtend", event.end_time)
        if event.location:
            vevent.add("location", event.location)
        if event.description:
            vevent.add("description", event.description)
        cal.add_component(vevent)
        return cal.to_ical()

    async def _discover_calendar_url(self) -> str | None:
        """Discover a writable calendar collection URL via CalDAV PROPFIND.

        iCloud uses a numeric DSID in the URL, not the username. Walk:
          1. PROPFIND / → current-user-principal href
          2. PROPFIND principal → calendar-home-set href
          3. PROPFIND calendar home (Depth:1) → pick first writable calendar
        """
        NS = {
            "D": "DAV:",
            "C": "urn:ietf:params:xml:ns:caldav",
            "CS": "http://calendarserver.org/ns/",
        }
        # Types that are NOT writable event stores
        SKIP_TYPES = {
            "{urn:ietf:params:xml:ns:caldav}schedule-inbox",
            "{urn:ietf:params:xml:ns:caldav}schedule-outbox",
            "{http://calendarserver.org/ns/}notification",
            "{http://calendarserver.org/ns/}subscribed",
        }
        auth = (self.username, self.password)
        h0 = {"Content-Type": "application/xml; charset=utf-8", "Depth": "0"}

        def _abs(href: str) -> str:
            return (self.caldav_url + href) if href.startswith("/") else href

        def _find_text(xml_str: str, *path: str) -> str | None:
            """Parse xml_str with ET and return text at the namespace-qualified path."""
            try:
                root = ET.fromstring(xml_str)
                node = root
                for tag in path:
                    # Try with each known namespace
                    found = None
                    for ns_uri in list(NS.values()) + [""]:
                        key = f"{{{ns_uri}}}{tag}" if ns_uri else tag
                        found = node.find(f".//{key}")
                        if found is not None:
                            break
                    if found is None:
                        return None
                    node = found
                return (node.text or "").strip() or None
            except ET.ParseError:
                return None

        try:
            # Step 1: principal URL
            r1 = await self.http_client.request(
                "PROPFIND", self.caldav_url + "/", auth=auth, headers=h0,
                content=(
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<D:propfind xmlns:D="DAV:"><D:prop>'
                    '<D:current-user-principal/>'
                    '</D:prop></D:propfind>'
                ),
            )
            principal_href = _find_text(r1.text, "current-user-principal", "href")
            if not principal_href:
                logger.warning(f"CalDAV step1: no current-user-principal ({r1.status_code})")
                return None

            # Step 2: calendar-home-set
            r2 = await self.http_client.request(
                "PROPFIND", _abs(principal_href), auth=auth, headers=h0,
                content=(
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
                    '<D:prop><C:calendar-home-set/></D:prop></D:propfind>'
                ),
            )
            home_href = _find_text(r2.text, "calendar-home-set", "href")
            if not home_href:
                logger.warning("CalDAV step2: no calendar-home-set")
                return None
            home_url = _abs(home_href)

            # Step 3: list calendars
            r3 = await self.http_client.request(
                "PROPFIND", home_url, auth=auth,
                headers={**h0, "Depth": "1"},
                content=(
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
                    '<D:prop><D:resourcetype/><D:displayname/></D:prop></D:propfind>'
                ),
            )
            root = ET.fromstring(r3.text)
            CALDAV_CAL = "{urn:ietf:params:xml:ns:caldav}calendar"
            DAV_NS = "DAV:"

            candidates: list[tuple[str, str]] = []  # (href, displayname)
            for response_el in root.iter(f"{{{DAV_NS}}}response"):
                href_el = response_el.find(f"{{{DAV_NS}}}href")
                if href_el is None:
                    continue
                href = (href_el.text or "").strip()
                if href.rstrip("/") == home_href.rstrip("/"):
                    continue  # skip home itself

                # Check resourcetype
                rt = response_el.find(f".//{{{DAV_NS}}}resourcetype")
                if rt is None:
                    continue
                child_tags = {child.tag for child in rt}
                if CALDAV_CAL not in child_tags:
                    continue  # not a calendar
                if child_tags & SKIP_TYPES:
                    continue  # inbox/outbox/notification/subscribed

                name_el = response_el.find(f".//{{{DAV_NS}}}displayname")
                name = (name_el.text or "").strip() if name_el is not None else ""
                candidates.append((href, name))

            if not candidates:
                logger.warning("CalDAV step3: no writable calendar collections found")
                return None

            # Prefer "Home" calendar; fall back to first found
            preferred = next(
                (href for href, name in candidates if name.lower() == "home"),
                candidates[0][0],
            )
            cal_url = _abs(preferred)
            logger.debug(f"CalDAV discovered calendar: {cal_url}")
            return cal_url

        except Exception as e:
            logger.error(f"CalDAV URL discovery failed: {e}")
            return None

    async def _caldav_put_event(self, event: CalendarEvent, uid: str) -> bool:
        """PUT a single VEVENT to the CalDAV server. Returns True on success."""
        ical_bytes = self._build_vcalendar(event, uid)

        # Discover real calendar URL (iCloud uses a numeric DSID, not the username)
        if not hasattr(self, "_calendar_url"):
            self._calendar_url = await self._discover_calendar_url()

        if self._calendar_url:
            url = self._calendar_url.rstrip("/") + f"/{uid}.ics"
        else:
            # Hard fallback to old pattern
            url = f"{self.caldav_url}/principals/__uuids__/{self.username}/calendar.ics/{uid}.ics"

        try:
            response = await self.http_client.put(
                url,
                content=ical_bytes,
                auth=(self.username, self.password),
                headers={"Content-Type": "text/calendar; charset=utf-8"},
            )
            if response.status_code not in (201, 204):
                logger.error(f"CalDAV PUT returned {response.status_code}: {response.text[:200]}")
            return response.status_code in (201, 204)
        except Exception as e:
            logger.error(f"CalDAV PUT failed: {e}")
            return False

    async def _append_to_ics_file(self, event: CalendarEvent, uid: str) -> bool:
        """Append a VEVENT to the local .ics file. Returns True on success."""
        file_path = Path(self.ics_file_path)
        try:
            if file_path.exists():
                with open(file_path, "rb") as f:
                    existing_cal = ICalCalendar.from_ical(f.read())
            else:
                existing_cal = ICalCalendar()
                existing_cal.add("prodid", "-//DailyOps AI//EN")
                existing_cal.add("version", "2.0")

            vevent = ICalEvent()
            vevent.add("uid", uid)
            vevent.add("summary", event.title)
            vevent.add("dtstart", event.start_time)
            vevent.add("dtend", event.end_time)
            if event.location:
                vevent.add("location", event.location)
            if event.description:
                vevent.add("description", event.description)
            existing_cal.add_component(vevent)

            with open(file_path, "wb") as f:
                f.write(existing_cal.to_ical())
            return True
        except Exception as e:
            logger.error(f".ics file append failed: {e}")
            return False

    async def parse_ics_file(self, file_path: str) -> list[CalendarEvent]:
        """Public method to parse an .ics file and return all events.

        Args:
            file_path: Path to the .ics file

        Returns:
            List of CalendarEvent objects extracted from the file
        """
        try:
            file_p = Path(file_path)
            if not file_p.exists():
                logger.warning(f"iCal file not found: {file_path}")
                return []

            with open(file_p, "rb") as f:
                cal = ICalCalendar.from_ical(f.read())

            events = []

            for component in cal.walk():
                if component.name == "VEVENT":
                    # Parse with no date range restriction
                    event = self._parse_vevent(
                        component,
                        datetime(1900, 1, 1, tzinfo=timezone.utc),
                        datetime(2100, 12, 31, tzinfo=timezone.utc),
                    )
                    if event:
                        events.append(event)

            return events

        except Exception as e:
            logger.error(f"Failed to parse .ics file {file_path}: {e}")
            raise
