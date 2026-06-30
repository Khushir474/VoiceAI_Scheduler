"""Google Calendar adapter implementation with OAuth 2.0."""

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.agents.state import CalendarEvent
from app.adapters.calendar.base import CalendarAdapter
from app.services.logger import DebugLogger
from app.config import Settings

logger = logging.getLogger(__name__)

# Google Calendar API constants
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3"
# Requires calendar.events (write) scope — re-run OAuth consent if token was issued
# with calendar.readonly only. See .env.template for setup instructions.
GOOGLE_CALENDAR_SCOPES = "https://www.googleapis.com/auth/calendar.events"

# Rate limiting constants
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 32
RATE_LIMIT_THRESHOLD = 429  # HTTP status for rate limit


class GoogleCalendarAdapter(CalendarAdapter):
    """Adapter for Google Calendar API with OAuth 2.0 authentication."""

    def __init__(self, debug_logger: DebugLogger, settings: Settings):
        """Initialize Google Calendar adapter.

        Args:
            debug_logger: Debug logger instance
            settings: Application settings with Google credentials
        """
        self.debug_logger = debug_logger
        self.settings = settings
        self.client_id = settings.google_calendar_client_id
        self.client_secret = settings.google_calendar_client_secret
        self.refresh_token = settings.google_calendar_refresh_token
        self.access_token = settings.google_calendar_access_token
        self.token_expiry = settings.google_calendar_token_expiry

        # HTTP client for API calls
        self.http_client: httpx.AsyncClient | None = None
        self._token_lock = asyncio.Lock()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=30.0)
        return self.http_client

    async def _refresh_access_token(self) -> bool:
        """Refresh Google OAuth access token using refresh token.

        Returns:
            True if successful, False otherwise
        """
        if not self.refresh_token:
            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="auth_failed",
                level="error",
                message="No refresh token configured for Google Calendar",
            )
            return False

        try:
            client = await self._get_http_client()
            start_time = time.time()

            response = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                error_msg = f"OAuth token refresh failed: {response.status_code}"
                await self.debug_logger.log_event(
                    agent_name="GoogleCalendarAdapter",
                    event_type="oauth_refresh_failed",
                    level="error",
                    message=error_msg,
                    error=response.text,
                    latency_ms=latency_ms,
                )
                return False

            data = response.json()
            self.access_token = data.get("access_token")

            # Calculate expiry (expires_in seconds from now)
            if "expires_in" in data:
                expires_in = data["expires_in"]
                expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                self.token_expiry = expiry.isoformat()

            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="oauth_refresh_succeeded",
                message="Successfully refreshed Google Calendar access token",
                latency_ms=latency_ms,
            )

            return True

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="oauth_refresh_error",
                level="error",
                message=f"Exception during OAuth token refresh: {str(e)}",
                error=str(e),
            )
            return False

    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token, refreshing if needed.

        Returns:
            True if we have a valid token, False otherwise
        """
        async with self._token_lock:
            # Check if token exists and is not expired
            if self.access_token:
                if self.token_expiry:
                    expiry = datetime.fromisoformat(self.token_expiry)
                    now = datetime.now(timezone.utc)
                    # Refresh 5 minutes before expiry
                    if now < expiry - timedelta(minutes=5):
                        return True
                else:
                    # No expiry time, assume token is valid
                    return True

            # Token missing or expired, refresh it
            return await self._refresh_access_token()

    async def _make_api_call_with_retry(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, bool, int]:
        """Make API call with exponential backoff retry.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to call
            headers: Optional headers
            params: Optional query parameters

        Returns:
            Tuple of (response_data, success, latency_ms)
        """
        backoff = INITIAL_BACKOFF_SECONDS
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                client = await self._get_http_client()
                start_time = time.time()

                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                )

                latency_ms = int((time.time() - start_time) * 1000)

                if response.status_code == 200:
                    return response.json(), True, latency_ms
                elif response.status_code == RATE_LIMIT_THRESHOLD:
                    # Rate limited, retry with backoff
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                        continue
                    else:
                        return None, False, latency_ms
                elif response.status_code == 401:
                    # Unauthorized, try refreshing token
                    if attempt < MAX_RETRIES - 1:
                        refreshed = await self._refresh_access_token()
                        if refreshed:
                            headers = headers or {}
                            headers["Authorization"] = f"Bearer {self.access_token}"
                            continue
                    return None, False, latency_ms
                else:
                    # Other error
                    return None, False, latency_ms

            except Exception as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    continue
                else:
                    return None, False, 0

        return None, False, 0

    async def get_events_for_date(self, user_id: str, target_date: date) -> list[CalendarEvent]:
        """Fetch events from Google Calendar for a specific date.

        Args:
            user_id: User identifier
            target_date: Target date to fetch events for

        Returns:
            List of CalendarEvent objects
        """
        return await self.get_events_range(user_id, target_date, target_date)

    async def get_events_range(
        self, user_id: str, start_date: date, end_date: date
    ) -> list[CalendarEvent]:
        """Fetch events from Google Calendar for a date range.

        Args:
            user_id: User identifier
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of CalendarEvent objects
        """
        start_iso = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_iso = end_date.isoformat() if isinstance(end_date, date) else end_date

        await self.debug_logger.log_event(
            agent_name="GoogleCalendarAdapter",
            event_type="fetch_started",
            message=f"Fetching Google Calendar events from {start_iso} to {end_iso}",
            input_payload={
                "user_id": user_id,
                "start_date": start_iso,
                "end_date": end_iso,
            },
        )

        try:
            # Ensure we have a valid token
            if not await self._ensure_valid_token():
                raise ValueError("Unable to obtain valid Google Calendar access token")

            client = await self._get_http_client()

            # Convert dates to RFC 3339 format for Google Calendar API
            start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            }

            params = {
                "calendarId": "primary",
                "timeMin": start_datetime.isoformat(),
                "timeMax": end_datetime.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 100,
            }

            url = f"{GOOGLE_CALENDAR_API_URL}/calendars/primary/events"

            data, success, latency_ms = await self._make_api_call_with_retry(
                "GET",
                url,
                headers=headers,
                params=params,
            )

            if not success:
                await self.debug_logger.log_event(
                    agent_name="GoogleCalendarAdapter",
                    event_type="fetch_failed",
                    level="error",
                    message="Failed to fetch events from Google Calendar API",
                    latency_ms=latency_ms,
                )
                return []

            # Parse events from response
            events: list[CalendarEvent] = []
            items = data.get("items", [])

            for item in items:
                try:
                    event = self._parse_google_event(item)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to parse Google Calendar event: {e}")
                    continue

            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="fetch_completed",
                message=f"Successfully fetched {len(events)} events from Google Calendar",
                output_payload={
                    "count": len(events),
                    "start_date": start_iso,
                    "end_date": end_iso,
                },
                latency_ms=latency_ms,
            )

            return events

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="fetch_error",
                level="error",
                message=f"Exception fetching Google Calendar events: {str(e)}",
                error=str(e),
            )
            return []

    def _parse_google_event(self, google_event: dict[str, Any]) -> CalendarEvent | None:
        """Parse a Google Calendar event to CalendarEvent format.

        Args:
            google_event: Raw event from Google Calendar API

        Returns:
            CalendarEvent or None if parsing fails
        """
        try:
            event_id = google_event.get("id")
            title = google_event.get("summary", "Untitled")
            description = google_event.get("description")
            location = google_event.get("location")

            # Handle date/time (can be all-day or specific time)
            start_dict = google_event.get("start", {})
            end_dict = google_event.get("end", {})

            # Handle both dateTime and date formats
            if "dateTime" in start_dict:
                start_time = datetime.fromisoformat(start_dict["dateTime"].replace("Z", "+00:00"))
            elif "date" in start_dict:
                start_time = datetime.combine(
                    date.fromisoformat(start_dict["date"]),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
            else:
                return None

            if "dateTime" in end_dict:
                end_time = datetime.fromisoformat(end_dict["dateTime"].replace("Z", "+00:00"))
            elif "date" in end_dict:
                end_time = datetime.combine(
                    date.fromisoformat(end_dict["date"]),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
            else:
                end_time = start_time + timedelta(hours=1)

            # Get attendees
            attendees: list[str] = []
            for attendee in google_event.get("attendees", []):
                if "email" in attendee:
                    attendees.append(attendee["email"])

            return CalendarEvent(
                source="google_calendar",
                external_id=event_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                location=location,
                description=description,
                attendees=attendees,
            )
        except Exception as e:
            logger.warning(f"Error parsing Google event: {e}")
            return None

    async def _post_api_call(
        self,
        url: str,
        headers: dict[str, str],
        json_body: dict,
    ) -> tuple[dict | None, bool, int]:
        """POST JSON to a Google API endpoint with retry on 429/401.

        Returns:
            (response_data, success, latency_ms)
        """
        backoff = INITIAL_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            try:
                client = await self._get_http_client()
                start_time = time.time()
                response = await client.post(url, headers=headers, json=json_body)
                latency_ms = int((time.time() - start_time) * 1000)

                if response.status_code == 200:
                    return response.json(), True, latency_ms
                elif response.status_code == RATE_LIMIT_THRESHOLD:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                        continue
                    return None, False, latency_ms
                elif response.status_code == 401:
                    if attempt < MAX_RETRIES - 1:
                        refreshed = await self._refresh_access_token()
                        if refreshed:
                            headers["Authorization"] = f"Bearer {self.access_token}"
                            continue
                    return None, False, latency_ms
                else:
                    return None, False, latency_ms

            except Exception:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    continue
                return None, False, 0

        return None, False, 0

    async def create_event(self, user_id: str, event: CalendarEvent) -> CalendarEvent | None:
        """Create a new event in Google Calendar.

        Uses POST /calendars/primary/events. Sets event.external_id on success.
        """
        await self.debug_logger.log_event(
            agent_name="GoogleCalendarAdapter",
            event_type="create_event_started",
            message=f"Creating Google Calendar event: {event.title}",
            input_payload={"user_id": user_id, "title": event.title,
                           "start_time": event.start_time.isoformat()},
        )

        if not await self._ensure_valid_token():
            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="create_event_failed",
                level="error",
                message="Cannot create event: no valid access token",
            )
            return None

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body: dict = {
            "summary": event.title,
            "start": {"dateTime": event.start_time.isoformat()},
            "end": {"dateTime": event.end_time.isoformat()},
        }
        if event.location:
            body["location"] = event.location
        if event.description:
            body["description"] = event.description
        if event.attendees:
            body["attendees"] = [{"email": addr} for addr in event.attendees]

        url = f"{GOOGLE_CALENDAR_API_URL}/calendars/primary/events"
        data, success, latency_ms = await self._post_api_call(url, headers, body)

        if success and data:
            event.external_id = data.get("id")
            await self.debug_logger.log_event(
                agent_name="GoogleCalendarAdapter",
                event_type="create_event_success",
                message=f"Created Google Calendar event: {event.title} (id={event.external_id})",
                output_payload={"event_id": event.external_id, "title": event.title},
                latency_ms=latency_ms,
            )
            return event

        await self.debug_logger.log_event(
            agent_name="GoogleCalendarAdapter",
            event_type="create_event_failed",
            level="error",
            message=f"Failed to create Google Calendar event: {event.title}",
            latency_ms=latency_ms,
        )
        return None

    async def is_configured(self, user_id: str) -> bool:
        """Check if Google Calendar is configured with valid credentials.

        Args:
            user_id: User identifier (not used for OAuth, would be for DB lookup)

        Returns:
            True if credentials exist and token can be obtained
        """
        if not self.client_id or not self.client_secret or not self.refresh_token:
            return False

        # Try to ensure we have a valid token
        return await self._ensure_valid_token()

    async def close(self) -> None:
        """Close HTTP client connections."""
        if self.http_client:
            await self.http_client.aclose()
