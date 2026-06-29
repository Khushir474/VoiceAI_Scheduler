"""TTS playback control and interruption handling.

Manages the lifecycle of text-to-speech playback:
- State transitions (IDLE → GENERATING → PLAYING → PAUSED → STOPPED)
- Pause/resume without artifacts
- Immediate stop on barge-in
- Cleanup of audio resources
"""

import asyncio
import logging
from typing import Optional, Callable
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class PlaybackState(str, Enum):
    """Playback state machine."""

    IDLE = "idle"
    GENERATING = "generating"  # TTS generating audio
    PLAYING = "playing"  # Audio actively playing
    PAUSED = "paused"  # Audio paused (can resume)
    STOPPED = "stopped"  # Stopped (cannot resume)
    ERROR = "error"


@dataclass
class PlaybackPosition:
    """Track current playback position."""

    audio_bytes_played: int = 0  # Bytes already played
    total_audio_bytes: int = 0  # Total bytes to play
    percentage_complete: float = 0.0
    started_at: Optional[datetime] = None
    current_time_ms: int = 0

    def update_progress(self, bytes_played: int, total_bytes: int):
        """Update playback progress."""
        self.audio_bytes_played = bytes_played
        self.total_audio_bytes = total_bytes
        if total_bytes > 0:
            self.percentage_complete = (bytes_played / total_bytes) * 100

    def elapsed_ms(self) -> int:
        """Milliseconds since playback started."""
        if self.started_at:
            return int((datetime.utcnow() - self.started_at).total_seconds() * 1000)
        return 0


class PlaybackController:
    """Controls TTS playback lifecycle and interruption.

    State Machine:
    ```
    IDLE
      ↓
    GENERATING (TTS is synthesizing)
      ↓
    PLAYING (audio is playing)
      ├─ pause() → PAUSED
      │   └─ resume() → PLAYING
      └─ stop() → STOPPED
      │   └─ (cannot resume from STOPPED)
      └─ error() → ERROR
    ```
    """

    def __init__(
        self,
        run_id: str = "",
        audio_sample_rate: int = 16000,  # 16kHz
        audio_bit_depth: int = 16,  # 16-bit
    ):
        """Initialize playback controller.

        Args:
            run_id: Call identifier
            audio_sample_rate: Sample rate in Hz (default 16kHz)
            audio_bit_depth: Bit depth (16 or 24)
        """
        self.run_id = run_id
        self.sample_rate = audio_sample_rate
        self.bit_depth = audio_bit_depth

        # State tracking
        self.state = PlaybackState.IDLE
        self.position = PlaybackPosition()
        self.started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None

        # Callbacks
        self.on_playback_started: Optional[Callable] = None
        self.on_playback_ended: Optional[Callable] = None
        self.on_playback_stopped: Optional[Callable] = None

        # Metrics
        self.total_audio_played: int = 0
        self.interruption_count = 0
        self.pause_count = 0
        self.error_count = 0

    async def start_generating(self):
        """Mark TTS generation as started."""
        if self.state != PlaybackState.IDLE:
            logger.warning(
                f"Cannot start generating from state {self.state.value} "
                f"(current state must be IDLE)"
            )
            return

        self.state = PlaybackState.GENERATING
        logger.debug(f"Playback state: IDLE → GENERATING")

    async def start_playing(self):
        """Mark playback as started.

        Called when first audio chunk starts playing.
        """
        if self.state != PlaybackState.GENERATING:
            logger.warning(
                f"Cannot start playing from state {self.state.value} "
                f"(current state must be GENERATING)"
            )
            return

        self.state = PlaybackState.PLAYING
        self.started_at = datetime.utcnow()
        self.position.started_at = self.started_at

        logger.debug(f"Playback state: GENERATING → PLAYING")

        # Trigger callback
        if self.on_playback_started:
            try:
                await self.on_playback_started()
            except Exception as e:
                logger.error(f"Error in on_playback_started callback: {e}")

    async def pause(self) -> bool:
        """Pause playback (can be resumed).

        Returns:
            True if paused, False if already paused/stopped
        """
        if self.state not in [PlaybackState.PLAYING, PlaybackState.GENERATING]:
            logger.warning(f"Cannot pause from state {self.state.value}")
            return False

        self.state = PlaybackState.PAUSED
        self.pause_count += 1

        logger.debug(
            f"Playback paused (position: {self.position.percentage_complete:.1f}%, "
            f"bytes: {self.position.audio_bytes_played}/{self.position.total_audio_bytes})"
        )
        return True

    async def resume(self) -> bool:
        """Resume playback from pause.

        Returns:
            True if resumed, False if not in PAUSED state
        """
        if self.state != PlaybackState.PAUSED:
            logger.warning(f"Cannot resume from state {self.state.value}")
            return False

        self.state = PlaybackState.PLAYING
        logger.debug("Playback resumed")
        return True

    async def stop(self) -> bool:
        """Stop playback immediately.

        Transitions to STOPPED state (cannot resume from here).
        Called on barge-in or call end.

        Returns:
            True if stopped, False if already stopped
        """
        if self.state == PlaybackState.STOPPED:
            logger.warning("Already stopped")
            return False

        if self.state == PlaybackState.ERROR:
            logger.warning("Cannot stop from ERROR state")
            return False

        old_state = self.state
        self.state = PlaybackState.STOPPED
        self.stopped_at = datetime.utcnow()
        self.interruption_count += 1

        logger.info(
            f"Playback stopped from {old_state.value} "
            f"(interruption_count={self.interruption_count}, "
            f"position: {self.position.percentage_complete:.1f}%)"
        )

        # Trigger callback
        if self.on_playback_stopped:
            try:
                await self.on_playback_stopped()
            except Exception as e:
                logger.error(f"Error in on_playback_stopped callback: {e}")

        return True

    async def mark_error(self, error: Exception | str):
        """Mark playback as errored.

        Args:
            error: Error that occurred
        """
        old_state = self.state
        self.state = PlaybackState.ERROR
        self.error_count += 1

        logger.error(
            f"Playback error from state {old_state.value}: {error} "
            f"(error_count={self.error_count})"
        )

    async def update_playback_position(
        self,
        bytes_played: int,
        total_bytes: int,
    ):
        """Update current playback position.

        Args:
            bytes_played: Bytes played so far
            total_bytes: Total bytes in stream
        """
        if self.state == PlaybackState.PLAYING:
            self.position.update_progress(bytes_played, total_bytes)
            self.total_audio_played = bytes_played

    async def finish_playback(self):
        """Mark playback as complete.

        Called when all audio has been played.
        """
        if self.state != PlaybackState.PLAYING:
            logger.warning(f"Cannot finish playback from state {self.state.value}")
            return

        self.state = PlaybackState.IDLE
        logger.debug("Playback finished (state: PLAYING → IDLE)")

        # Trigger callback
        if self.on_playback_ended:
            try:
                await self.on_playback_ended()
            except Exception as e:
                logger.error(f"Error in on_playback_ended callback: {e}")

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self.state == PlaybackState.PLAYING

    def is_paused(self) -> bool:
        """Check if audio is paused."""
        return self.state == PlaybackState.PAUSED

    def is_stopped(self) -> bool:
        """Check if playback has stopped."""
        return self.state == PlaybackState.STOPPED

    def can_resume(self) -> bool:
        """Check if playback can be resumed."""
        return self.state == PlaybackState.PAUSED

    def get_playback_duration_ms(self) -> int:
        """Get total elapsed playback time in milliseconds."""
        if self.started_at:
            end_time = self.stopped_at or datetime.utcnow()
            return int((end_time - self.started_at).total_seconds() * 1000)
        return 0

    def get_metrics(self) -> dict:
        """Get playback metrics for monitoring.

        Returns:
            Dictionary with playback statistics
        """
        return {
            "state": self.state.value,
            "total_audio_played_bytes": self.total_audio_played,
            "position_percentage": self.position.percentage_complete,
            "interruption_count": self.interruption_count,
            "pause_count": self.pause_count,
            "error_count": self.error_count,
            "elapsed_ms": self.get_playback_duration_ms(),
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
        }


class PlaybackInterruptionHandler:
    """Coordinates playback interruption on barge-in.

    Ensures interruption happens within latency budget (< 100ms)
    and handles cleanup.
    """

    def __init__(
        self,
        playback_controller: PlaybackController,
        run_id: str = "",
        max_interruption_latency_ms: int = 100,
    ):
        """Initialize interruption handler.

        Args:
            playback_controller: PlaybackController instance
            run_id: Call identifier
            max_interruption_latency_ms: Latency budget for interrupt (ms)
        """
        self.controller = playback_controller
        self.run_id = run_id
        self.max_latency_ms = max_interruption_latency_ms

        # Tracking
        self.interruption_detected_at: Optional[datetime] = None
        self.interruption_latency_ms: int = 0

    async def interrupt_playback(self) -> bool:
        """Interrupt playback immediately on barge-in.

        Records interruption latency.

        Returns:
            True if interrupted, False if already stopped/not playing
        """
        self.interruption_detected_at = datetime.utcnow()

        if not self.controller.is_playing():
            logger.warning(
                f"Cannot interrupt: playback not in PLAYING state "
                f"(current: {self.controller.state.value})"
            )
            return False

        # Stop playback
        success = await self.controller.stop()

        if success:
            # Record latency
            if self.controller.started_at:
                self.interruption_latency_ms = int(
                    (self.interruption_detected_at - self.controller.started_at)
                    .total_seconds()
                    * 1000
                )

            # Check latency budget
            if self.interruption_latency_ms > self.max_latency_ms:
                logger.warning(
                    f"Interruption latency exceeded budget: "
                    f"{self.interruption_latency_ms}ms > {self.max_latency_ms}ms"
                )
            else:
                logger.info(
                    f"Playback interrupted (latency: {self.interruption_latency_ms}ms)"
                )

        return success

    async def cleanup(self):
        """Clean up playback resources after interruption."""
        logger.debug("Cleaning up playback resources")
        # In a real implementation, this would clean up audio devices,
        # buffers, etc. For now, just logging the intent.

    def get_interruption_stats(self) -> dict:
        """Get interruption statistics.

        Returns:
            Dictionary with interruption metrics
        """
        return {
            "interruption_latency_ms": self.interruption_latency_ms,
            "max_latency_budget_ms": self.max_latency_ms,
            "within_budget": self.interruption_latency_ms <= self.max_latency_ms,
            "controller_state": self.controller.state.value,
            "total_interruptions": self.controller.interruption_count,
        }
