"""Base messaging adapter interface."""

from abc import ABC, abstractmethod


class MessageAdapter(ABC):
    """Base class for messaging providers."""

    @abstractmethod
    async def send_message(self, recipient: str, content: str) -> dict:
        """Send a message to a recipient.

        Args:
            recipient: Phone number or identifier
            content: Message content

        Returns:
            dict with 'status', 'message_id', and optional 'error'
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the messaging service is available."""
        pass
