"""Vapi webhook handlers for call state and transcript with comprehensive logging."""

import logging
from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Request, HTTPException, Depends

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhooks"])


# Dependency for Supabase client
async def get_supabase() -> Any:
    """Get Supabase client from app state."""
    from app.db.supabase_client import get_supabase_client
    return get_supabase_client()


async def log_webhook_event(
    supabase: Any,
    run_id: Optional[str],
    event_type: str,
    call_id: Optional[str],
    message: str,
    payload: dict,
    level: str = "info",
) -> None:
    """Log webhook events to debug_logs table.

    Args:
        supabase: Supabase client
        run_id: Run identifier
        event_type: Type of event
        call_id: Vapi call ID
        message: Human-readable message
        payload: Full webhook payload
        level: Log level (info, warning, error)
    """
    try:
        await supabase.table("debug_logs").insert({
            "run_id": run_id,
            "agent_name": "VapiWebhook",
            "event_type": event_type,
            "message": message,
            "level": level,
            "input_payload": payload,
            "output_payload": {
                "call_id": call_id,
                "handled_at": datetime.utcnow().isoformat(),
            },
            "created_at": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.error(f"Failed to log webhook event: {e}")


@router.post("/vapi/call-state")
async def handle_vapi_call_state(request: Request, supabase: Any = Depends(get_supabase)):
    """Handle Vapi call state changes (queued → ringing → in_call → ended).

    Expected webhook payload:
    {
        "id": "call_id",
        "status": "queued|ringing|in_call|ended",
        "customData": {"run_id": "run_id"},
        "startedAt": "2024-01-01T12:00:00Z",
        "endedAt": "2024-01-01T12:05:00Z",
        "duration": 300,
        "endedReason": "user-hangup|assistant-hangup|timeout|error"
    }
    """
    try:
        payload = await request.json()
        call_id = payload.get("id")
        status = payload.get("status")
        custom_data = payload.get("customData", {})
        run_id = custom_data.get("run_id")
        started_at = payload.get("startedAt")
        ended_at = payload.get("endedAt")
        duration = payload.get("duration")
        ended_reason = payload.get("endedReason")

        if not run_id:
            logger.warning(f"Received call state webhook without run_id for call {call_id}")
            await log_webhook_event(
                supabase,
                None,
                "call_state_received",
                call_id,
                "Call state webhook received (no run_id)",
                payload,
                level="warning",
            )
            raise HTTPException(status_code=400, detail="Missing run_id in customData")

        logger.info(f"Vapi call {call_id} state changed to: {status}")

        # Log to debug_logs
        await log_webhook_event(
            supabase,
            run_id,
            "call_state_changed",
            call_id,
            f"Call state changed to {status}",
            payload,
            level="info",
        )

        # Prepare update data
        update_data = {
            "status": status,
            "vapi_call_id": call_id,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if started_at:
            update_data["started_at"] = started_at

        if ended_at:
            update_data["ended_at"] = ended_at

        if duration is not None:
            update_data["duration_seconds"] = duration

        if ended_reason:
            update_data["ended_reason"] = ended_reason

        # Update calls table
        result = await supabase.table("calls").update(update_data).eq(
            "run_id", run_id
        ).execute()

        # Only update daily_plans if call has ended
        if status == "ended":
            await supabase.table("daily_plans").update({
                "status": "completed",
                "call_status": status,
                "call_duration_seconds": duration,
                "ended_at": datetime.utcnow().isoformat(),
            }).eq("run_id", run_id).execute()

        return {
            "status": "received",
            "run_id": run_id,
            "call_id": call_id,
            "processed_status": status,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling Vapi call state: {e}", exc_info=True)
        await log_webhook_event(
            supabase,
            run_id if "run_id" in locals() else None,
            "call_state_error",
            call_id if "call_id" in locals() else None,
            f"Error handling call state: {str(e)}",
            payload if "payload" in locals() else {},
            level="error",
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vapi/transcript")
async def handle_vapi_transcript(request: Request, supabase: Any = Depends(get_supabase)):
    """Handle Vapi transcript updates and call completion.

    Expected webhook payload:
    {
        "id": "call_id",
        "transcript": "Full conversation transcript",
        "duration": 300,
        "customData": {"run_id": "run_id"},
        "status": "ended",
        "endedReason": "user-hangup|assistant-hangup|etc"
    }
    """
    try:
        payload = await request.json()
        call_id = payload.get("id")
        transcript = payload.get("transcript", "")
        duration_seconds = payload.get("duration")
        custom_data = payload.get("customData", {})
        run_id = custom_data.get("run_id")
        status = payload.get("status", "completed")

        if not run_id:
            logger.warning(f"Received transcript webhook without run_id for call {call_id}")
            raise HTTPException(status_code=400, detail="Missing run_id in customData")

        logger.info(f"Vapi transcript received for run {run_id} (call {call_id}, {len(transcript)} chars)")

        # Log to debug_logs
        await log_webhook_event(
            supabase,
            run_id,
            "transcript_received",
            call_id,
            f"Transcript received ({len(transcript)} characters)",
            {
                **payload,
                "transcript_length": len(transcript),  # Avoid logging full transcript
            },
            level="info",
        )

        # Update calls table with transcript
        calls_update = {
            "transcript": transcript,
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if duration_seconds is not None:
            calls_update["duration_seconds"] = duration_seconds

        await supabase.table("calls").update(calls_update).eq(
            "run_id", run_id
        ).execute()

        # Update daily_plans table with transcript and completion
        daily_plan_update = {
            "status": "completed",
            "transcript": transcript,
            "call_status": status,
            "completed_at": datetime.utcnow().isoformat(),
        }

        if duration_seconds is not None:
            daily_plan_update["call_duration_seconds"] = duration_seconds

        await supabase.table("daily_plans").update(daily_plan_update).eq(
            "run_id", run_id
        ).execute()

        return {
            "status": "received",
            "run_id": run_id,
            "call_id": call_id,
            "transcript_length": len(transcript),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling Vapi transcript: {e}", exc_info=True)
        await log_webhook_event(
            supabase,
            run_id if "run_id" in locals() else None,
            "transcript_error",
            call_id if "call_id" in locals() else None,
            f"Error handling transcript: {str(e)}",
            payload if "payload" in locals() else {},
            level="error",
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vapi/error")
async def handle_vapi_error(request: Request, supabase: Any = Depends(get_supabase)):
    """Handle Vapi errors and call failures.

    Expected webhook payload:
    {
        "id": "call_id",
        "status": "failed",
        "error": "Error message",
        "customData": {"run_id": "run_id"},
        "endedReason": "error"
    }
    """
    try:
        payload = await request.json()
        call_id = payload.get("id")
        error_message = payload.get("error", "Unknown error")
        status = payload.get("status", "failed")
        custom_data = payload.get("customData", {})
        run_id = custom_data.get("run_id")
        ended_reason = payload.get("endedReason", "error")

        if run_id:
            logger.error(f"Vapi error for run {run_id} (call {call_id}): {error_message}")

            # Log to debug_logs
            await log_webhook_event(
                supabase,
                run_id,
                "call_error",
                call_id,
                f"Call failed: {error_message}",
                payload,
                level="error",
            )

            # Update calls table with error
            await supabase.table("calls").update({
                "status": status,
                "error_message": error_message,
                "ended_reason": ended_reason,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("run_id", run_id).execute()

            # Update daily_plans table
            await supabase.table("daily_plans").update({
                "status": "failed",
                "error_message": error_message,
                "failed_at": datetime.utcnow().isoformat(),
            }).eq("run_id", run_id).execute()
        else:
            logger.error(f"Vapi error for call {call_id} (no run_id): {error_message}")
            # Log even without run_id
            await log_webhook_event(
                supabase,
                None,
                "call_error",
                call_id,
                f"Call failed: {error_message}",
                payload,
                level="error",
            )

        return {"status": "received", "call_id": call_id}

    except Exception as e:
        logger.error(f"Error handling Vapi error webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vapi/message")
async def handle_vapi_message(request: Request, supabase: Any = Depends(get_supabase)):
    """Handle Vapi message webhooks for real-time events.

    This is a generic webhook for any other Vapi events.
    """
    try:
        payload = await request.json()
        event_type = payload.get("type", "unknown")
        call_id = payload.get("call_id") or payload.get("id")
        run_id = payload.get("customData", {}).get("run_id")

        logger.debug(f"Vapi message webhook: type={event_type}, call_id={call_id}")

        await log_webhook_event(
            supabase,
            run_id,
            f"vapi_message_{event_type}",
            call_id,
            f"Message event: {event_type}",
            payload,
            level="debug",
        )

        return {"status": "received", "event_type": event_type}

    except Exception as e:
        logger.error(f"Error handling Vapi message: {e}")
        raise HTTPException(status_code=500, detail=str(e))
