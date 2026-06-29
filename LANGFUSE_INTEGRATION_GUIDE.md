# Langfuse Integration Guide – Best Practices

This guide walks through setting up and using Langfuse tracing in DailyOps AI following industry best practices.

## Quick Start

### 1. Create Langfuse Account

```bash
# Sign up at https://langfuse.com
# Choose: Cloud (free tier) or Self-hosted
```

### 2. Get API Keys

1. Go to **Settings → API Keys**
2. Copy your **Public Key** and **Secret Key**

### 3. Add to .env

```bash
LANGFUSE_PUBLIC_KEY=pk_pub_xxxxx
LANGFUSE_SECRET_KEY=sk_prod_xxxxx
LANGFUSE_ENABLED=true
```

### 4. Install Dependencies

```bash
pip install langfuse
```

### 5. Start Backend

```bash
python -m app.main
```

Langfuse will automatically collect traces!

---

## Architecture Overview

### Trace Hierarchy

Every daily plan run creates a **trace tree**:

```
daily_plan_run (trace: run_id)
├── planning_agent (span)
│   ├── fetch_google_calendar (span)
│   ├── fetch_apple_calendar (span)
│   ├── fetch_weather (span)
│   ├── fetch_commute (span)
│   └── merge_calendars (span)
├── conversation_agent (span)
│   ├── llm_call_summary (generation)
│   └── llm_call_questions (generation)
├── evaluation_agent (span)
│   ├── score_plan_quality (span)
│   └── detect_hallucinations (span)
└── messaging (span)
    └── send_imessage_or_sms (span)
```

### Key Components

1. **Trace** – Top-level (run_id)
   - Represents one daily plan execution
   - Contains all spans
   - Has metadata: user_id, date, environment

2. **Span** – Agent/tool step
   - Represents one operation
   - Has input/output
   - Measures latency
   - Can be nested

3. **Generation** – LLM call
   - Special span for LLM interactions
   - Tracks tokens, cost, model
   - Captures prompt and completion

4. **Score** – Quality metric
   - User-facing quality score (0-1)
   - Can mark as good/bad
   - Enables training feedback

---

## Usage Examples

### 1. Trace an Agent

```python
from app.services.langfuse_tracer import LangfuseTracer

tracer = LangfuseTracer(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    enabled=settings.langfuse_enabled
)

# Start a trace for this run
trace = tracer.trace_agent(
    agent_name="PlanningAgent",
    run_id="run-123",
    user_id="user-456"
)

# Add spans
trace.span(
    name="fetch_calendar",
    input_data={"user_id": "user-456", "date": "2025-01-15"},
    output_data={"event_count": 3, "events": [...]},
    latency_ms=245
)

# End the trace
trace.end(output_data={"status": "success", "events_merged": 3})

# Flush to Langfuse
tracer.flush()
```

### 2. Trace a Tool Call

```python
tool_trace = tracer.trace_tool_call(
    tool_name="GoogleCalendarAdapter.get_events",
    run_id="run-123",
    agent_name="PlanningAgent",
    input_data={"date": "2025-01-15", "user_id": "user-456"}
)

# Do the work...
events = await calendar_adapter.get_events(...)

# End with output
tool_trace.end(output_data={"event_count": len(events)})
```

### 3. Trace an LLM Call

```python
llm_trace = tracer.trace_llm_call(
    model="claude-3-5-sonnet",
    messages=[
        {"role": "user", "content": "Summarize this calendar..."}
    ],
    run_id="run-123"
)

# Make LLM call...
response = await client.messages.create(...)

# End with token counts and cost
llm_trace.end(
    completion=response.content[0].text,
    tokens_prompt=response.usage.input_tokens,
    tokens_completion=response.usage.output_tokens,
    cost=calculate_cost(response.usage)
)
```

### 4. Score a Run

```python
# After plan is complete, add evaluation score
trace.score(
    name="plan_quality",
    value=0.85,
    comment="Good recommendations, minor hallucination in weather"
)
```

---

## Best Practices

### 1. Always Use Run IDs

```python
# ✅ Good: Unique ID per execution
trace_id = str(uuid.uuid4())
trace = tracer.trace_agent("PlanningAgent", run_id=trace_id, user_id=user_id)

# ❌ Bad: Reused IDs make traces hard to find
trace = tracer.trace_agent("PlanningAgent", run_id="planning")
```

### 2. Include Meaningful Metadata

```python
# ✅ Good: Rich metadata for filtering/debugging
trace = self.client.trace(
    name="daily_plan_run",
    metadata={
        "run_id": run_id,
        "user_id": user_id,
        "date": date_str,
        "version": "2.1.0",
        "environment": "production",
        "model": "claude-3-5-sonnet",
    }
)

# ❌ Bad: Sparse metadata
trace = self.client.trace(name="run", metadata={})
```

### 3. Always Flush at End

```python
# ✅ Good: Ensures all traces sent before shutdown
try:
    result = await run_daily_plan()
finally:
    tracer.flush()

# ❌ Bad: Traces may not be sent
result = await run_daily_plan()
tracer.flush()  # May happen after process exits
```

### 4. Use Try/Catch with Error Logging

```python
# ✅ Good: Captures errors in trace
try:
    events = await calendar.get_events()
except CalendarError as e:
    trace.span(
        name="fetch_calendar",
        input_data={"user_id": user_id},
        error=str(e)
    )
    raise

# ❌ Bad: Error swallowed
try:
    events = await calendar.get_events()
except CalendarError:
    events = []  # Silent failure, no tracing
```

### 5. Structure Nested Spans

```python
# ✅ Good: Clear hierarchy
planning_trace = tracer.trace_agent("PlanningAgent", run_id, user_id)

# Sub-spans with clear names
planning_trace.span(name="fetch_calendars", ...)
planning_trace.span(name="fetch_weather", ...)
planning_trace.span(name="merge_and_deduplicate", ...)

planning_trace.end()

# ❌ Bad: Flat structure, hard to follow
tracer.trace_tool_call("fetch_calendars", run_id, "PlanningAgent")
tracer.trace_tool_call("fetch_weather", run_id, "PlanningAgent")
tracer.trace_tool_call("merge_and_deduplicate", run_id, "PlanningAgent")
```

### 6. Link Traces Across Agents

```python
# ✅ Good: Same run_id connects all agents
planning_trace = tracer.trace_agent("PlanningAgent", run_id, user_id)
# ... planning work ...
planning_trace.end()

conversation_trace = tracer.trace_agent("ConversationAgent", run_id, user_id)
# ... conversation work ...
conversation_trace.end()

# In Langfuse UI, both traces appear together for this run_id

# ❌ Bad: Different IDs for each agent
planning_trace = tracer.trace_agent("PlanningAgent", "planning-trace", user_id)
conversation_trace = tracer.trace_agent("ConversationAgent", "conv-trace", user_id)
# Traces appear disconnected
```

### 7. Measure Latency Accurately

```python
import time

# ✅ Good: Measure actual operation time
start = time.time()
events = await calendar.get_events(user_id, date)
latency_ms = int((time.time() - start) * 1000)

trace.span(
    name="fetch_calendar",
    input_data={...},
    output_data={...},
    latency_ms=latency_ms
)

# ❌ Bad: Estimate or round
trace.span(name="fetch_calendar", latency_ms=250)  # Guessed
```

### 8. Score Runs for Evaluation

```python
# ✅ Good: Add evaluation score for training data
if plan_was_helpful:
    tracer.client.score(
        trace_id=run_id,
        name="helpfulness",
        value=1,
        comment="User followed all recommendations"
    )
else:
    tracer.client.score(
        trace_id=run_id,
        name="helpfulness",
        value=0,
        comment="User ignored plan, had scheduling conflict"
    )

# ❌ Bad: No feedback loop
# No way to improve model performance
```

---

## Configuration Reference

### .env Variables

```bash
# Langfuse API credentials
LANGFUSE_PUBLIC_KEY=pk_pub_xxxxx
LANGFUSE_SECRET_KEY=sk_prod_xxxxx

# Enable/disable tracing
LANGFUSE_ENABLED=true

# Optional: Self-hosted Langfuse
LANGFUSE_HOST=https://langfuse.example.com
LANGFUSE_BASE_URL=https://api.langfuse.example.com
```

### Settings

```python
# backend/app/config.py
class Settings(BaseSettings):
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_enabled: bool = True
    langfuse_host: str = "https://cloud.langfuse.com"
```

---

## Dashboards to Create

### 1. Daily Plan Quality

- Average plan quality score (0-1)
- Trend over time
- Breakdown by user
- Correlation with weather accuracy

### 2. Agent Performance

- Planning agent latency (ms)
- Conversation agent latency (ms)
- Evaluation agent latency (ms)
- Error rates by agent

### 3. Tool Performance

- Calendar API latency
- Weather API latency
- Maps API latency
- Tool error rates

### 4. LLM Usage & Cost

- Tokens per run (prompt + completion)
- Cost per run
- Model performance (which model produces best scores?)
- Cost trends

### 5. User Engagement

- How many users follow recommendations?
- Average barge-in count
- Message delivery success rate
- User satisfaction trends

---

## Debugging with Langfuse

### Find a Trace

1. Go to https://cloud.langfuse.com/traces
2. Filter by:
   - `run_id` (if you have it)
   - `user_id` (to see all runs for a user)
   - Date range
   - Status (success/error)

### Analyze Performance

1. Click a trace to see the trace tree
2. Expand spans to see:
   - Input/output data
   - Latency breakdown
   - Error messages
3. Compare with other traces

### Track Issues

1. Add tags to traces: `#bug`, `#slow`, `#hallucination`
2. Filter dashboard by tag
3. Create alerts for patterns

---

## Production Best Practices

### 1. Sampling for High Volume

```python
# Don't trace 100% of requests in production
import random

if random.random() < 0.1:  # Sample 10%
    trace = tracer.trace_agent(...)
else:
    trace = tracer.trace_agent(...)  # Still works, no-op
```

### 2. Batch Flushes

```python
# Flush periodically, not after every trace
tracer.flush()  # Every 5 minutes or 1000 traces

# Let SDK batch for efficiency
```

### 3. Monitor Langfuse Health

```python
# Ensure Langfuse is reachable
try:
    tracer.client.get_trace("dummy")
except Exception:
    logger.warning("Langfuse unreachable, tracing disabled")
    tracer.enabled = False
```

### 4. Set Retention

In Langfuse dashboard:
- Development traces: Keep 7 days
- Production traces: Keep 90 days
- Evaluation data: Keep indefinitely

---

## Troubleshooting

### Traces Not Appearing

1. Check `LANGFUSE_ENABLED=true` in .env
2. Verify API keys are correct
3. Run `tracer.flush()` explicitly
4. Check Langfuse dashboard for rate limiting errors
5. Review backend logs for Langfuse errors

### Performance Impact

Langfuse adds ~10-50ms per trace (async, batched):
- Network latency to send traces
- Minimal CPU overhead

If too slow:
- Use sampling (trace 10% of requests)
- Switch to self-hosted Langfuse (lower latency)
- Increase flush interval

### Missing Data

1. Ensure `.end()` is called on all spans
2. Call `tracer.flush()` before process exits
3. Check for exceptions during tracing
4. Verify Langfuse API keys have write permission

---

## Next Steps

1. ✅ Set up Langfuse account and get API keys
2. ✅ Add `LANGFUSE_*` variables to `.env`
3. ✅ Start backend with Langfuse enabled
4. ✅ Generate a daily plan (creates first trace)
5. ✅ View trace in Langfuse dashboard
6. ✅ Create custom dashboards
7. ✅ Set up alerts for errors/latency

See `LANGFUSE.md` for detailed configuration.
