"""Debug logger service for structured logging."""

import logging
import time
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from supabase import AsyncClient

logger = logging.getLogger(__name__)


class DebugLogger:
    """Structured debug logger that logs to Supabase."""

    def __init__(self, supabase_client: AsyncClient, run_id: str, user_id: str | None = None):
        self.supabase = supabase_client
        self.run_id = run_id
        self.user_id = user_id

    async def log_event(
        self,
        event_type: str,
        message: str,
        agent_name: str | None = None,
        level: Literal["debug", "info", "warning", "error", "critical"] = "info",
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Log an event to Supabase."""
        try:
            await self.supabase.table("debug_logs").insert({
                "run_id": self.run_id,
                "user_id": self.user_id,
                "agent_name": agent_name,
                "level": level,
                "event_type": event_type,
                "message": message,
                "input_payload": input_payload,
                "output_payload": output_payload,
                "error": error,
                "latency_ms": latency_ms,
                "created_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            # Fallback to stdout if Supabase fails
            logger.error(f"Failed to log event: {e}")
            print(f"[{level.upper()}] {agent_name or 'system'}: {message}")

    async def log_tool_call(
        self,
        tool_name: str,
        agent_name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any] | None = None,
        error: Exception | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Log a tool call."""
        try:
            await self.supabase.table("tool_calls").insert({
                "run_id": self.run_id,
                "user_id": self.user_id,
                "agent_name": agent_name,
                "tool_name": tool_name,
                "input_payload": input_payload,
                "output_payload": output_payload,
                "error": {"message": str(error), "type": type(error).__name__} if error else None,
                "latency_ms": latency_ms,
                "status": "success" if error is None else "error",
                "created_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            logger.error(f"Failed to log tool call: {e}")

    async def log_agent_start(self, agent_name: str) -> None:
        """Log the start of an agent."""
        await self.log_event(
            event_type="agent_start",
            message=f"{agent_name} started",
            agent_name=agent_name,
            level="info",
        )

    async def log_agent_end(self, agent_name: str, success: bool = True) -> None:
        """Log the end of an agent."""
        await self.log_event(
            event_type="agent_end",
            message=f"{agent_name} ended ({'success' if success else 'failure'})",
            agent_name=agent_name,
            level="info" if success else "error",
        )

    async def get_logs(self, filters: dict[str, Any] | None = None) -> list[dict]:
        """Retrieve logs for this run."""
        query = self.supabase.table("debug_logs").select("*").eq("run_id", self.run_id)

        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)

        result = await query.execute()
        return result.data or []
