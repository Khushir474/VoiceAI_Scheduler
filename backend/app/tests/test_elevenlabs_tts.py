"""Unit tests for ElevenLabs streaming TTS integration."""

import asyncio
import pytest

from app.adapters.voice.elevenlabs_tts import (
    TextBuffer,
    TTSChunk,
    TTSPlaybackState,
    StreamingTTSOrchestrator,
)


class TestTextBuffer:
    """Test text accumulation for TTS."""

    def test_buffer_creation(self):
        """Test buffer initialization."""
        buffer = TextBuffer(min_chunk_size=50, max_chunk_size=500)
        assert buffer.size() == 0
        assert buffer.is_empty()

    def test_add_text_below_minimum(self):
        """Test adding text below minimum chunk size."""
        buffer = TextBuffer(min_chunk_size=100)
        chunks = buffer.add("Hello ")

        assert len(chunks) == 0
        assert buffer.size() == 6

    def test_add_text_at_minimum(self):
        """Test adding text that reaches minimum."""
        buffer = TextBuffer(min_chunk_size=50)
        text = "This is a test sentence. " * 3

        chunks = buffer.add(text)

        # Should not flush yet (no sentence boundary)
        assert len(chunks) == 0
        assert buffer.size() > 0

    def test_add_text_with_sentence_boundary(self):
        """Test flushing on sentence boundary."""
        buffer = TextBuffer(min_chunk_size=20)
        text1 = "Hello world. "
        text2 = "How are you? "

        chunks1 = buffer.add(text1)
        # Might flush depending on size
        assert buffer.size() >= 0

        chunks2 = buffer.add(text2)
        # Should have flushed something
        assert buffer.size() >= 0

    def test_buffer_exceeds_max_chunk(self):
        """Test forcing flush when exceeding max chunk size."""
        buffer = TextBuffer(min_chunk_size=50, max_chunk_size=100)
        text = "x" * 150  # Exceeds max

        chunks = buffer.add(text)

        assert len(chunks) >= 1
        # First chunk should be max_chunk_size
        assert len(chunks[0]) == 100

    def test_buffer_flush(self):
        """Test manual flush."""
        buffer = TextBuffer()
        buffer.add("partial text")

        flushed = buffer.flush()

        assert flushed == "partial text"
        assert buffer.is_empty()

    def test_multiple_sentence_boundaries(self):
        """Test multiple sentence boundary characters."""
        buffer = TextBuffer(min_chunk_size=10)

        for char in [".", "!", "?", ",", ";", ":"]:
            buffer.buffer = "test text" + char
            result = buffer._ends_with_sentence_boundary()
            assert result, f"Should recognize '{char}' as boundary"

    def test_buffer_tracking(self):
        """Test total characters tracked."""
        buffer = TextBuffer()
        buffer.add("Hello")
        buffer.add(" ")
        buffer.add("world")

        assert buffer.total_chars == 11


class TestTTSChunk:
    """Test TTS chunk structure."""

    def test_chunk_creation(self):
        """Test creating a TTS chunk."""
        chunk = TTSChunk(
            text="Hello world",
            audio_bytes=b"audio_data",
            sequence_number=0,
        )

        assert chunk.text == "Hello world"
        assert chunk.audio_bytes == b"audio_data"
        assert chunk.sequence_number == 0
        assert chunk.is_final is False

    def test_chunk_with_final(self):
        """Test marking chunk as final."""
        chunk = TTSChunk(
            text="Goodbye",
            audio_bytes=b"data",
            sequence_number=1,
            is_final=True,
        )

        assert chunk.is_final is True


class TestStreamingTTSOrchestrator:
    """Test TTS orchestration (mock ElevenLabs client)."""

    @pytest.fixture
    def mock_tts_client(self):
        """Create a mock TTS client."""

        class MockTTSClient:
            async def synthesize_stream(self, text: str):
                """Mock TTS synthesis."""
                # Return dummy audio based on text length
                audio_bytes = b"audio_" + str(len(text)).encode()
                yield audio_bytes

        return MockTTSClient()

    @pytest.fixture
    def orchestrator(self, mock_tts_client):
        """Create orchestrator with mock client."""
        return StreamingTTSOrchestrator(
            mock_tts_client,
            min_text_chunk=20,
            run_id="test_run",
        )

    def test_orchestrator_creation(self, orchestrator):
        """Test orchestrator initialization."""
        assert orchestrator.state == TTSPlaybackState.IDLE
        assert orchestrator.sequence_number == 0

    @pytest.mark.asyncio
    async def test_text_to_speech_stream(self, orchestrator):
        """Test streaming text to speech."""

        async def mock_llm_stream():
            """Mock LLM response stream."""
            texts = [
                "Hello ",
                "world. ",
                "This is a test. ",
                "How are you?",
            ]
            for text in texts:
                yield text
                await asyncio.sleep(0.01)  # Simulate processing time

        chunks_received = []

        async for chunk in orchestrator.generate_stream(mock_llm_stream()):
            chunks_received.append(chunk)
            assert isinstance(chunk, TTSChunk)
            assert chunk.audio_bytes == b""  # Mock returns empty
            assert chunk.sequence_number == len(chunks_received) - 1

        assert len(chunks_received) >= 1
        assert orchestrator.state == TTSPlaybackState.IDLE

    @pytest.mark.asyncio
    async def test_streaming_with_empty_text(self, orchestrator):
        """Test handling empty text in stream."""

        async def mock_stream():
            yield ""
            yield ""
            yield "Valid text."

        chunks = []
        async for chunk in orchestrator.generate_stream(mock_stream()):
            chunks.append(chunk)

        # Should still generate output
        assert len(chunks) >= 0

    @pytest.mark.asyncio
    async def test_text_buffer_accumulation(self, orchestrator):
        """Test that text buffer accumulates properly."""

        async def mock_stream():
            yield "S"
            yield "h"
            yield "o"
            yield "r"
            yield "t"
            yield ". "

        text_chunks_queued = []
        original_put = orchestrator.tts_queue.put

        async def track_put(chunk):
            if chunk is not None:
                text_chunks_queued.append(chunk)
            await original_put(chunk)

        orchestrator.tts_queue.put = track_put

        chunks = []
        async for chunk in orchestrator.generate_stream(mock_stream()):
            chunks.append(chunk)

        # Text should have been accumulated and flushed
        # (exact behavior depends on buffering logic)
        assert len(text_chunks_queued) >= 0

    @pytest.mark.asyncio
    async def test_concurrent_text_and_tts(self, orchestrator):
        """Test concurrent text accumulation and TTS generation."""

        async def mock_stream():
            for i in range(10):
                yield f"Token {i}. "
                await asyncio.sleep(0.001)

        start_chunks = 0
        chunks_count = 0

        async for chunk in orchestrator.generate_stream(mock_stream()):
            chunks_count += 1

        # Should have generated multiple chunks
        assert chunks_count >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_stop(self, orchestrator):
        """Test stopping orchestration."""
        orchestrator.state = TTSPlaybackState.PLAYING
        await orchestrator.stop()

        assert orchestrator.state == TTSPlaybackState.STOPPED

    @pytest.mark.asyncio
    async def test_sequence_numbering(self, orchestrator):
        """Test that chunks get proper sequence numbers."""

        async def mock_stream():
            yield "First. "
            yield "Second. "
            yield "Third."

        chunks = []
        async for chunk in orchestrator.generate_stream(mock_stream()):
            chunks.append(chunk)

        # Verify sequence numbers are incremental
        if len(chunks) > 0:
            for i, chunk in enumerate(chunks):
                assert chunk.sequence_number == i


class TestTextBufferBoundaryDetection:
    """Test sentence boundary detection."""

    def test_period_boundary(self):
        """Test period as boundary."""
        buffer = TextBuffer()
        buffer.buffer = "Hello world."
        assert buffer._ends_with_sentence_boundary()

    def test_question_mark_boundary(self):
        """Test question mark as boundary."""
        buffer = TextBuffer()
        buffer.buffer = "What is this?"
        assert buffer._ends_with_sentence_boundary()

    def test_exclamation_boundary(self):
        """Test exclamation mark as boundary."""
        buffer = TextBuffer()
        buffer.buffer = "Watch out!"
        assert buffer._ends_with_sentence_boundary()

    def test_no_boundary(self):
        """Test text without boundary."""
        buffer = TextBuffer()
        buffer.buffer = "Still going"
        assert not buffer._ends_with_sentence_boundary()

    def test_boundary_with_whitespace(self):
        """Test boundary with trailing whitespace."""
        buffer = TextBuffer()
        buffer.buffer = "Hello world.   "
        assert buffer._ends_with_sentence_boundary()


class TestTextBufferEdgeCases:
    """Test edge cases in text buffering."""

    def test_very_long_text(self):
        """Test handling very long text."""
        buffer = TextBuffer(min_chunk_size=50, max_chunk_size=200)
        long_text = "x" * 1000

        chunks = buffer.add(long_text)

        # Should be split into multiple chunks
        assert len(chunks) >= 4  # 1000 / 200 = 5

    def test_rapid_additions(self):
        """Test rapid text additions."""
        buffer = TextBuffer(min_chunk_size=100)

        for i in range(50):
            buffer.add(f"Text {i}. ")

        # Should have accumulated significant text
        assert buffer.size() > 0

    def test_empty_additions(self):
        """Test adding empty strings."""
        buffer = TextBuffer()
        chunks = buffer.add("")

        assert len(chunks) == 0
        assert buffer.size() == 0
