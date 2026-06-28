"""Message sending API routes."""

import logging
from fastapi import APIRouter, HTTPException
from supabase import AsyncClient

from app.adapters.messaging import IMessageBridgeAdapter, TwilioSMSAdapter
from app.services.logger import DebugLogger

router = APIRouter(prefix="/api", tags=["messages"])
logger = logging.getLogger(__name__)


@router.post("/messages/send")
async def send_message(
    run_id: str,
    user_id: str,
    content: str,
    channel: str = "imessage",
    supabase: AsyncClient = None,
):
    """Send a message (iMessage or SMS)."""
    try:
        debug_logger = DebugLogger(supabase, run_id, user_id)

        # Get user phone number
        user = await supabase.table("users").select("phone_number").eq(
            "id", user_id
        ).single().execute()

        phone_number = user.data.get("phone_number") if user.data else None

        if not phone_number:
            raise ValueError("User phone number not found")

        # Send via appropriate channel
        if channel == "imessage":
            adapter = IMessageBridgeAdapter(debug_logger)
            result = await adapter.send_message(phone_number, content)
        else:
            # Fallback to Twilio
            adapter = TwilioSMSAdapter(
                debug_logger,
                account_sid="mock",
                auth_token="mock",
                from_number="mock",
            )
            result = await adapter.send_message(phone_number, content)

        # Log message to database
        await supabase.table("messages").insert({
            "run_id": run_id,
            "user_id": user_id,
            "channel": channel,
            "direction": "outbound",
            "content": content,
            "status": result.get("status"),
            "external_message_id": result.get("message_id"),
        }).execute()

        return {"status": result.get("status"), "message_id": result.get("message_id")}

    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=str(e))
