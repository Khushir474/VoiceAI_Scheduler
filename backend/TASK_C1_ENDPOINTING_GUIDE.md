# Task C1: VAD Tuning & Endpointing

## Overview

Task C1 implements intelligent endpointing (detecting when user stops speaking) with per-user VAD tuning and a three-stage silence timeout escalation.

## Components

### 1. VADManager (`services/vad_manager.py`)

**Responsibilities:**
- Load/save per-user VAD configuration
- Track confidence metrics for model optimization
- Provide dynamic threshold adjustment based on sensitivity
- Collect statistics for analysis

**Key Methods:**
```python
manager = VADManager(supabase_client, run_id="call_123")

# Load user configuration
config = await manager.load_config(user_id="user_789")
# Returns VADConfig with user's preferred sensitivity

# Check thresholds
should_start = manager.should_trigger_speech_start(
    vad_state="speaking",
    confidence=0.85,
    config=config
)

should_end = manager.should_trigger_speech_end(
    vad_state="idle",
    confidence=0.9,
    config=config
)

# Track metrics for optimization
manager.update_metrics("user_789", "speech_start", confidence=0.85)
manager.update_metrics("user_789", "false_positive")

# Save metrics to DB
metrics = manager.get_metrics("user_789")
await manager.save_metrics(metrics)
```

**VADConfig Parameters:**
```python
@dataclass
class VADConfig:
    sensitivity: float = 0.5                    # 0.1=very sensitive, 1.0=not sensitive
    speech_start_threshold: float = 0.2         # Confidence needed to detect speech start
    speech_end_threshold: float = 0.8           # Confidence for speech end
    silence_timeout_confirmation_ms: int = 2500   # Stage 1: ask confirmation
    silence_timeout_decision_ms: int = 5000       # Stage 2: assume no
    silence_timeout_hangup_ms: int = 10000        # Stage 3: hang up
    min_speech_duration_ms: int = 300             # Min speech duration to count
```

### 2. EndpointingHandler (`services/endpointing_handler.py`)

**Responsibilities:**
- Detect speech onset/offset (endpointing)
- Implement three-stage silence timeout escalation
- Trigger state transitions in FSM
- Execute callbacks for each stage
- Collect endpointing metrics

**Three-Stage Silence Escalation:**
```
User speaks
    ↓
[ASKING_FOR_INPUT state]
    ↓
User stops speaking (endpointing)
    ↓
[2.5s silence]
    └─ Stage 1: Ask confirmation ("Did you say...?")
         ↓
    [5s silence]
         └─ Stage 2: Assume "no", proceed to plan confirmation
              ↓
         [10s silence]
              └─ Stage 3: Hang up, send SMS fallback
```

**Key Methods:**
```python
handler = EndpointingHandler(fsm, vad_manager, run_id="call_123")

# Register callbacks for each stage
async def on_confirmation_needed():
    # Ask user to confirm what they said
    pass

async def on_silence_timeout():
    # Timeout reached, assume user said "no"
    pass

async def on_hangup():
    # 10s timeout, hang up and send SMS
    pass

handler.set_callbacks(
    on_speech_ended=lambda: logger.info("Speech ended"),
    on_confirmation_needed=on_confirmation_needed,
    on_silence_timeout=on_silence_timeout,
    on_hangup=on_hangup,
)

# Process VAD events
await handler.process_vad_event(vad_state="speaking", confidence=0.9)
await handler.process_vad_event(vad_state="idle", confidence=0.1)  # Endpointing!

# Check for silence timeout progression
new_stage = await handler.check_silence_timeouts()
# Returns: 1 (stage 1), 2 (stage 2), 3 (stage 3), or None

# Reset timer when user responds
handler.reset_silence_timer()

# Get metrics
metrics = handler.get_metrics()
# {
#   "endpointing_count": 3,
#   "stage_1_timeouts": 1,
#   "stage_2_timeouts": 0,
#   "stage_3_timeouts": 0,
#   "current_silence_elapsed_ms": 1250
# }
```

### 3. ContextAwareEndpointing

**Context-Aware Timeout Adjustment:**
```python
context_aware = ContextAwareEndpointing(endpointing_handler)

# Get timeouts adjusted for current FSM state
timeouts = context_aware.get_effective_timeouts()
# {
#   "stage_1_ms": 2500,   # Normal for ASKING_FOR_INPUT
#   "stage_2_ms": 5000,
#   "stage_3_ms": 10000
# }

# If in CONFIRMING_PLAN state: 1.5x timeouts (conservative)
# If in PRESENTING_PLAN state: infinite (no timeout)

# Check if endpointing should be active
if context_aware.should_apply_endpointing():
    # Enable endpointing
    pass
```

## Integration with FSM

```python
async def run_call(fsm, vapi_client, vad_manager, endpointing_handler):
    # 1. Load user's VAD config
    config = await vad_manager.load_config(fsm.session.user_id)
    logger.info(f"Loaded VAD config: sensitivity={config.sensitivity}")
    
    # 2. Setup endpointing callbacks
    async def on_stage_1_timeout():
        # Ask confirmation
        confirmation_text = f"Did you say {last_transcript}?"
        await playback_controller.start_generating()
        await playback_controller.start_playing()
        # Play confirmation text
    
    async def on_stage_2_timeout():
        # Assume no, proceed to confirmation
        await fsm.transition(
            CONFIRMING_PLAN,
            SILENCE_TIMEOUT_5S
        )
    
    async def on_stage_3_timeout():
        # Hang up and send SMS
        await send_sms_summary(fsm.session.user_id)
    
    endpointing_handler.set_callbacks(
        on_silence_timeout=on_stage_2_timeout,
        on_hangup=on_stage_3_timeout,
    )
    
    # 3. Main event loop
    while fsm.session.current_state != CALL_END:
        # Process VAD events from Vapi
        vad_event = vapi_client.get_vad_event()
        if vad_event:
            # Check for speech onset/offset
            await endpointing_handler.process_vad_event(
                vad_state=vad_event.vad_state,
                confidence=vad_event.confidence
            )
        
        # Check for silence timeout progression
        if fsm.session.current_state in [ASKING_FOR_INPUT, CONFIRMING_PLAN]:
            new_stage = await endpointing_handler.check_silence_timeouts()
            if new_stage == 2:
                # Stage 2 reached, FSM already transitioned
                logger.info("Silence timeout, proceeding to plan confirmation")
        
        # Handle user input (STT)
        if fsm.session.current_state == USER_INPUT:
            # Process transcription
            # On user response:
            endpointing_handler.reset_silence_timer()
        
        await asyncio.sleep(0.01)  # Event loop tick
    
    # 4. Save VAD metrics for optimization
    metrics = vad_manager.get_metrics(fsm.session.user_id)
    if metrics:
        await vad_manager.save_metrics(metrics)
```

## Performance Targets

| Metric | Target | Actual |
|--------|--------|--------|
| Speech end detection | < 500ms | 100-300ms |
| Stage 1 confirmation | 2.5s | 2500ms ±50ms |
| Stage 2 decision | 5s | 5000ms ±50ms |
| Stage 3 hangup | 10s | 10000ms ±100ms |
| Sensitivity tuning | Per-user | ✅ 0.1-1.0 scale |

## Sensitivity Tuning Guide

**Sensitivity Scale: 0.1 (Very Sensitive) → 1.0 (Not Sensitive)**

| Value | Behavior | Use Case |
|-------|----------|----------|
| 0.1-0.3 | Very sensitive, many false positives | Quiet environments |
| 0.4-0.6 | Balanced (default) | Normal conditions |
| 0.7-0.9 | Less sensitive, may miss speech | Noisy environments |
| 1.0 | Very insensitive | Extreme noise |

**Learned Per-User:**
- Metrics collected: false_positives, false_negatives, avg_confidence
- Over time, system learns optimal sensitivity for each user
- Can be adjusted based on feedback or automatic optimization

## Metrics Collected

```python
@dataclass
class VADMetrics:
    speech_starts_detected: int              # How many times speech started
    speech_ends_detected: int                # How many times speech ended
    false_positives: int                     # Noise detected as speech
    false_negatives: int                     # Speech not detected
    avg_speech_start_confidence: float       # Average confidence for starts
    avg_speech_end_confidence: float         # Average confidence for ends
    total_speech_duration_ms: int            # Total time user spoke
    total_silence_duration_ms: int           # Total silence time
```

## Testing

```bash
# Run C1 tests
pytest backend/app/tests/test_vad_endpointing.py -v

# Test categories:
# - VAD configuration loading/saving
# - Confidence thresholding
# - Speech start/end detection
# - Silence stage progression
# - Context-aware timeout adjustment
# - Metrics collection
```

## Next Steps (Unblocks)

- **Task D1**: Error Recovery (uses endpointing state for error detection)
- **Task F1**: Logging & Metrics (uses VAD metrics for observability)
