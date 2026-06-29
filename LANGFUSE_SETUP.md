# Langfuse Setup – Quick Start (5 minutes)

Get production observability working immediately.

## Step 1: Create Langfuse Account

1. Go to https://langfuse.com
2. Click **"Get Started"**
3. Sign up with email or GitHub
4. Verify email

**Done!** You now have a Langfuse workspace.

---

## Step 2: Get API Keys

1. After sign up, you'll be on the **Projects** page
2. Click **Settings** (gear icon, top-right)
3. Go to **API Keys**
4. You'll see:
   - **Public Key** (starts with `pk_pub_`)
   - **Secret Key** (starts with `sk_prod_`)
5. Copy both

```bash
Example:
Public Key:  pk_pub_xxxxxxxxxxxxx
Secret Key:  sk_prod_xxxxxxxxxxxxx
```

---

## Step 3: Add to .env

Open `.env` and update:

```bash
# Langfuse (Observability)
LANGFUSE_PUBLIC_KEY=pk_pub_xxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk_prod_xxxxxxxxxxxxx
LANGFUSE_ENABLED=true
```

Save the file.

---

## Step 4: Start Backend

```bash
python -m app.main
```

You should see:
```
INFO: Langfuse tracer initialized
INFO: Uvicorn running on http://0.0.0.0:8000
```

---

## Step 5: Trigger a Test Run

In another terminal:

```bash
curl -X POST http://localhost:8000/api/test-run \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-1"
  }'
```

Response:
```json
{
  "run_id": "abc-123-def",
  "status": "completed",
  "plan": {...}
}
```

**Important:** Note the `run_id` – this is what you'll search for in Langfuse.

---

## Step 6: View in Langfuse

1. Go to https://cloud.langfuse.com
2. You should see your workspace is now populated
3. Click **Traces** (top menu)
4. You'll see your test run with the `run_id`
5. Click on it to see the full trace tree:

```
daily_plan_run (run_id)
├── PlanningAgent
│   ├── fetch_google_calendar
│   ├── fetch_apple_calendar
│   ├── fetch_weather
│   └── merge_calendars
├── ConversationAgent
│   └── generate_summary
├── EvaluationAgent
│   └── score_plan
└── [success]
```

---

## What You're Seeing

### Trace View

- **Input** – What was passed to the agent
- **Output** – What the agent returned
- **Latency** – How long it took (in milliseconds)
- **Metadata** – Tags: `user_id`, `run_id`, `environment`, etc.

### Spans (Sub-steps)

Click on a span (like `fetch_weather`) to see:
- **Input** – e.g., `{lat: 37.7749, lon: -122.4194}`
- **Output** – e.g., `{temp: 72, condition: "sunny"}`
- **Latency** – e.g., 145ms

### Errors

If a tool failed, you'll see:
- **Level** = "error"
- **Error message** – What went wrong
- Stack trace (if available)

---

## Next: Create a Dashboard

### 1. Daily Plan Quality

1. Go to **Dashboards** (top menu)
2. Click **+ New Dashboard**
3. Name it: "Plan Quality"
4. Add a chart:
   - **Type:** Distribution
   - **Metric:** Filter by `langfuse_metadata.agent = "EvaluationAgent"`
   - **Y-axis:** Score

5. Run a few test plans to see the dashboard populate

### 2. Latency Breakdown

1. New dashboard: "Agent Latency"
2. Add chart:
   - **Type:** Bar chart
   - **Group by:** `name` (agent names)
   - **Metric:** Latency (ms)

This shows which agents are slowest.

### 3. Error Tracking

1. New dashboard: "Errors"
2. Filter:
   - `level = "error"`
3. Watch for patterns in which tools fail

---

## What Gets Traced Automatically

✅ **Already traced:**
- Agent execution (Planning, Conversation, Evaluation)
- Tool calls (Calendar, Weather, Maps adapters)
- LLM calls (if implemented)
- Errors and exceptions
- Latency for each step

⏸️ **To add later:**
- Custom scoring (quality feedback)
- User engagement metrics
- Model performance tracking
- Cost analysis

---

## Verify It's Working

Check these logs in your backend:

```bash
# Should appear when backend starts
INFO: Langfuse tracer initialized
```

Check Langfuse dashboard:

1. Go to https://cloud.langfuse.com/traces
2. You should see traces appearing in real-time
3. If empty, check:
   - Are `LANGFUSE_*` keys correct in `.env`?
   - Did you run a test with `/api/test-run`?
   - Is backend outputting "Langfuse tracer initialized"?

---

## Troubleshooting

### "Langfuse tracer initialized" doesn't appear

```bash
# Check .env has these set
grep LANGFUSE .env

# Should output:
# LANGFUSE_PUBLIC_KEY=pk_pub_...
# LANGFUSE_SECRET_KEY=sk_prod_...
# LANGFUSE_ENABLED=true
```

If any are missing, add them and restart backend.

### Dashboard is empty

```bash
# Trigger a test run
curl -X POST http://localhost:8000/api/test-run

# Wait 5 seconds (batching + network)

# Check Langfuse Traces page
```

Langfuse batches traces for efficiency, so there's a 2-5 second delay.

### "Failed to initialize Langfuse"

Check:
- API keys are correct (no typos)
- API keys haven't been revoked (regenerate in settings if needed)
- Network connectivity (can you reach https://api.langfuse.com?)

### High latency on requests

Langfuse is async and adds ~10-50ms per request:
- Network latency to send traces
- Minimal CPU overhead

To reduce:
- Use sampling (trace only 10% of requests)
- Switch to self-hosted Langfuse (lower latency)

---

## Production Tips

### 1. Use Environment-Based Sampling

```python
# In config.py or main.py
if settings.environment == "production":
    # Sample 10% of production traces
    import random
    enabled = random.random() < 0.1
else:
    # Trace everything in development
    enabled = True

tracer = LangfuseTracer(..., enabled=enabled)
```

### 2. Monitor Langfuse Health

```python
# Ensure Langfuse connectivity
try:
    tracer.client.get_trace("test")
except Exception as e:
    logger.error(f"Langfuse unreachable: {e}")
    tracer.enabled = False  # Fall back to local logging
```

### 3. Set Retention Policies

In Langfuse dashboard → Settings:
- Dev/test traces: **7 days**
- Production traces: **90 days**
- Evaluation feedback: **indefinite**

This balances storage cost with debugging capability.

### 4. Create Alerts

In Langfuse → Alerts:
- Alert if any trace has `level = "error"`
- Alert if latency > 5000ms
- Alert if error rate > 5%

Send to Slack or email.

---

## View Your First Trace

You're all set! 🎉

```bash
# Terminal 1: Start backend
python -m app.main

# Terminal 2: Trigger a test run
curl -X POST http://localhost:8000/api/test-run

# Then:
# 1. Go to https://cloud.langfuse.com/traces
# 2. Click on the trace with your run_id
# 3. Explore the trace tree!
```

That's it. Langfuse is now tracking everything.

---

## Next Steps

- Create custom dashboards (see above)
- Add custom evaluation scores (read LANGFUSE_INTEGRATION_GUIDE.md)
- Set up alerts and monitoring
- Review traces regularly for performance issues

**Questions?** See:
- `LANGFUSE.md` – Full configuration
- `LANGFUSE_INTEGRATION_GUIDE.md` – Best practices
- https://docs.langfuse.com – Official Langfuse docs
