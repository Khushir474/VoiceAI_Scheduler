# DOPS-8: Add calendar event creation (voice-triggered write)

Calendar adapters are read-only. Add create_event() to CalendarAdapter base class and implement in GoogleCalendarAdapter and AppleICalAdapter. Conversation agent triggers event creation after user confirms. Only ADD events, no decline/delete. Touches: adapters/calendar/base.py, google_calendar.py, apple_ical.py, conversation_agent.py. Acceptance: Agent can create events in both Google Calendar and Apple iCal; confirmation flow before write; mutations logged to debug_logs.
