"""VAD (Voice Activity Detection) management and tuning.

Handles:
- Per-user VAD sensitivity configuration
- Dynamic VAD thresholds based on context
- Confidence-based filtering
- Metrics collection for optimization
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VADConfig:
    """Voice Activity Detection configuration per user."""

    user_id: str

    # Sensitivity levels (0.1-1.0)
    # Lower = more sensitive (more false positives)
    # Higher = less sensitive (more false negatives)
    sensitivity: float = 0.5  # 0.1-1.0

    # Threshold for speech start detection (0.1-1.0 confidence)
    speech_start_threshold: float = 0.2

    # Threshold for speech end detection (0.1-1.0 confidence)
    speech_end_threshold: float = 0.8

    # Silence timeout before asking confirmation (ms)
    silence_timeout_confirmation_ms: int = 2500  # 2.5 seconds

    # Silence timeout before assuming "no" (ms)
    silence_timeout_decision_ms: int = 5000  # 5 seconds

    # Silence timeout before hanging up (ms)
    silence_timeout_hangup_ms: int = 10000  # 10 seconds

    # Minimum speech duration to count as valid input (ms)
    min_speech_duration_ms: int = 300  # 300ms minimum

    # Maximum speech duration before auto-confirm (ms)
    max_speech_duration_ms: int = 60000  # 60 seconds max


@dataclass
class VADMetrics:
    """Metrics for VAD tuning and optimization."""

    user_id: str
    run_id: str

    # Detection counts
    speech_starts_detected: int = 0
    speech_ends_detected: int = 0
    false_positives: int = 0  # Noise detected as speech
    false_negatives: int = 0  # Speech not detected

    # Confidence tracking
    avg_speech_start_confidence: float = 0.0
    avg_speech_end_confidence: float = 0.0

    # Duration tracking
    total_speech_duration_ms: int = 0
    total_silence_duration_ms: int = 0

    # Collected at
    collected_at: datetime = field(default_factory=datetime.utcnow)


class VADManager:
    """Manages VAD configuration and optimization per user.

    Responsibilities:
    - Load/save VAD config per user
    - Track metrics for model optimization
    - Provide dynamic threshold adjustment
    """

    def __init__(
        self,
        supabase_client=None,
        run_id: str = "",
    ):
        """Initialize VAD manager.

        Args:
            supabase_client: Supabase async client (optional)
            run_id: Call identifier
        """
        self.supabase = supabase_client
        self.run_id = run_id
        self.configs: dict[str, VADConfig] = {}  # Cache per user
        self.metrics: dict[str, VADMetrics] = {}  # Current run metrics

    async def load_config(self, user_id: str) -> VADConfig:
        """Load VAD config for user from database.

        Falls back to defaults if not found.

        Args:
            user_id: User UUID

        Returns:
            VADConfig (from DB or defaults)
        """
        # Check cache
        if user_id in self.configs:
            return self.configs[user_id]

        # Load from database if available
        if self.supabase:
            try:
                response = await self.supabase.table(
                    "user_preferences"
                ).select("*").eq("user_id", str(user_id)).execute()

                if response.data and len(response.data) > 0:
                    prefs = response.data[0]
                    config = VADConfig(
                        user_id=user_id,
                        sensitivity=prefs.get("vad_sensitivity", 0.5),
                        speech_start_threshold=prefs.get(
                            "speech_start_threshold", 0.2
                        ),
                        speech_end_threshold=prefs.get("speech_end_threshold", 0.8),
                        silence_timeout_confirmation_ms=prefs.get(
                            "silence_timeout_ms", 2500
                        ),
                        silence_timeout_decision_ms=prefs.get(
                            "confirmation_timeout_ms", 5000
                        ),
                    )
                    self.configs[user_id] = config
                    logger.info(f"Loaded VAD config for user {user_id}")
                    return config
            except Exception as e:
                logger.warning(f"Failed to load VAD config from DB: {e}")

        # Return defaults
        config = VADConfig(user_id=user_id)
        self.configs[user_id] = config
        logger.debug(f"Using default VAD config for user {user_id}")
        return config

    async def save_config(self, config: VADConfig) -> bool:
        """Save VAD config to database.

        Args:
            config: VADConfig to save

        Returns:
            True if saved, False if error
        """
        if not self.supabase:
            logger.warning("Supabase not available, cannot save config")
            return False

        try:
            await self.supabase.table("user_preferences").update({
                "vad_sensitivity": config.sensitivity,
                "speech_start_threshold": config.speech_start_threshold,
                "speech_end_threshold": config.speech_end_threshold,
                "silence_timeout_ms": config.silence_timeout_confirmation_ms,
                "confirmation_timeout_ms": config.silence_timeout_decision_ms,
            }).eq("user_id", str(config.user_id)).execute()

            self.configs[config.user_id] = config
            logger.info(f"Saved VAD config for user {config.user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save VAD config: {e}")
            return False

    def get_config(self, user_id: str) -> VADConfig:
        """Get cached config without DB lookup.

        Args:
            user_id: User UUID

        Returns:
            VADConfig from cache (or defaults if not loaded)
        """
        return self.configs.get(user_id, VADConfig(user_id=user_id))

    def should_trigger_speech_start(
        self,
        vad_state: str,
        confidence: float,
        config: Optional[VADConfig] = None,
    ) -> bool:
        """Check if VAD event should trigger speech start.

        Args:
            vad_state: "speaking" or "idle"
            confidence: Confidence 0.0-1.0
            config: VADConfig (uses default if not provided)

        Returns:
            True if event should trigger speech start
        """
        if config is None:
            config = VADConfig()

        if vad_state != "speaking":
            return False

        # Apply sensitivity adjustment
        # Lower sensitivity → lower effective threshold (more sensitive)
        # Higher sensitivity → higher effective threshold (less sensitive)
        # At sensitivity=0.5 (default), threshold equals speech_start_threshold
        adjusted_threshold = config.speech_start_threshold * config.sensitivity * 2
        adjusted_threshold = min(1.0, max(0.0, adjusted_threshold))

        return confidence >= adjusted_threshold

    def should_trigger_speech_end(
        self,
        vad_state: str,
        confidence: float,
        config: Optional[VADConfig] = None,
    ) -> bool:
        """Check if VAD event should trigger speech end.

        Args:
            vad_state: "speaking" or "idle"
            confidence: Confidence 0.0-1.0
            config: VADConfig (uses default if not provided)

        Returns:
            True if event should trigger speech end
        """
        if config is None:
            config = VADConfig()

        if vad_state != "idle":
            return False

        # Apply sensitivity adjustment
        # At sensitivity=0.5 (default), threshold equals speech_end_threshold
        # Lower sensitivity → higher threshold (need more confidence that speech ended)
        adjusted_threshold = config.speech_end_threshold / (config.sensitivity * 2)
        adjusted_threshold = min(1.0, max(0.0, adjusted_threshold))

        return confidence >= adjusted_threshold

    def update_metrics(
        self,
        user_id: str,
        event_type: str,
        confidence: float = 0.0,
    ):
        """Update VAD metrics for user.

        Args:
            user_id: User UUID
            event_type: "speech_start", "speech_end", "false_positive"
            confidence: Confidence level (0.0-1.0)
        """
        if user_id not in self.metrics:
            self.metrics[user_id] = VADMetrics(
                user_id=user_id,
                run_id=self.run_id,
            )

        metrics = self.metrics[user_id]

        if event_type == "speech_start":
            metrics.speech_starts_detected += 1
            # Update average confidence
            old_avg = metrics.avg_speech_start_confidence
            n = metrics.speech_starts_detected
            metrics.avg_speech_start_confidence = (
                (old_avg * (n - 1)) + confidence
            ) / n

        elif event_type == "speech_end":
            metrics.speech_ends_detected += 1
            old_avg = metrics.avg_speech_end_confidence
            n = metrics.speech_ends_detected
            metrics.avg_speech_end_confidence = (
                (old_avg * (n - 1)) + confidence
            ) / n

        elif event_type == "false_positive":
            metrics.false_positives += 1

        elif event_type == "false_negative":
            metrics.false_negatives += 1

    def get_metrics(self, user_id: str) -> Optional[VADMetrics]:
        """Get collected metrics for user.

        Args:
            user_id: User UUID

        Returns:
            VADMetrics if available, None otherwise
        """
        return self.metrics.get(user_id)

    async def save_metrics(self, metrics: VADMetrics) -> bool:
        """Save metrics to database for analysis.

        Args:
            metrics: VADMetrics to save

        Returns:
            True if saved, False if error
        """
        if not self.supabase:
            logger.warning("Supabase not available, cannot save metrics")
            return False

        try:
            await self.supabase.table("vad_metrics").insert({
                "user_id": str(metrics.user_id),
                "run_id": metrics.run_id,
                "speech_starts_detected": metrics.speech_starts_detected,
                "speech_ends_detected": metrics.speech_ends_detected,
                "false_positives": metrics.false_positives,
                "false_negatives": metrics.false_negatives,
                "avg_speech_start_confidence": metrics.avg_speech_start_confidence,
                "avg_speech_end_confidence": metrics.avg_speech_end_confidence,
                "total_speech_duration_ms": metrics.total_speech_duration_ms,
                "total_silence_duration_ms": metrics.total_silence_duration_ms,
            }).execute()

            logger.info(
                f"Saved VAD metrics for user {metrics.user_id} "
                f"(starts={metrics.speech_starts_detected}, "
                f"ends={metrics.speech_ends_detected}, "
                f"false_positives={metrics.false_positives})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save VAD metrics: {e}")
            return False

    def get_stats(self) -> dict:
        """Get aggregate VAD manager statistics."""
        total_starts = sum(m.speech_starts_detected for m in self.metrics.values())
        total_ends = sum(m.speech_ends_detected for m in self.metrics.values())
        total_false_positives = sum(m.false_positives for m in self.metrics.values())

        return {
            "configs_loaded": len(self.configs),
            "runs_tracked": len(self.metrics),
            "total_speech_starts": total_starts,
            "total_speech_ends": total_ends,
            "total_false_positives": total_false_positives,
        }
