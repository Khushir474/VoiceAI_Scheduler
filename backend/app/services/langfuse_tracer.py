"""Langfuse integration for observability."""

import logging
from typing import Any, Optional
from datetime import datetime

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

logger = logging.getLogger(__name__)


class LangfuseTracer:
    """Langfuse tracer for LLM and agent monitoring."""

    def __init__(self, public_key: str, secret_key: str, enabled: bool = True):
        """Initialize Langfuse client.

        Args:
            public_key: Langfuse public key
            secret_key: Langfuse secret key
            enabled: Enable/disable tracing
        """
        self.enabled = enabled
        self.client = None

        if enabled and public_key and secret_key:
            try:
                self.client = Langfuse(public_key=public_key, secret_key=secret_key)
                logger.info("Langfuse tracer initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Langfuse: {e}")
                self.enabled = False

    def trace_agent(
        self,
        agent_name: str,
        run_id: str,
        user_id: str | None = None,
    ):
        """Create a trace for an agent execution.

        Usage:
            trace = tracer.trace_agent("PlanningAgent", run_id, user_id)
            trace.span(name="fetch_calendar", input={"date": "2025-01-01"}, output=[...])
        """
        if not self.enabled or not self.client:
            return NoOpTrace()

        trace = self.client.trace(
            name=agent_name,
            input={"run_id": run_id, "user_id": user_id},
            metadata={
                "agent": agent_name,
                "run_id": run_id,
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return LangfuseTrace(trace, self.client, agent_name)

    def trace_tool_call(
        self,
        tool_name: str,
        run_id: str,
        agent_name: str,
        input_data: dict[str, Any] | None = None,
    ):
        """Create a trace for a tool call."""
        if not self.enabled or not self.client:
            return NoOpTrace()

        span = self.client.span(
            name=f"{agent_name}.{tool_name}",
            input=input_data,
            metadata={
                "tool": tool_name,
                "agent": agent_name,
                "run_id": run_id,
                "type": "tool_call",
            },
        )

        return LangfuseSpan(span)

    def trace_llm_call(
        self,
        model: str,
        messages: list[dict],
        run_id: str,
    ):
        """Create a trace for an LLM call."""
        if not self.enabled or not self.client:
            return NoOpTrace()

        generation = self.client.generation(
            name=model,
            model=model,
            input=messages,
            metadata={
                "run_id": run_id,
                "type": "llm_call",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return LangfuseGeneration(generation)

    def flush(self):
        """Flush pending traces to Langfuse."""
        if self.enabled and self.client:
            self.client.flush()


class LangfuseTrace:
    """Wrapper for Langfuse trace."""

    def __init__(self, trace: Any, client: Any, agent_name: str):
        self.trace = trace
        self.client = client
        self.agent_name = agent_name
        self.spans = []

    def span(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
        latency_ms: int | None = None,
    ):
        """Add a span to the trace."""
        span = self.trace.span(
            name=f"{self.agent_name}.{name}",
            input=input_data,
            metadata={
                "agent": self.agent_name,
                "step": name,
                "latency_ms": latency_ms,
            },
        )

        if output_data:
            span.end(output=output_data)
        elif error:
            span.end(level="error")

        self.spans.append(span)
        return span

    def end(self, output_data: dict[str, Any] | None = None, error: str | None = None):
        """End the trace."""
        if output_data:
            self.trace.end(output=output_data)
        elif error:
            self.trace.end(level="error")
        else:
            self.trace.end()


class LangfuseSpan:
    """Wrapper for Langfuse span."""

    def __init__(self, span: Any):
        self.span = span

    def end(self, output_data: dict[str, Any] | None = None, error: str | None = None):
        """End the span."""
        if output_data:
            self.span.end(output=output_data)
        elif error:
            self.span.end(level="error")
        else:
            self.span.end()


class LangfuseGeneration:
    """Wrapper for Langfuse generation."""

    def __init__(self, generation: Any):
        self.generation = generation

    def end(
        self,
        completion: str | None = None,
        tokens_prompt: int | None = None,
        tokens_completion: int | None = None,
        cost: float | None = None,
    ):
        """End the generation with completion info."""
        self.generation.end(
            output=completion,
            metadata={
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "cost": cost,
            },
        )


class NoOpTrace:
    """No-op trace when Langfuse is disabled."""

    def span(self, *args, **kwargs):
        return self

    def end(self, *args, **kwargs):
        return self

    def flush(self):
        pass
