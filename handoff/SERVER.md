# SERVER (Codex) — current row

ROW: S-22 /api/bench/latest + cost per answer
1. GET /api/bench/latest returns 404 on deployed (QA-LIVE). Implement it: read the newest results/bench/*.json that is a full real-provider run (fake=false), prefer the one docs/REPORT.md cites (e-s200-z1), and return {tag, n, numeric_correct, numeric_total, accuracy, abstentions, by_type, cost_usd_total, cost_per_answer, file}. Package results/bench/*.json (small files only, not *.rows.jsonl) into the deploy image if the Dockerfile doesn't already: check deploy/Dockerfile and say what you changed.
2. GET /api/costs/summary: total model spend and the median cost per answer from the answers table (last 24 h), for the Accuracy page "low inference cost" story. If the table has no cost column, say so and compute from the trace instead.
Tests: server/tests/test_bench_latest.py (tmp dir with two bench files, picks the right one; 404 → never).
Allowed: server/ (new bench_routes.py, app.py include), deploy/Dockerfile (COPY only), docs/API.md, this file.
Done test: .venv/bin/python -m pytest -q -p no:cacheprovider server/tests/test_bench_latest.py
Never commit. Write one line at the end: RESULT: ...
NEEDS: LEAD must allow results/bench/*.json through .dockerignore (currently excludes all results); append !results/, results/*, !results/bench/, results/bench/*, !results/bench/*.json in that order so the new Dockerfile COPY can build without row dumps. Also stage these small summary files in deploy/vercel_api/stage.sh for the current Vercel fallback host (outside S-22 allowed scope).
RESULT: S-22 done test 8 passed; targeted benchmark regression tests 10 passed. Latest prefers completed real e-s200-z1 with numeric/per-type/cost fields and packaged-results fallback; absent measurements return 200/null. Added /api/costs/summary (runtime model-log total plus last-24h answer median; answers has no cost column, uses answer.cost.usd_total then trace). Dockerfile adds COPY results/bench/*.json /app/results/bench/ only; docs/API.md updated; deployment packaging NEEDS above remain for LEAD. No commit.
