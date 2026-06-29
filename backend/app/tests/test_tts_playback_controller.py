"""Unit tests for TTS playback control and interruption."""

import pytest
import asyncio
from datetime import datetime

from app.services.tts_playback_controller import (
    PlaybackController,
    PlaybackState,
    PlaybackPosition,
    PlaybackInterruptionHandler,
)


@pytest.fixture
def controller():
    """Create a test playback controller."""
    return PlaybackController(run_id="test_run")


@pytest.fixture
def interruption_handler(controller):
    """Create a test interruption handler."""
    return PlaybackInterruptionHandler(controller, run_id="test_run")


class TestPlaybackControllerBasics:
    """Test basic playback controller functionality."""

    def test_initialization(self, controller):
        """Test controller initialization."""
        assert controller.state == PlaybackState.IDLE
        assert controller.started_at is None
        assert controller.total_audio_played == 0
        assert controller.interruption_count == 0

    def test_audio_parameters(self, controller):
        """Test audio parameter configuration."""
        assert controller.sample_rate == 16000
        assert controller.bit_depth == 16

    def test_custom_audio_parameters(self):
        """Test custom audio parameters."""
        controller = PlaybackController(
            run_id="test",
            audio_sample_rate=24000,
            audio_bit_depth=24,
        )
        assert controller.sample_rate == 24000
        assert controller.bit_depth == 24


class TestPlaybackStateTransitions:
    """Test playback state machine transitions."""

    @pytest.mark.asyncio
    async def test_idle_to_generating(self, controller):
        """Test IDLE → GENERATING transition."""
        await controller.start_generating()
        assert controller.state == PlaybackState.GENERATING

    @pytest.mark.asyncio
    async def test_generating_to_playing(self, controller):
        """Test GENERATING → PLAYING transition."""
        await controller.start_generating()
        await controller.start_playing()

        assert controller.state == PlaybackState.PLAYING
        assert controller.started_at is not None

    @pytest.mark.asyncio
    async def test_playing_to_paused(self, controller):
        """Test PLAYING → PAUSED transition."""
        await controller.start_generating()
        await controller.start_playing()
        result = await controller.pause()

        assert result is True
        assert controller.state == PlaybackState.PAUSED
        assert controller.pause_count == 1

    @pytest.mark.asyncio
    async def test_paused_to_playing(self, controller):
        """Test PAUSED → PLAYING transition (resume)."""
        await controller.start_generating()
        await controller.start_playing()
        await controller.pause()
        result = await controller.resume()

        assert result is True
        assert controller.state == PlaybackState.PLAYING

    @pytest.mark.asyncio
    async def test_playing_to_stopped(self, controller):
        """Test PLAYING → STOPPED transition."""
        await controller.start_generating()
        await controller.start_playing()
        result = await controller.stop()

        assert result is True
        assert controller.state == PlaybackState.STOPPED
        assert controller.stopped_at is not None
        assert controller.interruption_count == 1

    @pytest.mark.asyncio
    async def test_playing_to_idle_via_finish(self, controller):
        """Test PLAYING → IDLE transition (natural finish)."""
        await controller.start_generating()
        await controller.start_playing()
        await controller.finish_playback()

        assert controller.state == PlaybackState.IDLE


class TestInvalidTransitions:
    """Test that invalid transitions are rejected."""

    @pytest.mark.asyncio
    async def test_cannot_play_from_idle(self, controller):
        """Test that start_playing from IDLE is rejected."""
        # Do not call start_generating
        await controller.start_playing()

        # Should still be IDLE
        assert controller.state == PlaybackState.IDLE

    @pytest.mark.asyncio
    async def test_cannot_pause_from_idle(self, controller):
        """Test that pause from IDLE is rejected."""
        result = await controller.pause()
        assert result is False

    @pytest.mark.asyncio
    async def test_cannot_resume_from_playing(self, controller):
        """Test that resume from PLAYING is rejected."""
        await controller.start_generating()
        await controller.start_playing()
        result = await controller.resume()

        assert result is False

    @pytest.mark.asyncio
    async def test_cannot_stop_when_stopped(self, controller):
        """Test that stop from STOPPED is rejected."""
        await controller.start_generating()
        await controller.start_playing()
        await controller.stop()

        result = await controller.stop()
        assert result is False

    @pytest.mark.asyncio
    async def test_cannot_finish_unless_playing(self, controller):
        """Test that finish is rejected unless in PLAYING state."""
        await controller.start_generating()
        # Don't start playing
        await controller.finish_playback()

        # Should still be GENERATING
        assert controller.state == PlaybackState.GENERATING


class TestPlaybackCallbacks:
    """Test callback execution on state transitions."""

    @pytest.mark.asyncio
    async def test_on_playback_started_callback(self, controller):
        """Test on_playback_started callback."""
        callback_called = []

        async def callback():
            callback_called.append(True)

        controller.on_playback_started = callback

        await controller.start_generating()
        await controller.start_playing()

        assert len(callback_called) == 1

    @pytest.mark.asyncio
    async def test_on_playback_ended_callback(self, controller):
        """Test on_playback_ended callback."""
        callback_called = []

        async def callback():
            callback_called.append(True)

        controller.on_playback_ended = callback

        await controller.start_generating()
        await controller.start_playing()
        await controller.finish_playback()

        assert len(callback_called) == 1

    @pytest.mark.asyncio
    async def test_on_playback_stopped_callback(self, controller):
        """Test on_playback_stopped callback."""
        callback_called = []

        async def callback():
            callback_called.append(True)

        controller.on_playback_stopped = callback

        await controller.start_generating()
        await controller.start_playing()
        await controller.stop()

        assert len(callback_called) == 1

    @pytest.mark.asyncio
    async def test_callback_exception_handling(self, controller):
        """Test that exceptions in callbacks are handled."""

        async def failing_callback():
            raise RuntimeError("Callback error")

        controller.on_playback_started = failing_callback

        # Should not raise exception
        await controller.start_generating()
        await controller.start_playing()

        assert controller.state == PlaybackState.PLAYING


class TestPlaybackPosition:
    """Test playback position tracking."""

    def test_position_initialization(self):
        """Test PlaybackPosition initialization."""
        pos = PlaybackPosition()
        assert pos.audio_bytes_played == 0
        assert pos.total_audio_bytes == 0
        assert pos.percentage_complete == 0.0

    def test_update_progress(self):
        """Test updating playback progress."""
        pos = PlaybackPosition()
        pos.update_progress(bytes_played=500, total_bytes=1000)

        assert pos.audio_bytes_played == 500
        assert pos.total_audio_bytes == 1000
        assert pos.percentage_complete == 50.0

    def test_progress_at_start(self):
        """Test progress at start of playback."""
        pos = PlaybackPosition()
        pos.update_progress(bytes_played=0, total_bytes=1000)

        assert pos.percentage_complete == 0.0

    def test_progress_at_end(self):
        """Test progress at end of playback."""
        pos = PlaybackPosition()
        pos.update_progress(bytes_played=1000, total_bytes=1000)

        assert pos.percentage_complete == 100.0

    @pytest.mark.asyncio
    async def test_elapsed_ms(self):
        """Test elapsed time calculation."""
        pos = PlaybackPosition()
        pos.started_at = datetime.utcnow()

        await asyncio.sleep(0.1)  # 100ms

        elapsed = pos.elapsed_ms()
        assert elapsed >= 90  # Allow some tolerance


class TestPlaybackMetrics:
    """Test metrics collection."""

    @pytest.mark.asyncio
    async def test_metrics_idle(self, controller):
        """Test metrics in IDLE state."""
        metrics = controller.get_metrics()

        assert metrics["state"] == "idle"
        assert metrics["total_audio_played_bytes"] == 0
        assert metrics["interruption_count"] == 0
        assert metrics["pause_count"] == 0
        assert metrics["error_count"] == 0

    @pytest.mark.asyncio
    async def test_metrics_after_playback(self, controller):
        """Test metrics after playback."""
        await controller.start_generating()
        await controller.start_playing()

        # Simulate playback progress
        await controller.update_playback_position(500, 1000)
        await controller.stop()

        metrics = controller.get_metrics()

        assert metrics["state"] == "stopped"
        assert metrics["total_audio_played_bytes"] == 500
        assert metrics["position_percentage"] == 50.0
        assert metrics["interruption_count"] == 1

    @pytest.mark.asyncio
    async def test_metrics_paused(self, controller):
        """Test metrics in PAUSED state."""
        await controller.start_generating()
        await controller.start_playing()
        await controller.pause()

        metrics = controller.get_metrics()

        assert metrics["state"] == "paused"


class TestPlaybackDuration:
    """Test playback duration tracking."""

    @pytest.mark.asyncio
    async def test_duration_calculation(self, controller):
        """Test elapsed playback duration."""
        await controller.start_generating()
        await controller.start_playing()

        await asyncio.sleep(0.1)  # 100ms

        duration = controller.get_playback_duration_ms()
        assert duration >= 90  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_duration_after_stop(self, controller):
        """Test duration is recorded when stopped."""
        await controller.start_generating()
        await controller.start_playing()

        await asyncio.sleep(0.05)  # 50ms

        await controller.stop()
        duration = controller.get_playback_duration_ms()

        assert duration >= 40


class TestPlaybackStateChecks:
    """Test playback state checking methods."""

    @pytest.mark.asyncio
    async def test_is_playing(self, controller):
        """Test is_playing check."""
        assert not controller.is_playing()

        await controller.start_generating()
        assert not controller.is_playing()

        await controller.start_playing()
        assert controller.is_playing()

    @pytest.mark.asyncio
    async def test_is_paused(self, controller):
        """Test is_paused check."""
        assert not controller.is_paused()

        await controller.start_generating()
        await controller.start_playing()
        await controller.pause()

        assert controller.is_paused()

    @pytest.mark.asyncio
    async def test_is_stopped(self, controller):
        """Test is_stopped check."""
        assert not controller.is_stopped()

        await controller.start_generating()
        await controller.start_playing()
        await controller.stop()

        assert controller.is_stopped()

    @pytest.mark.asyncio
    async def test_can_resume(self, controller):
        """Test can_resume check."""
        assert not controller.can_resume()

        await controller.start_generating()
        await controller.start_playing()
        await controller.pause()

        assert controller.can_resume()


class TestPlaybackErrorHandling:
    """Test error state handling."""

    @pytest.mark.asyncio
    async def test_mark_error(self, controller):
        """Test marking playback as errored."""
        await controller.start_playing()
        await controller.mark_error("Playback error")

        assert controller.state == PlaybackState.ERROR
        assert controller.error_count == 1

    @pytest.mark.asyncio
    async def test_cannot_stop_from_error(self, controller):
        """Test that stop from ERROR state is rejected."""
        await controller.start_playing()
        await controller.mark_error("Playback error")

        result = await controller.stop()
        assert result is False


class TestPlaybackInterruptionHandler:
    """Test playback interruption handling."""

    @pytest.mark.asyncio
    async def test_interrupt_playback(self, controller, interruption_handler):
        """Test interrupting playback."""
        await controller.start_generating()
        await controller.start_playing()

        result = await interruption_handler.interrupt_playback()

        assert result is True
        assert controller.is_stopped()
        assert interruption_handler.interruption_latency_ms >= 0

    @pytest.mark.asyncio
    async def test_interrupt_when_not_playing(self, interruption_handler):
        """Test interruption when not playing."""
        result = await interruption_handler.interrupt_playback()
        assert result is False

    @pytest.mark.asyncio
    async def test_interruption_latency_tracking(self, controller, interruption_handler):
        """Test that interruption latency is recorded."""
        await controller.start_generating()
        await controller.start_playing()

        await asyncio.sleep(0.05)  # 50ms

        await interruption_handler.interrupt_playback()

        assert interruption_handler.interruption_latency_ms >= 40
        assert interruption_handler.interruption_latency_ms <= interruption_handler.max_latency_ms + 10

    @pytest.mark.asyncio
    async def test_interruption_stats(self, controller, interruption_handler):
        """Test interruption statistics."""
        await controller.start_generating()
        await controller.start_playing()
        await interruption_handler.interrupt_playback()

        stats = interruption_handler.get_interruption_stats()

        assert stats["controller_state"] == "stopped"
        assert stats["total_interruptions"] == 1
        assert "within_budget" in stats

    @pytest.mark.asyncio
    async def test_cleanup(self, interruption_handler):
        """Test cleanup after interruption."""
        # Should not raise exception
        await interruption_handler.cleanup()
