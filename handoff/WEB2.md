# Handoff: WEB2 (Codex, second WEB-scoped worker)

Row ID: W-15 (attempt 1)  — Overview screen
WEB is editing existing web files (W-18). New files only: `web/src/components/overview-screen.tsx` (+ `.css`), `web/src/lib/overview.ts` (+ `overview.test.ts`), `web/e2e/overview.spec.ts`. Never edit existing files; the LEAD wires `#/overview` (the Overview nav item already exists).
Stoa look: the reference home is quiet: a greeting/heading, then cards. Read refs/stoa-hero/02-phase-map.md + 01-design-tokens-and-shell.md for tokens; reuse CSS variables from web/src/styles/app.css. Copy style per CONTRACT §5.8 (short, plain).
Sections (each from the real API, see CONTRACT §5.9 and server/*_routes.py for exact shapes; each has its own empty state and never invents numbers):
1. "This week's changes": GET /api/changes (latest 5: title, doc, when) → click opens `#/changes`.
2. "Open findings": GET /api/findings (count by severity + top 3) — if the endpoint 404s or is empty, show "No findings yet." (E-15 not built yet).
3. "Latest answers": GET /api/chats (latest 5 chats with their last question + answer one-liner + cost) → click opens that chat (`#/chat?chat=<id>` or whatever the existing chat route supports; read chat-screen.tsx to match, don't edit it).
4. "Accuracy": GET /api/bench/latest → totals (accuracy %, cost per answer) with "test run, fake model" label when `fake` is true; 404 → "No bench run yet." Link to `#/accuracy`.
5. Starter buttons that open chat with the 4 starter questions used on the chat start screen (read them from chat-screen.tsx; import if exported, else duplicate the 4 strings in overview.ts with a comment).
e2e `overview.spec.ts` (real API, no mocks): open `#/overview`; for each section fetch the same endpoint via `request` and assert the screen matches (counts/titles) or shows the empty state.
In RESULT give the exact ≤4-line App.tsx wiring.
Done test (LEAD runs after wiring): `cd web && npx vitest run && npx playwright test e2e/overview.spec.ts` → pass.
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
