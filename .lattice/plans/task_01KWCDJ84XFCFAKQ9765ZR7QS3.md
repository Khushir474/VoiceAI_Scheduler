# DOPS-26: Detect current user location at call time

Replace stored home address with real-time location detection so travelers get accurate local time and weather.

Primary approach: scan today's calendar events for travel keywords (flight, hotel, traveling to, arriving in, conference in) and extract destination city/timezone. Wire into PlanningAgent before weather fetch.

Fallback: ConversationAgent asks user at call start if travel is detected or ambiguous ('Are you home today or somewhere different?').

Future: mobile companion app that pushes GPS coordinates to the API before the 6 AM call; store in Redis with 1-hour TTL.

Cleanup: remove LocationService (app/services/location.py) — IP geolocation returns server location not user location. Remove the 4 location columns added to daily_context in migration 004 (or keep as nullable and populate from calendar inference instead).
