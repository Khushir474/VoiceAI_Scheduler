"""Conversation state machine for voice interactions.

Implements a 12-state FSM for orchestrating the daily planning call:
1. GREETING - Initial greeting
2. PRESENTING_PLAN - Agent presents calendar/weather/recommendations
3. ASKING_FOR_INPUT - Agent asks for missing plans
4. USER_INPUT - User speaks response
5. LLM_PROCESSING - LLM interprets user input
6. TOOL_EXECUTION - Execute tools to update plan
7. RESPONSE_GENERATION - LLM generates next response
8. SPEAKING_RESPONSE - TTS playing agent response
9. CONFIRMING_PLAN - Final confirmation from user
10. SENDING_SUMMARY - Sending iMessage/SMS summary
11. CALL_END - Call ended successfully
12. ERROR - Error occurred

Transitions are governed by triggers and guard conditions.
All state changes are logged and persisted.
"""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class ConversationState(str, Enum):
    """12 states for the voice conversation FSM."""

    # Main happy path
    GREETING = "greeting"
    PRESENTING_PLAN = "presenting_plan"
    ASKING_FOR_INPUT = "asking_for_input"
    USER_INPUT = "user_input"
    LLM_PROCESSING = "llm_processing"
    TOOL_EXECUTION = "tool_execution"
    RESPONSE_GENERATION = "response_generation"
    SPEAKING_RESPONSE = "speaking_response"
    CONFIRMING_PLAN = "confirming_plan"
    SENDING_SUMMARY = "sending_summary"
    CALL_END = "call_end"

    # Error state
    ERROR = "error"


class StateTransitionTrigger(str, Enum):
    """Triggers that cause state transitions."""

    # General
    USER_READY = "user_ready"
    ERROR_OCCURRED = "error_occurred"
    TIMEOUT = "timeout"

    # Conversation flow
    AGENT_FINISHED_SPEAKING = "agent_finished_speaking"
    USER_RESPONDS = "user_responds"
    BARGE_IN = "barge_in"
    NO_SPEECH_DETECTED = "no_speech_detected"
    SILENCE_TIMEOUT_2_5S = "silence_timeout_2_5s"
    SILENCE_TIMEOUT_5S = "silence_timeout_5s"
    SILENCE_TIMEOUT_10S = "silence_timeout_10s"

    # LLM & Tool execution
    STT_SUCCESS = "stt_success"
    STT_LOW_CONFIDENCE = "stt_low_confidence"
    TOOLS_NEEDED = "tools_needed"
    NO_TOOLS_NEEDED = "no_tools_needed"
    TOOLS_COMPLETE = "tools_complete"
    RESPONSE_READY = "response_ready"

    # Speech detection
    SPEECH_ENDED_NATURALLY = "speech_ended_naturally"

    # User confirmation
    PLAN_CONFIRMED = "plan_confirmed"
    PLAN_NOT_CONFIRMED = "plan_not_confirmed"

    # Summary
    SUMMARY_SENT = "summary_sent"
    SUMMARY_FAILED = "summary_failed"

    # Error recovery
    ERROR_RECOVERY_RETRY = "error_recovery_retry"
    ERROR_UNRECOVERABLE = "error_unrecoverable"


# Valid state transitions with their allowed triggers
TRANSITION_RULES: dict[tuple[ConversationState, ConversationState], set[StateTransitionTrigger]] = {
    # GREETING transitions
    (ConversationState.GREETING, ConversationState.PRESENTING_PLAN): {
        StateTransitionTrigger.USER_READY
    },
    (ConversationState.GREETING, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # PRESENTING_PLAN transitions
    (ConversationState.PRESENTING_PLAN, ConversationState.ASKING_FOR_INPUT): {
        StateTransitionTrigger.AGENT_FINISHED_SPEAKING
    },
    (ConversationState.PRESENTING_PLAN, ConversationState.USER_INPUT): {
        StateTransitionTrigger.BARGE_IN
    },
    (ConversationState.PRESENTING_PLAN, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # ASKING_FOR_INPUT transitions
    (ConversationState.ASKING_FOR_INPUT, ConversationState.USER_INPUT): {
        StateTransitionTrigger.USER_RESPONDS,
        StateTransitionTrigger.BARGE_IN,
    },
    (ConversationState.ASKING_FOR_INPUT, ConversationState.CONFIRMING_PLAN): {
        StateTransitionTrigger.SILENCE_TIMEOUT_5S
    },
    (ConversationState.ASKING_FOR_INPUT, ConversationState.CALL_END): {
        StateTransitionTrigger.SILENCE_TIMEOUT_10S
    },
    (ConversationState.ASKING_FOR_INPUT, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # USER_INPUT transitions
    (ConversationState.USER_INPUT, ConversationState.LLM_PROCESSING): {
        StateTransitionTrigger.STT_SUCCESS
    },
    (ConversationState.USER_INPUT, ConversationState.ASKING_FOR_INPUT): {
        StateTransitionTrigger.STT_LOW_CONFIDENCE,
        StateTransitionTrigger.NO_SPEECH_DETECTED,
    },
    (ConversationState.USER_INPUT, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # LLM_PROCESSING transitions
    (ConversationState.LLM_PROCESSING, ConversationState.TOOL_EXECUTION): {
        StateTransitionTrigger.TOOLS_NEEDED
    },
    (ConversationState.LLM_PROCESSING, ConversationState.RESPONSE_GENERATION): {
        StateTransitionTrigger.NO_TOOLS_NEEDED
    },
    (ConversationState.LLM_PROCESSING, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED,
        StateTransitionTrigger.TIMEOUT,
    },

    # TOOL_EXECUTION transitions
    (ConversationState.TOOL_EXECUTION, ConversationState.RESPONSE_GENERATION): {
        StateTransitionTrigger.TOOLS_COMPLETE
    },
    (ConversationState.TOOL_EXECUTION, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # RESPONSE_GENERATION transitions
    (ConversationState.RESPONSE_GENERATION, ConversationState.SPEAKING_RESPONSE): {
        StateTransitionTrigger.RESPONSE_READY
    },
    (ConversationState.RESPONSE_GENERATION, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED,
        StateTransitionTrigger.TIMEOUT,
    },

    # SPEAKING_RESPONSE transitions
    (ConversationState.SPEAKING_RESPONSE, ConversationState.USER_INPUT): {
        StateTransitionTrigger.BARGE_IN
    },
    (ConversationState.SPEAKING_RESPONSE, ConversationState.CONFIRMING_PLAN): {
        StateTransitionTrigger.SPEECH_ENDED_NATURALLY,
        StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
    },
    (ConversationState.SPEAKING_RESPONSE, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # CONFIRMING_PLAN transitions
    (ConversationState.CONFIRMING_PLAN, ConversationState.SENDING_SUMMARY): {
        StateTransitionTrigger.PLAN_CONFIRMED
    },
    (ConversationState.CONFIRMING_PLAN, ConversationState.ASKING_FOR_INPUT): {
        StateTransitionTrigger.PLAN_NOT_CONFIRMED,
        StateTransitionTrigger.USER_RESPONDS,
    },
    (ConversationState.CONFIRMING_PLAN, ConversationState.CALL_END): {
        StateTransitionTrigger.SILENCE_TIMEOUT_10S
    },
    (ConversationState.CONFIRMING_PLAN, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # SENDING_SUMMARY transitions
    (ConversationState.SENDING_SUMMARY, ConversationState.CALL_END): {
        StateTransitionTrigger.SUMMARY_SENT
    },
    (ConversationState.SENDING_SUMMARY, ConversationState.ERROR): {
        StateTransitionTrigger.ERROR_OCCURRED
    },

    # ERROR transitions
    (ConversationState.ERROR, ConversationState.USER_INPUT): {
        StateTransitionTrigger.ERROR_RECOVERY_RETRY
    },
    (ConversationState.ERROR, ConversationState.CALL_END): {
        StateTransitionTrigger.ERROR_UNRECOVERABLE
    },

    # CALL_END is terminal (no outgoing transitions)
}


@dataclass
class StateTransitionLog:
    """Log entry for a state transition."""

    run_id: str
    user_id: str
    from_state: ConversationState
    to_state: ConversationState
    trigger: StateTransitionTrigger
    timestamp: datetime = field(default_factory=datetime.utcnow)
    latency_ms: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ConversationSession:
    """Session state for a single voice call."""

    run_id: str
    user_id: str
    current_state: ConversationState = ConversationState.GREETING
    previous_state: ConversationState | None = None
    state_changed_at: datetime = field(default_factory=datetime.utcnow)

    # Error tracking
    error_count: int = 0
    last_error: str | None = None
    error_recovery_attempts: int = 0

    # User interaction tracking
    barge_in_count: int = 0
    silence_timeout_count: int = 0
    stt_attempts: int = 0
    stt_low_confidence_count: int = 0

    # Call metadata
    transition_log: list[StateTransitionLog] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)

    def __repr__(self) -> str:
        return f"ConversationSession(run_id={self.run_id}, state={self.current_state.value})"


class ConversationStateMachine:
    """12-state FSM for voice conversation orchestration."""

    def __init__(self, session: ConversationSession):
        self.session = session
        self.logger = logger

    def can_transition(
        self,
        from_state: ConversationState,
        to_state: ConversationState,
        trigger: StateTransitionTrigger,
    ) -> bool:
        """Check if a state transition is valid."""
        valid_transitions = TRANSITION_RULES.get((from_state, to_state), set())
        is_valid = trigger in valid_transitions


        if not is_valid:
            trigger_str = getattr(trigger, 'value', str(trigger))
            self.logger.warning(
                f"Invalid transition: {from_state.value} -> {to_state.value} "
                f"with trigger {trigger_str}"
            )
        return is_valid

    def get_valid_transitions(
        self, from_state: ConversationState | None = None
    ) -> dict[ConversationState, set[StateTransitionTrigger]]:
        """Get all valid transitions from a state."""
        current = from_state or self.session.current_state
        valid = {}
        for (src, dst), triggers in TRANSITION_RULES.items():
            if src == current:
                valid[dst] = triggers
        return valid

    async def transition(
        self,
        to_state: ConversationState,
        trigger: StateTransitionTrigger,
        metadata: dict | None = None,
    ) -> bool:
        """Execute a state transition.

        Args:
            to_state: Target state
            trigger: What triggered the transition
            metadata: Optional metadata for logging

        Returns:
            True if transition succeeded, False otherwise
        """
        from_state = self.session.current_state

        if not self.can_transition(from_state, to_state, trigger):
            return False

        # Calculate latency since last state change
        latency_ms = int((datetime.utcnow() - self.session.state_changed_at).total_seconds() * 1000)

        # Create transition log entry
        log_entry = StateTransitionLog(
            run_id=self.session.run_id,
            user_id=self.session.user_id,
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )

        # Update session state
        self.session.previous_state = from_state
        self.session.current_state = to_state
        self.session.state_changed_at = datetime.utcnow()
        self.session.transition_log.append(log_entry)

        # Track specific transitions
        if trigger == StateTransitionTrigger.BARGE_IN:
            self.session.barge_in_count += 1
        elif trigger in {
            StateTransitionTrigger.SILENCE_TIMEOUT_2_5S,
            StateTransitionTrigger.SILENCE_TIMEOUT_5S,
            StateTransitionTrigger.SILENCE_TIMEOUT_10S,
        }:
            self.session.silence_timeout_count += 1
        elif trigger == StateTransitionTrigger.STT_SUCCESS:
            self.session.stt_attempts += 1
        elif trigger == StateTransitionTrigger.STT_LOW_CONFIDENCE:
            self.session.stt_low_confidence_count += 1

        # Log transition
        self.logger.info(
            f"State transition: {from_state.value} -> {to_state.value} "
            f"(trigger: {trigger.value}, latency: {latency_ms}ms)"
        )

        return True

    async def handle_error(
        self,
        error: Exception | str,
        recoverable: bool = True,
    ) -> bool:
        """Handle an error in the conversation.

        Args:
            error: Error object or message
            recoverable: Whether this error can be recovered from

        Returns:
            True if recovery was attempted, False if unrecoverable
        """
        self.session.error_count += 1
        self.session.last_error = str(error)

        self.logger.error(f"Error in {self.session.current_state.value}: {error}")

        # Transition to error state
        await self.transition(
            ConversationState.ERROR,
            StateTransitionTrigger.ERROR_OCCURRED,
            metadata={"error": str(error), "recoverable": recoverable},
        )

        if recoverable and self.session.error_recovery_attempts < 3:
            self.session.error_recovery_attempts += 1
            self.logger.info(f"Attempting error recovery (attempt {self.session.error_recovery_attempts})")
            return await self.transition(
                ConversationState.USER_INPUT,
                StateTransitionTrigger.ERROR_RECOVERY_RETRY,
                metadata={"attempt": self.session.error_recovery_attempts},
            )
        else:
            self.logger.error("Error unrecoverable, ending call")
            return await self.transition(
                ConversationState.CALL_END,
                StateTransitionTrigger.ERROR_UNRECOVERABLE,
            )

    def get_state_summary(self) -> dict:
        """Get a summary of the current session state."""
        return {
            "run_id": self.session.run_id,
            "user_id": self.session.user_id,
            "current_state": self.session.current_state.value,
            "previous_state": self.session.previous_state.value if self.session.previous_state else None,
            "error_count": self.session.error_count,
            "barge_in_count": self.session.barge_in_count,
            "silence_timeout_count": self.session.silence_timeout_count,
            "stt_attempts": self.session.stt_attempts,
            "stt_low_confidence_count": self.session.stt_low_confidence_count,
            "transition_log": [
                {
                    "from_state": log.from_state.value,
                    "to_state": log.to_state.value,
                    "trigger": log.trigger.value,
                    "latency_ms": log.latency_ms,
                    "timestamp": log.timestamp.isoformat(),
                }
                for log in self.session.transition_log
            ],
        }
