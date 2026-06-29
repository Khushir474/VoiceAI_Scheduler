"""Twilio SMS adapter implementation."""

import asyncio
import logging
import time
from functools import cached_property

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

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

    @cached_property
    def _client(self) -> Client:
        return Client(self.account_sid, self.auth_token)

    async def send_message(self, recipient: str, content: str) -> dict:
        """Send SMS via Twilio."""
        start_time = time.time()
        await self.debug_logger.log_event(
            agent_name="TwilioSMSAdapter",
            event_type="send_started",
            message="Sending SMS via Twilio",
            input_payload={"recipient": recipient, "content_length": len(content)},
        )

        try:
            # Twilio client is synchronous; run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    body=content,
                    from_=self.from_number,
                    to=recipient,
                ),
            )
            latency_ms = int((time.time() - start_time) * 1000)

            result = {
                "status": "sent",
                "message_id": message.sid,
            }

            await self.debug_logger.log_event(
                agent_name="TwilioSMSAdapter",
                event_type="send_completed",
                message="SMS sent via Twilio",
                output_payload=result,
                latency_ms=latency_ms,
            )
            return result

        except TwilioRestException as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error = f"Twilio error {e.code}: {e.msg}"
            await self.debug_logger.log_event(
                agent_name="TwilioSMSAdapter",
                event_type="send_failed",
                level="error",
                message=f"Failed to send SMS: {error}",
                error=error,
                latency_ms=latency_ms,
            )
            return {"status": "failed", "error": error}

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error = str(e)
            await self.debug_logger.log_event(
                agent_name="TwilioSMSAdapter",
                event_type="send_failed",
                level="error",
                message=f"Failed to send SMS: {error}",
                error=error,
                latency_ms=latency_ms,
            )
            return {"status": "failed", "error": error}

    async def is_available(self) -> bool:
        """Check if Twilio is configured."""
        return bool(self.account_sid and self.auth_token and self.from_number)
