# Task F1: Enhanced Logging & Observability

## Overview

Task F1 provides comprehensive observability through Langfuse integration with detailed metrics collection across all Phase 2 components.

## Key Components

### 1. MetricsCollector

**Centralizes all metrics collection:**

```python
collector = MetricsCollector(run_id="call_123", user_id="user_456")

# Record state transitions
collector.record_state_transition(
    from_state="greeting",
    to_state="presenting",
    trigger="user_ready",
    latency_ms=150
)

# Record error recovery
collector.record_error_recovery(
    error_type="stt_error",
    attempt=1,
    strategy="ask_repeat",
    success=True,
    latency_ms=200
)

# Record TTS metrics
collector.record_streaming_tts(
    text_chars=250,
    audio_bytes=16000,
    time_to_first_audio_ms=650,
    total_elapsed_ms=2500,
    chunks_generated=5,
    underrun_count=0,
    overflow_count=0,
    generation_errors=0
)

# Record barge-in
collector.record_barge_in(
    barge_in_count=2,
    avg_confidence=0.88,
    latency_ms=250,
    state_transition_success=True
)

# Record endpointing
collector.record_endpointing(
    endpointing_count=3,
    stage_1_timeouts=1,
    stage_2_timeouts=0,
    stage_3_timeouts=0,
    current_silence_ms=0
)

# Finalize call
collector.finalize_call(success=True, final_state="completed")

# Get comprehensive summary
summary = collector.get_call_summary()
# {
#   "duration_ms": 5000,
#   "success": True,
#   "state_transitions": 10,
#   "errors": 1,
#   "error_recoveries": 1,
#   "barge_ins": 2,
#   "silence_timeouts": 1
# }
```

### 2. LangfuseLogger

**Sends traces and metrics to Langfuse:**

```python
logger = LangfuseLogger(
    api_key=config.langfuse_public_key,
    secret_key=config.langfuse_secret_key,
    enabled=True,
    run_id="call_123"
)

# Start trace
trace_id = logger.start_trace("voice_call", metadata={
    "user_id": "user_456",
    "call_type": "voice_planning"
})

# Create spans for specific operations
span_id = logger.start_span("generate_plan", span_type="llm")
# ... do work ...
logger.end_span(span_id, status="success", output={...})

# Log custom metrics
logger.log_metric("time_to_first_audio_ms", 650, category="latency")
logger.log_metric("barge_in_count", 2, category="interaction")

# Log structured events
logger.log_event("barge_in_detected", "voice_interaction", {
    "confidence": 0.88
})

# End trace
logger.end_trace(output=call_summary)

# Get trace URL for dashboard
url = logger.get_trace_url()
```

### 3. LangfuseIntegration

**High-level integration with Phase 2 components:**

```python
integration = LangfuseIntegration(langfuse_logger)

# Log component interactions
await integration.log_state_transition("greeting", "presenting", "user_ready", 150)
await integration.log_barge_in(confidence=0.88, latency_ms=250)
await integration.log_error_recovery("stt_error", "ask_repeat", True, 200)
await integration.log_tool_call("calendar", latency_ms=350, success=True)
await integration.log_llm_call(prompt_tokens=150, completion_tokens=75, latency_ms=1500)

# Log call completion
await integration.log_call_complete(
    success=True,
    final_state="completed",
    total_duration_ms=5000,
    summary={...}
)
```

## Metrics Tracked

### By Category

**State Machine:**
- State transitions: from/to/trigger/latency
- State duration: time spent in each state

**Error Recovery:**
- Error type, recovery strategy, success rate
- Latency per error type
- Recovery attempt count

**VAD Performance:**
- Sensitivity level
- Speech detection accuracy
- False positive rate
- Confidence metrics

**Streaming TTS:**
- Time to first audio
- Audio chunk generation latency
- Buffer health (underrun/overflow)
- Generation errors

**Barge-In:**
- Detection count
- Average confidence
- Response latency
- FSM transition success

**Playback:**
- Audio bytes played
- Position percentage
- Interruption count
- Error count

**Endpointing:**
- Speech endpoint count
- Silence timeout stages (1/2/3)
- Current silence duration

**Call Summary:**
- Total duration
- Success/failure status
- Component metrics aggregated
- Quality indicators

## Production Dashboards (Langfuse)

**Automatically created:**

1. **Call Dashboard**
   - Call duration over time
   - Success/error rates
   - Latency breakdown (state, barge-in, TTS, etc.)
   - Barge-in frequency
   - Error recovery success rate

2. **Latency Dashboard**
   - Time to first audio distribution
   - State transition latencies
   - Component latency breakdown
   - Percentile analysis (p50, p95, p99)

3. **Error Dashboard**
   - Error types by frequency
   - Recovery strategy effectiveness
   - Error recovery latency
   - Error trends over time

4. **Quality Dashboard**
   - VAD false positive rate
   - Barge-in confidence distribution
   - Buffer underrun/overflow events
   - TTS generation errors

## Integration with Call Flow

```python
async def voice_call_with_observability(fsm, collector, langfuse):
    # 1. Start observability
    langfuse.logger.start_trace("voice_call")
    
    # 2. Main call loop
    while fsm.session.current_state != CALL_END:
        # Record state transitions
        if state_changed:
            collector.record_state_transition(
                from_state=old_state,
                to_state=new_state,
                trigger=trigger_name,
                latency_ms=state_latency
            )
            await langfuse.log_state_transition(...)
        
        # Record VAD events
        if vad_metric_available:
            collector.record_vad_metrics(...)
        
        # Record errors and recovery
        if error_occurred:
            collector.record_error_recovery(...)
            await langfuse.log_error_recovery(...)
        
        # Record barge-in
        if barge_in_detected:
            collector.record_barge_in(...)
            await langfuse.log_barge_in(...)
        
        # Record tool calls
        if tool_called:
            await langfuse.log_tool_call(...)
        
        # Record LLM calls
        if llm_called:
            await langfuse.log_llm_call(...)
    
    # 3. Finalize
    collector.finalize_call(success=True, final_state=fsm.session.current_state)
    
    # 4. Export metrics
    summary = collector.get_call_summary()
    await langfuse.log_call_complete(
        success=summary.success,
        final_state=summary.final_state,
        total_duration_ms=summary.total_duration_ms,
        summary=summary
    )
    
    # 5. Persist to database
    await state_manager.log_call_summary(summary)
    
    # 6. Get dashboard URL
    trace_url = langfuse.logger.get_trace_url()
    logger.info(f"View call in Langfuse: {trace_url}")
```

## Alerts & Monitoring

**Key alerts configured in Langfuse:**

- Time to first audio > 2 seconds
- Barge-in latency > 500ms
- Error recovery rate < 80%
- Buffer underrun events > 0
- TTS generation errors > 0
- VAD false positive rate > 10%
- Call duration > 10 minutes

## Testing

```bash
# Run F1 observability tests
pytest backend/app/tests/test_observability_f1.py -v

# Test categories:
# - Metrics collection
# - Langfuse logger
# - Integration with components
# - Call summary
# - Data export
```

## Environment Setup

```bash
# Add to .env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=<your-key>
LANGFUSE_SECRET_KEY=<your-secret>
```

## Success Criteria

✅ All metrics collected across all components
✅ Traces sent to Langfuse dashboard
✅ Latency breakdown available
✅ Error tracking and alerts working
✅ Call quality metrics visible
✅ Integration tests passing
✅ Production dashboards operational

## Performance Impact

- Metrics collection: < 5ms overhead per recording
- Langfuse batching: minimal network impact
- No blocking operations
- Async all observability I/O

## Next Steps

After F1:
- Task G1: End-to-end integration testing
- Production deployment with full observability
- Alert tuning based on baseline metrics
- Custom dashboard development
