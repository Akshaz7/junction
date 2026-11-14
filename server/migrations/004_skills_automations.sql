-- S-09: saved prompts (skills) and scheduled prompts (automations).
create table if not exists skills (
  id uuid primary key default gen_random_uuid(),
  slug text unique,
  name text not null,
  description text not null default '',
  prompt text not null,
  builtin boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists automations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  prompt text not null,
  doc_ids text[] not null default '{}',
  interval_minutes integer not null default 1440 check (interval_minutes >= 1),
  enabled boolean not null default true,
  last_run_at timestamptz,
  last_report jsonb,
  created_at timestamptz not null default now()
);
