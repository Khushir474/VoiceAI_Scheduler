"""Vapi WebSocket integration for real-time voice interaction.

Handles:
- WebSocket connection lifecycle (connect, heartbeat, reconnect)
- Audio chunk streaming from Vapi
- VAD (Voice Activity Detection) signals
- Real-time event dispatching
- Graceful disconnect and reconnection with exponential backoff
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional
from enum import Enum

import websockets

from app.services.audio_buffer import AudioBuffer, AudioChunk, VADEventQueue

logger = logging.getLogger(__name__)


class VapiEventType(str, Enum):
    """Vapi WebSocket event types."""

    # Connection lifecycle
    CLIENT_READY = "client-ready"
    SESSION_STARTED = "session-started"
    SESSION_ENDED = "session-ended"
    DISCONNECT = "disconnect"

    # Audio events
    AUDIO_CHUNK = "audio-chunk"
    TRANSCRIPT = "transcript"

    # VAD events
    VAD_UPDATED = "vad-updated"

    # Status
    STATUS = "status"
    ERROR = "error"


class VapiConnectionState(str, Enum):
    """Connection state tracking."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class VapiWebSocketClient:
    """WebSocket client for Vapi voice interactions.

    Maintains a persistent connection to Vapi, handles reconnection,
    buffers audio, and dispatches events to handlers.
    """

    def __init__(
        self,
        vapi_api_key: str,
        run_id: str,
        user_id: str,
        max_reconnect_attempts: int = 5,
        base_backoff_ms: int = 1000,
    ):
        """Initialize Vapi WebSocket client.

        Args:
            vapi_api_key: Vapi API key from config
            run_id: Unique call identifier
            user_id: User UUID
            max_reconnect_attempts: Max reconnect retries (exponential backoff)
            base_backoff_ms: Initial backoff in milliseconds
        """
        self.vapi_api_key = vapi_api_key
        self.run_id = run_id
        self.user_id = user_id
        self.max_reconnect_attempts = max_reconnect_attempts
        self.base_backoff_ms = base_backoff_ms

        # Connection management
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.state = VapiConnectionState.DISCONNECTED
        self.reconnect_attempts = 0

        # Audio buffering
        self.audio_buffer = AudioBuffer(max_size=100, run_id=run_id)
        self.vad_queue = VADEventQueue(maxsize=50)

        # Event handlers
        self.event_handlers: dict[VapiEventType, list[Callable]] = {
            event_type: [] for event_type in VapiEventType
        }

        # Stats
        self.connected_at: Optional[datetime] = None
        self.total_events_received = 0
        self.audio_chunks_received = 0

    def on(self, event_type: VapiEventType, handler: Callable):
        """Register an event handler.

        Args:
            event_type: Event type to listen for
            handler: Async callable(event_data)
        """
        self.event_handlers[event_type].append(handler)
        logger.debug(f"Registered handler for {event_type.value}")

    async def _dispatch_event(self, event_type: VapiEventType, data: dict):
        """Dispatch an event to all registered handlers.

        Args:
            event_type: Event type
            data: Event data
        """
        handlers = self.event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Error in event handler for {event_type.value}: {e}")

    async def _handle_audio_chunk(self, data: dict):
        """Handle audio chunk event.

        Args:
            data: Event data containing audio and sequence number
        """
        try:
            audio_bytes = data.get("chunk", b"")
            sequence = data.get("sequence", self.audio_chunks_received)

            if isinstance(audio_bytes, str):
                # Decode base64 if needed
                import base64
                audio_bytes = base64.b64decode(audio_bytes)

            chunk = AudioChunk(
                sequence_number=sequence,
                data=audio_bytes,
            )
            self.audio_buffer.add_chunk(chunk)
            self.audio_chunks_received += 1

            logger.debug(
                f"Received audio chunk: seq={sequence}, "
                f"size={len(audio_bytes)}, buffer_size={self.audio_buffer.size()}"
            )

            # Dispatch to handlers
            await self._dispatch_event(VapiEventType.AUDIO_CHUNK, {
                "chunk": chunk,
                "buffer_size": self.audio_buffer.size(),
            })
        except Exception as e:
            logger.error(f"Error handling audio chunk: {e}")

    async def _handle_vad_updated(self, data: dict):
        """Handle VAD (Voice Activity Detection) update.

        Args:
            data: Event data with vad_state and confidence
        """
        try:
            vad_state = data.get("vad_state", "unknown")  # "speaking" or "idle"
            confidence = data.get("confidence", 0.0)

            event = VADEventQueue.VADEvent(
                vad_state=vad_state,
                confidence=confidence,
            )
            self.vad_queue.put(event)

            logger.debug(f"VAD updated: {event}")

            # Dispatch to handlers
            await self._dispatch_event(VapiEventType.VAD_UPDATED, {
                "vad_state": vad_state,
                "confidence": confidence,
            })
        except Exception as e:
            logger.error(f"Error handling VAD update: {e}")

    async def _handle_transcript(self, data: dict):
        """Handle transcript update.

        Args:
            data: Event data with transcript text
        """
        try:
            transcript = data.get("transcript", "")
            is_final = data.get("is_final", False)

            logger.debug(
                f"Transcript: {transcript} "
                f"(final={is_final})"
            )

            # Dispatch to handlers
            await self._dispatch_event(VapiEventType.TRANSCRIPT, {
                "transcript": transcript,
                "is_final": is_final,
            })
        except Exception as e:
            logger.error(f"Error handling transcript: {e}")

    async def _process_message(self, message: str):
        """Process incoming WebSocket message.

        Args:
            message: JSON string from Vapi
        """
        try:
            data = json.loads(message)
            event_type_str = data.get("type", "unknown")

            self.total_events_received += 1

            # Route to specific handlers
            if event_type_str == VapiEventType.AUDIO_CHUNK.value:
                await self._handle_audio_chunk(data)
            elif event_type_str == VapiEventType.VAD_UPDATED.value:
                await self._handle_vad_updated(data)
            elif event_type_str == VapiEventType.TRANSCRIPT.value:
                await self._handle_transcript(data)
            else:
                # Generic dispatch for other event types
                try:
                    event_type = VapiEventType(event_type_str)
                    await self._dispatch_event(event_type, data)
                except ValueError:
                    logger.warning(f"Unknown event type: {event_type_str}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Vapi message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def _send_heartbeat(self):
        """Send periodic heartbeat to keep connection alive."""
        while self.state == VapiConnectionState.CONNECTED:
            try:
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
                if self.websocket and not self.websocket.closed:
                    await self.websocket.send(json.dumps({
                        "type": "ping",
                        "timestamp": datetime.utcnow().isoformat(),
                    }))
                    logger.debug("Sent heartbeat to Vapi")
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")

    async def connect(self) -> bool:
        """Establish WebSocket connection to Vapi.

        Returns:
            True if connected, False if connection failed
        """
        if self.state == VapiConnectionState.CONNECTED:
            logger.warning("Already connected to Vapi")
            return True

        self.state = VapiConnectionState.CONNECTING
        vapi_url = f"wss://api.vapi.ai/ws?apiKey={self.vapi_api_key}"

        try:
            self.websocket = await websockets.connect(
                vapi_url,
                close_timeout=10,
                compression=None,
            )
            self.state = VapiConnectionState.CONNECTED
            self.connected_at = datetime.utcnow()
            self.reconnect_attempts = 0

            logger.info(
                f"Connected to Vapi WebSocket "
                f"(run_id={self.run_id}, user_id={self.user_id})"
            )

            # Dispatch connection event
            await self._dispatch_event(VapiEventType.SESSION_STARTED, {
                "timestamp": self.connected_at.isoformat(),
                "run_id": self.run_id,
            })

            return True
        except Exception as e:
            logger.error(f"Failed to connect to Vapi: {e}")
            self.state = VapiConnectionState.FAILED
            return False

    async def disconnect(self):
        """Close WebSocket connection gracefully."""
        if self.websocket and not self.websocket.closed:
            try:
                await self.websocket.close()
                logger.info("Disconnected from Vapi WebSocket")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")

        self.state = VapiConnectionState.DISCONNECTED
        await self._dispatch_event(VapiEventType.SESSION_ENDED, {
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def _reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff.

        Returns:
            True if reconnected, False if max attempts exceeded
        """
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max reconnection attempts exceeded")
            self.state = VapiConnectionState.FAILED
            return False

        backoff_ms = self.base_backoff_ms * (2 ** self.reconnect_attempts)
        self.reconnect_attempts += 1

        logger.info(
            f"Reconnecting to Vapi (attempt {self.reconnect_attempts}, "
            f"backoff {backoff_ms}ms)"
        )

        self.state = VapiConnectionState.RECONNECTING
        await asyncio.sleep(backoff_ms / 1000)

        return await self.connect()

    async def listen(self):
        """Listen for incoming messages from Vapi.

        Blocks until connection is closed or error occurs.
        Automatically attempts reconnection on disconnect.
        """
        if self.state != VapiConnectionState.CONNECTED:
            logger.error("Not connected. Call connect() first.")
            return

        try:
            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._send_heartbeat())

            async for message in self.websocket:
                await self._process_message(message)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Vapi WebSocket connection closed")
            self.state = VapiConnectionState.DISCONNECTED

            # Attempt reconnection
            if await self._reconnect():
                logger.info("Reconnected, resuming listen...")
                await self.listen()
            else:
                logger.error("Failed to reconnect to Vapi")

        except Exception as e:
            logger.error(f"Error in listen loop: {e}")
            self.state = VapiConnectionState.FAILED

        finally:
            await self.disconnect()

    async def send_audio(self, audio_bytes: bytes) -> bool:
        """Send audio bytes to Vapi.

        Args:
            audio_bytes: Audio data to send

        Returns:
            True if sent successfully
        """
        if self.state != VapiConnectionState.CONNECTED or not self.websocket:
            logger.error("Not connected to Vapi")
            return False

        try:
            import base64
            encoded = base64.b64encode(audio_bytes).decode("utf-8")

            message = json.dumps({
                "type": "audio",
                "audio": encoded,
                "timestamp": datetime.utcnow().isoformat(),
            })

            await self.websocket.send(message)
            logger.debug(f"Sent audio: {len(audio_bytes)} bytes")
            return True

        except Exception as e:
            logger.error(f"Failed to send audio: {e}")
            return False

    def get_audio_chunk(self) -> Optional[AudioChunk]:
        """Get next audio chunk from buffer.

        Returns:
            AudioChunk if available, None if buffer empty
        """
        return self.audio_buffer.get_chunk()

    def get_vad_event(self) -> Optional[VADEventQueue.VADEvent]:
        """Get next VAD event from queue.

        Returns:
            VADEvent if available, None if queue empty
        """
        return self.vad_queue.get()

    def get_stats(self) -> dict:
        """Get connection and buffer statistics."""
        uptime_seconds = 0
        if self.connected_at:
            uptime_seconds = int((datetime.utcnow() - self.connected_at).total_seconds())

        return {
            "state": self.state.value,
            "uptime_seconds": uptime_seconds,
            "total_events_received": self.total_events_received,
            "audio_chunks_received": self.audio_chunks_received,
            "reconnect_attempts": self.reconnect_attempts,
            "audio_buffer": self.audio_buffer.get_stats(),
            "vad_queue_size": self.vad_queue.size(),
        }

    def log_stats(self):
        """Log connection statistics."""
        stats = self.get_stats()
        logger.info(
            f"Vapi WebSocket stats: "
            f"state={stats['state']}, "
            f"uptime={stats['uptime_seconds']}s, "
            f"events={stats['total_events_received']}, "
            f"chunks={stats['audio_chunks_received']}, "
            f"reconnects={stats['reconnect_attempts']}, "
            f"buffer_size={stats['audio_buffer']['size']}/{stats['audio_buffer']['max_size']}"
        )
