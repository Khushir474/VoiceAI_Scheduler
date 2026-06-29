"""Comprehensive metrics collection for observability.

Collects metrics across all Phase 2 components:
- State machine transitions
- Error recovery attempts
- VAD performance
- Streaming TTS latency
- Barge-in events
- Call summary
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class MetricCategory(str, Enum):
    """Categories of metrics."""

    STATE_MACHINE = "state_machine"
    ERROR_RECOVERY = "error_recovery"
    VAD = "vad"
    STREAMING_TTS = "streaming_tts"
    BARGE_IN = "barge_in"
    PLAYBACK = "playback"
    ENDPOINTING = "endpointing"
    CALL_SUMMARY = "call_summary"


@dataclass
class StateTransitionMetric:
    """Metric for FSM state transition."""

    from_state: str
    to_state: str
    trigger: str
    latency_ms: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ErrorRecoveryMetric:
    """Metric for error recovery."""

    error_type: str
    attempt: int
    strategy: str
    success: bool
    latency_ms: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class VADMetric:
    """Metric for VAD performance."""

    sensitivity: float
    speech_starts: int
    speech_ends: int
    false_positives: int
    false_negatives: int
    avg_confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StreamingTTSMetric:
    """Metric for streaming TTS performance."""

    text_chars: int
    audio_bytes: int
    time_to_first_audio_ms: int
    total_elapsed_ms: int
    chunks_generated: int
    underrun_count: int
    overflow_count: int
    generation_errors: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BargeInMetric:
    """Metric for barge-in detection."""

    barge_in_count: int
    avg_confidence: float
    latency_ms: int
    state_transition_success: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PlaybackMetric:
    """Metric for playback control."""

    total_audio_bytes: int
    position_percentage: float
    interruption_count: int
    pause_count: int
    error_count: int
    elapsed_ms: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EndpointingMetric:
    """Metric for endpointing and silence."""

    endpointing_count: int
    stage_1_timeouts: int
    stage_2_timeouts: int
    stage_3_timeouts: int
    current_silence_ms: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CallSummary:
    """Summary of entire call."""

    run_id: str
    user_id: str
    start_time: datetime
    end_time: Optional[datetime] = None

    # Timing
    total_duration_ms: int = 0
    time_to_first_audio_ms: Optional[int] = None

    # Interaction counts
    state_transitions: int = 0
    error_count: int = 0
    error_recoveries: int = 0
    barge_in_count: int = 0
    silence_timeouts: int = 0

    # Quality metrics
    final_state: str = "unknown"
    success: bool = False
    errors_encountered: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Call metadata
    call_type: str = "voice_planning"  # Type of call
    language: str = "en-US"
    llm_tokens_used: int = 0
    api_calls_made: int = 0


class MetricsCollector:
    """Central metrics collection service.

    Responsibilities:
    - Collect metrics across all components
    - Aggregate and summarize
    - Export to observability systems
    - Track call-level KPIs
    """

    def __init__(self, run_id: str = "", user_id: str = ""):
        """Initialize metrics collector.

        Args:
            run_id: Call identifier
            user_id: User UUID
        """
        self.run_id = run_id
        self.user_id = user_id

        # Metrics collections
        self.state_transitions: list[StateTransitionMetric] = []
        self.error_recoveries: list[ErrorRecoveryMetric] = []
        self.vad_metrics: list[VADMetric] = []
        self.tts_metrics: list[StreamingTTSMetric] = []
        self.barge_in_metrics: list[BargeInMetric] = []
        self.playback_metrics: list[PlaybackMetric] = []
        self.endpointing_metrics: list[EndpointingMetric] = []

        # Call summary
        self.call_summary = CallSummary(
            run_id=run_id,
            user_id=user_id,
            start_time=datetime.utcnow(),
        )

    def record_state_transition(
        self,
        from_state: str,
        to_state: str,
        trigger: str,
        latency_ms: int,
    ):
        """Record a state machine transition.

        Args:
            from_state: Source state
            to_state: Destination state
            trigger: Trigger that caused transition
            latency_ms: Latency of state in milliseconds
        """
        metric = StateTransitionMetric(
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            latency_ms=latency_ms,
        )
        self.state_transitions.append(metric)
        self.call_summary.state_transitions += 1

        logger.debug(
            f"Recorded state transition: {from_state} → {to_state} "
            f"({latency_ms}ms)"
        )

    def record_error_recovery(
        self,
        error_type: str,
        attempt: int,
        strategy: str,
        success: bool,
        latency_ms: int,
    ):
        """Record an error recovery attempt.

        Args:
            error_type: Type of error
            attempt: Attempt number
            strategy: Recovery strategy used
            success: Whether recovery succeeded
            latency_ms: Recovery latency
        """
        metric = ErrorRecoveryMetric(
            error_type=error_type,
            attempt=attempt,
            strategy=strategy,
            success=success,
            latency_ms=latency_ms,
        )
        self.error_recoveries.append(metric)
        self.call_summary.error_count += 1
        if success:
            self.call_summary.error_recoveries += 1

        logger.info(
            f"Recorded error recovery: {error_type} (attempt {attempt}, "
            f"strategy: {strategy}, success: {success})"
        )

    def record_vad_metrics(
        self,
        sensitivity: float,
        speech_starts: int,
        speech_ends: int,
        false_positives: int,
        false_negatives: int,
        avg_confidence: float,
    ):
        """Record VAD performance metrics.

        Args:
            sensitivity: VAD sensitivity (0.1-1.0)
            speech_starts: Count of speech onsets
            speech_ends: Count of speech offsets
            false_positives: Count of false positives
            false_negatives: Count of false negatives
            avg_confidence: Average VAD confidence
        """
        metric = VADMetric(
            sensitivity=sensitivity,
            speech_starts=speech_starts,
            speech_ends=speech_ends,
            false_positives=false_positives,
            false_negatives=false_negatives,
            avg_confidence=avg_confidence,
        )
        self.vad_metrics.append(metric)

        logger.debug(
            f"Recorded VAD metrics: sensitivity={sensitivity}, "
            f"starts={speech_starts}, false_pos={false_positives}"
        )

    def record_streaming_tts(
        self,
        text_chars: int,
        audio_bytes: int,
        time_to_first_audio_ms: int,
        total_elapsed_ms: int,
        chunks_generated: int,
        underrun_count: int,
        overflow_count: int,
        generation_errors: int,
    ):
        """Record streaming TTS metrics.

        Args:
            text_chars: Total text characters
            audio_bytes: Total audio bytes generated
            time_to_first_audio_ms: Latency to first audio
            total_elapsed_ms: Total operation time
            chunks_generated: Number of audio chunks
            underrun_count: Buffer underrun events
            overflow_count: Buffer overflow events
            generation_errors: TTS generation errors
        """
        metric = StreamingTTSMetric(
            text_chars=text_chars,
            audio_bytes=audio_bytes,
            time_to_first_audio_ms=time_to_first_audio_ms,
            total_elapsed_ms=total_elapsed_ms,
            chunks_generated=chunks_generated,
            underrun_count=underrun_count,
            overflow_count=overflow_count,
            generation_errors=generation_errors,
        )
        self.tts_metrics.append(metric)
        self.call_summary.time_to_first_audio_ms = time_to_first_audio_ms

        logger.info(
            f"Recorded TTS metrics: ttfa={time_to_first_audio_ms}ms, "
            f"chunks={chunks_generated}, errors={generation_errors}"
        )

    def record_barge_in(
        self,
        barge_in_count: int,
        avg_confidence: float,
        latency_ms: int,
        state_transition_success: bool,
    ):
        """Record barge-in detection metrics.

        Args:
            barge_in_count: Total barge-ins in call
            avg_confidence: Average confidence of barge-in detections
            latency_ms: Barge-in response latency
            state_transition_success: Whether FSM transitioned correctly
        """
        metric = BargeInMetric(
            barge_in_count=barge_in_count,
            avg_confidence=avg_confidence,
            latency_ms=latency_ms,
            state_transition_success=state_transition_success,
        )
        self.barge_in_metrics.append(metric)
        self.call_summary.barge_in_count = barge_in_count

        logger.debug(
            f"Recorded barge-in: count={barge_in_count}, "
            f"latency={latency_ms}ms, success={state_transition_success}"
        )

    def record_playback(
        self,
        total_audio_bytes: int,
        position_percentage: float,
        interruption_count: int,
        pause_count: int,
        error_count: int,
        elapsed_ms: int,
    ):
        """Record playback controller metrics.

        Args:
            total_audio_bytes: Total bytes played
            position_percentage: Final playback position (0-100%)
            interruption_count: Number of interruptions
            pause_count: Number of pauses
            error_count: Playback errors
            elapsed_ms: Total playback duration
        """
        metric = PlaybackMetric(
            total_audio_bytes=total_audio_bytes,
            position_percentage=position_percentage,
            interruption_count=interruption_count,
            pause_count=pause_count,
            error_count=error_count,
            elapsed_ms=elapsed_ms,
        )
        self.playback_metrics.append(metric)

        logger.debug(
            f"Recorded playback: {total_audio_bytes} bytes, "
            f"interruptions={interruption_count}"
        )

    def record_endpointing(
        self,
        endpointing_count: int,
        stage_1_timeouts: int,
        stage_2_timeouts: int,
        stage_3_timeouts: int,
        current_silence_ms: int,
    ):
        """Record endpointing metrics.

        Args:
            endpointing_count: Total speech endpoints detected
            stage_1_timeouts: 2.5s silence timeout events
            stage_2_timeouts: 5s silence timeout events
            stage_3_timeouts: 10s silence timeout events
            current_silence_ms: Current silence duration
        """
        metric = EndpointingMetric(
            endpointing_count=endpointing_count,
            stage_1_timeouts=stage_1_timeouts,
            stage_2_timeouts=stage_2_timeouts,
            stage_3_timeouts=stage_3_timeouts,
            current_silence_ms=current_silence_ms,
        )
        self.endpointing_metrics.append(metric)
        self.call_summary.silence_timeouts = (
            stage_1_timeouts + stage_2_timeouts + stage_3_timeouts
        )

        logger.debug(
            f"Recorded endpointing: endpoints={endpointing_count}, "
            f"timeouts={stage_1_timeouts + stage_2_timeouts + stage_3_timeouts}"
        )

    def finalize_call(self, success: bool, final_state: str):
        """Finalize call metrics.

        Args:
            success: Whether call completed successfully
            final_state: Final FSM state
        """
        self.call_summary.end_time = datetime.utcnow()
        self.call_summary.total_duration_ms = int(
            (self.call_summary.end_time - self.call_summary.start_time)
            .total_seconds()
            * 1000
        )
        self.call_summary.success = success
        self.call_summary.final_state = final_state

        logger.info(
            f"Call finalized: duration={self.call_summary.total_duration_ms}ms, "
            f"success={success}, final_state={final_state}"
        )

    def get_call_summary(self) -> CallSummary:
        """Get call summary.

        Returns:
            CallSummary with all aggregated metrics
        """
        return self.call_summary

    def get_metrics_by_category(self, category: MetricCategory) -> dict:
        """Get metrics for specific category.

        Args:
            category: Metric category to retrieve

        Returns:
            Dictionary with metrics for category
        """
        if category == MetricCategory.STATE_MACHINE:
            return {
                "transitions": len(self.state_transitions),
                "metrics": [
                    {
                        "from": m.from_state,
                        "to": m.to_state,
                        "latency_ms": m.latency_ms,
                    }
                    for m in self.state_transitions
                ],
            }

        elif category == MetricCategory.ERROR_RECOVERY:
            return {
                "recoveries": len(self.error_recoveries),
                "successful": sum(1 for m in self.error_recoveries if m.success),
                "metrics": [
                    {
                        "type": m.error_type,
                        "strategy": m.strategy,
                        "success": m.success,
                    }
                    for m in self.error_recoveries
                ],
            }

        elif category == MetricCategory.STREAMING_TTS:
            if self.tts_metrics:
                m = self.tts_metrics[-1]
                return {
                    "text_chars": m.text_chars,
                    "audio_bytes": m.audio_bytes,
                    "time_to_first_audio_ms": m.time_to_first_audio_ms,
                    "chunks": m.chunks_generated,
                    "errors": m.generation_errors,
                }
            return {}

        elif category == MetricCategory.BARGE_IN:
            if self.barge_in_metrics:
                m = self.barge_in_metrics[-1]
                return {
                    "count": m.barge_in_count,
                    "avg_confidence": m.avg_confidence,
                    "latency_ms": m.latency_ms,
                }
            return {}

        elif category == MetricCategory.ENDPOINTING:
            if self.endpointing_metrics:
                m = self.endpointing_metrics[-1]
                return {
                    "endpoints": m.endpointing_count,
                    "stage_1": m.stage_1_timeouts,
                    "stage_2": m.stage_2_timeouts,
                    "stage_3": m.stage_3_timeouts,
                }
            return {}

        else:
            return {}

    def get_all_metrics(self) -> dict:
        """Get all collected metrics.

        Returns:
            Dictionary with all metrics by category
        """
        return {
            "call_summary": {
                "duration_ms": self.call_summary.total_duration_ms,
                "success": self.call_summary.success,
                "state_transitions": self.call_summary.state_transitions,
                "errors": self.call_summary.error_count,
                "error_recoveries": self.call_summary.error_recoveries,
                "barge_ins": self.call_summary.barge_in_count,
                "silence_timeouts": self.call_summary.silence_timeouts,
            },
            "state_machine": self.get_metrics_by_category(
                MetricCategory.STATE_MACHINE
            ),
            "error_recovery": self.get_metrics_by_category(
                MetricCategory.ERROR_RECOVERY
            ),
            "streaming_tts": self.get_metrics_by_category(
                MetricCategory.STREAMING_TTS
            ),
            "barge_in": self.get_metrics_by_category(MetricCategory.BARGE_IN),
            "endpointing": self.get_metrics_by_category(MetricCategory.ENDPOINTING),
        }
