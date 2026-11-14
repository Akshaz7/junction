# Handoff: WEB (Codex worker)

Row ID: W-19 (attempt 2) — remote scene edits must apply < 2 s
Full suite 07:00: 85/86 pass; the only failure is e2e/scene-commands.spec.ts:57 "The remote edit must arrive within two seconds" — measured 4506 ms (earlier 2049, 2415, 2635 ms). LEAD measured the server directly (tools/stress/ws_latency_probe.py): a second /ws client receives `scene.edit` 0.605 s after "remove W3" is sent. So ~4 s is spent in the web client between receiving scene.edit and the test seeing W3 hidden (2D overlay + `__viewer3d.state()`). Find it: likely waiting for the SSE answer to enrich tags, a scene-state refetch, a debounce, or the 3D fade (state must flip at once; the visual fade can follow). Apply remote scene.edit immediately on receipt in both 2D and 3D, labels/tags enriched later without blocking. Add timing marks (performance.mark) around receive → applied and assert < 500 ms in a unit/e2e check.
Only web/ except web/src/viewer3d/ (if the delay is inside viewer3d, write the exact change in NEEDS) and web/src/main.tsx; WEB2 is editing web/src/components/document-viewer.tsx, item-panel.tsx and lib/linked.ts — don't touch those.
Done test (LEAD): full web suite → pass (scene-commands.spec.ts:57 < 2 s).
Last failed attempt (if any): see above.

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

NEEDS: W-19 attempt 2 — LEAD must run the full web suite outside the sandbox (Chromium bootstrap_check_in is denied here); npm run build and npm test pass (37 files, 201 tests). WEB now flushes socket edits synchronously into shared 2D/model state and silently deduplicates model snapshots instead of replaying/publishing all historical commands; performance marks and e2e assert receipt→applied <500 ms while retaining the <2 s end-to-end assertion. Exact scope: web/src/components/chat-screen.tsx, web/src/components/drawing-model.tsx, web/src/lib/use-scene-edits.ts, web/src/lib/scene-edit-context.ts, web/src/lib/scene-edit-timing.ts, web/src/lib/scene-snapshot.ts, web/src/lib/scene-snapshot.test.ts, web/e2e/scene-commands.spec.ts. No viewer3d/ or WEB2 files edited; done status awaits browser validation.
