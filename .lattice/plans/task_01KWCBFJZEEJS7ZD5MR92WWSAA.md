# DOPS-25: Cache and reuse daily plan — skip re-fetch if plan already generated today

Once `PlanningAgent.run()` generates and stores the daily plan in Supabase, subsequent calls and conversations the same day should load that cached plan rather than re-fetching calendar, weather, and commute data. The `daily_plans` table already persists the serialised `DailyPlanData`; the fix is a cache-check at call entry that avoids redundant API calls while keeping the full pipeline available on cache miss or explicit refresh.

---

## Audit of existing state

| What exists | Location |
|---|---|
| `PlanningAgent.run()` — full data-fetch pipeline | `agents/planning_agent.py` |
| `daily_plans` Supabase table — stores serialised plan + `generated_at` | `migrations/001_initial_schema.sql` |
| `AgentState.plan: DailyPlanData` — in-memory plan during a call | `agents/state.py` |
| Call entry point (Vapi) | `api/vapi_webhooks.py` — `_handle_call_started` and inbound PROPFIND block |
| Local REPL entry point | `backend/simulate_call.py` — Phase 1 block |
| Settings | `config.py` — add `plan_cache_ttl_hours` |

No cache-check exists today; every call unconditionally calls `PlanningAgent.run()`.

---

## Design

### 1. `agents/planning_agent.py` — add `load_today_plan()`

```python
async def load_today_plan(
    self, user_id: str, force_refresh: bool = False
) -> DailyPlanData | None:
    """Return today's cached plan from Supabase, or None on miss/stale/forced."""
```

Logic:
1. If `force_refresh`, return `None` immediately.
2. Query `daily_plans` where `user_id = user_id` AND `plan_date = today` ORDER BY `generated_at DESC` LIMIT 1.
3. If no row → return `None` (cache miss).
4. If `generated_at` is older than `settings.plan_cache_ttl_hours` → return `None` (stale).
5. Deserialise JSON column → `DailyPlanData` and return it.

Log `plan_cache_hit` or `plan_cache_miss` to `debug_logger` with `generated_at` and `age_minutes`.

### 2. `agents/state.py` — add `plan_source` field

```python
plan_source: Literal["fresh", "cached"] = "fresh"
```

Set to `"cached"` in callers when `load_today_plan()` returns a value.

### 3. `api/vapi_webhooks.py` — cache-check before `run()`

In `_handle_call_started` (and the inbound call refresh block):

```python
cached = await planning_agent.load_today_plan(user_id)
if cached:
    state.plan = cached
    state.plan_source = "cached"
else:
    state = await planning_agent.run(user_id)
    state.plan_source = "fresh"
```

### 4. `backend/simulate_call.py` — same pattern in Phase 1

Add `--force-refresh` CLI flag that passes `force_refresh=True` to `load_today_plan()`.

### 5. `config.py` — new setting

```python
plan_cache_ttl_hours: int = Field(default=8, env="PLAN_CACHE_TTL_HOURS")
```

Add `PLAN_CACHE_TTL_HOURS=8` to `.env.template`.

---

## Files changed

| File | Change |
|---|---|
| `agents/planning_agent.py` | Add `load_today_plan()` |
| `agents/state.py` | Add `plan_source` field |
| `api/vapi_webhooks.py` | Cache-check before `planning_agent.run()` |
| `backend/simulate_call.py` | Cache-check + `--force-refresh` flag |
| `config.py` | Add `plan_cache_ttl_hours` setting |
| `.env.template` | Add `PLAN_CACHE_TTL_HOURS=8` |

---

## Acceptance criteria

| Criterion | How verified |
|---|---|
| Second call of the day skips calendar/weather/commute APIs | Check debug_logs — no `calendar_fetch_*` events after first call |
| `debug_logs` shows `plan_cache_hit` with `generated_at` | Query `debug_logs` table after second call |
| `plan_source = "cached"` in AgentState | Print `state.plan_source` in simulate_call.py output |
| Cache miss runs full pipeline | Delete today's `daily_plans` row; trigger call; confirm `plan_cache_miss` log |
| `force_refresh=True` bypasses cache | `python simulate_call.py --force-refresh`; confirm fresh fetch |
| TTL configurable via env var | Set `PLAN_CACHE_TTL_HOURS=0`; confirm cache always misses |

---

## Test run

```bash
cd backend
pytest app/tests/test_planning_agent.py -v -k "cache"
# Expected: TestPlanCache — ~5 new tests covering hit / miss / stale / force_refresh
```

---

## Open notes

- If `daily_plans` JSON schema changes between versions, deserialisation may fail — wrap in try/except and treat as cache miss, log `plan_cache_deserialise_error`.
- Multi-user: `load_today_plan()` is already scoped to `user_id`; no cross-user risk.
- The cached plan does not update mid-day if calendar events change — acceptable for MVP; DOPS-26 could add explicit mid-day refresh via iMessage command.
