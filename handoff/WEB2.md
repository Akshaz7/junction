# Handoff: WEB2 (Codex, second WEB-scoped worker)

Row ID: W-08 (attempt 1)  — Tier 1: Accuracy and cost dashboard
The main WEB worker is editing web/src/components/{chat-screen,document-viewer,answer-card,data-screen,workspace-navigation}.tsx, App.tsx and app.css right now (W-18). You MUST NOT edit any existing file. Create new files only:
- `web/src/components/accuracy-screen.tsx` (export `AccuracyScreen`), `web/src/components/accuracy-screen.css` (imported by the component; use the existing CSS variables from web/src/styles/app.css, Stoa look: quiet cards, tabular numbers), `web/src/lib/dashboard.ts` (fetch + shape helpers), `web/src/lib/dashboard.test.ts` (vitest), `web/e2e/dashboard.spec.ts`.
Data (real API, no mocks in e2e):
- `GET /api/bench` → list of runs [{tag, set, fake, mtime}] and `GET /api/bench/latest?tag=` → {file, data: {set, tag, fake, totals, cells}} (SERVER is adding the list + tag param now; until then /api/bench/latest without tag works and may 404 with {status:"no_bench"}). Field meanings: read engine/bench.py (cells = per source × question type: accuracy, answered_accuracy, scored, correct, cost_usd_per_answer, latency_ms_mean …; text answers are "unscored").
- `GET /api/costs` → {total_usd, calls, by_provider{p:{calls,usd}}, by_task{...}}.
Screen:
1. Header "Accuracy" + run picker (tags; marks `fake` runs as "test run, fake model" so nobody mistakes them for real numbers).
2. Totals row: accuracy, answered accuracy, questions scored, cost per answer ($, 6 dp when < $0.01), mean latency.
3. Table source × type with accuracy cells (no colour-only meaning: show the number), unscored shown as "not scored".
4. Before/after fine-tuning: if two runs share a set and one tag contains "baseline" and another "finetune"/"ft", show both columns side by side with the delta; otherwise a one-line "No fine-tuned run yet."
5. Costs card from /api/costs by provider.
6. "Model switcher": a read-only list of the routes (rules → Nemotron → Runware) for now, with a note "switching from the UI comes with S-09"; no fake buttons.
7. Empty states: no bench → "No bench run yet. Run `python -m engine.bench --set sample200 --tag <t>`." Numbers come only from the API: never hard-code.
e2e `dashboard.spec.ts`: open `#/accuracy` (LEAD wires the route to AccuracyScreen), fetch /api/bench/latest and /api/costs in the test via `request`, and assert the screen shows the same totals (accuracy %, cost per answer, total_usd). If the API returns no_bench, assert the empty state instead.
Done test (LEAD runs after wiring the route): `cd web && npx vitest run && npx playwright test e2e/dashboard.spec.ts` → pass.
In your RESULT line, give the exact ≤5-line route wiring for App.tsx (import + where AccuracyScreen renders for `#/accuracy`).
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

NEEDS: W-08: Five new dashboard files ready; all 110 Vitest tests pass (13 dashboard), tsc --noEmit passes, isolated AccuracyScreen Vite production build passes, Playwright discovers 2 real-API tests. Full done test awaits LEAD route wiring and browser execution; no existing source files edited, no commit. App.tsx wiring below: add import, insert AccuracyScreen beside ChangesScreen, replace the existing PlaceholderPage expression with the third line. Then run `cd web && npx vitest run && ../scripts/heavy.sh npx playwright test e2e/dashboard.spec.ts`.
```tsx
import { AccuracyScreen } from './components/accuracy-screen'
{view === 'accuracy' && <AccuracyScreen />}
{view !== 'data' && view !== 'chat' && view !== 'changes' && view !== 'accuracy' ? <PlaceholderPage route={view} /> : null}
```
