-- Migration 002: Conversation state machine tracking

-- Conversation sessions (tracks FSM state for each call)
CREATE TABLE IF NOT EXISTS conversation_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP DEFAULT NOW(),

  run_id TEXT UNIQUE NOT NULL,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  -- FSM state tracking
  current_state TEXT NOT NULL DEFAULT 'greeting',
  previous_state TEXT,
  state_changed_at TIMESTAMP DEFAULT NOW(),

  -- Interaction counters
  barge_in_count INTEGER DEFAULT 0,
  silence_timeout_count INTEGER DEFAULT 0,
  stt_attempts INTEGER DEFAULT 0,
  stt_low_confidence_count INTEGER DEFAULT 0,

  -- Error tracking
  error_count INTEGER DEFAULT 0,
  error_recovery_attempts INTEGER DEFAULT 0,
  last_error TEXT,

  -- Call metadata
  started_at TIMESTAMP DEFAULT NOW(),
  ended_at TIMESTAMP,

  CONSTRAINT valid_state CHECK (current_state IN (
    'greeting', 'presenting_plan', 'asking_for_input', 'user_input',
    'llm_processing', 'tool_execution', 'response_generation',
    'speaking_response', 'confirming_plan', 'sending_summary',
    'call_end', 'error'
  ))
);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_user_id
  ON conversation_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_run_id
  ON conversation_sessions(run_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_current_state
  ON conversation_sessions(current_state);

-- State transition audit log (every transition is logged)
CREATE TABLE IF NOT EXISTS state_transitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP DEFAULT NOW(),

  run_id TEXT NOT NULL REFERENCES conversation_sessions(run_id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  trigger TEXT NOT NULL,
  latency_ms INTEGER,
  metadata JSONB DEFAULT '{}',

  CONSTRAINT valid_from_state CHECK (from_state IN (
    'greeting', 'presenting_plan', 'asking_for_input', 'user_input',
    'llm_processing', 'tool_execution', 'response_generation',
    'speaking_response', 'confirming_plan', 'sending_summary',
    'call_end', 'error'
  )),
  CONSTRAINT valid_to_state CHECK (to_state IN (
    'greeting', 'presenting_plan', 'asking_for_input', 'user_input',
    'llm_processing', 'tool_execution', 'response_generation',
    'speaking_response', 'confirming_plan', 'sending_summary',
    'call_end', 'error'
  ))
);

CREATE INDEX IF NOT EXISTS idx_state_transitions_run_id
  ON state_transitions(run_id);
CREATE INDEX IF NOT EXISTS idx_state_transitions_user_id
  ON state_transitions(user_id);
CREATE INDEX IF NOT EXISTS idx_state_transitions_trigger
  ON state_transitions(trigger);
CREATE INDEX IF NOT EXISTS idx_state_transitions_created_at
  ON state_transitions(created_at);

-- Error recovery log (tracks all error handling attempts)
CREATE TABLE IF NOT EXISTS error_recovery_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP DEFAULT NOW(),

  run_id TEXT NOT NULL REFERENCES conversation_sessions(run_id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  -- Error details
  error_type TEXT NOT NULL,
  error_message TEXT,

  -- Recovery details
  attempt INTEGER NOT NULL,
  recovery_strategy TEXT,
  result TEXT NOT NULL, -- 'success', 'partial', 'failed'

  -- Additional context
  from_state TEXT,
  to_state TEXT,
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_error_recovery_logs_run_id
  ON error_recovery_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_error_recovery_logs_user_id
  ON error_recovery_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_error_recovery_logs_error_type
  ON error_recovery_logs(error_type);
CREATE INDEX IF NOT EXISTS idx_error_recovery_logs_result
  ON error_recovery_logs(result);

-- Add state machine fields to user_preferences (for VAD tuning in Phase 2)
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS (
  vad_sensitivity FLOAT DEFAULT 0.5 CHECK (vad_sensitivity >= 0.1 AND vad_sensitivity <= 1.0),
  speech_start_threshold FLOAT DEFAULT 0.2 CHECK (speech_start_threshold >= 0.1 AND speech_start_threshold <= 1.0),
  speech_end_threshold FLOAT DEFAULT 0.8 CHECK (speech_end_threshold >= 0.1 AND speech_end_threshold <= 1.0),
  silence_timeout_ms INTEGER DEFAULT 2500,
  confirmation_timeout_ms INTEGER DEFAULT 5000
);

-- Enable RLS on new tables
ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE state_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_recovery_logs ENABLE ROW LEVEL SECURITY;

-- RLS policies (users can only see their own sessions)
CREATE POLICY "Users can view their own conversation sessions"
  ON conversation_sessions FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can view their own state transitions"
  ON state_transitions FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can view their own error recovery logs"
  ON error_recovery_logs FOR SELECT
  USING (auth.uid() = user_id);
