-- The changes engine writes rows from outside the API process: notify from the database.
create or replace function notify_changes_new() returns trigger as $$
begin
  perform pg_notify(case when current_schema() = 'public' then 'hologram_events' else 'hologram_events_' || current_schema() end, json_build_object('type', 'changes.new', 'id', new.id)::text);
  return new;
end;
$$ language plpgsql;

drop trigger if exists changes_notify on changes;
create trigger changes_notify after insert on changes
  for each row execute function notify_changes_new();
