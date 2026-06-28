# DailyOps AI – Project Context for Claude

## Project Summary

**DailyOps AI** is a voice-first productivity assistant that:
1. Calls you at 6 AM
2. Reviews your Google Calendar + Apple iCal events
3. Checks weather and commute
4. Asks if you have missing plans
5. Recommends workout timing and leave time
6. Sends an iMessage summary

This is a **portfolio project** for AI Implementation Manager / Forward Deployed AI roles. Prioritize:
- ✅ Sturdy architecture (adapter pattern, clear separation)
- ✅ Complete debug logging and instrumentation
- ✅ Multiple integrations (calendars, voice, messaging)
- ✅ Demoability (working endpoints, dashboard)

**NOT** a production SaaS—focus on showcasing architectural thinking and clean code.

---

## Architecture Decisions

### 1. Adapter Pattern
All external integrations (calendar, messaging, voice, weather) use base classes + concrete implementations. This allows:
- Easy testing with mocks
- Swapping implementations without touching core logic
- Clear boundaries between agent logic and external services

### 2. LangGraph for Agent Orchestration
Three agents:
1. **Planning Agent** – Gathers data
2. **Conversation Agent** – Interacts with user
3. **Evaluation & Debug Agent** – Scores run, logs issues

Shared state (`AgentState`) flows through the graph.

### 3. Debug Logger as a Service
All agent actions log to Supabase `debug_logs` table with:
- `run_id` (unique call identifier)
- `agent_name`, `event_type`, `latency_ms`
- `input_payload`, `output_payload`, `error`

This enables the dashboard to reconstruct the entire call flow.

### 4. Normalized Calendar Schema
Calendar events from Google + iCal are normalized into `CalendarEvent` with:
- `source` (identifies provider)
- `title`, `start_time`, `end_time`, `location`, `attendees`

Deduplication logic in `CalendarMerger` handles:
- Exact duplicates (same title + time)
- Similar titles + same time
- Location-based matching

### 5. Supabase for Everything
- Database (all tables)
- Auth (optional, built-in)
- Row-level security (users see only their data)
- Webhooks (can trigger functions on inserts/updates)

---

## Current Status

**Completed**:
1. ✅ Supabase schema (all tables + indexes)
2. ✅ FastAPI skeleton with config
3. ✅ Adapter pattern (base + implementations)
4. ✅ Normalized schemas (CalendarEvent, DailyPlanData, etc.)
5. ✅ Debug logger service
6. ✅ Calendar merge + deduplication logic
7. ✅ Planning agent stub
8. ✅ Tests for calendar merge
9. ✅ Requirements.txt
10. ✅ Comprehensive README

**Stubs (ready for implementation)**:
- Google Calendar adapter (API calls)
- Apple iCal adapter (AppleScript or .ics parsing)
- Weather & Maps adapters
- Conversation agent
- Evaluation agent
- Vapi webhook handlers
- Dashboard API routes
- Frontend components

---

## Key Files

### Backend Structure
```
backend/app/
├── main.py                    # FastAPI app
├── config.py                  # Settings
├── agents/
│   ├── state.py              # Shared schemas + AgentState
│   ├── planning_agent.py      # Data gathering
│   ├── conversation_agent.py  # (stub)
│   └── evaluation_agent.py    # (stub)
├── adapters/
│   ├── calendar/              # Google + Apple iCal
│   ├── messaging/             # iMessage + Twilio
│   └── voice/                 # Vapi
├── services/
│   ├── logger.py             # Debug logger
│   └── calendar_merge.py      # Dedup logic
└── tests/
    └── test_calendar_merge.py
```

### Database
`migrations/001_initial_schema.sql` contains:
- `users`, `user_preferences`
- `daily_plans`, `calendar_events`
- `calls`, `messages`, `tool_calls`
- `debug_logs`, `evaluation_scores`, `memory_items`

All with RLS enabled.

---

## How to Continue

### For implementing agents:
1. Start with `Conversation Agent` (simplest—just formats plan as text)
2. Then `Evaluation Agent` (scores plan quality)
3. Wire them into LangGraph in `agents/graph.py`

### For wiring Vapi:
1. Create `api/vapi_webhooks.py` to handle call state changes
2. Implement `VapiAdapter.initiate_call()` to actually call Vapi API
3. Add POST endpoint for Vapi to POST transcript/status back

### For dashboard:
1. Start with debug logs page (simplest—just query `debug_logs` table)
2. Add daily plans page
3. Add settings page

### Environment Setup for Local Dev:
- Copy `.env.template` to `.env`
- Fill in mock values for keys you don't have yet
- Supabase: `pip install supabase` and set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`
- For testing: `pytest app/tests/ -v`

---

## Testing Strategy

- Unit tests for `CalendarMerger` dedup logic (done)
- Unit tests for adapter behaviors (pending)
- Integration tests for the full planning flow (pending)
- Mock `DebugLogger` in tests to avoid Supabase calls

---

## Code Standards

- **Async/await** throughout (FastAPI + Supabase are async)
- **Type hints** on all functions and returns
- **Pydantic BaseModel** for all data schemas
- **Structured logging** via `DebugLogger` (never print())
- **No hardcoded values** (use `.env` + `config.py`)
- **Clean adapters** – implementations only talk to external APIs, not to each other
- **One responsibility per class** – agents do orchestration, adapters do integration, services do logic

---

## Success Criteria (MVP)

- ✅ Trigger a test run
- ✅ Fetch mock/real Google Calendar + iCal events
- ✅ Generate structured daily plan
- ✅ Log all tool calls and steps
- ✅ Send summary via iMessage bridge or Twilio
- ✅ Dashboard shows plan + debug logs
- ✅ Code is clean enough to discuss in an Avoca AI Implementation Manager interview

---

## Notes for Future Contributors

- **Calendar adapters**: Apple iCal is notoriously tricky. Consider using `.ics` file parsing instead of AppleScript for reliability.
- **Conversation agent**: Will need real LLM calls (Claude/GPT). For MVP, hardcode responses.
- **Evaluation agent**: Simple scoring (did we use weather? did we log errors?) is enough for MVP.
- **Deployment**: Use Railway for backend, Vercel for frontend (both have free tiers + easy Supabase integration).
- **Memory**: Cognee integration is future work—Supabase memory table is enough for MVP.
