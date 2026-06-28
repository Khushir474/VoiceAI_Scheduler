# DailyOps AI

A voice-first and iMessage-first expert productivity assistant that orchestrates your daily plans using LangGraph, Vapi, and Supabase.

## Overview

**DailyOps AI** calls you every morning, reviews your Google Calendar + Apple iCal events, checks weather and commute, asks if you have any missing plans, recommends workout timing, tells you when to leave and what to carry, then sends a concise iMessage summary.

Key features:
- 🎙️ Voice-first interaction via Vapi + ElevenLabs
- 📱 iMessage summaries (Twilio fallback)
- 📅 Google Calendar + Apple iCal support
- 🌦️ Weather & commute integration
- 📊 Complete debug dashboard with tool calls and latency logging
- 🏗️ Adapter-based architecture for extensibility
- 🔗 LangGraph multi-agent orchestration

## MVP Flow

1. 6 AM scheduled Vapi call
2. Backend creates a `run_id`
3. **Planning Agent** fetches:
   - Google Calendar events
   - Apple iCal events
   - Weather
   - Commute estimate
   - User preferences
4. **Conversation Agent** converses:
   - Calendar summary
   - Weather summary
   - Preliminary recommendations
   - Asks: "Do you have anything not on your calendar?"
5. User answers (voice)
6. **Planning Agent** updates plan
7. **Conversation Agent** confirms final plan
8. Send iMessage summary (or SMS via Twilio fallback)
9. **Evaluation & Debug Agent** scores the run
10. Dashboard displays final plan, transcript, tool calls, debug logs

---

## Tech Stack

### Backend
- **Framework**: FastAPI
- **Agent Orchestration**: LangGraph
- **Database/Auth**: Supabase
- **Voice**: Vapi + ElevenLabs
- **Messaging**: iMessage Mac bridge + Twilio
- **Calendar**: Google Calendar API + Apple iCal
- **Weather**: OpenWeather or WeatherAPI
- **Commute**: Google Maps API

### Frontend
- **Framework**: Next.js
- **UI Components**: shadcn/ui
- **Theme**: Tweakcn Darkmatter
- **Deployment**: Vercel

### Deployment
- **Backend**: Railway
- **Frontend**: Vercel

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry
│   │   ├── config.py             # Settings from env
│   │   ├── api/
│   │   │   ├── vapi_webhooks.py  # Vapi callback handlers
│   │   │   ├── dashboard.py      # Dashboard API routes
│   │   │   ├── messages.py       # Message endpoints
│   │   │   └── scheduler.py      # Scheduled tasks
│   │   ├── agents/
│   │   │   ├── graph.py          # LangGraph workflow
│   │   │   ├── state.py          # Shared agent state & schemas
│   │   │   ├── conversation_agent.py
│   │   │   ├── planning_agent.py
│   │   │   ├── evaluation_agent.py
│   │   │   └── prompts.py        # LLM prompts
│   │   ├── adapters/
│   │   │   ├── calendar/
│   │   │   │   ├── base.py
│   │   │   │   ├── google_calendar.py
│   │   │   │   └── apple_ical.py
│   │   │   ├── messaging/
│   │   │   │   ├── base.py
│   │   │   │   ├── imessage_bridge.py
│   │   │   │   └── twilio_sms.py
│   │   │   ├── voice/
│   │   │   │   ├── base.py
│   │   │   │   └── vapi.py
│   │   │   ├── weather.py
│   │   │   └── maps.py
│   │   ├── db/
│   │   │   ├── supabase_client.py
│   │   │   ├── models.py         # ORM models
│   │   │   └── crud.py           # Database operations
│   │   ├── services/
│   │   │   ├── planner.py
│   │   │   ├── logger.py         # Structured debug logger
│   │   │   ├── memory.py         # Memory management
│   │   │   ├── evaluator.py
│   │   │   └── calendar_merge.py # Deduplication logic
│   │   └── tests/
│   │       ├── test_calendar_merge.py
│   │       ├── test_planner.py
│   │       └── test_debug_logging.py
│   ├── requirements.txt
│   └── .dockerignore
├── frontend/
│   ├── app/
│   │   ├── page.tsx              # Overview page
│   │   ├── plans/page.tsx        # Daily plans
│   │   ├── logs/page.tsx         # Debug logs
│   │   └── settings/page.tsx     # Settings
│   ├── components/
│   │   ├── daily-plan-card.tsx
│   │   ├── debug-log-table.tsx
│   │   ├── tool-call-viewer.tsx
│   │   ├── settings-form.tsx
│   │   └── evaluation-score-card.tsx
│   ├── lib/
│   │   ├── supabase.ts
│   │   └── api.ts
│   ├── package.json
│   └── tailwind.config.ts
├── migrations/
│   └── 001_initial_schema.sql    # Supabase schema
├── .env.template
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- Supabase account
- Vapi account + ElevenLabs account
- Google OAuth credentials for Calendar
- OpenWeather or WeatherAPI key
- Twilio account (fallback)

### Backend Setup

1. **Clone and navigate**:
   ```bash
   cd backend
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up Supabase**:
   - Create a new project at https://supabase.com
   - Copy `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
   - Run the migration:
     ```bash
     # Use Supabase dashboard SQL editor or psql
     psql -h db.XXXX.supabase.co -U postgres -d postgres < ../migrations/001_initial_schema.sql
     ```

5. **Configure environment**:
   ```bash
   cp ../.env.template ../.env
   # Edit .env with your API keys
   ```

6. **Run tests**:
   ```bash
   pytest app/tests/ -v
   ```

7. **Start development server**:
   ```bash
   python -m app.main
   ```
   Server runs at `http://localhost:8000`

### Frontend Setup

1. **Navigate to frontend**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Add shadcn/ui theme**:
   ```bash
   npx shadcn@latest add https://tweakcn.com/r/themes/darkmatter.json
   ```

4. **Configure environment**:
   ```bash
   cp .env.template .env.local
   # Edit with your Supabase URL and anon key
   ```

5. **Run development server**:
   ```bash
   npm run dev
   ```
   Frontend runs at `http://localhost:3000`

---

## Environment Variables

See `.env.template` for the complete list. Key variables:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Vapi
VAPI_API_KEY=your-vapi-key
VAPI_ASSISTANT_ID=your-assistant-id

# ElevenLabs
ELEVENLABS_API_KEY=your-elevenlabs-key

# Google Calendar
GOOGLE_CALENDAR_CLIENT_ID=...
GOOGLE_CALENDAR_CLIENT_SECRET=...
GOOGLE_CALENDAR_REFRESH_TOKEN=...

# Messaging
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
USER_PHONE_NUMBER=+1234567890

# iMessage Bridge
IMESSAGE_BRIDGE_URL=http://localhost:8001
```

---

## Database Schema

Key tables:

### `daily_plans`
Daily plan summaries: events, weather, commute, workout, final text.

### `debug_logs`
Structured logging: agent name, event type, latency, tool calls, errors.

### `tool_calls`
Instrumentation: which tool, agent, input/output, latency, status.

### `calendar_events`
Normalized events from Google Calendar and Apple iCal.

### `calls`
Vapi call metadata: ID, transcript, status, duration.

### `messages`
Sent messages: channel (iMessage/Twilio), status, recipient.

### `evaluation_scores`
Agent evaluation: usefulness, correctness, hallucination detection.

See `migrations/001_initial_schema.sql` for full schema.

---

## Agents

### 1. Planning Agent
**Responsibility**: Gather data and build the daily plan.

Fetches:
- Calendar events (Google + iCal)
- Weather forecast
- Commute estimate
- User preferences

Outputs:
- Merged & deduplicated events
- Calendar summary
- Weather summary
- Commute recommendation
- Workout recommendation
- Leave time

### 2. Conversation Agent
**Responsibility**: Voice/text conversation and confirmation.

- Reads the plan
- Speaks calendar, weather, and recommendations
- Asks: "Do you have anything else to plan?"
- Listens for user input
- Confirms final plan

### 3. Evaluation & Debug Agent
**Responsibility**: Quality checks and logging.

- Validates tool data was used correctly
- Flags hallucinations
- Scores plan usefulness (0-1)
- Creates debug summary
- Logs final state

---

## Adapters

All adapters follow a common interface so implementations are swappable.

### CalendarAdapter
```python
class CalendarAdapter:
    async def get_events_for_date(self, user_id: str, target_date: date) -> list[CalendarEvent]
    async def get_events_range(self, user_id: str, start: date, end: date) -> list[CalendarEvent]
    async def is_configured(self, user_id: str) -> bool
```

**Implementations**:
- `GoogleCalendarAdapter` – Google Calendar API
- `AppleICalAdapter` – Apple Calendar via AppleScript or .ics files

### MessageAdapter
```python
class MessageAdapter:
    async def send_message(self, recipient: str, content: str) -> dict
    async def is_available(self) -> bool
```

**Implementations**:
- `IMessageBridgeAdapter` – Local Mac bridge (HTTP)
- `TwilioSMSAdapter` – Twilio SMS fallback

### VoiceAdapter
```python
class VoiceAdapter:
    async def initiate_call(self, recipient_phone: str, run_id: str) -> dict
    async def get_call_status(self, call_id: str) -> dict
    async def is_available(self) -> bool
```

**Implementations**:
- `VapiAdapter` – Vapi voice service

---

## Testing

Run the test suite:

```bash
cd backend
pytest app/tests/ -v
```

### Current Tests

- `test_calendar_merge.py` – Deduplication logic
- `test_planner.py` – Planning agent (stub)
- `test_debug_logging.py` – Debug logger (stub)

---

## Dashboard

The frontend dashboard includes:

1. **Overview** – Latest plan status, call status, message status, evaluation score
2. **Daily Plans** – Calendar summary, weather, commute, recommendations, final text
3. **Debug Logs** – Run ID filter, agent filter, log level, tool calls, latency, errors
4. **Settings** – User preferences (wake time, home address, work address, workout timing, messaging channel, enabled calendars)

---

## Deployment

### Backend (Railway)

1. Create Railway project
2. Connect GitHub repo
3. Set environment variables in Railway dashboard
4. Deploy

### Frontend (Vercel)

1. Connect GitHub repo to Vercel
2. Set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
3. Deploy

---

## Success Criteria

The MVP is successful if:

- ✅ Can trigger a test daily planning run
- ✅ Fetches or mocks Google Calendar + iCal events
- ✅ Generates a structured daily plan
- ✅ Logs all tool calls and agent steps
- ✅ Sends a text summary through iMessage bridge or Twilio fallback
- ✅ Dashboard shows final plan and debug logs
- ✅ Clean architecture suitable for discussion in AI Implementation Manager interviews

---

## Next Steps (Beyond MVP)

- [ ] Implement Google Calendar OAuth flow
- [ ] Implement Apple iCal file parsing
- [ ] Connect to actual Vapi endpoints
- [ ] Integrate weather API
- [ ] Integrate Google Maps commute API
- [ ] Build conversation agent with Claude/Anthropic API
- [ ] Build evaluation agent
- [ ] Add memory/Cognee integration
- [ ] Deploy to Railway/Vercel
- [ ] Add real-time dashboard updates with WebSockets
- [ ] Implement user authentication

---

## Development Notes

### Calendar Deduplication

Events are deduplicated if:
- Same title (case-insensitive)
- Start times within 5 minutes
- OR similar titles + same time + similar location

See `services/calendar_merge.py` for full logic.

### Debug Logging

All agent steps, tool calls, and errors are logged to the `debug_logs` table with:
- `run_id` – Unique run identifier
- `agent_name` – Which agent
- `event_type` – What happened
- `latency_ms` – How long it took
- `input_payload` / `output_payload` – Full data
- `error` – If failed

### LangGraph State

Shared state across agents:
```python
class AgentState(BaseModel):
    run_id: str
    user_id: str
    transcript: list[dict]
    user_input: str
    plan: DailyPlanData | None
    evaluation_score: float | None
    error: str | None
```

---

## License

[TBD]

---

## Author

Built as a portfolio project for AI Implementation Manager / Forward Deployed AI roles.
