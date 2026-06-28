"""Base voice adapter interface."""

from abc import ABC, abstractmethod


class VoiceAdapter(ABC):
    """Base class for voice providers."""

    @abstractmethod
    async def initiate_call(self, recipient_phone: str, run_id: str) -> dict:
        """Initiate an outbound call.

        Args:
            recipient_phone: Phone number to call
            run_id: Unique run identifier

        Returns:
            dict with 'status', 'call_id', and optional 'error'
        """
        pass

    @abstractmethod
    async def get_call_status(self, call_id: str) -> dict:
        """Get the current status of a call."""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the voice service is available."""
        pass
