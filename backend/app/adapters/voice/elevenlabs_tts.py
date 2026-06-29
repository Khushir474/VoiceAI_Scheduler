"""ElevenLabs streaming TTS integration.

Handles real-time text-to-speech synthesis with:
- Streaming audio generation (start playback before response completes)
- Text buffering (accumulate until minimum chunk size)
- Parallel TTS + playback (minimize latency)
- Error handling and fallback
"""

import asyncio
import logging
from typing import AsyncIterator, Optional, Callable
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class TTSPlaybackState(str, Enum):
    """TTS playback state."""

    IDLE = "idle"
    GENERATING = "generating"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class TTSChunk:
    """A chunk of generated audio from TTS."""

    text: str
    audio_bytes: bytes
    sequence_number: int
    is_final: bool = False


class TextBuffer:
    """Accumulates text until it reaches a minimum size for TTS.

    Balances:
    - Too small: TTS overhead, latency
    - Too large: perceived delay before first audio
    """

    def __init__(self, min_chunk_size: int = 50, max_chunk_size: int = 500):
        """Initialize text buffer.

        Args:
            min_chunk_size: Minimum chars before sending to TTS
            max_chunk_size: Maximum chars before forced flush
        """
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.buffer = ""
        self.total_chars = 0

    def add(self, text: str) -> list[str]:
        """Add text and return chunks ready to send to TTS.

        Args:
            text: Text to add

        Returns:
            List of text chunks ready for TTS (may be empty)
        """
        self.buffer += text
        self.total_chars += len(text)
        chunks = []

        # Flush if we exceed max size
        while len(self.buffer) >= self.max_chunk_size:
            chunk = self.buffer[:self.max_chunk_size]
            chunks.append(chunk)
            self.buffer = self.buffer[self.max_chunk_size:]

        # Flush if we have minimum and text ends with sentence boundary
        if len(self.buffer) >= self.min_chunk_size and self._ends_with_sentence_boundary():
            chunks.append(self.buffer)
            self.buffer = ""

        return chunks

    def flush(self) -> str:
        """Force flush all remaining text.

        Returns:
            All remaining text in buffer
        """
        result = self.buffer
        self.buffer = ""
        return result

    def size(self) -> int:
        """Get current buffer size in characters."""
        return len(self.buffer)

    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return len(self.buffer) == 0

    def _ends_with_sentence_boundary(self) -> bool:
        """Check if buffer ends with sentence boundary."""
        return self.buffer.rstrip().endswith((".", "?", "!", ",", ";", ":"))

    def size(self) -> int:
        """Return current buffer size in characters."""
        return len(self.buffer)

    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return len(self.buffer) == 0


class ElevenLabsStreamingTTS:
    """ElevenLabs streaming TTS client.

    Synthesizes text to speech with streaming output.
    """

    # ElevenLabs API endpoint
    API_BASE = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        api_key: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Default Bella voice
        model_id: str = "eleven_monolingual_v1",
        run_id: str = "",
    ):
        """Initialize ElevenLabs TTS client.

        Args:
            api_key: ElevenLabs API key
            voice_id: Voice ID to use for synthesis
            model_id: Model to use (eleven_monolingual_v1, eleven_multilingual_v2, etc.)
            run_id: Call identifier for logging
        """
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.run_id = run_id
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    async def synthesize_stream(
        self,
        text: str,
    ) -> AsyncIterator[bytes]:
        """Synthesize text to speech with streaming output.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks as bytes

        Raises:
            RuntimeError: If TTS generation fails
        """
        if not text.strip():
            logger.warning("Empty text provided to TTS")
            return

        url = f"{self.API_BASE}/text-to-speech/{self.voice_id}/stream"

        headers = {
            "xi-api-key": self.api_key,
        }

        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        logger.debug(f"Synthesizing TTS: {len(text)} chars, model={self.model_id}")

        try:
            async with self.client.stream(
                "POST",
                url,
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.atext()
                    logger.error(
                        f"TTS synthesis failed: {response.status_code} - {error_text}"
                    )
                    raise RuntimeError(
                        f"TTS synthesis failed: {response.status_code}"
                    )

                # Stream audio chunks
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if chunk:
                        yield chunk
                        logger.debug(f"Yielded TTS chunk: {len(chunk)} bytes")

        except httpx.RequestError as e:
            logger.error(f"TTS request failed: {e}")
            raise RuntimeError(f"TTS request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in TTS stream: {e}")
            raise

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class StreamingTTSOrchestrator:
    """Orchestrates parallel text accumulation, TTS generation, and playback.

    Implements the streaming TTS pipeline:
    1. LLM generates response text (streaming)
    2. TextBuffer accumulates chars until min_chunk_size
    3. TTS synthesizes chunk while LLM continues
    4. Playback starts as soon as audio available
    5. Process repeats for next chunk
    """

    def __init__(
        self,
        elevenlabs_client: ElevenLabsStreamingTTS,
        min_text_chunk: int = 50,
        run_id: str = "",
    ):
        """Initialize orchestrator.

        Args:
            elevenlabs_client: ElevenLabs TTS client
            min_text_chunk: Minimum chars before sending to TTS
            run_id: Call identifier
        """
        self.tts_client = elevenlabs_client
        self.text_buffer = TextBuffer(min_chunk_size=min_text_chunk)
        self.run_id = run_id
        self.state = TTSPlaybackState.IDLE
        self.sequence_number = 0
        self.tts_queue: asyncio.Queue[Optional[TTSChunk]] = asyncio.Queue(maxsize=3)
        self.playback_queue: asyncio.Queue[Optional[TTSChunk]] = asyncio.Queue(maxsize=3)

    async def generate_stream(
        self,
        llm_stream: AsyncIterator[str],
    ) -> AsyncIterator[TTSChunk]:
        """Generate TTS audio from LLM text stream.

        Coordinates:
        - TextBuffer accumulates LLM output
        - TTS generates audio in parallel
        - Audio is yielded as chunks become available

        Args:
            llm_stream: Async iterator of text tokens from LLM

        Yields:
            TTSChunk with audio data and metadata
        """
        self.state = TTSPlaybackState.GENERATING

        async def accumulate_text():
            """Accumulate LLM tokens and queue for TTS."""
            async for token in llm_stream:
                # Add to buffer and get ready chunks
                chunks = self.text_buffer.add(token)
                for chunk in chunks:
                    await self.tts_queue.put(chunk)
            # Flush remaining text
            final = self.text_buffer.flush()
            if final.strip():
                await self.tts_queue.put(final)
            # Signal end
            await self.tts_queue.put(None)

        async def generate_tts():
            """Generate TTS audio chunks."""
            while True:
                text_chunk = await self.tts_queue.get()
                if text_chunk is None:
                    break

                try:
                    logger.debug(f"Generating TTS for: {text_chunk[:50]}...")
                    audio_bytes = b""

                    async for audio_chunk in self.tts_client.synthesize_stream(
                        text_chunk
                    ):
                        audio_bytes += audio_chunk

                    tts_chunk = TTSChunk(
                        text=text_chunk,
                        audio_bytes=audio_bytes,
                        sequence_number=self.sequence_number,
                        is_final=False,
                    )
                    self.sequence_number += 1

                    await self.playback_queue.put(tts_chunk)
                    logger.debug(
                        f"Generated TTS chunk {tts_chunk.sequence_number}: "
                        f"{len(audio_bytes)} bytes"
                    )

                except Exception as e:
                    logger.error(f"TTS generation failed: {e}")
                    # Send error signal
                    await self.playback_queue.put(None)
                    break

            # Signal end
            await self.playback_queue.put(None)

        async def stream_playback():
            """Yield TTS chunks as they're ready."""
            while True:
                chunk = await self.playback_queue.get()
                if chunk is None:
                    self.state = TTSPlaybackState.IDLE
                    break
                chunk.is_final = self.playback_queue.qsize() == 0
                yield chunk

        # Run accumulate_text and generate_tts concurrently
        # while yielding from stream_playback
        try:
            accumulate_task = asyncio.create_task(accumulate_text())
            generate_task = asyncio.create_task(generate_tts())

            async for chunk in stream_playback():
                yield chunk

            # Wait for tasks to complete
            await asyncio.gather(accumulate_task, generate_task)

        except asyncio.CancelledError:
            logger.info("TTS generation cancelled")
            self.state = TTSPlaybackState.STOPPED
            raise
        except Exception as e:
            logger.error(f"Error in TTS streaming: {e}")
            self.state = TTSPlaybackState.ERROR
            raise

    async def stop(self):
        """Stop TTS generation."""
        self.state = TTSPlaybackState.STOPPED
        logger.info("Stopped TTS generation")
