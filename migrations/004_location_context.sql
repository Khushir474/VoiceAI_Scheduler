-- Migration 004: Add location context columns to daily_context
--
-- Location is detected once per call via IP geolocation (LocationService → ipapi.co)
-- and stored here so every agent read is a single Supabase fetch, not a live API call.
-- The agent reads user_timezone from this row when building LLM prompts — no hardcoding.

ALTER TABLE daily_context
  ADD COLUMN IF NOT EXISTS user_timezone TEXT NOT NULL DEFAULT 'UTC',
  ADD COLUMN IF NOT EXISTS user_city     TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS user_lat      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS user_lng      DOUBLE PRECISION;

COMMENT ON COLUMN daily_context.user_timezone IS 'IANA timezone name detected at call-start (e.g. America/Chicago)';
COMMENT ON COLUMN daily_context.user_city     IS 'Display city name from IP geolocation (e.g. Chicago, Illinois)';
COMMENT ON COLUMN daily_context.user_lat      IS 'Latitude from IP geolocation';
COMMENT ON COLUMN daily_context.user_lng      IS 'Longitude from IP geolocation';
