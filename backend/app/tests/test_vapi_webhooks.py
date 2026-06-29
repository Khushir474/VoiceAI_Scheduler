"""Tests for the unified Vapi webhook handler."""

import hashlib
import hmac
import json
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

# ─── Transcript parsing (no I/O) ─────────────────────────────────────────────

from app.api.vapi_webhooks import _parse_transcript, _user_turns, _verify_signature


class TestParseTranscript:
    def test_parses_list_format(self):
        raw = [
            {"role": "assistant", "message": "Good morning!"},
            {"role": "user", "message": "I have a dentist appointment at 2pm"},
            {"role": "assistant", "message": "Got it, noted."},
        ]
        turns = _parse_transcript(raw)
        assert len(turns) == 3
        assert turns[0] == {"role": "assistant", "content": "Good morning!"}
        assert turns[1] == {"role": "user", "content": "I have a dentist appointment at 2pm"}

    def test_parses_list_with_content_key(self):
        raw = [
            {"role": "user", "content": "Yes, sounds good"},
        ]
        turns = _parse_transcript(raw)
        assert turns[0]["content"] == "Yes, sounds good"

    def test_parses_string_format(self):
        raw = "User: I have a dentist appointment.\nAssistant: Got it."
        turns = _parse_transcript(raw)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "I have a dentist appointment."
        assert turns[1]["role"] == "assistant"

    def test_string_bot_role_normalised_to_assistant(self):
        raw = "Bot: Hello there.\nUser: Hi."
        turns = _parse_transcript(raw)
        assert turns[0]["role"] == "assistant"
        assert turns[1]["role"] == "user"

    def test_empty_list_returns_empty(self):
        assert _parse_transcript([]) == []

    def test_empty_string_returns_empty(self):
        assert _parse_transcript("") == []

    def test_list_skips_turns_with_no_content(self):
        raw = [
            {"role": "user", "message": ""},
            {"role": "assistant", "message": "Hello"},
        ]
        turns = _parse_transcript(raw)
        assert len(turns) == 1
        assert turns[0]["role"] == "assistant"

    def test_multiline_user_message_in_string(self):
        raw = "User: I have two things:\nfirst is groceries.\nAssistant: Understood."
        turns = _parse_transcript(raw)
        # The user turn should include both lines
        user = next(t for t in turns if t["role"] == "user")
        assert "first is groceries" in user["content"]

    def test_case_insensitive_roles_in_string(self):
        raw = "USER: hello\nASSISTANT: hi"
        turns = _parse_transcript(raw)
        assert turns[0]["role"] == "user"
        assert turns[1]["role"] == "assistant"


class TestUserTurns:
    def test_extracts_only_user_turns(self):
        turns = [
            {"role": "assistant", "content": "Good morning!"},
            {"role": "user", "content": "I'm free at noon"},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "Also dentist at 3pm"},
        ]
        result = _user_turns(turns)
        assert result == ["I'm free at noon", "Also dentist at 3pm"]

    def test_returns_empty_when_no_user_turns(self):
        turns = [{"role": "assistant", "content": "Anything to add?"}]
        assert _user_turns(turns) == []

    def test_returns_empty_on_empty_list(self):
        assert _user_turns([]) == []


# ─── HMAC signature verification ─────────────────────────────────────────────

class TestVerifySignature:
    def _make_sig(self, body: bytes, secret: str) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_passes(self):
        body = b'{"message": {"type": "transcript"}}'
        secret = "test_secret_abc"
        sig = self._make_sig(body, secret)
        # Should not raise
        _verify_signature(body, sig, secret)

    def test_invalid_signature_raises_401(self):
        body = b'{"message": {"type": "transcript"}}'
        with pytest.raises(HTTPException) as exc_info:
            _verify_signature(body, "wrong_signature", "test_secret")
        assert exc_info.value.status_code == 401

    def test_empty_signature_raises_401(self):
        body = b'{"message": {}}'
        with pytest.raises(HTTPException) as exc_info:
            _verify_signature(body, "", "test_secret")
        assert exc_info.value.status_code == 401

    def test_signature_is_body_sensitive(self):
        secret = "mysecret"
        body1 = b'{"message": {"type": "call.started"}}'
        body2 = b'{"message": {"type": "call.ended"}}'
        sig1 = self._make_sig(body1, secret)
        # sig1 should NOT verify body2
        with pytest.raises(HTTPException):
            _verify_signature(body2, sig1, secret)


# ─── Endpoint tests (FastAPI TestClient) ─────────────────────────────────────

def _make_client():
    """Return a TestClient with Supabase and settings mocked."""
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _event_body(event_type: str, extra: dict | None = None) -> dict:
    body = {
        "message": {
            "type": event_type,
            "call": {
                "id": "vapi_call_001",
                "customData": {"run_id": "run_abc", "user_id": "user_xyz"},
                "startedAt": "2026-06-29T06:00:00Z",
                "endedAt": "2026-06-29T06:05:00Z",
                "endedReason": "user-hangup",
            },
        }
    }
    if extra:
        body["message"].update(extra)
    return body


# Shared mock patches for all endpoint tests
_MOCK_PATCHES = [
    patch("app.api.vapi_webhooks.get_settings"),
    patch("app.api.vapi_webhooks.get_supabase_client"),  # patched via lazy import inside handler
]


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.vapi_webhook_secret = ""  # disabled so we skip sig check
    settings.llm_provider = "anthropic"
    settings.user_phone_number = ""  # disabled so we skip SMS
    settings.imessage_bridge_url = ""
    settings.twilio_account_sid = ""
    settings.twilio_auth_token = ""
    settings.twilio_phone_number = ""
    return settings


@pytest.fixture
def mock_supabase():
    sb = MagicMock()
    # Make all chained calls return an awaitable with .data = []
    resp = MagicMock()
    resp.data = []
    chain = MagicMock()
    chain.execute = AsyncMock(return_value=resp)
    sb.table.return_value.insert.return_value = chain
    sb.table.return_value.update.return_value.eq.return_value = chain
    sb.table.return_value.select.return_value.eq.return_value = chain
    return sb


class TestHandleVapiEndpoint:
    """Integration-level tests for the POST /api/webhook/vapi endpoint."""

    def _post(self, client, body: dict, headers: dict | None = None):
        return client.post(
            "/api/webhook/vapi",
            content=json.dumps(body),
            headers={"Content-Type": "application/json", **(headers or {})},
        )

    @pytest.mark.asyncio
    async def test_call_started_returns_ok(self, mock_settings, mock_supabase):
        with (
            patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings),
            patch("app.db.supabase_client.get_supabase_client", new=AsyncMock(return_value=mock_supabase)),
        ):
            client = _make_client()
            resp = self._post(client, _event_body("call.started"))
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["event"] == "call.started"
            assert data["call_id"] == "vapi_call_001"

    @pytest.mark.asyncio
    async def test_call_ended_returns_ok(self, mock_settings, mock_supabase):
        with (
            patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings),
            patch("app.db.supabase_client.get_supabase_client", new=AsyncMock(return_value=mock_supabase)),
        ):
            client = _make_client()
            resp = self._post(client, _event_body("call.ended"))
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["event"] == "call.ended"

    @pytest.mark.asyncio
    async def test_transcript_chunk_returns_ok(self, mock_settings, mock_supabase):
        with (
            patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings),
            patch("app.db.supabase_client.get_supabase_client", new=AsyncMock(return_value=mock_supabase)),
        ):
            client = _make_client()
            body = _event_body("transcript", {"transcript": "User: hello"})
            resp = self._post(client, body)
            assert resp.status_code == 200
            assert resp.json()["event"] == "transcript"

    @pytest.mark.asyncio
    async def test_unknown_event_is_ignored(self, mock_settings, mock_supabase):
        with (
            patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings),
            patch("app.db.supabase_client.get_supabase_client", new=AsyncMock(return_value=mock_supabase)),
        ):
            client = _make_client()
            resp = self._post(client, _event_body("assistant-request"))
            assert resp.status_code == 200
            assert resp.json()["status"] == "ignored"

    def test_invalid_json_returns_400(self, mock_settings):
        with patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings):
            client = _make_client()
            resp = client.post(
                "/api/webhook/vapi",
                content=b"not json at all",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 400

    def test_bad_hmac_returns_401(self, mock_settings):
        mock_settings.vapi_webhook_secret = "real_secret"
        with patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings):
            client = _make_client()
            resp = self._post(
                client,
                _event_body("call.started"),
                headers={"X-Vapi-Signature": "bad_signature"},
            )
            assert resp.status_code == 401

    def test_valid_hmac_passes(self, mock_settings, mock_supabase):
        secret = "webhook_secret_xyz"
        mock_settings.vapi_webhook_secret = secret
        body_bytes = json.dumps(_event_body("call.started")).encode()
        sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()

        with (
            patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings),
            patch("app.db.supabase_client.get_supabase_client", new=AsyncMock(return_value=mock_supabase)),
        ):
            client = _make_client()
            resp = client.post(
                "/api/webhook/vapi",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Vapi-Signature": sig,
                },
            )
            assert resp.status_code == 200

    def test_missing_signature_when_secret_set_returns_401(self, mock_settings):
        mock_settings.vapi_webhook_secret = "real_secret"
        with patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings):
            client = _make_client()
            # No X-Vapi-Signature header → empty string → will not match
            resp = self._post(client, _event_body("call.started"))
            assert resp.status_code == 401

    def test_response_includes_latency_ms(self, mock_settings, mock_supabase):
        with (
            patch("app.api.vapi_webhooks.get_settings", return_value=mock_settings),
            patch("app.db.supabase_client.get_supabase_client", new=AsyncMock(return_value=mock_supabase)),
        ):
            client = _make_client()
            resp = self._post(client, _event_body("call.ended"))
            assert "latency_ms" in resp.json()
            assert isinstance(resp.json()["latency_ms"], int)


# ─── End-of-call-report handler unit tests ────────────────────────────────────

class TestEndOfCallReport:
    """Unit tests for _handle_end_of_call_report without going through HTTP."""

    @pytest.fixture
    def supabase(self):
        sb = MagicMock()
        resp = MagicMock()
        resp.data = []
        chain = MagicMock()
        chain.execute = AsyncMock(return_value=resp)
        sb.table.return_value.insert.return_value = chain
        sb.table.return_value.update.return_value.eq.return_value = chain
        sb.table.return_value.select.return_value.eq.return_value = chain
        return sb

    @pytest.fixture
    def settings(self):
        s = MagicMock()
        s.llm_provider = "anthropic"
        s.user_phone_number = ""
        s.imessage_bridge_url = ""
        return s

    def _message(self, transcript="", user_id="user1", duration=300):
        return {
            "call": {
                "id": "call_test",
                "customData": {"run_id": "run_test", "user_id": user_id},
                "endedReason": "user-hangup",
            },
            "transcript": transcript,
            "durationSeconds": duration,
            "summary": "AI-generated summary.",
        }

    @pytest.mark.asyncio
    async def test_returns_correct_shape(self, supabase, settings):
        from app.api.vapi_webhooks import _handle_end_of_call_report

        with patch("app.services.logger.DebugLogger", autospec=True) as MockLogger:
            MockLogger.return_value.log_event = AsyncMock()
            result = await _handle_end_of_call_report(self._message(), supabase, settings)

        assert result["status"] == "ok"
        assert result["event"] == "end-of-call-report"
        assert result["call_id"] == "call_test"
        assert result["run_id"] == "run_test"

    @pytest.mark.asyncio
    async def test_user_turns_counted(self, supabase, settings):
        from app.api.vapi_webhooks import _handle_end_of_call_report

        transcript = [
            {"role": "assistant", "message": "Good morning!"},
            {"role": "user", "message": "I have a dentist at 2pm"},
            {"role": "user", "message": "Also picking up kids at 4"},
        ]
        result = await _handle_end_of_call_report(
            self._message(transcript=transcript), supabase, settings
        )
        assert result["user_turns"] == 2

    @pytest.mark.asyncio
    async def test_no_user_turns_skips_process_input(self, supabase, settings):
        from app.api.vapi_webhooks import _handle_end_of_call_report

        # No user turns → process_user_input should NOT be called
        transcript = [{"role": "assistant", "message": "Have a great day!"}]
        with patch("app.agents.conversation_agent.ConversationAgent") as MockAgent:
            MockAgent.return_value.process_user_input = AsyncMock()
            await _handle_end_of_call_report(
                self._message(transcript=transcript), supabase, settings
            )
            MockAgent.return_value.process_user_input.assert_not_called()

    @pytest.mark.asyncio
    async def test_sms_sent_when_phone_configured(self, supabase, settings):
        from app.api.vapi_webhooks import _handle_end_of_call_report

        settings.user_phone_number = "+15555550100"
        settings.imessage_bridge_url = "http://localhost:8001"

        # Lazy imports inside the handler must be patched at their source modules
        with (
            patch("app.adapters.messaging.imessage_bridge.IMessageBridgeAdapter") as MockIMsg,
            patch("app.agents.conversation_agent.ConversationAgent") as MockAgent,
        ):
            mock_bridge = MagicMock()
            mock_bridge.is_available = AsyncMock(return_value=True)
            MockIMsg.return_value = mock_bridge

            mock_conv = MagicMock()
            mock_conv.process_user_input = AsyncMock(return_value=("confirm", "All noted!"))
            mock_conv.send_summary = AsyncMock(return_value=True)
            MockAgent.return_value = mock_conv

            result = await _handle_end_of_call_report(
                self._message(), supabase, settings
            )
        assert result["summary_sent"] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_twilio_when_bridge_unavailable(self, supabase, settings):
        from app.api.vapi_webhooks import _handle_end_of_call_report

        settings.user_phone_number = "+15555550100"
        settings.imessage_bridge_url = "http://localhost:8001"
        settings.twilio_account_sid = "ACtest"
        settings.twilio_auth_token = "authtest"
        settings.twilio_phone_number = "+15550001111"

        with (
            patch("app.adapters.messaging.imessage_bridge.IMessageBridgeAdapter") as MockIMsg,
            patch("app.adapters.messaging.twilio_sms.TwilioSMSAdapter") as MockTwilio,
            patch("app.agents.conversation_agent.ConversationAgent") as MockAgent,
        ):
            mock_bridge = MagicMock()
            mock_bridge.is_available = AsyncMock(return_value=False)
            MockIMsg.return_value = mock_bridge

            mock_twilio = MagicMock()
            MockTwilio.return_value = mock_twilio

            mock_conv = MagicMock()
            mock_conv.send_summary = AsyncMock(return_value=True)
            MockAgent.return_value = mock_conv

            await _handle_end_of_call_report(self._message(), supabase, settings)

            # Twilio adapter should have been created as fallback
            MockTwilio.assert_called_once()

    @pytest.mark.asyncio
    async def test_supabase_failure_does_not_crash(self, settings):
        """If Supabase is down, handler should still return a result."""
        from app.api.vapi_webhooks import _handle_end_of_call_report

        bad_sb = MagicMock()
        bad_sb.table.side_effect = Exception("DB connection refused")

        result = await _handle_end_of_call_report(self._message(), bad_sb, settings)
        # Should not raise; errors are caught
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_reconstructs_plan_from_supabase(self, settings):
        """When a daily_plan row exists, it should populate AgentState.plan fields."""
        from app.api.vapi_webhooks import _handle_end_of_call_report
        from app.agents.conversation_agent import ConversationAgent

        plan_row = {
            "run_id": "run_test",
            "calendar_summary": "Team standup at 9am",
            "weather_summary": "Partly cloudy today",
            "commute_summary": "45 mins with light traffic",
            "carry_items": ["laptop", "keys"],
            "extra_user_plans": "",
            "final_summary": "Good day ahead",
        }

        sb = MagicMock()
        resp = MagicMock()
        resp.data = [plan_row]
        chain = MagicMock()
        chain.execute = AsyncMock(return_value=resp)
        good_chain = MagicMock()
        empty_resp = MagicMock()
        empty_resp.data = []
        good_chain.execute = AsyncMock(return_value=empty_resp)

        sb.table.return_value.select.return_value.eq.return_value = chain
        sb.table.return_value.insert.return_value = good_chain
        sb.table.return_value.update.return_value.eq.return_value = good_chain

        captured_state = {}

        # patch.object on an instance method passes `self` as first arg
        async def capture_send(_self, state, adapter, recipient):
            captured_state["plan"] = state.plan
            return True

        transcript = [{"role": "user", "message": "Add gym at 7pm"}]

        settings.user_phone_number = "+15555550100"
        settings.imessage_bridge_url = ""
        settings.twilio_account_sid = "AC"
        settings.twilio_auth_token = "tok"
        settings.twilio_phone_number = "+1555"

        with (
            patch.object(ConversationAgent, "send_summary", capture_send),
            patch("app.adapters.messaging.twilio_sms.TwilioSMSAdapter"),
        ):
            await _handle_end_of_call_report(
                self._message(transcript=transcript), sb, settings
            )

        assert captured_state.get("plan") is not None
        assert captured_state["plan"].calendar_summary == "Team standup at 9am"
