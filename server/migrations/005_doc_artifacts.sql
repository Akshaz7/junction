-- Durable copy of uploaded documents and everything derived from them (the Runtime container disk is ephemeral).
-- name is relative to artifacts/<doc_id>/ ; the original upload is stored as '__original__/<file name>'.
create table if not exists doc_artifacts (
  doc_id text not null,
  name text not null,
  content_type text,
  data bytea not null,
  size integer not null,
  created_at timestamptz not null default now(),
  primary key (doc_id, name)
);
