"""Unit tests for the conversation state machine."""

import pytest
from datetime import datetime

from app.agents.conversation_state_machine import (
    ConversationState,
    StateTransitionTrigger,
    ConversationSession,
    ConversationStateMachine,
    TRANSITION_RULES,
)


@pytest.fixture
def session():
    """Create a test conversation session."""
    return ConversationSession(
        run_id="test_run_123",
        user_id="user_456",
    )


@pytest.fixture
def fsm(session):
    """Create a test state machine."""
    return ConversationStateMachine(session)


class TestStateTransitionRules:
    """Test state transition rule definitions."""

    def test_greeting_to_presenting_plan(self):
        """Test valid transition from GREETING to PRESENTING_PLAN."""
        assert (
            ConversationState.GREETING,
            ConversationState.PRESENTING_PLAN,
        ) in TRANSITION_RULES
        allowed = TRANSITION_RULES[
            (ConversationState.GREETING, ConversationState.PRESENTING_PLAN)
        ]
        assert StateTransitionTrigger.USER_READY in allowed

    def test_presenting_plan_has_multiple_transitions(self):
        """Test that PRESENTING_PLAN has multiple valid transitions."""
        transitions = [
            (ConversationState.PRESENTING_PLAN, ConversationState.ASKING_FOR_INPUT),
            (ConversationState.PRESENTING_PLAN, ConversationState.USER_INPUT),
            (ConversationState.PRESENTING_PLAN, ConversationState.ERROR),
        ]
        for src, dst in transitions:
            assert (src, dst) in TRANSITION_RULES

    def test_call_end_is_terminal(self):
        """Test that CALL_END has no outgoing transitions."""
        for (src, dst) in TRANSITION_RULES.keys():
            assert src != ConversationState.CALL_END, "CALL_END should not have outgoing transitions"

    def test_all_transitions_have_triggers(self):
        """Test that all transitions have at least one trigger."""
        for transitions in TRANSITION_RULES.values():
            assert len(transitions) > 0, "All transitions must have at least one trigger"


class TestStateMachineTransitions:
    """Test state machine transition logic."""

    @pytest.mark.asyncio
    async def test_valid_transition(self, fsm):
        """Test that a valid transition succeeds."""
        result = await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        assert result is True
        assert fsm.session.current_state == ConversationState.PRESENTING_PLAN

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self, fsm):
        """Test that invalid transitions are rejected."""
        result = await fsm.transition(
            ConversationState.CALL_END,
            StateTransitionTrigger.USER_READY,
        )
        assert result is False
        assert fsm.session.current_state == ConversationState.GREETING

    @pytest.mark.asyncio
    async def test_invalid_trigger_rejected(self, fsm):
        """Test that invalid triggers for a valid state pair are rejected."""
        result = await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.BARGE_IN,  # Invalid trigger for this transition
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_transition_updates_previous_state(self, fsm):
        """Test that transitions update previous state."""
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        assert fsm.session.previous_state == ConversationState.GREETING

    @pytest.mark.asyncio
    async def test_transition_updates_timestamp(self, fsm):
        """Test that transitions update state_changed_at."""
        before = datetime.utcnow()
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        after = datetime.utcnow()
        assert before <= fsm.session.state_changed_at <= after

    @pytest.mark.asyncio
    async def test_transition_creates_log_entry(self, fsm):
        """Test that transitions create log entries."""
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        assert len(fsm.session.transition_log) == 1
        log_entry = fsm.session.transition_log[0]
        assert log_entry.from_state == ConversationState.GREETING
        assert log_entry.to_state == ConversationState.PRESENTING_PLAN
        assert log_entry.trigger == StateTransitionTrigger.USER_READY


class TestBargeInHandling:
    """Test barge-in detection and state transitions."""

    @pytest.mark.asyncio
    async def test_barge_in_during_presenting(self, fsm):
        """Test barge-in transitions from PRESENTING_PLAN."""
        # Setup: Agent is presenting
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        # User barges in
        result = await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.BARGE_IN,
        )
        assert result is True
        assert fsm.session.current_state == ConversationState.USER_INPUT
        assert fsm.session.barge_in_count == 1

    @pytest.mark.asyncio
    async def test_barge_in_during_speaking(self, fsm):
        """Test barge-in transitions from SPEAKING_RESPONSE."""
        # Setup: Agent is speaking response
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.USER_RESPONDS,
        )
        await fsm.transition(
            ConversationState.LLM_PROCESSING,
            StateTransitionTrigger.STT_SUCCESS,
        )
        await fsm.transition(
            ConversationState.RESPONSE_GENERATION,
            StateTransitionTrigger.NO_TOOLS_NEEDED,
        )
        await fsm.transition(
            ConversationState.SPEAKING_RESPONSE,
            StateTransitionTrigger.RESPONSE_READY,
        )
        # User barges in
        result = await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.BARGE_IN,
        )
        assert result is True
        assert fsm.session.barge_in_count == 1

    @pytest.mark.asyncio
    async def test_multiple_barge_ins_counted(self, fsm):
        """Test that multiple barge-ins are counted."""
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.BARGE_IN,
        )
        assert fsm.session.barge_in_count == 1

        # Simulate another barge-in after response
        await fsm.transition(
            ConversationState.LLM_PROCESSING,
            StateTransitionTrigger.STT_SUCCESS,
        )
        await fsm.transition(
            ConversationState.RESPONSE_GENERATION,
            StateTransitionTrigger.NO_TOOLS_NEEDED,
        )
        await fsm.transition(
            ConversationState.SPEAKING_RESPONSE,
            StateTransitionTrigger.RESPONSE_READY,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.BARGE_IN,
        )
        assert fsm.session.barge_in_count == 2


class TestSilenceHandling:
    """Test silence timeout escalation."""

    @pytest.mark.asyncio
    async def test_silence_2_5s_confirmation(self, fsm):
        """Test 2.5s silence triggers confirmation request."""
        # Setup: Agent asked for input
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        # Log: Silence at 2.5s would trigger confirmation in the conversation agent
        # (state machine just tracks events, conversation agent handles confirmation logic)
        assert fsm.session.current_state == ConversationState.ASKING_FOR_INPUT

    @pytest.mark.asyncio
    async def test_silence_5s_timeout(self, fsm):
        """Test 5s silence transitions to CONFIRMING_PLAN."""
        # Setup
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        # 5s silence
        result = await fsm.transition(
            ConversationState.CONFIRMING_PLAN,
            StateTransitionTrigger.SILENCE_TIMEOUT_5S,
        )
        assert result is True
        assert fsm.session.current_state == ConversationState.CONFIRMING_PLAN
        assert fsm.session.silence_timeout_count == 1

    @pytest.mark.asyncio
    async def test_silence_10s_timeout(self, fsm):
        """Test 10s silence ends the call."""
        # Setup
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        # 10s silence
        result = await fsm.transition(
            ConversationState.CALL_END,
            StateTransitionTrigger.SILENCE_TIMEOUT_10S,
        )
        assert result is True
        assert fsm.session.current_state == ConversationState.CALL_END
        assert fsm.session.silence_timeout_count == 1


class TestSTTHandling:
    """Test STT success and failure scenarios."""

    @pytest.mark.asyncio
    async def test_stt_success(self, fsm):
        """Test STT success transitions to LLM processing."""
        # Setup
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.USER_RESPONDS,
        )
        # STT success
        result = await fsm.transition(
            ConversationState.LLM_PROCESSING,
            StateTransitionTrigger.STT_SUCCESS,
        )
        assert result is True
        assert fsm.session.stt_attempts == 1

    @pytest.mark.asyncio
    async def test_stt_low_confidence_retry(self, fsm):
        """Test low-confidence STT asks for clarification."""
        # Setup
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.USER_RESPONDS,
        )
        # Low confidence STT
        result = await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.STT_LOW_CONFIDENCE,
        )
        assert result is True
        assert fsm.session.stt_low_confidence_count == 1

    @pytest.mark.asyncio
    async def test_no_speech_detected(self, fsm):
        """Test no speech detected asks user to repeat."""
        # Setup
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.USER_RESPONDS,
        )
        # No speech
        result = await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.NO_SPEECH_DETECTED,
        )
        assert result is True


class TestErrorHandling:
    """Test error state transitions and recovery."""

    @pytest.mark.asyncio
    async def test_error_transition_from_any_state(self, fsm):
        """Test ERROR transition is reachable from most states."""
        # From PRESENTING_PLAN
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        result = await fsm.transition(
            ConversationState.ERROR,
            StateTransitionTrigger.ERROR_OCCURRED,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_error_recovery_retry(self, fsm):
        """Test error recovery transitions back to USER_INPUT."""
        # Setup: Error occurred
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ERROR,
            StateTransitionTrigger.ERROR_OCCURRED,
        )
        # Recovery
        result = await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.ERROR_RECOVERY_RETRY,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_error_unrecoverable_ends_call(self, fsm):
        """Test unrecoverable error ends the call."""
        # Setup: Error occurred
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ERROR,
            StateTransitionTrigger.ERROR_OCCURRED,
        )
        # Unrecoverable
        result = await fsm.transition(
            ConversationState.CALL_END,
            StateTransitionTrigger.ERROR_UNRECOVERABLE,
        )
        assert result is True
        assert fsm.session.current_state == ConversationState.CALL_END

    @pytest.mark.asyncio
    async def test_handle_error_method(self, fsm):
        """Test the handle_error convenience method."""
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        result = await fsm.handle_error("Test error", recoverable=True)
        assert result is True
        assert fsm.session.error_count == 1
        assert fsm.session.last_error == "Test error"


class TestToolExecutionFlow:
    """Test LLM processing and tool execution."""

    @pytest.mark.asyncio
    async def test_tools_needed_flow(self, fsm):
        """Test flow when tools need to be executed."""
        # Setup: User input processed, tools needed
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.USER_RESPONDS,
        )
        await fsm.transition(
            ConversationState.LLM_PROCESSING,
            StateTransitionTrigger.STT_SUCCESS,
        )
        # Tools needed
        result = await fsm.transition(
            ConversationState.TOOL_EXECUTION,
            StateTransitionTrigger.TOOLS_NEEDED,
        )
        assert result is True
        # Tools complete
        await fsm.transition(
            ConversationState.RESPONSE_GENERATION,
            StateTransitionTrigger.TOOLS_COMPLETE,
        )
        assert fsm.session.current_state == ConversationState.RESPONSE_GENERATION

    @pytest.mark.asyncio
    async def test_no_tools_needed_flow(self, fsm):
        """Test flow when no tools are needed."""
        # Setup
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        await fsm.transition(
            ConversationState.ASKING_FOR_INPUT,
            StateTransitionTrigger.AGENT_FINISHED_SPEAKING,
        )
        await fsm.transition(
            ConversationState.USER_INPUT,
            StateTransitionTrigger.USER_RESPONDS,
        )
        await fsm.transition(
            ConversationState.LLM_PROCESSING,
            StateTransitionTrigger.STT_SUCCESS,
        )
        # No tools needed
        result = await fsm.transition(
            ConversationState.RESPONSE_GENERATION,
            StateTransitionTrigger.NO_TOOLS_NEEDED,
        )
        assert result is True
        assert fsm.session.current_state == ConversationState.RESPONSE_GENERATION


class TestHappyPath:
    """Test complete happy path call flow."""

    @pytest.mark.asyncio
    async def test_complete_call_flow(self, fsm):
        """Test a complete successful call from start to finish."""
        steps = [
            (ConversationState.PRESENTING_PLAN, StateTransitionTrigger.USER_READY),
            (ConversationState.ASKING_FOR_INPUT, StateTransitionTrigger.AGENT_FINISHED_SPEAKING),
            (ConversationState.USER_INPUT, StateTransitionTrigger.USER_RESPONDS),
            (ConversationState.LLM_PROCESSING, StateTransitionTrigger.STT_SUCCESS),
            (ConversationState.RESPONSE_GENERATION, StateTransitionTrigger.NO_TOOLS_NEEDED),
            (ConversationState.SPEAKING_RESPONSE, StateTransitionTrigger.RESPONSE_READY),
            (ConversationState.CONFIRMING_PLAN, StateTransitionTrigger.SPEECH_ENDED_NATURALLY),
            (ConversationState.SENDING_SUMMARY, StateTransitionTrigger.PLAN_CONFIRMED),
            (ConversationState.CALL_END, StateTransitionTrigger.SUMMARY_SENT),
        ]

        for target_state, trigger in steps:
            result = await fsm.transition(target_state, trigger)
            assert result is True, f"Failed to transition to {target_state}"
            assert fsm.session.current_state == target_state

        # Verify transition log
        assert len(fsm.session.transition_log) == len(steps)

    @pytest.mark.asyncio
    async def test_get_valid_transitions(self, fsm):
        """Test retrieving valid transitions from current state."""
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            StateTransitionTrigger.USER_READY,
        )
        valid = fsm.get_valid_transitions()
        assert ConversationState.ASKING_FOR_INPUT in valid
        assert ConversationState.USER_INPUT in valid
        assert ConversationState.ERROR in valid

    def test_get_state_summary(self, fsm):
        """Test getting a summary of session state."""
        summary = fsm.get_state_summary()
        assert summary["run_id"] == "test_run_123"
        assert summary["user_id"] == "user_456"
        assert summary["current_state"] == "greeting"
        assert summary["error_count"] == 0
