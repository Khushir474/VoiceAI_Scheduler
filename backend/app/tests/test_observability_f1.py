"""Unit tests for Task F1: Enhanced logging and metrics."""

import pytest
from datetime import datetime, timedelta

from app.services.metrics_collector import (
    MetricsCollector,
    MetricCategory,
    CallSummary,
)
from app.services.langfuse_logger import (
    LangfuseLogger,
    LangfuseIntegration,
)


@pytest.fixture
def metrics_collector():
    """Create a test metrics collector."""
    return MetricsCollector(run_id="test_run_123", user_id="user_456")


@pytest.fixture
def langfuse_logger():
    """Create a test Langfuse logger (disabled for tests)."""
    return LangfuseLogger(enabled=False, run_id="test_run_123")


@pytest.fixture
def langfuse_integration(langfuse_logger):
    """Create a test Langfuse integration."""
    return LangfuseIntegration(langfuse_logger)


class TestMetricsCollector:
    """Test metrics collection."""

    def test_initialization(self, metrics_collector):
        """Test collector initialization."""
        assert metrics_collector.run_id == "test_run_123"
        assert metrics_collector.user_id == "user_456"
        assert len(metrics_collector.state_transitions) == 0

    def test_record_state_transition(self, metrics_collector):
        """Test recording state transitions."""
        metrics_collector.record_state_transition(
            from_state="idle",
            to_state="processing",
            trigger="user_input",
            latency_ms=150,
        )

        assert len(metrics_collector.state_transitions) == 1
        assert metrics_collector.call_summary.state_transitions == 1

    def test_record_multiple_transitions(self, metrics_collector):
        """Test recording multiple transitions."""
        for i in range(5):
            metrics_collector.record_state_transition(
                from_state=f"state_{i}",
                to_state=f"state_{i+1}",
                trigger="test",
                latency_ms=100 * i,
            )

        assert len(metrics_collector.state_transitions) == 5
        assert metrics_collector.call_summary.state_transitions == 5

    def test_record_error_recovery(self, metrics_collector):
        """Test recording error recovery."""
        metrics_collector.record_error_recovery(
            error_type="stt_error",
            attempt=1,
            strategy="ask_repeat",
            success=True,
            latency_ms=250,
        )

        assert len(metrics_collector.error_recoveries) == 1
        assert metrics_collector.call_summary.error_count == 1
        assert metrics_collector.call_summary.error_recoveries == 1

    def test_record_failed_recovery(self, metrics_collector):
        """Test recording failed recovery."""
        metrics_collector.record_error_recovery(
            error_type="network_error",
            attempt=1,
            strategy="retry",
            success=False,
            latency_ms=100,
        )

        assert metrics_collector.call_summary.error_count == 1
        assert metrics_collector.call_summary.error_recoveries == 0

    def test_record_vad_metrics(self, metrics_collector):
        """Test recording VAD metrics."""
        metrics_collector.record_vad_metrics(
            sensitivity=0.5,
            speech_starts=5,
            speech_ends=4,
            false_positives=1,
            false_negatives=0,
            avg_confidence=0.85,
        )

        assert len(metrics_collector.vad_metrics) == 1

    def test_record_streaming_tts(self, metrics_collector):
        """Test recording streaming TTS metrics."""
        metrics_collector.record_streaming_tts(
            text_chars=250,
            audio_bytes=16000,
            time_to_first_audio_ms=650,
            total_elapsed_ms=2500,
            chunks_generated=5,
            underrun_count=0,
            overflow_count=0,
            generation_errors=0,
        )

        assert len(metrics_collector.tts_metrics) == 1
        assert metrics_collector.call_summary.time_to_first_audio_ms == 650

    def test_record_barge_in(self, metrics_collector):
        """Test recording barge-in metrics."""
        metrics_collector.record_barge_in(
            barge_in_count=2,
            avg_confidence=0.88,
            latency_ms=200,
            state_transition_success=True,
        )

        assert len(metrics_collector.barge_in_metrics) == 1
        assert metrics_collector.call_summary.barge_in_count == 2

    def test_record_playback(self, metrics_collector):
        """Test recording playback metrics."""
        metrics_collector.record_playback(
            total_audio_bytes=32000,
            position_percentage=100.0,
            interruption_count=1,
            pause_count=0,
            error_count=0,
            elapsed_ms=2000,
        )

        assert len(metrics_collector.playback_metrics) == 1

    def test_record_endpointing(self, metrics_collector):
        """Test recording endpointing metrics."""
        metrics_collector.record_endpointing(
            endpointing_count=3,
            stage_1_timeouts=1,
            stage_2_timeouts=0,
            stage_3_timeouts=0,
            current_silence_ms=0,
        )

        assert len(metrics_collector.endpointing_metrics) == 1
        assert metrics_collector.call_summary.silence_timeouts == 1

    def test_finalize_call(self, metrics_collector):
        """Test finalizing call."""
        metrics_collector.finalize_call(success=True, final_state="completed")

        assert metrics_collector.call_summary.success is True
        assert metrics_collector.call_summary.final_state == "completed"
        assert metrics_collector.call_summary.end_time is not None
        assert metrics_collector.call_summary.total_duration_ms > 0

    def test_get_call_summary(self, metrics_collector):
        """Test getting call summary."""
        metrics_collector.record_state_transition(
            "a", "b", "test", 100
        )
        metrics_collector.finalize_call(success=True, final_state="end")

        summary = metrics_collector.get_call_summary()

        assert summary.success is True
        assert summary.state_transitions == 1

    def test_get_metrics_by_category_state_machine(self, metrics_collector):
        """Test getting state machine metrics."""
        metrics_collector.record_state_transition(
            "greeting", "presenting", "user_ready", 150
        )

        metrics = metrics_collector.get_metrics_by_category(
            MetricCategory.STATE_MACHINE
        )

        assert metrics["transitions"] == 1
        assert len(metrics["metrics"]) == 1

    def test_get_metrics_by_category_error_recovery(self, metrics_collector):
        """Test getting error recovery metrics."""
        metrics_collector.record_error_recovery(
            "stt_error", 1, "ask_repeat", True, 200
        )

        metrics = metrics_collector.get_metrics_by_category(
            MetricCategory.ERROR_RECOVERY
        )

        assert metrics["recoveries"] == 1
        assert metrics["successful"] == 1

    def test_get_all_metrics(self, metrics_collector):
        """Test getting all metrics."""
        metrics_collector.record_state_transition("a", "b", "test", 100)
        metrics_collector.record_error_recovery("err", 1, "strat", True, 50)

        all_metrics = metrics_collector.get_all_metrics()

        assert "call_summary" in all_metrics
        assert "state_machine" in all_metrics
        assert "error_recovery" in all_metrics


class TestLangfuseLogger:
    """Test Langfuse logger."""

    def test_initialization_disabled(self, langfuse_logger):
        """Test logger initialization with Langfuse disabled."""
        assert langfuse_logger.enabled is False
        assert langfuse_logger.client is None

    def test_initialization_with_credentials(self):
        """Test logger with credentials."""
        logger = LangfuseLogger(
            api_key="test_key",
            secret_key="test_secret",
            enabled=False,  # Disabled for testing
        )

        assert logger.enabled is False

    def test_start_trace(self, langfuse_logger):
        """Test starting a trace."""
        trace_id = langfuse_logger.start_trace("voice_call")

        assert trace_id == langfuse_logger.trace_id

    def test_start_span(self, langfuse_logger):
        """Test starting a span."""
        span_id = langfuse_logger.start_span("generate_plan", span_type="llm")

        assert span_id is not None
        assert "generate_plan" in span_id

    def test_end_span(self, langfuse_logger):
        """Test ending a span."""
        span_id = langfuse_logger.start_span("test_span")
        langfuse_logger.end_span(span_id, status="success")

        assert span_id not in langfuse_logger.active_spans

    def test_log_metric(self, langfuse_logger):
        """Test logging a metric."""
        # Should not raise exception
        langfuse_logger.log_metric(
            metric_name="latency",
            value=150.0,
            category="performance",
        )

    def test_log_event(self, langfuse_logger):
        """Test logging an event."""
        # Should not raise exception
        langfuse_logger.log_event(
            event_name="barge_in_detected",
            event_type="voice_interaction",
            details={"confidence": 0.85},
        )

    def test_end_trace(self, langfuse_logger):
        """Test ending a trace."""
        # Should not raise exception
        langfuse_logger.end_trace(output={"success": True})

    def test_get_trace_url(self, langfuse_logger):
        """Test getting trace URL."""
        url = langfuse_logger.get_trace_url()

        assert url is None  # Disabled logger


class TestLangfuseIntegration:
    """Test Langfuse integration with DailyOps components."""

    @pytest.mark.asyncio
    async def test_log_state_transition(self, langfuse_integration):
        """Test logging state transition."""
        await langfuse_integration.log_state_transition(
            from_state="greeting",
            to_state="presenting",
            trigger="user_ready",
            latency_ms=150,
        )

    @pytest.mark.asyncio
    async def test_log_error_recovery(self, langfuse_integration):
        """Test logging error recovery."""
        await langfuse_integration.log_error_recovery(
            error_type="stt_error",
            strategy="ask_repeat",
            success=True,
            latency_ms=200,
        )

    @pytest.mark.asyncio
    async def test_log_barge_in(self, langfuse_integration):
        """Test logging barge-in."""
        await langfuse_integration.log_barge_in(
            confidence=0.88,
            latency_ms=250,
        )

    @pytest.mark.asyncio
    async def test_log_tool_call(self, langfuse_integration):
        """Test logging tool call."""
        await langfuse_integration.log_tool_call(
            tool_name="calendar",
            latency_ms=350,
            success=True,
        )

    @pytest.mark.asyncio
    async def test_log_tool_error(self, langfuse_integration):
        """Test logging tool error."""
        await langfuse_integration.log_tool_call(
            tool_name="weather",
            latency_ms=2000,
            success=False,
            error="API timeout",
        )

    @pytest.mark.asyncio
    async def test_log_llm_call(self, langfuse_integration):
        """Test logging LLM call."""
        await langfuse_integration.log_llm_call(
            prompt_tokens=150,
            completion_tokens=75,
            latency_ms=1500,
        )

    @pytest.mark.asyncio
    async def test_log_call_complete(self, langfuse_integration):
        """Test logging call completion."""
        summary = {
            "success": True,
            "duration_ms": 5000,
            "barge_in_count": 1,
            "error_count": 0,
        }

        await langfuse_integration.log_call_complete(
            success=True,
            final_state="completed",
            total_duration_ms=5000,
            summary=summary,
        )


class TestCallSummary:
    """Test call summary data."""

    def test_call_summary_creation(self):
        """Test creating call summary."""
        summary = CallSummary(
            run_id="run_123",
            user_id="user_456",
            start_time=datetime.utcnow(),
        )

        assert summary.run_id == "run_123"
        assert summary.success is False

    def test_call_summary_finalization(self):
        """Test finalizing call summary."""
        start = datetime.utcnow()
        summary = CallSummary(
            run_id="run_123",
            user_id="user_456",
            start_time=start,
        )

        summary.end_time = datetime.utcnow()
        summary.success = True
        summary.total_duration_ms = 5000

        assert summary.success is True
        assert summary.total_duration_ms == 5000

    def test_call_summary_with_metrics(self):
        """Test call summary with metrics."""
        summary = CallSummary(
            run_id="run_123",
            user_id="user_456",
            start_time=datetime.utcnow(),
        )

        summary.state_transitions = 10
        summary.barge_in_count = 2
        summary.error_count = 1
        summary.error_recoveries = 1

        assert summary.state_transitions == 10
        assert summary.barge_in_count == 2
        assert summary.error_recoveries == 1
