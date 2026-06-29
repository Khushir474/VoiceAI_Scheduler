"""Demo workflow runner — uses a mock DB so no Supabase credentials needed."""

import asyncio
import json
import sys
import time
import uuid
from datetime import datetime
from typing import Any

sys.path.insert(0, ".")

# Load .env from project root (one level up from backend/)
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

# ── Mock Supabase client ────────────────────────────────────────────────────
class MockResult:
    data = []
    error = None

class MockQuery:
    def __init__(self, table_name: str, records: list):
        self._table = table_name
        self._records = records

    def select(self, *_): return self
    def eq(self, *_): return self
    def order(self, *_): return self
    def limit(self, *_): return self

    def execute(self): return MockResult()
    def __await__(self): return self._async_execute().__await__()
    async def _async_execute(self): return MockResult()


class MockTable:
    def __init__(self, name: str):
        self._name = name
        self._rows: list[dict] = []

    def insert(self, row: dict):
        self._rows.append(row)
        ts = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
        agent = row.get("agent_name", "")
        event = row.get("event_type", "")
        msg = row.get("message", "")
        level = (row.get("level") or "info").upper()
        print(f"  [{ts}] [{level}] {agent} | {event} — {msg}")
        return MockQuery(self._name, self._rows)

    def select(self, *_): return MockQuery(self._name, self._rows)


class MockSupabase:
    def __init__(self):
        self._tables: dict[str, MockTable] = {}

    def table(self, name: str) -> MockTable:
        if name not in self._tables:
            self._tables[name] = MockTable(name)
        return self._tables[name]


# ── Main demo ───────────────────────────────────────────────────────────────
async def main():
    from app.config import get_settings, Settings
    get_settings.cache_clear()  # bust lru_cache so .env changes are picked up
    from app.services.logger import DebugLogger
    from app.adapters.calendar import GoogleCalendarAdapter, AppleICalAdapter
    from app.adapters.weather import WeatherAdapter
    from app.adapters.maps import MapsAdapter
    from app.adapters.voice.vapi import VapiAdapter
    from app.services.langfuse_tracer import LangfuseTracer
    from app.agents.planning_agent import PlanningAgent
    from app.agents.conversation_agent import ConversationAgent
    from app.agents.evaluation_agent import EvaluationAgent
    from app.agents.graph import DailyOpsGraph
    from app.agents.state import AgentState

    settings = get_settings()
    run_id = str(uuid.uuid4())
    user_id = "demo-user-1"

    print("=" * 60)
    print("  DailyOps AI — Demo Workflow Run")
    print("=" * 60)
    print(f"  run_id  : {run_id}")
    print(f"  user_id : {user_id}")
    print(f"  started : {datetime.utcnow().isoformat()}")
    print("=" * 60)

    db = MockSupabase()
    debug_logger = DebugLogger(db, run_id, user_id)
    langfuse_tracer = LangfuseTracer(
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        enabled=False,          # disable real traces for demo
    )

    calendar_adapters = [
        GoogleCalendarAdapter(debug_logger, settings),   # needs full settings for OAuth
        AppleICalAdapter(
            debug_logger,
            caldav_url=settings.apple_ical_caldav_url,
            username=settings.apple_ical_username,
            password=settings.apple_ical_password,
        ),
    ]
    weather_adapter = WeatherAdapter(debug_logger, settings.weather_api_key, provider=settings.weather_provider)
    maps_adapter = MapsAdapter(debug_logger, settings.google_maps_api_key)

    vapi_adapter = VapiAdapter(
        debug_logger,
        settings.vapi_api_key,
        assistant_id=settings.vapi_assistant_id,
        phone_number_id=settings.vapi_phone_number_id,
    )


    planning_agent = PlanningAgent(debug_logger, calendar_adapters, weather_adapter, maps_adapter, langfuse_tracer)
    conversation_agent = ConversationAgent(
        debug_logger,
        langfuse_tracer,
        provider=settings.llm_provider,
        vapi_adapter=vapi_adapter,
        recipient_phone=settings.user_phone_number,
    )
    evaluation_agent = EvaluationAgent(debug_logger, langfuse_tracer)

    graph = DailyOpsGraph(debug_logger, planning_agent, conversation_agent, evaluation_agent)

    initial_state = AgentState(run_id=run_id, user_id=user_id)

    print("\n[1/3] Running PlanningAgent → ConversationAgent → EvaluationAgent\n")
    t0 = time.perf_counter()
    final_state = await graph.run(initial_state)
    elapsed = time.perf_counter() - t0

    print(f"\n[DONE] elapsed={elapsed:.2f}s  error={final_state.error}  score={final_state.evaluation_score}")

    if final_state.plan:
        print("\n── Daily Plan ──────────────────────────────────────────────")
        plan = final_state.plan.model_dump()
        print(json.dumps(plan, indent=2, default=str))

    if final_state.transcript:
        print("\n── Conversation Transcript ─────────────────────────────────")
        for turn in final_state.transcript[:5]:
            print(f"  [{turn.get('role','?')}] {turn.get('content','')[:120]}")

    print("\n── DB rows written ─────────────────────────────────────────")
    for tname, tobj in db._tables.items():
        print(f"  {tname}: {len(tobj._rows)} row(s)")

    print("\n" + "=" * 60)
    return final_state


if __name__ == "__main__":
    asyncio.run(main())
