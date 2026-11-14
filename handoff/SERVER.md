# SERVER (Codex): row S-14. Live smoke test of the whole API (judging readiness)
Scope: scripts/smoke_live.py (new) and results/qa/ (outputs only).
Write scripts/smoke_live.py <base_url> (default https://hologram-khaki.vercel.app) that hits EVERY endpoint in server/ (read the routers: docs, files, folders, chats + messages SSE, changes + refresh, compare, skills + run, automations + run + report (+ pdf if present), findings run/list, advise, linked items/tags, bench, tts, speech, health, /ws connect + ping).
For each endpoint: status, latency, and a basic shape check against docs/API.md.
- Pace requests to stay under the rate limit (write calls ≤ 25/min).
- Create test chats and automations with the title prefix "smoke-", and delete what it created where an API exists.
- Write results/qa/smoke-<HHMM>.json and a short .md table. Exit non-zero on any failure.
- Never print keys; it needs none.
Done test: `python3 scripts/smoke_live.py --dry-run` lists every endpoint it will call. A real run against http://localhost:8000 passes if a local server is up; otherwise say so.
Do not commit. Append a RESULT: line.
