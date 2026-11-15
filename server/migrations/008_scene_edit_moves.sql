-- Shared edit layer: Edit-panel moves and wall materials join the chat's scene edits (detail holds offset_m / material).
alter table scene_edits drop constraint if exists scene_edits_op_check;
alter table scene_edits add constraint scene_edits_op_check
  check (op in ('highlight','hide','restore','reset','isolate','move','material'));
alter table scene_edits add column if not exists detail jsonb not null default '{}'::jsonb;
