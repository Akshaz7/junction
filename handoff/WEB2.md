# Handoff: WEB2 (Codex, second worker)

Row ID: X-01 (attempt 1)  — README (Tier 1; draft now, LEAD refreshes numbers when E-10 lands)
Rewrite `README.md` (currently the old IFC spike readme; keep its useful IfcConvert notes in a short "IFC conversion" section) for the project "Hologram" (Junction 2026, Team RS3, Stoa challenge "Make Blueprints Talk"):
1. What it is (pitch from CLAUDE.md; 3 views 2D/3D/AR with the same numbered items; plan map read once → most answers are plain code).
2. How to run: `make dev` with no keys (fake provider, Docker Postgres on 5433), web :5173, API :8000; keys in `.env` (names only, from .env.example; never values); iOS: ios/README.md and `bash ios/scripts/install_on_device.sh`; tests (`make test`, Playwright e2e list, xcodebuild test).
3. Architecture: short diagram in text (pipeline/ → artifacts/<doc_id>/ plan map + scene.glb + usdz → engine/ (router rules → Nemotron → Runware; solvers; models call()) → server/ FastAPI + Postgres + /ws → web/ (Vite React, three.js viewer3d) and ios/ (SwiftUI + RealityKit)). Point to CONTRACT.md for formats.
4. Accuracy and cost: numbers ONLY copied from results/ files, each with its file path in the same sentence: results/bench/<latest real tag>.json (state honestly that text answers are reported apart and which cells abstain), results/router_cost.json, results/router_model_only.json, results/vision/*.json, results/costs.jsonl totals (sum it), results/fidelity/report.json (pass counts). Add a line "Numbers last refreshed: <time>".
5. Credits & licences: repo MIT; datasets and models from docs/MODELS.md (copy names + licences; cubicasa5k CC BY-NC-SA; publishable:false sources not shown in the app); the line "Built for the Stoa challenge at Junction 2026 with Stoa's permission to reference their product flow; no Stoa code, logo or drawings are included." Wordmark "Hologram".
6. Sponsor tools: link docs/sponsors/README.md.
Rules: only README.md. No keys. No claims without a path.
Done test (LEAD): every number in README appears in a results/ file (LEAD greps each).
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: X-01 — Rewrote README.md for Hologram with local/iOS/test commands, architecture, IFC notes, licences and sponsor links; local evidence audit passed (links, .env names, latest non-fake sample200-r2 table/text/cost, all metric values, summed first 4949 costs.jsonl records, fidelity phase counts). Refreshed benchmark text after concurrent results update; LEAD should refresh live numbers before submission. No commits.
