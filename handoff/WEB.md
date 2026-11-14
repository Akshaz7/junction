# Handoff: WEB (Codex worker)

Row ID: W-01 (attempt 1)
Task: Scaffold `web/` with Vite + React + TypeScript + Tailwind v4 + lucide-react. Use the design tokens from `refs/stoa-hero/theme-tokens.css` (copy the CSS variables into `web/src/styles/tokens.css`; the variables are design values, not code). Read `refs/stoa-hero/01-design-tokens-and-shell.md` and `refs/stoa-hero/03-build-guide.md` for the type scale and components. Until the backend endpoints exist (row S-03), add a tiny local mock in `web/src/mock/` that serves contract-shaped example data for `GET /api/docs` and a `POST /api/chats/{id}/messages` answer (CONTRACT.md 5.7 and 5.9). Add `npm` scripts: `dev`, `build`, `test` (vitest), `test:e2e` (Playwright, headless). Put the Vite dev proxy `/api` and `/ws` -> `http://localhost:8000`. Leave an empty folder `web/src/viewer3d/` with a `README.md` saying it belongs to the 3D worker.
Rules: use our own wordmark "Hologram", never Stoa's logo. Never copy code from `refs/stoa-hero/source/`. Node is v26. Only edit `web/` (not `web/src/viewer3d/` beyond that README).
Input files: refs/stoa-hero/theme-tokens.css, refs/stoa-hero/01-design-tokens-and-shell.md, refs/stoa-hero/03-build-guide.md, CONTRACT.md
Contract sections to read: 5.7, 5.8, 5.9
Done test command: `cd web && npm ci && npm run build && (timeout 40 npm run dev -- --port 5173 --strictPort > /tmp/w01dev.log 2>&1 &) ; sleep 8; curl -sf http://localhost:5173/ | grep -q '<div id="root"'`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

RESULT: W-01 scaffold complete; supplied done test passed on local run 2 after adding three/@types/three for concurrent T-00 files; npm test passed all 9 tests; GET docs and POST SSE mocks checked; Playwright configured but browser verification incomplete (local Chrome launch aborted SIGABRT/EPERM); no commits.
