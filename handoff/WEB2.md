# Handoff: WEB2 (Codex, second worker)

Row ID: X-03 (attempt 1)  — docs/DEMO.md: demo script chosen by test results
Read docs/MASTER_PROMPT.md section 12 (demo script: 8 steps) and MORNING.md section 1.
Pick the exact documents and questions that WORK, by testing them against the running local API (http://localhost:8000; you have network to localhost):
1. For each demo step, list 3–6 candidate (doc_id, question) pairs from data/junction-dataset-preview/questions.jsonl (English only) and the demo docs (ifc_bench__ac20-arc is the demo building; generated-for-demo docs are allowed for chat flow steps but must be labelled). Ask each via `POST /api/chats` then `POST /api/chats/{id}/messages {"content": q, "doc_ids": [doc_id]}` (SSE/JSON; read server/chats_routes.py), max 40 questions total, sequentially (rate limit 30/min: sleep 2 s between).
2. Compare to the dataset's gold answer where one exists; record per candidate: answer text, correct?, evidence item count, latency_ms, cost. Write `results/demo_candidates.json`.
3. Write `docs/DEMO.md`: the 8-step script with the chosen question per step (the most reliable correct one, fast, with clear evidence boxes), exact clicks (Data → doc → Ask; chip → drawing; Visualise it; Show on table; "show me all the windows" → "remove W3" once E-20 lands — mark as pending if the API doesn't support it yet), backup question per step, what to say in one sentence, and a 2-minute video shot list. Every number quoted must come from results/demo_candidates.json or another results/ file.
Rules: only docs/DEMO.md and results/demo_candidates.json. No keys. Don't start servers. Never use held-out training data claims.
Done test (LEAD): DEMO.md exists; LEAD re-asks the chosen questions and gets the same answers.
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

RESULT: X-03 wrote docs/DEMO.md and results/demo_candidates.json; 28 English candidates + 10 identical API replays = 38 questions (sequential, paced); main high-quality-108 = 7 gold-correct windows/7 scene-matched boxes, backup colorful-7513 = 5/5; AC20 show/remove W3/restore/reset persisted; eight-step script, exact clicks, backups and two-minute shots included; local artifact/consistency checks pass, no commit; LEAD target-app re-ask remains.
NEEDS: LEAD/WEB wire and rehearse the web Show on table bridge (native toolbar currently opens fixture__ios); real-device AR/browser focus/highlights remain unverified; ENGINE advisor returned no cards; DATA current scenes omit toilet/sink evidence IDs for C02/C03/C05/C06/C07 (kept as 2D-only alternatives); fire-exit answers remain explicitly unverified model inference.
