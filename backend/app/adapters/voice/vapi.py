"""Vapi voice adapter implementation."""

import logging
import httpx
from datetime import datetime

from app.adapters.voice.base import VoiceAdapter
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class VapiAdapter(VoiceAdapter):
    """Adapter for Vapi voice service."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        api_key: str,
        assistant_id: str | None = None,
    ):
        self.debug_logger = debug_logger
        self.api_key = api_key
        self.assistant_id = assistant_id
        self.base_url = "https://api.vapi.ai"
        self.http_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )

    async def initiate_call(self, recipient_phone: str, run_id: str) -> dict:
        """Initiate an outbound call via Vapi."""
        await self.debug_logger.log_event(
            agent_name="VapiAdapter",
            event_type="call_initiate",
            message=f"Initiating Vapi call to {recipient_phone}",
            input_payload={"recipient": recipient_phone, "run_id": run_id},
        )

        try:
            payload = {
                "phoneNumberId": recipient_phone,
                "assistantId": self.assistant_id,
                "customData": {"run_id": run_id},
            }

            response = await self.http_client.post(
                f"{self.base_url}/call",
                json=payload,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                call_id = result.get("id")

                await self.debug_logger.log_event(
                    agent_name="VapiAdapter",
                    event_type="call_initiated",
                    message=f"Call initiated with ID: {call_id}",
                    output_payload={"call_id": call_id, "status": "initiated"},
                )

                return {
                    "status": "initiated",
                    "call_id": call_id,
                }
            else:
                error = f"Vapi returned {response.status_code}"
                await self.debug_logger.log_event(
                    agent_name="VapiAdapter",
                    event_type="call_failed",
                    level="error",
                    message=error,
                    error=error,
                )
                return {"status": "failed", "error": error}

        except Exception as e:
            error = str(e)
            await self.debug_logger.log_event(
                agent_name="VapiAdapter",
                event_type="call_failed",
                level="error",
                message=f"Failed to initiate call: {error}",
                error=error,
            )
            return {"status": "failed", "error": error}

    async def get_call_status(self, call_id: str) -> dict:
        """Get the status of a Vapi call."""
        try:
            response = await self.http_client.get(
                f"{self.base_url}/call/{call_id}",
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "status": result.get("status", "unknown"),
                    "duration_seconds": result.get("duration"),
                    "transcript": result.get("transcript"),
                }
            else:
                return {"status": "error", "error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def is_available(self) -> bool:
        """Check if Vapi is available."""
        try:
            response = await self.http_client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Vapi health check failed: {e}")
            return False
