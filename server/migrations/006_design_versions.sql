-- Saved design versions: 3D edits of a document kept as a new version, linked to the version they were based on.
-- n = 1, 2, ... per document (0 = the original, never stored or overwritten). edits = full snapshot over the original:
-- {"removed": [item_id], "moved": {item_id: [dx_m, dz_m]}, "materials": {item_id: name}} (engine/design_versions.py).
create table if not exists design_versions (
  doc_id text not null,
  n integer not null check (n > 0),
  parent integer not null default 0,
  label text not null,
  edits jsonb not null,
  chat_id text,
  created_at timestamptz not null default now(),
  primary key (doc_id, n)
);
