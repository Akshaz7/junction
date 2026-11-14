# CLAUDE.md — Junction 2026, Team RS3 (Stoa "Make Blueprints Talk")

Every agent reads this first. The full plan is `docs/MASTER_PROMPT.md`. When in doubt, it wins.

## Mission
Pitch: "We rebuilt Stoa's product in two days. Then we built the part that does not exist yet."

A Stoa-style app that answers natural-language questions about construction drawings and BIM models. Every answer shows proof, and the same numbered items carry through three views:
1. **2D**: numbered boxes on the drawing, with citations.
2. **3D**: "Visualise it" extrudes the plan; the same items glow.
3. **AR**: "Show on table" in the iOS app; same items glow; 1:1 walk-through.

Core idea: read each drawing ONCE into a structured **plan map** (walls, doors, windows, rooms, fixtures, text, with positions). Most answers are then plain code over the plan map: exact, checkable, almost free. Models only where code cannot.

Judging (25% each): accuracy / visual verifiability / creativity / low inference cost.

Deadlines (Finland time): hard freeze Sun 15 Nov 07:00, final report 08:30, submission 10:00. Check `date` every lead loop.

## Fixed decisions (do not reopen; see DECISIONS.md)
- English only answers. Filter non-English questions out of tests.
- No accounts. No security/code reviews, no CI. Only: keys never in git; 30 req/min/IP rate limit on deployed backend.
- Web on Vercel. Backend (API + live sync) one container on Aiven Runtime. Aiven PostgreSQL. EU region.
- Local first: `make dev` runs everything with NO keys (Docker Postgres, `fake` model provider).
- GPU: Modal (fine-tuning, optional vision endpoints). No training on the Mac.
- Providers: Runware = budget bulk + fallback for all. Gemini = drawing reading, item checks, voice. Nemotron (build.nvidia.com) = router fallback, advisor, cheap checks (NOT wall detection). Claude = written answers, hard reasoning. Verda: OUT.
- Our own fine-tuned small vision models: one segmenter (walls/doors/windows/rooms), one detector (doors/windows/toilets/sinks/showers/bathtubs).
- Demo building `ac20_arc.ifc`; best DXF and raster plans picked by test results.
- Agents: LEAD (Claude) + DATA, VISION, ENGINE, SERVER (Claude) + WEB, 3D, IOS (Codex).
- Tiers 1 → 2 → 3. Nothing is cut; order decides what finishes first.

## Rules (full text: MASTER_PROMPT section 4)
- Done test decides done. <60 s unless LONG. Max 3 attempts, then `blocked` + one line.
- **Only the LEAD commits.** Message starts with row ID (`E-03: count solver`). Workers never `git commit/add -A/stash/checkout`.
- Each worker edits only its own folders (AGENTS.md). Cross-folder changes go via LEAD (`NEEDS:` line).
- Only LEAD edits CONTRACT.md (version bump + DECISIONS.md line). LEAD may add TASKS rows, never delete/alter.
- Never ask Ash during PHASE B: decide, write it in DECISIONS.md, continue.
- Read LESSONS.md and GOTCHAS.md before each row; add 1–2 lines when you learn something.
- Never commit: `.env*`, `data/`, `refs/`, `weights/`, `artifacts/`, `logs/`, model files, service-account JSON, files >10 MB. Never copy keys anywhere. No force-push, no history rewrite.
- **LEAD pushes after every commit:** `git push origin main`. On rejection: `git pull --rebase origin main`, then push. Never force.
- Honesty: numbers only from `results/`. Never train on held-out drawings (`data/sets/heldout_docs.txt`). Label generated content "generated for demo". Advisor never invents rules/sources. No data → say so.
- Licences: repo MIT. No AGPL/GPL deps (`ultralytics`, `PyMuPDF` banned → pypdfium2 + pdfminer.six; RT-DETR/YOLOX). Record models/datasets in docs/MODELS.md. `refs/` is visual reference only; never copy `refs/stoa-hero/source/` code; no Stoa logo/drawings in git or app. Wordmark: "Hologram". Don't publish converted `duplex_arc`, Dental Clinic (CC BY-ND) or `hitos_arc` (GPL data). cubicasa5k is CC BY-NC-SA.
- Budget: every model call through `engine/models` `call()`; caps in COSTS.md. Ladder: code → small model → large model. Quick tests on `sample200`; full bench ≤4×/run. Every external service behind a switch with a fallback.

## Machine limits (MacBook Pro M4 Pro, 24 GB)
- Heavy jobs via `scripts/heavy.sh <cmd>` (max 2 at once): xcodebuild, IFC/batch conversion, bulk inference, bench, Playwright, Docker builds.
- IfcConvert `-j 4`, one file at a time; >50 MB runs alone. Batch conversion ≤3 procs, `nice`.
- Vision inference batch 1–4, one model loaded at a time. Playwright headless, one browser per worker.
- Docker: only local Postgres, 1 GB limit. One web + one API dev server (via `make dev`).
- Disk <15 GB free → pause D-11, delete `artifacts/**/tmp` and Xcode DerivedData. Swap >8 GB → pause LONG jobs.

## Key commands
- `./tools/IfcConvert -j 4 --use-element-guids --y-up in.ifc out.glb`
- `python3 scripts/check_keys.py` — key status (never prints keys)
- `python3 scripts/pulse.py` — workers, rows, memory, swap, disk
- `python3 scripts/preflight.py` — environment check
- `make dev` / `make test` (after S-01)

## Where things are
| File | What |
|---|---|
| `docs/MASTER_PROMPT.md` | Full plan (sections 1–14) |
| `CONTRACT.md` | IDs, coordinates, file formats, answer object, API (versioned) |
| `AGENTS.md` | Workers, owned folders, how Codex gets a row |
| `TASKS.md` | The task table with Status and Notes |
| `handoff/<WORKER>.md` | Current row for each Codex worker |
| `DECISIONS.md` / `LESSONS.md` / `GOTCHAS.md` | Decisions, learnings, traps |
| `COSTS.md` | Budget caps and hourly spend |
| `STATE.md` | Paths, tool versions, preflight, hourly log |
| `MORNING.md` | Report for Ash, kept current hourly |
| `data/junction-dataset-preview/` | Preview dataset (`questions.jsonl`, `data/<source>/…`) |
| `out/`, `scripts/extract_elements.py`, `scripts/validate_glb.py` | IFC spike output and scripts |
| `refs/stoa-hero/` | Stoa UI reference pack (git-ignored) |
| `docs/MODELS.md`, `docs/ACCURACY.md`, `docs/API.md`, `docs/DEMO.md`, `docs/sponsors/` | Docs |
