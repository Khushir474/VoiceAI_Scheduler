# DailyOps AI – Technical Architecture & File Reference

**Purpose**: This document is for any LLM, developer, or AI system to understand every file, layer, and component of DailyOps AI. Read this to understand how the code flows end-to-end.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Backend Architecture](#backend-architecture)
3. [Frontend Architecture](#frontend-architecture)
4. [Database Layer](#database-layer)
5. [Observability Layer](#observability-layer)
6. [File-by-File Reference](#file-by-file-reference)
7. [Data Flow](#data-flow)
8. [Integration Points](#integration-points)

---

## System Overview

### What DailyOps AI Does

1. **6 AM**: Vapi calls user
2. **Planning Agent** fetches: Google Calendar + iCal + Weather + Commute
3. **Conversation Agent** speaks plan, asks for missing items
4. **Evaluation Agent** scores the run, detects hallucinations
5. Send iMessage summary (fallback: SMS)
6. **Langfuse** traces entire execution
7. **Supabase** logs all steps with latency

### Architecture Layers (Top to Bottom)

```
┌─────────────────────────────────────────────────────┐
│  Frontend (Next.js Dashboard)                       │
│  - Overview, Plans, Logs, Settings pages            │
│  - Real-time data fetching from Backend API        │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP/REST
┌──────────────────▼──────────────────────────────────┐
│  Backend (FastAPI)                                  │
│  - 21 API endpoints (plans, logs, webhook, etc)    │
│  - Dependency injection for services               │
│  - Async/await throughout                          │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
┌───────▼────┐ ┌──▼──────┐ ┌─▼──────────┐
│  Agents    │ │Services │ │ Adapters   │
│ (Graph)    │ │(Logger) │ │ (Cloud     │
│            │ │(Tracer) │ │  APIs)     │
└───────┬────┘ └──┬──────┘ └─┬──────────┘
        │         │         │
┌───────▼─────────▼─────────▼──────────────┐
│  Supabase (Database + Logging)           │
│  - debug_logs (all agent steps)          │
│  - tool_calls (performance data)         │
│  - daily_plans (final output)            │
│  - users, preferences, etc.              │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  Langfuse (Tracing & Observability)     │
│  - Full workflow traces                 │
│  - Span timing, LLM cost tracking       │
│  - Production dashboards                │
└─────────────────────────────────────────┘

External Services (via REST APIs):
- Google Calendar API (calendar events)
- CalDAV (Apple iCal)
- OpenWeather API (weather)
- Google Maps API (commute)
- Vapi API (voice calls)
- Twilio API (SMS fallback)
```

---

## Backend Architecture

### Core Stack

- **Framework**: FastAPI (async, type-safe)
- **Agent Orchestration**: LangGraph (state machine)
- **Database**: Supabase (PostgreSQL + Auth + RLS)
- **Observability**: Langfuse (tracing) + Supabase (logging)
- **HTTP Client**: httpx (async, timeout-safe)

### Entry Point

**`backend/app/main.py`**

```python
# FastAPI app initialization
app = FastAPI(title="DailyOps AI", ...)

# CORS for frontend
app.add_middleware(CORSMiddleware, allow_origins=[...])

# Routes registered:
# - /health              (health check)
# - /api/test-run        (trigger workflow)
# - /api/webhook/vapi/*  (Vapi callbacks)
# - /api/plans           (dashboard data)
# - /api/logs            (debug logs)
# - /api/tool-calls      (performance data)
# - /api/settings        (user prefs)
# - /api/messages/send   (iMessage/SMS)
# - /api/overview        (summary card)
```

**Key Endpoints**:

1. `POST /api/test-run?user_id=xxx`
   - Triggers entire workflow
   - Creates run_id, initializes agents
   - Returns final plan + score

2. `POST /api/webhook/vapi/call-state`
   - Receives Vapi call status (initiated, in_progress, completed, failed)
   - Updates `calls` table

3. `POST /api/webhook/vapi/transcript`
   - Receives transcript after call completes
   - Updates `daily_plans` with transcript

4. `GET /api/plans/latest?user_id=xxx`
   - Latest plan for user
   - Used by dashboard Overview

5. `GET /api/logs?run_id=xxx&agent_name=xxx&level=xxx`
   - Debug logs with filters
   - Used by dashboard Logs page

6. `GET /api/tool-calls?run_id=xxx`
   - Tool call performance data
   - Shows latency, input, output, errors

---

## Agent Layer

### Agent Architecture (LangGraph)

**File**: `backend/app/agents/graph.py`

```python
# LangGraph workflow definition
workflow = StateGraph(AgentState)

workflow.add_node("planning", planning_agent.run)
workflow.add_node("conversation", conversation_agent.run)
workflow.add_node("evaluation", evaluation_agent.run)

workflow.add_edge("planning", "conversation")
workflow.add_edge("conversation", "evaluation")
workflow.add_edge("evaluation", END)
```

**Flow**:
1. Start → PlanningAgent
2. PlanningAgent → ConversationAgent
3. ConversationAgent → EvaluationAgent
4. EvaluationAgent → End

All agents share `AgentState` (immutable Pydantic model).

### Agent 1: Planning Agent

**File**: `backend/app/agents/planning_agent.py`

**Responsibility**: Gather data and build plan

**Steps**:
1. Fetch calendar events (Google Calendar API + CalDAV)
2. Merge + deduplicate events
3. Fetch weather (OpenWeather API)
4. Fetch commute (Google Maps API)
5. Build `DailyPlanData` with summaries

**Tracing** (Langfuse):
- `trace.span("fetch_calendar", output=..., latency_ms=...)`
- `trace.span("fetch_weather", output=..., latency_ms=...)`
- `trace.span("fetch_commute", output=..., latency_ms=...)`

**Output**:
```python
state.plan = DailyPlanData(
    calendar_events=[...],
    calendar_summary="You have 3 events",
    weather=WeatherData(...),
    weather_summary="Sunny, 72°F",
    commute=CommuteData(...),
    commute_summary="30 min, moderate traffic",
    workout_recommendation=WorkoutRecommendation(...),
    leave_time=datetime(...),
    carry_items=["umbrella", "jacket"],
)
```

### Agent 2: Conversation Agent

**File**: `backend/app/agents/conversation_agent.py`

**Responsibility**: Interact with user (voice/text)

**Steps**:
1. Format plan as natural language
2. (Future) Call Vapi to speak text
3. (Future) Listen for user response
4. Parse user input
5. Update plan if needed

**Current MVP**:
- Formats plan to text
- Builds transcript
- Mocks user input (no Vapi yet)

**Tracing** (Langfuse):
- `trace.span("format_plan", output=..., latency_ms=...)`
- `trace.span("user_input", input=..., latency_ms=...)`

**Output**:
```python
state.transcript = [
    {"role": "assistant", "content": "You have 3 events: ..."},
    {"role": "user", "content": "I have a dentist appointment..."},
]
state.user_input = "I have a dentist appointment at 2pm"
```

### Agent 3: Evaluation & Debug Agent

**File**: `backend/app/agents/evaluation_agent.py`

**Responsibility**: Quality checks and scoring

**Checks**:
1. Tool usage: Did we use calendar? Weather? Commute?
2. Hallucinations: Any unsupported claims?
3. Scoring: Usefulness (0.0-1.0)
4. Debug summary: Full report

**Scoring Logic**:
- Base: 0.5
- +0.1 if has calendar events
- +0.1 if has weather
- +0.1 if has commute
- +0.1 if has workout recommendation
- +0.1 if has user input
- Cap at 1.0

**Tracing** (Langfuse):
- `trace.span("check_tool_usage", output=..., latency_ms=...)`
- `trace.span("detect_hallucinations", output=..., latency_ms=...)`
- `trace.span("calculate_score", output=..., latency_ms=...)`

**Output**:
```python
state.evaluation_score = 0.85
state.hallucinations_detected = []
state.debug_summary = {
    "tool_checks": {...},
    "usefulness_score": 0.85,
    "plan_sections": {...},
    "transcript_length": 2,
}
```

### Shared State

**File**: `backend/app/agents/state.py`

```python
class AgentState(BaseModel):
    run_id: str                    # Unique run identifier
    user_id: str                   # User who triggered run
    created_at: datetime           # When run started
    
    # Agent data
    transcript: list[dict]         # User + assistant messages
    user_input: str                # User's voice input
    plan: DailyPlanData | None     # Final plan
    
    # Evaluation
    evaluation_score: float | None # 0.0-1.0 usefulness
    hallucinations_detected: list  # List of hallucinations
    debug_summary: dict            # Full debug info
    
    # Metadata
    error: str | None              # If failed
    call_duration_seconds: int     # Total call time
```

**Related Schemas**:

```python
class CalendarEvent(BaseModel):
    source: Literal["google_calendar", "apple_ical"]
    external_id: str | None
    title: str
    start_time: datetime
    end_time: datetime
    location: str | None
    description: str | None
    attendees: list[str] = []

class WeatherData(BaseModel):
    temperature_high: float
    temperature_low: float
    condition: str
    humidity: int
    wind_speed_mph: float
    precipitation_probability: int
    uv_index: int | None
    sunrise: datetime
    sunset: datetime

class CommuteData(BaseModel):
    from_address: str
    to_address: str
    estimated_duration_minutes: int
    traffic_condition: str  # "light", "moderate", "heavy"
    departure_time: datetime | None

class WorkoutRecommendation(BaseModel):
    duration_minutes: int
    recommended_time: Literal["morning", "evening", "flexible"]
    start_time: datetime | None
    end_time: datetime | None
    notes: str | None

class DailyPlanData(BaseModel):
    calendar_events: list[CalendarEvent]
    calendar_summary: str
    weather: WeatherData | None
    weather_summary: str
    commute: CommuteData | None
    commute_summary: str
    workout_recommendation: WorkoutRecommendation | None
    leave_time: datetime | None
    carry_items: list[str]
    extra_user_plans: str
    final_summary: str
```

---

## Adapter Layer

### Overview

Adapters are **swappable implementations** for external services. Each adapter follows a base interface.

### Calendar Adapter

**Base**: `backend/app/adapters/calendar/base.py`

```python
class CalendarAdapter(ABC):
    async def get_events_for_date(user_id: str, date: date) -> list[CalendarEvent]
    async def get_events_range(user_id: str, start: date, end: date) -> list[CalendarEvent]
    async def is_configured(user_id: str) -> bool
```

**Implementations**:

1. **Google Calendar**: `backend/app/adapters/calendar/google_calendar.py`
   - Calls Google Calendar REST API
   - OAuth or service account setup required
   - Fetches events for date range

2. **Apple iCal (CalDAV)**: `backend/app/adapters/calendar/apple_ical.py`
   - Uses CalDAV protocol (RFC 4791)
   - Supports iCloud CalDAV: `caldav.icloud.com`
   - Or any CalDAV server (Nextcloud, OwnCloud, etc.)
   - Sends REPORT query to fetch events

### Weather Adapter

**File**: `backend/app/adapters/weather.py`

```python
class WeatherAdapter:
    async def get_weather(latitude: float, longitude: float) -> WeatherData | None
```

**Implementation**:
- Calls OpenWeather API: `https://api.openweathermap.org/data/2.5/weather`
- Returns `WeatherData` with temp, condition, humidity, wind, UV, sunrise/sunset
- All cloud-based (no local weather files)

### Maps Adapter

**File**: `backend/app/adapters/maps.py`

```python
class MapsAdapter:
    async def get_commute(origin: str, destination: str) -> CommuteData | None
```

**Implementation**:
- Calls Google Maps Distance Matrix API
- Returns duration, distance, traffic condition
- All cloud-based (no local routing)

### Message Adapter

**Base**: `backend/app/adapters/messaging/base.py`

```python
class MessageAdapter(ABC):
    async def send_message(recipient: str, content: str) -> dict
    async def is_available() -> bool
```

**Implementations**:

1. **iMessage Bridge**: `backend/app/adapters/messaging/imessage_bridge.py`
   - HTTP POST to local Mac bridge (port 8001)
   - Sends via iMessage
   - Fallback if bridge unavailable

2. **Twilio SMS**: `backend/app/adapters/messaging/twilio_sms.py`
   - Calls Twilio API
   - Reliable SMS alternative
   - Auto-fallback if iMessage fails

### Voice Adapter

**Base**: `backend/app/adapters/voice/base.py`

```python
class VoiceAdapter(ABC):
    async def initiate_call(recipient_phone: str, run_id: str) -> dict
    async def get_call_status(call_id: str) -> dict
    async def is_available() -> bool
```

**Implementation**: `backend/app/adapters/voice/vapi.py`
- Calls Vapi REST API
- Initiates outbound call
- Polls call status
- Receives transcript via webhook

---

## Services Layer

### Debug Logger

**File**: `backend/app/services/logger.py`

```python
class DebugLogger:
    async def log_event(
        event_type: str,
        message: str,
        agent_name: str | None = None,
        level: str = "info",
        input_payload: dict | None = None,
        output_payload: dict | None = None,
        error: str | None = None,
        latency_ms: int | None = None,
    ) -> None
```

**What it does**:
- Logs to Supabase `debug_logs` table
- Every agent action gets logged
- Fallback to stdout if Supabase fails
- Includes latency, input, output, errors

**Tables written to**:
- `debug_logs` – All agent steps
- `tool_calls` – Performance data per tool

### Langfuse Tracer

**File**: `backend/app/services/langfuse_tracer.py`

```python
class LangfuseTracer:
    def trace_agent(agent_name: str, run_id: str, user_id: str) -> LangfuseTrace
    def trace_tool_call(tool_name: str, ...) -> LangfuseSpan
    def trace_llm_call(model: str, messages: list) -> LangfuseGeneration
    def flush() -> None
```

**What it does**:
- Creates Langfuse traces for workflow visualization
- Creates spans for each agent/tool step
- Records latency (ms) for performance analysis
- Flushes at end of run to Langfuse cloud

**Usage in agents**:
```python
trace = langfuse_tracer.trace_agent("PlanningAgent", run_id, user_id)
trace.span("fetch_calendar", output=..., latency_ms=245)
trace.end(output_data={...})
```

**No-op fallback**: If Langfuse disabled, uses `NoOpTrace` (no overhead, no errors).

### Calendar Merger

**File**: `backend/app/services/calendar_merge.py`

```python
class CalendarMerger:
    def merge(events: list[CalendarEvent]) -> tuple[list[CalendarEvent], dict]
```

**Deduplication Logic**:
- Exact match: Same title + time within 5 min
- Similar title + same time + similar location
- Removes duplicates from multiple sources

**Output**:
```python
deduplicated_events, report = calendar_merger.merge(all_events)
# report = {
#     "total_input": 10,
#     "total_output": 8,
#     "duplicates_removed": 2,
#     "sources": {"google_calendar": 6, "apple_ical": 4}
# }
```

---

## API Layer

### Vapi Webhooks

**File**: `backend/app/api/vapi_webhooks.py`

**Endpoints**:

1. `POST /api/webhook/vapi/call-state`
   - Receives: call_id, status (initiated/in_progress/completed/failed), customData
   - Updates: `calls` table with status

2. `POST /api/webhook/vapi/transcript`
   - Receives: transcript, duration_seconds, custom_data
   - Updates: `calls` table with transcript + duration
   - Updates: `daily_plans` table with transcript + duration

3. `POST /api/webhook/vapi/error`
   - Receives: error_message, call_id, custom_data
   - Updates: `calls` table with error_message
   - Updates: `daily_plans` table status to "failed"

### Dashboard API

**File**: `backend/app/api/dashboard.py`

**Endpoints**:

1. `GET /api/plans/latest?user_id=xxx`
   - Returns: Latest daily plan

2. `GET /api/plans?user_id=xxx&limit=10&offset=0`
   - Returns: Paginated plans

3. `GET /api/logs?run_id=xxx&agent_name=xxx&level=xxx&limit=100`
   - Returns: Filtered debug logs

4. `GET /api/tool-calls?run_id=xxx&agent_name=xxx&limit=100`
   - Returns: Tool calls with latency stats
   - Includes: total latency, avg latency, success/error counts

5. `GET /api/settings/{user_id}`
   - Returns: User preferences

6. `POST /api/settings/{user_id}`
   - Updates: User preferences

7. `GET /api/overview/{user_id}`
   - Returns: Latest plan + call + evaluation

### Messages API

**File**: `backend/app/api/messages.py`

**Endpoints**:

1. `POST /api/messages/send`
   - Params: run_id, user_id, content, channel (imessage/twilio)
   - Sends via IMessageBridgeAdapter or TwilioSMSAdapter
   - Logs to `messages` table

---

## Database Layer

### Configuration

**File**: `backend/app/config.py`

Loads all settings from `.env`:
- Supabase: URL, service role key
- APIs: OpenAI, Vapi, ElevenLabs, Google, Weather, Twilio, etc.
- Langfuse: Public key, secret key
- Application: Environment, debug, log level

### Supabase Client

**File**: `backend/app/db/supabase_client.py`

```python
def get_supabase_client() -> AsyncClient
```

Returns async Supabase client.

### Schema

**File**: `migrations/001_initial_schema.sql`

**Tables**:

1. **users**
   - id, created_at, email, phone_number, full_name, home_address, work_address, timezone

2. **user_preferences**
   - user_id, wake_up_time, workout_duration_minutes, workout_preference, commute_buffer_minutes, preferred_messaging_channel, google_calendar_enabled, apple_ical_enabled

3. **daily_plans**
   - run_id (PK), user_id, plan_date, calendar_summary, weather_summary, commute_summary, workout_recommendation, leave_time, carry_items, extra_user_plans, final_summary, status, call_duration_seconds, transcript

4. **calendar_events**
   - id, run_id, user_id, source, external_id, title, start_time, end_time, location, description, attendees, is_deduplicated, deduplicated_from_id

5. **calls**
   - id, run_id, user_id, vapi_call_id, status, duration_seconds, transcript, error_message

6. **messages**
   - id, run_id, user_id, channel (imessage/twilio), direction (inbound/outbound), content, status, external_message_id

7. **tool_calls**
   - id, run_id, user_id, agent_name, tool_name, input_payload, output_payload, error, latency_ms, status

8. **debug_logs**
   - id, run_id, user_id, agent_name, level, event_type, message, input_payload, output_payload, error, latency_ms

9. **evaluation_scores**
   - id, run_id, user_id, usefulness_score, correctness_score, hallucination_detected, hallucination_details, overall_score, debug_summary, feedback

10. **memory_items**
    - id, user_id, memory_type, content, embedding, related_run_ids, relevance_score, archived_at

**Indexes**: Created on run_id, user_id, date, agent_name for fast queries.

**RLS**: Row-level security enabled (users see only their data).

---

## Frontend Architecture

### Technology Stack

- **Framework**: Next.js 14 (React)
- **Styling**: Tailwind CSS (dark theme)
- **HTTP Client**: Fetch API
- **State**: React hooks (useState, useEffect)
- **Database**: Supabase JS client

### Pages

#### 1. Overview (`app/page.tsx`)

**Purpose**: Dashboard summary card

**Displays**:
- Latest plan (status, calendar, weather)
- Latest call (status, duration)
- Latest evaluation (score)
- "Trigger Test Run" button

**API Calls**:
```javascript
GET /api/overview/{userId}
POST /api/test-run?user_id={userId}
```

**State**:
- `data` – Latest plan/call/eval
- `loading` – Fetching state
- `testRunning` – Test run in progress

#### 2. Daily Plans (`app/plans/page.tsx`)

**Purpose**: View daily plans with details

**Layout**:
- Left: List of plans (clickable)
- Right: Detailed view of selected plan

**Displays**:
- Plan date, run_id
- Calendar summary
- Weather summary
- Commute summary
- Metadata (created_at)

**API Calls**:
```javascript
GET /api/plans?user_id={userId}&limit=10
```

**State**:
- `plans` – All plans
- `selectedPlan` – Currently viewed plan
- `loading` – Fetching state

#### 3. Debug Logs (`app/logs/page.tsx`)

**Purpose**: Inspect workflow execution

**Features**:
- Search by run_id
- Filter by agent_name, level
- View full payloads (toggle)
- Show tool call stats

**Displays**:
- Debug logs table (level-colored)
- Tool calls table (with latency)
- Aggregate stats (total, success, error counts)

**API Calls**:
```javascript
GET /api/logs?run_id={runId}&agent_name=...&level=...
GET /api/tool-calls?run_id={runId}&agent_name=...
```

**State**:
- `runId` – Search input
- `logs` – Debug logs
- `toolCalls` – Tool call data
- `loading` – Fetching state
- `showPayloads` – Toggle payload display

#### 4. Settings (`app/settings/page.tsx`)

**Purpose**: User preferences

**Fields**:
- Wake-up time (time input)
- Workout duration (number)
- Workout preference (select: morning/evening/flexible)
- Commute buffer (number)
- Preferred messaging (select: imessage/twilio)
- Calendar integrations (checkboxes: Google/Apple)

**API Calls**:
```javascript
GET /api/settings/{userId}
POST /api/settings/{userId}
```

**State**:
- `settings` – User preferences
- `loading` – Fetching state
- `saving` – Save in progress
- `message` – Feedback message

### Layout (`app/layout.tsx`)

**Components**:
- Navigation bar (top)
- Links to all pages
- Main content area

**Styling**:
- Dark background (slate-950)
- Light text (slate-100)
- Responsive grid

### API Client (`lib/api.ts`)

**Functions**:
```javascript
fetchPlans(userId, limit)
fetchLatestPlan(userId)
fetchDebugLogs(filters)
fetchToolCalls(filters)
fetchSettings(userId)
updateSettings(userId, settings)
getOverview(userId)
triggerTestRun(userId)
```

**Base URL**: `process.env.NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)

### Supabase Client (`lib/supabase.ts`)

```typescript
const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
)
```

Used for future real-time updates (subscriptions, etc.).

---

## Observability Layer

### Dual-Layer Approach

#### Layer 1: Supabase (Local Debugging)

**Purpose**: Structured logging for local queries

**Tables**:
- `debug_logs` – Every agent step, message, error
- `tool_calls` – Tool performance data (input, output, latency)
- `daily_plans` – Final plan summaries

**Usage**:
- Query locally for any run_id
- Filter by agent_name, level, event_type
- See full payloads (input/output)
- Dashboard: Logs page queries this

**Query Example**:
```sql
select * from debug_logs
where run_id = 'abc-123'
order by created_at desc
limit 100;
```

#### Layer 2: Langfuse (Production Observability)

**Purpose**: Workflow visualization, LLM cost tracking, production dashboards

**Traces**:
- PlanningAgent trace
  - fetch_calendar span
  - fetch_weather span
  - fetch_commute span
- ConversationAgent trace
  - format_plan span
  - user_input span
- EvaluationAgent trace
  - check_tool_usage span
  - detect_hallucinations span
  - calculate_score span

**Usage**:
- View full workflow timeline in Langfuse dashboard
- See latency for each step
- Track LLM costs when LLMs added
- Custom scoring and alerts

**Setup**:
1. Create account: https://langfuse.com
2. Get public_key + secret_key
3. Add to .env: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
4. Backend auto-traces all agents
5. View in Langfuse dashboard

---

## Data Flow

### End-to-End Flow

```
1. Frontend: User clicks "Trigger Test Run"
   ↓
2. API: POST /api/test-run?user_id=test-user-1
   ↓
3. Backend: Generate run_id, initialize services
   ├─ DebugLogger(db, run_id, user_id)
   ├─ LangfuseTracer(public_key, secret_key)
   ├─ Initialize adapters (Calendar, Weather, Maps)
   ├─ Initialize agents (Planning, Conversation, Evaluation)
   └─ Build LangGraph workflow
   ↓
4. Execute Workflow:
   a) PlanningAgent.run(state)
      - fetch_calendar() → CalendarAdapter → Google Calendar API + CalDAV
      - merge + deduplicate events
      - fetch_weather() → WeatherAdapter → OpenWeather API
      - fetch_commute() → MapsAdapter → Google Maps API
      - Build DailyPlanData
      - Trace spans (Langfuse)
      - Log events (Supabase)
      
   b) ConversationAgent.run(state)
      - format_plan_for_speech(plan)
      - Build transcript
      - Mock user input
      - Trace spans (Langfuse)
      - Log events (Supabase)
      
   c) EvaluationAgent.run(state)
      - check_tool_usage()
      - detect_hallucinations()
      - calculate_score()
      - Build debug_summary
      - Trace spans (Langfuse)
      - Log events (Supabase)
   ↓
5. Save Results:
   - Insert daily_plans row
   - Insert evaluation_scores row
   - Flush Langfuse (send to cloud)
   ↓
6. Return Response:
   {
     "run_id": "abc-123",
     "status": "success",
     "plan": {...},
     "evaluation_score": 0.85
   }
   ↓
7. Frontend: Display results
   - Overview page shows latest plan + score
   - Logs page can search by run_id
   - Plans page shows full daily plan
```

### Data Transformations

```
Raw Calendar Data (Google Calendar API)
  ↓ (normalize to CalendarEvent)
  ↓
Calendar Events List
  ↓ (merge + deduplicate)
  ↓
Deduplicated Events
  ↓ (summarize)
  ↓
calendar_summary: "You have 3 events: standup at 9am, lunch at 12pm, review at 3pm"
  ↓ (include in DailyPlanData)
  ↓
Final Plan
  ↓ (save to daily_plans table)
  ↓
Supabase + Langfuse
```

---

## Integration Points

### Cloud APIs (All REST)

1. **Google Calendar API**
   - Auth: OAuth or service account
   - Endpoint: `https://www.googleapis.com/calendar/v3/`
   - Adapter: `GoogleCalendarAdapter`

2. **Apple iCal (CalDAV)**
   - Protocol: WebDAV (RFC 4791)
   - Endpoint: `https://caldav.icloud.com/`
   - Adapter: `AppleICalAdapter`
   - Returns: iCalendar format (parsed to CalendarEvent)

3. **OpenWeather API**
   - Endpoint: `https://api.openweathermap.org/data/2.5/weather`
   - Adapter: `WeatherAdapter`
   - Input: latitude, longitude
   - Output: WeatherData

4. **Google Maps Distance Matrix API**
   - Endpoint: `https://maps.googleapis.com/maps/api/distancematrix/json`
   - Adapter: `MapsAdapter`
   - Input: origin, destination
   - Output: CommuteData

5. **Vapi (Voice)**
   - Endpoint: `https://api.vapi.ai/`
   - Adapter: `VapiAdapter`
   - Methods: initiate_call(), get_call_status()
   - Webhooks: /api/webhook/vapi/*

6. **Twilio (SMS)**
   - Endpoint: `https://api.twilio.com/`
   - Adapter: `TwilioSMSAdapter`
   - Fallback if iMessage unavailable

7. **Langfuse (Observability)**
   - Endpoint: `https://api.langfuse.com/`
   - Service: `LangfuseTracer`
   - Methods: trace(), flush()
   - No-op if disabled

8. **Supabase (Database)**
   - REST API: `https://{project}.supabase.co/`
   - AsyncClient for all queries
   - RLS policies enforce user isolation

---

## Testing

### Test Files

**`backend/app/tests/test_calendar_merge.py`**

Tests for `CalendarMerger.merge()`:
- No duplicates → output = input
- Exact duplicates → deduplicated
- Time window duplicates (5 min) → deduplicated
- Similar titles + same time → deduplicated
- Different times → not deduplicated
- Multiple sources → dedup_report includes counts

**Running**:
```bash
cd backend
pytest app/tests/ -v
```

### Mock/Stub Strategy

- Adapters: Stub implementations (return mock data)
- LLM calls: Not yet implemented (future)
- Vapi: Webhook stubs (future)
- Langfuse: No-op fallback when disabled

---

## Environment Variables

**Backend** (`.env`):
- `SUPABASE_URL` – Supabase project URL
- `SUPABASE_PUBLISHABLE_KEY` – Publishable key
- `SUPABASE_SECRET_KEY` – Secret key
- `OPENAI_API_KEY` – For future LLM calls
- `VAPI_API_KEY` – Vapi API key
- `ELEVENLABS_API_KEY` – Voice synthesis
- `GOOGLE_CALENDAR_CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN` – Google Calendar
- `GOOGLE_MAPS_API_KEY` – Google Maps
- `WEATHER_API_KEY` – OpenWeather
- `APPLE_ICAL_CALDAV_URL`, `USERNAME`, `PASSWORD` – CalDAV
- `TWILIO_ACCOUNT_SID`, `AUTH_TOKEN`, `PHONE_NUMBER` – Twilio
- `LANGFUSE_PUBLIC_KEY`, `SECRET_KEY`, `ENABLED` – Langfuse
- `ENVIRONMENT` – dev/prod
- `DEBUG` – true/false
- `LOG_LEVEL` – DEBUG/INFO/WARNING/ERROR

**Frontend** (`.env.local`):
- `NEXT_PUBLIC_API_URL` – Backend URL (default: `http://localhost:8000`)
- `NEXT_PUBLIC_SUPABASE_URL` – Supabase URL
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` – Supabase publishable key

---

## Deployment

### Backend (Railway)

1. Connect GitHub repo
2. Set environment variables in Railway dashboard
3. Auto-deploy on git push
4. Runs on Railway node

### Frontend (Vercel)

1. Connect GitHub repo
2. Set `NEXT_PUBLIC_*` env vars
3. Auto-deploy on git push
4. Runs on Vercel edge

### Database (Supabase)

1. Hosted at Supabase
2. Migrations applied via dashboard
3. RLS policies restrict access

---

## Summary

- **Backend**: FastAPI + LangGraph + async
- **Frontend**: Next.js + React hooks + Tailwind
- **Database**: Supabase (PostgreSQL + RLS)
- **Adapters**: Cloud APIs (Google, Apple, OpenWeather, Maps, Vapi, Twilio)
- **Observability**: Supabase logging + Langfuse tracing
- **Deployment**: Railway (backend) + Vercel (frontend) + Supabase (database)

Every file, every function, every table follows a clear pattern. This document should enable any LLM to understand and modify the codebase.
