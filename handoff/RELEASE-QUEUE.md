# RELEASE-QUEUE (integrator)
Updated Sat 14 Nov 2026 ~23:50 EET.

## Deployed
- 9d244d2 (backend + web prod + staging): awais/shared-edits, awais/compare-versions, final/mistakes, final/3d (partial) merged onto 60efc46. sample200 bench rel3-shared 156/200, zero row changes vs rel2-2206.
  Conflict decisions: engine/scene_cmds undo uses the edit-log path (F-3D) when state has `edits`, Awais last_hidden path otherwise; viewer keeps main recordCommand for isolation + Awais noteExternalHide for hides; server passes edits+hidden+last_hidden.

## In progress
- Scene GLB rebuild (P-21 infill) of all 306 deployed non-IFC docs via scripts/rebuild_scenes.py; backups in /Users/akshatthapa/Workspace/scene-backup. Then load to PG (deploy/load_artifacts_pg.py --force) and refresh deploy/demo_artifacts.

## Queue
- final/changes (F-CHANGES) on top of awais/compare-versions when it has a RESULT
- other final/* branches as their handoff/F-*.md get RESULT blocks
- investigate 7 sample200 items wrong since e-s200-z3 (doors 11011/13843, toilets 2609/site303/site644, saunas 41/7041)
