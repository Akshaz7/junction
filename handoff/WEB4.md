# WEB4 (Codex) — current row

ROW: W-42 e2e specs follow the real Changes feed
1. web/e2e/changes.spec.ts asserts comparison.generated_for_demo === false; S-25 omits the field. Assert it is absent, and assert the feed's first entry ids are real dataset ids (no "swiss_dwellings__…-v2" synthetic pairs, no generated_for_demo).
2. Grep web/e2e for other references to generated/synthetic changes and update them to the real feed shape.
3. Any web/src text that still says "generated for demo" for Changes: remove it if the data is now real (keep the label anywhere content really is generated).
Allowed: web/e2e/*.spec.ts, web/src/components/changes-screen.*, compare-screen.*, this file.
Done test: cd web && npx tsc --noEmit && npx vitest run (0 failures) and `npx playwright test e2e/changes.spec.ts --list` succeeds.
Never commit. Write one line at the end: RESULT: ...
RESULT: W-42 passed: changes.spec.ts asserts omitted demo fields and validates all feed document IDs (including first entries) against /api/docs, rejecting synthetic Swiss revision IDs; overview.spec.ts expects the real feed shape. Kept conditional Changes/Compare demo labels because generated offline/fidelity fixtures still use them. Done test: tsc passed, Vitest 60 files/375 tests passed, heavy.sh Playwright changes.spec.ts --list passed (1 test); no browser run, no commit.
