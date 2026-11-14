# Deployed e2e check (LEAD, 2026-11-14 ~09:30 EET)

Target: web https://hologram-khaki.vercel.app → /api rewrite → API https://hologram-api.vercel.app (Vercel Python, region fra1 per x-vercel-id) → Aiven PostgreSQL hologram-pg.
Config: same specs as the local suite with baseURL = deployed web, Chromium on the Mac GPU.

| Spec | Result |
|---|---|
| e2e/chat.spec.ts (real chat, bold answer, citations, cost) | pass |
| e2e/viewer.spec.ts (2 tests: citation opens numbered page; phone sheet) | pass |
| e2e/demo-flow.spec.ts:17 desktop live raster proof → 3D → AC20 doors → scene edits | pass |
| e2e/demo-flow.spec.ts:103 phone live count sheet | pass on rerun (first: 60 s response timeout during the 30 req/min/IP limit window; second: backend status line not seen once; then 2/2 clean passes) |
| e2e/demo-flow.spec.ts:138 phone Data preview + Chat tab | pass |

Before the fixes at ~09:20 the same run failed 4/6: baked demo artifacts were from 03:31 (stale plan maps, demo-flow doc missing). Refreshed (deploy/build_demo_artifacts.py, 11 docs, 44.7 MB); API pinned to fra1; DB pool made loop-safe for serverless.
Health: {"ok":true,"db":true}; rate limit: 429 after the per-minute allowance.
Not covered on the deployment: /ws live sync between devices (Vercel has no WebSockets; Aiven Runtime target needs the Aiven GitHub App).
Local full suites on final HEAD: web 94/94; backend 222/222 (one load-flake when run alongside the web suite, 222/222 alone twice).
