"""Barge-in detection and handling for voice interactions.

Detects when the user speaks during agent playback and triggers
immediate TTS interruption and state transition.
"""

import logging
from typing import Callable, Optional
from datetime import datetime

from app.agents.conversation_state_machine import (
    ConversationStateMachine,
    ConversationState,
    StateTransitionTrigger,
)
from app.services.audio_buffer import VADEventQueue

logger = logging.getLogger(__name__)


class BargeInHandler:
    """Detects and handles user barge-in (interrupt) during agent speech.

    Responsibilities:
    - Listen for VAD (Voice Activity Detection) signals
    - Detect user speaking during SPEAKING_RESPONSE state
    - Trigger immediate TTS stop (< 100ms)
    - Transition FSM to USER_INPUT state
    - Track barge-in metrics

    Barge-in Flow:
    1. Agent in SPEAKING_RESPONSE state (playing TTS)
    2. User starts speaking → VAD signal "speaking"
    3. BargeInHandler detects this
    4. Calls on_barge_in callback (TTS stop)
    5. FSM transitions to USER_INPUT
    """

    def __init__(
        self,
        fsm: ConversationStateMachine,
        vad_queue: VADEventQueue,
        run_id: str = "",
    ):
        """Initialize barge-in handler.

        Args:
            fsm: Conversation state machine for transitions
            vad_queue: VAD event queue from Vapi WebSocket
            run_id: Call identifier for logging
        """
        self.fsm = fsm
        self.vad_queue = vad_queue
        self.run_id = run_id

        # Callback for TTS interruption
        self.on_barge_in: Optional[Callable] = None

        # Metrics
        self.barge_in_count = 0
        self.last_vad_state = "idle"
        self.last_vad_confidence = 0.0
        self.last_barge_in_timestamp: Optional[datetime] = None

    def set_barge_in_callback(self, callback: Callable):
        """Register callback to stop TTS on barge-in.

        Args:
            callback: Async callable() that stops playback
        """
        self.on_barge_in = callback
        logger.debug(f"Registered barge-in callback (run_id={self.run_id})")

    async def process_vad_events(self) -> bool:
        """Process pending VAD events and detect barge-in.

        Should be called regularly from the main event loop.

        Returns:
            True if barge-in was detected and handled
        """
        barge_in_detected = False

        # Process all pending VAD events
        while not self.vad_queue.is_empty():
            event = self.vad_queue.get()
            if event is None:
                continue

            self.last_vad_state = event.vad_state
            self.last_vad_confidence = event.confidence

            # Check for barge-in: user speaks while agent is speaking
            if self._should_trigger_barge_in(event):
                barge_in_detected = True
                await self._handle_barge_in(event)

        return barge_in_detected

    def _should_trigger_barge_in(self, vad_event: VADEventQueue.VADEvent) -> bool:
        """Determine if this VAD event should trigger barge-in.

        Args:
            vad_event: VAD event from Vapi

        Returns:
            True if barge-in should be triggered
        """
        # Only detect barge-in during SPEAKING_RESPONSE state
        if self.fsm.session.current_state != ConversationState.SPEAKING_RESPONSE:
            return False

        # VAD signal must indicate speaking
        if vad_event.vad_state != "speaking":
            return False

        # Confidence must exceed threshold (0.5 = 50% confidence)
        vad_confidence_threshold = 0.5
        if vad_event.confidence < vad_confidence_threshold:
            logger.debug(
                f"VAD confidence too low: {vad_event.confidence:.2f} "
                f"< {vad_confidence_threshold}"
            )
            return False

        return True

    async def _handle_barge_in(self, vad_event: VADEventQueue.VADEvent):
        """Handle a detected barge-in event.

        Args:
            vad_event: The VAD event that triggered barge-in
        """
        self.barge_in_count += 1
        self.last_barge_in_timestamp = datetime.utcnow()

        logger.info(
            f"Barge-in detected: count={self.barge_in_count}, "
            f"vad_confidence={vad_event.confidence:.2f}"
        )

        # 1. Stop TTS playback immediately (< 100ms)
        if self.on_barge_in:
            try:
                await self.on_barge_in()
                logger.debug("TTS playback stopped")
            except Exception as e:
                logger.error(f"Error stopping TTS on barge-in: {e}")

        # 2. Transition FSM to USER_INPUT state
        try:
            success = await self.fsm.transition(
                ConversationState.USER_INPUT,
                StateTransitionTrigger.BARGE_IN,
                metadata={
                    "vad_confidence": vad_event.confidence,
                    "barge_in_count": self.barge_in_count,
                },
            )

            if success:
                logger.info(
                    f"FSM transitioned to USER_INPUT on barge-in "
                    f"(count={self.barge_in_count})"
                )
            else:
                logger.warning(
                    f"Failed to transition FSM to USER_INPUT on barge-in "
                    f"(current_state={self.fsm.session.current_state.value})"
                )
        except Exception as e:
            logger.error(f"Error transitioning FSM on barge-in: {e}")

    async def check_for_barge_in(self) -> bool:
        """Non-blocking check for barge-in.

        This is a convenience wrapper around process_vad_events()
        for use in event loops.

        Returns:
            True if barge-in was detected
        """
        return await self.process_vad_events()

    def get_metrics(self) -> dict:
        """Get barge-in metrics for monitoring.

        Returns:
            Dictionary with barge-in statistics
        """
        time_since_last_barge_in = None
        if self.last_barge_in_timestamp:
            time_since_last_barge_in = int(
                (datetime.utcnow() - self.last_barge_in_timestamp).total_seconds()
            )

        return {
            "barge_in_count": self.barge_in_count,
            "last_vad_state": self.last_vad_state,
            "last_vad_confidence": self.last_vad_confidence,
            "last_barge_in_timestamp": (
                self.last_barge_in_timestamp.isoformat()
                if self.last_barge_in_timestamp
                else None
            ),
            "seconds_since_last_barge_in": time_since_last_barge_in,
        }


class BargeInDetector:
    """Monitors VAD stream for barge-in patterns.

    Advanced detection that handles:
    - False positives (noise mistaken for speech)
    - Multiple rapid interrupts
    - Barge-in during silence between agent sentences
    """

    def __init__(
        self,
        vad_queue: VADEventQueue,
        confidence_threshold: float = 0.5,
        min_speech_duration_ms: int = 300,  # Min 300ms of speech to count
        run_id: str = "",
    ):
        """Initialize barge-in detector.

        Args:
            vad_queue: VAD event queue
            confidence_threshold: Minimum VAD confidence (0.0-1.0)
            min_speech_duration_ms: Minimum speech duration to count as barge-in
            run_id: Call identifier
        """
        self.vad_queue = vad_queue
        self.confidence_threshold = confidence_threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.run_id = run_id

        # Speech detection tracking
        self.speech_detected_at: Optional[datetime] = None
        self.speech_duration_ms = 0
        self.false_positive_count = 0
        self.speech_streak = 0  # Consecutive "speaking" signals

    async def detect_speech_onset(self) -> Optional[dict]:
        """Detect when user starts speaking.

        Returns:
            Dict with speech info if detected, None otherwise
        """
        while not self.vad_queue.is_empty():
            event = self.vad_queue.get()
            if event is None:
                continue

            if event.vad_state == "speaking":
                # Speech detected
                if self.speech_detected_at is None:
                    # Speech onset
                    self.speech_detected_at = event.timestamp
                    self.speech_streak = 1
                    logger.debug(
                        f"Speech onset detected (confidence={event.confidence:.2f})"
                    )
                else:
                    self.speech_streak += 1

                # Check if confidence is below threshold
                if event.confidence < self.confidence_threshold:
                    self.false_positive_count += 1
                    logger.debug(
                        f"Low confidence speech: {event.confidence:.2f}, "
                        f"possible false positive"
                    )

            else:
                # VAD = idle
                if self.speech_detected_at is not None:
                    # Speech ended
                    self.speech_duration_ms = int(
                        (event.timestamp - self.speech_detected_at).total_seconds() * 1000
                    )

                    # Check if met minimum duration threshold
                    if self.speech_duration_ms >= self.min_speech_duration_ms:
                        result = {
                            "detected_at": self.speech_detected_at,
                            "duration_ms": self.speech_duration_ms,
                            "confidence": event.confidence,
                            "speech_streak": self.speech_streak,
                        }
                        logger.info(
                            f"Speech detected: duration={self.speech_duration_ms}ms, "
                            f"streak={self.speech_streak}"
                        )

                        # Reset for next detection
                        self.speech_detected_at = None
                        self.speech_streak = 0

                        return result
                    else:
                        logger.debug(
                            f"Speech too short: {self.speech_duration_ms}ms "
                            f"< {self.min_speech_duration_ms}ms (false positive)"
                        )
                        self.false_positive_count += 1
                        self.speech_detected_at = None
                        self.speech_streak = 0

        return None

    def get_detector_stats(self) -> dict:
        """Get detection statistics.

        Returns:
            Dictionary with detector metrics
        """
        return {
            "confidence_threshold": self.confidence_threshold,
            "min_speech_duration_ms": self.min_speech_duration_ms,
            "false_positive_count": self.false_positive_count,
            "current_speech_streak": self.speech_streak,
            "is_currently_detecting_speech": self.speech_detected_at is not None,
        }
