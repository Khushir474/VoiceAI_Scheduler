"""Dashboard API routes."""

import logging
from datetime import date, datetime
from fastapi import APIRouter, Query, HTTPException
from supabase import AsyncClient

router = APIRouter(prefix="/api", tags=["dashboard"])
logger = logging.getLogger(__name__)


@router.get("/plans/latest")
async def get_latest_plan(user_id: str, supabase: AsyncClient):
    """Get the latest daily plan for a user."""
    try:
        result = await supabase.table("daily_plans").select(
            "*"
        ).eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()

        plans = result.data or []
        if not plans:
            return {"plan": None}

        return {"plan": plans[0]}

    except Exception as e:
        logger.error(f"Error fetching latest plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plans")
async def get_plans(
    user_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase: AsyncClient = None,
):
    """Get daily plans for a user with pagination."""
    try:
        result = await supabase.table("daily_plans").select(
            "id,created_at,run_id,plan_date,calendar_summary,weather_summary,"
            "commute_summary,workout_recommendation,status,evaluation_scores(overall_score)"
        ).eq("user_id", user_id).order("plan_date", desc=True).range(offset, offset + limit - 1).execute()

        return {"plans": result.data or [], "total": len(result.data or [])}

    except Exception as e:
        logger.error(f"Error fetching plans: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs")
async def get_debug_logs(
    user_id: str | None = None,
    run_id: str | None = None,
    agent_name: str | None = None,
    level: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    supabase: AsyncClient = None,
):
    """Get debug logs with filters."""
    try:
        query = supabase.table("debug_logs").select("*")

        if run_id:
            query = query.eq("run_id", run_id)
        if user_id:
            query = query.eq("user_id", user_id)
        if agent_name:
            query = query.eq("agent_name", agent_name)
        if level:
            query = query.eq("level", level)

        result = await query.order("created_at", desc=True).limit(limit).execute()

        return {"logs": result.data or []}

    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tool-calls")
async def get_tool_calls(
    run_id: str | None = None,
    agent_name: str | None = None,
    tool_name: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    supabase: AsyncClient = None,
):
    """Get tool calls with filters."""
    try:
        query = supabase.table("tool_calls").select("*")

        if run_id:
            query = query.eq("run_id", run_id)
        if agent_name:
            query = query.eq("agent_name", agent_name)
        if tool_name:
            query = query.eq("tool_name", tool_name)

        result = await query.order("created_at", desc=True).limit(limit).execute()

        # Calculate stats
        tool_calls = result.data or []
        total_latency = sum(tc.get("latency_ms", 0) for tc in tool_calls)
        avg_latency = total_latency / len(tool_calls) if tool_calls else 0

        return {
            "tool_calls": tool_calls,
            "stats": {
                "total": len(tool_calls),
                "total_latency_ms": total_latency,
                "avg_latency_ms": avg_latency,
                "success_count": sum(1 for tc in tool_calls if tc.get("status") == "success"),
                "error_count": sum(1 for tc in tool_calls if tc.get("status") == "error"),
            },
        }

    except Exception as e:
        logger.error(f"Error fetching tool calls: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings/{user_id}")
async def get_user_settings(user_id: str, supabase: AsyncClient):
    """Get user settings/preferences."""
    try:
        result = await supabase.table("user_preferences").select("*").eq(
            "user_id", user_id
        ).single().execute()

        return {"settings": result.data}

    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        # Return defaults if not found
        return {
            "settings": {
                "wake_up_time": "06:00",
                "workout_duration_minutes": 30,
                "workout_preference": "morning",
                "commute_buffer_minutes": 15,
                "preferred_messaging_channel": "imessage",
                "google_calendar_enabled": True,
                "apple_ical_enabled": True,
            }
        }


@router.post("/settings/{user_id}")
async def update_user_settings(user_id: str, settings: dict, supabase: AsyncClient):
    """Update user settings/preferences."""
    try:
        await supabase.table("user_preferences").update(settings).eq(
            "user_id", user_id
        ).execute()

        return {"success": True}

    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview/{user_id}")
async def get_overview(user_id: str, supabase: AsyncClient):
    """Get dashboard overview for a user."""
    try:
        # Get latest plan
        plans = await supabase.table("daily_plans").select("*").eq(
            "user_id", user_id
        ).order("created_at", desc=True).limit(1).execute()

        latest_plan = plans.data[0] if plans.data else None

        # Get latest call
        calls = await supabase.table("calls").select("*").eq(
            "user_id", user_id
        ).order("created_at", desc=True).limit(1).execute()

        latest_call = calls.data[0] if calls.data else None

        # Get latest evaluation
        evals = await supabase.table("evaluation_scores").select("*").eq(
            "user_id", user_id
        ).order("created_at", desc=True).limit(1).execute()

        latest_eval = evals.data[0] if evals.data else None

        return {
            "latest_plan": latest_plan,
            "latest_call": latest_call,
            "latest_evaluation": latest_eval,
        }

    except Exception as e:
        logger.error(f"Error fetching overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))
