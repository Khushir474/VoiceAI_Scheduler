# Task D1: Error Recovery Framework

## Overview

Task D1 implements comprehensive error recovery for 6 different error types with specific recovery strategies for each.

## 6 Error Types & Recovery Strategies

### 1. STT Errors (Speech-to-Text)
**Error Types:**
- `STT_LOW_CONFIDENCE` (0.2-0.6 confidence)
- `STT_NO_SPEECH` (no speech detected)

**Recovery Strategies:**
```
Confidence 0.4-0.6: Ask confirmation ("Did you say 'X'?")
Confidence 0.2-0.4: Ask to repeat ("Could you say that again?")
Confidence < 0.2: Retry or fallback to text input
```

### 2. Silence Errors
**Error Types:**
- `SILENCE_ERROR` (unexpected silence)
- `SILENCE_TIMEOUT` (timeout waiting for response)

**Recovery Strategies:**
```
< 5s silence: Prompt user to speak ("I'm listening...")
> 5s silence: Assume "no" and proceed to confirmation
> 10s silence: Hang up and send SMS fallback
```

### 3. LLM Errors (Language Model)
**Error Types:**
- `LLM_TIMEOUT` (response too slow)
- `LLM_INVALID_FORMAT` (response not valid JSON)
- `LLM_HALLUCINATION` (LLM made up information)

**Recovery Strategies:**
```
Timeout: Use cached response from previous call
Invalid format: Use template/fallback response
Hallucination: Flag and skip (don't present to user)
```

### 4. Tool Errors (API calls)
**Error Types:**
- `TOOL_TIMEOUT` (API timeout)
- `TOOL_ERROR` (API returned error)
- `TOOL_PARSE_ERROR` (couldn't parse response)

**Recovery Strategies:**
```
Timeout: Use cached data from previous call
Network error: Retry with exponential backoff
Parse error: Skip tool, continue without it
```

### 5. TTS Errors (Text-to-Speech)
**Error Types:**
- `TTS_TIMEOUT` (synthesis too slow)
- `TTS_CORRUPTED` (audio corrupted)

**Recovery Strategies:**
```
Timeout: Skip TTS, present plan as text
Corrupted audio: Retry once, then fallback to text
High latency: Continue (expected with streaming)
```

### 6. Network Errors
**Error Types:**
- `NETWORK_ERROR` (connection failed)
- `NETWORK_TIMEOUT` (request timeout)
- `NETWORK_DISCONNECT` (connection lost)

**Recovery Strategies:**
```
Disconnect: Attempt to reconnect
Timeout: Retry with exponential backoff (max 3x)
Connection error: Fallback to SMS summary
```

## Key Components

### ErrorRecoveryStrategy

**Main orchestrator for all error recovery:**

```python
recovery = ErrorRecoveryStrategy(fsm, state_manager, logger_service)

# Handle an error
result = await recovery.handle_error(
    error=exception,
    error_type=ErrorType.STT_LOW_CONFIDENCE,
    context={
        "confidence": 0.45,
        "transcript": "hello world"
    }
)

# Result tells you what recovery was used
# {
#   "success": True,
#   "strategy_used": "ask_confirmation",
#   "message": "Did you say 'hello world'?",
#   "fallback_used": False
# }
```

### RetryStrategy

**Exponential backoff for retries:**

```python
retry = RetryStrategy(base_backoff_ms=100, max_retries=3)

# Get backoff time for attempt N
backoff_ms = retry.get_backoff_ms(1)  # 100ms
backoff_ms = retry.get_backoff_ms(2)  # 200ms
backoff_ms = retry.get_backoff_ms(3)  # 400ms

# Wait before retry
await retry.wait_for_retry(1)  # Wait 100ms
```

**Backoff Schedule:**
```
Attempt 1: 100ms
Attempt 2: 200ms
Attempt 3: 400ms
(capped at 8 seconds)
```

## Integration Example

```python
async def handle_voice_interaction(fsm, logger_service):
    recovery = ErrorRecoveryStrategy(
        fsm=fsm,
        logger_service=logger_service
    )
    
    # Process user input
    try:
        # Call STT API
        transcript = await stt_service.transcribe(audio_data)
        confidence = transcript.get("confidence", 0.0)
        
        # Check confidence
        if confidence < 0.5:
            # Low confidence - trigger recovery
            result = await recovery.handle_error(
                error="STT low confidence",
                error_type=ErrorType.STT_LOW_CONFIDENCE,
                context={
                    "confidence": confidence,
                    "transcript": transcript["text"]
                }
            )
            
            if result.success:
                if result.strategy_used == "ask_confirmation":
                    # Ask user to confirm
                    user_confirmed = await ask_confirmation(transcript["text"])
                    if not user_confirmed:
                        # Retry STT
                        pass
                elif result.strategy_used == "ask_repeat":
                    # Ask user to repeat
                    await prompt_user("Could you say that again?")
                    # Retry
            else:
                # Recovery failed, move to error state
                await fsm.handle_error(result.message)
    
    except Exception as e:
        # Unhandled error
        result = await recovery.handle_error(
            error=e,
            error_type=ErrorType.STT_ERROR,
            context={}
        )
```

## Error Metrics & Tracking

```python
# Get error metrics
metrics = recovery.get_metrics()
# {
#   "total_errors": 5,
#   "total_recoveries": 4,
#   "errors_by_type": {
#       "stt_low_confidence": 2,
#       "silence_error": 2,
#       "tool_timeout": 1
#   },
#   "recoveries_by_type": {
#       "ask_confirmation": 2,
#       "cached_data": 1,
#       "retry": 1
#   }
# }
```

## Severity Levels

**Critical** (immediate action needed):
- Network disconnect
- LLM timeout
- TTS corrupted
- Call-ending errors

**Error** (handle gracefully):
- Tool timeout
- Network timeout
- TTS timeout

**Warning** (inform user):
- STT low confidence
- Silence error
- Tool parse error

## Testing

```bash
# Run error recovery tests
pytest backend/app/tests/test_error_recovery.py -v

# Test categories:
# - STT error recovery (medium/low/critical confidence)
# - Silence error recovery (early/prolonged)
# - LLM error recovery (timeout/invalid/hallucination)
# - Tool error recovery (timeout/parse/network)
# - TTS error recovery (timeout/corrupted)
# - Network error recovery (disconnect/timeout)
# - Error tracking & metrics
# - Retry strategy backoff
```

## Success Criteria

✅ All 6 error types have recovery strategies
✅ Errors are tracked and logged
✅ Fallback responses work when APIs fail
✅ Exponential backoff prevents thundering herd
✅ User experience remains smooth despite errors
✅ Error metrics help identify optimization opportunities

## Performance Targets

| Metric | Target |
|--------|--------|
| STT recovery latency | < 500ms |
| Tool fallback latency | < 100ms |
| Network retry backoff | 100ms → 200ms → 400ms |
| Error tracking overhead | < 10ms |
| Total error handling | < 1s |

## Next Steps

After D1, remaining Phase 2 work:
- Task E1: Streaming TTS refinements (validation with real audio)
- Task F1: Enhanced logging & metrics (Langfuse integration)
- Task G1: End-to-end integration testing
