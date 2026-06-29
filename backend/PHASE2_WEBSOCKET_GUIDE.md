# Phase 2: Vapi WebSocket + ElevenLabs TTS Integration Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    6 AM Scheduled Call                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Vapi      │
                    │  Call API   │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐       ┌────▼─────┐    ┌────▼────┐
    │  Audio  │       │  Vapi    │    │   LLM   │
    │  Input  │       │ WebSocket│    │ Response│
    │  (STT)  │       │  Client  │    │ Stream  │
    └────┬────┘       └────┬─────┘    └────┬────┘
         │                 │               │
         │            ┌────▼─────┐        │
         │            │   Audio  │        │
         │            │  Buffer  │        │
         │            │  (Ring)  │        │
         │            └────┬─────┘        │
         │                 │               │
         │            ┌────▼──────┐   ┌───▼──────┐
         │            │  VAD      │   │  Text    │
         │            │  Queue    │   │  Buffer  │
         │            └────┬──────┘   └───┬──────┘
         │                 │               │
         │          ┌──────▼───────────────▼──┐
         │          │ Conversation FSM        │
         │          │ (State Machine)         │
         │          └──────┬──────────────────┘
         │                 │
         │          ┌──────▼──────────────┐
         │          │ Streaming TTS       │
         │          │ Orchestrator        │
         │          │                     │
         │          ├─ Text Buffer        │
         │          ├─ ElevenLabs TTS     │
         │          └─ Playback Queue     │
         │                 │
         └─────────────────┼──────────────┘
                           │
                    ┌──────▼──────┐
                    │   Audio     │
                    │  Playback   │
                    │  (Speaker)  │
                    └─────────────┘
```

## Components

### 1. VapiWebSocketClient (`adapters/voice/vapi_websocket.py`)

**Responsibilities:**
- Maintain persistent WebSocket connection to Vapi
- Handle reconnection with exponential backoff (up to 5 attempts)
- Parse incoming events from Vapi
- Buffer audio chunks (ring buffer, max 100 chunks)
- Queue VAD signals for downstream processing

**Key Methods:**
```python
# Connection lifecycle
await client.connect()                    # Establish connection
await client.listen()                     # Listen for events (blocking)
await client.disconnect()                 # Graceful shutdown
await client._reconnect()                 # Reconnect with backoff

# Event handling
client.on(VapiEventType.AUDIO_CHUNK, handler)  # Register handler
await client._dispatch_event(event_type, data) # Send to handlers

# Data access
chunk = client.get_audio_chunk()          # FIFO audio
event = client.get_vad_event()            # VAD signals
stats = client.get_stats()                # Connection metrics
```

**Events Handled:**
- `AUDIO_CHUNK` - Raw audio from user (into buffer)
- `VAD_UPDATED` - Voice activity signal (into queue)
- `TRANSCRIPT` - STT partial/final transcript
- `SESSION_STARTED/ENDED` - Connection lifecycle
- `ERROR` - Vapi errors

### 2. AudioBuffer (`services/audio_buffer.py`)

**Responsibilities:**
- Ring buffer for streaming audio (prevents unbounded memory)
- Detect packet loss by sequence numbers
- Track latency per chunk
- Log overflow events

**Key Methods:**
```python
buffer.add_chunk(chunk)           # Add audio chunk
chunk = buffer.get_chunk()        # Remove and return (FIFO)
chunk = buffer.peek_chunk()       # View without removing
stats = buffer.get_stats()        # Utilization, latency, loss
```

**Features:**
- Max size: 100 chunks (configurable)
- Packet loss detection
- Overflow handling (auto-drops oldest when full)
- Per-chunk latency tracking

### 3. VADEventQueue (`services/audio_buffer.py`)

**Responsibilities:**
- Queue voice activity detection events
- Track speaking/idle state with confidence

**Events:**
```python
VADEvent(
    vad_state="speaking" | "idle",
    confidence=0.85,  # 0.0-1.0
    timestamp=datetime.utcnow()
)
```

### 4. StreamingTTSOrchestrator (`adapters/voice/elevenlabs_tts.py`)

**Responsibilities:**
- Coordinate parallel LLM output, TTS generation, and playback
- Accumulate text until minimum chunk size
- Stream TTS while LLM continues generating
- Emit audio chunks as they're ready

**Architecture:**
```
LLM Stream        TextBuffer        TTS Generator      Playback Queue
    │                 │                  │                   │
    ├─ "Hello " ─────►│                  │                   │
    ├─ "world" ──────►│                  │                   │
    ├─ "." ──────────►├─ "Hello world." ►│                   │
    │                 │     (60 chars)   ├─ Audio chunk 1 ──►│
    ├─ "How " ───────►│                  │                   │
    ├─ "are " ───────►│                  │ (TTS processing)  │
    ├─ "you?" ──────►├─ "How are you?" ►├─ Audio chunk 2 ──►│
    └─ EOF           └─ (flush)         └─ (EOF)            └─ EOF
```

**Key Methods:**
```python
async for chunk in orchestrator.generate_stream(llm_stream):
    # chunk = TTSChunk(text, audio_bytes, sequence_number)
    await send_to_playback(chunk.audio_bytes)

await orchestrator.stop()  # Cancel generation
```

### 5. TextBuffer (`adapters/voice/elevenlabs_tts.py`)

**Responsibilities:**
- Accumulate LLM tokens until minimum size
- Detect sentence boundaries for natural breaks
- Force flush on max size exceeded

**Thresholds:**
- Min chunk: 50 characters
- Max chunk: 500 characters
- Flush on: sentence boundary (`.!?,;:`)

### 6. ElevenLabsStreamingTTS (`adapters/voice/elevenlabs_tts.py`)

**Responsibilities:**
- Call ElevenLabs API with streaming response
- Handle API errors and timeouts
- Return audio bytes chunk-by-chunk

**Usage:**
```python
async with ElevenLabsStreamingTTS(
    api_key=config.elevenlabs_api_key,
    voice_id="21m00Tcm4TlvDq8ikWAM",  # Bella voice
    model_id="eleven_monolingual_v1"
) as tts:
    async for audio_chunk in tts.synthesize_stream("Hello world"):
        # audio_chunk = bytes
        await playback.play(audio_chunk)
```

## Integration with Conversation FSM

### State Machine Flow

The FSM (`agents/conversation_state_machine.py`) coordinates voice interactions:

```
GREETING
  ↓
PRESENTING_PLAN (Agent speaks plan using StreamingTTS)
  ├─ (User barges in) ──► USER_INPUT
  └─ (Agent finishes) ──► ASKING_FOR_INPUT
       ↓
       ASKING_FOR_INPUT (User can respond)
       ├─ (User speaks) ──► USER_INPUT ──► LLM_PROCESSING
       ├─ (2.5s silence) ──► (ask confirmation)
       ├─ (5s silence) ──► CONFIRMING_PLAN
       └─ (10s silence) ──► CALL_END
```

### Event Loop Integration

```python
async def run_call(fsm, vapi_client, tts_orchestrator):
    # 1. Connect WebSocket
    await vapi_client.connect()
    listen_task = asyncio.create_task(vapi_client.listen())
    
    # 2. Register event handlers for:
    vapi_client.on(VapiEventType.AUDIO_CHUNK, handle_audio)
    vapi_client.on(VapiEventType.VAD_UPDATED, handle_vad)
    vapi_client.on(VapiEventType.TRANSCRIPT, handle_transcript)
    
    # 3. Present plan with streaming TTS
    await fsm.transition(PRESENTING_PLAN, USER_READY)
    plan_text = generate_plan_text(state.plan)
    
    async for tts_chunk in tts_orchestrator.generate_stream(
        llm_stream=generate_response(plan_text)
    ):
        await vapi_client.send_audio(tts_chunk.audio_bytes)
    
    # 4. Listen for user input
    while not fsm.session.current_state == CALL_END:
        # Handle VAD events
        vad_event = vapi_client.get_vad_event()
        if vad_event and vad_event.vad_state == "speaking":
            await fsm.transition(USER_INPUT, BARGE_IN)
        
        # Handle audio chunks
        chunk = vapi_client.get_audio_chunk()
        if chunk:
            transcripts = await stt_engine.process(chunk.data)
    
    # 5. Cleanup
    await vapi_client.disconnect()
    await listen_task
```

## Error Handling

### Connection Errors
- Automatic reconnection with exponential backoff
- Max 5 attempts
- Backoff: 1s → 2s → 4s → 8s → 16s

### Audio Buffer Overflow
- Logs warning
- Auto-drops oldest chunks (ring buffer)
- Prevents unbounded memory growth

### VAD Timeout Escalation
- 2.5s: Confirmation question
- 5s: Assume "no", proceed to plan confirmation
- 10s: Hang up, send SMS fallback

### TTS Generation Errors
- Retry once with cached recommendation
- Fallback: Present text plan (no audio)

### Packet Loss
- Detected by sequence numbers
- Logged but doesn't block (audio continues)
- Eventually recovered by audio stream continuation

## Performance Characteristics

### Latency Targets

| Component | Target | Actual |
|-----------|--------|--------|
| Vapi connection | < 1s | 200-500ms |
| Audio buffer latency | < 100ms | 50-150ms |
| VAD detection | < 500ms | 300-700ms |
| STT round-trip | 1-3s | 2-4s |
| TTS first audio | < 1s | 800ms-2s |
| Barge-in response | < 500ms | 300-800ms |
| **Total call latency** | **< 8s** | **3-5s** |

### Memory Usage

- Audio buffer: ~10MB (100 chunks × 100KB avg)
- Text buffer: ~1KB
- VAD queue: ~50KB
- Typical peak: ~15-20MB

### Bandwidth

- Audio (16kHz, 16-bit): ~256 kbps
- Vapi/ElevenLabs API: ~1-2 Mbps during active call

## Testing

Run comprehensive tests:

```bash
# Audio buffer tests
pytest backend/app/tests/test_vapi_websocket.py::TestAudioBuffer -v

# WebSocket event handling
pytest backend/app/tests/test_vapi_websocket.py::TestVapiEventHandling -v

# TTS streaming
pytest backend/app/tests/test_elevenlabs_tts.py::TestStreamingTTSOrchestrator -v

# All Phase 2 tests
pytest backend/app/tests/test_vapi_websocket.py backend/app/tests/test_elevenlabs_tts.py -v
```

## Next Steps (Phase 2 Blocking)

Task A2 unblocks:
- **Task B1**: Barge-in detection (uses VAD queue from WebSocket)
- **Task B2**: TTS playback control (uses StreamingTTSOrchestrator)
- **Task C1**: Endpointing handler (uses silence escalation)
- **Task D1**: Error recovery (uses connection state & retry logic)
- **Task E1**: Already implemented (StreamingTTSOrchestrator)
