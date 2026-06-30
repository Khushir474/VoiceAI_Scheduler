"""DailyContextService — read/write the ephemeral daily_context table.

One row per (user_id, plan_date). The agent fetches this live during every call
instead of having plan data baked into the system prompt.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.state import DailyPlanData

logger = logging.getLogger(__name__)


def _user_tz(plan: DailyPlanData) -> ZoneInfo:
    """Return ZoneInfo for the plan's detected user timezone, falling back to UTC."""
    try:
        return ZoneInfo(plan.user_timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _today_in_tz(tz: ZoneInfo) -> str:
    return datetime.now(tz=tz).date().isoformat()


class DailyContextService:
    def __init__(self, supabase_client: Any):
        self.db = supabase_client

    # ── Write ──────────────────────────────────────────────────────────────────

    async def upsert(self, user_id: str, plan: DailyPlanData) -> None:
        """Insert or refresh today's context row for a user."""
        tz = _user_tz(plan)
        plan_date = _today_in_tz(tz)

        row = {
            "user_id": user_id,
            "plan_date": plan_date,
            "calendar_events": [e.model_dump(mode="json") for e in plan.calendar_events],
            "weather": plan.weather.model_dump(mode="json") if plan.weather else None,
            "commute": plan.commute.model_dump(mode="json") if plan.commute else None,
            "calendar_summary": plan.calendar_summary,
            "weather_summary": plan.weather_summary,
            "commute_summary": plan.commute_summary,
            "workout_recommendation": plan.workout_recommendation.model_dump(mode="json") if plan.workout_recommendation else None,
            "leave_time": plan.leave_time.isoformat() if plan.leave_time else None,
            "carry_items": plan.carry_items,
            "final_summary": plan.final_summary,
            # Location context — fresh per-call from LocationService
            "user_timezone": plan.user_timezone,
            "user_city": plan.user_city,
            "user_lat": plan.user_lat,
            "user_lng": plan.user_lng,
            "last_refreshed_at": datetime.now(tz=timezone.utc).isoformat(),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            await self.db.table("daily_context").upsert(
                row,
                on_conflict="user_id,plan_date",
                count="exact",
            ).execute()
            logger.info(f"daily_context upserted for user={user_id} date={plan_date} tz={plan.user_timezone}")
        except Exception as e:
            logger.error(f"Failed to upsert daily_context: {e}")
            raise

    # ── Read ───────────────────────────────────────────────────────────────────

    async def fetch(self, user_id: str, plan_date: date | None = None) -> dict | None:
        """Return today's context row for a user, or None if not found.

        If plan_date is omitted, today is computed in UTC (location unknown at fetch time).
        """
        target = plan_date.isoformat() if plan_date else datetime.now(tz=ZoneInfo("UTC")).date().isoformat()
        try:
            resp = await self.db.table("daily_context") \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("plan_date", target) \
                .limit(1) \
                .execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"Failed to fetch daily_context: {e}")
            return None

    def format_for_agent(self, row: dict) -> str:
        """Render a daily_context row as a concise briefing string for the agent."""
        if row.get("final_summary"):
            return row["final_summary"]

        lines = []
        if row.get("user_city"):
            lines.append(f"Location: {row['user_city']}")
        if row.get("calendar_summary"):
            lines.append(f"Calendar: {row['calendar_summary']}")
        if row.get("weather_summary"):
            lines.append(f"Weather: {row['weather_summary']}")
        if row.get("commute_summary"):
            lines.append(f"Commute: {row['commute_summary']}")

        wr = row.get("workout_recommendation")
        if wr:
            lines.append(f"Workout: {wr.get('duration_minutes', 30)} min in the {wr.get('recommended_time', 'morning')}")

        carry = row.get("carry_items") or []
        if carry:
            lines.append(f"Bring: {', '.join(carry)}")

        return "\n".join(lines) if lines else "No plan data available."

    # ── Wipe ───────────────────────────────────────────────────────────────────

    async def wipe_stale(self) -> int:
        """Delete all rows where plan_date is before today UTC. Returns count deleted."""
        today = datetime.now(tz=ZoneInfo("UTC")).date().isoformat()
        try:
            resp = await self.db.table("daily_context") \
                .delete() \
                .lt("plan_date", today) \
                .execute()
            count = len(resp.data) if resp.data else 0
            logger.info(f"Wiped {count} stale daily_context rows (before {today})")
            return count
        except Exception as e:
            logger.error(f"Failed to wipe daily_context: {e}")
            raise
