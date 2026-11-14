# S-23 deployed smoke: FAIL

`0254cc0` became healthy at 2026-11-14 13:01:16 UTC after 6 polls over 150.7 seconds. Health and database were ready. The Vercel smoke began on that revision and ended on `52dd6f6`; the Aiven full smoke stopped at its revision guard.

- Vercel: 77/79 checks passed. Failures: `/api/bench/latest` returned 404; final health returned the wrong revision.
- Aiven full smoke: revision check failed; 46 routes were not reached (not 46 observed endpoint failures).
- Supplemental Aiven diagnostics on `52dd6f6`: health/database passed; `/api/bench/latest` returned 404; `/api/costs/summary` returned 200.
- `/api/costs/summary` also returned 200 through Vercel. The expected benchmark accuracy 0.7647 (143/187), abstentions 0, could not be verified.

| AC20 via Vercel | Successful / requested | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| cached | 10 / 10 | 667.6 | 1313.2 |
| novel | 5 / 5 | 1555.0 | 1827.2 |

Timings are end-to-end through the terminal SSE answer, excluding pacing; requests were spaced by at least 2.5 seconds (24/min). Percentiles use nearest rank. Five warmups preceded the 10 repeated questions. The 5 novel questions had unique run labels. The API exposes no cache-hit flag, so “cached” denotes warmed repeats only. The deployment changed during this sample; timings cannot be attributed to `0254cc0`. Direct-Aiven latency was not run after the revision guard failed.

Full evidence: [combined JSON](deployed-0254cc0.json), [Vercel](deployed-0254cc0-vercel.md), [Aiven guard](deployed-0254cc0-aiven.md), [Aiven diagnostics](deployed-0254cc0-aiven-diagnostics.json), [health watch](deployed-0254cc0-watch.json).

Needs: restore the benchmark endpoint and rerun against a stable deployment revision.
