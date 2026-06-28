-- Users table
create table users (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  email text unique not null,
  phone_number text,
  full_name text,
  home_address text,
  work_address text,
  timezone text default 'America/New_York'
);

-- User preferences table
create table user_preferences (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  user_id uuid not null references users(id) on delete cascade,
  wake_up_time time default '06:00',
  workout_duration_minutes integer default 30,
  workout_preference text default 'morning', -- 'morning', 'evening', 'flexible'
  commute_buffer_minutes integer default 15,
  preferred_messaging_channel text default 'imessage', -- 'imessage', 'twilio'
  google_calendar_enabled boolean default true,
  apple_ical_enabled boolean default true,
  unique(user_id)
);

-- Daily plans table
create table daily_plans (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  run_id text unique not null,
  user_id uuid not null references users(id) on delete cascade,
  plan_date date default current_date,

  calendar_summary text,
  weather_summary text,
  commute_summary text,
  workout_recommendation text,
  leave_time timestamp with time zone,
  carry_items jsonb default '[]'::jsonb,
  extra_user_plans text,
  final_summary text,

  status text default 'pending', -- 'pending', 'in_progress', 'completed', 'failed'

  call_duration_seconds integer,
  transcript text
);

-- Calendar events table (normalized)
create table calendar_events (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  run_id text not null,
  user_id uuid not null references users(id) on delete cascade,

  source text not null, -- 'google_calendar', 'apple_ical'
  external_id text,
  title text not null,
  start_time timestamp with time zone not null,
  end_time timestamp with time zone not null,
  location text,
  description text,
  attendees jsonb default '[]'::jsonb,

  is_deduplicated boolean default false,
  deduplicated_from_id uuid
);

-- Calls table
create table calls (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  run_id text unique not null,
  user_id uuid not null references users(id) on delete cascade,

  vapi_call_id text,
  status text default 'pending', -- 'pending', 'initiated', 'in_progress', 'completed', 'failed'
  duration_seconds integer,
  transcript text,

  error_message text
);

-- Messages table
create table messages (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  run_id text not null,
  user_id uuid not null references users(id) on delete cascade,

  channel text not null, -- 'imessage', 'twilio', 'test'
  direction text not null, -- 'inbound', 'outbound'
  content text not null,
  status text default 'pending', -- 'pending', 'sent', 'delivered', 'failed'

  external_message_id text
);

-- Tool calls table
create table tool_calls (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  run_id text not null,
  user_id uuid not null references users(id) on delete cascade,

  agent_name text not null,
  tool_name text not null,
  input_payload jsonb,
  output_payload jsonb,
  error jsonb,

  latency_ms integer,
  status text default 'success' -- 'success', 'error', 'timeout'
);

-- Debug logs table
create table debug_logs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  run_id text not null,
  user_id uuid,

  agent_name text,
  level text not null, -- 'debug', 'info', 'warning', 'error', 'critical'
  event_type text not null,
  message text not null,

  input_payload jsonb,
  output_payload jsonb,
  error text,

  latency_ms integer
);

-- Evaluation scores table
create table evaluation_scores (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  run_id text not null,
  user_id uuid not null references users(id) on delete cascade,

  usefulness_score decimal(3, 2),
  correctness_score decimal(3, 2),
  hallucination_detected boolean,
  hallucination_details text,

  overall_score decimal(3, 2),
  debug_summary jsonb,

  feedback text
);

-- Memory items table (for Cognee integration later)
create table memory_items (
  id uuid primary key default gen_random_uuid(),
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  user_id uuid not null references users(id) on delete cascade,

  memory_type text not null, -- 'preference', 'pattern', 'fact', 'schedule'
  content text not null,
  embedding vector(1536),

  related_run_ids text[] default array[]::text[],
  relevance_score decimal(3, 2),

  archived_at timestamp with time zone
);

-- Create indexes for common queries
create index idx_daily_plans_user_date on daily_plans(user_id, plan_date desc);
create index idx_daily_plans_run_id on daily_plans(run_id);
create index idx_calendar_events_run_id on calendar_events(run_id);
create index idx_calendar_events_user on calendar_events(user_id, start_time);
create index idx_tool_calls_run_id on tool_calls(run_id);
create index idx_tool_calls_agent on tool_calls(agent_name);
create index idx_debug_logs_run_id on debug_logs(run_id);
create index idx_debug_logs_level on debug_logs(level);
create index idx_messages_run_id on messages(run_id);
create index idx_calls_run_id on calls(run_id);

-- Enable RLS (Row Level Security) for multi-tenant safety
alter table users enable row level security;
alter table user_preferences enable row level security;
alter table daily_plans enable row level security;
alter table calendar_events enable row level security;
alter table calls enable row level security;
alter table messages enable row level security;
alter table tool_calls enable row level security;
alter table debug_logs enable row level security;
alter table evaluation_scores enable row level security;
alter table memory_items enable row level security;

-- Basic RLS policies (service role can bypass, users can only see their own)
create policy "Users can view own data" on users for select using (auth.uid() = id);
create policy "Users can view own preferences" on user_preferences for select using (auth.uid() = user_id);
create policy "Users can view own plans" on daily_plans for select using (auth.uid() = user_id);
create policy "Users can view own events" on calendar_events for select using (auth.uid() = user_id);
create policy "Users can view own calls" on calls for select using (auth.uid() = user_id);
create policy "Users can view own messages" on messages for select using (auth.uid() = user_id);
create policy "Users can view own tool calls" on tool_calls for select using (auth.uid() = user_id);
create policy "Users can view own debug logs" on debug_logs for select using (auth.uid() = user_id);
create policy "Users can view own scores" on evaluation_scores for select using (auth.uid() = user_id);
create policy "Users can view own memory" on memory_items for select using (auth.uid() = user_id);
