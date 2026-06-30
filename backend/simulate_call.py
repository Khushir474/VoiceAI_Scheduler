#!/usr/bin/env python3
"""
simulate_call.py — terminal emulator for the DailyOps AI morning call.

Runs the full stack locally:
  PlanningAgent (real calendar / weather / commute data)
  → ConversationAgent (real LLM plan generation)
  → Interactive REPL (you type; LLM interprets and responds)
  → Calendar event creation on confirm (Apple iCal + GCal)
  → iMessage / SMS summary

Usage:
    cd backend
    python simulate_call.py

Optional flags:
    --mock-data     skip real API calls, use hardcoded fixture data
    --no-calendar   skip calendar event creation after confirm
    --no-summary    skip iMessage/SMS send at the end
"""

import asyncio
import sys
import uuid
import argparse
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(".env")

from app.config import get_settings
from app.agents.state import (
    AgentState, DailyPlanData, CalendarEvent, WeatherData,
    CommuteData, WorkoutRecommendation,
)

# ── colour helpers ────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"    # agent speech
GREEN  = "\033[92m"    # system messages
YELLOW = "\033[93m"    # prompts / labels
DIM    = "\033[2m"     # secondary info
RED    = "\033[91m"    # errors

def agent(msg: str):  print(f"\n{CYAN}{BOLD}[DailyOps]{RESET} {CYAN}{msg}{RESET}")
def system(msg: str): print(f"{GREEN}  ▸ {msg}{RESET}")
def label(msg: str):  print(f"{YELLOW}{msg}{RESET}")
def dim(msg: str):    print(f"{DIM}  {msg}{RESET}")
def err(msg: str):    print(f"{RED}  ✗ {msg}{RESET}", file=sys.stderr)


# ── null logger (no Supabase needed for local sim) ───────────────────────────
class NullLogger:
    async def log_event(self, level="info", message="", event_type="", agent_name="", error="", **kwargs):
        if level == "error":
            print(f"{RED}  [log:{agent_name}:{event_type}] {message}{' — ' + error if error else ''}{RESET}")
        elif level == "warning":
            print(f"{DIM}  [log:{agent_name}:{event_type}] {message}{RESET}")
    async def log_agent_start(self, name): pass
    async def log_agent_end(self, name, success=True): pass


# ── mock fixture data (--mock-data flag) ─────────────────────────────────────
def _mock_state(run_id: str) -> AgentState:
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    events = [
        CalendarEvent(
            source="google_calendar",
            title="Team standup",
            start_time=now.replace(hour=9, minute=30),
            end_time=now.replace(hour=9, minute=45),
        ),
        CalendarEvent(
            source="apple_ical",
            title="Dentist appointment",
            start_time=now.replace(hour=14, minute=0),
            end_time=now.replace(hour=15, minute=0),
            location="123 Dental St",
        ),
        CalendarEvent(
            source="google_calendar",
            title="1:1 with Sarah",
            start_time=now.replace(hour=16, minute=0),
            end_time=now.replace(hour=16, minute=30),
        ),
    ]
    plan = DailyPlanData(
        calendar_events=events,
        calendar_summary="3 events today: standup at 9:30, dentist at 2pm, 1:1 at 4pm.",
        weather=WeatherData(
            condition="Sunny",
            temperature_high=78,
            temperature_low=62,
            precipitation_probability=5,
            humidity=45,
            wind_speed_mph=8,
            sunrise=now.replace(hour=6, minute=15),
            sunset=now.replace(hour=20, minute=5),
        ),
        weather_summary="Sunny and 78°F, great day to be outside.",
        commute=CommuteData(
            from_address="Home",
            to_address="Office",
            estimated_duration_minutes=28,
            traffic_condition="moderate",
        ),
        commute_summary="28 minute commute, leave by 8:45 AM.",
        workout_recommendation=WorkoutRecommendation(
            duration_minutes=30,
            recommended_time="morning",
        ),
        # Mock location — LocationService populates these for real runs
        user_timezone="UTC",
        user_city="Mock City",
        user_lat=0.0,
        user_lng=0.0,
    )
    return AgentState(run_id=run_id, user_id="local-sim", plan=plan)


# ── real data via PlanningAgent ───────────────────────────────────────────────
async def _build_real_state(run_id: str, settings) -> AgentState:
    from app.agents.planning_agent import PlanningAgent
    from app.adapters.calendar.google_calendar import GoogleCalendarAdapter
    from app.adapters.calendar.apple_ical import AppleICalAdapter
    from app.adapters.weather import WeatherAdapter
    from app.adapters.maps import MapsAdapter

    logger = NullLogger()

    calendar_adapters = [
        GoogleCalendarAdapter(logger, settings),
        AppleICalAdapter(
            logger,
            caldav_url=settings.apple_ical_caldav_url,
            username=settings.apple_ical_username,
            password=settings.apple_ical_password,
        ),
    ]
    weather_adapter = WeatherAdapter(logger, settings.weather_api_key, settings.weather_provider)
    maps_adapter = MapsAdapter(logger, settings.google_maps_api_key)

    agent = PlanningAgent(
        debug_logger=logger,
        calendar_adapters=calendar_adapters,
        weather_adapter=weather_adapter,
        maps_adapter=maps_adapter,
    )
    state = AgentState(run_id=run_id, user_id="local-sim")
    return await agent.run(state)


# ── conversation REPL ─────────────────────────────────────────────────────────
async def _run_conversation(state: AgentState, agent_obj, args) -> AgentState:
    from app.agents.conversation_agent import ConversationAgent

    # Generate and display the opening plan
    system("Generating your daily plan...")
    plan_data_raw = await agent_obj._generate_plan_with_llm(state)
    agent_obj._update_plan_from_llm_response(state, plan_data_raw)
    opening = agent_obj._format_plan_for_speech(state.plan)
    state.transcript.append({"role": "assistant", "content": opening})
    agent(opening)

    label("\n─── Your turn ────────────────────────────────────────────────────")
    label("  Type your response and press Enter. Commands:")
    label("  'done'   → end the call (same as confirming)")
    label("  'quit'   → exit without creating events")
    label("  'show'   → print current plan state")
    label("──────────────────────────────────────────────────────────────────\n")

    confirmed = False
    turn = 0

    while True:
        turn += 1
        try:
            user_text = input(f"{YELLOW}You [{turn}]: {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            system("Call ended by user.")
            break

        if not user_text:
            continue

        if user_text.lower() == "quit":
            system("Exiting without creating events.")
            return state

        if user_text.lower() == "show":
            _print_plan(state)
            continue

        if user_text.lower() == "done":
            user_text = "Yes, that all sounds good, go ahead."

        state.user_input = user_text
        action, response = await agent_obj.process_user_input(state)
        agent(response)

        dim(f"[action={action}  ad_hoc_events={len(state.ad_hoc_events)}]")

        if action == "confirm":
            confirmed = True
            break

    return state, confirmed


def _print_plan(state: AgentState):
    p = state.plan
    if not p:
        print("  (no plan yet)")
        return
    print(f"\n{BOLD}Current plan snapshot:{RESET}")
    print(f"  Calendar : {p.calendar_summary}")
    print(f"  Weather  : {p.weather_summary}")
    print(f"  Commute  : {p.commute_summary}")
    if p.workout_recommendation:
        print(f"  Workout  : {p.workout_recommendation.recommended_time} — {p.workout_recommendation.duration_minutes} min")
    if p.final_summary:
        print(f"  Summary  : {p.final_summary}")
    if state.ad_hoc_events:
        print(f"  Ad-hoc events to create ({len(state.ad_hoc_events)}):")
        for e in state.ad_hoc_events:
            print(f"    • {e.get('title')} @ {e.get('start_time')}")
    print()


# ── post-call: create events + send summary ───────────────────────────────────
async def _post_call(state: AgentState, agent_obj, settings, args):
    if args.no_calendar or not state.ad_hoc_events:
        if state.ad_hoc_events and args.no_calendar:
            system(f"Skipping calendar writes (--no-calendar). Would have created: {[e.get('title') for e in state.ad_hoc_events]}")
    else:
        from app.adapters.calendar.google_calendar import GoogleCalendarAdapter
        from app.adapters.calendar.apple_ical import AppleICalAdapter

        logger = NullLogger()
        calendar_adapters = [
            GoogleCalendarAdapter(logger, settings),
            AppleICalAdapter(
                logger,
                caldav_url=settings.apple_ical_caldav_url,
                username=settings.apple_ical_username,
                password=settings.apple_ical_password,
            ),
        ]

        system(f"Creating {len(state.ad_hoc_events)} ad-hoc event(s) in calendar...")
        created = await agent_obj.create_calendar_events_from_state(state, calendar_adapters)
        for ev in created:
            system(f"  ✓ Created '{ev.title}' (id={ev.external_id or 'n/a'})")
        if not created:
            err("No events were created (check adapter config).")

    # Generate and show post-call summary
    system("Generating post-call summary...")
    summary = await agent_obj.generate_post_call_summary(state)
    print(f"\n{BOLD}{'─'*60}")
    print(f"  POST-CALL SUMMARY (would be sent as iMessage / SMS){RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")
    print(summary)
    print(f"{BOLD}{'─'*60}{RESET}\n")

    if args.no_summary:
        system("Skipping iMessage/SMS send (--no-summary).")
    else:
        try:
            from app.adapters.messaging.imessage_bridge import IMessageBridgeAdapter
            msg_adapter = IMessageBridgeAdapter(
                NullLogger(),
                bridge_url=getattr(settings, "imessage_bridge_url", None),
            )
            phone = getattr(settings, "user_phone_number", None)
            if phone:
                system(f"Sending summary to {phone}...")
                result = await agent_obj.send_summary(state, msg_adapter, phone)
                system(f"  {'✓ Sent' if result else '✗ Failed'}")
            else:
                system("USER_PHONE_NUMBER not set — skipping send.")
        except Exception as e:
            system(f"iMessage send skipped ({e}). Set up bridge to enable.")


# ── main ──────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Simulate a DailyOps AI morning call in the terminal.")
    parser.add_argument("--mock-data", action="store_true", help="Use hardcoded fixture data instead of live APIs")
    parser.add_argument("--no-calendar", action="store_true", help="Skip calendar event creation after confirm")
    parser.add_argument("--no-summary", action="store_true", help="Skip iMessage/SMS send at end")
    args = parser.parse_args()

    settings = get_settings()
    run_id = str(uuid.uuid4())[:8]

    print(f"\n{BOLD}{'═'*60}")
    print(f"  DailyOps AI — Call Simulator  (run_id={run_id})")
    print(f"{'═'*60}{RESET}\n")

    # ── Phase 1: gather data ──────────────────────────────────────────────────
    if args.mock_data:
        system("Using mock fixture data (--mock-data).")
        state = _mock_state(run_id)
    else:
        system("Fetching live data (calendar, weather, commute)...")
        try:
            state = await _build_real_state(run_id, settings)
        except Exception as e:
            err(f"PlanningAgent failed: {e}")
            err("Try --mock-data to run without live APIs.")
            sys.exit(1)

    if state.error:
        err(f"Planning error: {state.error}")
        err("Continuing with partial data...")

    # ── Phase 2: conversation ─────────────────────────────────────────────────
    from app.agents.conversation_agent import ConversationAgent

    # Match whichever provider is configured in .env
    if settings.openrouter_api_key:
        provider = "openrouter"
    elif settings.anthropic_api_key:
        provider = "anthropic"
    else:
        provider = "openai"

    agent_obj = ConversationAgent(
        debug_logger=NullLogger(),
        provider=provider,
    )

    result = await _run_conversation(state, agent_obj, args)
    if isinstance(result, tuple):
        state, confirmed = result
    else:
        state, confirmed = result, False

    # ── Phase 3: post-call ────────────────────────────────────────────────────
    print(f"\n{BOLD}{'─'*60}{RESET}")
    if confirmed:
        system("Call confirmed — running post-call flow.")
        await _post_call(state, agent_obj, settings, args)
    else:
        system("Call ended without confirmation — skipping calendar writes.")
        _print_plan(state)

    # ── Transcript ────────────────────────────────────────────────────────────
    try:
        show_transcript = input(f"\n{YELLOW}Show full transcript? [y/N]: {RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        show_transcript = "n"
    if show_transcript == "y":
        print(f"\n{BOLD}Transcript:{RESET}")
        for turn in state.transcript:
            role = turn.get("role", "?")
            colour = CYAN if role == "assistant" else YELLOW
            prefix = "Agent" if role == "assistant" else "You  "
            print(f"  {colour}{prefix}{RESET}: {turn.get('content', '')}")

    print(f"\n{GREEN}Done.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
