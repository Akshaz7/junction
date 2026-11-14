-- F-PROJ-ENGINE: projects = saved workspaces of many documents of one building site.
create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now(),
  demo boolean not null default false
);
-- No foreign key on doc_id: uploads and library documents live in `documents`, but a project must survive a document being re-ingested.
create table if not exists project_docs (
  project_id uuid not null references projects(id) on delete cascade,
  doc_id text not null,
  role text not null default 'other' check (role in ('model','plan','section','elevation','detail','schedule','scan','photo','spec','revision','other')),
  level text,
  role_source text not null default 'auto' check (role_source in ('auto','user')),
  added_at timestamptz not null default now(),
  primary key (project_id, doc_id)
);
create index if not exists project_docs_doc_idx on project_docs (doc_id);
alter table chats add column if not exists project_id uuid references projects(id) on delete set null;
create unique index if not exists projects_demo_name_idx on projects (name) where demo;
