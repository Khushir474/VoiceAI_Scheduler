"""Vapi webhook handlers for call state and transcript."""

import logging
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from supabase import AsyncClient

router = APIRouter(prefix="/api/webhook", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/vapi/call-state")
async def handle_vapi_call_state(request: Request, supabase: AsyncClient):
    """Handle Vapi call state changes (initiated, in_progress, completed, failed)."""
    try:
        payload = await request.json()
        call_id = payload.get("id")
        status = payload.get("status")
        custom_data = payload.get("customData", {})
        run_id = custom_data.get("run_id")

        if not run_id:
            raise HTTPException(status_code=400, detail="Missing run_id in customData")

        logger.info(f"Vapi call {call_id} status: {status}")

        # Update call record in Supabase
        await supabase.table("calls").update({
            "status": status,
            "vapi_call_id": call_id,
        }).eq("run_id", run_id).execute()

        return {"status": "received", "run_id": run_id}

    except Exception as e:
        logger.error(f"Error handling Vapi call state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vapi/transcript")
async def handle_vapi_transcript(request: Request, supabase: AsyncClient):
    """Handle Vapi transcript and call completion."""
    try:
        payload = await request.json()
        call_id = payload.get("id")
        transcript = payload.get("transcript", "")
        duration_seconds = payload.get("duration")
        custom_data = payload.get("customData", {})
        run_id = custom_data.get("run_id")

        if not run_id:
            raise HTTPException(status_code=400, detail="Missing run_id")

        logger.info(f"Vapi transcript received for run {run_id}")

        # Update call with transcript
        await supabase.table("calls").update({
            "transcript": transcript,
            "duration_seconds": duration_seconds,
            "status": "completed",
        }).eq("run_id", run_id).execute()

        # Update daily plan status
        await supabase.table("daily_plans").update({
            "status": "completed",
            "transcript": transcript,
            "call_duration_seconds": duration_seconds,
        }).eq("run_id", run_id).execute()

        return {"status": "received", "run_id": run_id}

    except Exception as e:
        logger.error(f"Error handling Vapi transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vapi/error")
async def handle_vapi_error(request: Request, supabase: AsyncClient):
    """Handle Vapi errors."""
    try:
        payload = await request.json()
        call_id = payload.get("id")
        error_message = payload.get("error")
        custom_data = payload.get("customData", {})
        run_id = custom_data.get("run_id")

        logger.error(f"Vapi error for run {run_id}: {error_message}")

        if run_id:
            # Update call with error
            await supabase.table("calls").update({
                "status": "failed",
                "error_message": error_message,
            }).eq("run_id", run_id).execute()

            # Update daily plan status
            await supabase.table("daily_plans").update({
                "status": "failed",
            }).eq("run_id", run_id).execute()

        return {"status": "received"}

    except Exception as e:
        logger.error(f"Error handling Vapi error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
