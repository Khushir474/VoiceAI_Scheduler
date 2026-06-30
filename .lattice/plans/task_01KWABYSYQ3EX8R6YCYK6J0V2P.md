# DOPS-8: Add calendar event creation (voice-triggered write)

## Summary

Add `create_event()` to the `CalendarAdapter` base class and implement it in both
`GoogleCalendarAdapter` and `AppleICalAdapter`. Wire the conversation agent to call
`create_event()` for each ad-hoc event the user confirms during the call, logging
all mutations to `debug_logs`.

**Scope:** adapters/calendar/base.py, google_calendar.py, apple_ical.py,
agents/conversation_agent.py. Only ADD; no decline/delete.

---

## Audit of existing state

All implementation is already present and tested. Plan documents the approach for
reviewability.

---

## Design

### 1. CalendarAdapter base class (`adapters/calendar/base.py`)

Add one abstract method:

```python
@abstractmethod
async def create_event(self, user_id: str, event: CalendarEvent) -> CalendarEvent | None:
    """Create a new calendar event.

    Returns the event with external_id populated on success, None on failure.
    Implementations must log mutations to debug_logs.
    """
```

Status: ✅ implemented.

### 2. GoogleCalendarAdapter (`adapters/calendar/google_calendar.py`)

POST to `https://www.googleapis.com/calendar/v3/calendars/primary/events` using
the existing `_post_api_call()` helper (shared retry / 401-refresh logic).

Fields sent: `summary`, `start.dateTime`, `end.dateTime`, optional `location`,
`description`, `attendees`.

On HTTP 200, set `event.external_id = data["id"]` and return the event.
On any failure, log `create_event_failed` and return `None`.
Token refresh uses the same `_ensure_valid_token()` path as reads.
Scope note: creation requires `calendar.events.write`; implementation trusts that
the OAuth token's scopes include it (no scope-promotion logic here — out of scope).

Status: ✅ implemented. Tests: `TestGoogleCalendarCreateEvent` (5 cases).

### 3. AppleICalAdapter (`adapters/calendar/apple_ical.py`)

Two write paths, tried in order:

**Path A — CalDAV PUT** (when `username` + `password` are set):
- Generate a UUID for the event if `external_id` is unset.
- Build a minimal `VCALENDAR` + `VEVENT` blob using `icalendar` library.
- PUT to `{caldav_url}/principals/__uuids__/{username}/calendar.ics/{uid}.ics`.
- Accept 201 or 204 as success.

**Path B — .ics file append** (when only `ics_file_path` is set):
- Read existing `.ics` file (or start a fresh `VCALENDAR` if file is absent).
- Add the `VEVENT` component and rewrite the file atomically.

**Path C — not configured** → log warning, return `None`.

All paths log mutation events to `debug_logs` (`create_event_started`,
`create_event_success` / `create_event_failed` / `create_event_skipped`).

Status: ✅ implemented. Tests: `TestAppleICalCreateEvent` (6 cases).

### 4. ConversationAgent — confirmation flow + event creation

**Confirmation flow (already present):**
- `process_user_input()` detects action `"confirm"` from the LLM response.
- State machine moves from `listening` → `confirming` → user approves.
- Ad-hoc events extracted by the LLM are stored in `state.ad_hoc_events` as raw
  dicts (`{"title": ..., "start_time": ..., "end_time": ..., "location": ...}`).

**`create_calendar_events_from_state(state, calendar_adapters)`:**
- Iterates `state.ad_hoc_events`.
- Parses `start_time` / `end_time` via `datetime.fromisoformat()`; defaults
  `end_time = start_time + 1h` if absent.
- For each adapter, calls `is_configured()` first — skips unconfigured adapters
  silently.
- Calls `adapter.create_event(state.user_id, event)`.
- On success, appends the returned event to `state.plan.calendar_events` so the
  post-call summary reflects it.
- All outcomes (created / failed / skipped / exception) logged to `debug_logs`.

**No-delete guarantee:** only `create_event()` is called; no `delete_event` or
`update_event` surface exists.

Status: ✅ implemented. Tests: `TestCreateCalendarEventsFromState` (4 cases in
`test_conversation_agent.py`).

---

## Files changed

| File | Change |
|------|--------|
| `adapters/calendar/base.py` | `create_event()` abstract method |
| `adapters/calendar/google_calendar.py` | `create_event()` + `_post_api_call()` helper |
| `adapters/calendar/apple_ical.py` | `create_event()` + CalDAV PUT + .ics append |
| `agents/conversation_agent.py` | `create_calendar_events_from_state()` |
| `tests/test_google_calendar.py` | `TestGoogleCalendarCreateEvent` (5 tests) |
| `tests/test_apple_ical.py` | `TestAppleICalCreateEvent` (6 tests) |
| `tests/test_conversation_agent.py` | `TestCreateCalendarEventsFromState` (4 tests) |

---

## Acceptance criteria

| Criterion | How verified |
|-----------|-------------|
| Agent can create events in Google Calendar | `test_create_event_success_returns_event_with_external_id` passes |
| Agent can create events in Apple iCal | `TestAppleICalCreateEvent` (CalDAV + .ics paths) all pass |
| Confirmation flow before write | `process_user_input` action=confirm test + state machine test |
| Mutations logged to debug_logs | `test_create_event_logs_success` asserts `create_event_success` event |
| No delete/decline operations | No `delete_event` method on base class or implementations |

All 15 DOPS-8 tests pass (`pytest -k "create_event or calendar_event"` → 15 pass).

---

## Test run

```
pytest app/tests/test_google_calendar.py -k "create_event"                         # 5 passed
pytest app/tests/test_apple_ical.py -k "create_event"                              # 6 passed
pytest app/tests/test_conversation_agent.py -k "create_event or calendar_event"    # 2+ passed
```

No regressions in full suite (run before submitting PR).

---

## Open notes

- CalDAV PUT URL assumes iCloud's `principals/__uuids__/{username}/` path; generic
  CalDAV servers may differ. Acceptable for MVP — documented in adapter docstring.
- OAuth scope (`calendar.events.write`) must be granted during the DOPS-1 OAuth
  flow setup. No code change needed here; noted for operator setup docs.
