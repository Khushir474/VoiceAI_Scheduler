# Phase 3 Build Plan: Real APIs & LLMs

## Architecture Overview

Phase 3 replaces mock adapters with production implementations. All adapters follow the existing base-class pattern for testability and swappability.

### Component Dependency Graph

```
┌─────────────────┐
│ Planning Agent  │
└────────┬────────┘
         │
    ┌────┴─────────────────────────────────────┐
    │                                          │
┌───▼──────────┐  ┌────────────┐  ┌─────────┐ │
│ Calendar     │  │ Weather    │  │ Weather │ │
│ Merger       │  │ Adapter    │  │ Cache   │ │
├──────────────┤  ├────────────┤  └─────────┘ │
│ Google Cal   │  │            │              │
│ Apple iCal   │  └────────────┘              │
│              │                              │
│ ↓ normalize  │  ┌────────────┐              │
│   to         │  │ Maps       │              │
│  CalEvent    │  │ Adapter    │              │
└──────────────┘  └────────────┘              │
    │                                         │
    │             ┌──────────────┐            │
    │             │ Vapi Adapter │            │
    │             │ (real calls) │            │
    └─────────────┤              │            │
                  └──────────────┘            │
                                             │
                  ┌────────────┐              │
                  │ Conversation
                  │ Agent       │◄────────────┘
                  │ (Claude/GPT)│
                  └────────────┘
```

### Data Flow

1. **Planning Agent** calls `get_daily_plan(user_id, date)`
2. **Calendar Merger** fetches from Google + Apple, normalizes, deduplicates
3. **Weather Adapter** fetches forecast, applies cache
4. **Maps Adapter** queries commute time
5. **Conversation Agent** receives merged data, calls LLM to generate recommendations
6. **Vapi Adapter** initiates call, streams transcript live
7. All components log to Supabase + Langfuse

---

## Tickets (Parallel Work)

### Ticket 1: Google Calendar OAuth + Adapter
**Owner**: Delegator 1  
**Dependencies**: None (can start immediately)  
**Estimated**: 4–6 hours

**Acceptance Criteria:**
- [ ] OAuth 2.0 token exchange implemented in `config.py`
- [ ] `GoogleCalendarAdapter.get_events_for_date()` fetches real events
- [ ] `GoogleCalendarAdapter.get_events_range()` for multi-day queries
- [ ] Rate limiting handled (backoff + retry)
- [ ] Events saved to `calendar_events` table with `source='google'`
- [ ] Tests pass: `test_google_calendar.py` (15+ test cases)
- [ ] Debug logging captures API latency + error codes

**Deliverables:**
- `app/adapters/calendar/google_calendar.py` — production impl
- `app/tests/test_google_calendar.py` — unit tests
- Updated `.env.template` with Google OAuth keys
- PR with passing tests

---

### Ticket 2: Apple iCal + Calendar Merge Integration
**Owner**: Delegator 2  
**Dependencies**: None (parallel to Ticket 1, but merges with output)  
**Estimated**: 4–6 hours

**Acceptance Criteria:**
- [ ] `.ics` file parsing via `icalendar` library
- [ ] `AppleICalAdapter.parse_ics_file()` extracts all-day + timed events
- [ ] CalDAV URL support (if time permits) or skip in MVP
- [ ] Events normalized to `CalendarEvent` schema
- [ ] `CalendarMerger` deduplicates Google + Apple events
- [ ] Existing tests pass: `test_calendar_merge.py`
- [ ] New tests for Apple import: `test_apple_ical.py` (10+ cases)

**Deliverables:**
- `app/adapters/calendar/apple_ical.py` — .ics parser
- `app/tests/test_apple_ical.py` — unit tests
- Updated `app/services/calendar_merge.py` if needed
- PR with passing tests

---

### Ticket 3: Weather + Maps Adapters
**Owner**: Delegator 3  
**Dependencies**: None (parallel, standalone)  
**Estimated**: 4–5 hours

**Acceptance Criteria:**

**Weather:**
- [ ] OpenWeather API integration (free tier)
- [ ] `WeatherAdapter.get_forecast(lat, lon, days=1)` returns temp, condition, precip
- [ ] Response cached for 1 hour in-memory + Supabase
- [ ] Fallback to cached weather on API error

**Maps:**
- [ ] `MapsAdapter.get_commute_time(home_address, work_address, mode='driving')`
- [ ] Returns ETA, distance, current traffic condition
- [ ] Caches for 30 min (traffic changes frequently)
- [ ] Handles multiple modes (driving, transit)

**Both:**
- [ ] Tests pass: `test_weather_adapter.py`, `test_maps_adapter.py` (20+ cases)
- [ ] Logging to `debug_logs` + `tool_calls`

**Deliverables:**
- `app/adapters/weather.py` — production weather adapter
- `app/adapters/maps.py` — production maps adapter
- `app/tests/test_weather_adapter.py`
- `app/tests/test_maps_adapter.py`
- Updated `.env.template` with API keys
- PR with passing tests

---

### Ticket 4: Vapi Real Endpoint Integration
**Owner**: Delegator 4  
**Dependencies**: None (parallel, but integrates in final flow)  
**Estimated**: 5–7 hours

**Acceptance Criteria:**
- [ ] `VapiAdapter.initiate_call()` creates real Vapi call (not mock)
- [ ] Vapi API key + assistant ID loaded from `.env`
- [ ] WebSocket connection established for live transcript
- [ ] Call state transitions logged (connecting → in_call → ended)
- [ ] Graceful close on user hangup
- [ ] Error handling: connection loss, timeout, invalid state
- [ ] Tests pass: `test_vapi_real_integration.py` (20+ cases, may use mocks for some)
- [ ] Webhook handler in `api/vapi_webhooks.py` receives call completion

**Deliverables:**
- `app/adapters/voice/vapi.py` — updated with real API calls
- `app/api/vapi_webhooks.py` — webhook handlers
- `app/tests/test_vapi_real_integration.py`
- Updated `.env.template` with real Vapi keys
- PR with passing tests

---

### Ticket 5: Conversation Agent (Claude/OpenAI LLM)
**Owner**: Delegator 5  
**Dependencies**: Tickets 1–4 (needs their data inputs)  
**Estimated**: 6–8 hours

**Acceptance Criteria:**
- [ ] `ConversationAgent` takes `AgentState` with calendar + weather + commute
- [ ] Calls Claude API (Anthropic SDK) or OpenAI API
- [ ] Prompt template in `app/agents/prompts.py`
- [ ] Generates structured recommendations (leave time, workout timing, missing events prompt)
- [ ] Handles LLM errors gracefully (fallback responses, retry logic)
- [ ] Conversation loop: agent speaks, waits for user input, refines plan
- [ ] Tests pass: `test_conversation_agent.py` (20+ cases, mostly mocked LLM)
- [ ] Latency tracked: LLM response time logged
- [ ] Integration test with planning agent: `test_planning_flow.py`

**Deliverables:**
- `app/agents/conversation_agent.py` — production impl
- `app/agents/prompts.py` — refined prompts
- `app/tests/test_conversation_agent.py`
- `app/tests/test_planning_flow.py`
- Updated `.env.template` with Claude/OpenAI API keys
- PR with passing tests

---

### Ticket 6: Integration + Error Recovery + Observability
**Owner**: Optional (can be done in-flight or as cleanup task)  
**Dependencies**: Tickets 1–5 (integration depends on all components)  
**Estimated**: 3–4 hours

**Acceptance Criteria:**
- [ ] End-to-end flow works: trigger planning agent → all adapters fire → conversation → iMessage
- [ ] Error recovery: if Google Calendar times out, fall back to cached events
- [ ] Error recovery: if weather API fails, skip weather; if maps fails, skip commute time
- [ ] Langfuse traces span all components with latency breakdown
- [ ] Dashboard queries work: debug logs, daily plans, tool calls
- [ ] Full integration test: `test_e2e_daily_run.py` (5+ scenarios)

**Deliverables:**
- `app/services/error_recovery.py` — updated with Phase 3 error types
- `app/tests/test_e2e_daily_run.py`
- Updated `app/main.py` if needed for new endpoints
- PR with passing tests + clean logs

---

## Implementation Priority

**Parallel dispatch (target 5 delegators):**
- Tickets 1–3: **Independent tier** (no inter-dependencies, start immediately)
- Tickets 4–5: **Dependent tier** (start after 1–3 are under way)
- Ticket 6: **Integration tier** (cleanup + glue after 1–5)

**Rationale**: Calendar, weather, and maps are isolated adapters. Vapi and conversation agent can start in parallel with them but benefit from seeing completed interfaces. Integration happens last when all pieces are in place.

---

## Testing Strategy

- **Unit tests**: Each adapter tested in isolation with mocked external APIs
- **Integration tests**: Planning agent calls real adapter interfaces
- **E2E test**: Full daily run from trigger → plan → message
- **Error tests**: Each adapter tested for timeout, rate limit, invalid response
- **Latency tests**: Ensure <8 second end-to-end (components contribute <2s each)

All tests use pytest. Mocks via `unittest.mock` and `responses` library for HTTP.

---

## Deployment Readiness

After Phase 3:
- [ ] Supabase schema verified (all tables + indexes exist)
- [ ] Environment variables documented in `.env.template`
- [ ] All API keys loaded from `.env`, never hardcoded
- [ ] Dashboard works: can view debug logs + daily plans
- [ ] Tests pass on CI/CD (GitHub Actions recommended)
- [ ] Code is interview-ready for AI Implementation Manager roles

---

## Success Metrics

- ✅ All 6 tickets reach `pr_open` status
- ✅ All tests passing (280+ from Phase 2 + 80+ new from Phase 3)
- ✅ End-to-end latency <8 seconds
- ✅ Langfuse dashboard shows clean traces, no errors
- ✅ Code reviewed by Result Validator against SPEC.md
- ✅ Ready for demo: trigger a run, see real calendar + weather + recommendation in 8 seconds

---

## References

- **Architecture Details**: [TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md)
- **Conversation Design**: [CONVERSATION_DESIGN.md](CONVERSATION_DESIGN.md)
- **Phase 2 Code**: `backend/app/agents/`, `backend/app/adapters/`, `backend/app/services/`
