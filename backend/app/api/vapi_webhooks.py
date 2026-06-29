"""Vapi webhook handler.

All Vapi events arrive at a single endpoint: POST /api/webhook/vapi
Each payload has the shape: {"message": {"type": "<event>", ...}}

Handled event types:
  call.started        — update calls table, log
  call.ended          — update calls table, log
  end-of-call-report  — parse transcript, process user input, send SMS summary
  transcript          — store real-time partial transcripts
  <anything else>     — logged and acknowledged

Security: every request is verified against the HMAC-SHA256 signature in
X-Vapi-Signature (skipped when VAPI_WEBHOOK_SECRET is not configured, which is
fine for local dev but must be set in production).
"""

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhooks"])


# ─── Signature verification ───────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, signature_header: str, secret: str) -> None:
    """Raise HTTP 401 if the HMAC-SHA256 signature does not match.

    Vapi sends the hex-encoded signature in X-Vapi-Signature.
    """
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature_header, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


# ─── Supabase helper ──────────────────────────────────────────────────────────

async def _log(
    supabase: Any,
    run_id: str | None,
    call_id: str | None,
    event_type: str,
    message: str,
    payload: dict,
    level: str = "info",
) -> None:
    try:
        await supabase.table("debug_logs").insert({
            "run_id": run_id,
            "agent_name": "VapiWebhook",
            "event_type": event_type,
            "level": level,
            "message": message,
            "input_payload": payload,
            "output_payload": {"call_id": call_id, "handled_at": datetime.utcnow().isoformat()},
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to write debug log: {e}")


# ─── Transcript parsing ───────────────────────────────────────────────────────

def _parse_transcript(raw: str | list) -> list[dict]:
    """Normalise Vapi transcript into [{role, content}] list.

    Vapi delivers the transcript either as:
      - A plain string:   "User: ...\nAssistant: ..."
      - A list of dicts:  [{"role": "user", "message": "..."}, ...]
    """
    if isinstance(raw, list):
        turns = []
        for turn in raw:
            role = turn.get("role", "unknown").lower()
            content = turn.get("message") or turn.get("content") or ""
            if content:
                turns.append({"role": role, "content": content.strip()})
        return turns

    # Plain string — split on "User:" / "Assistant:" lines
    turns = []
    for line in re.split(r"\n(?=(?:User|Assistant|Bot):\s)", raw.strip(), flags=re.IGNORECASE):
        m = re.match(r"^(User|Assistant|Bot):\s*(.+)$", line.strip(), re.IGNORECASE | re.DOTALL)
        if m:
            role = "user" if m.group(1).lower() == "user" else "assistant"
            turns.append({"role": role, "content": m.group(2).strip()})
    return turns


def _user_turns(turns: list[dict]) -> list[str]:
    return [t["content"] for t in turns if t["role"] == "user"]


# ─── Event handlers ───────────────────────────────────────────────────────────

async def _handle_call_started(message: dict, supabase: Any) -> dict:
    call = message.get("call", {})
    call_id = call.get("id")
    run_id = (call.get("customData") or {}).get("run_id")
    started_at = call.get("startedAt")

    await _log(supabase, run_id, call_id, "call_started", "Call started", message)

    try:
        await supabase.table("calls").update({
            "status": "in_call",
            "vapi_call_id": call_id,
            "started_at": started_at,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("run_id", run_id).execute()
    except Exception as e:
        logger.warning(f"calls table update failed: {e}")

    return {"status": "ok", "event": "call.started", "call_id": call_id}


async def _handle_call_ended(message: dict, supabase: Any) -> dict:
    call = message.get("call", {})
    call_id = call.get("id")
    run_id = (call.get("customData") or {}).get("run_id")
    ended_at = call.get("endedAt")
    ended_reason = call.get("endedReason", "unknown")

    await _log(supabase, run_id, call_id, "call_ended",
               f"Call ended: {ended_reason}", message)

    try:
        await supabase.table("calls").update({
            "status": "ended",
            "ended_at": ended_at,
            "ended_reason": ended_reason,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("run_id", run_id).execute()
    except Exception as e:
        logger.warning(f"calls table update failed: {e}")

    return {"status": "ok", "event": "call.ended", "call_id": call_id}


async def _handle_transcript_chunk(message: dict, supabase: Any) -> dict:
    """Store real-time partial transcript chunks (best-effort)."""
    call = message.get("call", {})
    call_id = call.get("id")
    run_id = (call.get("customData") or {}).get("run_id")
    transcript_text = message.get("transcript", "")

    await _log(supabase, run_id, call_id, "transcript_chunk",
               f"Transcript chunk ({len(transcript_text)} chars)",
               {"transcript_length": len(transcript_text)})

    return {"status": "ok", "event": "transcript"}


async def _handle_end_of_call_report(message: dict, supabase: Any, settings) -> dict:
    """Core post-call handler.

    1. Parse full transcript from the report.
    2. Pull daily_plan from Supabase to reconstruct the plan.
    3. If user spoke, run ConversationAgent.process_user_input().
    4. Send SMS/iMessage summary.
    5. Write final transcript + status back to Supabase.
    """
    call = message.get("call", {})
    call_id = call.get("id")
    custom_data = call.get("customData") or {}
    run_id = custom_data.get("run_id") or str(uuid.uuid4())
    user_id = custom_data.get("user_id", "unknown")

    raw_transcript = message.get("transcript", "")
    duration_seconds = message.get("durationSeconds")
    ended_reason = message.get("endedReason", "unknown")
    summary = message.get("summary", "")

    # Parse structured transcript
    turns = _parse_transcript(raw_transcript)
    user_texts = _user_turns(turns)
    combined_user_input = " ".join(user_texts).strip()

    logger.info(
        f"end-of-call-report: run={run_id}, call={call_id}, "
        f"turns={len(turns)}, user_texts={len(user_texts)}"
    )

    await _log(supabase, run_id, call_id, "end_of_call_report",
               f"End of call report: {len(turns)} turns, {duration_seconds}s",
               {"transcript_length": len(raw_transcript), "ended_reason": ended_reason,
                "user_turn_count": len(user_texts)})

    # --- Rebuild AgentState from persisted plan --------------------------------
    from app.agents.state import AgentState, DailyPlanData
    from app.services.logger import DebugLogger

    debug_logger = DebugLogger(supabase, run_id=run_id, user_id=user_id)

    plan = DailyPlanData()
    try:
        resp = await supabase.table("daily_plans").select("*").eq(
            "run_id", run_id
        ).execute()
        if resp.data:
            row = resp.data[0]
            plan = DailyPlanData(
                calendar_summary=row.get("calendar_summary", ""),
                weather_summary=row.get("weather_summary", ""),
                commute_summary=row.get("commute_summary", ""),
                carry_items=row.get("carry_items") or [],
                extra_user_plans=row.get("extra_user_plans", ""),
                final_summary=row.get("final_summary", ""),
            )
    except Exception as e:
        logger.warning(f"Could not load daily_plan for run {run_id}: {e}")

    state = AgentState(
        run_id=run_id,
        user_id=user_id,
        plan=plan,
        transcript=turns,
        user_input=combined_user_input,
    )
    if duration_seconds:
        state.call_duration_seconds = int(duration_seconds)

    # --- Process user input through ConversationAgent -------------------------
    agent_reply = ""
    if combined_user_input:
        from app.agents.conversation_agent import ConversationAgent
        conv_agent = ConversationAgent(
            debug_logger=debug_logger,
            provider=settings.llm_provider,
        )
        try:
            _action, agent_reply = await conv_agent.process_user_input(state)
            await _log(supabase, run_id, call_id, "user_input_processed",
                       f"User input processed: {_action}",
                       {"action": _action, "user_input": combined_user_input[:200]})
        except Exception as e:
            logger.error(f"process_user_input failed: {e}")
            await _log(supabase, run_id, call_id, "user_input_error",
                       f"Failed to process user input: {e}", {}, level="error")

    # --- Send SMS summary -----------------------------------------------------
    summary_sent = False
    if settings.user_phone_number:
        from app.agents.conversation_agent import ConversationAgent
        from app.adapters.messaging.imessage_bridge import IMessageBridgeAdapter
        from app.adapters.messaging.twilio_sms import TwilioSMSAdapter

        conv_agent = ConversationAgent(
            debug_logger=debug_logger,
            provider=settings.llm_provider,
        )

        # Prefer iMessage bridge; fall back to Twilio
        if settings.imessage_bridge_url:
            msg_adapter = IMessageBridgeAdapter(debug_logger, settings.imessage_bridge_url)
            if not await msg_adapter.is_available():
                msg_adapter = TwilioSMSAdapter(
                    debug_logger,
                    settings.twilio_account_sid,
                    settings.twilio_auth_token,
                    settings.twilio_phone_number,
                )
        else:
            msg_adapter = TwilioSMSAdapter(
                debug_logger,
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.twilio_phone_number,
            )

        summary_sent = await conv_agent.send_summary(
            state, msg_adapter, settings.user_phone_number
        )

    # --- Persist final transcript + status ------------------------------------
    try:
        update = {
            "status": "completed",
            "transcript": raw_transcript,
            "ended_reason": ended_reason,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if duration_seconds:
            update["call_duration_seconds"] = int(duration_seconds)
        if summary:
            update["vapi_summary"] = summary

        await supabase.table("calls").update(update).eq("run_id", run_id).execute()
        await supabase.table("daily_plans").update({
            "status": "completed",
            "transcript": raw_transcript,
            "completed_at": datetime.utcnow().isoformat(),
        }).eq("run_id", run_id).execute()
    except Exception as e:
        logger.warning(f"Final Supabase update failed: {e}")

    return {
        "status": "ok",
        "event": "end-of-call-report",
        "call_id": call_id,
        "run_id": run_id,
        "user_turns": len(user_texts),
        "summary_sent": summary_sent,
    }


# ─── Unified endpoint ─────────────────────────────────────────────────────────

@router.post("/vapi")
async def handle_vapi(request: Request) -> dict:
    """Single entry point for all Vapi webhook events.

    Vapi sends every event here as:
        {"message": {"type": "<event_type>", ...}}

    The X-Vapi-Signature header is verified when VAPI_WEBHOOK_SECRET is set.
    """
    settings = get_settings()

    # Read raw body once so we can both verify the signature and parse JSON
    raw_body = await request.body()

    if settings.vapi_webhook_secret:
        sig = request.headers.get("X-Vapi-Signature", "")
        _verify_signature(raw_body, sig, settings.vapi_webhook_secret)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    message = body.get("message", {})
    event_type = message.get("type", "unknown")

    # Lazy Supabase import to keep the module testable without a live DB
    from app.db.supabase_client import get_supabase_client
    supabase = await get_supabase_client()

    t0 = time.time()
    try:
        if event_type == "call.started":
            result = await _handle_call_started(message, supabase)

        elif event_type == "call.ended":
            result = await _handle_call_ended(message, supabase)

        elif event_type == "end-of-call-report":
            result = await _handle_end_of_call_report(message, supabase, settings)

        elif event_type == "transcript":
            result = await _handle_transcript_chunk(message, supabase)

        else:
            logger.debug(f"Unhandled Vapi event type: {event_type!r}")
            result = {"status": "ignored", "event": event_type}

        result["latency_ms"] = int((time.time() - t0) * 1000)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unhandled error in Vapi webhook ({event_type}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
