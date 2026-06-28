"""Twilio SMS adapter implementation."""

import logging
from typing import Any

from app.adapters.messaging.base import MessageAdapter
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class TwilioSMSAdapter(MessageAdapter):
    """Adapter for sending SMS via Twilio."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        account_sid: str,
        auth_token: str,
        from_number: str,
    ):
        self.debug_logger = debug_logger
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.client = None  # Twilio client initialized lazily

    async def _init_client(self):
        """Initialize Twilio client (lazy)."""
        # TODO: Initialize Twilio client
        # from twilio.rest import Client
        # self.client = Client(self.account_sid, self.auth_token)
        pass

    async def send_message(self, recipient: str, content: str) -> dict:
        """Send SMS via Twilio."""
        await self.debug_logger.log_event(
            agent_name="TwilioSMSAdapter",
            event_type="send_started",
            message="Sending SMS via Twilio",
            input_payload={"recipient": recipient, "content_length": len(content)},
        )

        try:
            await self._init_client()

            # TODO: Call Twilio API to send SMS
            # For MVP, return mock success
            result = {
                "status": "sent",
                "message_id": "mock-twilio-sid",
            }

            await self.debug_logger.log_event(
                agent_name="TwilioSMSAdapter",
                event_type="send_completed",
                message="SMS sent via Twilio",
                output_payload=result,
            )
            return result

        except Exception as e:
            error = str(e)
            await self.debug_logger.log_event(
                agent_name="TwilioSMSAdapter",
                event_type="send_failed",
                level="error",
                message=f"Failed to send SMS: {error}",
                error=error,
            )
            return {"status": "failed", "error": error}

    async def is_available(self) -> bool:
        """Check if Twilio is configured."""
        return bool(self.account_sid and self.auth_token and self.from_number)
