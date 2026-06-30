"""Base calendar adapter interface."""

from abc import ABC, abstractmethod
from datetime import date
from app.agents.state import CalendarEvent


class CalendarAdapter(ABC):
    """Base class for calendar providers."""

    @abstractmethod
    async def get_events_for_date(self, user_id: str, target_date: date) -> list[CalendarEvent]:
        """Fetch calendar events for a specific date."""
        pass

    @abstractmethod
    async def get_events_range(
        self, user_id: str, start_date: date, end_date: date
    ) -> list[CalendarEvent]:
        """Fetch calendar events for a date range."""
        pass

    @abstractmethod
    async def is_configured(self, user_id: str) -> bool:
        """Check if the adapter is configured for this user."""
        pass

    @abstractmethod
    async def create_event(self, user_id: str, event: CalendarEvent) -> CalendarEvent | None:
        """Create a new calendar event.

        Returns the event with external_id populated on success, None on failure.
        Implementations must log mutations to debug_logs.
        """
        pass
