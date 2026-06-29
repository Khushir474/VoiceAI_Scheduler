"""Unit tests for error recovery framework."""

import pytest
import asyncio
from datetime import datetime

from app.services.error_recovery import (
    ErrorRecoveryStrategy,
    ErrorType,
    ErrorContext,
    RecoveryResult,
    RetryStrategy,
)


@pytest.fixture
def recovery_strategy():
    """Create a test error recovery strategy."""
    return ErrorRecoveryStrategy()


@pytest.fixture
def retry_strategy():
    """Create a test retry strategy."""
    return RetryStrategy(base_backoff_ms=100, max_retries=3)


class TestRetryStrategy:
    """Test retry strategy with exponential backoff."""

    def test_backoff_calculation(self, retry_strategy):
        """Test exponential backoff calculation."""
        # Attempt 1: 100ms
        assert retry_strategy.get_backoff_ms(1) == 100

        # Attempt 2: 200ms (100 * 2^1)
        assert retry_strategy.get_backoff_ms(2) == 200

        # Attempt 3: 400ms (100 * 2^2)
        assert retry_strategy.get_backoff_ms(3) == 400

    def test_backoff_cap(self, retry_strategy):
        """Test that backoff is capped at 8 seconds."""
        # Very high attempt should be capped
        assert retry_strategy.get_backoff_ms(10) <= 8000

    def test_invalid_attempt(self, retry_strategy):
        """Test invalid attempt numbers."""
        assert retry_strategy.get_backoff_ms(0) == 0
        assert retry_strategy.get_backoff_ms(10) <= 8000

    @pytest.mark.asyncio
    async def test_wait_for_retry(self, retry_strategy):
        """Test waiting for retry."""
        import time

        start = time.time()
        await retry_strategy.wait_for_retry(1)  # 100ms
        elapsed = time.time() - start

        assert elapsed >= 0.09  # Allow some tolerance


class TestErrorContext:
    """Test error context."""

    def test_error_context_creation(self):
        """Test creating error context."""
        ctx = ErrorContext(
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            message="Low confidence STT",
            timestamp=datetime.utcnow(),
            severity="warning",
        )

        assert ctx.error_type == ErrorType.STT_LOW_CONFIDENCE
        assert ctx.severity == "warning"
        assert ctx.recoverable is True

    def test_error_context_metadata(self):
        """Test error context with metadata."""
        ctx = ErrorContext(
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            message="Test",
            timestamp=datetime.utcnow(),
            severity="warning",
            metadata={"confidence": 0.45, "transcript": "hello"},
        )

        assert ctx.metadata["confidence"] == 0.45
        assert ctx.metadata["transcript"] == "hello"


class TestSTTErrorRecovery:
    """Test STT error recovery."""

    @pytest.mark.asyncio
    async def test_medium_confidence_recovery(self, recovery_strategy):
        """Test medium confidence STT asks for confirmation."""
        result = await recovery_strategy.handle_error(
            error="Low confidence",
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            context={"confidence": 0.50, "transcript": "hello"},
        )

        assert result.success is True
        assert result.strategy_used == "ask_confirmation"
        assert "Did you say" in result.message

    @pytest.mark.asyncio
    async def test_low_confidence_recovery(self, recovery_strategy):
        """Test very low confidence asks user to repeat."""
        result = await recovery_strategy.handle_error(
            error="Very low confidence",
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            context={"confidence": 0.30},
        )

        assert result.success is True
        assert result.strategy_used == "ask_repeat"
        assert "say that again" in result.message.lower()

    @pytest.mark.asyncio
    async def test_critical_stt_confidence(self, recovery_strategy):
        """Test critical STT confidence triggers retry."""
        result = await recovery_strategy.handle_error(
            error="Critical confidence",
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            context={"confidence": 0.15},
        )

        assert result.success is False
        assert result.strategy_used == "retry"


class TestSilenceErrorRecovery:
    """Test silence error recovery."""

    @pytest.mark.asyncio
    async def test_early_silence_recovery(self, recovery_strategy):
        """Test early silence prompts user."""
        result = await recovery_strategy.handle_error(
            error="User silent",
            error_type=ErrorType.SILENCE_ERROR,
            context={"duration_ms": 2000},
        )

        assert result.success is True
        assert result.strategy_used == "prompt_user"

    @pytest.mark.asyncio
    async def test_prolonged_silence_recovery(self, recovery_strategy):
        """Test prolonged silence assumes no."""
        result = await recovery_strategy.handle_error(
            error="Extended silence",
            error_type=ErrorType.SILENCE_TIMEOUT,
            context={"duration_ms": 6000},
        )

        assert result.success is True
        assert result.strategy_used == "assume_no"


class TestLLMErrorRecovery:
    """Test LLM error recovery."""

    @pytest.mark.asyncio
    async def test_llm_timeout_recovery(self, recovery_strategy):
        """Test LLM timeout uses cached response."""
        result = await recovery_strategy.handle_error(
            error="LLM timeout",
            error_type=ErrorType.LLM_TIMEOUT,
            context={},
        )

        assert result.success is True
        assert result.strategy_used == "cached_response"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_llm_invalid_format_recovery(self, recovery_strategy):
        """Test LLM invalid format uses template."""
        result = await recovery_strategy.handle_error(
            error="Invalid format",
            error_type=ErrorType.LLM_INVALID_FORMAT,
            context={},
        )

        assert result.success is True
        assert result.strategy_used == "template_response"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_llm_hallucination_recovery(self, recovery_strategy):
        """Test LLM hallucination is flagged."""
        result = await recovery_strategy.handle_error(
            error="Hallucination detected",
            error_type=ErrorType.LLM_HALLUCINATION,
            context={},
        )

        assert result.success is False
        assert result.strategy_used == "flag_skip"


class TestToolErrorRecovery:
    """Test tool execution error recovery."""

    @pytest.mark.asyncio
    async def test_tool_timeout_recovery(self, recovery_strategy):
        """Test tool timeout uses cached data."""
        result = await recovery_strategy.handle_error(
            error="Tool timeout",
            error_type=ErrorType.TOOL_TIMEOUT,
            context={"tool_name": "weather"},
        )

        assert result.success is True
        assert result.strategy_used == "cached_data"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_tool_parse_error_recovery(self, recovery_strategy):
        """Test tool parse error skips tool."""
        result = await recovery_strategy.handle_error(
            error="Parse error",
            error_type=ErrorType.TOOL_PARSE_ERROR,
            context={"tool_name": "calendar"},
        )

        assert result.success is True
        assert result.strategy_used == "skip_tool"


class TestTTSErrorRecovery:
    """Test TTS error recovery."""

    @pytest.mark.asyncio
    async def test_tts_timeout_recovery(self, recovery_strategy):
        """Test TTS timeout falls back to text."""
        result = await recovery_strategy.handle_error(
            error="TTS timeout",
            error_type=ErrorType.TTS_TIMEOUT,
            context={},
        )

        assert result.success is True
        assert result.strategy_used == "text_fallback"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_tts_corrupted_recovery(self, recovery_strategy):
        """Test corrupted TTS audio triggers retry."""
        result = await recovery_strategy.handle_error(
            error="Corrupted audio",
            error_type=ErrorType.TTS_CORRUPTED,
            context={},
        )

        assert result.success is False
        assert result.strategy_used == "retry"


class TestNetworkErrorRecovery:
    """Test network error recovery."""

    @pytest.mark.asyncio
    async def test_network_disconnect_recovery(self, recovery_strategy):
        """Test network disconnect triggers reconnect."""
        result = await recovery_strategy.handle_error(
            error="Network disconnect",
            error_type=ErrorType.NETWORK_DISCONNECT,
            context={},
        )

        assert result.success is False
        assert result.strategy_used == "reconnect"

    @pytest.mark.asyncio
    async def test_network_timeout_recovery(self, recovery_strategy):
        """Test network timeout retries with backoff."""
        result = await recovery_strategy.handle_error(
            error="Network timeout",
            error_type=ErrorType.NETWORK_TIMEOUT,
            context={},
        )

        assert result.success is False
        assert result.strategy_used == "retry_backoff"


class TestErrorMetrics:
    """Test error tracking and metrics."""

    @pytest.mark.asyncio
    async def test_error_tracking(self, recovery_strategy):
        """Test that errors are tracked."""
        await recovery_strategy.handle_error(
            error="Test error",
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            context={},
        )

        assert ErrorType.STT_LOW_CONFIDENCE.value in recovery_strategy.errors_encountered

    @pytest.mark.asyncio
    async def test_multiple_error_tracking(self, recovery_strategy):
        """Test tracking multiple error types."""
        await recovery_strategy.handle_error(
            error="STT error",
            error_type=ErrorType.STT_LOW_CONFIDENCE,
            context={},
        )
        await recovery_strategy.handle_error(
            error="Silence error",
            error_type=ErrorType.SILENCE_ERROR,
            context={},
        )

        metrics = recovery_strategy.get_metrics()
        assert metrics["total_errors"] == 2
        assert len(metrics["errors_by_type"]) >= 2

    def test_error_severity(self, recovery_strategy):
        """Test error severity classification."""
        # Critical errors
        assert recovery_strategy._get_severity(
            ErrorType.NETWORK_DISCONNECT
        ) == "critical"

        # Error level
        assert recovery_strategy._get_severity(ErrorType.LLM_TIMEOUT) == "error"

        # Warning level
        assert recovery_strategy._get_severity(ErrorType.STT_LOW_CONFIDENCE) == "warning"
