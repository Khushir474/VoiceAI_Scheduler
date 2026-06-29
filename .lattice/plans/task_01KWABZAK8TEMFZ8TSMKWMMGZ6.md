# DOPS-10: Pre-event buffer user preference

Add first_event_buffer_minutes to user_preferences table (default 60). Planning agent reads this preference and calculates: wake_time = first_event_time - commute_minutes - buffer_minutes. Include buffer rationale in plan summary and voice call. Edge case: alert user if buffer + commute exceeds available time. Touches: migrations/, agents/state.py, agents/planning_agent.py. Acceptance: Preference persisted in DB; wake-up time recommendation accounts for buffer; voice agent mentions buffer.
