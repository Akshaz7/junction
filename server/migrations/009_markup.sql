create table if not exists taught_symbols (
    id uuid primary key default gen_random_uuid(),
    doc_id text not null,
    project_id text,
    name text not null,
    note text not null default '',
    template_bbox jsonb not null,
    page integer not null check (page > 0),
    matches jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);
create unique index if not exists taught_symbols_doc_name_page on taught_symbols(doc_id, lower(name), page);
create index if not exists taught_symbols_project on taught_symbols(project_id);
create table if not exists markup_pins (
    id uuid primary key default gen_random_uuid(),
    doc_id text not null,
    page integer not null check (page > 0),
    x double precision not null,
    y double precision not null,
    note text not null,
    created_at timestamptz not null default now()
);
create index if not exists markup_pins_doc on markup_pins(doc_id, created_at);
