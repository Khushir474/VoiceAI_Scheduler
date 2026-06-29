"""Structured prompts for plan generation and conversation."""

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
    def user_input_processing_prompt(user_input: str, current_plan: DailyPlanData) -> str:
        """Generate a prompt for processing user input and updating the plan."""
        return f"""The user just said: "{user_input}"

Current plan summary:
- {current_plan.calendar_summary}
- {current_plan.weather_summary}
- {current_plan.final_summary}

Based on their input, determine if they're:
1. Providing missing events (e.g., "I have a dentist appointment at 2pm")
2. Confirming they understood the plan
3. Asking for clarification
4. Declining a recommendation

If they mentioned an event, extract it and provide an updated plan.
Otherwise, acknowledge their input and confirm next steps.

Respond with JSON:
{{
  "action": "add_event" | "confirm" | "clarify" | "decline",
  "new_event": {{
    "title": "string or null",
    "start_time": "ISO 8601 or null",
    "end_time": "ISO 8601 or null",
    "location": "string or null"
  }} | null,
  "response": "string - Natural language response to user",
  "updated_plan": {{
    "final_summary": "string - Updated plan summary"
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
