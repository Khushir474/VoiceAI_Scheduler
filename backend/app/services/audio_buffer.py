"""Audio buffer management for streaming voice interactions.

Implements a thread-safe ring buffer for managing audio chunks from Vapi,
with overflow handling, packet loss detection, and latency tracking.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A single audio chunk from the network."""

    sequence_number: int
    data: bytes
    timestamp: datetime = field(default_factory=datetime.utcnow)
    received_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def latency_ms(self) -> int:
        """Milliseconds between creation and receipt."""
        return int((self.received_at - self.timestamp).total_seconds() * 1000)


class AudioBuffer:
    """Ring buffer for streaming audio chunks.

    Manages incoming audio from Vapi with:
    - Fixed-size ring buffer (prevents unbounded memory growth)
    - Packet loss detection (tracks sequence numbers)
    - Overflow handling (logs and drops oldest chunks)
    - Latency tracking (per-chunk and aggregate)
    """

    def __init__(
        self,
        max_size: int = 100,
        run_id: str = "",
    ):
        """Initialize audio buffer.

        Args:
            max_size: Maximum number of chunks to buffer (prevents OOM)
            run_id: Call identifier for logging
        """
        self.max_size = max_size
        self.run_id = run_id
        self.buffer: deque[AudioChunk] = deque(maxlen=max_size)
        self.last_sequence_number = -1
        self.packet_loss_count = 0
        self.overflow_count = 0
        self.total_chunks_received = 0
        self.bytes_received = 0

    def add_chunk(self, chunk: AudioChunk) -> bool:
        """Add an audio chunk to the buffer.

        Detects packet loss by checking sequence numbers.
        Logs overflow if buffer reaches capacity.

        Args:
            chunk: AudioChunk to add

        Returns:
            True if chunk was added, False if buffer was full (overflow)
        """
        self.total_chunks_received += 1
        self.bytes_received += len(chunk.data)

        # Detect packet loss
        if chunk.sequence_number > self.last_sequence_number + 1:
            lost_packets = chunk.sequence_number - self.last_sequence_number - 1
            self.packet_loss_count += lost_packets
            logger.warning(
                f"Packet loss detected: {lost_packets} packets "
                f"(seq {self.last_sequence_number + 1}-{chunk.sequence_number - 1})"
            )

        # Check for overflow (buffer at capacity before adding)
        if len(self.buffer) >= self.max_size:
            self.overflow_count += 1
            logger.warning(
                f"Audio buffer overflow: dropping oldest chunk "
                f"(overflow_count={self.overflow_count})"
            )

        # Add to buffer (deque automatically removes oldest if full)
        self.buffer.append(chunk)
        self.last_sequence_number = chunk.sequence_number

        return True

    def get_chunk(self) -> Optional[AudioChunk]:
        """Remove and return the oldest chunk from the buffer.

        Returns:
            AudioChunk if available, None if buffer is empty
        """
        try:
            return self.buffer.popleft()
        except IndexError:
            return None

    def peek_chunk(self) -> Optional[AudioChunk]:
        """View the oldest chunk without removing it.

        Returns:
            AudioChunk if available, None if buffer is empty
        """
        try:
            return self.buffer[0]
        except IndexError:
            return None

    def size(self) -> int:
        """Return current number of chunks in buffer."""
        return len(self.buffer)

    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return len(self.buffer) == 0

    def is_full(self) -> bool:
        """Check if buffer is at capacity."""
        return len(self.buffer) >= self.max_size

    def clear(self):
        """Clear all chunks from buffer."""
        self.buffer.clear()
        logger.debug(f"Cleared audio buffer (run_id={self.run_id})")

    def get_stats(self) -> dict:
        """Get buffer statistics for monitoring."""
        avg_latency_ms = 0
        if self.buffer:
            avg_latency = sum(c.latency_ms for c in self.buffer) / len(self.buffer)
            avg_latency_ms = int(avg_latency)

        return {
            "size": len(self.buffer),
            "max_size": self.max_size,
            "total_chunks_received": self.total_chunks_received,
            "bytes_received": self.bytes_received,
            "packet_loss_count": self.packet_loss_count,
            "overflow_count": self.overflow_count,
            "average_latency_ms": avg_latency_ms,
            "utilization_percent": int((len(self.buffer) / self.max_size) * 100),
        }

    def log_stats(self):
        """Log buffer statistics."""
        stats = self.get_stats()
        logger.info(
            f"Audio buffer stats (run_id={self.run_id}): "
            f"size={stats['size']}/{stats['max_size']}, "
            f"chunks={stats['total_chunks_received']}, "
            f"packet_loss={stats['packet_loss_count']}, "
            f"overflow={stats['overflow_count']}, "
            f"avg_latency={stats['average_latency_ms']}ms"
        )


class VADEventQueue:
    """Queue for voice activity detection (VAD) events from Vapi.

    Decouples VAD signal processing from WebSocket event handling.
    """

    class VADEvent:
        """Voice activity event."""

        def __init__(
            self,
            vad_state: str,  # "speaking" or "idle"
            confidence: float,  # 0.0-1.0
            timestamp: datetime = None,
        ):
            self.vad_state = vad_state
            self.confidence = confidence
            self.timestamp = timestamp or datetime.utcnow()

        def __repr__(self):
            return f"VADEvent(state={self.vad_state}, confidence={self.confidence:.2f})"

    def __init__(self, maxsize: int = 50):
        """Initialize VAD event queue.

        Args:
            maxsize: Maximum events to queue
        """
        self.queue: deque[VADEventQueue.VADEvent] = deque(maxlen=maxsize)
        self.overflow_count = 0

    def put(self, event: "VADEventQueue.VADEvent"):
        """Add a VAD event to the queue.

        Args:
            event: VADEvent to queue
        """
        if len(self.queue) >= self.queue.maxlen:
            self.overflow_count += 1
            logger.warning(f"VAD event queue overflow (count={self.overflow_count})")

        self.queue.append(event)

    def get(self) -> Optional["VADEventQueue.VADEvent"]:
        """Remove and return the oldest VAD event.

        Returns:
            VADEvent if available, None if queue is empty
        """
        try:
            return self.queue.popleft()
        except IndexError:
            return None

    def peek(self) -> Optional["VADEventQueue.VADEvent"]:
        """View the oldest event without removing it."""
        try:
            return self.queue[0]
        except IndexError:
            return None

    def size(self) -> int:
        """Return number of events in queue."""
        return len(self.queue)

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self.queue) == 0

    def clear(self):
        """Clear all events from queue."""
        self.queue.clear()
