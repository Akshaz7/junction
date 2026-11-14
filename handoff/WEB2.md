# WEB2: row W-21 (Codex). Viewer tools + spec panel (Stoa parity)
Scope: web/src/components/document-viewer.tsx, document-viewer.css, and new files under web/src/components/viewer-tools/ only. Other workers are editing other web screens at the same time.
Everything must be LIVE against the real API. No mocks. refs/stoa-hero is a visual reference only; never copy its source.
Make every button in the viewer toolbar work:
- search: find text on the sheet (use /api/docs/{id} text or planmap labels) and highlight hits with numbered yellow boxes
- highlight/marker
- pen annotations on top of the page, kept per doc in localStorage
- download: original source via /api/docs/{id}/source
- zoom: keep it working
When an answer cites a text passage (spec/notes), show a side spec panel with the passage highlighted in yellow, like Stoa.
Done test:
- Playwright specs in web/e2e/viewer-tools.spec.ts, run with `scripts/heavy.sh scripts/test_snapshot.sh 4187 "web" -- e2e/viewer-tools.spec.ts`. Use port 4187 only.
- `cd web && npx tsc --noEmit && npx vitest run` must pass.
Do not commit. When done, append one line starting with RESULT: plus the test numbers.
NEEDS: LEAD run `scripts/heavy.sh scripts/test_snapshot.sh 4187 "web" -- e2e/viewer-tools.spec.ts` outside the sandbox: prescribed harness cannot create `.git/worktrees/junction-snap-4187` (Operation not permitted); a temporary copy on 4187 built successfully but all 5 browser tests stopped at Chromium launch (SIGABRT/EPERM), before assertions. W-21 implementation is in the two scoped viewer files, four new viewer-tools files and the requested e2e spec; TypeScript passes, Vitest 39 files / 213 tests pass, production build passes. Browser verification blocked; no passing RESULT claimed.
