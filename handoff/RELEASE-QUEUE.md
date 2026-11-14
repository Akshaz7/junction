# RELEASE-QUEUE (integrator)
Updated Sat 14 Nov 2026 ~23:50 EET.

## Deployed
- 9d244d2 (backend + web prod + staging): awais/shared-edits, awais/compare-versions, final/mistakes, final/3d (partial) merged onto 60efc46. sample200 bench rel3-shared 156/200, zero row changes vs rel2-2206.
  Conflict decisions: engine/scene_cmds undo uses the edit-log path (F-3D) when state has `edits`, Awais last_hidden path otherwise; viewer keeps main recordCommand for isolation + Awais noteExternalHide for hides; server passes edits+hidden+last_hidden.

- 1aefe85 (backend; web unchanged): rebuilt scenes for 306 non-IFC docs (PG + baked demo_artifacts), P-21 infill verified on prod (22/24 infill nodes, screenshot of colorful-11397).
- f76bb92 batch 2 (building): awais/compare-versions X-34b, F-CHANGES (applied as patch on Awais), F-MEP, F-SCANSYM, F-PROJ-ENGINE (migration renumbered 007_projects), F-PROJ-UI. Bench rel4 156/200. Aiven build of f76bb92 failed on a transient registry push error; redeployed under a new rev.

## In progress
- Scene GLB rebuild (P-21 infill) of all 306 deployed non-IFC docs via scripts/rebuild_scenes.py; backups in /Users/akshatthapa/Workspace/scene-backup. Then load to PG (deploy/load_artifacts_pg.py --force) and refresh deploy/demo_artifacts.

## Queue
- final/changes (F-CHANGES) on top of awais/compare-versions when it has a RESULT
- other final/* branches as their handoff/F-*.md get RESULT blocks
- investigate 7 sample200 items wrong since e-s200-z3 (doors 11011/13843, toilets 2609/site303/site644, saunas 41/7041)

## Batch 2 deployed (Sat 14 Nov, late)
- Backend build_rev 6e0419f live (f76bb92 build failed on registry push; redeployed with new rev). /api/projects 200 (migration 007 applied).
- Web prod (hologram) and staging (hologram-staging-pi) redeployed from 6e0419f.
- Contents: shared edits, compare-versions, mistakes, 3D, MEP, projects engine+UI, changes screen, scansym.

## Batch 3 deployed (Sun 15 Nov 00:25)
- Backend 691c47a live: wallarea, order, props (finished work committed from worktrees), CONTRACT 3.4 + DECISIONS line. sample200 156/200, no correct->wrong (two guard fixes: props leaves area questions to solvers; order leaves plain length questions; wallarea no longer matches "sheet A-909").
- Web unchanged (no web files in this batch).
- Prod note: wall surface area on ifc_bench__ac20-arc answers "cannot be verified" because wallarea needs the original IFC body geometry, which the container does not hold. Needs the IFC (or its geometry cache) shipped to prod; lead to decide.
- Next: [perf + scales] -> [robust + mirror-shell/changes] -> [e2e + qa + qa2].
