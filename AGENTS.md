# AGENTS

**Read `CLAUDE.md` first.** Then `CONTRACT.md`, `LESSONS.md`, `GOTCHAS.md`, and your row in `handoff/<WORKER>.md`.

## Rules (short form; full text in `docs/MASTER_PROMPT.md` section 4)
1. The done test decides if a row is done. Each runs in under 60 s unless marked LONG.
2. Max 3 fix attempts per row, then `blocked` with one line why.
3. **Workers never run `git commit`, `git add -A`, `git stash` or `git checkout`.** Only the LEAD commits.
4. Edit only your own folders (table below). Need a change elsewhere? Write one line starting `NEEDS:` in your handoff file.
5. Only the LEAD edits `CONTRACT.md`. Build against it exactly.
6. No CI, no reviews, no refactors, no cleanup, no long reports.
7. Never ask Ash. Decide and record it.
8. Never commit or copy keys. `.env` is read fresh, never printed.
9. Heavy jobs (xcodebuild, IFC/batch conversion, bulk inference, bench, Playwright, Docker builds) go through `scripts/heavy.sh <cmd>`. 24 GB Mac: no training locally.
10. Never invent a number. Never train on held-out drawings. Label generated content "generated for demo". If the data has no answer, say so.
11. Licences: repo is MIT. No AGPL/GPL deps (`ultralytics`, `PyMuPDF` are banned). Never copy code from `refs/stoa-hero/source/`. No Stoa logo/drawings in git or app.
12. Model calls only through `engine/models` `call()`.
13. When your done test passes, append one line starting `RESULT:` to your handoff file.


There is one LEAD (Claude) and 7 workers: 4 Claude workers and 3 Codex workers. Claude owns the data, the models, the engine and the server. Codex owns everything the user sees: web, 3D and iOS. The two sides meet only at the contract (section 5).

| Worker | Agent | Owns folders | Job |
|---|---|---|---|
| **LEAD** | Claude | root `*.md`, `docs/`, `handoff/`, `logs/` (not in git), `scripts/preflight.py`, `scripts/check_keys.py`, `scripts/pulse.py` | Runs the loop in section 10. Owns the contract, the table and all commits. |
| **DATA** | Claude | `pipeline/`, `artifacts/` (not in git), `data/` | Dataset, registry, question sets, page images, IFC and DXF to plan map and 3D, extrusion, USDZ, Drive, Cloudinary. |
| **VISION** | Claude | `vision/`, `train/`, `weights/` (not in git) | Raster plans to plan map. Fine-tuning. Vision evaluation. |
| **ENGINE** | Claude | `engine/`, `results/` | Model layer, router, solvers, answers, bench, changes engine, advisor. |
| **SERVER** | Claude | `server/`, `deploy/`, `Makefile`, Docker files | Backend API, database, live sync, deploy of server and web. Rows S-xx. |
| **WEB** | Codex | `web/` except `web/src/viewer3d/` | Stoa-style web app screens. Rows W-xx. |
| **3D** | Codex | `web/src/viewer3d/` | three.js viewer, highlight, "Visualise it", edit mode. Rows T-xx. |
| **IOS** | Codex | `ios/` | iOS shell and native AR screen. Rows I-xx. |

**How the lead runs workers**
- Claude workers: the parallel subagent mechanism of this Claude Code version.
- Codex workers: `codex exec`, one process per Codex worker at a time, each started in the repo root. Run the three Codex workers in parallel with each other and with the Claude workers.
- If parallel runs are not possible for some reason, take rows round-robin in tier order.

**How a Codex worker gets a row**
1. The lead writes `handoff/<WORKER>.md` (for example `handoff/WEB.md`): row ID, task, input files, contract sections to read, the done test command, and the result of the last failed attempt if there is one.
2. The lead runs `codex exec` with a short instruction: "You are the <WORKER> worker. Read AGENTS.md, CLAUDE.md, CONTRACT.md, LESSONS.md, GOTCHAS.md, then do the row in handoff/<WORKER>.md. Edit only your own folders. Do not commit. When the done test passes locally, append one line to handoff/<WORKER>.md that starts with RESULT:."
3. The lead runs the done test itself. Pass: commit and give the next row. Fail: write the error into the handoff file and run Codex again. At most 3 attempts.
4. Codex reads `AGENTS.md` by default. So `AGENTS.md` must start with the rules of section 4 in short form and a pointer to `CLAUDE.md`.

**Cross-side requests.** A Codex worker that needs a change in `server/` or the contract writes one line starting with `NEEDS:` in its handoff file. The lead turns it into a row for the right Claude worker. The same applies in the other direction.

VISION was split from DATA because reading raster plans is the heart of the engine. SERVER was split from WEB so that the backend is ready early and the Codex side can build against real endpoints. IOS has no tier 1 rows, so it starts its tier 2 rows at once.

**Stack**
- Python 3.12 with `uv`: `pipeline/`, `vision/`, `train/`, `engine/`, `server/` in one project. Libraries: ifcopenshell, ezdxf, trimesh, shapely, usd-core, pypdfium2, pdfminer.six, opencv, onnxruntime, torch, transformers, FastAPI, asyncpg.
- Web: Vite + React + TypeScript + Tailwind v4 + lucide-react, shadcn-style components, three.js. Design tokens from `refs/stoa-hero/theme-tokens.css` and the three guide files in that pack.
- iOS: Swift, SwiftUI, RealityKit, ARKit, XcodeGen for the project file.
- `make dev` starts local Postgres (Docker), the server and the web app. `make test` runs all fast tests.

---
