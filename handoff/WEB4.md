# WEB4 handoff
ROW: W-52 judge demo use case as one Playwright spec (web/e2e/demo-usecase.spec.ts)
Story ("fire-safety walk-through before a renovation meeting", AC20 = ifc_bench__ac20-arc), one chat, real local API (make dev, fake model provider; these steps are code-answered):
1 Data -> search "AC20" -> open it -> Ask.
2 "How many doors and windows are on the ground floor?" -> answer has both counts, numbered boxes, kind legend (two colours).
3 Click citation chip 1 -> drawing opens with boxes.
4 "And on the first floor?" -> open drawing updates in place (no image reload: same <img> element), counts change.
5 "Where are the toilets?" -> boxes present.
6 Visualise it -> 3D ready; build-up slider exists and steps.
7 "Remove the front door. Is it still compliant?" -> answer-advisor-cards visible with text containing "33".
8 "Reset the model" -> hidden list empty.
9 Clicking every visible button in the answer card leads somewhere (no dead end).
Use stable data-testid selectors already in the code (grep web/src for data-testid); add a data-testid only where missing, in the component files of that step. Screenshots to results/qa/shots/w52-<step>.png.
Done test: cd web && npx tsc --noEmit && npx playwright test e2e/demo-usecase.spec.ts --list  (lists the test). Do NOT run the full Playwright suite (machine swap is high); LEAD runs it via scripts/heavy.sh.
Write RESULT: one line at the end. Never commit.
RESULT: W-52 done test passed: npx tsc --noEmit and scripts/heavy.sh npx playwright test e2e/demo-usecase.spec.ts --list (1 test); files: web/e2e/demo-usecase.spec.ts, web/src/components/answer-card.tsx (answer-card testid); all nine AC20 steps use the real API in one chat, with w52-01 through w52-09 screenshots configured under results/qa/shots; browser execution and actual screenshots remain for LEAD, no commit.
