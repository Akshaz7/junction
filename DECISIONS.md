# DECISIONS

Format for new lines: `YYYY-MM-DD HH:MM — decision — reason`.

## Fixed (section 2 of MASTER_PROMPT; do not reopen)
- Language: English only. Non-English questions filtered out of tests; drawings may contain other languages, app answers in English.
- Accounts: none. One shared demo workspace.
- Security: no security reviews, code reviews or CI. Only: keys never in git; rate limit 30 req/min/IP on deployed backend.
- Hosting: web on Vercel; backend (API + live sync) one container on Aiven Runtime; Aiven PostgreSQL; EU region.
- Local first: `make dev` runs everything with no keys (Docker Postgres, fake provider). Deploy rows wait for keys.
- GPU: Modal for fine-tuning and optional vision endpoints. Budget cap in COSTS.md.
- Budget provider: Runware (OpenAI-compatible) is main paid provider for bulk tests and fallback for every other provider.
- Gemini: called directly (Google challenge): reads drawings, checks unclear items, voice to intent.
- Nemotron: called directly on build.nvidia.com (NVIDIA challenge): router fallback, advisor, cheap item checks. Not wall detection.
- Claude: final written answers for text questions and hard reasoning.
- Small vision models: fine-tuned at the event: one segmenter (walls, doors, windows, rooms), one detector (doors, windows, toilets, sinks, showers, bathtubs).
- Verda: out (domain down). Do not call.
- Advisor rules: Finnish building rules in English translation; unofficial translations marked.
- Demo building: `ac20_arc.ifc` for IFC. Best DXF and raster plan chosen by test results.
- Dataset: preview first; full 10 GB in background.
- Agents: 7 workers under one Claude lead: 4 Claude (DATA, VISION, ENGINE, SERVER), 3 Codex (WEB, 3D, IOS). Lead runs every done test.
- Scope order: three tiers. Nothing is cut; order decides what finishes first.

## Log
- 2026-11-14 02:45 — LICENSE copyright changed to "2026 Team RS3" — section 11 requires it.
- 2026-11-14 02:45 — Initial TASKS status: rows with no keys `todo`, rows naming keys `waiting-key` — check_keys.py releases them.
- 2026-11-14 02:55 — Ash: build every iOS row (I-01..I-09) overnight against the simulator and unit tests; no device tonight. I-05 (install on iPhone) is deferred to Saturday morning when Ash plugs in the phone: the lead writes the exact install steps to MORNING.md and sets I-05 `blocked-human` instead of spending attempts on it. Device absence never counts as a failed attempt for any other iOS row — Ash's instruction.
- 2026-11-14 02:50 — Runware cap raised from 300 to 500 USD — Ash's instruction.
