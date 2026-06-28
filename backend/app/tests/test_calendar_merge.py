"""Tests for calendar merge and deduplication logic."""

import pytest
from datetime import datetime, timezone

from app.agents.state import CalendarEvent
from app.services.calendar_merge import CalendarMerger
from app.services.logger import DebugLogger


@pytest.fixture
def debug_logger(mocker):
    """Mock debug logger."""
    return mocker.MagicMock(spec=DebugLogger)


@pytest.fixture
def calendar_merger(debug_logger):
    """Create a calendar merger instance."""
    return CalendarMerger(debug_logger)


def create_event(
    title: str,
    start_time: datetime,
    source: str = "google_calendar",
    location: str | None = None,
) -> CalendarEvent:
    """Helper to create a calendar event."""
    return CalendarEvent(
        source=source,
        title=title,
        start_time=start_time,
        end_time=start_time.replace(hour=start_time.hour + 1),
        location=location,
    )


class TestCalendarMerger:
    """Tests for CalendarMerger."""

    def test_merge_empty_list(self, calendar_merger):
        """Test merging an empty list."""
        result, report = calendar_merger.merge([])
        assert result == []
        assert report["total_input"] == 0
        assert report["total_output"] == 0
        assert report["duplicates_removed"] == 0

    def test_merge_no_duplicates(self, calendar_merger):
        """Test merging events with no duplicates."""
        now = datetime.now(timezone.utc)
        events = [
            create_event("Meeting 1", now.replace(hour=9)),
            create_event("Meeting 2", now.replace(hour=10)),
            create_event("Meeting 3", now.replace(hour=11)),
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 3
        assert report["duplicates_removed"] == 0
        assert report["total_output"] == 3

    def test_merge_exact_duplicates(self, calendar_merger):
        """Test merging exact duplicate events."""
        now = datetime.now(timezone.utc)
        event = create_event("Team Sync", now.replace(hour=10))

        events = [
            event,
            CalendarEvent(
                source="apple_ical",
                title="Team Sync",
                start_time=event.start_time,
                end_time=event.end_time,
                location=event.location,
            ),
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 1
        assert report["duplicates_removed"] == 1
        assert result[0].title == "Team Sync"

    def test_merge_time_window_duplicates(self, calendar_merger):
        """Test merging events within the time window."""
        base_time = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0)
        events = [
            create_event("Meeting", base_time),
            create_event("Meeting", base_time.replace(minute=3)),  # 3 minutes later
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 1
        assert report["duplicates_removed"] == 1

    def test_merge_similar_titles_same_time(self, calendar_merger):
        """Test merging events with similar titles at the same time."""
        now = datetime.now(timezone.utc)
        events = [
            create_event("Team Sync", now.replace(hour=10)),
            create_event("Team Synchronization", now.replace(hour=10)),
        ]

        result, report = calendar_merger.merge(events)
        # These should be deduplicated due to similar titles
        assert len(result) == 1
        assert report["duplicates_removed"] == 1

    def test_merge_same_location(self, calendar_merger):
        """Test deduplication with location matching."""
        now = datetime.now(timezone.utc)
        events = [
            create_event("Conference", now.replace(hour=10), location="Conference Room A"),
            create_event("Conference", now.replace(hour=10), location="Conference Room A"),
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 1
        assert report["duplicates_removed"] == 1

    def test_merge_different_times_not_duplicated(self, calendar_merger):
        """Test that events with different times are not deduplicated."""
        now = datetime.now(timezone.utc)
        events = [
            create_event("Meeting", now.replace(hour=10)),
            create_event("Meeting", now.replace(hour=14)),  # 4 hours later
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 2
        assert report["duplicates_removed"] == 0

    def test_merge_multiple_sources(self, calendar_merger):
        """Test merging events from multiple sources."""
        now = datetime.now(timezone.utc)
        events = [
            create_event("Meeting", now.replace(hour=10), source="google_calendar"),
            create_event("Meeting", now.replace(hour=10), source="apple_ical"),
            create_event("Lunch", now.replace(hour=12), source="google_calendar"),
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 2
        assert report["duplicates_removed"] == 1
        assert report["sources"]["google_calendar"] == 2
        assert report["sources"]["apple_ical"] == 1

    def test_merge_sorts_by_time(self, calendar_merger):
        """Test that merged events are sorted by start time."""
        now = datetime.now(timezone.utc)
        events = [
            create_event("Meeting 3", now.replace(hour=11)),
            create_event("Meeting 1", now.replace(hour=9)),
            create_event("Meeting 2", now.replace(hour=10)),
        ]

        result, report = calendar_merger.merge(events)
        assert len(result) == 3
        assert result[0].title == "Meeting 1"
        assert result[1].title == "Meeting 2"
        assert result[2].title == "Meeting 3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
