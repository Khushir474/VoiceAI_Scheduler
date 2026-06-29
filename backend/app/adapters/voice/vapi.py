"""Vapi voice adapter implementation with real API calls and state tracking."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from app.adapters.voice.base import VoiceAdapter
from app.adapters.voice.vapi_websocket import VapiWebSocketClient, VapiConnectionState
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class VapiCallState:
    """Tracks the state of a Vapi call."""

    def __init__(self, call_id: str, run_id: str):
        self.call_id = call_id
        self.run_id = run_id
        self.status = "queued"  # queued → ringing → in_call → ended
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.duration_seconds: int = 0
        self.transcript: str = ""
        self.error: Optional[str] = None
        self.vapi_response: dict = {}

    def get_duration(self) -> int:
        """Calculate call duration in seconds."""
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return self.duration_seconds


class VapiAdapter(VoiceAdapter):
    """Adapter for Vapi voice service with real API calls and WebSocket support."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        api_key: str,
        assistant_id: str | None = None,
        timeout_seconds: int = 30,
    ):
        self.debug_logger = debug_logger
        self.api_key = api_key
        self.assistant_id = assistant_id
        self.base_url = "https://api.vapi.ai"
        self.timeout_seconds = timeout_seconds
        self.http_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )
        # Track active calls
        self.active_calls: dict[str, VapiCallState] = {}
        self.websocket_clients: dict[str, VapiWebSocketClient] = {}

    async def initiate_call(self, recipient_phone: str, run_id: str) -> dict:
        """Initiate an outbound call via Vapi.

        Makes a real API call to Vapi to create an outbound call.
        Tracks call state and optionally sets up WebSocket for live streaming.

        Args:
            recipient_phone: Phone number to call (E.164 format)
            run_id: Unique run identifier for tracking

        Returns:
            dict with status, call_id, and optional error
        """
        start_time = time.time()

        await self.debug_logger.log_event(
            agent_name="VapiAdapter",
            event_type="call_initiate",
            message=f"Initiating Vapi call to {recipient_phone}",
            input_payload={"recipient": recipient_phone, "run_id": run_id},
        )

        try:
            # Validate phone number format
            if not recipient_phone or not isinstance(recipient_phone, str):
                raise ValueError("Invalid recipient phone number")

            payload = {
                "phoneNumber": recipient_phone,
                "assistantId": self.assistant_id,
                "customData": {
                    "run_id": run_id,
                    "initiated_at": datetime.utcnow().isoformat(),
                },
            }

            # Make real API call with timeout
            response = await asyncio.wait_for(
                self.http_client.post(
                    f"{self.base_url}/call",
                    json=payload,
                ),
                timeout=self.timeout_seconds,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code in [200, 201]:
                result = response.json()
                call_id = result.get("id")

                if not call_id:
                    raise ValueError("No call_id returned from Vapi API")

                # Track this call
                call_state = VapiCallState(call_id, run_id)
                call_state.status = "queued"
                call_state.vapi_response = result
                self.active_calls[call_id] = call_state

                await self.debug_logger.log_event(
                    agent_name="VapiAdapter",
                    event_type="call_initiated",
                    message=f"Call initiated with ID: {call_id} (latency: {latency_ms}ms)",
                    output_payload={
                        "call_id": call_id,
                        "status": "queued",
                        "latency_ms": latency_ms,
                    },
                    latency_ms=latency_ms,
                )

                return {
                    "status": "success",
                    "call_id": call_id,
                    "latency_ms": latency_ms,
                }
            else:
                error_msg = f"Vapi API returned {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get("message", error_msg)
                except Exception:
                    pass

                await self.debug_logger.log_event(
                    agent_name="VapiAdapter",
                    event_type="call_failed",
                    level="error",
                    message=error_msg,
                    error=error_msg,
                    output_payload={"status_code": response.status_code},
                )
                return {"status": "failed", "error": error_msg}

        except asyncio.TimeoutError:
            error = f"Call initiation timed out after {self.timeout_seconds}s"
            await self.debug_logger.log_event(
                agent_name="VapiAdapter",
                event_type="call_timeout",
                level="error",
                message=error,
                error=error,
            )
            return {"status": "timeout", "error": error}

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
        """Get the current status of a Vapi call.

        Queries Vapi API for the latest call status.

        Args:
            call_id: Vapi call ID

        Returns:
            dict with status, duration, transcript, etc.
        """
        try:
            response = await self.http_client.get(
                f"{self.base_url}/call/{call_id}",
            )

            if response.status_code == 200:
                result = response.json()

                # Update local state if we're tracking this call
                if call_id in self.active_calls:
                    call_state = self.active_calls[call_id]
                    call_state.status = result.get("status", "unknown")
                    call_state.duration_seconds = result.get("duration", 0)
                    call_state.transcript = result.get("transcript", "")

                return {
                    "status": result.get("status", "unknown"),
                    "duration_seconds": result.get("duration"),
                    "transcript": result.get("transcript"),
                    "ended_reason": result.get("endedReason"),
                }
            else:
                return {"status": "error", "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error(f"Error getting call status for {call_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def connect_websocket(
        self, call_id: str, run_id: str, user_id: str
    ) -> bool:
        """Establish WebSocket connection for live transcript streaming.

        Args:
            call_id: Vapi call ID
            run_id: Run identifier
            user_id: User identifier

        Returns:
            True if connected, False otherwise
        """
        try:
            ws_client = VapiWebSocketClient(
                vapi_api_key=self.api_key,
                run_id=run_id,
                user_id=user_id,
            )

            # Connect to Vapi WebSocket
            connected = await ws_client.connect()
            if not connected:
                logger.error(f"Failed to connect WebSocket for call {call_id}")
                return False

            # Store for later reference
            self.websocket_clients[call_id] = ws_client

            # Set up event handlers
            await self._setup_websocket_handlers(call_id, ws_client)

            logger.info(f"WebSocket connected for call {call_id}")
            return True

        except Exception as e:
            logger.error(f"Error connecting WebSocket: {e}")
            return False

    async def _setup_websocket_handlers(
        self, call_id: str, ws_client: VapiWebSocketClient
    ) -> None:
        """Set up event handlers for WebSocket client."""
        from app.adapters.voice.vapi_websocket import VapiEventType

        async def handle_transcript(data):
            """Handle transcript updates."""
            transcript = data.get("transcript", "")
            if call_id in self.active_calls:
                self.active_calls[call_id].transcript = transcript

        async def handle_audio_chunk(data):
            """Handle audio chunks."""
            logger.debug(f"Audio chunk received for call {call_id}")

        # Register handlers
        ws_client.on(VapiEventType.TRANSCRIPT, handle_transcript)
        ws_client.on(VapiEventType.AUDIO_CHUNK, handle_audio_chunk)

    async def disconnect_websocket(self, call_id: str) -> None:
        """Disconnect WebSocket for a call.

        Args:
            call_id: Vapi call ID
        """
        if call_id in self.websocket_clients:
            ws_client = self.websocket_clients[call_id]
            await ws_client.disconnect()
            del self.websocket_clients[call_id]
            logger.info(f"WebSocket disconnected for call {call_id}")

    async def update_call_state(self, call_id: str, status: str, **kwargs) -> None:
        """Update the state of a tracked call.

        Args:
            call_id: Vapi call ID
            status: New status
            **kwargs: Additional fields to update (transcript, error, etc.)
        """
        if call_id in self.active_calls:
            call_state = self.active_calls[call_id]
            call_state.status = status

            if "transcript" in kwargs:
                call_state.transcript = kwargs["transcript"]

            if "error" in kwargs:
                call_state.error = kwargs["error"]

            if "started_at" in kwargs:
                call_state.started_at = kwargs["started_at"]

            if "ended_at" in kwargs:
                call_state.ended_at = kwargs["ended_at"]

            if "duration_seconds" in kwargs:
                call_state.duration_seconds = kwargs["duration_seconds"]

    async def get_call_state(self, call_id: str) -> Optional[VapiCallState]:
        """Get the state of a tracked call.

        Args:
            call_id: Vapi call ID

        Returns:
            VapiCallState or None if not found
        """
        return self.active_calls.get(call_id)

    async def end_call(self, call_id: str) -> bool:
        """End a Vapi call.

        Args:
            call_id: Vapi call ID

        Returns:
            True if successful, False otherwise
        """
        try:
            response = await self.http_client.delete(
                f"{self.base_url}/call/{call_id}",
            )

            if response.status_code in [200, 204]:
                await self.update_call_state(call_id, "ended", ended_at=datetime.utcnow())
                await self.disconnect_websocket(call_id)
                return True
            else:
                logger.error(f"Failed to end call {call_id}: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error ending call {call_id}: {e}")
            return False

    async def is_available(self) -> bool:
        """Check if Vapi is available.

        Returns:
            True if Vapi API is reachable
        """
        try:
            response = await asyncio.wait_for(
                self.http_client.get(f"{self.base_url}/health"),
                timeout=5,
            )
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Vapi health check failed: {e}")
            return False

    async def cleanup(self) -> None:
        """Clean up resources (close HTTP client and WebSocket connections)."""
        # Close all WebSocket connections
        for call_id in list(self.websocket_clients.keys()):
            await self.disconnect_websocket(call_id)

        # Close HTTP client
        await self.http_client.aclose()
        logger.info("VapiAdapter cleanup completed")

    def get_active_calls_count(self) -> int:
        """Get number of active calls being tracked.

        Returns:
            Count of active calls
        """
        return len(self.active_calls)
