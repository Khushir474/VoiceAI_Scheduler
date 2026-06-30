"""Langfuse tracing for DailyOps AI.

Works with both langfuse >=3.0,<3.8 (Python 3.9) and langfuse >=4.0 (Python 3.10+).

Initialise once via LangfuseTracer(public_key, secret_key).  After that,
use the re-exported @observe() decorator and propagate_attributes() context
manager anywhere in the codebase — they route through the same global client.
"""

import logging
import os
from contextlib import contextmanager, nullcontext
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Safe re-exports with fallbacks for missing API surface ────────────────────

try:
    from langfuse import observe  # type: ignore[import]
    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False

    def observe(*args, **kwargs):  # type: ignore[misc]
        """No-op @observe() when Langfuse is not installed."""
        if len(args) == 1 and callable(args[0]):
            return args[0]

        def decorator(fn):
            return fn

        return decorator


try:
    from langfuse import propagate_attributes  # type: ignore[import]
except (ImportError, AttributeError):
    # langfuse <4.0 (e.g. 3.7.x on Python 3.9) doesn't have propagate_attributes.
    # Shim it as a context manager that calls update_current_trace() instead —
    # semantically equivalent for setting user_id / session_id on the current trace.
    @contextmanager
    def propagate_attributes(**kwargs):  # type: ignore[misc]
        if _LANGFUSE_AVAILABLE:
            try:
                from langfuse import get_client  # type: ignore[import]
                remap = {
                    "name": kwargs.get("trace_name"),
                    "user_id": kwargs.get("user_id"),
                    "session_id": kwargs.get("session_id"),
                    "version": kwargs.get("version"),
                    "tags": kwargs.get("tags"),
                }
                update_kwargs = {k: v for k, v in remap.items() if v is not None}
                if update_kwargs:
                    get_client().update_current_trace(**update_kwargs)
            except Exception:
                pass
        yield


# ── Tracer ─────────────────────────────────────────────────────────────────────


class LangfuseTracer:
    """Thin wrapper around the Langfuse client.

    Responsibilities:
    - Initialise the global Langfuse client (sets env vars so @observe()
      picks them up automatically).
    - Provide backward-compatible trace_agent() / trace_llm_call() helpers
      for code that still uses the manual observation pattern.
    - Expose flush() / shutdown() for lifecycle management.
    """

    def __init__(self, public_key: str, secret_key: str, enabled: bool = True):
        self.enabled = enabled and bool(public_key) and bool(secret_key)
        self._client = None

        if self.enabled:
            # Populate env vars so get_client() / @observe() find credentials
            os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
            os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
            try:
                from langfuse import Langfuse  # type: ignore[import]

                self._client = Langfuse(public_key=public_key, secret_key=secret_key)
                logger.info("Langfuse tracer initialised")
            except ImportError:
                logger.warning("langfuse package not installed — tracing disabled")
                self.enabled = False
            except Exception as e:
                logger.error("Failed to initialise Langfuse: %s", e)
                self.enabled = False

    # ── Manual observation helpers (backward compat) ───────────────────────────

    def trace_agent(
        self,
        agent_name: str,
        run_id: str,
        user_id: Optional[str] = None,
    ) -> "LangfuseTrace":
        """Create a root observation for an agent execution."""
        if not self.enabled or not self._client:
            return NoOpTrace()  # type: ignore[return-value]
        try:
            obs = self._client.start_observation(
                name=agent_name,
                as_type="span",
                input={"run_id": run_id, "user_id": user_id},
            )
            return LangfuseTrace(obs, agent_name)
        except Exception as e:
            logger.debug("Langfuse trace_agent failed: %s", e)
            return NoOpTrace()  # type: ignore[return-value]

    def trace_llm_call(
        self,
        model: str,
        messages: List[Dict],
        run_id: str,
    ) -> "LangfuseGeneration":
        """Create a generation observation for an LLM call."""
        if not self.enabled or not self._client:
            return NoOpTrace()  # type: ignore[return-value]
        try:
            obs = self._client.start_observation(
                name=model,
                as_type="generation",
                model=model,
                input=messages,
            )
            return LangfuseGeneration(obs)
        except Exception as e:
            logger.debug("Langfuse trace_llm_call failed: %s", e)
            return NoOpTrace()  # type: ignore[return-value]

    def trace_tool_call(
        self,
        tool_name: str,
        run_id: str,
        agent_name: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> "LangfuseTrace":
        """Create a span observation for a tool call."""
        if not self.enabled or not self._client:
            return NoOpTrace()  # type: ignore[return-value]
        try:
            obs = self._client.start_observation(
                name=f"{agent_name}.{tool_name}",
                as_type="span",
                input=input_data,
            )
            return LangfuseTrace(obs, tool_name)
        except Exception as e:
            logger.debug("Langfuse trace_tool_call failed: %s", e)
            return NoOpTrace()  # type: ignore[return-value]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def flush(self) -> None:
        """Block until all buffered observations are sent."""
        if self._client:
            try:
                self._client.flush()
            except Exception as e:
                logger.debug("Langfuse flush failed: %s", e)

    def shutdown(self) -> None:
        """Gracefully flush and shut down background threads."""
        if self._client:
            try:
                self._client.shutdown()
            except Exception as e:
                logger.debug("Langfuse shutdown failed: %s", e)


# ── Observation wrappers ───────────────────────────────────────────────────────


class LangfuseTrace:
    """Wrapper for a Langfuse manual span observation."""

    def __init__(self, obs: Any, agent_name: str):
        self._obs = obs
        self._agent_name = agent_name

    def span(
        self,
        name: str,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> Any:
        """Create a child span, update it, and end it immediately."""
        try:
            child = self._obs.start_observation(
                name=f"{self._agent_name}.{name}",
                as_type="span",
            )
            updates: Dict[str, Any] = {}
            if input_data is not None:
                updates["input"] = input_data
            if output_data is not None:
                updates["output"] = output_data
            if latency_ms is not None:
                updates["metadata"] = {"latency_ms": str(latency_ms)}
            if error:
                updates["level"] = "ERROR"
                updates["status_message"] = error[:200]
            if updates:
                child.update(**updates)
            child.end()
            return child
        except Exception as e:
            logger.debug("Langfuse span failed: %s", e)

    def end(
        self,
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        try:
            updates: Dict[str, Any] = {}
            if output_data is not None:
                updates["output"] = output_data
            if error:
                updates["level"] = "ERROR"
                updates["status_message"] = error[:200]
            if updates:
                self._obs.update(**updates)
            self._obs.end()
        except Exception as e:
            logger.debug("Langfuse trace end failed: %s", e)


class LangfuseGeneration:
    """Wrapper for a Langfuse generation observation."""

    def __init__(self, obs: Any):
        self._obs = obs

    def end(
        self,
        completion: Optional[str] = None,
        tokens_prompt: Optional[int] = None,
        tokens_completion: Optional[int] = None,
        cost: Optional[float] = None,
    ) -> None:
        try:
            updates: Dict[str, Any] = {}
            if completion is not None:
                updates["output"] = completion
            if tokens_prompt is not None or tokens_completion is not None:
                updates["usage_details"] = {
                    "input_tokens": tokens_prompt or 0,
                    "output_tokens": tokens_completion or 0,
                }
            if cost is not None:
                updates["metadata"] = {"cost": str(cost)}
            if updates:
                self._obs.update(**updates)
            self._obs.end()
        except Exception as e:
            logger.debug("Langfuse generation end failed: %s", e)


class NoOpTrace:
    """Silent no-op when Langfuse is disabled or unavailable."""

    def span(self, *args: Any, **kwargs: Any) -> "NoOpTrace":
        return self

    def end(self, *args: Any, **kwargs: Any) -> "NoOpTrace":
        return self

    def flush(self) -> None:
        pass
