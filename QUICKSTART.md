# DailyOps AI – Quick Start (5 minutes)

## 1. Backend Setup

```bash
# Navigate to backend
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy env template
cp ../.env.template ../.env

# Edit .env with your API keys (see CLOUD_APIS.md)
# At minimum, set:
# - SUPABASE_URL
# - SUPABASE_PUBLISHABLE_KEY
# - SUPABASE_SECRET_KEY
# - OPENAI_API_KEY (for future LLM calls)
# - VAPI_API_KEY
# - GOOGLE_MAPS_API_KEY
# - WEATHER_API_KEY
```

## 2. Supabase Setup

```bash
# Create a Supabase project at https://supabase.com

# Copy SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, and SUPABASE_SECRET_KEY into .env

# Run the migration in Supabase dashboard:
# 1. Go to SQL Editor
# 2. Paste contents of migrations/001_initial_schema.sql
# 3. Run

# Verify tables exist in Supabase dashboard
```

## 3. Run Backend Tests

```bash
# From backend/ directory
pytest app/tests/ -v

# Expected: 7 tests for calendar merge (PASSED)
```

## 4. Start Backend Server

```bash
# From backend/ directory
python -m app.main

# Server runs at http://localhost:8000
# Health check: curl http://localhost:8000/health
```

## 5. Frontend Setup (New Terminal)

```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev

# Frontend runs at http://localhost:3000
```

## 6. Test the Flow

Open browser: **http://localhost:3000**

1. Go to **Overview** page
2. Click **"Trigger Test Run"**
3. Wait 2-3 seconds
4. See populated plan, call status, evaluation score
5. Go to **Logs** page
6. Paste the `run_id` to see debug logs and tool calls
7. Go to **Plans** page to see the daily plan details

## Environment Variables (Minimal for Testing)

```bash
# Supabase (required)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=eyJ...
SUPABASE_SECRET_KEY=eyJ...

# Optional (for testing with mock data)
OPENAI_API_KEY=sk-...          # Future: LLM calls
VAPI_API_KEY=your-key          # Future: actual Vapi integration
GOOGLE_MAPS_API_KEY=your-key   # Future: real commute data
WEATHER_API_KEY=your-key       # Future: real weather data
ELEVENLABS_API_KEY=your-key    # Future: voice synthesis
```

**Without these keys, the system uses mock data** – perfect for testing the architecture.

## What You Get

✅ Full workflow: Planning Agent → Conversation Agent → Evaluation Agent
✅ All actions logged to Supabase (debug_logs, tool_calls)
✅ Dashboard to view plans, logs, and scores
✅ Calendar merge & deduplication logic
✅ Structured error handling

## Next Steps

### To add real data:
1. Set up Google Calendar OAuth (see CLOUD_APIS.md)
2. Configure Apple iCal CalDAV (see CLOUD_APIS.md)
3. Get OpenWeather and Google Maps API keys
4. Adapters automatically use real APIs when keys are set

### To enable Vapi voice:
1. Create Vapi account at https://vapi.ai/
2. Set `VAPI_API_KEY` and `VAPI_ASSISTANT_ID` in .env
3. Configure webhook in Vapi dashboard to point to `/api/webhook/vapi/*`

### To enable iMessage:
1. Run local iMessage bridge on port 8001, OR
2. Configure Twilio (falls back automatically)

### To go to production:
1. Deploy backend to Railway (`.env` via dashboard)
2. Deploy frontend to Vercel (`.env.local`)
3. Update Vapi webhook URL to production backend

## File Structure Reminder

```
DailyOps_Scheduler/
├── backend/           # FastAPI + agents
│   ├── app/
│   │   ├── main.py    # Start here
│   │   ├── agents/    # Planning, Conversation, Evaluation
│   │   └── adapters/  # Calendar, Weather, Maps, Messaging
│   └── requirements.txt
├── frontend/          # Next.js dashboard
│   ├── app/          # Pages: /, /plans, /logs, /settings
│   └── package.json
├── migrations/        # Supabase schema
├── .env.template      # Copy to .env
├── CLOUD_APIS.md      # Cloud API setup guide
├── CLAUDE.md          # Architecture & design decisions
└── README.md          # Full documentation
```

## Troubleshooting

**Backend won't start?**
```bash
# Check Supabase connection
python -c "from app.db.supabase_client import get_supabase_client; print(get_supabase_client())"

# Check migrations were applied
# (tables should exist in Supabase dashboard)
```

**Frontend can't reach backend?**
```bash
# Check backend is running on http://localhost:8000
curl http://localhost:8000/health

# Check CORS is enabled (should see "ok")
```

**Test run fails with "no logs found"?**
```bash
# Supabase connection issue
# 1. Verify SUPABASE_URL in .env
# 2. Verify SUPABASE_SECRET_KEY is correct (not publishable key)
# 3. Check migrations were applied
```

---

**Questions?** See:
- `CLOUD_APIS.md` – Cloud API setup
- `CLAUDE.md` – Architecture decisions
- `README.md` – Full documentation
