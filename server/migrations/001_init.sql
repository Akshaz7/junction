create table if not exists documents (
  doc_id text primary key,
  source text not null,
  title text not null,
  kind text not null,
  formats text[] not null default '{}',
  pages int not null default 1,
  licence text,
  credit text,
  heldout boolean not null default false,
  files jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists documents_source_idx on documents (source);

create table if not exists chats (
  id uuid primary key default gen_random_uuid(),
  doc_id text references documents(doc_id),
  title text,
  created_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  role text not null check (role in ('user','assistant','system')),
  content text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists messages_chat_idx on messages (chat_id, created_at);

create table if not exists answers (
  id uuid primary key default gen_random_uuid(),
  message_id uuid references messages(id) on delete cascade,
  chat_id uuid references chats(id) on delete cascade,
  doc_id text,
  answer jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists changes (
  id uuid primary key default gen_random_uuid(),
  doc_a text,
  doc_b text,
  summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists model_calls (
  id bigserial primary key,
  provider text not null,
  model text,
  purpose text,
  tokens_in int not null default 0,
  tokens_out int not null default 0,
  cost_usd numeric(12,6) not null default 0,
  latency_ms int,
  created_at timestamptz not null default now()
);

create table if not exists bench_runs (
  id uuid primary key default gen_random_uuid(),
  label text,
  results jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists rules (
  id text primary key,
  title text not null,
  body jsonb not null default '{}'::jsonb,
  source text,
  created_at timestamptz not null default now()
);

create table if not exists findings (
  id uuid primary key default gen_random_uuid(),
  doc_id text references documents(doc_id),
  rule_id text references rules(id),
  item_ids text[] not null default '{}',
  severity text,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
