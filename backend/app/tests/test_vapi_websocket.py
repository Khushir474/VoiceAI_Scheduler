"""Unit tests for Vapi WebSocket integration."""

import asyncio
import json
import pytest
from datetime import datetime

from app.adapters.voice.vapi_websocket import (
    VapiWebSocketClient,
    VapiEventType,
    VapiConnectionState,
)
from app.services.audio_buffer import AudioChunk, AudioBuffer


@pytest.fixture
def vapi_client():
    """Create a test Vapi WebSocket client."""
    return VapiWebSocketClient(
        vapi_api_key="test_key_123",
        run_id="test_run_456",
        user_id="user_789",
    )


class TestAudioBuffer:
    """Test audio buffer functionality."""

    def test_buffer_creation(self):
        """Test buffer initialization."""
        buffer = AudioBuffer(max_size=50, run_id="test")
        assert buffer.size() == 0
        assert buffer.is_empty()
        assert not buffer.is_full()

    def test_add_chunk(self):
        """Test adding audio chunks."""
        buffer = AudioBuffer(max_size=10)
        chunk = AudioChunk(sequence_number=0, data=b"audio_data")
        buffer.add_chunk(chunk)

        assert buffer.size() == 1
        assert not buffer.is_empty()

    def test_buffer_overflow(self):
        """Test buffer overflow handling."""
        buffer = AudioBuffer(max_size=3)

        for i in range(5):
            chunk = AudioChunk(sequence_number=i, data=b"data")
            buffer.add_chunk(chunk)

        # Buffer should only have 3 items (most recent)
        assert buffer.size() == 3
        assert buffer.overflow_count == 2

    def test_packet_loss_detection(self):
        """Test packet loss detection by sequence numbers."""
        buffer = AudioBuffer()

        # Add chunks with gaps
        buffer.add_chunk(AudioChunk(sequence_number=0, data=b"data"))
        buffer.add_chunk(AudioChunk(sequence_number=1, data=b"data"))
        buffer.add_chunk(AudioChunk(sequence_number=5, data=b"data"))  # Gap!

        assert buffer.packet_loss_count == 3  # Packets 2, 3, 4 missing

    def test_get_chunk(self):
        """Test retrieving chunks FIFO."""
        buffer = AudioBuffer()
        chunk1 = AudioChunk(sequence_number=0, data=b"data1")
        chunk2 = AudioChunk(sequence_number=1, data=b"data2")

        buffer.add_chunk(chunk1)
        buffer.add_chunk(chunk2)

        retrieved1 = buffer.get_chunk()
        assert retrieved1.data == b"data1"

        retrieved2 = buffer.get_chunk()
        assert retrieved2.data == b"data2"

        assert buffer.get_chunk() is None

    def test_buffer_peek(self):
        """Test peeking at oldest chunk without removing."""
        buffer = AudioBuffer()
        chunk = AudioChunk(sequence_number=0, data=b"data")
        buffer.add_chunk(chunk)

        peeked = buffer.peek_chunk()
        assert peeked.data == b"data"

        # Peek should not remove
        assert buffer.size() == 1

    def test_buffer_clear(self):
        """Test clearing buffer."""
        buffer = AudioBuffer()
        for i in range(5):
            buffer.add_chunk(AudioChunk(sequence_number=i, data=b"data"))

        assert buffer.size() == 5
        buffer.clear()
        assert buffer.size() == 0

    def test_buffer_stats(self):
        """Test buffer statistics."""
        buffer = AudioBuffer(max_size=10)
        for i in range(5):
            buffer.add_chunk(AudioChunk(sequence_number=i, data=b"x" * 100))

        stats = buffer.get_stats()
        assert stats["size"] == 5
        assert stats["total_chunks_received"] == 5
        assert stats["bytes_received"] == 500
        assert stats["utilization_percent"] == 50


class TestVapiEventHandling:
    """Test Vapi event dispatching and handling."""

    @pytest.mark.asyncio
    async def test_register_event_handler(self, vapi_client):
        """Test registering event handlers."""
        events_received = []

        async def handler(data):
            events_received.append(data)

        vapi_client.on(VapiEventType.AUDIO_CHUNK, handler)
        await vapi_client._dispatch_event(VapiEventType.AUDIO_CHUNK, {"test": "data"})

        assert len(events_received) == 1
        assert events_received[0]["test"] == "data"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, vapi_client):
        """Test multiple handlers for same event."""
        calls1 = []
        calls2 = []

        async def handler1(data):
            calls1.append(data)

        async def handler2(data):
            calls2.append(data)

        vapi_client.on(VapiEventType.AUDIO_CHUNK, handler1)
        vapi_client.on(VapiEventType.AUDIO_CHUNK, handler2)

        await vapi_client._dispatch_event(VapiEventType.AUDIO_CHUNK, {"test": "data"})

        assert len(calls1) == 1
        assert len(calls2) == 1

    @pytest.mark.asyncio
    async def test_audio_chunk_handling(self, vapi_client):
        """Test audio chunk event processing."""
        message = json.dumps({
            "type": VapiEventType.AUDIO_CHUNK.value,
            "chunk": "YXVkaW9fZGF0YQ==",  # base64: "audio_data"
            "sequence": 0,
        })

        await vapi_client._process_message(message)

        assert vapi_client.audio_chunks_received == 1
        assert vapi_client.audio_buffer.size() == 1

    @pytest.mark.asyncio
    async def test_vad_event_handling(self, vapi_client):
        """Test VAD event processing."""
        message = json.dumps({
            "type": VapiEventType.VAD_UPDATED.value,
            "vad_state": "speaking",
            "confidence": 0.95,
        })

        await vapi_client._process_message(message)

        assert vapi_client.vad_queue.size() == 1
        event = vapi_client.vad_queue.get()
        assert event.vad_state == "speaking"
        assert event.confidence == 0.95

    @pytest.mark.asyncio
    async def test_transcript_handling(self, vapi_client):
        """Test transcript event processing."""
        message = json.dumps({
            "type": VapiEventType.TRANSCRIPT.value,
            "transcript": "Hello, how are you?",
            "is_final": False,
        })

        await vapi_client._process_message(message)

        assert vapi_client.total_events_received == 1

    @pytest.mark.asyncio
    async def test_invalid_json_handling(self, vapi_client):
        """Test handling of invalid JSON."""
        # Should not raise exception
        await vapi_client._process_message("invalid json {]}")

        # Should still process other messages
        valid_message = json.dumps({
            "type": VapiEventType.AUDIO_CHUNK.value,
            "chunk": "dGVzdA==",
            "sequence": 0,
        })
        await vapi_client._process_message(valid_message)

        assert vapi_client.audio_chunks_received == 1


class TestVapiConnectionState:
    """Test connection state management."""

    def test_initial_state(self, vapi_client):
        """Test initial connection state."""
        assert vapi_client.state == VapiConnectionState.DISCONNECTED
        assert vapi_client.websocket is None

    def test_stats_disconnected(self, vapi_client):
        """Test stats when disconnected."""
        stats = vapi_client.get_stats()
        assert stats["state"] == "disconnected"
        assert stats["uptime_seconds"] == 0

    def test_stats_collection(self, vapi_client):
        """Test statistics collection."""
        # Add some data
        for i in range(3):
            vapi_client.audio_buffer.add_chunk(
                AudioChunk(sequence_number=i, data=b"test")
            )

        stats = vapi_client.get_stats()
        assert stats["audio_chunks_received"] == 0  # Not incremented by add_chunk
        assert stats["audio_buffer"]["size"] == 3
        assert stats["audio_buffer"]["total_chunks_received"] == 3


class TestAudioBufferIntegration:
    """Test audio buffer with WebSocket client."""

    @pytest.mark.asyncio
    async def test_get_audio_chunk(self, vapi_client):
        """Test retrieving audio chunks."""
        message = json.dumps({
            "type": VapiEventType.AUDIO_CHUNK.value,
            "chunk": "dGVzdCBhdWRpbw==",  # "test audio"
            "sequence": 0,
        })

        await vapi_client._process_message(message)

        chunk = vapi_client.get_audio_chunk()
        assert chunk is not None
        assert chunk.data == b"test audio"

    @pytest.mark.asyncio
    async def test_get_vad_event(self, vapi_client):
        """Test retrieving VAD events."""
        message = json.dumps({
            "type": VapiEventType.VAD_UPDATED.value,
            "vad_state": "idle",
            "confidence": 0.85,
        })

        await vapi_client._process_message(message)

        event = vapi_client.get_vad_event()
        assert event is not None
        assert event.vad_state == "idle"


class TestEventProcessing:
    """Test comprehensive event processing."""

    @pytest.mark.asyncio
    async def test_unknown_event_type(self, vapi_client):
        """Test handling of unknown event types."""
        message = json.dumps({
            "type": "unknown_event",
            "data": "something",
        })

        # Should not raise exception
        await vapi_client._process_message(message)

    @pytest.mark.asyncio
    async def test_sequential_audio_chunks(self, vapi_client):
        """Test processing multiple sequential audio chunks."""
        for seq in range(5):
            message = json.dumps({
                "type": VapiEventType.AUDIO_CHUNK.value,
                "chunk": f"Y2h1bms{seq}".encode().decode(),
                "sequence": seq,
            })
            await vapi_client._process_message(message)

        assert vapi_client.audio_buffer.size() == 5
        assert vapi_client.audio_buffer.packet_loss_count == 0

    @pytest.mark.asyncio
    async def test_mixed_event_types(self, vapi_client):
        """Test processing mixed event types."""
        events = [
            {
                "type": VapiEventType.AUDIO_CHUNK.value,
                "chunk": "YXVkaW8x",
                "sequence": 0,
            },
            {
                "type": VapiEventType.VAD_UPDATED.value,
                "vad_state": "speaking",
                "confidence": 0.9,
            },
            {
                "type": VapiEventType.TRANSCRIPT.value,
                "transcript": "Hello",
                "is_final": False,
            },
            {
                "type": VapiEventType.AUDIO_CHUNK.value,
                "chunk": "YXVkaW8y",
                "sequence": 1,
            },
        ]

        for event in events:
            await vapi_client._process_message(json.dumps(event))

        assert vapi_client.audio_buffer.size() == 2
        assert vapi_client.vad_queue.size() == 1
        assert vapi_client.total_events_received == 4
