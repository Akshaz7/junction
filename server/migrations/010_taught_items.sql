-- One independently marked item per record. Existing find-all records stay legacy.
alter table taught_symbols add column if not exists canonical_kind text;
alter table taught_symbols add column if not exists manual_selection boolean not null default false;
drop index if exists taught_symbols_doc_name_page;
create index if not exists taught_symbols_doc_page on taught_symbols(doc_id, page);
