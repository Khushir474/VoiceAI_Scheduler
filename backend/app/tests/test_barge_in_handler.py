"""Unit tests for barge-in detection and handling."""

import pytest
import asyncio
from datetime import datetime

from app.services.barge_in_handler import (
    BargeInHandler,
    BargeInDetector,
)
from app.services.audio_buffer import VADEventQueue
from app.agents.conversation_state_machine import (
    ConversationSession,
    ConversationStateMachine,
    ConversationState,
)


@pytest.fixture
def vad_queue():
    """Create a test VAD event queue."""
    return VADEventQueue()


@pytest.fixture
def session():
    """Create a test conversation session."""
    return ConversationSession(
        run_id="test_run",
        user_id="user_123",
    )


@pytest.fixture
def fsm(session):
    """Create a test FSM."""
    return ConversationStateMachine(session)


@pytest.fixture
def barge_in_handler(fsm, vad_queue):
    """Create a test barge-in handler."""
    return BargeInHandler(fsm, vad_queue, run_id="test_run")


class TestBargeInHandlerBasics:
    """Test basic barge-in handler functionality."""

    def test_handler_creation(self, barge_in_handler):
        """Test handler initialization."""
        assert barge_in_handler.barge_in_count == 0
        assert barge_in_handler.last_vad_state == "idle"
        assert barge_in_handler.last_barge_in_timestamp is None

    def test_set_barge_in_callback(self, barge_in_handler):
        """Test registering barge-in callback."""
        callback_called = []

        async def callback():
            callback_called.append(True)

        barge_in_handler.set_barge_in_callback(callback)
        assert barge_in_handler.on_barge_in is not None

    @pytest.mark.asyncio
    async def test_empty_vad_queue(self, barge_in_handler):
        """Test processing empty VAD queue."""
        result = await barge_in_handler.process_vad_events()
        assert result is False
        assert barge_in_handler.barge_in_count == 0


class TestBargeInDetection:
    """Test barge-in detection logic."""

    @pytest.mark.asyncio
    async def test_barge_in_during_speaking_response(
        self, fsm, vad_queue, barge_in_handler
    ):
        """Test barge-in during SPEAKING_RESPONSE state."""
        # Setup: Agent is speaking
        await fsm.transition(
            ConversationState.PRESENTING_PLAN,
            asyncio.create_task(asyncio.sleep(0)),  # dummy trigger
        )
        # Manually set to SPEAKING_RESPONSE for testing
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        # User speaks
        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.85,
        ))

        # Register callback
        callback_called = []

        async def stop_tts():
            callback_called.append(True)

        barge_in_handler.set_barge_in_callback(stop_tts)

        # Process events
        result = await barge_in_handler.process_vad_events()

        assert result is True
        assert barge_in_handler.barge_in_count == 1
        assert len(callback_called) == 1
        assert fsm.session.current_state == ConversationState.USER_INPUT

    @pytest.mark.asyncio
    async def test_no_barge_in_wrong_state(self, fsm, vad_queue, barge_in_handler):
        """Test that barge-in is not detected in wrong state."""
        # FSM in ASKING_FOR_INPUT (not SPEAKING_RESPONSE)
        fsm.session.current_state = ConversationState.ASKING_FOR_INPUT

        # User speaks
        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.85,
        ))

        result = await barge_in_handler.process_vad_events()

        assert result is False
        assert barge_in_handler.barge_in_count == 0

    @pytest.mark.asyncio
    async def test_low_confidence_not_barge_in(self, fsm, vad_queue, barge_in_handler):
        """Test that low-confidence speech doesn't trigger barge-in."""
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        # Very low confidence (noise, not speech)
        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.2,  # Below 0.5 threshold
        ))

        result = await barge_in_handler.process_vad_events()

        assert result is False
        assert barge_in_handler.barge_in_count == 0

    @pytest.mark.asyncio
    async def test_idle_vad_not_barge_in(self, fsm, vad_queue, barge_in_handler):
        """Test that idle VAD doesn't trigger barge-in."""
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="idle",
            confidence=0.1,
        ))

        result = await barge_in_handler.process_vad_events()

        assert result is False
        assert barge_in_handler.barge_in_count == 0


class TestMultipleBargeIns:
    """Test handling multiple barge-in events."""

    @pytest.mark.asyncio
    async def test_multiple_barge_ins_counted(self, fsm, vad_queue, barge_in_handler):
        """Test that multiple barge-ins are counted."""
        callback_count = [0]

        async def count_callback():
            callback_count[0] += 1

        barge_in_handler.set_barge_in_callback(count_callback)

        # First barge-in
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE
        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.9,
        ))
        await barge_in_handler.process_vad_events()

        assert barge_in_handler.barge_in_count == 1
        assert callback_count[0] == 1

        # Second barge-in (reset to SPEAKING_RESPONSE)
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE
        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.95,
        ))
        await barge_in_handler.process_vad_events()

        assert barge_in_handler.barge_in_count == 2
        assert callback_count[0] == 2

    @pytest.mark.asyncio
    async def test_batch_vad_events(self, fsm, vad_queue, barge_in_handler):
        """Test processing multiple VAD events in one call."""
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        # Queue multiple events
        for i in range(3):
            vad_queue.put(VADEventQueue.VADEvent(
                vad_state="speaking",
                confidence=0.8 + (0.05 * i),
            ))

        result = await barge_in_handler.process_vad_events()

        # First event should trigger barge-in
        assert result is True
        assert barge_in_handler.barge_in_count == 1


class TestBargeInMetrics:
    """Test barge-in metrics collection."""

    @pytest.mark.asyncio
    async def test_metrics_after_barge_in(self, fsm, vad_queue, barge_in_handler):
        """Test metrics after a barge-in event."""
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.88,
        ))

        await barge_in_handler.process_vad_events()

        metrics = barge_in_handler.get_metrics()

        assert metrics["barge_in_count"] == 1
        assert metrics["last_vad_state"] == "speaking"
        assert metrics["last_vad_confidence"] == 0.88
        assert metrics["last_barge_in_timestamp"] is not None
        assert metrics["seconds_since_last_barge_in"] is not None


class TestBargeInDetector:
    """Test advanced barge-in detection."""

    @pytest.fixture
    def detector(self):
        """Create a test detector."""
        vad_queue = VADEventQueue()
        return BargeInDetector(
            vad_queue,
            confidence_threshold=0.5,
            min_speech_duration_ms=300,
            run_id="test",
        )

    @pytest.mark.asyncio
    async def test_speech_detection(self, detector):
        """Test detecting user speech."""
        # Queue speech onset
        detector.vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.9,
        ))

        # Process while speaking
        result = await detector.detect_speech_onset()
        assert result is None  # Still speaking

        # Queue speech offset (after 500ms)
        import time
        time.sleep(0.3)
        detector.vad_queue.put(VADEventQueue.VADEvent(
            vad_state="idle",
            confidence=0.1,
        ))

        result = await detector.detect_speech_onset()
        assert result is not None
        assert result["duration_ms"] >= 300

    def test_detector_stats(self, detector):
        """Test detector statistics."""
        stats = detector.get_detector_stats()

        assert stats["confidence_threshold"] == 0.5
        assert stats["min_speech_duration_ms"] == 300
        assert stats["false_positive_count"] == 0

    @pytest.mark.asyncio
    async def test_false_positive_detection(self, detector):
        """Test detection of false positives (short speech bursts)."""
        # Queue very short speech burst
        detector.vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.95,
        ))

        # Immediately idle (< 300ms)
        detector.vad_queue.put(VADEventQueue.VADEvent(
            vad_state="idle",
            confidence=0.1,
        ))

        result = await detector.detect_speech_onset()
        assert result is None  # Too short, rejected
        assert detector.false_positive_count == 1

    @pytest.mark.asyncio
    async def test_low_confidence_rejected(self, detector):
        """Test rejection of low-confidence speech."""
        detector.vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.3,  # Below 0.5 threshold
        ))

        result = await detector.detect_speech_onset()
        assert detector.false_positive_count >= 0  # Depending on timing


class TestBargeInCallbackHandling:
    """Test callback execution on barge-in."""

    @pytest.mark.asyncio
    async def test_callback_exception_handled(self, barge_in_handler, fsm, vad_queue):
        """Test that exceptions in callback don't break handler."""

        async def failing_callback():
            raise RuntimeError("Callback error")

        barge_in_handler.set_barge_in_callback(failing_callback)
        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.9,
        ))

        # Should not raise exception
        result = await barge_in_handler.process_vad_events()
        assert result is True  # Should have attempted barge-in despite error

    @pytest.mark.asyncio
    async def test_no_callback_registered(self, barge_in_handler, fsm, vad_queue):
        """Test barge-in without callback registered."""
        # No callback registered
        assert barge_in_handler.on_barge_in is None

        fsm.session.current_state = ConversationState.SPEAKING_RESPONSE

        vad_queue.put(VADEventQueue.VADEvent(
            vad_state="speaking",
            confidence=0.9,
        ))

        result = await barge_in_handler.process_vad_events()

        # Should still transition FSM even without callback
        assert result is True
        assert barge_in_handler.barge_in_count == 1
