# WEB3: row W-22 (Codex). Data + Changes + chat starters (Stoa parity)
Scope: web/src/components/data-screen.tsx, changes screens, overview/home starter cards, and the upload flow. Do not touch document-viewer.* or viewer3d/; other workers own those.
Everything must be LIVE against the real API (/api/folders, /api/docs, /api/changes, uploads). No mocks.
1. Data: a folder tree from /api/folders, with size, date and version count per file, and a versions dropdown that opens older versions.
2. Changes: group by date (Today / Yesterday / earlier dates), with a filter by type and by folder.
3. Upload: after upload, poll the ingest status until ready, show progress, then open the doc. Hide "Show on table" for docs that have no scene.
4. Home: Stoa-style starter cards (Draft claim, Meeting prep, Plan work phase, Review contract) that start a real chat with a construction prompt.
Done test:
- Playwright specs in web/e2e/data-changes.spec.ts via `scripts/heavy.sh scripts/test_snapshot.sh 4189 "web" -- e2e/data-changes.spec.ts`. Use port 4189 only.
- tsc and vitest pass.
Do not commit. Append a RESULT: line.

NOTE: The concurrent WEB2 annotation TypeScript error was resolved by its owner during this row.

IMPLEMENTED: W-22 live API folder tree, file size/date/version metadata and older-version selection; dated Changes with type/folder/search filters; ingestion progress and automatic document opening; four construction starter cards create and persist real chats. Scope: web/src/components/{data-screen,changes-screen,overview-screen}.{tsx,css}, web/e2e/data-changes.spec.ts only.
VALIDATION: tsc --noEmit passed; Vitest 39 files / 213 tests passed; temporary snapshot production build passed. Added 7 API-backed Playwright tests with no API mocks.
blocked: Required scripts/heavy.sh scripts/test_snapshot.sh 4189 "web" -- e2e/data-changes.spec.ts cannot create .git/worktrees (Operation not permitted); fallback copied snapshot on 4189 builds but Chromium aborts at launch with SIGABRT / EPERM before any test body runs.
NEEDS: LEAD run the exact Playwright done command outside the sandbox, then append RESULT: only on success. Existing data.spec.ts source-folder and overview.spec.ts starter-link assertions describe the superseded UI and need corresponding updates outside this row's named test scope.
