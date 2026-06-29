"""Unit tests for streaming TTS refinements and validation (Task E1)."""

import pytest
import asyncio
from datetime import datetime, timedelta

from app.services.streaming_tts import (
    StreamingTTSValidator,
    StreamingTTSManager,
    StreamingMetrics,
    StreamingPhase,
)


@pytest.fixture
def validator():
    """Create a test validator."""
    return StreamingTTSValidator(run_id="test_run")


@pytest.fixture
def metrics():
    """Create test metrics."""
    return StreamingMetrics()


class TestStreamingMetrics:
    """Test streaming TTS metrics tracking."""

    def test_metrics_initialization(self, metrics):
        """Test metrics initialization."""
        assert metrics.phase == StreamingPhase.IDLE
        assert metrics.total_text_chars == 0
        assert metrics.chunks_generated == 0
        assert metrics.underrun_count == 0

    def test_elapsed_time(self, metrics):
        """Test elapsed time calculation."""
        metrics.started_at = datetime.utcnow()

        # Should have some elapsed time
        elapsed = metrics.elapsed_ms()
        assert elapsed >= 0

    def test_time_to_first_audio(self, metrics):
        """Test time to first audio calculation."""
        metrics.started_at = datetime.utcnow()
        metrics.first_audio_at = datetime.utcnow() + timedelta(milliseconds=500)

        ttfa = metrics.time_to_first_audio_actual_ms()
        assert 400 <= ttfa <= 600  # Allow tolerance

    def test_completion_elapsed_time(self, metrics):
        """Test elapsed time from start to completion."""
        metrics.started_at = datetime.utcnow()
        metrics.completed_at = datetime.utcnow() + timedelta(milliseconds=2000)

        elapsed = metrics.elapsed_ms()
        assert 1900 <= elapsed <= 2100


class TestStreamingValidator:
    """Test streaming TTS validation."""

    def test_time_to_first_audio_within_target(self, validator):
        """Test validation passes when within target."""
        result = validator.validate_time_to_first_audio(
            actual_ms=800,
            target_ms=1000
        )
        assert result is True

    def test_time_to_first_audio_exceeds_target(self, validator):
        """Test validation fails when exceeding target."""
        result = validator.validate_time_to_first_audio(
            actual_ms=1500,
            target_ms=1000
        )
        assert result is False

    def test_time_to_first_audio_at_target(self, validator):
        """Test validation at exact target."""
        result = validator.validate_time_to_first_audio(
            actual_ms=1000,
            target_ms=1000
        )
        assert result is True

    def test_chunk_size_validation_valid(self, validator):
        """Test valid chunk size."""
        # 4KB chunk
        result = validator.validate_chunk_size(4096)
        assert result is True

    def test_chunk_size_validation_too_small(self, validator):
        """Test chunk size too small."""
        result = validator.validate_chunk_size(100)
        assert result is False

    def test_chunk_size_validation_too_large(self, validator):
        """Test chunk size too large."""
        result = validator.validate_chunk_size(100000)
        assert result is False

    def test_buffer_health_good(self, validator):
        """Test buffer in good health."""
        result = validator.validate_buffer_health(
            buffer_size=50,
            buffer_max=100
        )
        assert result is True

    def test_buffer_health_nearly_full(self, validator):
        """Test buffer nearly full."""
        result = validator.validate_buffer_health(
            buffer_size=95,
            buffer_max=100
        )
        assert result is False
        assert validator.metrics.overflow_count > 0

    def test_buffer_health_nearly_empty(self, validator):
        """Test buffer nearly empty."""
        validator.metrics.chunks_generated = 1
        result = validator.validate_buffer_health(
            buffer_size=5,
            buffer_max=100
        )
        assert result is False
        assert validator.metrics.underrun_count > 0

    def test_validation_report(self, validator):
        """Test generating validation report."""
        validator.metrics.total_text_chars = 100
        validator.metrics.chunks_generated = 5

        report = validator.get_validation_report()

        assert report["total_text_chars"] == 100
        assert report["chunks_generated"] == 5
        assert "health_status" in report


class TestStreamingTTSManager:
    """Test streaming TTS manager."""

    @pytest.fixture
    def mock_tts_client(self):
        """Create mock TTS client."""
        class MockTTSClient:
            async def synthesize_stream(self, text):
                # Simulate TTS generating audio
                yield b"audio_chunk_1"
                yield b"audio_chunk_2"

        return MockTTSClient()

    @pytest.fixture
    def manager(self, mock_tts_client):
        """Create test manager."""
        return StreamingTTSManager(
            tts_client=mock_tts_client,
            run_id="test_run",
            target_first_audio_ms=1000
        )

    def test_manager_initialization(self, manager):
        """Test manager initialization."""
        assert manager.run_id == "test_run"
        assert manager.target_first_audio_ms == 1000
        assert manager.metrics.phase == StreamingPhase.IDLE

    def test_get_metrics(self, manager):
        """Test getting metrics."""
        metrics = manager.get_metrics()

        assert "phase" in metrics
        assert "total_text_chars" in metrics
        assert "chunks_generated" in metrics
        assert "errors" in metrics

    @pytest.mark.asyncio
    async def test_stream_response_mock(self, manager):
        """Test streaming response with mock data."""
        async def mock_llm():
            yield "Hello "
            yield "world"
            yield "!"

        chunks = []
        async for chunk in manager.stream_response(mock_llm()):
            chunks.append(chunk)

        # Should have generated some chunks
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_metrics_updated_during_streaming(self, manager):
        """Test metrics are updated during streaming."""
        async def mock_llm():
            yield "Test "
            yield "text"

        async for chunk in manager.stream_response(mock_llm()):
            pass

        # Verify metrics were updated
        assert manager.metrics.total_text_chars > 0
        assert manager.metrics.started_at is not None
        assert manager.metrics.completed_at is not None


class TestStreamingPhases:
    """Test streaming phase transitions."""

    def test_phase_enum_values(self):
        """Test phase enum has expected values."""
        assert StreamingPhase.IDLE.value == "idle"
        assert StreamingPhase.BUFFERING.value == "buffering"
        assert StreamingPhase.GENERATING.value == "generating"
        assert StreamingPhase.PLAYING.value == "playing"
        assert StreamingPhase.COMPLETE.value == "complete"

    def test_phase_transitions(self, metrics):
        """Test phase transitions."""
        assert metrics.phase == StreamingPhase.IDLE

        metrics.phase = StreamingPhase.BUFFERING
        assert metrics.phase == StreamingPhase.BUFFERING

        metrics.phase = StreamingPhase.GENERATING
        assert metrics.phase == StreamingPhase.GENERATING

        metrics.phase = StreamingPhase.COMPLETE
        assert metrics.phase == StreamingPhase.COMPLETE


class TestStreamingPerformance:
    """Test streaming performance characteristics."""

    def test_time_to_first_audio_tracking(self, metrics):
        """Test time to first audio is tracked."""
        metrics.started_at = datetime.utcnow()

        # Simulate first audio at 500ms
        metrics.first_audio_at = datetime.utcnow() + timedelta(milliseconds=500)

        ttfa = metrics.time_to_first_audio_actual_ms()
        assert 400 <= ttfa <= 600

    def test_chunk_tracking(self, metrics):
        """Test chunk counting."""
        assert metrics.chunks_generated == 0

        metrics.chunks_generated += 1
        assert metrics.chunks_generated == 1

        metrics.chunks_generated += 1
        assert metrics.chunks_generated == 2

    def test_error_tracking(self, metrics):
        """Test error counting."""
        assert metrics.generation_errors == 0

        metrics.generation_errors += 1
        assert metrics.generation_errors == 1


class TestStreamingEdgeCases:
    """Test edge cases in streaming TTS."""

    def test_validator_with_zero_metrics(self, validator):
        """Test validator handles zero metrics."""
        report = validator.get_validation_report()
        assert report["total_text_chars"] == 0
        assert report["chunks_generated"] == 0

    def test_buffer_validation_boundaries(self, validator):
        """Test buffer validation at exact boundaries."""
        # At 10% (boundary)
        result = validator.validate_buffer_health(10, 100)
        assert result is True

        # At 90% (boundary)
        result = validator.validate_buffer_health(90, 100)
        assert result is True

    def test_metrics_with_no_first_audio(self, metrics):
        """Test metrics when first audio never recorded."""
        metrics.started_at = datetime.utcnow()
        assert metrics.time_to_first_audio_actual_ms() is None


class TestStreamingValidationReport:
    """Test comprehensive validation reports."""

    def test_healthy_validation_report(self, validator):
        """Test report for healthy streaming."""
        validator.metrics.total_text_chars = 100
        validator.metrics.total_audio_bytes = 16000
        validator.metrics.chunks_generated = 4
        validator.metrics.chunks_played = 4

        report = validator.get_validation_report()
        assert report["health_status"] == "healthy"
        assert report["underrun_count"] == 0
        assert report["overflow_count"] == 0

    def test_degraded_validation_report(self, validator):
        """Test report for degraded streaming."""
        validator.metrics.underrun_count = 1

        report = validator.get_validation_report()
        assert report["health_status"] == "degraded"

    def test_report_with_errors(self, validator):
        """Test report includes all errors."""
        validator.metrics.generation_errors = 2
        validator.metrics.playback_errors = 1

        report = validator.get_validation_report()
        assert report["errors"]["generation"] == 2
        assert report["errors"]["playback"] == 1
