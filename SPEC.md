# Phase 3 Specification: Real APIs & LLMs

## Project Summary

**DailyOps AI – Phase 3** completes the real-world integration layer, replacing mocks with production APIs and LLM backends. The system now fetches real calendar events, actual weather, real routing data, and uses Claude/OpenAI for conversation logic.

## Goals & Scope

Replace all mock implementations with production APIs:
- ✅ Google Calendar OAuth + event fetching
- ✅ Apple iCal file parsing or CalDAV streaming
- ✅ Real Vapi call orchestration (not webhook mocks)
- ✅ OpenWeather or WeatherAPI integration
- ✅ Google Maps Distance Matrix API for commute
- ✅ Claude/OpenAI conversation agent

## Success Criteria

A daily planning run that:
1. **Authenticates** with Google Calendar via OAuth and retrieves actual events
2. **Merges** events from Google + Apple iCal without duplication
3. **Fetches** real weather forecast for the user's location
4. **Estimates** actual commute time to work address via Google Maps
5. **Converses** with the user using Claude or OpenAI LLM (not hardcoded responses)
6. **Generates** a final iMessage summary sent via real bridge or Twilio
7. **Logs** every step to Supabase + Langfuse for observability
8. **Handles** all error states gracefully with fallbacks
9. **Completes** end-to-end in <8 seconds (target latency)

## Acceptance Criteria (per API)

### Google Calendar
- [ ] OAuth 2.0 flow implemented (retrieve refresh token)
- [ ] `get_events_for_date()` fetches real events from user's primary calendar
- [ ] Handles rate limiting + pagination
- [ ] Caches events in `calendar_events` table with dedup

### Apple iCal
- [ ] Accepts `.ics` file upload or CalDAV stream URL
- [ ] Parses all-day, recurring, and timed events
- [ ] Normalizes to `CalendarEvent` schema
- [ ] Merges with Google events via `CalendarMerger`

### Weather API
- [ ] Calls OpenWeather or WeatherAPI for user's location
- [ ] Returns temp, condition, precipitation chance
- [ ] Caches for 1 hour to avoid rate limits
- [ ] Fallback to last-known weather on API error

### Google Maps Distance Matrix
- [ ] Queries commute time (home → work address)
- [ ] Returns ETA, current traffic, recommendations for leave time
- [ ] Handles multiple mode (driving, transit, walking)
- [ ] Caches for 30 min

### Vapi Integration
- [ ] `initiate_call()` creates a real Vapi call (not mock)
- [ ] WebSocket connection receives live transcript
- [ ] Handles call state transitions (connecting → in_call → ended)
- [ ] Gracefully closes on user hangup

### Conversation Agent (Claude/OpenAI)
- [ ] Takes merged calendar events + weather + commute as context
- [ ] Calls Claude or OpenAI to generate plan recommendations
- [ ] Asks clarifying questions (missing events, preferences)
- [ ] Confirms final plan before sending summary

### Observability
- [ ] All API calls logged to Supabase `debug_logs` + `tool_calls`
- [ ] Langfuse spans for latency breakdown per component
- [ ] Error tracking with retry counts + fallback used

## Non-Goals

- User authentication (Supabase Auth is scaffolded, out of scope for MVP)
- Mobile app (web dashboard only)
- Predictive/memory features (Phase 4)
- Scaling to millions of users (MVP is single-user friendly)

## Tech Stack (Phase 3)

- **Google Calendar**: oauth2session (requests-oauthlib)
- **Apple iCal**: icalendar library (.ics parsing)
- **Weather**: OpenWeather API (free tier)
- **Commute**: Google Maps Distance Matrix API
- **Voice**: Vapi (production keys, real calls)
- **LLM**: Claude API via Anthropic SDK (or OpenAI if preferred)
- **Database**: Supabase (existing)
- **Observability**: Langfuse (existing)

## Timeline

Parallel delegator dispatch (target: 2–3 days for small team):
- **Delegator 1**: Google Calendar OAuth + adapter
- **Delegator 2**: Apple iCal + calendar merge
- **Delegator 3**: Weather + Maps adapters
- **Delegator 4**: Vapi real endpoint integration
- **Delegator 5**: Conversation agent + error recovery

All work feeds into integration tests + dashboard validation.

---

## References

- **Architecture**: [TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md)
- **Voice UX**: [CONVERSATION_DESIGN.md](CONVERSATION_DESIGN.md)
- **Current Status**: [README.md](README.md#phase-3-real-apis--llms)
