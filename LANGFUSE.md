# Langfuse Integration – Production Observability

DailyOps AI integrates **Langfuse** for deep observability into agent execution, LLM calls, tool calls, latency, and costs.

## What Is Langfuse?

Langfuse is an open-source LLM observability platform that provides:

- **Trace** – Full workflow visualization from start to finish
- **Spans** – Individual agent/tool steps with latency
- **Generations** – LLM call monitoring (tokens, cost, latency)
- **Scores** – Custom evaluation scores and quality metrics
- **Dashboards** – Real-time monitoring and debugging
- **Analytics** – Cost, latency, and performance trends

Perfect for:
- Debugging multi-agent systems
- Monitoring LLM costs
- Tracking performance regressions
- Identifying bottlenecks
- User-facing quality scoring

---

## Setup

### 1. Create Langfuse Account

Visit **https://langfuse.com** and sign up.

### 2. Get API Keys

1. Go to **Settings → API Keys**
2. Copy:
   - `Public Key`
   - `Secret Key`

### 3. Add to Environment

```bash
# .env
LANGFUSE_PUBLIC_KEY=pk_pub_xxx
LANGFUSE_SECRET_KEY=sk_prod_xxx
LANGFUSE_ENABLED=true
```

### 4. Start Backend

```bash
python -m app.main
```

Langfuse will automatically initialize and start collecting traces.

---

## How It Works

### Agent Tracing

Every agent (Planning, Conversation, Evaluation) creates a **trace** with:

```
PlanningAgent (trace)
├── fetch_calendar (span)
│   ├── input: {user_id, date}
│   ├── output: {events_count: 3}
│   └── latency: 245ms
├── fetch_weather (span)
│   ├── output: {condition: "sunny"}
│   └── latency: 127ms
├── fetch_commute (span)
│   ├── output: {duration_minutes: 30}
│   └── latency: 89ms
└── [end]
```

### What Gets Logged

1. **Agent Traces**
   - Agent name, run_id, user_id
   - Start/end time
   - Success/failure
   - Input/output data

2. **Agent Spans** (tool calls)
   - Tool name
   - Input payload
   - Output payload
   - Latency (ms)
   - Error details

3. **Custom Metadata**
   - Events count
   - Weather condition
   - Commute duration
   - Transcript length
   - Evaluation score
   - Hallucinations detected

---

## Viewing Traces

### 1. Dashboard

Go to **Langfuse Dashboard → Traces**

You'll see:
- All runs for your project
- Filter by run_id, date, user, agent
- Click any trace to expand

### 2. Drill Into Run

Click a run to see:
- Timeline of all steps
- Latency for each span
- Input/output for each tool
- Errors with stack traces
- Total duration

### 3. Compare Runs

View metrics:
- Average latency per tool
- Success vs. failure rate
- Most expensive operations
- Slowest steps

---

## Integrations in Code

### Planning Agent

```python
# Spans created:
trace.span("fetch_calendar", input=..., output=..., latency_ms=...)
trace.span("fetch_weather", output=..., latency_ms=...)
trace.span("fetch_commute", output=..., latency_ms=...)
```

### Conversation Agent

```python
# Spans created:
trace.span("format_plan", output=..., latency_ms=...)
trace.span("user_input", input=..., latency_ms=...)
```

### Evaluation Agent

```python
# Spans created:
trace.span("check_tool_usage", output=..., latency_ms=...)
trace.span("detect_hallucinations", output=..., latency_ms=...)
trace.span("calculate_score", output=..., latency_ms=...)
```

---

## Langfuse + Supabase Debug Logs

Both are captured:

| Metric | Langfuse | Supabase |
|--------|----------|----------|
| Trace visualization | ✅ Yes | ✗ No |
| Latency tracking | ✅ Yes | ✅ Yes |
| Full payloads | ✅ Yes | ✅ Yes |
| Error traces | ✅ Yes | ✅ Yes |
| Long-term analytics | ✅ Yes | ✗ No |
| Local queries | ✗ No | ✅ Yes |
| Shared dashboard | ✅ Yes | ✅ Yes |

**Recommendation**: Use **Langfuse for production dashboards**, **Supabase for local debugging**.

---

## Advanced: LLM Call Tracing

When you add real LLM calls (Claude, GPT, etc.), Langfuse can track:

```python
generation = langfuse_tracer.trace_llm_call(
    model="gpt-4",
    messages=[{"role": "user", "content": "..."}],
    run_id=run_id,
)

# ... make LLM call ...

generation.end(
    completion="The response...",
    tokens_prompt=150,
    tokens_completion=80,
    cost=0.0042,
)
```

Langfuse will automatically:
- Track token usage
- Calculate costs based on model pricing
- Monitor latency
- Detect errors

---

## Cost Tracking

Langfuse automatically tracks LLM costs if you configure model pricing:

1. Go to **Settings → Models**
2. Add or update model pricing (e.g., GPT-4, Claude 3, etc.)
3. Langfuse calculates cost per call based on tokens

**In Dashboard:**
```
Total Cost: $12.34
- PlanningAgent: $4.50
- ConversationAgent: $3.80
- EvaluationAgent: $4.04
```

---

## Custom Scoring

Add custom quality scores to traces:

```python
langfuse_tracer.client.score(
    trace_id=run_id,
    name="usefulness",
    value=0.85,
    comment="Calendar merge worked, all events deduplicated",
)
```

Then filter/analyze by score in the dashboard.

---

## Alerts & Notifications

Set up alerts for:
- **Latency thresholds**: Alert if any span > 500ms
- **Error rates**: Alert if > 5% fail
- **Cost anomalies**: Alert if cost > $0.10 per run

Go to **Settings → Alerts** to configure.

---

## Self-Hosting (Optional)

Langfuse can be self-hosted:

```bash
# Docker
docker run -d \
  -e DATABASE_URL=postgresql://... \
  -e NEXTAUTH_SECRET=... \
  -p 3000:3000 \
  langfuse/langfuse:latest
```

Point your client to:
```python
LangfuseTracer(
    public_key=...,
    secret_key=...,
    base_url="https://langfuse.your-domain.com",  # Self-hosted
)
```

---

## Troubleshooting

**Traces not appearing in Langfuse?**

1. Check keys are correct in `.env`
2. Verify `LANGFUSE_ENABLED=true`
3. Run `/api/test-run` to trigger a trace
4. Check Langfuse dashboard → Settings → Status for connection

**Traces delayed?**

Traces are batched and sent every few seconds. Call `langfuse_tracer.flush()` to force immediate send (done automatically at end of run).

**High latency on /api/test-run?**

Langfuse network calls add ~50-100ms per request. This is normal and can be minimized by:
1. Using self-hosted Langfuse on same network
2. Batching traces
3. Running Langfuse in background

---

## Production Best Practices

1. **Sampling**: Send 100% of traces in dev, 10% in production (reduces cost)

2. **PII Masking**: Before sending payloads, mask email addresses, phone numbers

3. **Retention**: Langfuse can archive old traces (Settings → Data Retention)

4. **Alerts**: Set up alerts for:
   - Error spikes
   - Latency regressions
   - Cost anomalies
   - Failed deployments

5. **Dashboards**: Create custom dashboards for:
   - Daily cost trends
   - Agent performance comparison
   - Tool call latency breakdown
   - User feedback correlations

---

## Environment Variables

```bash
# Required
LANGFUSE_PUBLIC_KEY=pk_pub_xxx
LANGFUSE_SECRET_KEY=sk_prod_xxx

# Optional
LANGFUSE_ENABLED=true              # Enable/disable tracing
LANGFUSE_BASE_URL=...              # Self-hosted Langfuse URL
```

---

## Costs

Langfuse pricing:
- **Free tier**: Up to 1M traces/month
- **Hobby**: $19/month (10M traces)
- **Pro**: $99/month (100M traces)
- **Custom**: Enterprise pricing

For DailyOps AI MVP (~100 runs/day), free tier is sufficient.

---

## Next: Combining with LLMs

When you add real LLM calls:

```python
# In planning_agent.py
llm_trace = langfuse_tracer.trace_llm_call(
    model="claude-3-sonnet",
    messages=[{"role": "user", "content": f"Create plan for: {state.plan}"}],
    run_id=state.run_id,
)

# Call Claude API...
response = await client.messages.create(...)

llm_trace.end(
    completion=response.content[0].text,
    tokens_prompt=response.usage.input_tokens,
    tokens_completion=response.usage.output_tokens,
)
```

Langfuse will automatically track cost, latency, tokens.

---

## References

- **Langfuse Docs**: https://docs.langfuse.com
- **Python SDK**: https://github.com/langfuse/langfuse-python
- **Self-Hosting**: https://langfuse.com/self-host
