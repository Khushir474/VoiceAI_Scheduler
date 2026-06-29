"""Tests for Google Calendar adapter with OAuth 2.0."""

import asyncio
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.calendar.google_calendar import GoogleCalendarAdapter
from app.agents.state import CalendarEvent
from app.config import Settings
from app.services.logger import DebugLogger


@pytest.fixture
def mock_settings():
    """Mock settings with Google Calendar credentials."""
    return Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-publishable-key",
        supabase_secret_key="test-secret-key",
        openai_api_key="test-key",
        vapi_api_key="test-key",
        elevenlabs_api_key="test-key",
        google_calendar_client_id="test-client-id",
        google_calendar_client_secret="test-secret",
        google_calendar_refresh_token="test-refresh-token",
    )


@pytest.fixture
def mock_debug_logger():
    """Mock debug logger."""
    logger = AsyncMock(spec=DebugLogger)
    return logger


@pytest.fixture
def adapter(mock_debug_logger, mock_settings):
    """Create a GoogleCalendarAdapter instance."""
    return GoogleCalendarAdapter(mock_debug_logger, mock_settings)


class TestGoogleCalendarAdapterOAuth:
    """Tests for OAuth token refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self, adapter, mock_debug_logger):
        """Test successful OAuth token refresh."""
        mock_response = {
            "access_token": "new-access-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = mock_response

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_http_response

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            result = await adapter._refresh_access_token()

        assert result is True
        assert adapter.access_token == "new-access-token"
        assert adapter.token_expiry is not None
        mock_debug_logger.log_event.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_access_token_no_refresh_token(self, mock_debug_logger, mock_settings):
        """Test refresh fails when refresh token is not configured."""
        mock_settings.google_calendar_refresh_token = ""
        adapter = GoogleCalendarAdapter(mock_debug_logger, mock_settings)

        result = await adapter._refresh_access_token()

        assert result is False
        mock_debug_logger.log_event.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_access_token_api_error(self, adapter, mock_debug_logger):
        """Test refresh fails on API error."""
        mock_http_response = MagicMock()
        mock_http_response.status_code = 400
        mock_http_response.text = "Invalid grant"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_http_response

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            result = await adapter._refresh_access_token()

        assert result is False
        mock_debug_logger.log_event.assert_called()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_existing_valid(self, adapter):
        """Test token validation with existing valid token."""
        adapter.access_token = "valid-token"
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        adapter.token_expiry = future_time.isoformat()

        result = await adapter._ensure_valid_token()

        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_valid_token_expired(self, adapter):
        """Test token refresh when existing token is expired."""
        adapter.access_token = "expired-token"
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        adapter.token_expiry = past_time.isoformat()

        mock_refresh = AsyncMock(return_value=True)
        with patch.object(adapter, "_refresh_access_token", side_effect=mock_refresh):
            result = await adapter._ensure_valid_token()

        assert result is True
        mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_no_token(self, adapter):
        """Test token refresh when no token exists."""
        adapter.access_token = ""

        mock_refresh = AsyncMock(return_value=True)
        with patch.object(adapter, "_refresh_access_token", side_effect=mock_refresh):
            result = await adapter._ensure_valid_token()

        assert result is True
        mock_refresh.assert_called_once()


class TestGoogleCalendarAdapterEventFetching:
    """Tests for calendar event fetching."""

    @pytest.mark.asyncio
    async def test_get_events_for_date_success(self, adapter, mock_debug_logger):
        """Test successful single-day event fetch."""
        target_date = date(2025, 6, 28)

        mock_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Team Standup",
                    "start": {"dateTime": "2025-06-28T09:00:00Z"},
                    "end": {"dateTime": "2025-06-28T09:30:00Z"},
                    "location": "Conference Room A",
                    "attendees": [{"email": "alice@example.com"}],
                }
            ]
        }

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 250)
            ):
                events = await adapter.get_events_for_date("user1", target_date)

        assert len(events) == 1
        assert events[0].title == "Team Standup"
        assert events[0].source == "google_calendar"
        mock_debug_logger.log_event.assert_called()

    @pytest.mark.asyncio
    async def test_get_events_range_multiple_days(self, adapter):
        """Test event fetch for multiple days."""
        start_date = date(2025, 6, 28)
        end_date = date(2025, 6, 30)

        mock_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Meeting 1",
                    "start": {"dateTime": "2025-06-28T10:00:00Z"},
                    "end": {"dateTime": "2025-06-28T11:00:00Z"},
                }
            ]
        }

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 250)
            ):
                events = await adapter.get_events_range("user1", start_date, end_date)

        assert len(events) >= 1
        assert all(isinstance(e, CalendarEvent) for e in events)

    @pytest.mark.asyncio
    async def test_get_events_empty_response(self, adapter):
        """Test handling of empty event response."""
        target_date = date(2025, 6, 28)

        mock_events = {"items": []}

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 100)
            ):
                events = await adapter.get_events_for_date("user1", target_date)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_get_events_invalid_token(self, adapter):
        """Test event fetch fails with invalid token."""
        target_date = date(2025, 6, 28)

        with patch.object(adapter, "_ensure_valid_token", return_value=False):
            events = await adapter.get_events_for_date("user1", target_date)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_get_events_api_failure(self, adapter):
        """Test event fetch handles API failure."""
        target_date = date(2025, 6, 28)

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(None, False, 500)
            ):
                events = await adapter.get_events_for_date("user1", target_date)

        assert len(events) == 0


class TestGoogleCalendarAdapterRetryLogic:
    """Tests for retry and rate limiting logic."""

    @pytest.mark.asyncio
    async def test_make_api_call_success_first_try(self, adapter):
        """Test successful API call on first attempt."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            data, success, latency_ms = await adapter._make_api_call_with_retry(
                "GET", "https://api.test.com/events"
            )

        assert success is True
        assert data == {"data": "test"}
        assert latency_ms >= 0

    @pytest.mark.asyncio
    async def test_make_api_call_rate_limit_retry(self, adapter):
        """Test API call retries on rate limit."""
        mock_response_rate_limit = MagicMock()
        mock_response_rate_limit.status_code = 429

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"data": "success"}

        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            mock_response_rate_limit,
            mock_response_success,
        ]

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                data, success, latency_ms = await adapter._make_api_call_with_retry(
                    "GET", "https://api.test.com/events"
                )

        assert success is True
        assert data == {"data": "success"}

    @pytest.mark.asyncio
    async def test_make_api_call_unauthorized_refresh_retry(self, adapter):
        """Test API call retries on 401 with token refresh."""
        mock_response_unauthorized = MagicMock()
        mock_response_unauthorized.status_code = 401

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"data": "success"}

        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            mock_response_unauthorized,
            mock_response_success,
        ]

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            with patch.object(adapter, "_refresh_access_token", return_value=True):
                data, success, latency_ms = await adapter._make_api_call_with_retry(
                    "GET", "https://api.test.com/events"
                )

        assert success is True
        assert data == {"data": "success"}

    @pytest.mark.asyncio
    async def test_make_api_call_max_retries_exceeded(self, adapter):
        """Test API call fails after max retries."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                data, success, latency_ms = await adapter._make_api_call_with_retry(
                    "GET", "https://api.test.com/events"
                )

        assert success is False

    @pytest.mark.asyncio
    async def test_make_api_call_exception_handling(self, adapter):
        """Test API call handles exceptions with retry."""
        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            Exception("Connection error"),
            MagicMock(status_code=200, json=lambda: {"data": "success"}),
        ]

        with patch.object(adapter, "_get_http_client", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                data, success, latency_ms = await adapter._make_api_call_with_retry(
                    "GET", "https://api.test.com/events"
                )

        assert success is True


class TestGoogleCalendarAdapterEventParsing:
    """Tests for parsing Google Calendar events."""

    def test_parse_google_event_with_datetime(self, adapter):
        """Test parsing event with dateTime format."""
        google_event = {
            "id": "event123",
            "summary": "Team Meeting",
            "description": "Weekly sync",
            "location": "Room 101",
            "start": {"dateTime": "2025-06-28T10:00:00Z"},
            "end": {"dateTime": "2025-06-28T11:00:00Z"},
            "attendees": [
                {"email": "alice@example.com"},
                {"email": "bob@example.com"},
            ],
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.title == "Team Meeting"
        assert event.source == "google_calendar"
        assert event.external_id == "event123"
        assert event.location == "Room 101"
        assert event.description == "Weekly sync"
        assert len(event.attendees) == 2
        assert "alice@example.com" in event.attendees

    def test_parse_google_event_with_date_only(self, adapter):
        """Test parsing all-day event with date only."""
        google_event = {
            "id": "event456",
            "summary": "All Day Event",
            "start": {"date": "2025-06-28"},
            "end": {"date": "2025-06-29"},
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.title == "All Day Event"
        assert event.start_time.date() == date(2025, 6, 28)

    def test_parse_google_event_minimal_fields(self, adapter):
        """Test parsing event with minimal fields."""
        google_event = {
            "id": "event789",
            "summary": "Minimal Event",
            "start": {"dateTime": "2025-06-28T14:00:00Z"},
            "end": {"dateTime": "2025-06-28T15:00:00Z"},
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.title == "Minimal Event"
        assert event.location is None
        assert event.attendees == []

    def test_parse_google_event_no_summary(self, adapter):
        """Test parsing event with missing summary defaults to 'Untitled'."""
        google_event = {
            "id": "event999",
            "start": {"dateTime": "2025-06-28T16:00:00Z"},
            "end": {"dateTime": "2025-06-28T17:00:00Z"},
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.title == "Untitled"

    def test_parse_google_event_no_start_time(self, adapter):
        """Test parsing event with missing start time returns None."""
        google_event = {
            "id": "event_bad",
            "summary": "Bad Event",
        }

        event = adapter._parse_google_event(google_event)

        assert event is None

    def test_parse_google_event_timezone_handling(self, adapter):
        """Test parsing event handles timezone correctly."""
        google_event = {
            "id": "event_tz",
            "summary": "Timezone Event",
            "start": {"dateTime": "2025-06-28T10:00:00-07:00"},
            "end": {"dateTime": "2025-06-28T11:00:00-07:00"},
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.start_time is not None


class TestGoogleCalendarAdapterConfiguration:
    """Tests for adapter configuration checking."""

    @pytest.mark.asyncio
    async def test_is_configured_true(self, adapter):
        """Test is_configured returns True with valid credentials."""
        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            result = await adapter.is_configured("user1")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_configured_false_no_credentials(self, mock_debug_logger, mock_settings):
        """Test is_configured returns False with missing credentials."""
        mock_settings.google_calendar_client_id = ""
        adapter = GoogleCalendarAdapter(mock_debug_logger, mock_settings)

        result = await adapter.is_configured("user1")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_configured_false_token_refresh_fails(self, adapter):
        """Test is_configured returns False when token refresh fails."""
        with patch.object(adapter, "_ensure_valid_token", return_value=False):
            result = await adapter.is_configured("user1")

        assert result is False


class TestGoogleCalendarAdapterDebugLogging:
    """Tests for debug logging functionality."""

    @pytest.mark.asyncio
    async def test_logs_fetch_start(self, adapter, mock_debug_logger):
        """Test logging at start of fetch."""
        target_date = date(2025, 6, 28)

        with patch.object(adapter, "_ensure_valid_token", return_value=False):
            await adapter.get_events_for_date("user1", target_date)

        # Check that log_event was called
        assert mock_debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_logs_fetch_completion_with_latency(self, adapter, mock_debug_logger):
        """Test logging includes latency metrics."""
        target_date = date(2025, 6, 28)

        mock_events = {"items": []}

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 350)
            ):
                await adapter.get_events_for_date("user1", target_date)

        # Verify that log_event was called (logging is tested)
        assert mock_debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_logs_errors(self, adapter, mock_debug_logger):
        """Test error logging."""
        target_date = date(2025, 6, 28)

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(None, False, 0)
            ):
                await adapter.get_events_for_date("user1", target_date)

        # Check that error was logged
        assert mock_debug_logger.log_event.called


class TestGoogleCalendarAdapterEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_parse_event_with_empty_attendees_list(self, adapter):
        """Test parsing event with explicitly empty attendees."""
        google_event = {
            "id": "event_no_attendees",
            "summary": "Solo Event",
            "start": {"dateTime": "2025-06-28T10:00:00Z"},
            "end": {"dateTime": "2025-06-28T11:00:00Z"},
            "attendees": [],
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.attendees == []

    @pytest.mark.asyncio
    async def test_get_events_handles_parsing_exception(self, adapter):
        """Test graceful handling of event parsing exception."""
        target_date = date(2025, 6, 28)

        mock_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Good Event",
                    "start": {"dateTime": "2025-06-28T10:00:00Z"},
                    "end": {"dateTime": "2025-06-28T11:00:00Z"},
                },
                {
                    # This will fail to parse (no start time)
                    "id": "event2",
                    "summary": "Bad Event",
                },
            ]
        }

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 250)
            ):
                events = await adapter.get_events_for_date("user1", target_date)

        # Should have 1 good event, 1 skipped
        assert len(events) == 1
        assert events[0].title == "Good Event"

    @pytest.mark.asyncio
    async def test_start_date_equals_end_date(self, adapter):
        """Test event fetch with start_date == end_date."""
        start_date = date(2025, 6, 28)
        end_date = date(2025, 6, 28)

        mock_events = {"items": []}

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 200)
            ):
                events = await adapter.get_events_range("user1", start_date, end_date)

        assert isinstance(events, list)

    @pytest.mark.asyncio
    async def test_close_http_client(self, adapter):
        """Test closing HTTP client."""
        mock_client = AsyncMock()
        adapter.http_client = mock_client

        await adapter.close()

        mock_client.aclose.assert_called_once()

    def test_parse_event_missing_end_time(self, adapter):
        """Test parsing event with missing end time defaults to 1 hour later."""
        google_event = {
            "id": "event_no_end",
            "summary": "No End Time",
            "start": {"dateTime": "2025-06-28T10:00:00Z"},
        }

        event = adapter._parse_google_event(google_event)

        assert event is not None
        assert event.end_time == event.start_time + timedelta(hours=1)

    @pytest.mark.asyncio
    async def test_get_events_with_different_date_formats(self, adapter):
        """Test handling different date formats in Google Calendar response."""
        target_date = date(2025, 6, 28)

        mock_events = {
            "items": [
                {
                    "id": "event_datetime",
                    "summary": "DateTime Event",
                    "start": {"dateTime": "2025-06-28T10:00:00Z"},
                    "end": {"dateTime": "2025-06-28T11:00:00Z"},
                },
                {
                    "id": "event_date",
                    "summary": "All Day Event",
                    "start": {"date": "2025-06-28"},
                    "end": {"date": "2025-06-29"},
                },
            ]
        }

        with patch.object(adapter, "_ensure_valid_token", return_value=True):
            with patch.object(
                adapter, "_make_api_call_with_retry", return_value=(mock_events, True, 250)
            ):
                events = await adapter.get_events_for_date("user1", target_date)

        assert len(events) == 2
        assert events[0].title == "DateTime Event"
        assert events[1].title == "All Day Event"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
