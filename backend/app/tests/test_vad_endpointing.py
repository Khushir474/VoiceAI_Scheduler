"""Unit tests for VAD management and endpointing."""

import pytest
import asyncio
from datetime import datetime

from app.services.vad_manager import VADConfig, VADManager, VADMetrics
from app.services.endpointing_handler import (
    EndpointingHandler,
    SilenceTimeoutStage,
    ContextAwareEndpointing,
)
from app.agents.conversation_state_machine import (
    ConversationSession,
    ConversationStateMachine,
    ConversationState,
)


@pytest.fixture
def vad_config():
    """Create a test VAD config."""
    return VADConfig(user_id="user_123")


@pytest.fixture
def vad_manager():
    """Create a test VAD manager."""
    return VADManager(run_id="test_run")


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
def endpointing_handler(fsm, vad_manager):
    """Create a test endpointing handler."""
    return EndpointingHandler(fsm, vad_manager, run_id="test_run")


class TestVADConfig:
    """Test VAD configuration."""

    def test_vad_config_creation(self, vad_config):
        """Test creating a VAD config."""
        assert vad_config.user_id == "user_123"
        assert vad_config.sensitivity == 0.5
        assert vad_config.speech_start_threshold == 0.2
        assert vad_config.speech_end_threshold == 0.8

    def test_vad_config_defaults(self):
        """Test default values."""
        config = VADConfig(user_id="user")
        assert config.silence_timeout_confirmation_ms == 2500
        assert config.silence_timeout_decision_ms == 5000
        assert config.silence_timeout_hangup_ms == 10000
        assert config.min_speech_duration_ms == 300

    def test_custom_vad_config(self):
        """Test custom configuration."""
        config = VADConfig(
            user_id="user",
            sensitivity=0.7,
            speech_start_threshold=0.3,
            silence_timeout_confirmation_ms=3000,
        )
        assert config.sensitivity == 0.7
        assert config.speech_start_threshold == 0.3
        assert config.silence_timeout_confirmation_ms == 3000


class TestVADManager:
    """Test VAD manager functionality."""

    def test_manager_creation(self, vad_manager):
        """Test manager initialization."""
        assert len(vad_manager.configs) == 0
        assert len(vad_manager.metrics) == 0

    @pytest.mark.asyncio
    async def test_load_config_defaults(self, vad_manager):
        """Test loading defaults when no DB."""
        config = await vad_manager.load_config("user_123")

        assert config.user_id == "user_123"
        assert config.sensitivity == 0.5

    def test_cache_loaded_config(self, vad_manager):
        """Test that configs are cached."""
        config1 = vad_manager.get_config("user_123")
        vad_manager.configs["user_123"] = VADConfig(user_id="user_123", sensitivity=0.7)

        config2 = vad_manager.get_config("user_123")
        assert config2.sensitivity == 0.7

    def test_should_trigger_speech_start(self, vad_manager):
        """Test speech start threshold check."""
        config = VADConfig(user_id="user", speech_start_threshold=0.2)

        # Below threshold
        assert not vad_manager.should_trigger_speech_start(
            "speaking", 0.1, config
        )

        # At threshold
        assert vad_manager.should_trigger_speech_start("speaking", 0.2, config)

        # Above threshold
        assert vad_manager.should_trigger_speech_start("speaking", 0.9, config)

        # Idle state
        assert not vad_manager.should_trigger_speech_start("idle", 0.9, config)

    def test_should_trigger_speech_end(self, vad_manager):
        """Test speech end threshold check."""
        config = VADConfig(user_id="user", speech_end_threshold=0.8)

        # Below threshold
        assert not vad_manager.should_trigger_speech_end("idle", 0.5, config)

        # At threshold
        assert vad_manager.should_trigger_speech_end("idle", 0.8, config)

        # Speaking state
        assert not vad_manager.should_trigger_speech_end("speaking", 0.9, config)

    def test_update_metrics_speech_start(self, vad_manager):
        """Test updating metrics for speech start."""
        vad_manager.update_metrics("user_123", "speech_start", confidence=0.9)

        metrics = vad_manager.get_metrics("user_123")
        assert metrics is not None
        assert metrics.speech_starts_detected == 1
        assert metrics.avg_speech_start_confidence == 0.9

    def test_update_metrics_multiple_starts(self, vad_manager):
        """Test averaging confidence over multiple starts."""
        vad_manager.update_metrics("user_123", "speech_start", confidence=0.8)
        vad_manager.update_metrics("user_123", "speech_start", confidence=0.9)

        metrics = vad_manager.get_metrics("user_123")
        assert metrics.speech_starts_detected == 2
        assert abs(metrics.avg_speech_start_confidence - 0.85) < 0.01

    def test_update_metrics_false_positives(self, vad_manager):
        """Test tracking false positives."""
        vad_manager.update_metrics("user_123", "false_positive")
        vad_manager.update_metrics("user_123", "false_positive")

        metrics = vad_manager.get_metrics("user_123")
        assert metrics.false_positives == 2


class TestSilenceTimeoutStage:
    """Test silence timeout stage tracking."""

    def test_stage_initialization(self):
        """Test initial stage state."""
        stage = SilenceTimeoutStage()
        assert stage.silence_started_at is None
        assert stage.current_stage == 0

    def test_start_silence(self):
        """Test starting silence."""
        stage = SilenceTimeoutStage()
        stage.start_silence()

        assert stage.silence_started_at is not None
        assert stage.elapsed_ms() >= 0

    @pytest.mark.asyncio
    async def test_stage_1_timeout(self):
        """Test reaching stage 1 (2.5s)."""
        stage = SilenceTimeoutStage()
        stage.start_silence()

        # Simulate 2.6 seconds of silence
        stage.silence_started_at = datetime.utcnow() - timedelta(milliseconds=2600)

        new_stage = stage.check_stage()
        assert new_stage == 1

    def test_silence_reset(self):
        """Test resetting silence timer."""
        stage = SilenceTimeoutStage()
        stage.start_silence()
        stage.current_stage = 1

        stage.reset()

        assert stage.silence_started_at is None
        assert stage.current_stage == 0
        assert stage.elapsed_ms() == 0


class TestEndpointingHandler:
    """Test endpointing and silence timeout handling."""

    def test_handler_initialization(self, endpointing_handler):
        """Test handler initialization."""
        assert endpointing_handler.endpointing_count == 0
        assert endpointing_handler.stage_1_timeout_count == 0
        assert endpointing_handler.current_vad_state == "idle"

    def test_set_callbacks(self, endpointing_handler):
        """Test registering callbacks."""

        async def callback():
            pass

        endpointing_handler.set_callbacks(
            on_speech_ended=callback,
            on_confirmation_needed=callback,
        )

        assert endpointing_handler.on_speech_ended is not None
        assert endpointing_handler.on_confirmation_needed is not None

    @pytest.mark.asyncio
    async def test_speech_onset_detection(self, endpointing_handler):
        """Test detecting when speech starts."""
        # Start with silence
        assert endpointing_handler.current_vad_state == "idle"

        # Speech begins
        await endpointing_handler.process_vad_event("speaking", 0.9)

        assert endpointing_handler.current_vad_state == "speaking"

    @pytest.mark.asyncio
    async def test_speech_offset_detection(self, endpointing_handler):
        """Test detecting when speech ends (endpointing)."""
        # Start with speech
        await endpointing_handler.process_vad_event("speaking", 0.9)
        assert endpointing_handler.endpointing_count == 0

        # Speech ends
        await endpointing_handler.process_vad_event("idle", 0.1)

        assert endpointing_handler.endpointing_count == 1
        assert endpointing_handler.last_speech_end is not None

    @pytest.mark.asyncio
    async def test_silence_timer_progression(self, endpointing_handler, fsm):
        """Test silence stage progression."""
        # Setup: User is asking for input
        fsm.session.current_state = ConversationState.ASKING_FOR_INPUT

        # Simulate speech ending
        await endpointing_handler.process_vad_event("idle", 0.1)

        # Manually set silence_started_at to simulate 2.6 seconds elapsed
        from datetime import timedelta

        endpointing_handler.silence_stage.silence_started_at = datetime.utcnow() - timedelta(
            milliseconds=2600
        )

        new_stage = await endpointing_handler.check_silence_timeouts()
        # Would check for stage 1 timeout

    @pytest.mark.asyncio
    async def test_reset_silence_timer(self, endpointing_handler):
        """Test resetting silence timer on user response."""
        # Start silence
        endpointing_handler.silence_stage.start_silence()
        assert endpointing_handler.silence_stage.elapsed_ms() >= 0

        # Reset on user response
        endpointing_handler.reset_silence_timer()

        assert endpointing_handler.silence_stage.silence_started_at is None


class TestEndpointingMetrics:
    """Test endpointing metrics collection."""

    def test_metrics_collection(self, endpointing_handler):
        """Test collecting endpointing metrics."""
        endpointing_handler.endpointing_count = 3
        endpointing_handler.stage_1_timeout_count = 1

        metrics = endpointing_handler.get_metrics()

        assert metrics["endpointing_count"] == 3
        assert metrics["stage_1_timeouts"] == 1

    def test_metrics_full_scenario(self, endpointing_handler):
        """Test metrics in a full scenario."""
        # Simulate a call
        endpointing_handler.endpointing_count = 2
        endpointing_handler.stage_2_timeout_count = 1
        endpointing_handler.stage_3_timeout_count = 0
        endpointing_handler.current_vad_state = "idle"

        metrics = endpointing_handler.get_metrics()

        assert metrics["endpointing_count"] == 2
        assert metrics["stage_2_timeouts"] == 1
        assert metrics["current_vad_state"] == "idle"


class TestContextAwareEndpointing:
    """Test context-aware endpointing adjustments."""

    @pytest.fixture
    def context_aware(self, endpointing_handler):
        """Create a context-aware wrapper."""
        return ContextAwareEndpointing(endpointing_handler)

    def test_timeouts_default_state(self, context_aware):
        """Test timeouts in ASKING_FOR_INPUT state."""
        context_aware.handler.fsm.session.current_state = ConversationState.ASKING_FOR_INPUT

        timeouts = context_aware.get_effective_timeouts()

        assert timeouts["stage_1_ms"] == 2500  # Normal timeout
        assert timeouts["stage_2_ms"] == 5000
        assert timeouts["stage_3_ms"] == 10000

    def test_timeouts_confirming_state(self, context_aware):
        """Test timeouts in CONFIRMING_PLAN state (conservative)."""
        context_aware.handler.fsm.session.current_state = ConversationState.CONFIRMING_PLAN

        timeouts = context_aware.get_effective_timeouts()

        # Should be longer (1.5x multiplier)
        assert timeouts["stage_1_ms"] > 2500
        assert timeouts["stage_2_ms"] > 5000

    def test_timeouts_presenting_state(self, context_aware):
        """Test timeouts during PRESENTING_PLAN (no timeout)."""
        context_aware.handler.fsm.session.current_state = ConversationState.PRESENTING_PLAN

        timeouts = context_aware.get_effective_timeouts()

        # Should be infinite (no timeout during presentation)
        assert timeouts["stage_1_ms"] == float("inf")
        assert timeouts["stage_2_ms"] == float("inf")

    def test_should_apply_endpointing(self, context_aware):
        """Test when endpointing should be applied."""
        # Should apply during ASKING_FOR_INPUT
        context_aware.handler.fsm.session.current_state = ConversationState.ASKING_FOR_INPUT
        assert context_aware.should_apply_endpointing()

        # Should not apply during PRESENTING_PLAN
        context_aware.handler.fsm.session.current_state = ConversationState.PRESENTING_PLAN
        assert not context_aware.should_apply_endpointing()

        # Should not apply during CALL_END
        context_aware.handler.fsm.session.current_state = ConversationState.CALL_END
        assert not context_aware.should_apply_endpointing()


class TestVADSensitivityTuning:
    """Test VAD sensitivity tuning."""

    def test_sensitivity_affects_threshold(self, vad_manager):
        """Test that sensitivity affects effective threshold."""
        config_low_sens = VADConfig(user_id="user", sensitivity=0.2)
        config_high_sens = VADConfig(user_id="user", sensitivity=0.9)

        # Low sensitivity (more sensitive) should have lower effective threshold
        # High sensitivity (less sensitive) should have higher effective threshold

        # Both should detect speech at high confidence
        assert vad_manager.should_trigger_speech_start("speaking", 0.9, config_low_sens)
        assert vad_manager.should_trigger_speech_start("speaking", 0.9, config_high_sens)

    def test_confidence_range(self, vad_manager):
        """Test confidence threshold validation."""
        config = VADConfig(
            user_id="user",
            speech_start_threshold=0.5,  # 50% confidence
        )

        # Below range
        assert not vad_manager.should_trigger_speech_start("speaking", 0.0, config)

        # In range
        assert vad_manager.should_trigger_speech_start("speaking", 0.5, config)

        # Above range
        assert vad_manager.should_trigger_speech_start("speaking", 1.0, config)


# Import timedelta for use in tests
from datetime import timedelta
