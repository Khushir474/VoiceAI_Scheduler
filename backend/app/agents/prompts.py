"""Structured prompts for plan generation and conversation."""

from __future__ import annotations

from app.agents.state import DailyPlanData, AgentState
import json


class PlanGenerationPrompt:
    """Prompts for generating daily plans using LLM."""

    @staticmethod
    def system_prompt() -> str:
        """System prompt for the conversation agent."""
        return """You are DailyOps AI, a helpful morning productivity assistant. Your job is to:
1. Review the user's calendar events, weather, and commute information
2. Generate a structured daily plan with recommendations
3. Ask about any missing events or plans

You should be friendly, concise, and actionable. Provide specific recommendations for:
- When to leave for work/destinations
- Best time to workout based on calendar and weather
- What to bring/wear based on weather and meetings
- Any gaps in the calendar that might need planning

Always respond with a JSON-formatted plan that includes:
- calendar_summary: Brief summary of key events
- weather_summary: What to wear/expect weather-wise
- commute_summary: Travel time and traffic info
- workout_recommendation: Suggested workout time and duration
- leave_time: Specific time to leave in ISO format (or null)
- carry_items: List of things to bring
- final_summary: Natural language summary of the day's plan
- missing_events_prompt: Question about any events we missed"""

    @staticmethod
    def generate_plan_prompt(state: AgentState) -> str:
        """Generate a prompt for creating the daily plan."""
        plan_input = state.plan or {}

        # Build context from state
        calendar_context = ""
        if state.plan and state.plan.calendar_events:
            events = [
                f"- {e.title} at {e.start_time.strftime('%I:%M %p')}"
                for e in state.plan.calendar_events
            ]
            calendar_context = f"Calendar Events:\n" + "\n".join(events)
        else:
            calendar_context = "No calendar events for today"

        weather_context = ""
        if state.plan and state.plan.weather:
            w = state.plan.weather
            weather_context = f"""Weather for today:
- Temperature: {w.temperature_low}°F to {w.temperature_high}°F
- Condition: {w.condition}
- Humidity: {w.humidity}%
- Wind: {w.wind_speed_mph} mph
- Rain probability: {w.precipitation_probability}%
- Sunrise: {w.sunrise.strftime('%I:%M %p')}
- Sunset: {w.sunset.strftime('%I:%M %p')}"""
        else:
            weather_context = "Weather data not available"

        commute_context = ""
        if state.plan and state.plan.commute:
            c = state.plan.commute
            commute_context = f"""Commute Information:
- From: {c.from_address}
- To: {c.to_address}
- Duration: {c.estimated_duration_minutes} minutes
- Traffic: {c.traffic_condition}"""
        else:
            commute_context = "Commute data not available"

        prompt = f"""Based on this information, create a structured daily plan for the user:

{calendar_context}

{weather_context}

{commute_context}

Please generate recommendations for:
1. When they should leave home/office (accounting for traffic and first meeting)
2. Best time to workout (fitting around their schedule and weather)
3. What to bring/wear (based on weather and meetings)
4. A natural language summary of their day
5. A question about any events we might have missed

Respond with ONLY a valid JSON object (no markdown, no extra text) with this structure:
{{
  "calendar_summary": "string - Brief summary of today's events",
  "weather_summary": "string - Weather advice and what to wear",
  "commute_summary": "string - Commute timing and traffic info",
  "leave_time": "ISO 8601 datetime string or null",
  "workout_recommendation": {{
    "duration_minutes": number,
    "recommended_time": "morning" | "evening" | "flexible",
    "start_time": "ISO 8601 datetime string or null",
    "end_time": "ISO 8601 datetime string or null",
    "notes": "string or null"
  }},
  "carry_items": ["item1", "item2", ...],
  "final_summary": "string - Natural language summary of the day",
  "missing_events_prompt": "string - Question about missed events"
}}"""

        return prompt

    @staticmethod
    def user_input_processing_prompt(
        user_input: str,
        current_plan: DailyPlanData,
    ) -> str:
        """Generate a prompt for processing user input with full local context.

        Timezone and city come from current_plan, which is populated by LocationService
        at call-start. No hardcoded values here.
        """
        from datetime import datetime, timezone
        import zoneinfo

        user_timezone = current_plan.user_timezone or "UTC"
        user_city = current_plan.user_city or "Unknown location"

        try:
            tz = zoneinfo.ZoneInfo(user_timezone)
        except Exception:
            tz = timezone.utc

        now_local = datetime.now(tz)
        local_time_str = now_local.strftime("%A, %B %-d %Y %-I:%M %p %Z")   # e.g. "Tuesday, July 1 2026 8:42 AM CDT"
        today_date = now_local.strftime("%Y-%m-%d")
        utc_offset = now_local.strftime("%z")                                # e.g. "-0500"
        utc_offset_colon = f"{utc_offset[:3]}:{utc_offset[3:]}"             # e.g. "-05:00"

        # Remaining events today (start_time after now)
        remaining = [
            e for e in current_plan.calendar_events
            if e.start_time.astimezone(tz) > now_local
        ] if current_plan.calendar_events else []
        events_str = "\n".join(
            f"  - {e.start_time.astimezone(tz).strftime('%-I:%M %p')}: {e.title}"
            + (f" at {e.location}" if e.location else "")
            for e in remaining
        ) or "  (none remaining today)"

        # Weather snapshot
        w = current_plan.weather
        weather_str = (
            f"{w.condition}, {w.temperature_high}°F high / {w.temperature_low}°F low, "
            f"{w.precipitation_probability}% rain"
        ) if w else current_plan.weather_summary or "unknown"

        return f"""## User context
Location : {user_city}
Local time: {local_time_str}
Weather   : {weather_str}

## Remaining events today
{events_str}

## The user just said
"{user_input}"

## Your task
Classify the input and respond in JSON. Actions:
- "add_event"  — user mentioned something to add to the calendar
- "confirm"    — user approved the plan / said yes / said they're good
- "clarify"    — user asked a question or said something ambiguous
- "decline"    — user rejected a recommendation

### Time rules for add_event
All times MUST be ISO 8601 with the user's UTC offset ({utc_offset_colon}), e.g. "{today_date}T14:00:00{utc_offset_colon}".
- Use the EXACT time the user stated ("at 2pm" → 14:00 local = "{today_date}T14:00:00{utc_offset_colon}").
- "tonight" / "this evening" → 18:00 local today.
- "tomorrow morning" → 09:00 next day. "tomorrow afternoon" → 14:00 next day.
- No time stated → 12:00 local today.
- end_time = start_time + 1 hour unless the user specified a duration.
- NEVER output start_time as null when action is "add_event".

Respond with JSON only — no markdown, no code fences:
{{
  "action": "add_event" | "confirm" | "clarify" | "decline",
  "new_event": {{
    "title": "string",
    "start_time": "ISO 8601 with UTC offset — REQUIRED for add_event",
    "end_time": "ISO 8601 with UTC offset — REQUIRED for add_event",
    "location": "string or null"
  }} | null,
  "response": "string - natural language reply to user",
  "updated_plan": {{
    "final_summary": "string - updated plan summary including the new event"
  }} | null
}}"""


class ConversationPrompt:
    """Prompts for multi-turn conversation."""

    @staticmethod
    def confirmation_prompt(plan: DailyPlanData) -> str:
        """Prompt for confirming the plan with the user."""
        return f"""The user has reviewed the plan. Ask them to confirm:

Current plan:
{plan.final_summary}

Ask a simple confirmation question (yes/no) to wrap up the conversation.
Respond with JSON:
{{
  "message": "string - Question to confirm plan",
  "response_options": ["yes", "no"]
}}"""

    @staticmethod
    def refinement_prompt(plan: DailyPlanData, user_feedback: str) -> str:
        """Prompt for refining the plan based on user feedback."""
        return f"""The user gave this feedback: "{user_feedback}"

Current plan:
{plan.final_summary}

Refine the plan based on their feedback and provide an updated summary.
Respond with JSON:
{{
  "refined_summary": "string - Updated plan based on feedback",
  "acknowledgment": "string - Acknowledge their feedback",
  "action_items": ["item1", "item2", ...]
}}"""


class PostCallSummaryPrompt:
    """Prompts for generating a post-call summary using the full call context."""

    @staticmethod
    def system_prompt() -> str:
        return (
            "You are DailyOps AI generating a post-call daily summary. "
            "You have access to everything: the pre-fetched calendar, weather, and commute data, "
            "plus the complete call transcript showing what the user actually said. "
            "Produce a concise, friendly summary that reflects ALL of this — "
            "including any events or corrections the user mentioned during the call. "
            "The summary will be sent as an SMS/iMessage."
        )

    @staticmethod
    def generate_summary_prompt(state: AgentState) -> str:
        plan = state.plan

        # Calendar section
        if plan and plan.calendar_events:
            cal_lines = [
                "- {title} at {time}{loc}".format(
                    title=e.title,
                    time=e.start_time.strftime("%I:%M %p"),
                    loc=f" ({e.location})" if e.location else "",
                )
                for e in plan.calendar_events
            ]
            calendar_section = "\n".join(cal_lines)
        elif plan and plan.calendar_summary:
            calendar_section = plan.calendar_summary
        else:
            calendar_section = "None fetched"

        weather_section = (plan.weather_summary if plan and plan.weather_summary else "Not available")
        commute_section = (plan.commute_summary if plan and plan.commute_summary else "Not available")

        leave_section = "Not set"
        if plan and plan.leave_time:
            leave_section = plan.leave_time.strftime("%I:%M %p")

        carry_section = (", ".join(plan.carry_items) if plan and plan.carry_items else "None noted")

        workout_section = "None recommended"
        if plan and plan.workout_recommendation:
            wr = plan.workout_recommendation
            workout_section = f"{wr.duration_minutes} min in the {wr.recommended_time}"

        # Transcript section
        if state.transcript:
            transcript_lines = [
                f"{t.get('role', 'unknown').capitalize()}: {t.get('content', '')}"
                for t in state.transcript
                if t.get("content")
            ]
            transcript_section = "\n".join(transcript_lines)
        else:
            transcript_section = "No transcript available"

        return f"""Generate a post-call daily summary using ALL the context below.

## Pre-Call Plan
Calendar Events:
{calendar_section}

Weather: {weather_section}
Commute: {commute_section}
Suggested Leave Time: {leave_section}
Items to Bring: {carry_section}
Workout: {workout_section}

## Full Call Transcript
{transcript_section}

## Instructions
1. Start with "Good morning! Here's your DailyOps summary:"
2. List ALL calendar events — original ones AND any the user mentioned during the call
3. Reflect any corrections the user made (e.g., changed times, cancelled events)
4. Include weather and commute info
5. Include leave time and carry items
6. Mention workout if applicable
7. Keep it under 280 words; plain text, SMS-friendly (light emoji OK)

Write ONLY the summary text — no JSON, no markdown, no extra commentary."""
