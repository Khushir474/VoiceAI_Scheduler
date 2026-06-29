"""Speech endpointing and silence timeout handling.

Detects when the user has finished speaking and implements
three-stage silence escalation:
- 2.5s: Ask confirmation
- 5s: Assume "no", proceed
- 10s: Hang up, send SMS fallback
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

from app.agents.conversation_state_machine import (
    ConversationStateMachine,
    ConversationState,
    StateTransitionTrigger,
)
from app.services.vad_manager import VADConfig, VADManager

logger = logging.getLogger(__name__)


class SilenceTimeoutStage:
    """Tracks progression through silence timeout stages."""

    STAGE_1_MS = 2500  # 2.5 seconds - ask confirmation
    STAGE_2_MS = 5000  # 5 seconds - assume no
    STAGE_3_MS = 10000  # 10 seconds - hang up

    def __init__(self):
        self.silence_started_at: Optional[datetime] = None
        self.current_stage = 0  # 0=no silence, 1=2.5s, 2=5s, 3=10s
        self.confirmation_asked = False
        self.decision_made = False

    def start_silence(self):
        """Mark the start of silence."""
        self.silence_started_at = datetime.utcnow()
        self.current_stage = 0
        self.confirmation_asked = False
        self.decision_made = False

    def reset(self):
        """Reset silence tracking."""
        self.silence_started_at = None
        self.current_stage = 0
        self.confirmation_asked = False
        self.decision_made = False

    def elapsed_ms(self) -> int:
        """Milliseconds of silence elapsed."""
        if self.silence_started_at is None:
            return 0
        return int((datetime.utcnow() - self.silence_started_at).total_seconds() * 1000)

    def check_stage(self) -> Optional[int]:
        """Check if we've advanced to a new silence stage.

        Returns:
            New stage number (1, 2, or 3) if advanced, None otherwise
        """
        elapsed = self.elapsed_ms()

        new_stage = 0
        if elapsed >= self.STAGE_3_MS:
            new_stage = 3
        elif elapsed >= self.STAGE_2_MS:
            new_stage = 2
        elif elapsed >= self.STAGE_1_MS:
            new_stage = 1

        if new_stage > self.current_stage:
            self.current_stage = new_stage
            return new_stage

        return None


class EndpointingHandler:
    """Detects speech endpoints and manages silence timeouts.

    Responsibilities:
    - Detect when user stops speaking (endpointing)
    - Implement three-stage silence timeout
    - Handle context-aware endpointing (different for different states)
    - Trigger confirmation/decision/hangup callbacks
    """

    def __init__(
        self,
        fsm: ConversationStateMachine,
        vad_manager: VADManager,
        run_id: str = "",
    ):
        """Initialize endpointing handler.

        Args:
            fsm: Conversation state machine
            vad_manager: VAD configuration manager
            run_id: Call identifier
        """
        self.fsm = fsm
        self.vad_manager = vad_manager
        self.run_id = run_id

        # Silence tracking
        self.silence_stage = SilenceTimeoutStage()
        self.current_vad_state = "idle"
        self.last_speech_end: Optional[datetime] = None

        # Callbacks
        self.on_speech_ended: Optional[Callable] = None
        self.on_confirmation_needed: Optional[Callable] = None
        self.on_silence_timeout: Optional[Callable] = None
        self.on_hangup: Optional[Callable] = None

        # Metrics
        self.endpointing_count = 0
        self.stage_1_timeout_count = 0
        self.stage_2_timeout_count = 0
        self.stage_3_timeout_count = 0

    def set_callbacks(
        self,
        on_speech_ended: Optional[Callable] = None,
        on_confirmation_needed: Optional[Callable] = None,
        on_silence_timeout: Optional[Callable] = None,
        on_hangup: Optional[Callable] = None,
    ):
        """Register callbacks for different stages.

        Args:
            on_speech_ended: Called when speech ends
            on_confirmation_needed: Called at 2.5s silence
            on_silence_timeout: Called at 5s silence
            on_hangup: Called at 10s silence
        """
        self.on_speech_ended = on_speech_ended
        self.on_confirmation_needed = on_confirmation_needed
        self.on_silence_timeout = on_silence_timeout
        self.on_hangup = on_hangup

    async def process_vad_event(self, vad_state: str, confidence: float) -> Optional[int]:
        """Process a VAD event and check for state changes.

        Args:
            vad_state: "speaking" or "idle"
            confidence: Confidence 0.0-1.0

        Returns:
            New silence stage (1, 2, 3) if reached, None otherwise
        """
        # Detect speech onset
        if vad_state == "speaking" and self.current_vad_state == "idle":
            logger.debug("Speech onset detected")
            self.silence_stage.reset()

        # Detect speech offset (endpointing)
        elif vad_state == "idle" and self.current_vad_state == "speaking":
            logger.debug("Speech offset detected (endpointing)")
            self.endpointing_count += 1
            self.last_speech_end = datetime.utcnow()
            self.silence_stage.start_silence()

            # Trigger callback
            if self.on_speech_ended:
                try:
                    await self.on_speech_ended()
                except Exception as e:
                    logger.error(f"Error in on_speech_ended callback: {e}")

        # Update current state
        self.current_vad_state = vad_state

        return None

    async def check_silence_timeouts(self) -> Optional[int]:
        """Check for silence timeout progression.

        Returns:
            New stage (1, 2, 3) if reached, None otherwise
        """
        # Only check if we're in USER_INPUT state (listening for user)
        if self.fsm.session.current_state not in [
            ConversationState.ASKING_FOR_INPUT,
            ConversationState.CONFIRMING_PLAN,
        ]:
            return None

        new_stage = self.silence_stage.check_stage()

        if new_stage is None:
            return None

        logger.info(f"Silence stage {new_stage} reached after {self.silence_stage.elapsed_ms()}ms")

        if new_stage == 1:
            # Stage 1 (2.5s): Ask confirmation
            return await self._handle_stage_1_confirmation()

        elif new_stage == 2:
            # Stage 2 (5s): Assume "no"
            return await self._handle_stage_2_decision()

        elif new_stage == 3:
            # Stage 3 (10s): Hang up
            return await self._handle_stage_3_hangup()

        return None

    async def _handle_stage_1_confirmation(self) -> int:
        """Handle 2.5s silence - ask confirmation.

        Returns:
            Stage number (1)
        """
        self.stage_1_timeout_count += 1

        logger.info(
            f"Stage 1 timeout (2.5s): asking confirmation "
            f"(count={self.stage_1_timeout_count})"
        )

        if self.on_confirmation_needed:
            try:
                await self.on_confirmation_needed()
            except Exception as e:
                logger.error(f"Error in on_confirmation_needed callback: {e}")

        return 1

    async def _handle_stage_2_decision(self) -> int:
        """Handle 5s silence - make decision (assume no).

        Returns:
            Stage number (2)
        """
        self.stage_2_timeout_count += 1

        logger.info(
            f"Stage 2 timeout (5s): assuming user said no "
            f"(count={self.stage_2_timeout_count})"
        )

        # Transition FSM to CONFIRMING_PLAN (skip USER_INPUT)
        try:
            await self.fsm.transition(
                ConversationState.CONFIRMING_PLAN,
                StateTransitionTrigger.SILENCE_TIMEOUT_5S,
                metadata={"stage": 2},
            )
        except Exception as e:
            logger.error(f"Error transitioning FSM: {e}")

        if self.on_silence_timeout:
            try:
                await self.on_silence_timeout()
            except Exception as e:
                logger.error(f"Error in on_silence_timeout callback: {e}")

        return 2

    async def _handle_stage_3_hangup(self) -> int:
        """Handle 10s silence - hang up.

        Returns:
            Stage number (3)
        """
        self.stage_3_timeout_count += 1

        logger.warning(
            f"Stage 3 timeout (10s): hanging up "
            f"(count={self.stage_3_timeout_count})"
        )

        # Transition FSM to CALL_END
        try:
            await self.fsm.transition(
                ConversationState.CALL_END,
                StateTransitionTrigger.SILENCE_TIMEOUT_10S,
                metadata={"stage": 3},
            )
        except Exception as e:
            logger.error(f"Error transitioning FSM: {e}")

        if self.on_hangup:
            try:
                await self.on_hangup()
            except Exception as e:
                logger.error(f"Error in on_hangup callback: {e}")

        return 3

    def reset_silence_timer(self):
        """Reset silence timer (called when user responds)."""
        self.silence_stage.reset()
        logger.debug("Silence timer reset")

    def get_metrics(self) -> dict:
        """Get endpointing metrics.

        Returns:
            Dictionary with endpointing statistics
        """
        return {
            "endpointing_count": self.endpointing_count,
            "stage_1_timeouts": self.stage_1_timeout_count,
            "stage_2_timeouts": self.stage_2_timeout_count,
            "stage_3_timeouts": self.stage_3_timeout_count,
            "current_silence_elapsed_ms": self.silence_stage.elapsed_ms(),
            "current_vad_state": self.current_vad_state,
            "last_speech_end": (
                self.last_speech_end.isoformat() if self.last_speech_end else None
            ),
        }


class ContextAwareEndpointing:
    """Context-aware endpointing that adjusts based on FSM state.

    Different conversation states require different endpointing behavior:
    - ASKING_FOR_INPUT: Aggressive (detect quick responses)
    - CONFIRMING_PLAN: Conservative (wait for user confirmation)
    - PRESENTING_PLAN: Very conservative (don't interrupt)
    """

    def __init__(self, endpointing_handler: EndpointingHandler):
        """Initialize context-aware wrapper.

        Args:
            endpointing_handler: EndpointingHandler to wrap
        """
        self.handler = endpointing_handler

    def get_effective_timeouts(self) -> dict:
        """Get timeout values adjusted for current FSM state.

        Returns:
            Dictionary with adjusted timeout values
        """
        config = self.handler.vad_manager.get_config(self.handler.fsm.session.user_id)
        current_state = self.handler.fsm.session.current_state

        # Base timeouts
        stage_1_ms = config.silence_timeout_confirmation_ms
        stage_2_ms = config.silence_timeout_decision_ms
        stage_3_ms = config.silence_timeout_hangup_ms

        # Adjust based on state
        if current_state == ConversationState.PRESENTING_PLAN:
            # Don't timeout during presentation
            return {
                "stage_1_ms": float("inf"),
                "stage_2_ms": float("inf"),
                "stage_3_ms": float("inf"),
            }

        elif current_state == ConversationState.CONFIRMING_PLAN:
            # Conservative: longer timeouts
            return {
                "stage_1_ms": stage_1_ms * 1.5,
                "stage_2_ms": stage_2_ms * 1.5,
                "stage_3_ms": stage_3_ms,
            }

        else:  # ASKING_FOR_INPUT, etc.
            # Aggressive: normal/shorter timeouts
            return {
                "stage_1_ms": stage_1_ms,
                "stage_2_ms": stage_2_ms,
                "stage_3_ms": stage_3_ms,
            }

    def should_apply_endpointing(self) -> bool:
        """Check if endpointing should be applied in current state.

        Returns:
            True if endpointing should be active
        """
        current_state = self.handler.fsm.session.current_state

        # Don't apply during presentation or already ended
        return current_state not in [
            ConversationState.PRESENTING_PLAN,
            ConversationState.SENDING_SUMMARY,
            ConversationState.CALL_END,
            ConversationState.ERROR,
        ]
