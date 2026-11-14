-- S-10: per-chat scene edit layer (hide/restore/highlight/isolate/reset). Source data is never changed.
create table if not exists scene_edits (
  id bigserial primary key,
  edit_id text not null unique,
  chat_id uuid not null references chats(id) on delete cascade,
  doc_id text not null,
  op text not null check (op in ('highlight','hide','restore','reset','isolate')),
  item_ids jsonb not null default '[]'::jsonb,
  labels jsonb not null default '{}'::jsonb,
  ts timestamptz not null default now()
);
create index if not exists scene_edits_chat_idx on scene_edits (chat_id, id);
