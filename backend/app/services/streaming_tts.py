"""Streaming TTS management and optimization.

Coordinates parallel text generation, TTS synthesis, and playback
with performance optimization and validation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, AsyncIterator
from enum import Enum

logger = logging.getLogger(__name__)


class StreamingPhase(str, Enum):
    """Phases of streaming TTS operation."""

    IDLE = "idle"
    BUFFERING = "buffering"  # Accumulating text before TTS
    GENERATING = "generating"  # TTS synthesizing
    PLAYING = "playing"  # Audio playing
    COMPLETE = "complete"


@dataclass
class StreamingMetrics:
    """Performance metrics for streaming TTS."""

    phase: StreamingPhase = StreamingPhase.IDLE
    total_text_chars: int = 0
    total_audio_bytes: int = 0
    chunks_generated: int = 0
    chunks_played: int = 0

    # Latency tracking
    time_to_first_audio_ms: Optional[int] = None
    time_to_complete_ms: Optional[int] = None
    avg_chunk_generation_ms: int = 0
    avg_chunk_playback_ms: int = 0

    # Errors
    underrun_count: int = 0  # Buffer underflow
    overflow_count: int = 0  # Buffer overflow
    generation_errors: int = 0
    playback_errors: int = 0

    started_at: Optional[datetime] = None
    first_audio_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def elapsed_ms(self) -> int:
        """Total elapsed time."""
        if self.started_at:
            end = self.completed_at or datetime.utcnow()
            return int((end - self.started_at).total_seconds() * 1000)
        return 0

    def time_to_first_audio_actual_ms(self) -> Optional[int]:
        """Actual time to first audio."""
        if self.started_at and self.first_audio_at:
            return int(
                (self.first_audio_at - self.started_at).total_seconds() * 1000
            )
        return None


class StreamingTTSValidator:
    """Validates streaming TTS performance and behavior."""

    def __init__(self, run_id: str = ""):
        """Initialize validator.

        Args:
            run_id: Call identifier
        """
        self.run_id = run_id
        self.metrics = StreamingMetrics()

    def validate_time_to_first_audio(self, actual_ms: int, target_ms: int = 1000) -> bool:
        """Validate time to first audio meets target.

        Args:
            actual_ms: Actual time to first audio
            target_ms: Target time (default 1000ms)

        Returns:
            True if within target, False otherwise
        """
        if actual_ms > target_ms:
            logger.warning(
                f"Time to first audio exceeded target: "
                f"{actual_ms}ms > {target_ms}ms"
            )
            return False

        logger.info(f"Time to first audio within target: {actual_ms}ms ≤ {target_ms}ms")
        return True

    def validate_chunk_size(self, chunk_size_bytes: int) -> bool:
        """Validate audio chunk size is reasonable.

        Args:
            chunk_size_bytes: Size of audio chunk

        Returns:
            True if valid, False otherwise
        """
        min_size = 256  # Minimum chunk size
        max_size = 65536  # Maximum chunk size (64KB)

        if chunk_size_bytes < min_size:
            logger.warning(f"Chunk size too small: {chunk_size_bytes} < {min_size}")
            return False

        if chunk_size_bytes > max_size:
            logger.warning(f"Chunk size too large: {chunk_size_bytes} > {max_size}")
            return False

        return True

    def validate_buffer_health(
        self,
        buffer_size: int,
        buffer_max: int,
    ) -> bool:
        """Validate buffer is in healthy state.

        Args:
            buffer_size: Current buffer size
            buffer_max: Maximum buffer size

        Returns:
            True if healthy, False otherwise
        """
        utilization = (buffer_size / buffer_max) * 100

        if utilization > 90:
            logger.warning(f"Buffer nearly full: {utilization:.1f}%")
            self.metrics.overflow_count += 1
            return False

        if utilization < 10 and self.metrics.chunks_generated > 0:
            logger.warning(f"Buffer nearly empty: {utilization:.1f}%")
            self.metrics.underrun_count += 1
            return False

        return True

    def get_validation_report(self) -> dict:
        """Get full validation report.

        Returns:
            Dictionary with validation results
        """
        return {
            "phase": self.metrics.phase.value,
            "total_text_chars": self.metrics.total_text_chars,
            "total_audio_bytes": self.metrics.total_audio_bytes,
            "chunks_generated": self.metrics.chunks_generated,
            "chunks_played": self.metrics.chunks_played,
            "time_to_first_audio_ms": self.metrics.time_to_first_audio_actual_ms(),
            "total_elapsed_ms": self.metrics.elapsed_ms(),
            "underrun_count": self.metrics.underrun_count,
            "overflow_count": self.metrics.overflow_count,
            "errors": {
                "generation": self.metrics.generation_errors,
                "playback": self.metrics.playback_errors,
            },
            "health_status": "healthy"
            if (self.metrics.underrun_count == 0 and self.metrics.overflow_count == 0)
            else "degraded",
        }


class StreamingTTSManager:
    """High-level manager for streaming TTS operations.

    Coordinates:
    - Text accumulation (LLM → TextBuffer)
    - TTS generation (TextBuffer → TTS API → Audio)
    - Playback (Audio → Speaker)
    - Performance monitoring
    """

    def __init__(
        self,
        tts_client,
        run_id: str = "",
        target_first_audio_ms: int = 1000,
    ):
        """Initialize streaming TTS manager.

        Args:
            tts_client: ElevenLabs TTS client
            run_id: Call identifier
            target_first_audio_ms: Target for time to first audio
        """
        self.tts_client = tts_client
        self.run_id = run_id
        self.target_first_audio_ms = target_first_audio_ms

        self.validator = StreamingTTSValidator(run_id)
        self.metrics = self.validator.metrics

    async def stream_response(
        self,
        llm_stream: AsyncIterator[str],
        text_buffer_size: int = 50,
    ) -> AsyncIterator[dict]:
        """Stream a response from LLM through TTS to playback.

        Yields chunks with metadata for monitoring.

        Args:
            llm_stream: Async iterator of text tokens from LLM
            text_buffer_size: Minimum characters before sending to TTS

        Yields:
            Dictionary with audio chunk and metadata
        """
        self.metrics.started_at = datetime.utcnow()
        self.metrics.phase = StreamingPhase.BUFFERING

        text_buffer = ""
        tts_queue = asyncio.Queue(maxsize=3)
        playback_queue = asyncio.Queue(maxsize=3)

        async def accumulate_text():
            """Accumulate LLM tokens."""
            nonlocal text_buffer
            async for token in llm_stream:
                text_buffer += token
                self.metrics.total_text_chars += len(token)

                if len(text_buffer) >= text_buffer_size:
                    chunk = text_buffer
                    text_buffer = ""
                    await tts_queue.put(chunk)

            # Flush remaining
            if text_buffer.strip():
                await tts_queue.put(text_buffer)

            await tts_queue.put(None)  # EOF

        async def generate_tts():
            """Generate TTS audio."""
            self.metrics.phase = StreamingPhase.GENERATING
            chunk_num = 0

            while True:
                text_chunk = await tts_queue.get()
                if text_chunk is None:
                    break

                try:
                    audio_data = b""
                    async for audio_chunk in self.tts_client.synthesize_stream(
                        text_chunk
                    ):
                        audio_data += audio_chunk
                        self.metrics.total_audio_bytes += len(audio_chunk)

                        # Validate chunk size
                        if audio_data:
                            self.validator.validate_chunk_size(len(audio_data))

                    await playback_queue.put({
                        "audio": audio_data,
                        "text": text_chunk,
                        "chunk_num": chunk_num,
                    })
                    chunk_num += 1
                    self.metrics.chunks_generated += 1

                except Exception as e:
                    logger.error(f"TTS generation error: {e}")
                    self.metrics.generation_errors += 1
                    await playback_queue.put(None)

            await playback_queue.put(None)  # EOF

        async def stream_playback():
            """Yield chunks for playback."""
            self.metrics.phase = StreamingPhase.PLAYING
            chunk_num = 0

            while True:
                chunk_data = await playback_queue.get()
                if chunk_data is None:
                    break

                # Record time to first audio
                if chunk_num == 0 and self.metrics.first_audio_at is None:
                    self.metrics.first_audio_at = datetime.utcnow()
                    ttfa = self.metrics.time_to_first_audio_actual_ms()
                    logger.info(f"First audio generated in {ttfa}ms")
                    self.validator.validate_time_to_first_audio(
                        ttfa or 0, self.target_first_audio_ms
                    )

                yield {
                    "audio": chunk_data.get("audio"),
                    "text": chunk_data.get("text"),
                    "chunk_num": chunk_data.get("chunk_num"),
                    "is_final": playback_queue.empty(),
                    "total_audio_bytes": self.metrics.total_audio_bytes,
                }

                chunk_num += 1
                self.metrics.chunks_played += 1

        try:
            # Run accumulate and generate concurrently
            await asyncio.gather(
                accumulate_text(),
                generate_tts(),
                return_exceptions=False,
            )

            # Stream playback
            async for chunk in stream_playback():
                yield chunk

        finally:
            self.metrics.phase = StreamingPhase.COMPLETE
            self.metrics.completed_at = datetime.utcnow()

            # Log final metrics
            logger.info(f"Streaming TTS complete: {self.get_metrics()}")

    def get_metrics(self) -> dict:
        """Get current streaming metrics.

        Returns:
            Dictionary with metrics
        """
        return {
            "phase": self.metrics.phase.value,
            "total_text_chars": self.metrics.total_text_chars,
            "total_audio_bytes": self.metrics.total_audio_bytes,
            "chunks_generated": self.metrics.chunks_generated,
            "chunks_played": self.metrics.chunks_played,
            "time_to_first_audio_ms": self.metrics.time_to_first_audio_actual_ms(),
            "total_elapsed_ms": self.metrics.elapsed_ms(),
            "errors": {
                "underrun": self.metrics.underrun_count,
                "overflow": self.metrics.overflow_count,
                "generation": self.metrics.generation_errors,
                "playback": self.metrics.playback_errors,
            },
        }
