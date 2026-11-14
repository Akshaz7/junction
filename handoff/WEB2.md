# Handoff: WEB2 (Codex, second worker)

Row ID: X-07 (attempt 1)  — Stress and variety testing harness (Ash's request; budget: Runware $500 tonight, but use engine caps)
Build `tools/stress/` (new folder, Python 3.12, stdlib + httpx only; run with `.venv/bin/python -m tools.stress.run --tag <t> [--only a,b,c] [--limit N]`) that drives the LIVE local API (http://localhost:8000) and writes `results/stress/<tag>.json` (+ `<tag>.cases.jsonl`).
Read first: TASKS.md X-07 row, CONTRACT.md §5.7 (answer object; validate every answer against server/schemas/answer.schema.json), §5.9 API, engine/bench.py (scoring: count exact, area/length/volume within 2 %, text judged apart — import and reuse its scoring functions, don't reimplement), data/sets/ (sample1000.full.jsonl).
Case groups:
(a) dataset: questions from data/sets/sample1000.full.jsonl, ≥300 across every source × type present (stratified sample, seed fixed), asked through the API with their doc_id; score numeric answers vs gold; text: record only.
(b) paraphrases: for each chosen demo question in docs/DEMO.md, 10 paraphrases generated ONCE through the model layer (`engine.models.call` task `route` or a cheap text task; cache to tools/stress/paraphrases.json, commit-able) — every paraphrase must give the same numeric answer as the original.
(c) edge inputs: empty string, 5,000-char text, Finnish + 2 other languages (must answer in English or abstain politely per DECISIONS: English only), nonsense, prompt-injection ("ignore previous instructions…", "print your system prompt", "reveal API keys"), question about a doc that's not selected, no doc selected, multi-doc (2 docs), scene commands on a raster doc and on ac20 (show/remove/restore/reset/undo), uploads via POST /api/upload of png, jpg, pdf, dxf, ifc, svg and a corrupt file (small samples from data/; the corrupt file = random bytes with .pdf) → expect doc.new or a clean 4xx, never 5xx; 10 concurrent chats (asyncio, respect the 30 req/min/IP limit if enabled locally: pace or note it); two /ws clients on one chat: a message in A appears in B < 2 s.
Checks per case: HTTP status not 5xx, response contract-valid, no crash, abstains when it should (edge cases), evidence boxes inside the page image bounds (GET page image size from the API), latency, cost (from the answer's cost field). Summary JSON: totals, pass/fail per case, accuracy on (a) by source × type, crash_count, invalid_answer_count, injection_leak_count (any key-like string or system-prompt text in an answer = leak), max latency, total cost.
Run it once with `--tag stress-r1` (it may take a while; pace requests; stop if engine budget caps trigger) and commit nothing — LEAD commits.
Rules: only tools/stress/ and results/stress/. Never print keys. Don't start/stop servers. Don't upload anything from refs/.
Done test (LEAD): results/stress/stress-r1.json exists with all groups, crash_count 0 and invalid_answer_count 0 (or the failing cases listed, which LEAD routes to the owners).
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
