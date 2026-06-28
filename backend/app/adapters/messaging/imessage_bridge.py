"""iMessage bridge adapter implementation."""

import logging
import httpx
from typing import Any

from app.adapters.messaging.base import MessageAdapter
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class IMessageBridgeAdapter(MessageAdapter):
    """Adapter for sending messages via local iMessage Mac bridge."""

    def __init__(self, debug_logger: DebugLogger, bridge_url: str = "http://localhost:8001"):
        self.debug_logger = debug_logger
        self.bridge_url = bridge_url
        self.http_client = httpx.AsyncClient(timeout=10)

    async def send_message(self, recipient: str, content: str) -> dict:
        """Send message via iMessage bridge."""
        await self.debug_logger.log_event(
            agent_name="IMessageBridgeAdapter",
            event_type="send_started",
            message="Sending iMessage",
            input_payload={"recipient": recipient, "content_length": len(content)},
        )

        try:
            response = await self.http_client.post(
                f"{self.bridge_url}/send",
                json={"recipient": recipient, "content": content},
            )

            if response.status_code == 200:
                result = {
                    "status": "sent",
                    "message_id": response.json().get("message_id"),
                }
                await self.debug_logger.log_event(
                    agent_name="IMessageBridgeAdapter",
                    event_type="send_completed",
                    message="iMessage sent successfully",
                    output_payload=result,
                )
                return result
            else:
                error = f"Bridge returned {response.status_code}"
                await self.debug_logger.log_event(
                    agent_name="IMessageBridgeAdapter",
                    event_type="send_failed",
                    level="error",
                    message=f"Failed to send iMessage: {error}",
                    error=error,
                )
                return {"status": "failed", "error": error}

        except httpx.ConnectError as e:
            error = f"Bridge connection error: {str(e)}"
            await self.debug_logger.log_event(
                agent_name="IMessageBridgeAdapter",
                event_type="send_failed",
                level="error",
                message=error,
                error=error,
            )
            return {"status": "failed", "error": error}
        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            await self.debug_logger.log_event(
                agent_name="IMessageBridgeAdapter",
                event_type="send_failed",
                level="error",
                message=error,
                error=error,
            )
            return {"status": "failed", "error": error}

    async def is_available(self) -> bool:
        """Check if the iMessage bridge is available."""
        try:
            response = await self.http_client.get(f"{self.bridge_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"iMessage bridge health check failed: {e}")
            return False
