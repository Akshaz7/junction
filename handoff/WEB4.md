# WEB4: row W-24 (Codex). Accuracy page, judge-grade
Scope: web/src/components/accuracy-screen.tsx and accuracy-screen.css only.
The page must show REAL numbers only, from /api/bench (list) and /api/bench/latest?tag=<tag>; see server/ and docs/API.md. Never hard-code numbers.
Show:
- headline accuracy
- 0 abstentions
- $/answer
- per-source and per-question-type tables (n, correct, accuracy, answered accuracy, $/answer, p95 latency)
- the text-judge section
- the before/after comparison between two tags (a selector for tag A vs tag B)
- a short "how we measure" note: held-out drawings are never used for training or tuning, the 2% tolerance, and how text answers are judged
Stoa-like look, consistent with the app (tokens.css). It must work on a phone.
Done test: `cd web && npx tsc --noEmit && npx vitest run` pass, plus a vitest unit test of the table derivation. The LEAD runs Playwright.
Do not commit. Append a RESULT: line.

W-24: API-backed source/type marginal tables (including p95), numeric abstentions without a forced zero, separate text-judge results/costs, selectable tag A/B comparison with set/mode/completion checks, measurement note and responsive table scrolling. Only the two scoped component files were edited.
Unit tests are in-source to honor the two-file scope. From web/: `node --input-type=module -e 'import {writeFileSync} from "node:fs"; writeFileSync("/private/tmp/web4-vitest.config.mjs", "export default " + JSON.stringify({root:process.cwd(),test:{include:[],includeSource:["src/components/accuracy-screen.tsx"],environment:"node"}}))'` then `npx vitest run --config /private/tmp/web4-vitest.config.mjs` (2 tests pass).
NEEDS: Shared-working-tree done test is blocked outside WEB4 scope: viewer3d/rise.ts no longer exports createRiseAnimation/RISE_DURATION_MS/riseState/scheduleRiseTransitions expected by viewer/tests; linked.test.ts expects an evidence object without the new kind field (5 Vitest failures total). Owners/LEAD must reconcile these; LEAD runs Playwright.
RESULT: W-24 scoped local HEAD snapshot (/private/tmp/web4-validation; HEAD web plus only accuracy-screen.tsx/css) passes `cd web && npx tsc --noEmit && npx vitest run` (38 files, 210 tests), plus 2 in-source table-derivation tests and production vite build; production assets exclude test code. Shared-working-tree blockers are recorded above. No commit.
