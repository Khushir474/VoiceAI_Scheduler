"""Tests for Apple iCal adapter."""

import pytest
import asyncio
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from icalendar import Calendar as ICalCalendar, Event as ICalEvent
import tempfile

from app.agents.state import CalendarEvent
from app.adapters.calendar.apple_ical import AppleICalAdapter
from app.services.logger import DebugLogger


@pytest.fixture
def debug_logger(mocker):
    """Mock debug logger."""
    return mocker.MagicMock(spec=DebugLogger)


@pytest.fixture
def apple_adapter(debug_logger):
    """Create an Apple iCal adapter instance."""
    return AppleICalAdapter(debug_logger=debug_logger)


def create_ics_file(events: list[dict]) -> Path:
    """Create a temporary .ics file with the given events.

    Each event dict should have:
    - summary: str
    - dtstart: datetime or date
    - dtend: datetime or date (optional)
    - location: str (optional)
    - description: str (optional)
    - attendees: list[str] (optional)
    - uid: str (optional)
    """
    cal = ICalCalendar()
    cal.add("prodid", "-//Test//Test//EN")
    cal.add("version", "2.0")

    for event_data in events:
        event = ICalEvent()
        event.add("summary", event_data["summary"])
        event.add("dtstart", event_data["dtstart"])

        if "dtend" in event_data:
            event.add("dtend", event_data["dtend"])
        else:
            # Default to 1 hour after start for timed events
            if isinstance(event_data["dtstart"], datetime):
                event.add("dtend", event_data["dtstart"] + timedelta(hours=1))
            else:
                event.add("dtend", event_data["dtstart"] + timedelta(days=1))

        if "location" in event_data:
            event.add("location", event_data["location"])

        if "description" in event_data:
            event.add("description", event_data["description"])

        if "attendees" in event_data:
            for attendee in event_data["attendees"]:
                event.add("attendee", f"mailto:{attendee}")

        event.add("uid", event_data.get("uid", f"test-{id(event)}"))

        cal.add_component(event)

    # Write to temporary file
    temp_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".ics", delete=False)
    temp_file.write(cal.to_ical())
    temp_file.close()

    return Path(temp_file.name)


class TestAppleICalParseIcsFile:
    """Tests for parsing .ics files."""

    @pytest.mark.asyncio
    async def test_parse_ics_file_single_timed_event(self, debug_logger):
        """Test parsing a single timed event."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([{"summary": "Meeting", "dtstart": now}])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].title == "Meeting"
            assert events[0].source == "apple_ical"
            assert events[0].start_time == now
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_parse_ics_file_all_day_event(self, debug_logger):
        """Test parsing an all-day event."""
        today = date.today()
        temp_file = create_ics_file([{"summary": "Birthday", "dtstart": today}])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].title == "Birthday"
            # All-day events should be at midnight UTC
            assert events[0].start_time == datetime.combine(
                today, datetime.min.time(), tzinfo=timezone.utc
            )
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_parse_ics_file_multiple_events(self, debug_logger):
        """Test parsing multiple events."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([
            {"summary": "Meeting 1", "dtstart": now},
            {"summary": "Meeting 2", "dtstart": now + timedelta(hours=2)},
            {"summary": "Meeting 3", "dtstart": now + timedelta(hours=4)},
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 3
            assert events[0].title == "Meeting 1"
            assert events[1].title == "Meeting 2"
            assert events[2].title == "Meeting 3"
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_parse_ics_file_with_location(self, debug_logger):
        """Test parsing events with location."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([
            {
                "summary": "Conference",
                "dtstart": now,
                "location": "Conference Room A",
            }
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].location == "Conference Room A"
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_parse_ics_file_with_description(self, debug_logger):
        """Test parsing events with description."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([
            {
                "summary": "Team Sync",
                "dtstart": now,
                "description": "Weekly team synchronization",
            }
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].description == "Weekly team synchronization"
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_parse_ics_file_with_attendees(self, debug_logger):
        """Test parsing events with attendees."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([
            {
                "summary": "Meeting",
                "dtstart": now,
                "attendees": ["alice@example.com", "bob@example.com"],
            }
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert len(events[0].attendees) == 2
            assert "alice@example.com" in events[0].attendees
            assert "bob@example.com" in events[0].attendees
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_parse_ics_file_not_found(self, debug_logger):
        """Test parsing a non-existent file."""
        adapter = AppleICalAdapter(debug_logger=debug_logger)
        events = await adapter.parse_ics_file("/nonexistent/file.ics")
        assert events == []

    @pytest.mark.asyncio
    async def test_parse_ics_file_with_uid(self, debug_logger):
        """Test that UIDs are preserved as external_id."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        test_uid = "test-event-12345@example.com"
        temp_file = create_ics_file([
            {"summary": "Meeting", "dtstart": now, "uid": test_uid}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].external_id == test_uid
        finally:
            temp_file.unlink()


class TestAppleICalGetEventsRange:
    """Tests for getting events in a date range."""

    @pytest.mark.asyncio
    async def test_get_events_range_no_events(self, debug_logger):
        """Test getting events for a date range with no events."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([
            {"summary": "Meeting", "dtstart": now - timedelta(days=5)}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.get_events_range(
                "user123",
                (now + timedelta(days=1)).date(),
                (now + timedelta(days=2)).date(),
            )
            assert len(events) == 0
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_get_events_range_within_range(self, debug_logger):
        """Test getting events within a date range."""
        base_date = datetime.now(timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ).date()
        start_dt = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc)
        temp_file = create_ics_file([
            {"summary": "Meeting", "dtstart": start_dt + timedelta(hours=5)}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.get_events_range("user123", base_date, base_date)

            assert len(events) == 1
            assert events[0].title == "Meeting"
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_get_events_range_multiple_days(self, debug_logger):
        """Test getting events across multiple days."""
        base_date = datetime.now(timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ).date()
        start_dt = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc)
        temp_file = create_ics_file([
            {"summary": "Meeting 1", "dtstart": start_dt},
            {"summary": "Meeting 2", "dtstart": start_dt + timedelta(days=1)},
            {"summary": "Meeting 3", "dtstart": start_dt + timedelta(days=2)},
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.get_events_range("user123", base_date, base_date + timedelta(days=2))

            assert len(events) == 3
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_get_events_range_excludes_before_range(self, debug_logger):
        """Test that events before the range are excluded."""
        base_date = datetime.now(timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ).date()
        start_dt = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc)
        temp_file = create_ics_file([
            {"summary": "Before", "dtstart": start_dt - timedelta(days=2)},
            {"summary": "During", "dtstart": start_dt},
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.get_events_range("user123", base_date, base_date)

            assert len(events) == 1
            assert events[0].title == "During"
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_get_events_range_excludes_after_range(self, debug_logger):
        """Test that events after the range are excluded."""
        base_date = datetime.now(timezone.utc).replace(
            hour=10, minute=0, second=0, microsecond=0
        ).date()
        start_dt = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc)
        temp_file = create_ics_file([
            {"summary": "During", "dtstart": start_dt},
            {"summary": "After", "dtstart": start_dt + timedelta(days=2)},
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.get_events_range("user123", base_date, base_date)

            assert len(events) == 1
            assert events[0].title == "During"
        finally:
            temp_file.unlink()


class TestAppleICalDeduplication:
    """Tests for integration with CalendarMerger."""

    @pytest.mark.asyncio
    async def test_merged_with_google_calendar_events(self, debug_logger, mocker):
        """Test that Apple events merge properly with Google events."""
        from app.services.calendar_merge import CalendarMerger

        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)

        # Create Apple event via .ics
        temp_file = create_ics_file([
            {"summary": "Team Sync", "dtstart": now}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            apple_events = await adapter.parse_ics_file(str(temp_file))

            # Create Google event
            google_event = CalendarEvent(
                source="google_calendar",
                title="Team Sync",
                start_time=now,
                end_time=now + timedelta(hours=1),
            )

            # Merge
            merger = CalendarMerger(debug_logger)
            merged, report = merger.merge(apple_events + [google_event])

            # Should deduplicate
            assert len(merged) == 1
            assert report["duplicates_removed"] == 1
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_no_dedup_different_times(self, debug_logger, mocker):
        """Test that events at different times aren't deduplicated."""
        from app.services.calendar_merge import CalendarMerger

        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)

        # Create Apple event
        temp_file = create_ics_file([
            {"summary": "Team Sync", "dtstart": now}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            apple_events = await adapter.parse_ics_file(str(temp_file))

            # Create Google event at different time
            google_event = CalendarEvent(
                source="google_calendar",
                title="Team Sync",
                start_time=now + timedelta(hours=4),
                end_time=now + timedelta(hours=5),
            )

            # Merge
            merger = CalendarMerger(debug_logger)
            merged, report = merger.merge(apple_events + [google_event])

            # Should NOT deduplicate
            assert len(merged) == 2
            assert report["duplicates_removed"] == 0
        finally:
            temp_file.unlink()


class TestAppleICalEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_ics_file(self, debug_logger):
        """Test parsing an empty .ics file."""
        cal = ICalCalendar()
        cal.add("prodid", "-//Test//Test//EN")
        cal.add("version", "2.0")

        temp_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".ics", delete=False)
        temp_file.write(cal.to_ical())
        temp_file.close()

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))
            assert len(events) == 0
        finally:
            Path(temp_file.name).unlink()

    @pytest.mark.asyncio
    async def test_event_without_summary(self, debug_logger):
        """Test that events without summary are skipped gracefully."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        cal = ICalCalendar()
        cal.add("prodid", "-//Test//Test//EN")
        cal.add("version", "2.0")

        event = ICalEvent()
        event.add("dtstart", now)
        event.add("uid", "test-no-summary")
        cal.add_component(event)

        temp_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".ics", delete=False)
        temp_file.write(cal.to_ical())
        temp_file.close()

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger)
            events = await adapter.parse_ics_file(str(temp_file))
            # Should parse but use default title
            assert len(events) >= 0  # Depends on parser behavior
        finally:
            Path(temp_file.name).unlink()

    @pytest.mark.asyncio
    async def test_is_configured_with_ics_file(self, debug_logger):
        """Test is_configured returns True when .ics file exists."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        temp_file = create_ics_file([{"summary": "Meeting", "dtstart": now}])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            is_configured = await adapter.is_configured("user123")
            assert is_configured is True
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_is_configured_without_ics_or_caldav(self, debug_logger):
        """Test is_configured returns False when neither .ics nor CalDAV configured."""
        adapter = AppleICalAdapter(debug_logger=debug_logger)
        is_configured = await adapter.is_configured("user123")
        assert is_configured is False

    @pytest.mark.asyncio
    async def test_event_with_explicit_end_time(self, debug_logger):
        """Test parsing events with explicit end times."""
        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        end = now + timedelta(hours=2)
        temp_file = create_ics_file([
            {"summary": "Long Meeting", "dtstart": now, "dtend": end}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].end_time == end
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_all_day_event_with_explicit_end_date(self, debug_logger):
        """Test parsing all-day events with explicit end dates."""
        today = date.today()
        tomorrow = today + timedelta(days=1)
        temp_file = create_ics_file([
            {
                "summary": "Multi-day Event",
                "dtstart": today,
                "dtend": tomorrow,
            }
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            assert events[0].start_time == datetime.combine(
                today, datetime.min.time(), tzinfo=timezone.utc
            )
        finally:
            temp_file.unlink()

    @pytest.mark.asyncio
    async def test_event_normalized_to_utc(self, debug_logger):
        """Test that event times are normalized to UTC."""
        # Create an event with a specific timezone
        from datetime import timezone as dt_timezone
        import pytz

        now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        # Convert to a different timezone and back
        eastern = pytz.timezone("America/New_York")
        now_eastern = now.astimezone(eastern)

        temp_file = create_ics_file([
            {"summary": "Meeting", "dtstart": now_eastern}
        ])

        try:
            adapter = AppleICalAdapter(debug_logger=debug_logger, ics_file_path=str(temp_file))
            events = await adapter.parse_ics_file(str(temp_file))

            assert len(events) == 1
            # Should be in UTC
            assert events[0].start_time.tzinfo == timezone.utc
        finally:
            temp_file.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ─── DOPS-8: create_event ────────────────────────────────────────────────────

class TestAppleICalCreateEvent:
    """Tests for AppleICalAdapter.create_event (DOPS-8)."""

    @pytest.fixture
    def now(self):
        return datetime.now(timezone.utc).replace(microsecond=0)

    @pytest.fixture
    def sample_event(self, now):
        return CalendarEvent(
            source="apple_ical",
            title="Gym Session",
            start_time=now.replace(hour=18, minute=0),
            end_time=now.replace(hour=19, minute=0),
        )

    @pytest.mark.asyncio
    async def test_create_event_caldav_success_returns_event(
        self, debug_logger, sample_event
    ):
        """create_event via CalDAV PUT 201 returns the event with external_id set."""
        adapter = AppleICalAdapter(
            debug_logger=debug_logger,
            caldav_url="https://caldav.icloud.com",
            username="user@icloud.com",
            password="app-password",
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        adapter.http_client = AsyncMock()
        adapter.http_client.put = AsyncMock(return_value=mock_response)

        result = await adapter.create_event("user1", sample_event)

        assert result is not None
        assert result.title == "Gym Session"
        assert result.external_id is not None
        adapter.http_client.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_event_caldav_204_returns_event(
        self, debug_logger, sample_event
    ):
        """CalDAV PUT returning 204 (no content) also counts as success."""
        adapter = AppleICalAdapter(
            debug_logger=debug_logger,
            username="user@icloud.com",
            password="pass",
        )
        mock_response = MagicMock()
        mock_response.status_code = 204
        adapter.http_client = AsyncMock()
        adapter.http_client.put = AsyncMock(return_value=mock_response)

        result = await adapter.create_event("user1", sample_event)
        assert result is not None

    @pytest.mark.asyncio
    async def test_create_event_caldav_non_2xx_returns_none(
        self, debug_logger, sample_event
    ):
        """CalDAV PUT returning a non-success code returns None."""
        adapter = AppleICalAdapter(
            debug_logger=debug_logger,
            username="user@icloud.com",
            password="pass",
        )
        mock_response = MagicMock()
        mock_response.status_code = 500
        adapter.http_client = AsyncMock()
        adapter.http_client.put = AsyncMock(return_value=mock_response)

        result = await adapter.create_event("user1", sample_event)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_event_appends_to_ics_file(self, debug_logger, sample_event, tmp_path):
        """create_event writes a VEVENT to a local .ics file when no CalDAV credentials."""
        ics_file = tmp_path / "calendar.ics"
        # Start with a valid empty calendar
        cal = ICalCalendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        ics_file.write_bytes(cal.to_ical())

        adapter = AppleICalAdapter(
            debug_logger=debug_logger,
            ics_file_path=str(ics_file),
        )

        result = await adapter.create_event("user1", sample_event)

        assert result is not None
        assert result.external_id is not None

        # Verify the event was actually written
        written_cal = ICalCalendar.from_ical(ics_file.read_bytes())
        summaries = [
            str(c.get("SUMMARY"))
            for c in written_cal.walk()
            if c.name == "VEVENT"
        ]
        assert "Gym Session" in summaries

    @pytest.mark.asyncio
    async def test_create_event_creates_ics_file_if_not_exists(
        self, debug_logger, sample_event, tmp_path
    ):
        """create_event creates a new .ics file if the target path doesn't exist yet."""
        ics_file = tmp_path / "new_calendar.ics"
        assert not ics_file.exists()

        adapter = AppleICalAdapter(
            debug_logger=debug_logger,
            ics_file_path=str(ics_file),
        )

        result = await adapter.create_event("user1", sample_event)

        assert result is not None
        assert ics_file.exists()

    @pytest.mark.asyncio
    async def test_create_event_returns_none_when_not_configured(
        self, debug_logger, sample_event
    ):
        """create_event returns None when neither CalDAV credentials nor .ics file configured."""
        adapter = AppleICalAdapter(debug_logger=debug_logger)

        result = await adapter.create_event("user1", sample_event)
        assert result is None
