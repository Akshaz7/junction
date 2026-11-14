# WEB4 (Codex) — current row

ROW: W-32 live-QA polish (results/qa/live-1439.md items 9 and 10)
1. Never show "size unavailable" / "version unavailable" / similar placeholder labels: omit the field when missing.
2. Accuracy page: if /api/bench/latest fails, fall back to the bundled public results file (web/public/ or the API's static results; check what exists) and show the latest recorded run (e-s200-z1: 143/187, 76.47%, 0 abstentions); never "No bench runs" when results exist. Number must come from a results file, not hard-coded text.
3. Rate limit (HTTP 429) anywhere in the API client: friendly message "Too many requests, retrying in Ns" with automatic retry (respect Retry-After, max 2 retries), never raw "rate limit exceeded".
4. Transient 502/503 during a backend restart: API client retries GETs twice with 1 s backoff; the live socket reconnects with backoff and shows a small "Reconnecting…" pill, which clears on reconnect.
Allowed files: web/src/lib/api.ts, web/src/lib/live*.ts, web/src/components/accuracy-screen.*, overview-screen.*, changes-screen.*, data-screen.*, a new web/src/components/connection-pill.* , their tests, this file.
Done test: cd web && npx tsc --noEmit && npx vitest run (0 failures) + one test per item.
Never commit. Write one line at the end: RESULT: ...

RESULT: W-32 passed: missing metadata omitted; accuracy-screen.results.json bundles the unchanged results/bench/e-s200-z1.json (143/187, 76.47%, 0 abstentions); WorkspaceApi plus Accuracy/Overview transports retry 429 twice with Retry-After countdown and GET 502/503 twice at 1 s; shared live socket backoff drives a cross-route Reconnecting… pill. Done test: cd web && npx tsc --noEmit && npx vitest run — 54 files, 309 tests passed. Learning: retry mocks must return fresh Response bodies. No commit.
