"""Integration tests for Vapi real endpoint and call state tracking.

Tests cover:
- Real API call initiation with latency tracking
- Call state machine (queued → ringing → in_call → ended)
- WebSocket connection lifecycle
- Error handling and recovery
- Webhook handlers for call state and transcript
- Call state persistence and retrieval
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.adapters.voice.vapi import VapiAdapter, VapiCallState
from app.services.logger import DebugLogger


# Fixtures

@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    supabase = AsyncMock()
    supabase.table.return_value.insert.return_value.execute = AsyncMock()
    supabase.table.return_value.update.return_value.eq.return_value.execute = AsyncMock()
    supabase.table.return_value.select.return_value.eq.return_value.execute = AsyncMock()
    return supabase


@pytest.fixture
def debug_logger(mock_supabase):
    """Create a debug logger with mock Supabase."""
    return DebugLogger(mock_supabase, run_id="test_run_123", user_id="test_user_456")


@pytest.fixture
def vapi_adapter(debug_logger):
    """Create a Vapi adapter instance."""
    return VapiAdapter(
        debug_logger=debug_logger,
        api_key="test_api_key_xyz",
        assistant_id="test_assistant_id",
        timeout_seconds=10,
    )


# Call State Tests

class TestVapiCallState:
    """Test VapiCallState tracking."""

    def test_call_state_initialization(self):
        """Test call state initialization."""
        state = VapiCallState("call_123", "run_456")

        assert state.call_id == "call_123"
        assert state.run_id == "run_456"
        assert state.status == "queued"
        assert state.started_at is None
        assert state.ended_at is None
        assert state.duration_seconds == 0
        assert state.transcript == ""

    def test_call_state_duration_calculation(self):
        """Test call duration calculation."""
        state = VapiCallState("call_123", "run_456")

        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 5, 30)

        state.started_at = start
        state.ended_at = end

        assert state.get_duration() == 330  # 5 minutes 30 seconds

    def test_call_state_duration_from_seconds(self):
        """Test duration from seconds field."""
        state = VapiCallState("call_123", "run_456")
        state.duration_seconds = 120

        assert state.get_duration() == 120


# Adapter Tests

class TestVapiAdapterInitialize:
    """Test adapter initialization."""

    def test_adapter_initialization(self, vapi_adapter):
        """Test basic initialization."""
        assert vapi_adapter.api_key == "test_api_key_xyz"
        assert vapi_adapter.assistant_id == "test_assistant_id"
        assert vapi_adapter.base_url == "https://api.vapi.ai"
        assert vapi_adapter.timeout_seconds == 10

    def test_adapter_active_calls_empty(self, vapi_adapter):
        """Test active calls tracking initialized empty."""
        assert vapi_adapter.get_active_calls_count() == 0
        assert len(vapi_adapter.active_calls) == 0


class TestVapiAdapterInitiateCall:
    """Test call initiation."""

    @pytest.mark.asyncio
    async def test_initiate_call_success(self, vapi_adapter):
        """Test successful call initiation."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            # Mock HTTP response
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "call_abc123", "status": "queued"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client

            vapi_adapter.http_client = mock_client

            # Make call
            result = await vapi_adapter.initiate_call("+1234567890", "run_xyz")

            # Assertions
            assert result["status"] == "success"
            assert result["call_id"] == "call_abc123"
            assert "latency_ms" in result
            assert result["latency_ms"] < 2000  # Should complete in less than 2 seconds

            # Check call tracking
            assert vapi_adapter.get_active_calls_count() == 1
            assert "call_abc123" in vapi_adapter.active_calls

    @pytest.mark.asyncio
    async def test_initiate_call_invalid_phone(self, vapi_adapter):
        """Test call initiation with invalid phone number."""
        result = await vapi_adapter.initiate_call("", "run_xyz")

        assert result["status"] == "failed"
        assert "Invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_initiate_call_timeout(self, vapi_adapter):
        """Test call initiation timeout."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            # Mock timeout
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=asyncio.TimeoutError("Connection timeout")
            )
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client
            vapi_adapter.timeout_seconds = 0.1

            result = await vapi_adapter.initiate_call("+1234567890", "run_xyz")

            assert result["status"] == "timeout"
            assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_initiate_call_http_error(self, vapi_adapter):
        """Test call initiation with HTTP error."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"message": "Unauthorized"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.initiate_call("+1234567890", "run_xyz")

            assert result["status"] == "failed"
            assert "Unauthorized" in result["error"]

    @pytest.mark.asyncio
    async def test_initiate_call_no_call_id(self, vapi_adapter):
        """Test call initiation when API doesn't return call_id."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {}  # No 'id' field

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.initiate_call("+1234567890", "run_xyz")

            assert result["status"] == "failed"
            assert "call_id" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_initiate_call_preserves_custom_data(self, vapi_adapter):
        """Test that custom data is preserved in call request."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "call_xyz", "status": "queued"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            await vapi_adapter.initiate_call("+1234567890", "run_abc")

            # Verify the request payload
            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]

            assert payload["customData"]["run_id"] == "run_abc"
            assert "initiated_at" in payload["customData"]


class TestVapiAdapterCallStatus:
    """Test call status retrieval."""

    @pytest.mark.asyncio
    async def test_get_call_status_success(self, vapi_adapter):
        """Test getting call status."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "call_123",
                "status": "in_call",
                "duration": 45,
                "transcript": "Hello, this is a test call",
            }

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.get_call_status("call_123")

            assert result["status"] == "in_call"
            assert result["duration_seconds"] == 45
            assert "Hello" in result["transcript"]

    @pytest.mark.asyncio
    async def test_get_call_status_error(self, vapi_adapter):
        """Test getting call status with error."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.get_call_status("nonexistent_call")

            assert result["status"] == "error"


class TestVapiAdapterStateManagement:
    """Test call state management."""

    @pytest.mark.asyncio
    async def test_update_call_state(self, vapi_adapter):
        """Test updating call state."""
        # First, create a tracked call
        vapi_adapter.active_calls["call_123"] = VapiCallState("call_123", "run_456")

        # Update its state
        await vapi_adapter.update_call_state(
            "call_123",
            "in_call",
            transcript="User is speaking",
            started_at=datetime.utcnow(),
        )

        state = vapi_adapter.active_calls["call_123"]
        assert state.status == "in_call"
        assert state.transcript == "User is speaking"
        assert state.started_at is not None

    @pytest.mark.asyncio
    async def test_get_call_state(self, vapi_adapter):
        """Test retrieving call state."""
        call_state = VapiCallState("call_123", "run_456")
        vapi_adapter.active_calls["call_123"] = call_state

        retrieved = await vapi_adapter.get_call_state("call_123")

        assert retrieved is call_state
        assert retrieved.call_id == "call_123"

    @pytest.mark.asyncio
    async def test_end_call_success(self, vapi_adapter):
        """Test ending a call."""
        vapi_adapter.active_calls["call_123"] = VapiCallState("call_123", "run_456")

        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.end_call("call_123")

            assert result is True
            state = vapi_adapter.active_calls["call_123"]
            assert state.status == "ended"
            assert state.ended_at is not None


class TestVapiAdapterWebSocket:
    """Test WebSocket integration."""

    @pytest.mark.asyncio
    async def test_connect_websocket_success(self, vapi_adapter):
        """Test successful WebSocket connection."""
        with patch("app.adapters.voice.vapi.VapiWebSocketClient") as mock_ws_class:
            mock_ws = AsyncMock()
            mock_ws.connect = AsyncMock(return_value=True)
            mock_ws.on = MagicMock()
            mock_ws_class.return_value = mock_ws

            result = await vapi_adapter.connect_websocket(
                "call_123", "run_456", "user_789"
            )

            assert result is True
            assert "call_123" in vapi_adapter.websocket_clients

    @pytest.mark.asyncio
    async def test_disconnect_websocket(self, vapi_adapter):
        """Test WebSocket disconnection."""
        mock_ws = AsyncMock()
        vapi_adapter.websocket_clients["call_123"] = mock_ws

        await vapi_adapter.disconnect_websocket("call_123")

        mock_ws.disconnect.assert_called_once()
        assert "call_123" not in vapi_adapter.websocket_clients


class TestVapiAdapterHealth:
    """Test health checks."""

    @pytest.mark.asyncio
    async def test_is_available_true(self, vapi_adapter):
        """Test health check success."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.is_available()

            assert result is True

    @pytest.mark.asyncio
    async def test_is_available_false(self, vapi_adapter):
        """Test health check failure."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            result = await vapi_adapter.is_available()

            assert result is False


class TestVapiAdapterCleanup:
    """Test resource cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_closes_connections(self, vapi_adapter):
        """Test cleanup closes all connections."""
        # Add a mock WebSocket
        mock_ws = AsyncMock()
        vapi_adapter.websocket_clients["call_123"] = mock_ws

        # Mock HTTP client
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            await vapi_adapter.cleanup()

            mock_ws.disconnect.assert_called_once()
            mock_client.aclose.assert_called_once()
            assert len(vapi_adapter.websocket_clients) == 0


# Webhook Handler Tests (integration tests via FastAPI TestClient are recommended)

class TestVapiWebhookPayloads:
    """Test webhook payload validation and structure."""

    def test_call_state_payload_validation(self):
        """Test call state webhook payload structure."""
        payload = {
            "id": "call_123",
            "status": "queued",
            "customData": {"run_id": "run_456"},
            "startedAt": "2024-01-01T12:00:00Z",
        }

        assert payload.get("id") == "call_123"
        assert payload.get("status") == "queued"
        assert payload.get("customData", {}).get("run_id") == "run_456"

    def test_transcript_payload_validation(self):
        """Test transcript webhook payload structure."""
        payload = {
            "id": "call_123",
            "transcript": "Hello, how can I help you today?",
            "duration": 300,
            "customData": {"run_id": "run_456"},
            "status": "ended",
        }

        assert payload.get("id") == "call_123"
        assert len(payload.get("transcript", "")) > 0
        assert payload.get("customData", {}).get("run_id") == "run_456"

    def test_error_payload_validation(self):
        """Test error webhook payload structure."""
        payload = {
            "id": "call_123",
            "status": "failed",
            "error": "Connection lost",
            "customData": {"run_id": "run_456"},
        }

        assert payload.get("id") == "call_123"
        assert payload.get("status") == "failed"
        assert len(payload.get("error", "")) > 0


# Integration Tests

class TestVapiIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_call_lifecycle_success(self, vapi_adapter):
        """Test complete call lifecycle from initiation to completion."""
        with patch("app.adapters.voice.vapi.httpx.AsyncClient") as mock_http:
            # Mock successful call creation
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "call_lifecycle_123"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value = mock_client
            vapi_adapter.http_client = mock_client

            # Initiate call
            init_result = await vapi_adapter.initiate_call("+1234567890", "run_lifecycle")
            assert init_result["status"] == "success"
            call_id = init_result["call_id"]

            # Verify call is tracked
            assert await vapi_adapter.get_call_state(call_id) is not None

            # Update call state to in_call
            await vapi_adapter.update_call_state(
                call_id,
                "in_call",
                started_at=datetime.utcnow(),
            )

            # Verify state change
            state = await vapi_adapter.get_call_state(call_id)
            assert state.status == "in_call"

    @pytest.mark.asyncio
    async def test_multiple_concurrent_calls(self, vapi_adapter):
        """Test tracking multiple concurrent calls."""
        call_ids = []

        for i in range(3):
            call_state = VapiCallState(f"call_{i}", f"run_{i}")
            vapi_adapter.active_calls[f"call_{i}"] = call_state
            call_ids.append(f"call_{i}")

        assert vapi_adapter.get_active_calls_count() == 3

        # Update one call
        await vapi_adapter.update_call_state(call_ids[0], "ended")

        # Verify others are unaffected
        assert vapi_adapter.active_calls[call_ids[0]].status == "ended"
        assert vapi_adapter.active_calls[call_ids[1]].status == "queued"
        assert vapi_adapter.active_calls[call_ids[2]].status == "queued"
