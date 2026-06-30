"""Langfuse v4 logger for voice-call workflow observability.

LangfuseLogger is kept for backward compatibility with existing tests and
callers.  It wraps the Langfuse v4 client and implements the same interface
as the old stub, but now actually sends data to Langfuse.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LangfuseLogger:
    """Langfuse client wrapper for voice-call observability.

    Tracks the full workflow as a single trace with child spans for each
    component (calendar fetch, LLM call, barge-in, state transitions, etc.).
    """

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        enabled: bool = True,
        run_id: str = "",
        user_id: str = "",
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.enabled = enabled and bool(api_key)
        self.run_id = run_id
        self.user_id = user_id
        self.client = None  # public attribute (tests check this)
        self.trace_id = run_id  # public attribute (tests check this)
        self.active_spans: dict = {}  # public attribute (tests check this)
        self._root_obs = None  # root observation for the current call

        if self.enabled:
            try:
                from langfuse import Langfuse  # type: ignore[import]

                self.client = Langfuse(public_key=api_key, secret_key=secret_key)
                logger.info("LangfuseLogger initialised")
            except ImportError:
                logger.warning("langfuse not installed — LangfuseLogger disabled")
                self.enabled = False
            except Exception as e:
                logger.warning("LangfuseLogger init failed: %s", e)
                self.enabled = False

    # ── Trace lifecycle ────────────────────────────────────────────────────────

    def start_trace(self, name: str, metadata: Optional[dict] = None) -> str:
        """Open a root observation representing the entire call."""
        if not self.enabled or not self.client:
            return self.run_id
        try:
            self._root_obs = self.client.start_observation(
                name=name,
                as_type="span",
                input={"user_id": self.user_id, "run_id": self.run_id},
            )
            logger.debug("Langfuse trace started: %s", self.run_id)
        except Exception as e:
            logger.warning("start_trace failed: %s", e)
        return self.run_id

    def end_trace(self, output: Optional[dict] = None) -> None:
        """Close the root observation."""
        if not self.enabled or not self._root_obs:
            return
        try:
            if output:
                self._root_obs.update(output=output)
            self._root_obs.end()
            self._root_obs = None
        except Exception as e:
            logger.warning("end_trace failed: %s", e)

    # ── Span lifecycle ─────────────────────────────────────────────────────────

    def start_span(
        self,
        span_name: str,
        span_type: str = "span",
        metadata: Optional[dict] = None,
    ) -> str:
        """Open a child span under the current root observation."""
        if not self.enabled or not self._root_obs:
            return span_name
        try:
            obs = self._root_obs.start_observation(
                name=span_name,
                as_type="generation" if span_type == "llm" else "span",
            )
            if metadata:
                obs.update(metadata={k: str(v)[:200] for k, v in metadata.items()})
            span_id = f"{span_name}_{len(self.active_spans)}"
            self.active_spans[span_id] = obs
            logger.debug("Langfuse span started: %s", span_id)
            return span_id
        except Exception as e:
            logger.warning("start_span failed: %s", e)
            return span_name

    def end_span(
        self,
        span_id: str,
        status: str = "success",
        output: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        """Close a previously opened child span."""
        if not self.enabled:
            return
        obs = self.active_spans.pop(span_id, None)
        if obs is None:
            return
        try:
            updates: dict[str, Any] = {}
            if output is not None:
                updates["output"] = output
            if error or status == "error":
                updates["level"] = "ERROR"
                if error:
                    updates["status_message"] = error[:200]
            if updates:
                obs.update(**updates)
            obs.end()
        except Exception as e:
            logger.warning("end_span failed: %s", e)

    # ── Convenience methods ────────────────────────────────────────────────────

    def log_metric(self, metric_name: str, value: float, category: str = "custom") -> None:
        """Log a numeric metric as a score on the current trace."""
        if not self.enabled or not self.client or not self._root_obs:
            return
        try:
            self._root_obs.score_trace(name=metric_name, value=value, comment=category)
        except Exception as e:
            logger.debug("log_metric failed: %s", e)

    def log_event(
        self,
        event_name: str,
        event_type: str,
        details: Optional[dict] = None,
    ) -> None:
        """Log a structured event as a zero-duration child span."""
        if not self.enabled or not self._root_obs:
            return
        try:
            obs = self._root_obs.start_observation(name=event_name, as_type="span")
            obs.update(
                input={"type": event_type},
                output={k: str(v)[:200] for k, v in (details or {}).items()},
            )
            obs.end()
        except Exception as e:
            logger.debug("log_event failed: %s", e)

    def get_trace_url(self) -> Optional[str]:
        """Return a link to the trace in the Langfuse dashboard, or None if disabled."""
        if not self.enabled:
            return None
        if self._root_obs:
            try:
                return f"https://cloud.langfuse.com/trace/{self._root_obs.trace_id}"
            except Exception:
                pass
        if self.run_id:
            return f"https://cloud.langfuse.com/trace/{self.run_id}"
        return None

    def flush(self) -> None:
        if self.client:
            try:
                self.client.flush()
            except Exception:
                pass


class LangfuseIntegration:
    """High-level integration of LangfuseLogger with DailyOps AI events."""

    def __init__(self, langfuse_logger: LangfuseLogger):
        self.logger = langfuse_logger

    async def log_state_transition(
        self, from_state: str, to_state: str, trigger: str, latency_ms: int
    ) -> None:
        self.logger.log_event(
            event_name="state_transition",
            event_type="state_machine",
            details={"from": from_state, "to": to_state, "trigger": trigger},
        )
        self.logger.log_metric(
            f"state_latency_{from_state}_{to_state}", latency_ms, "latency"
        )

    async def log_error_recovery(
        self, error_type: str, strategy: str, success: bool, latency_ms: int
    ) -> None:
        self.logger.log_event(
            event_name="error_recovery",
            event_type="error_handling",
            details={"error_type": error_type, "strategy": strategy, "success": str(success)},
        )
        self.logger.log_metric(f"error_recovery_latency_{error_type}", latency_ms, "latency")

    async def log_barge_in(self, confidence: float, latency_ms: int) -> None:
        self.logger.log_event(
            event_name="barge_in_detected",
            event_type="voice_interaction",
            details={"confidence": str(confidence)},
        )
        self.logger.log_metric("barge_in_response_latency", latency_ms, "latency")
        self.logger.log_metric("barge_in_confidence", confidence, "quality")

    async def log_tool_call(
        self, tool_name: str, latency_ms: int, success: bool, error: Optional[str] = None
    ) -> None:
        span_id = self.logger.start_span(f"tool_{tool_name}", span_type="tool")
        self.logger.end_span(
            span_id,
            status="success" if success else "error",
            error=error,
        )
        self.logger.log_metric(f"tool_latency_{tool_name}", latency_ms, "latency")

    async def log_llm_call(
        self, prompt_tokens: int, completion_tokens: int, latency_ms: int
    ) -> None:
        span_id = self.logger.start_span(
            "llm_call",
            span_type="llm",
            metadata={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        )
        self.logger.end_span(span_id, status="success")
        self.logger.log_metric("llm_latency", latency_ms, "latency")
        self.logger.log_metric("llm_tokens_total", prompt_tokens + completion_tokens, "usage")

    async def log_call_complete(
        self, success: bool, final_state: str, total_duration_ms: int, summary: dict
    ) -> None:
        self.logger.log_event(
            event_name="call_complete",
            event_type="call_lifecycle",
            details={"success": str(success), "final_state": final_state},
        )
        self.logger.log_metric("call_duration", total_duration_ms, "performance")
        if "barge_in_count" in summary:
            self.logger.log_metric("barge_in_count", summary["barge_in_count"], "interaction")
        if "error_count" in summary:
            self.logger.log_metric("error_count", summary["error_count"], "reliability")
        self.logger.end_trace(output={k: str(v)[:200] for k, v in summary.items()})
