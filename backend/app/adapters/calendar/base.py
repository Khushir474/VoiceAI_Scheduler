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
