"""Tests for DOPS-7: Twilio SMS adapter, iMessage bridge, and messaging router."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.messaging.twilio_sms import TwilioSMSAdapter
from app.adapters.messaging.imessage_bridge import IMessageBridgeAdapter
from app.adapters.messaging.router import build_messaging_adapter
from app.services.logger import DebugLogger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def debug_logger(mocker):
    logger = mocker.MagicMock(spec=DebugLogger)
    logger.log_event = AsyncMock()
    return logger


@pytest.fixture
def twilio_adapter(debug_logger):
    return TwilioSMSAdapter(
        debug_logger=debug_logger,
        account_sid="ACtest123",
        auth_token="authtoken",
        from_number="+15550000000",
    )


@pytest.fixture
def imessage_adapter(debug_logger):
    return IMessageBridgeAdapter(
        debug_logger=debug_logger,
        bridge_url="http://localhost:8001",
    )


# ---------------------------------------------------------------------------
# TwilioSMSAdapter tests
# ---------------------------------------------------------------------------


class TestTwilioSMSAdapter:
    @pytest.mark.asyncio
    async def test_send_message_success(self, twilio_adapter, mocker):
        """Happy path: Twilio creates a message and returns its SID."""
        mock_message = MagicMock()
        mock_message.sid = "SM_abc123"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        # Patch the cached_property so no real credentials are needed
        mocker.patch.object(
            type(twilio_adapter), "_client", new_callable=lambda: property(lambda self: mock_client)
        )

        result = await twilio_adapter.send_message("+15551234567", "Good morning!")

        assert result["status"] == "sent"
        assert result["message_id"] == "SM_abc123"
        mock_client.messages.create.assert_called_once_with(
            body="Good morning!",
            from_="+15550000000",
            to="+15551234567",
        )

    @pytest.mark.asyncio
    async def test_send_message_twilio_rest_exception(self, twilio_adapter, mocker):
        """TwilioRestException is caught and returned as failed status."""
        from twilio.base.exceptions import TwilioRestException

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400, uri="/Messages", msg="Invalid number"
        )
        mocker.patch.object(
            type(twilio_adapter), "_client", new_callable=lambda: property(lambda self: mock_client)
        )

        result = await twilio_adapter.send_message("+15551234567", "Hello")

        assert result["status"] == "failed"
        assert "error" in result
        assert "Invalid number" in result["error"]

    @pytest.mark.asyncio
    async def test_send_message_generic_exception(self, twilio_adapter, mocker):
        """Unexpected exceptions are caught and returned as failed."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("network error")
        mocker.patch.object(
            type(twilio_adapter), "_client", new_callable=lambda: property(lambda self: mock_client)
        )

        result = await twilio_adapter.send_message("+15551234567", "Hello")

        assert result["status"] == "failed"
        assert "network error" in result["error"]

    @pytest.mark.asyncio
    async def test_send_message_logs_latency(self, twilio_adapter, debug_logger, mocker):
        """Both send_started and send_completed events are logged."""
        mock_message = MagicMock(sid="SM_xyz")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mocker.patch.object(
            type(twilio_adapter), "_client", new_callable=lambda: property(lambda self: mock_client)
        )

        await twilio_adapter.send_message("+15551234567", "Hello")

        event_types = [call.kwargs["event_type"] for call in debug_logger.log_event.call_args_list]
        assert "send_started" in event_types
        assert "send_completed" in event_types

        # send_completed should include latency_ms
        completed_call = next(c for c in debug_logger.log_event.call_args_list if c.kwargs["event_type"] == "send_completed")
        assert completed_call.kwargs.get("latency_ms") is not None

    def test_is_available_when_configured(self, twilio_adapter):
        assert twilio_adapter.is_available.__wrapped__ if hasattr(twilio_adapter.is_available, "__wrapped__") else True
        # Direct check on attributes
        assert twilio_adapter.account_sid == "ACtest123"
        assert twilio_adapter.auth_token == "authtoken"
        assert twilio_adapter.from_number == "+15550000000"

    @pytest.mark.asyncio
    async def test_is_available_true(self, twilio_adapter):
        assert await twilio_adapter.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false_when_missing_credentials(self, debug_logger):
        adapter = TwilioSMSAdapter(
            debug_logger=debug_logger,
            account_sid="",
            auth_token="",
            from_number="",
        )
        assert await adapter.is_available() is False


# ---------------------------------------------------------------------------
# IMessageBridgeAdapter tests
# ---------------------------------------------------------------------------


class TestIMessageBridgeAdapter:
    @pytest.mark.asyncio
    async def test_send_message_success(self, imessage_adapter, mocker):
        """200 from bridge returns sent status."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message_id": "imsg_001"}

        mock_post = AsyncMock(return_value=mock_response)
        mocker.patch.object(imessage_adapter.http_client, "post", mock_post)

        result = await imessage_adapter.send_message("+15551234567", "Good morning!")

        assert result["status"] == "sent"
        assert result["message_id"] == "imsg_001"

    @pytest.mark.asyncio
    async def test_send_message_non_200_response(self, imessage_adapter, mocker):
        """Non-200 from bridge returns failed status."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_post = AsyncMock(return_value=mock_response)
        mocker.patch.object(imessage_adapter.http_client, "post", mock_post)

        result = await imessage_adapter.send_message("+15551234567", "Hello")

        assert result["status"] == "failed"
        assert "503" in result["error"]

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self, imessage_adapter, mocker):
        """ConnectError is handled gracefully."""
        import httpx

        mock_post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mocker.patch.object(imessage_adapter.http_client, "post", mock_post)

        result = await imessage_adapter.send_message("+15551234567", "Hello")

        assert result["status"] == "failed"
        assert "Bridge connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_send_message_unexpected_exception(self, imessage_adapter, mocker):
        """Unexpected exceptions are caught."""
        mock_post = AsyncMock(side_effect=RuntimeError("explode"))
        mocker.patch.object(imessage_adapter.http_client, "post", mock_post)

        result = await imessage_adapter.send_message("+15551234567", "Hello")

        assert result["status"] == "failed"
        assert "explode" in result["error"]

    @pytest.mark.asyncio
    async def test_is_available_bridge_healthy(self, imessage_adapter, mocker):
        """Returns True when bridge health check returns 200."""
        mock_response = MagicMock(status_code=200)
        mock_get = AsyncMock(return_value=mock_response)
        mocker.patch.object(imessage_adapter.http_client, "get", mock_get)

        assert await imessage_adapter.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_bridge_down(self, imessage_adapter, mocker):
        """Returns False when bridge is unreachable."""
        import httpx

        mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mocker.patch.object(imessage_adapter.http_client, "get", mock_get)

        assert await imessage_adapter.is_available() is False

    @pytest.mark.asyncio
    async def test_send_logs_events(self, imessage_adapter, debug_logger, mocker):
        """send_started and send_completed events are logged."""
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"message_id": "x"}
        mocker.patch.object(imessage_adapter.http_client, "post", AsyncMock(return_value=mock_response))

        await imessage_adapter.send_message("+15551234567", "hi")

        event_types = [c.kwargs["event_type"] for c in debug_logger.log_event.call_args_list]
        assert "send_started" in event_types
        assert "send_completed" in event_types


# ---------------------------------------------------------------------------
# Messaging router tests
# ---------------------------------------------------------------------------


class TestBuildMessagingAdapter:
    def _make_settings(self, mocker, channel="imessage"):
        s = mocker.MagicMock()
        s.preferred_messaging_channel = channel
        s.imessage_bridge_url = "http://localhost:8001"
        s.twilio_account_sid = "ACtest"
        s.twilio_auth_token = "auth"
        s.twilio_phone_number = "+15550000000"
        return s

    def test_returns_imessage_adapter_for_imessage(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="imessage")
        adapter = build_messaging_adapter(settings, debug_logger)
        assert isinstance(adapter, IMessageBridgeAdapter)

    def test_returns_twilio_adapter_for_twilio(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="twilio")
        adapter = build_messaging_adapter(settings, debug_logger)
        assert isinstance(adapter, TwilioSMSAdapter)

    def test_defaults_to_twilio_for_unknown_channel(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="carrier_pigeon")
        adapter = build_messaging_adapter(settings, debug_logger)
        assert isinstance(adapter, TwilioSMSAdapter)

    def test_imessage_adapter_uses_bridge_url(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="imessage")
        settings.imessage_bridge_url = "http://mybridge:9000"
        adapter = build_messaging_adapter(settings, debug_logger)
        assert adapter.bridge_url == "http://mybridge:9000"

    def test_twilio_adapter_uses_credentials(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="twilio")
        settings.twilio_account_sid = "AC_custom"
        settings.twilio_auth_token = "tok_custom"
        settings.twilio_phone_number = "+19990000001"
        adapter = build_messaging_adapter(settings, debug_logger)
        assert adapter.account_sid == "AC_custom"
        assert adapter.auth_token == "tok_custom"
        assert adapter.from_number == "+19990000001"

    def test_channel_matching_is_case_insensitive(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="iMessage")
        adapter = build_messaging_adapter(settings, debug_logger)
        assert isinstance(adapter, IMessageBridgeAdapter)

    def test_channel_matching_strips_whitespace(self, mocker, debug_logger):
        settings = self._make_settings(mocker, channel="  twilio  ")
        adapter = build_messaging_adapter(settings, debug_logger)
        assert isinstance(adapter, TwilioSMSAdapter)
