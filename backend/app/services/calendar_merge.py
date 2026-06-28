"""Calendar event merge and deduplication logic."""

from datetime import datetime, timedelta
from app.agents.state import CalendarEvent
from app.services.logger import DebugLogger


class CalendarMerger:
    """Merge and deduplicate calendar events from multiple sources."""

    TITLE_SIMILARITY_THRESHOLD = 0.8
    TIME_WINDOW_MINUTES = 5

    def __init__(self, debug_logger: DebugLogger):
        self.debug_logger = debug_logger

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity (0.0 to 1.0)."""
        s1, s2 = s1.lower().strip(), s2.lower().strip()
        if s1 == s2:
            return 1.0

        # Simple Levenshtein-based similarity
        if len(s1) == 0 or len(s2) == 0:
            return 0.0

        # Count matching characters
        matches = sum(1 for c1, c2 in zip(s1, s2) if c1 == c2)
        return matches / max(len(s1), len(s2))

    def _should_deduplicate(self, event1: CalendarEvent, event2: CalendarEvent) -> bool:
        """Check if two events should be deduplicated."""
        # Same title
        if event1.title.lower() == event2.title.lower():
            # Start times within 5 minutes
            time_diff = abs((event1.start_time - event2.start_time).total_seconds() / 60)
            if time_diff <= self.TIME_WINDOW_MINUTES:
                return True

        # Similar title + same time
        similarity = self._string_similarity(event1.title, event2.title)
        if similarity >= self.TITLE_SIMILARITY_THRESHOLD:
            time_diff = abs((event1.start_time - event2.start_time).total_seconds() / 60)
            if time_diff <= self.TIME_WINDOW_MINUTES:
                # Also check location similarity if both have locations
                if event1.location and event2.location:
                    loc_sim = self._string_similarity(event1.location, event2.location)
                    if loc_sim >= 0.7:
                        return True
                else:
                    return True

        return False

    def merge(self, events: list[CalendarEvent]) -> tuple[list[CalendarEvent], dict]:
        """Merge and deduplicate events.

        Returns:
            (deduplicated_events, dedup_report)
        """
        if not events:
            return [], {"total_input": 0, "total_output": 0, "duplicates_removed": 0}

        # Sort by start time
        sorted_events = sorted(events, key=lambda e: e.start_time)
        deduplicated = []
        dedup_map = {}  # Track which events were marked as duplicates

        for i, event in enumerate(sorted_events):
            if i in dedup_map:
                continue  # Already marked as duplicate

            # Check against all remaining events
            primary = event
            for j in range(i + 1, len(sorted_events)):
                if j in dedup_map:
                    continue

                if self._should_deduplicate(primary, sorted_events[j]):
                    dedup_map[j] = i  # Mark j as duplicate of i

            deduplicated.append(primary)

        duplicates_removed = len(events) - len(deduplicated)

        report = {
            "total_input": len(events),
            "total_output": len(deduplicated),
            "duplicates_removed": duplicates_removed,
            "sources": {
                "google_calendar": sum(1 for e in events if e.source == "google_calendar"),
                "apple_ical": sum(1 for e in events if e.source == "apple_ical"),
            },
        }

        return deduplicated, report

    async def log_dedup_results(self, events: list[CalendarEvent], report: dict) -> None:
        """Log deduplication results."""
        await self.debug_logger.log_event(
            agent_name="CalendarMerger",
            event_type="merge_completed",
            message=f"Merged calendar events: {report['total_input']} input, "
            f"{report['total_output']} output, {report['duplicates_removed']} duplicates removed",
            output_payload=report,
        )
