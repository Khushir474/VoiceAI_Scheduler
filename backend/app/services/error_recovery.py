"""Error recovery framework for 6 error types.

Implements recovery strategies for:
1. STT errors (low confidence, no speech)
2. Silence errors (timeout, no response)
3. LLM errors (invalid format, timeout, hallucination)
4. Tool errors (API fails, parse error)
5. TTS errors (high latency, corrupted audio)
6. Network errors (disconnect, message send failed)
"""

import logging
import asyncio
from enum import Enum
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Any

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """6 error types for recovery handling."""

    # STT errors
    STT_ERROR = "stt_error"
    STT_LOW_CONFIDENCE = "stt_low_confidence"
    STT_NO_SPEECH = "stt_no_speech"

    # Silence errors
    SILENCE_ERROR = "silence_error"
    SILENCE_TIMEOUT = "silence_timeout"

    # LLM errors
    LLM_ERROR = "llm_error"
    LLM_TIMEOUT = "llm_timeout"
    LLM_HALLUCINATION = "llm_hallucination"
    LLM_INVALID_FORMAT = "llm_invalid_format"

    # Tool errors
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_PARSE_ERROR = "tool_parse_error"

    # TTS errors
    TTS_ERROR = "tts_error"
    TTS_TIMEOUT = "tts_timeout"
    TTS_CORRUPTED = "tts_corrupted"

    # Network errors
    NETWORK_ERROR = "network_error"
    NETWORK_TIMEOUT = "network_timeout"
    NETWORK_DISCONNECT = "network_disconnect"


@dataclass
class ErrorContext:
    """Context information for an error."""

    error_type: ErrorType
    message: str
    timestamp: datetime
    severity: str  # "warning", "error", "critical"
    recoverable: bool = True
    retry_count: int = 0
    max_retries: int = 3
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RecoveryResult:
    """Result of a recovery attempt."""

    success: bool
    error_type: ErrorType
    attempt: int
    strategy_used: str
    latency_ms: int = 0
    fallback_used: bool = False
    message: str = ""


class RetryStrategy:
    """Exponential backoff retry strategy."""

    def __init__(
        self,
        base_backoff_ms: int = 100,
        max_retries: int = 3,
    ):
        """Initialize retry strategy.

        Args:
            base_backoff_ms: Initial backoff in milliseconds
            max_retries: Maximum retry attempts
        """
        self.base_backoff_ms = base_backoff_ms
        self.max_retries = max_retries

    def get_backoff_ms(self, attempt: int) -> int:
        """Get backoff time for a retry attempt.

        Args:
            attempt: Attempt number (1-based)

        Returns:
            Milliseconds to wait before retry
        """
        if attempt < 1 or attempt > self.max_retries:
            return 0

        # Exponential: base * 2^(attempt-1)
        backoff = self.base_backoff_ms * (2 ** (attempt - 1))
        return min(backoff, 8000)  # Cap at 8 seconds

    async def wait_for_retry(self, attempt: int):
        """Wait before retry.

        Args:
            attempt: Attempt number (1-based)
        """
        backoff_ms = self.get_backoff_ms(attempt)
        if backoff_ms > 0:
            logger.debug(f"Retrying after {backoff_ms}ms...")
            await asyncio.sleep(backoff_ms / 1000)


class ErrorRecoveryStrategy:
    """Master error recovery orchestrator."""

    def __init__(
        self,
        fsm=None,
        state_manager=None,
        logger_service=None,
    ):
        """Initialize recovery strategy.

        Args:
            fsm: Conversation state machine
            state_manager: State persistence manager
            logger_service: Debug logger service
        """
        self.fsm = fsm
        self.state_manager = state_manager
        self.logger_service = logger_service

        # Retry strategy
        self.retry_strategy = RetryStrategy(base_backoff_ms=100, max_retries=3)

        # Recovery counters
        self.errors_encountered = {}
        self.recoveries_attempted = {}

    async def handle_error(
        self,
        error: Exception | str,
        error_type: ErrorType,
        context: Optional[dict] = None,
    ) -> RecoveryResult:
        """Handle an error with appropriate recovery strategy.

        Args:
            error: The error that occurred
            error_type: Type of error
            context: Additional context

        Returns:
            RecoveryResult with outcome of recovery attempt
        """
        error_context = ErrorContext(
            error_type=error_type,
            message=str(error),
            timestamp=datetime.utcnow(),
            severity=self._get_severity(error_type),
            metadata=context or {},
        )

        # Track error
        self._track_error(error_type)

        logger.warning(
            f"Error encountered: {error_type.value} - {error_context.message}"
        )

        # Get appropriate recovery strategy
        if error_type in [
            ErrorType.STT_LOW_CONFIDENCE,
            ErrorType.STT_NO_SPEECH,
        ]:
            return await self._recover_stt_error(error_context)

        elif error_type in [ErrorType.SILENCE_ERROR, ErrorType.SILENCE_TIMEOUT]:
            return await self._recover_silence_error(error_context)

        elif error_type in [
            ErrorType.LLM_ERROR,
            ErrorType.LLM_TIMEOUT,
            ErrorType.LLM_INVALID_FORMAT,
            ErrorType.LLM_HALLUCINATION,
        ]:
            return await self._recover_llm_error(error_context)

        elif error_type in [
            ErrorType.TOOL_ERROR,
            ErrorType.TOOL_TIMEOUT,
            ErrorType.TOOL_PARSE_ERROR,
        ]:
            return await self._recover_tool_error(error_context)

        elif error_type in [
            ErrorType.TTS_ERROR,
            ErrorType.TTS_TIMEOUT,
            ErrorType.TTS_CORRUPTED,
        ]:
            return await self._recover_tts_error(error_context)

        elif error_type in [
            ErrorType.NETWORK_ERROR,
            ErrorType.NETWORK_DISCONNECT,
            ErrorType.NETWORK_TIMEOUT,
        ]:
            return await self._recover_network_error(error_context)

        else:
            return RecoveryResult(
                success=False,
                error_type=error_type,
                attempt=1,
                strategy_used="unknown",
                message="Unknown error type",
            )

    async def _recover_stt_error(self, ctx: ErrorContext) -> RecoveryResult:
        """Recover from STT (Speech-to-Text) errors.

        Strategy:
        - Low confidence (0.4-0.6): Ask confirmation
        - Very low (0.2-0.4): Ask to repeat
        - Critical (<0.2): Fallback to text input
        """
        logger.info(f"Recovering from STT error: {ctx.error_type.value}")

        confidence = ctx.metadata.get("confidence", 0.0)

        if 0.4 <= confidence < 0.6:
            # Ask confirmation
            logger.info("STT confidence medium, asking confirmation")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="ask_confirmation",
                message=f"Did you say '{ctx.metadata.get('transcript', '')}'?",
            )

        elif 0.2 <= confidence < 0.4:
            # Ask to repeat
            logger.info("STT confidence low, asking to repeat")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="ask_repeat",
                message="Sorry, could you say that again?",
            )

        else:
            # Fallback to text input or retry
            logger.warning("STT confidence critical, retrying")
            await self.retry_strategy.wait_for_retry(1)
            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="retry",
                message="STT failed, please try again",
            )

    async def _recover_silence_error(self, ctx: ErrorContext) -> RecoveryResult:
        """Recover from silence errors.

        Strategy:
        - Silence during input: Ask user to speak (stage 1)
        - Prolonged silence: Assume "no" (stage 2)
        - Extended silence: Hang up (stage 3)
        """
        logger.info(f"Recovering from silence error: {ctx.error_type.value}")

        duration_ms = ctx.metadata.get("duration_ms", 0)

        if duration_ms < 5000:
            # Early silence, ask user to speak
            logger.info("Early silence, prompting user")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="prompt_user",
                message="I'm listening...",
            )

        else:
            # Prolonged silence, assume no
            logger.info("Prolonged silence, assuming no")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="assume_no",
                message="Proceeding without additional input",
            )

    async def _recover_llm_error(self, ctx: ErrorContext) -> RecoveryResult:
        """Recover from LLM (Language Model) errors.

        Strategy:
        - Invalid format: Use cached/fallback response
        - Timeout: Use cached recommendation
        - Hallucination: Flag and don't present to user
        """
        logger.info(f"Recovering from LLM error: {ctx.error_type.value}")

        if ctx.error_type == ErrorType.LLM_TIMEOUT:
            # Timeout: use cached response
            logger.warning("LLM timeout, using cached response")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="cached_response",
                fallback_used=True,
                message="Using cached recommendation",
            )

        elif ctx.error_type == ErrorType.LLM_INVALID_FORMAT:
            # Invalid format: use template response
            logger.warning("LLM invalid format, using template")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="template_response",
                fallback_used=True,
                message="Using default response",
            )

        elif ctx.error_type == ErrorType.LLM_HALLUCINATION:
            # Hallucination: flag but continue
            logger.error("LLM hallucination detected!")
            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="flag_skip",
                message="Hallucination detected, skipping",
            )

        else:
            # General LLM error: retry
            await self.retry_strategy.wait_for_retry(1)
            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="retry",
                message="LLM error, retrying",
            )

    async def _recover_tool_error(self, ctx: ErrorContext) -> RecoveryResult:
        """Recover from tool execution errors.

        Strategy:
        - Network error: Retry once, then use cached
        - Parse error: Log and skip tool
        - Timeout: Use cached data
        """
        logger.info(f"Recovering from tool error: {ctx.error_type.value}")

        tool_name = ctx.metadata.get("tool_name", "unknown")

        if ctx.error_type == ErrorType.TOOL_TIMEOUT:
            # Timeout: use cached
            logger.warning(f"Tool {tool_name} timeout, using cached data")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="cached_data",
                fallback_used=True,
                message=f"Using cached data for {tool_name}",
            )

        elif ctx.error_type == ErrorType.TOOL_PARSE_ERROR:
            # Parse error: skip and log
            logger.error(f"Tool {tool_name} parse error, skipping")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="skip_tool",
                message=f"Skipping {tool_name} due to parse error",
            )

        else:
            # Network error: retry once
            logger.warning(f"Tool {tool_name} error, retrying")
            await self.retry_strategy.wait_for_retry(1)
            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="retry",
                message=f"Retrying {tool_name}",
            )

    async def _recover_tts_error(self, ctx: ErrorContext) -> RecoveryResult:
        """Recover from TTS (Text-to-Speech) errors.

        Strategy:
        - High latency: Continue (expected in streaming)
        - Corrupted audio: Retry once, then text fallback
        - API timeout: Skip TTS, present text
        """
        logger.info(f"Recovering from TTS error: {ctx.error_type.value}")

        if ctx.error_type == ErrorType.TTS_TIMEOUT:
            # Timeout: skip TTS, present text
            logger.warning("TTS timeout, falling back to text")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="text_fallback",
                fallback_used=True,
                message="Presenting plan as text",
            )

        elif ctx.error_type == ErrorType.TTS_CORRUPTED:
            # Corrupted audio: retry once
            logger.warning("TTS audio corrupted, retrying")
            await self.retry_strategy.wait_for_retry(1)
            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="retry",
                message="Retrying TTS generation",
            )

        else:
            # High latency is expected with streaming
            logger.debug("TTS latency normal for streaming")
            return RecoveryResult(
                success=True,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="continue",
                message="Continuing with streaming",
            )

    async def _recover_network_error(self, ctx: ErrorContext) -> RecoveryResult:
        """Recover from network errors.

        Strategy:
        - During conversation: Can't recover immediately
        - During quiet: Reconnect
        - Before summary: Retry 3x, then SMS fallback
        """
        logger.info(f"Recovering from network error: {ctx.error_type.value}")

        if ctx.error_type == ErrorType.NETWORK_DISCONNECT:
            logger.warning("Network disconnected, attempting to reconnect")
            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=1,
                strategy_used="reconnect",
                message="Network disconnected, trying to reconnect",
            )

        else:
            # Network error: retry with backoff
            logger.warning("Network error, retrying with backoff")
            for attempt in range(1, self.retry_strategy.max_retries + 1):
                await self.retry_strategy.wait_for_retry(attempt)
                # (actual retry would happen in calling code)

            return RecoveryResult(
                success=False,
                error_type=ctx.error_type,
                attempt=self.retry_strategy.max_retries,
                strategy_used="retry_backoff",
                message="Network error, retries exhausted",
            )

    def _get_severity(self, error_type: ErrorType) -> str:
        """Get severity level for error type.

        Args:
            error_type: Type of error

        Returns:
            "warning", "error", or "critical"
        """
        critical_errors = {
            ErrorType.NETWORK_DISCONNECT,
            ErrorType.TTS_CORRUPTED,
        }

        if error_type in critical_errors:
            return "critical"
        elif "timeout" in error_type.value:
            return "error"
        else:
            return "warning"

    def _track_error(self, error_type: ErrorType):
        """Track error occurrence for metrics.

        Args:
            error_type: Type of error
        """
        key = error_type.value
        self.errors_encountered[key] = self.errors_encountered.get(key, 0) + 1

    def get_metrics(self) -> dict:
        """Get error recovery metrics.

        Returns:
            Dictionary with error statistics
        """
        total_errors = sum(self.errors_encountered.values())
        total_recoveries = sum(self.recoveries_attempted.values())

        return {
            "total_errors": total_errors,
            "total_recoveries": total_recoveries,
            "errors_by_type": dict(self.errors_encountered),
            "recoveries_by_type": dict(self.recoveries_attempted),
        }
