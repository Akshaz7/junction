# Handoff: WEB (Codex worker)

Row ID: W-07 (attempt 1)
Task: Data screen: folders by source (GET /api/docs returns `{total, sources:[{source,count,docs}]}`; the DB has the 773 preview docs, possibly more later), file list per folder with format badges (pdf, dxf, dwg, ifc, png, jpg, svg; from `formats`), thumbnails (`/api/docs/{doc_id}/files/page-1.thumb.png` when present; file-type icon otherwise), title, pages, licence + credit line, search across all docs, and "Ask about it" (opens Chat with the doc preselected as an @ chip) and "Visualise it" (opens the 3D panel via `VisualiseItButton` from web/src/viewer3d/VisualiseIt.tsx when a scene exists; read-only import).
Upload: a drop zone + button → `POST /api/upload` (multipart; docs/API.md), shows ingest progress by polling `GET /api/docs/{doc_id}/ingest` until ready/partial/failed, then the new doc appears in its folder (also listen for `doc.new` if you already have a /ws client; polling is fine).
Large lists: virtualise or paginate (a folder can hold thousands of docs once the full set is seeded).
Tests: e2e `e2e/data.spec.ts`: opens the cubicasa5k folder, opens a file (detail panel with credit), uploads `tests/assets/upload-fixture.png` (copy a small PNG from data/junction-dataset-preview/data/cubicasa5k/ into web/e2e/assets/ — < 500 KB) and sees a new doc appear (ingest can take ~10 s; allow 60 s).
Rules: only web/ except web/src/viewer3d/ and web/src/main.tsx. Shared dev servers are running; don't start your own. Playwright can't run in your sandbox; type-check it; the LEAD runs it.
Done test (LEAD runs): `cd web && npm run build && npx vitest run && npx playwright test e2e/data.spec.ts`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

RESULT: W-07 implemented source folders, 40-document pagination, global search, thumbnails/fallback icons, credited detail panel, Chat preselection, existing-scene VisualiseItButton, multipart upload and cancellable ingest polling with retry; npm run build and npx vitest run pass (57 tests); e2e/data.spec.ts is type-checked with a 44,754-byte credited PNG fixture, browser execution remains for LEAD per sandbox instructions.
