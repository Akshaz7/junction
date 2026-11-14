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
- 2026-11-14 02:51 — LEAD runs `git push origin main` right after every commit (never force; on rejection: `git pull --rebase origin main` then push; if that conflicts, abort the rebase, log it here and in MORNING.md, keep committing locally) — Ash's instruction, so progress is visible on GitHub.
- 2026-11-14 02:55 — Added row V-00 (model shortlist + CubiCasa5K download) — VISION has no row with satisfied deps until D-04. 3D waits for W-01 (~15 min) because T-01 needs the web scaffold.
- 2026-11-14 02:55 — LEAD owns root `pyproject.toml`/`uv.lock`; Claude workers request new Python deps with a NEEDS: line in their report instead of running `uv add` — avoids 4 agents racing on the lock file.
- 2026-11-14 02:55 — Codex runs as `codex exec -s workspace-write -c sandbox_workspace_write.network_access=true` (network for npm); iOS builds use `-derivedDataPath ios/build/DerivedData` so they stay inside the sandbox.
- 2026-11-14 02:56 — Added row T-00 (viewer core as plain TS, no package.json edits) — 3D had no row with satisfied deps (T-01 needs W-01 and D-06); Ash pointed out it was idle.
- 2026-11-14 02:57 — Pulse runs every 60 s in `scripts/lead_watch.sh` (logs/pulse.log); it wakes the LEAD only on a '!!' flag or every 10 min for check_keys. Worker completions wake the LEAD directly. Same 60 s pulse, far fewer idle lead turns.
- 2026-11-14 02:58 — I-02 starts before D-10 using a fixture USDZ the LEAD generates with usd-core (5 prims named by usd_name) — the row allows a bundled fixture; avoids IOS idling for hours. Real scenes swap in when D-10 lands.
- 2026-11-14 03:04 — T-01 starts before D-06 on the digital_hub fixture from T-00 — same reasoning as I-02; real ac20 scene swaps in when D-06 lands.
- 2026-11-14 03:05 — Router chain for task `route`: rules parser → NVIDIA Nemotron → Runware; Gemini removed from route — section 2 assigns the router fallback to Nemotron (NVIDIA challenge).
- 2026-11-14 03:08 — doc_id keeps the source folder name verbatim and slugs only the stem (`ifc_bench__ac20-arc`, `cubicasa5k__colorful-11397`); matches the CONTRACT 5.1 example. CONTRACT v2: doc.json gains `files` {format: path relative to dataset root}.
- 2026-11-14 03:21 — Vision: Yytsi ResNet34-UNet (MIT) is the segmenter; CubiCasa official (CC BY-NC) is an internal fixtures baseline only; final detector = permissive RT-DETR fine-tuned on CubiCasa5K SVG boxes (V-07) — licence + coverage.
- 2026-11-14 03:26 — OCR = rapidocr-onnxruntime (Apache-2.0, runs in the Linux deploy image) over macOS Vision; added onnx for V-08.
- 2026-11-14 03:28 — Shared dev servers started by LEAD with `make dev` (logs/dev.log): API :8000, web :5173. Workers must not start their own copies.
