# SERVER (Codex) — current row

ROW: S-23 deployed health watch + smoke after 0254cc0
1. Poll https://obviously-present-piglet.eur-1.aiven.app/api/health every 30 s until build_rev == 0254cc0 (max 25 min). If it never arrives or health fails, report the last state (the Aiven build may have failed: say so).
2. Then run scripts/smoke_live.py against the deployed site (via https://hologram-khaki.vercel.app and the Aiven origin), including the new checks: GET /api/bench/latest returns 200 with accuracy 0.7647 (143/187) and abstentions 0; GET /api/costs/summary returns 200. Save results/smoke/deployed-0254cc0.json and .md.
3. Measure p50/p95 latency for 10 cached and 5 novel AC20 questions (pace ≤ 25 req/min); add them to the md.
Allowed: scripts/smoke_live.py, results/smoke/, this file.
Never commit. Write one line at the end: RESULT: ...

NEEDS: S-23 /api/bench/latest returns 404 via Vercel and Aiven; deploy a stable revision serving the recorded bench. 0254cc0 arrived but changed to 52dd6f6 mid-smoke, so the origin smoke stopped at the revision guard.
RESULT: S-23 FAIL: health watch matched 0254cc0 after 150.7 s; Vercel 77/79 passed (bench 404, revision changed), costs/summary 200 on both paths; Aiven full smoke stopped at revision guard. Vercel warm repeats n=10 p50/p95 667.6/1313.2 ms, novel n=5 1555.0/1827.2 ms (mixed deployment, no cache-hit claim). Reports: results/smoke/deployed-0254cc0.json and .md. Dry-run 47-route coverage and local latency-runner checks passed; no commit.
