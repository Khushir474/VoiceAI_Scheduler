"""Message sending API routes."""

import logging
from fastapi import APIRouter, HTTPException, Depends
from supabase import AsyncClient

from app.adapters.messaging import IMessageBridgeAdapter, TwilioSMSAdapter
from app.services.logger import DebugLogger
from app.config import get_settings
from app.db.supabase_client import get_supabase_client

router = APIRouter(prefix="/api", tags=["messages"])
logger = logging.getLogger(__name__)


async def send_with_fallback(
    debug_logger: DebugLogger,
    phone_number: str,
    content: str,
    supabase: AsyncClient,
) -> dict:
    """
    Send message with automatic fallback.

    Flow:
    1. Try iMessage bridge first
    2. If unavailable or fails → Fall back to Twilio
    3. Log both attempts
    """
    settings = get_settings()

    # Try iMessage bridge first
    imessage_adapter = IMessageBridgeAdapter(debug_logger)
    is_imessage_available = await imessage_adapter.is_available()

    if is_imessage_available:
        logger.info("iMessage bridge available, attempting to send via iMessage")
        result = await imessage_adapter.send_message(phone_number, content)

        if result.get("status") == "sent":
            await debug_logger.log_event(
                agent_name="MessageRouter",
                event_type="send_success",
                message="Message sent via iMessage",
                output_payload={"channel": "imessage", "status": "sent"}
            )
            return {"channel": "imessage", **result}

        # iMessage failed, log and try fallback
        logger.warning(f"iMessage send failed: {result.get('error')}")
        await debug_logger.log_event(
            agent_name="MessageRouter",
            event_type="imessage_failed",
            level="warning",
            message=f"iMessage failed: {result.get('error')}, falling back to Twilio",
            error=result.get("error")
        )

    else:
        logger.info("iMessage bridge unavailable, falling back to Twilio")
        await debug_logger.log_event(
            agent_name="MessageRouter",
            event_type="imessage_unavailable",
            message="iMessage bridge unavailable, using Twilio fallback"
        )

    # Fallback to Twilio SMS
    if not settings.twilio_account_sid or settings.twilio_account_sid == "your-account-sid":
        error_msg = "Twilio not configured and iMessage unavailable"
        await debug_logger.log_event(
            agent_name="MessageRouter",
            event_type="send_failed",
            level="error",
            message=error_msg,
            error=error_msg
        )
        return {"status": "failed", "error": error_msg, "channel": "none"}

    twilio_adapter = TwilioSMSAdapter(
        debug_logger,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_phone_number,
    )

    result = await twilio_adapter.send_message(phone_number, content)

    if result.get("status") == "sent":
        await debug_logger.log_event(
            agent_name="MessageRouter",
            event_type="send_success",
            message="Message sent via Twilio SMS (fallback)",
            output_payload={"channel": "twilio", "status": "sent"}
        )
        return {"channel": "twilio", **result}
    else:
        await debug_logger.log_event(
            agent_name="MessageRouter",
            event_type="send_failed",
            level="error",
            message=f"All messaging channels failed: {result.get('error')}",
            error=result.get("error")
        )
        return {"channel": "none", **result}


@router.post("/messages/send")
async def send_message(
    run_id: str,
    user_id: str,
    content: str,
    supabase: AsyncClient = Depends(get_supabase_client),
):
    """Send a message with automatic fallback (iMessage → Twilio SMS)."""
    try:
        debug_logger = DebugLogger(supabase, run_id, user_id)

        # Get user phone number
        response = await supabase.table("users").select("phone_number").eq(
            "id", user_id
        ).execute()

        if not response.data or len(response.data) == 0:
            raise ValueError(f"User {user_id} not found")

        phone_number = response.data[0].get("phone_number")
        if not phone_number:
            raise ValueError("User phone number not found")

        # Send with fallback
        result = await send_with_fallback(debug_logger, phone_number, content, supabase)

        # Log message to database
        await supabase.table("messages").insert({
            "run_id": run_id,
            "user_id": user_id,
            "channel": result.get("channel"),
            "direction": "outbound",
            "content": content,
            "status": result.get("status"),
            "external_message_id": result.get("message_id"),
        }).execute()

        return {
            "status": result.get("status"),
            "channel": result.get("channel"),
            "message_id": result.get("message_id")
        }

    except Exception as e:
        logger.error(f"Error sending message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
