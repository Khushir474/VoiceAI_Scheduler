# Voice Conversation Design & Implementation

Complete specification for DailyOps AI voice interaction, from user speech to agent response, including latency, error handling, and conversational UX.

---

## Table of Contents

1. [Voice Flow Architecture](#voice-flow-architecture)
2. [Timing & Latency](#timing--latency)
3. [Voice Activity Detection (VAD)](#voice-activity-detection-vad)
4. [Conversation State Machine](#conversation-state-machine)
5. [Conversation Design Patterns](#conversation-design-patterns)
6. [State Management](#state-management)
7. [Error Handling](#error-handling)
8. [Observability & Logging](#observability--logging)
9. [Implementation Roadmap](#implementation-roadmap)

---

## Voice Flow Architecture

### Complete Request-Response Cycle

```
USER SPEAKS
    ↓
[1] VAD Detection: "User is speaking"
    ↓
[2] STT (Speech-to-Text)
    Input: Audio stream
    Output: "I have a dentist appointment at 2pm"
    Latency: 1-3 seconds (streaming) or 2-5 seconds (batch)
    ↓
[3] LLM Processing
    Input: Transcript + conversation context + user state
    Processing: Reason about intent, decide if tool call needed
    Output: Tool calls + response text
    Latency: 1-2 seconds
    ↓
[4] Tool Execution (if needed)
    Tools: Calendar merge, recommendation logic, etc.
    Latency: 0.5-2 seconds per tool
    ↓
[5] Response Generation
    LLM creates final response based on tool outputs
    Latency: 0.5-1 second
    ↓
[6] TTS (Text-to-Speech)
    Input: "Got it. I've added the dentist appointment to your calendar..."
    Output: Audio stream
    Latency: 0.5-2 seconds (streaming) or 3-5 seconds (batch)
    ↓
[7] Playback
    User hears response
    Duration: Variable (usually 10-30 seconds)
    ↓
[8] VAD Detection: "Agent finished speaking, listening for user..."
    ↓
USER SPEAKS AGAIN or SILENCE
    ↓
[Decision]
    - Barge-in: User interrupted → stop playback, go to [2]
    - Endpointing: Silence > 2.5s → end call or ask clarification
    - Continue: User speaks → go to [2]
```

### Latency Breakdown (Typical)

```
1. VAD Detection:        100-500ms
2. STT:                  1,000-5,000ms  ← Longest single component
3. LLM Processing:       1,000-2,000ms
4. Tool Calls:           500-2,000ms
5. Response Generation:  500-1,000ms
6. TTS:                  500-5,000ms    ← Longest single component
                         ───────────
Total:                   4-16 seconds

Goal:
- < 5s STT + LLM + tools (user doesn't notice delay)
- < 2s TTS (smooth playback)
- Streaming for both STT + TTS (perceived latency < 3s)
```

### Streaming vs Batch

**STT Streaming** (Recommended):
- Audio comes in chunks → transcribed in real-time
- Perceived latency: 1-2 seconds
- Implementation: Vapi handles streaming STT (ElevenLabs)

**STT Batch** (Fallback):
- Wait for silence → transcribe entire utterance
- Perceived latency: 2-5 seconds
- Implementation: Fall back if streaming unavailable

**TTS Streaming** (Recommended):
- Generate text chunks → synthesize + play in parallel
- Perceived latency: 0.5-2 seconds
- Implementation: ElevenLabs streaming API

**TTS Batch** (Fallback):
- Wait for full response → synthesize entire → play
- Perceived latency: 3-5 seconds
- Implementation: Fall back if streaming unavailable

---

## Timing & Latency

### Acceptable Latency Budgets

```
Component               Target       Acceptable    Unacceptable
─────────────────────────────────────────────────────────────
STT (streaming)         1-2s         <3s           >5s
LLM Processing          1s           <2s           >3s
Tool Calls              0.5s         <2s           >5s
TTS (streaming)         0.5-1s       <2s           >3s
─────────────────────────────────────────────────────────────
Total (P95):            3-4s         <8s           >12s
```

### Optimization Strategies

**Parallel Processing** (where possible):
```
Sequence (slow):
  STT → LLM → Tool Calls → Response Generation → TTS
  ~8 seconds

Parallel (faster):
  STT ──────────┐
                ├─→ LLM + Tool Calls → Response Generation → TTS
                │
  Start TTS generation as soon as first words available
  ~3 seconds
```

**Streaming TTL (Time-To-Live)**:
```
TTS doesn't wait for full LLM response.
Instead:
1. LLM starts generating response
2. After first 50 chars → send to TTS
3. TTS starts playing
4. Continue streaming text to TTS
5. User hears response while agent still generating
```

**Caching & Shortcuts**:
```
Known Responses (no LLM needed):
- "Do you have anything else to plan?" (simple confirmation)
- "Your plan is ready. Sending to iMessage." (summary)
- "Sorry, I didn't catch that. Say again?" (error recovery)

Predictive Preparation:
- Pre-load user preferences at call start
- Pre-fetch calendar events before processing
- Pre-compute common recommendations
```

---

## Voice Activity Detection (VAD)

### What is VAD?

Detects when the user **starts** and **stops** speaking.

### Responsibilities

```
1. Detect Speech Start
   - User begins speaking → alert STT to start recording
   - Should be sensitive (avoid false negatives)
   - Should ignore background noise

2. Detect Speech End (Endpointing)
   - User stops speaking → trigger processing
   - Should use timeout (don't wait forever for silence)
   - Should ignore brief pauses within utterance

3. Detect Agent Speaking
   - Agent is talking → block STT (don't record response)
   - User shouldn't interrupt (or implement barge-in)
```

### Implementation (Vapi Handles This)

Vapi has built-in VAD via:
- **Provider**: OpenAI Whisper or ElevenLabs STT
- **VAD Model**: Silero VAD (open source, low latency)
- **Tuning**: Adjustable sensitivity + endpointing timeout

**Key Settings**:
```
VAD Config:
  silence_timeout_ms: 2500  # End speech after 2.5s silence
  speech_start_threshold: 0.2  # Sensitivity to speech start
  speech_end_threshold: 0.8   # Confidence to end speech
  
Adjustments for DailyOps:
  - Lower sensitivity if environment is noisy
  - Higher endpointing timeout if user thinks a lot
  - Different settings per user (in user_preferences)
```

### Edge Cases

```
1. Long Pause Mid-Thought
   User: "I have a... [3 second pause] ...dentist appointment"
   Solution: Multiple endpointing (ask "did you finish?" after 2.5s silence)

2. Background Noise
   User: [dog barking] "...schedule..." [more barking]
   Solution: Adjust VAD sensitivity, retry STT if confidence low

3. Overlapping Speech
   User: "I have..." Agent: "Got it..." User: "...at 2pm"
   Solution: Barge-in (stop agent, re-process user's speech)
```

---

## Conversation State Machine

### States & Transitions

```
START
  ↓
[GREETING] ("Good morning! Let me organize your day.")
  ↓
[PRESENTING_PLAN] (Agent speaks calendar, weather, recommendations)
  ├─ User barges in → [USER_INPUT]
  ├─ Agent finishes → [ASKING_FOR_INPUT]
  └─ Timeout → [TIMEOUT_ERROR]
  ↓
[ASKING_FOR_INPUT] ("Do you have anything else I should know?")
  ├─ User responds (yes) → [USER_INPUT]
  ├─ User responds (no) → [CONFIRMING_PLAN]
  ├─ User barges in → [USER_INPUT]
  └─ Silence > 5s → [CONFIRMING_PLAN] (assume no input)
  ↓
[USER_INPUT] (Processing user's spoken request)
  ├─ STT success → [LLM_PROCESSING]
  ├─ STT low confidence → [CLARIFICATION_NEEDED]
  ├─ No speech detected → [SILENCE_ERROR]
  └─ Network error → [ERROR_RETRY]
  ↓
[LLM_PROCESSING] (Agent reasoning)
  ├─ Tool calls needed → [TOOL_EXECUTION]
  ├─ No tools needed → [RESPONSE_GENERATION]
  └─ Invalid format → [LLM_ERROR]
  ↓
[TOOL_EXECUTION] (Calendar merge, recommendations, etc.)
  ├─ Success → [RESPONSE_GENERATION]
  ├─ Partial success → [RESPONSE_GENERATION] (with fallback)
  └─ Failure → [TOOL_ERROR]
  ↓
[RESPONSE_GENERATION] (LLM creates response from tool results)
  ├─ Success → [SPEAKING_RESPONSE]
  └─ Error → [LLM_ERROR]
  ↓
[SPEAKING_RESPONSE] (TTS playing)
  ├─ User barges in → [USER_INPUT]
  ├─ Finish normally → [CONFIRMING_PLAN] or [SENDING_SUMMARY]
  └─ TTS error → [TTS_ERROR]
  ↓
[CONFIRMING_PLAN] ("Your final plan is ready...")
  ↓
[SENDING_SUMMARY] (Send iMessage)
  ├─ Success → [CALL_END]
  └─ Failure → [MESSAGE_ERROR]
  ↓
[CALL_END] ("Have a great day!")
  ↓
END

ERROR PATHS:
────────────
[STT_ERROR] → Retry once → [CLARIFICATION_NEEDED] → [USER_INPUT]
[SILENCE_ERROR] → Ask user to repeat → [USER_INPUT]
[LLM_ERROR] → Use fallback response → [RESPONSE_GENERATION]
[TOOL_ERROR] → Use cached/default values → [RESPONSE_GENERATION]
[TTS_ERROR] → Log error, continue with text summary → [CALL_END]
[MESSAGE_ERROR] → Retry + SMS fallback → [CALL_END]
[TIMEOUT_ERROR] → End call with apology → [CALL_END]
```

### State Persistence

```python
class ConversationState(BaseModel):
    call_id: str                 # Vapi call ID
    run_id: str                  # DailyOps run ID
    user_id: str                 # User ID
    
    current_state: str           # Current FSM state
    timestamp: datetime          # When state changed
    
    # Data accumulated during call
    raw_transcript: list[dict]   # Full conversation
    calendar_events: list        # User's events
    weather_data: WeatherData    # Weather
    commute_data: CommuteData    # Commute
    user_input: str              # User's spoken additions
    
    # Agent decisions
    tools_called: list[dict]     # Which tools, results
    plan_generated: DailyPlanData
    evaluation_score: float
    
    # Errors encountered
    errors: list[dict]           # Each error logged
    
    # Observability
    latencies: dict              # Latency for each step
    stt_confidence: float        # Confidence of transcription
```

---

## Conversation Design Patterns

### 1. Greeting

**Goal**: Establish context, build rapport

```
Agent: "Good morning! I'm DailyOps. Let me organize your day."
Latency: Immediate (pre-recorded or simple TTS)
Next: PRESENTING_PLAN
```

### 2. Presenting the Plan

**Goal**: Deliver information concisely

```
Agent: "You have 3 meetings: standup at 9, lunch at 12, review at 3.
Weather is sunny and 72 degrees. 
You have a 30-minute commute to work.
I recommend a 30-minute run before work.
You should leave by 8:30 to be early.
Do you have anything else I should know about?"

Design Principles:
✅ Short sentences (< 10 words each)
✅ One concept per sentence
✅ Pause between sections (1-2 seconds)
✅ Actionable recommendations (not just facts)
✅ Clear call-to-action at end (question asking for input)

Latency Target: < 20 seconds total (STT + LLM + tools + TTS)
```

### 3. Asking for Input

**Goal**: Give user opportunity to add missing info

```
Agent: "Do you have anything else I should know about?"

User Responses (expected):
✅ "No" / "Nothing" → End call, send summary
✅ "Yes, I have a dentist appointment at 2pm" → Process & re-plan
✅ "Actually, I have another meeting" → Process & re-plan
❌ [silence for 5 seconds] → Assume "no", proceed to confirmation
❌ "Um... maybe?" → Ask "You're not sure? Tell me yes or no."

Latency Target: 5 second silence timeout, quick response < 2s
```

### 4. Processing User Input

**Goal**: Update plan based on user's addition

```
User: "I have a dentist appointment at 2 PM"

Process:
1. STT → "I have a dentist appointment at two PM"
2. LLM → Extract: type=event, title=Dentist, time=14:00
3. Validation → Does 2pm conflict with other events?
4. Plan Update → Add to calendar, re-compute recommendations
5. TTS Response → "Got it. I've added your dentist appointment at 2 PM."

Latency Target: 3-5 seconds end-to-end
Confidence Handling: If STT confidence < 0.7 → Ask "Did you say 2 PM?"
```

### 5. Confirmation

**Goal**: Finalize plan, prepare for summary

```
Agent: "Your plan is ready. Here's what I'm sending you:

Calendar:
• 9:00 AM - Standup
• 12:00 PM - Team Lunch  
• 2:00 PM - Dentist (added)
• 3:00 PM - Code Review

Weather: Sunny, 72°F

Commute: 30 minutes, leave by 8:30 AM

Workout: 30-min run before work

Have a great day!"

Design:
✅ Restate entire plan (confirm we understood correctly)
✅ Highlight user's additions (show we listened)
✅ Give final call-to-action
✅ Keep upbeat tone

Latency Target: < 30 seconds total speech
```

### 6. Error Recovery

**If STT failed**:
```
Agent: "Sorry, I didn't catch that. Could you say that again?"
Next: Retry STT, re-process

If LLM confused:
```
Agent: "I'm not sure I understand. Did you want to add an event 
or change your wake-up time?"
Next: User clarifies

If API failed:
```
Agent: "I'm having trouble with [service]. Let me use what I know 
and get back to you later."
Next: Continue with cached data, note error for later review
```

### 7. Barge-In (User Interrupts)

**When user speaks while agent is speaking**:
```
Agent: "You have 3 meetings: standup at—"
User: "I need to leave early today"

Action:
1. Vapi detects barge-in
2. Stop TTS playback immediately
3. Start STT for user input
4. Process: "I need to leave early today"
5. LLM updates plan (change leave-time recommendation)
6. Re-generate response: "Got it. Updated leave time to 7:30 AM."

Latency: < 500ms to stop playback, < 2s to respond
```

---

## State Management

### Persistent User State

**`user_preferences` Table** (in Supabase):
```python
class UserPreferences(BaseModel):
    user_id: str
    
    # Conversation preferences
    stf_silence_timeout: int = 2500  # ms before ending speech
    vad_sensitivity: float = 0.5     # 0.1-1.0
    
    # Behavioral preferences
    wake_up_time: str = "06:00"
    workout_duration: int = 30       # minutes
    workout_preference: str = "morning"  # morning/evening/flexible
    commute_buffer: int = 15         # minutes before first meeting
    preferred_messaging: str = "imessage"  # imessage/sms
    
    # Conversation style
    max_call_duration: int = 300     # seconds (5 min)
    prefers_summary_only: bool = False
    allow_recommendations: bool = True
    
    # User behavior history
    user_usually_leaves: int | None  # minutes before recommended
    prefers_short_workouts: bool = False
    gets_stressed_by_long_calls: bool = False
```

### Session State

```python
class CallSession(BaseModel):
    call_id: str           # Vapi call ID
    run_id: str           # DailyOps run ID
    user_id: str
    session_started: datetime
    
    # User state (for personalization)
    user_prefs: UserPreferences  # Loaded from DB
    user_history: dict    # Past behavior patterns
    
    # Call state
    state: str            # Current FSM state
    barge_in_count: int   # How many times user interrupted
    errors: list[dict]    # Errors during this call
    
    # Plan data
    plan: DailyPlanData   # Current plan
    updates: list[dict]   # User's updates to plan
    
    # Timing
    latencies: dict       # Latency for each component
    total_duration: int   # seconds
```

### Memory Strategy

**Short-term** (during call):
- Store in ConversationState
- Access for follow-up reasoning
- Example: "User just said they have a dentist appointment"

**Medium-term** (per day):
- Store in daily_plans table
- Evaluate end of call
- Example: "User added 1 event, took 8 min, score 0.85"

**Long-term** (across days):
- Store in memory_items table (with Cognee later)
- Build user profile
- Example: "User prefers morning workouts", "User usually leaves 10 min early"

---

## Error Handling

### STT Errors

```
Scenario: STT returns low confidence (< 0.6)
├─ Confidence 0.4-0.6: Ask for confirmation
│  Agent: "Did you say 2 PM?"
│  User: "Yes" / "No"
├─ Confidence 0.2-0.4: Ask to repeat
│  Agent: "Sorry, I didn't catch that. Can you say it again?"
│  Retry STT once
└─ Confidence < 0.2: Fallback to typed input
   Agent: "I'm having trouble understanding. Would you like to 
   text me or try again?"
   Next: End call, send summary, user texts

Logging:
{
  "error_type": "stt_low_confidence",
  "confidence": 0.45,
  "transcript": "dentist appointment...",
  "recovery": "asked_for_confirmation"
}
```

### Silence Errors

```
Scenario: User doesn't respond (timeout)
├─ First 2.5s: Natural endpointing (wait for more input)
├─ At 2.5s: Agent confirms "I didn't hear anything, did you want to add something?"
├─ At 5s: Agent decides (assume "no")
│  Action: Proceed to [CONFIRMING_PLAN]
└─ At 10s: Hang up
   Agent: "I'll send you a summary. Have a great day!"
   Next: Send iMessage, end call

Edge case - Breathing/Thinking sounds:
- Low-volume sounds might trigger STT but return no text
- Result: Empty transcript
- Action: Ask "Did you say something?"

Logging:
{
  "error_type": "silence_timeout",
  "silence_duration_ms": 5000,
  "recovery": "assumed_no_input"
}
```

### LLM Errors

```
Scenario: LLM returns invalid format
├─ Wrong JSON structure → Parse error
│  Recovery: Use fallback response
│  Agent: "Let me save what I know for now..."
├─ Hallucination (makes up facts) → Detected by evaluation agent
│  Recovery: Flag in debug logs, don't present to user
└─ Timeout (> 3s) → Use cached recommendation
   Recovery: "I'll get back to you on that one..."

Logging:
{
  "error_type": "llm_invalid_format",
  "input": {...},
  "error": "KeyError: 'plan_type'",
  "recovery": "used_fallback_response"
}
```

### Tool Call Errors

```
Scenario: Calendar merge fails
├─ Network error → Retry once, then use cached calendar
│  Recovery: "Using your calendar from earlier..."
├─ Parsing error → Log, use basic recommendation
│  Recovery: "I'll stick with the default recommendation..."
└─ Invalid data → Skip tool, don't mention

Scenario: Weather API timeout
├─ First try: Fail over to forecast cache
│  Recovery: "Using yesterday's forecast..."
├─ Second try: Use generic statement
│  Recovery: "Have an umbrella just in case..."
└─ Logging: Mark as degraded service

Logging:
{
  "error_type": "tool_error",
  "tool": "calendar_merge",
  "error": "ConnectionTimeout",
  "recovery": "used_cached_calendar",
  "impact": "plan_quality_degraded"
}
```

### TTS Errors

```
Scenario: TTS has high latency (> 2s)
├─ First response: Wait (user expectation set)
├─ Subsequent: Pre-generate text while speaking previous
│  Parallel TTS: Start TTS as soon as 50 chars available

Scenario: TTS returns corrupted audio
├─ Recovery: Retry once
├─ If retry fails: Send text summary instead
   Agent: "Having audio trouble. Sending your plan via iMessage."

Logging:
{
  "error_type": "tts_latency",
  "duration_ms": 2500,
  "impact": "delayed_response"
}
```

### Network Errors

```
Scenario: Vapi call disconnects
├─ During active conversation → Log, can't recover
├─ During quiet moment → Reconnect, continue
├─ Just before sending summary → Retry 3x, then SMS fallback

Logging:
{
  "error_type": "network_disconnect",
  "when": "during_ltm_processing",
  "recovery": "ended_call",
  "fallback": "sms_summary"
}
```

### Message Sending Errors

```
Scenario: iMessage fails
├─ First try: Use iMessage bridge
├─ Second try: Fall back to Twilio SMS
├─ Notify user: "Sending via text instead..."

Scenario: Both fail
├─ Recovery: Email fallback
├─ Notify user: "I'll email you your plan"
├─ Logging: Alert ops team

Logging:
{
  "error_type": "message_send_failed",
  "imessage_result": {"status": "failed", "error": "bridge_unavailable"},
  "sms_result": {"status": "failed", "error": "rate_limited"},
  "email_fallback": "sent",
  "user_notified": true
}
```

---

## Observability & Logging

### Call Transcript (What to Log)

```python
class CallTranscript(BaseModel):
    call_id: str
    run_id: str
    user_id: str
    timestamp: datetime
    
    # Full conversation
    messages: list[dict] = [
        {
            "role": "agent",
            "content": "Good morning! Let me organize your day.",
            "timestamp": "2025-03-01T06:00:00Z",
            "duration_ms": 2000,  # TTS playback time
            "confidence": 1.0,    # How confident in this response
        },
        {
            "role": "user",
            "content": "I have a dentist appointment at 2 PM",
            "timestamp": "2025-03-01T06:02:00Z",
            "duration_ms": 3000,  # How long user talked
            "confidence": 0.92,   # STT confidence
            "raw_audio_duration_ms": 3200,
        },
        {
            "role": "agent",
            "content": "Got it. I've added your dentist appointment at 2 PM.",
            "timestamp": "2025-03-01T06:04:00Z",
            "duration_ms": 2500,
        },
    ]
```

### Tool Calls (What to Log)

```python
class ToolCall(BaseModel):
    id: str
    call_id: str
    timestamp: datetime
    
    tool_name: str
    agent_name: str
    
    # Input
    input_payload: dict
    input_size_bytes: int
    
    # Execution
    started_at: datetime
    ended_at: datetime
    duration_ms: int  # Total latency
    
    # Output
    output_payload: dict
    output_size_bytes: int
    
    # Status
    status: str  # "success", "error", "timeout"
    error: str | None
    
    # Observability
    retry_count: int
    fallback_used: bool
    fallback_reason: str | None
```

### Agent Decisions (What to Log)

```python
class AgentDecision(BaseModel):
    call_id: str
    timestamp: datetime
    
    decision_point: str  # "handle_silence", "process_input", "error_recovery"
    
    # Context
    user_state: UserPreferences
    conversation_state: str  # Current FSM state
    last_n_messages: list[dict]  # Recent conversation
    
    # Decision
    action_taken: str  # "asked_confirmation", "ended_call", "retried"
    reasoning: str     # Why this decision
    confidence: float  # How confident in this decision
    
    # Result
    user_response: str | None  # What user said next (if applicable)
    outcome: str  # "success", "needs_clarification", "error"
```

### Errors (What to Log)

```python
class ErrorLog(BaseModel):
    call_id: str
    timestamp: datetime
    
    # Error details
    error_type: str  # "stt_error", "lml_error", "tool_error", "network_error"
    error_message: str
    error_context: dict
    
    # Recovery
    recovery_attempted: str
    recovery_result: str  # "success", "partial", "failed"
    
    # Impact
    severity: str  # "info", "warning", "error", "critical"
    user_affected: bool
    user_notified: bool
    notification_method: str  # "voice", "text"
    
    # Resolution
    auto_resolved: bool
    manual_intervention_needed: bool
    ops_alert: bool
```

### Latency Tracking

```python
class LatencyLog(BaseModel):
    call_id: str
    timestamp: datetime
    
    # Per-component latency
    vad_detection_ms: int
    stt_ms: int
    llm_processing_ms: int
    tool_calls_ms: dict  # {tool_name: latency_ms}
    response_generation_ms: int
    tts_ms: int
    
    # Aggregates
    total_request_ms: int  # STT → Response ready
    total_response_ms: int  # TTS playback
    total_cycle_ms: int    # STT → User hears response
    
    # Analysis
    bottleneck: str  # Which component was slowest
    exceeded_targets: list[str]  # Which components exceeded targets
```

### Call Summary (What to Log After Call)

```python
class CallSummary(BaseModel):
    call_id: str
    run_id: str
    user_id: str
    
    # Timing
    call_started: datetime
    call_ended: datetime
    call_duration: int  # seconds
    speaking_time_agent: int  # Total agent speech
    speaking_time_user: int   # Total user speech
    silent_time: int  # Silence during call
    
    # Conversation quality
    barge_in_count: int
    clarification_requests: int
    errors_encountered: int
    
    # Plan generated
    plan_events_count: int
    user_additions_count: int
    plan_quality_score: float
    
    # System quality
    stt_avg_confidence: float
    tool_call_success_rate: float
    error_recovery_rate: float
    
    # User satisfaction (future: add surveys)
    user_feedback_score: float | None  # 1-5
    user_feedback_text: str | None
```

---

## Implementation Roadmap

### Phase 1: Foundation (MVP, Done)

✅ Vapi integration (basic call flow)
✅ Planning agent (gather data)
✅ Conversation agent (format response)
✅ Evaluation agent (score run)
✅ Debug logging to Supabase
✅ Langfuse tracing

### Phase 2: Voice UX (Next 4 weeks)

**Implement**:
- [ ] Complete conversation state machine
- [ ] Barge-in handling (user interrupts agent)
- [ ] Endpointing tuning (when to end speech)
- [ ] Error recovery (all 6 error types)
- [ ] Streaming TTS (start playback before full response)
- [ ] Silence handling (5s timeout → assume "no")

**Testing**:
- [ ] 100+ test calls with real users
- [ ] Measure latency end-to-end
- [ ] Measure STT/TTS errors
- [ ] Measure user satisfaction

### Phase 3: Personalization (Weeks 5-8)

**Implement**:
- [ ] User preference storage (wake time, workout pref, etc.)
- [ ] Behavioral memory (user usually leaves 10 min early)
- [ ] Conversation style personalization (adjust sentence length)
- [ ] Error recovery based on user history

**Testing**:
- [ ] A/B test different conversation styles
- [ ] Measure improvement in user satisfaction
- [ ] Track adoption of recommendations

### Phase 4: Advanced (Weeks 9+)

**Implement**:
- [ ] Real LLM calls (Claude/GPT for reasoning)
- [ ] Dynamic plan adjustment (user feedback → better recommendations)
- [ ] Smart silence handling (user thinking vs. done)
- [ ] Contextual clarification (ask specific questions, not generic)
- [ ] Predictive actions (if user always declines workout recommendation, stop suggesting)

---

## Success Metrics

### Technical

| Metric | Target | Why |
|--------|--------|-----|
| STT accuracy | >95% | User understands correctly |
| Call latency (end-to-end) | <8s for response | Doesn't feel slow |
| Error recovery rate | >90% | System is robust |
| Uptime | >99.9% | Reliable for daily use |

### User Experience

| Metric | Target | Why |
|--------|--------|-----|
| Avg call duration | 3-5 min | Not too long |
| Barge-in rate | <20% of calls | Users don't get frustrated |
| User satisfaction | >4.0/5.0 | People actually like it |
| Plan adoption | >80% follow recommendation | Plan is useful |

### Conversational Quality

| Metric | Target | Why |
|--------|--------|-----|
| Clarification requests | <1 per call | Not confusing |
| Error recovery success | >90% | Graceful failures |
| Perceived naturalness | >4.0/5.0 | Feels like talking to human |

---

This specification enables building a voice-first experience that feels natural, responds quickly, and recovers gracefully from errors.
