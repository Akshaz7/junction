# JUNCTION 2026 MASTER PROMPT (Team RS3, Stoa "Make Blueprints Talk")

You are the LEAD agent in Claude Code on Ash's Mac. This file is the full plan for the build. Read all of it before you act.

The build has several runs. **This is run 1: the first overnight run. It starts about 02:30 on Saturday 14 Nov.** The final deadline is Sunday 10:00, so there is more than a full day after this run. Do not rush and do not cut corners to "finish" tonight. Work in tier order and keep going until Ash comes back.

The work has two phases.

- **PHASE A (run now, about 20 minutes):** set up the repo, write the project files from this prompt, run the preflight check, print the report, then STOP.
- **PHASE B (starts when Ash sends the `/goal` line from section 14):** work through `TASKS.md` without Ash until he comes back and gives a new instruction.

Ash adds API keys to `.env` while you work. A missing key is normal. It never stops you (section 9).

---

## 1. Mission

**Pitch:** "We rebuilt Stoa's product in two days. Then we built the part that does not exist yet."

**Product:** a Stoa-style app that answers natural-language questions about construction drawings and BIM models. Each answer shows proof. The proof moves through three views with the same items:

1. **2D:** numbered boxes on the drawing, with citations.
2. **3D:** "Visualise it" turns the plan into a 3D building. The same items glow.
3. **AR:** "Show on table" puts the building on a table through the iOS app. The same items glow. At 1:1 scale the user walks through it.

**Core engine idea:** read each drawing ONCE into a structured **plan map** (walls, doors, windows, rooms, fixtures, text, each with a position). After that, most answers are plain code over the plan map: exact, checkable, and almost free. AI models work only where code cannot.

**Judging (25% each):** accuracy of answers / how well a human can verify the answer visually / creativity / low inference cost. Every decision must serve one of these four.

**Timeline:** Check the clock with `date` in every lead loop.
- Run 1 (now): no fixed end. Keep `MORNING.md` current every hour, so it is correct whenever Ash returns on Saturday morning.
- Later runs on Saturday: Ash starts each one with a new instruction. The table, the contract and the notes files carry over.
- Hard freeze: Sunday 15 Nov 07:00 Finland time. Final report 08:30. FINAL submission 10:00.

**Event rules (breaking these disqualifies the team):**
- All project code is written at the event. Write all code fresh. Open-source libraries are fine.
- The repo is public and MIT licensed.
- A 2-minute video and a source link are part of the submission.

---

## 2. Fixed decisions (do not reopen)

| Topic | Decision |
|---|---|
| Language | English only. Filter non-English questions out of tests. Drawings can contain other languages; the app answers in English. |
| Accounts | None. One shared demo workspace. |
| Security work | None. No security reviews, no code reviews, no CI. Only two rules: keys never in git, and a rate limit (30 requests/min per IP) on the deployed backend. |
| Hosting | Web on Vercel. Backend (API + live sync) as one container on Aiven Runtime. Database: Aiven PostgreSQL. EU region. |
| Local first | Everything must run on the Mac with `make dev` and NO keys (local Postgres in Docker, fake model provider). Deploy rows wait for keys. |
| GPU | Modal, for fine-tuning and optional vision endpoints. Budget cap in `COSTS.md`. |
| Budget provider | Runware (OpenAI-compatible) is the main paid provider for bulk tests and the fallback for every other model provider. |
| Gemini | Called directly (Google challenge): reads drawings, checks unclear items, voice to intent. |
| Nemotron | Called directly on build.nvidia.com (NVIDIA challenge): question router fallback, advisor, cheap item checks. Nemotron does NOT detect walls. |
| Claude | Final written answers for text questions and hard reasoning. |
| Small vision models | Fine-tuned by us at the event: one segmentation model (walls, doors, windows, rooms) and one detector (doors, windows, toilets, sinks, showers, bathtubs). |
| Verda | Out. Their domain is down. Do not call it. |
| Advisor rules | Finnish building rules in English translation. Mark unofficial translations as such. |
| Demo building | `ac20_arc.ifc` for the IFC story. Pick the best DXF plan and the best raster plan by test results. |
| Dataset | Preview first. Download the full 10 GB set in the background. |
| Agents | 7 workers under one Claude lead: 4 Claude workers (DATA, VISION, ENGINE, SERVER) and 3 Codex workers (WEB, 3D, IOS). The lead runs every done test. |
| Scope order | Three tiers (section 7). Nothing is cut. Order decides what is finished first. |

---

## 3. Paths and facts you start with

Confirm each path in PHASE A. If a path differs, find the real one and record it in `STATE.md`.

| Thing | Expected location |
|---|---|
| Repo | `/Users/akshatthapa/Workspace/junction` |
| Preview dataset (unzipped) | `data/` inside the repo. Find the folder that holds `questions.jsonl`. |
| Spike output | `out/` (GLB + `*.elements.json` + logs), `scripts/extract_elements.py`, `scripts/validate_glb.py`, `tools/IfcConvert` (0.8.4) |
| Stoa UI reference pack | `/Users/akshatthapa/.aside/u/0/sessions/2026-11-14_cFTAsHRhqqpxT8I0/artifacts/stoa-hero/` |
| Scraped Stoa site text | `stoabuild-full-text.md` in the repo root or in `~/Downloads` |
| Keys | `.env` in the repo root. Ash edits it during the run. |

**Dataset URLs**
- Preview (0.5 GB): `https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset-preview.zip`
- Full (10 GB): `https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip`

**Dataset facts (measured on the preview)**
- Layout: `data/<source>/<file>`, `data/<source>/LICENSE.md`, `questions.jsonl` with `{"path","question","answer","unit","type"}`.
- `type` is count, area, length, volume, text or other. Scoring: counts exact; areas, lengths, volumes within 2%; text is free-form.
- Files with the same name and a different extension are the same drawing. `ifc_models` plans `<model>_<level>.pdf` were rendered from `<model>.ifc`.
- Preview: 924 files (374 jpg, 306 png, 123 pdf, 66 dxf, 20 dwg, 14 ifc, 10 svg). 7,990 questions: 6,914 on PNG/PDF, 1,076 on IFC. Types: 6,076 count, 1,599 area, 265 text, 34 volume, 16 length. Many questions have a Finnish copy.
- Sources: cubicasa5k (Finnish raster plans), swiss_dwellings (PDF + DXF + PNG of the same floor), opening_design (real drawing sets, DWG, some IFC), ifc_models, ifc_bench, habs, finna, europeana, wikimedia.
- Known answers to use in tests: `ac20_arc.ifc` has 5 storeys, 77 doors, 206 windows, 121 walls, 82 spaces; storey "Erdgeschoss" has 18 spaces; largest room is "006" (Seminarraum, 128.3 m2). `cubicasa5k/colorful-11397.png`: 13 windows, 2 toilets, 3 sinks, 3 showers+bathtubs.
- Working IFC command: `./tools/IfcConvert -j 4 --use-element-guids --y-up in.ifc out.glb`. GLB node names are IFC GlobalIds. IfcConvert leaves out IfcSpace and IfcOpeningElement unless included. Names, types and storeys are NOT in the GLB; they come from the IFC through `elements.json`.

**Licence facts**
- Show the credit from `data/<source>/LICENSE.md` whenever the app shows a drawing.
- `duplex_arc.ifc` and the Dental Clinic model are CC BY-ND: do not publish converted files of them. Local tests only.
- `hitos_arc.ifc` is GPL-3.0 data: do not redistribute it.
- `ac20_arc.ifc` (KIT, unrestricted) and `digital_hub_arc.ifc` (MIT) are safe for the public demo.
- cubicasa5k is CC BY-NC-SA: non-commercial use only. Say so in the README.

**The machine: MacBook Pro M4 Pro, 24 GB memory**

Seven agents, Docker, dev servers, browsers, PyTorch and Xcode share 24 GB. Memory is the tightest resource. Follow these limits:

- **No training on the Mac.** All fine-tuning runs on Modal. The Mac does inference only (MPS or ONNX on CPU).
- **Heavy lock.** Write `scripts/heavy.sh <command>` in PHASE A: a simple lock that lets at most 2 heavy jobs run at once. Heavy jobs are: `xcodebuild`, IFC conversion, batch conversion, model inference over many drawings, the bench, Playwright runs, Docker image builds. Every worker runs heavy jobs through this script.
- **IfcConvert:** use `-j 4`, not `-j 8`. Convert one IFC file at a time. Files over 50 MB run alone, with no other heavy job.
- **Batch conversion (D-11):** at most 3 worker processes. Lower priority with `nice`.
- **Vision inference:** batch size 1 to 4. Load one model at a time and free it after the batch.
- **Playwright:** headless, one browser at a time per worker. Close it after each test.
- **Docker:** limit the local Postgres container to 1 GB. No other containers stay running.
- **Dev servers:** one web dev server and one API server for the whole team, started by `make dev`. Workers do not start their own copies.
- **Disk:** the full dataset, CubiCasa5K, artifacts, weights and Xcode build data need about 60 GB. Check free disk each hour. Below 15 GB free: pause D-11 and delete `artifacts/**/tmp` and Xcode DerivedData.
- **Memory watch:** `scripts/pulse.py` also prints memory pressure and swap in use (from `memory_pressure` and `sysctl vm.swapusage`). If swap is over 8 GB, the lead pauses LONG jobs until it falls, and starts no new heavy job.

---

## 4. Rules for every run

**Work rules**
1. The **done test** decides if a row is done. Not the worker's opinion.
2. Each done test runs in under 60 seconds on the Mac. Exceptions are marked LONG (fine-tuning, full bench, batch conversion). LONG jobs run in the background.
3. Maximum 3 fix attempts per row. Then set status `blocked`, write one line why, and take the next row.
4. Only the lead commits. After a done test passes, the lead commits that worker's folders. The message starts with the row ID: `E-03: count solver`. Workers never run `git commit`, `git add -A`, `git stash` or `git checkout` on shared files. This stops 7 agents from fighting over the git index.
5. No CI, no reviews, no refactors, no cleanup rows, no long reports. One line in Notes per row.
6. Each worker edits only its own folders (section 6). A change in another folder goes through the lead.
7. Only the lead edits `CONTRACT.md`. Each change gets a version bump and one line in `DECISIONS.md`.
8. The lead may ADD rows to `TASKS.md`. The lead may not delete rows or change what a row asks for.
9. Never ask Ash a question during PHASE B. Decide, record the decision in `DECISIONS.md`, continue.
10. Read `LESSONS.md` and `GOTCHAS.md` before each new row. Add to them when you learn something. One or two lines per entry.

**Git rules**
- Never commit: `.env*`, `data/`, `refs/`, `weights/`, `artifacts/`, `logs/`, model files, service-account JSON, files over 10 MB.
- Never copy keys into any other file, log or commit message. Read `.env` fresh each time.
- Never force-push. Never rewrite history.

**Honesty rules**
- Never invent a number. Accuracy and cost numbers come only from files in `results/`.
- Never train or tune on a drawing that appears in any `questions.jsonl` (section 8).
- Label generated content: sample documents and synthetic revisions carry "generated for demo" in their title and metadata.
- The advisor never invents a rule or a source (rows E-14 to E-16).
- If the data does not hold an answer, the app says so. It does not guess.

**Licence rules**
- The repo is MIT. Do not add AGPL or GPL code dependencies. Known traps: `ultralytics` (AGPL) and `PyMuPDF` (AGPL). Use permissive tools instead (for example pypdfium2 + pdfminer.six for PDF; RT-DETR or YOLOX for detection).
- Record every third-party model and dataset in `docs/MODELS.md`: name, source URL, licence, what data it was trained on.
- `refs/` holds Stoa's material. It is a visual and timing reference only. Never copy code from `refs/stoa-hero/source/`. Never put Stoa's logo, drawings or source files in git or in the deployed app. Use our own wordmark ("Hologram", working title) and dataset drawings.
- Add to the README: "UI design follows Stoa's product, with permission from Stoa Technologies Oy."

**Budget rules**
- API credits are limited. Every model call goes through the model layer (section 5.6), which logs cost and enforces the caps in `COSTS.md`.
- Cost ladder for every answer: plain code first, then small models, then large models.
- Quick tests use `sample200`. The full bench runs at most 4 times per run.
- Every external service sits behind a switch with a fallback. The core demo must work with every sponsor service switched off.

---

## 5. CONTRACT (write this section to `CONTRACT.md`, version 1)

All workers build against this contract. If something is unclear, the lead decides and bumps the version.

### 5.1 IDs
- `doc_id`: `<source>__<file stem>` in lowercase with non-alphanumerics replaced by `-`. Files with the same stem in one source share one `doc_id` and are listed as `formats`.
- `item_id`: unique inside one doc. IFC elements use the IFC GlobalId. Plan-map items use `<kind>-<3 digits>`, for example `window-007`.
- `usd_name`: USD prim names cannot hold every character of a GlobalId. `usd_name = "i_" + first 16 hex chars of sha1(item_id)`. The map lives in `scene.json`.
- The same `item_id` is used in the 2D boxes, the GLB node name, the USDZ prim (through `usd_name`), and every answer. This is the backbone of 2D to 3D to AR.

### 5.2 Coordinates
- 2D: pixels of the page image, origin top-left, `[x0, y0, x1, y1]`.
- 3D: metres, right-handed, Y up (glTF). For a plan map: `X = (px_x - cx) * m_per_px`, `Z = (px_y - cy) * m_per_px`, `Y = height`, where `(cx, cy)` is the image centre.
- IFC scenes are recentred in X and Z on the bounding-box centre. Y keeps real elevation. The offset is stored in `scene.json`.

### 5.3 Files per document, under `artifacts/<doc_id>/`
| File | Content |
|---|---|
| `doc.json` | `doc_id`, `source`, `formats[]`, `kind` (raster, pdf, dxf, dwg, ifc, svg), `title`, `pages`, `licence`, `credit`, `heldout` (bool) |
| `page-<n>.png` | Page image. `page-<n>.thumb.png` thumbnail. |
| `text-<n>.json` | Words with `bbox_px`, from the PDF text layer or OCR. Optional. |
| `planmap-<n>.json` | The plan map for page n (5.4). |
| `elements.json` | IFC only. One entry per element (5.5). |
| `scene.json` | 3D scene manifest (5.5). |
| `scene.glb`, `scene.usdz` | 3D model. One node or prim per item. |

### 5.4 Plan map
```json
{
  "doc_id": "cubicasa5k__colorful-11397", "page": 1,
  "image": {"w": 1200, "h": 900},
  "scale": {"m_per_px": 0.0123, "method": "dimension|scalebar|dxf-units|ifc|door-prior|none", "confidence": 0.0},
  "items": [
    {"item_id": "window-007", "kind": "window", "label": null,
     "bbox_px": [410, 88, 470, 102], "polygon_px": null,
     "props": {"width_m": 1.2}, "conf": 0.93,
     "source": "seg|det|vlm|dxf|ifc|ocr|rule"}
  ],
  "provenance": {"models": {}, "created": "", "ms": 0}
}
```
`kind` values: wall, door, window, room, toilet, sink, shower, bathtub, stairs, column, text, dimension, other. Rooms carry `props.room_type`, `props.area_m2` (null if no scale) and a polygon. Units inside `props` are metres and square metres.

### 5.5 IFC elements and scene manifest
`elements.json` entry: `item_id` (GlobalId), `name`, `ifc_class`, `kind`, `predefined_type`, `type_name`, `storey` {`name`, `elevation_m`}, `bbox_m` [[minx,miny,minz],[maxx,maxy,maxz]], `quantities` (width_m, height_m, length_m, area_m2, volume_m3 where known), `props` (is_external, material, fire_rating, where present), `bbox_source`.

`scene.json`: `doc_id`, `glb`, `usdz` (local path and URL when uploaded), `units: "m"`, `up: "Y"`, `origin_offset_m`, `storeys[]`, `plan_image` (for a textured floor, optional), and `items`: map of `item_id` to {`node`, `usd_name`, `bbox_m`, `storey`, `kind`}.

### 5.6 Model layer (`engine/models/`)
- One entry point: `call(task, messages, images=None, schema=None)`. No other code may call a provider.
- `models.yaml` maps each task to a provider and model, with a fallback chain. Tasks: `route`, `read_drawing`, `verify_item`, `write_answer`, `judge_text`, `advise`, `speech_intent`, `tts`.
- Providers: `fake` (deterministic, for tests), `gemini`, `nvidia`, `anthropic`, `runware`, `featherless`. NVIDIA, Runware and Featherless share one OpenAI-compatible adapter.
- Look up current model IDs in each provider's documentation at the time you add the adapter. Never guess a model ID. Record IDs in `docs/MODELS.md`.
- Every call is logged: provider, model, tokens, images, cost in USD, latency, row or request ID. Logs go to the `model_calls` table and to `results/costs.jsonl`.
- Disk cache keyed by a hash of the full request. Tests and bench reruns hit the cache.
- Budget caps per provider from `COSTS.md`. At the cap the layer raises `BudgetExceeded` and the caller takes the fallback or abstains.
- Rate-limit errors: wait and retry with backoff, at most 5 times.

### 5.7 Answer object
```json
{
  "answer_id": "", "question": "", "doc_ids": [],
  "answer": {"text_md": "There are **13 windows** on this floor plan. [1]",
             "value": 13, "unit": "count", "confidence": 0.9, "abstained": false},
  "citations": [{"n": 1, "doc_id": "", "page": 1, "kind": "region|text|element",
                 "bbox_px": null, "item_ids": ["window-001"], "quote": null}],
  "evidence": {
    "boxes": [{"item_id": "window-001", "page": 1, "bbox_px": [0,0,0,0], "label": "1"}],
    "scene": {"doc_id": "", "highlight_item_ids": [], "camera_target_item_id": null}
  },
  "trace": [{"step": "route", "detail": "count / window -> plan map", "ms": 3, "model": null, "cost_usd": 0}],
  "route": "index|planmap|vlm|hybrid",
  "cost": {"usd_total": 0.0, "calls": []},
  "latency_ms": 0
}
```
- Box labels ("1", "2", ...) are the same numbers in 2D, 3D and AR.
- `trace` feeds the live status lines and "Show thought process".
- Numeric answers are written from templates with no model call. Only text answers use `write_answer`.

### 5.8 Voice guide (how the app talks)
Source: `refs/stoabuild-full-text.md`. Follow its style:
- Key fact first, in bold. A numbered citation after each sentence.
- A "Where it is set out" list of sources. A "Sources (n)" control. A "Show thought process" control.
- Live status lines while working, for example "Thinking…" and "Exploring document: <name>".
- When the documents do not hold the answer, say so plainly.
- Change sentences use the form "The area of room 205 reads 47.0 m2 where it read 23.5 m2."
- Under the composer: "AI can make mistakes. Verify important information."

### 5.9 Backend API (`server/`, FastAPI, Python)
| Endpoint | Purpose |
|---|---|
| `GET /api/docs`, `GET /api/docs/{doc_id}` | Document list (folders = sources) and detail |
| `GET /api/docs/{doc_id}/pages/{n}/image` | Page image |
| `GET /api/docs/{doc_id}/planmap/{n}` | Plan map |
| `GET /api/docs/{doc_id}/scene` | `scene.json`. Triggers extrusion if no scene exists yet. |
| `POST /api/upload` | Upload a drawing, start ingestion |
| `GET /api/chats`, `POST /api/chats`, `GET /api/chats/{id}` | Chats |
| `POST /api/chats/{id}/messages` | Ask. Streams server-sent events: `status`, `trace`, `answer` |
| `GET /api/changes`, `GET /api/changes/{id}` | Change feed and one comparison |
| `GET /api/bench/latest`, `GET /api/costs` | Dashboard data |
| `POST /api/tts` | Speech for an answer |
| `POST /api/findings/run`, `GET /api/findings`, `POST /api/advise` | Inspect and advisor (tier 3) |
| `WS /ws` | Live events: `chat.message`, `chat.status`, `scene.highlight`, `doc.new`, `changes.new` |

- Database tables: `documents`, `chats`, `messages`, `answers`, `changes`, `model_calls`, `bench_runs`, `rules`, `findings`.
- Live sync: the server writes to PostgreSQL, PostgreSQL `NOTIFY` fires, the server pushes the event to all WebSocket clients. A message sent on one device appears on the others in under 2 seconds.
- `scene.highlight` carries `doc_id` and `item_ids`. The web 3D viewer and the iOS AR screen both follow it.

### 5.10 iOS bridge
The iOS app shows the web app (mobile layout) in a WKWebView. The web app calls `window.webkit.messageHandlers.ar.postMessage({doc_id, item_ids})` for "Show on table". The native AR screen loads `scene.usdz`, finds prims by `usd_name`, and listens on `/ws` for `scene.highlight`.

---

## 6. Workers and folders (write this section to `AGENTS.md`)

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

## 7. TASK TABLE (write this section to `TASKS.md`, add columns `Status` and `Notes`)

**Tiers**
- **Tier 1 (must work):** engine with boxes and sources, accuracy bench, Stoa-style chat with citations and viewer, Data screen, 3D with "Visualise it", accuracy dashboard, deployed.
- **Tier 2 (the wow):** AR first, then fine-tuned models, live sync, mobile layout, Changes, linked codes, voice, Drive.
- **Tier 3 (extras):** advisor, watch loop, Overview, Skills, Automations, edit mode, sponsor write-ups.

**Tier gate:** the lead gives attention and merges in tier order. A worker with no open row in the current tier takes its next row with satisfied dependencies in a later tier. No worker is ever idle.

**Columns:** ID / Tier / Depends / Keys needed / Task / Done test. "Keys" lists `.env` names; `-` means none. ◆ = small, self-contained row: the lead may give it to any worker with spare capacity. LONG = may run over 60 s in the background.

**Fixtures:** `tests/fixtures.json` lists 10 drawings used by fast tests: 4 cubicasa5k PNG (including `colorful-11397`), 3 swiss_dwellings floors (PDF + DXF + PNG each), `ac20_arc.ifc`, `digital_hub_arc.ifc`, one `ifc_models` plan PDF.

### DATA (Claude)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| D-01 | 1 | - | - | LONG. Download the full dataset to `data/full/` with resume (`curl -C -`), unzip. Keep the preview. | `questions.jsonl` in `data/full` has over 100,000 lines. If the download fails 3 times, continue on the preview and retry each hour. |
| D-02 | 1 | - | - | Registry: scan the dataset, write `artifacts/<doc_id>/doc.json` and `artifacts/registry.jsonl`. Parse licence and credit from each `LICENSE.md`. | Every preview file maps to a doc. `ac20_arc` licence is the KIT one. Docs with no credit are listed in `results/missing_credits.txt`. |
| D-03 | 1 | D-02 | - | Question sets in `data/sets/`: `questions_en.jsonl` (English only), `heldout_docs.txt` (every doc with a question, plus same-stem siblings), `cubicasa_heldout_ids.txt` (dataset name `colorful-11397` maps to CubiCasa5K sample `colorful/11397`), `sample200.jsonl` (stratified by source and type, seed 42), `router_train.jsonl` and `router_test.jsonl` (80/20 split BY DRAWING). | 200 rows in the sample. No drawing is in both router files. A language check finds no Finnish row in the sample. `doc.json.heldout` is set. |
| D-04 | 1 | D-02 | - | Write `tests/fixtures.json` and a loader helper. | The loader returns 10 existing docs. |
| D-05 | 1 | D-02 | - | Page images for PDF, SVG, DXF (and DWG if a converter works) at a fixed DPI, plus thumbnails. Extract the PDF text layer and vector paths to `text-<n>.json` where they exist. | Every fixture has `page-1.png`. Vector PDFs in the fixtures have words with boxes. DWG failure is allowed: note it in `GOTCHAS.md`. |
| D-06 | 1 | D-04 | - | IFC pipeline: recentred `scene.glb` (IfcConvert, GUID node names, Y up), `elements.json` v2 (5.5) with quantities from property sets and geometry, `scene.json`. Take boxes from the GLB nodes, not from a second geometry pass. Include IfcSpace in the index. | For `ac20_arc`: 77 doors, 206 windows, 121 walls, 82 spaces, 5 storeys. Every `item_id` in `scene.json` exists as a GLB node. |
| D-07 | 1 | D-06 | - | IFC storey plans: one plan image per storey and a plan map whose `item_id`s are GlobalIds, with `bbox_px` projected from 3D. | `ac20_arc` storey "Erdgeschoss" plan map has 18 rooms. Each box lies inside the image. |
| D-08 | 1 | D-05 | - | DXF to plan map with ezdxf: walls, doors, windows, rooms, with real units as scale. | For each swiss fixture the room and unit counts match the question answers that exist for it. |
| D-09 | 1 | D-08 | - | `pipeline/extrude.py`: any plan map to `scene.glb` + `scene.json`. One node per wall, door, window and room floor. Defaults: wall 2.7 m, door opening 2.1 m, window sill 0.9 m and head 2.1 m. The plan image is the floor texture. | The GLB loads in trimesh. Node names include every wall, door and window `item_id`. Extents equal image size times scale within 1%. |
| D-10 | 1 | D-06, D-09 | - | USDZ export with usd-core for every scene. Prim names are `usd_name`. | The USDZ opens with `usdchecker --arkit` (or loads in a Swift test). Every `usd_name` in `scene.json` exists as a prim. |
| D-11 | 1 | D-05..D-10 | - | LONG. Batch runner with resume: all preview docs, then the full set. Progress in `STATE.md`. | A second run skips finished docs. Failures are listed with a reason in `results/batch_failures.jsonl`. |
| D-12 | 2 | D-08 | - | Synthetic revisions for the Changes demo: edit 3 DXF plans (remove a wall, add a door, change a room) and render version 2. Store the true change list. Label "generated for demo". | Each revised doc has `v1`, `v2` and `truth_changes.json`. |
| D-13 | 2 | S-04 | GOOGLE_APPLICATION_CREDENTIALS, DRIVE_FOLDER_ID | Google Drive sync: read-only poll of one folder every 30 s. New or changed files go to ingestion and raise `doc.new` or `changes.new`. | A file dropped in the folder appears in `/api/docs` within 60 s (live test). |
| D-14 | 2 | D-10 | CLOUDINARY_URL | Upload GLB, USDZ, page images and thumbnails to Cloudinary. Put URLs in `scene.json` and `doc.json`. Test whether Cloudinary converts GLB to USDZ; record the result in `GOTCHAS.md`. | URLs for the demo docs return HTTP 200. |
| D-15 | 3 | D-06 | - | ◆ Sample project documents for `ac20_arc`, labelled "generated for demo": a short specification, a door schedule built from the IFC, three meeting minutes. | Files exist in `artifacts/samples/` with the label in the first line. |

### VISION (Claude)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| V-01 | 1 | D-04 | - | Baseline segmentation of walls, doors, windows and rooms on raster plans with a pretrained open model. Candidates: the CubiCasa5K official model, a SegFormer-B0 floor-plan model, a ResNet-UNet floor-plan model. Record licence and training data in `docs/MODELS.md`. Vectorise masks to plan-map items. | Valid plan maps (schema check) for the 4 cubicasa fixtures. Time per image is recorded. |
| V-02 | 1 | D-04 | - | Baseline symbol detection: doors, windows, toilets, sinks, showers, bathtubs. Permissive licence only. | Plan maps for the cubicasa fixtures hold fixture items with boxes. |
| V-03 | 1 | V-01 | - | Rooms and scale: room polygons, room labels by OCR, scale from dimension text or a scale bar. If neither exists, use the door-width prior and set low confidence. Area per room. | `colorful-11397` has rooms with labels. `scale.method` and `confidence` are set on every fixture. |
| V-04 | 1 | V-02, D-03 | - | Vision evaluation: exact-count accuracy per kind and area error against the questions, on fixtures and on `sample200`. | `results/vision/baseline.json` exists with accuracy per kind. |
| V-05 | 2 | D-03 | - | LONG. Training data: download the official CubiCasa5K set, remove every sample in `cubicasa_heldout_ids.txt`, convert the SVG labels to masks and boxes, split train and validation. | A check proves zero overlap between training samples and held-out IDs. |
| V-06 | 2 | V-05, V-04 | MODAL_TOKEN_ID, MODAL_TOKEN_SECRET | LONG. Fine-tune the segmentation model on Modal. GPU cap: 2 hours. | `results/vision/seg_finetuned.json` shows before and after numbers on held-out data. |
| V-07 | 2 | V-05, V-04 | MODAL_TOKEN_ID, MODAL_TOKEN_SECRET | LONG. Fine-tune the detector on Modal. GPU cap: 2 hours. | `results/vision/det_finetuned.json` shows before and after numbers on held-out data. |
| V-08 | 2 | V-06 or V-07 | - | Export to ONNX. Run on the Mac. LONG: rebuild plan maps for all raster docs with the best models. | ONNX output matches the PyTorch output on 3 fixtures. Bench on `sample200` is not worse than before. |
| V-09 | 2 | V-04, E-01 | GEMINI_API_KEY or NVIDIA_API_KEY or RUNWARE_API_KEY | Verify step: geometry rules (a door sits in a wall; a window sits on an outer wall) plus a model check of low-confidence items on small crops. Cached. | Count accuracy on `sample200` rises or stays equal, and cost per drawing is logged. |
| V-10 | 2 | V-04 | - | Generalisation: test on swiss PNG, wikimedia, habs and finna samples. Add an abstain rule for low confidence. | `results/vision/generalisation.json` has accuracy and abstain rate per source. |
| V-11 | 3 | V-08 | as needed | Improve loop: take the weakest kind or source from the latest results, fix it, measure again. Repeat. | Each pass adds one line to `LESSONS.md` and a new results file. |

### ENGINE (Claude)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| E-01 | 1 | - | - | Model layer (5.6): `fake` provider, adapters, `models.yaml`, disk cache, cost log, budget caps, backoff. | Tests pass with `fake`. A call over the cap raises `BudgetExceeded`. A repeated call hits the cache. |
| E-02 | 1 | D-03 | - | Question parser: rules and a synonym table give `{type, kind, scope}` with no model call. | At least 90% correct on `router_test.jsonl`. |
| E-03 | 1 | E-02, D-06, D-07 | - | Solvers for count, area, length and volume over `elements.json` and plan maps. Build the answer object (5.7) with boxes, scene highlights, trace and cost. Numeric text from templates. | `ac20_arc`: doors 77, windows 206, walls 121. A hand-made plan map of `colorful-11397` gives 13 windows with 13 boxes. Cost of these answers is 0. |
| E-04 | 1 | E-03 | - | Public function `engine.answer(question, doc_ids, on_event)` that emits `status` and `trace` events and returns the answer object. Abstain with a plain sentence when data is missing or confidence is low. | An event test sees `status`, then `trace`, then `answer`. A question with no data returns `abstained: true`. |
| E-05 | 1 | E-04, D-03 | - | Bench: `python -m engine.bench --set sample200|full --tag <t> --max-usd <n>`. Scoring as in the dataset README. Results by source and type, with cost and latency per answer. Text answers are scored apart with `judge_text` and reported apart. | `results/bench/<tag>.json` and `docs/ACCURACY.md` are written. A run with `fake` models finishes in under 60 s on `sample200`. |
| E-06 | 1 | E-05, V-04 | - | Wire the vision plan maps into the solvers. Run `sample200`. | `results/bench/t1_planmap.json` exists. Numbers are whatever they are; record them. |
| E-07 | 1 | E-01 | NVIDIA_API_KEY (fallback RUNWARE_API_KEY) | Router fallback: questions the rules cannot parse go to a small Nemotron model through the model layer. | At least 95% correct on `router_test.jsonl` with rules plus model. Mean router cost per question is logged. |
| E-08 | 1 | E-04, D-05 | GEMINI_API_KEY (fallback RUNWARE_API_KEY) | Drawing-reading path for questions the plan map cannot answer: Gemini reads the page or crops and returns the answer with regions. Check each region against OCR or plan-map items before it becomes a citation. | A text question on a fixture returns an answer with at least one checked region. |
| E-09 | 1 | E-03 | ANTHROPIC_API_KEY (fallback RUNWARE_API_KEY) | IFC text questions in the IFC-Bench style: facts from `elements.json` go into a short written answer. Say plainly when the model lacks the data. | 10 IFC-Bench questions on `ac20_arc` run; the facts in each answer match `elements.json`. |
| E-10 | 1 | E-05..E-09 | any model key | LONG. Full bench, run 1. Then model comparison per task on `sample200` (Gemini, Nemotron, Runware-hosted models): pick the cheapest model that keeps accuracy, write it to `models.yaml`. | `results/bench/full_1.json` and `results/model_compare.json` exist. `COSTS.md` is updated. |
| E-11 | 2 | D-12, E-03 | - | Changes engine: compare two plan maps (and two page images as a fallback). Output a numbered change list with boxes and sentences in the form of 5.8. | On the 3 synthetic revisions, every true change is found. |
| E-12 | 2 | D-07, V-03 | - | Linked information: index of tags (door tags, room names and numbers, wall types). A click on a tag returns every place it appears and the IFC properties where they exist. | A lookup of an `ac20_arc` door returns its storey, type and properties. |
| E-13 | 2 | E-03 | - | Exit finder for "where is the fire exit on level N": outer doors, stairs, and names such as Exit, Ausgang, Notausgang, Treppe. Answer with highlights and a camera target. State that it is an inference from the model data. | The question on `ac20_arc` returns at least one item on the asked storey with a camera target. |
| E-14 | 3 | - | - | Rule library in `engine/rules/*.yaml`. Fetch real Finnish building rules in English (accessibility, escape routes). Each rule: id, plain text, source title, section, URL, quoted snippet, translation status, check ID. A rule with no verified URL and section is not allowed. | Every rule file passes a validator: URL returns 200 and the snippet is found in the fetched page or PDF. |
| E-15 | 3 | E-14, D-06 | - | Checks and findings: plain-code checks (door clear width, corridor width, level change with no ramp at an entrance, exits per storey). Findings carry item IDs, the rule and severity. Wording: "suggestion" unless the rule clearly fails. | Findings on `ac20_arc` each cite a rule from the library and at least one item. |
| E-16 | 3 | E-15 | NVIDIA_API_KEY (fallback RUNWARE_API_KEY) | Advisor: after an edit event, rerun the checks and return up to 3 short option cards, each with a source. No source means no card. Material options come only from a sourced material table. | An edit that narrows a door returns a card that cites a library rule. An edit with no rule returns no card. |
| E-17 | 3 | E-14, S-04 | CONTEXT_DEV_API_KEY | Watch loop: Context.dev monitors on the rule source URLs. A change webhook adds a `changes.new` entry and reruns the findings. Read their API documentation first. | A monitor exists for each rule URL. A test webhook creates a feed entry. |
| E-18 | 3 | E-04, D-15 | any model key | Skills (saved prompts, four starters as on the start screen) and automations (a prompt on a schedule that posts a report). Report export as Markdown and PDF. | A skill runs on a chosen document. A scheduled automation writes one report. |
| E-19 | 3 | E-10 | as needed | Improve loop: take the weakest source and type cell from the latest bench, fix it, rerun `sample200`. Full bench runs 2 to 4 only when `sample200` improved. | Each pass adds one line to `LESSONS.md` and a new results file. |

### SERVER (Claude)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| S-01 | 1 | - | - | Scaffold `server/`, `deploy/`, `Makefile`, Docker compose with local Postgres. `make dev` also starts the web dev server once `web/` exists. | `make dev` serves `/api/health`. `make test` runs. |
| S-02 | 1 | S-01, D-02 | - | Database schema and migrations. Seed documents from `artifacts/registry.jsonl`. | Migrations apply on an empty database. `/api/docs` lists the preview docs by source. |
| S-03 | 1 | S-02 | - | All tier 1 endpoints of 5.9 with the `fake` provider and a stub engine that returns contract-valid answers for the fixtures. Publish `docs/API.md` with one example request and response per endpoint. This unblocks the Codex side early. | Contract tests pass for each endpoint. A streamed question returns `status`, `trace`, `answer`. |
| S-04 | 1 | S-03, E-04 | - | Replace the stub with the real `engine.answer`. Upload starts real ingestion. | A fixture question through the API returns the same answer as a direct engine call. |
| S-05 | 1 | S-04, W-05, W-06, T-04 | DATABASE_URL, AIVEN_TOKEN, Vercel login | Deploy: server container to Aiven Runtime next to Aiven PostgreSQL (EU region), web to Vercel. Rate limit on. Write the URLs to `STATE.md`. | The deployed URL answers a fixture question end to end. |
| S-06 | 2 | S-03 | - | Live sync: PostgreSQL `LISTEN/NOTIFY` to WebSocket `/ws`. Events of 5.9, including `scene.highlight`. | A test with two WebSocket clients: an event sent by A reaches B in under 2 s. |
| S-07 | 2 | S-04, E-11 | - | Changes endpoints backed by the changes engine. | `/api/changes` lists the synthetic revisions with their numbered changes. |
| S-08 | 2 | S-04 | ELEVENLABS_API_KEY | `/api/tts` through the model layer (ElevenLabs; the client falls back to device speech when the key is missing). Speech-to-intent endpoint through Gemini. | With the key: audio is returned. Without the key: a clear `fallback` response. |
| S-09 | 3 | E-15, E-16, E-18 | - | Endpoints for findings, advisor, skills and automations. | Contract tests pass. |

### WEB (Codex)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| W-01 | 1 | - | - | Scaffold `web/` (Vite, React, TypeScript, Tailwind v4, lucide-react). Tokens from the reference pack. Until S-03 is done, use a local mock that serves the contract examples. | The dev server starts and the build passes. |
| W-04 | 1 | W-01 | - | App shell from the reference pack: sidebar, layout, type, colours, controls. Our own wordmark. | A Playwright test finds the nav items and checks 10 CSS variables against `theme-tokens.css`. |
| W-05 | 1 | W-04, S-03 | - | Chat screen: start screen with four starter cards, composer with `@` document picker, live status lines, answer with bold fact, citation chips, "Where it is set out", "Sources (n)", "Show thought process", cost chip, and the notice from 5.8. | A Playwright test asks a fixture question and sees the answer, the citation chips and the cost chip. |
| W-06 | 1 | W-05 | - | Document viewer beside the chat: pan and zoom, numbered boxes, text highlight, "n of m" source navigation, licence credit line. A click on a chip opens the right page and box. | A Playwright test clicks chip 1 and sees the viewer with the box in view and the credit line. |
| W-07 | 1 | S-03, W-04 | - | Data screen: folders by source, file list with format badges, upload. | A Playwright test opens a folder and a file. An upload of a fixture PNG creates a doc. |
| W-08 | 1 | S-03, W-04 | - | Accuracy and cost dashboard: latest bench by source and type, before and after fine-tuning when present, cost per answer, model switcher. | The screen renders numbers that equal the API response. |
| W-10 | 2 | S-06, W-05 | - | Live sync in the client: chats, messages and status lines update from `/ws` on every open device. | A test with two browser contexts: a message sent in A shows in B in under 2 s. |
| W-11 | 2 | W-05, W-06 | - | Mobile layout with bottom tabs (Overview, Chat, Changes, Data, More) and the "Show on table" button that calls the bridge of 5.10. | A Playwright test at phone size sees the tabs. The bridge call fires with `doc_id` and `item_ids`. |
| W-12 | 2 | S-07, W-06 | - | Changes screen: feed (new versions, new documents), comparison with Plain, Wipe and Overlay, change boxes, numbered change list. | A Playwright test opens a synthetic revision and sees the numbered changes and the wipe handle. |
| W-13 | 2 | E-12, W-06 | - | Linked codes: tags on the drawing are clickable and open the related places and properties beside the plan. | A click on a door in an `ac20_arc` storey plan shows its properties. |
| W-14 | 2 | S-08, W-05 | - | Voice in the client: play the spoken answer, with browser speech as fallback. Microphone input. | With the key: audio plays. Without the key: the fallback speaks. |
| W-15 | 3 | W-04 | - | Overview screen: this week's changes, open findings, latest answers, bench summary. | The screen renders with real data from the API. |
| W-16 | 3 | S-09 | - | Skills and Automations screens. | A skill can be picked from the composer. An automation can be created and shows its last report. |
| W-17 | 3 | S-09 | - | Findings list and advisor cards. Each card shows its source. | A finding click highlights its items in 2D and 3D. |

### 3D (Codex)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| T-01 | 1 | W-01, D-06 | - | Viewer: load `scene.glb` through `scene.json`, orbit, storey filter, pick an item to get its `item_id`. | A unit test resolves 5 `item_id`s to nodes. A Playwright test (software GL) shows a non-blank canvas. |
| T-02 | 1 | T-01 | - | Highlight API: `highlight(item_ids)` makes items glow, dims the rest, shows the same number labels as the 2D boxes, and flies the camera to the target. | A unit test checks highlight state. A screenshot differs from the unhighlighted one. |
| T-03 | 1 | T-02, W-06 | - | 2D and 3D side by side, linked: hover or click a box and the 3D item responds, and the reverse. | A Playwright test clicks box 3 and reads highlight state for the same `item_id`. |
| T-04 | 1 | T-02, D-09 | - | "Visualise it": a button on any answer or document. It requests the scene, shows the plan flat, raises the walls, keeps the answer highlighted. | A Playwright test presses the button on the `colorful-11397` window answer and reads 13 highlighted items. |
| T-05 | 1 | T-01 | - | ◆ Tap to identify: a click on an item opens a card with its name, kind, storey and properties. | A click on an `ac20_arc` door shows its name and storey. |
| T-06 | 2 | T-02, S-06 | - | Follow `scene.highlight` from the WebSocket, and send it when the user changes the highlight. | Two browser contexts stay in step. |
| T-07 | 2 | T-01 | - | Performance for large models: mesh compression and instancing where needed. | The largest safe demo model orbits smoothly on the Mac; frame time is recorded. |
| T-08 | 3 | T-05, E-16 | - | Edit mode: move or remove an item, change a wall material. Each edit sends an event to the advisor and shows its cards. | An edit produces an advisor request and renders a returned card. |
| T-09 | 3 | E-15, T-02 | - | Findings pins in 3D, red or amber, with tap to explain. | A finding on `ac20_arc` shows a pin at its item. |
| T-10 | 3 | T-01 | - | ◆ First-person walk mode in the browser. | The camera moves at eye height inside the model. |

### IOS (Codex)
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| I-01 | 2 | - | - | Xcode project with XcodeGen. SwiftUI shell with a WKWebView that loads `WEB_URL` (local dev URL until deploy). | `xcodebuild` builds for the simulator. |
| I-02 | 2 | I-01, D-10 | - | AR screen with RealityKit: find a flat surface, place `scene.usdz` (a bundled fixture scene as fallback), pinch to scale, rotate, drag, a scale slider from 1:100 to 1:1, reset. | The build succeeds. A unit test loads the fixture USDZ and finds a prim by `usd_name`. |
| I-03 | 2 | I-02 | - | Highlight in AR: glow the answer items, dim the rest, show the number labels. | A unit test applies a highlight to named entities of the fixture scene. |
| I-04 | 2 | I-03, W-11 | - | Bridge and live link: "Show on table" from the web view opens AR with the right doc and items. The AR screen follows `scene.highlight` from `/ws`. | A test message through the bridge handler opens the AR screen with the given `doc_id`. |
| I-05 | 2 | I-04 | APPLE_TEAM_ID | Install on the connected iPhone and launch. If signing or the device fails, write the exact manual steps to `MORNING.md` and set `blocked-human`. | The app is installed on the device, or the manual steps are written. |
| I-06 | 2 | I-03 | - | Walk mode at 1:1: floor alignment, a small "you are here" map, and a guide arrow to the highlighted item. | The build succeeds; the guide logic has a unit test. |
| I-07 | 3 | I-04, S-08 | - | Voice in AR: a button to ask by speech; the spoken answer plays. | The speech request reaches the chat endpoint in a test. |
| I-08 | 3 | I-03 | - | Tap to identify in AR. | A tap on an entity returns its `item_id` and shows the card. |
| I-09 | 3 | I-04, E-16 | - | Advisor cards in AR. | A card from the API renders in the AR overlay. |

### LEAD
| ID | Tier | Depends | Keys | Task | Done test |
|---|---|---|---|---|---|
| X-01 | 1 | E-10 | - | README: what it is, how to run, architecture, accuracy and cost numbers from `results/`, dataset and model credits, licences, the Stoa permission line. | README exists; every number in it appears in a `results/` file. |
| X-02 | 3 | features done | - | ◆ `docs/sponsors/`: one page per tech challenge (Gemini, Nemotron, ElevenLabs, Modal, Cloudinary, Context.dev, Aiven, Codex). What the tool does in the app, where in the code, one screenshot path. Write a page only for a tool that really runs in the app. | One file per integrated tool. |
| X-03 | 2 | S-05 | - | `docs/DEMO.md`: the demo script (section 12) with the exact questions and documents that work best by test results, and a 2-minute video shot list. | The file names real doc IDs and questions that pass in the app. |
| X-04 | 3 | X-01 | - | ◆ Draft the submission fields: project name, punchline, description, tech used, challenge list. | `docs/SUBMISSION.md` exists. |
| X-05 | - | every hour | - | Update `MORNING.md` (section 13). | The file is current at 08:30. |

---

## 8. Data rules for training and testing

1. Build `heldout_docs.txt` and `cubicasa_heldout_ids.txt` (row D-03) before any training.
2. Training code must load the held-out list and assert zero overlap. No assert, no training.
3. Pretrained models may have seen test drawings in their own training. Record what is known in `docs/MODELS.md`. Report bench results per source, so a reader sees the sources a model has never seen.
4. Router data is split by drawing, not by question.
5. Report before and after numbers for each fine-tuned model on held-out data only.
6. Use `sample200` for fast checks. Full bench at most 4 times per run.

---

## 9. Keys that arrive during a run

- `.env.example` lists every name. Ash fills `.env` in his own time.
- Names: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `RUNWARE_API_KEY`, `FEATHERLESS_API_KEY`, `HF_TOKEN`, `ELEVENLABS_API_KEY`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `CLOUDINARY_URL`, `CONTEXT_DEV_API_KEY`, `DATABASE_URL`, `AIVEN_TOKEN`, `AIVEN_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`, `DRIVE_FOLDER_ID`, `APPLE_TEAM_ID`.
- `scripts/check_keys.py` reads `.env` fresh, makes one small real call per present key, and prints `OK`, `MISSING` or `FAILED` per key. It also writes `results/keys.json`. It never prints a key.
- A row whose keys are `MISSING` has status `waiting-key`. It is not blocked and it costs no attempts.
- The lead runs `check_keys.py` every 10 minutes. When a key turns `OK`, its waiting rows become `todo`.
- A `FAILED` key gets one line in `MORNING.md` for Ash.
- Where a row names a fallback key, use the fallback when the first key is missing.

---

## 10. The lead loop (PHASE B)

**The pulse: one pass of this loop every 60 seconds.**
- Start every worker as a background process, so the lead never waits for one worker to finish. Codex workers: `codex exec` in the background with output to `logs/<WORKER>.log`. Claude workers: background subagents; if this Claude Code version cannot run a subagent in the background, start them as separate headless Claude Code processes with output to `logs/<WORKER>.log`.
 It also prints memory pressure, swap in use and free disk (section 3).
- Each pass: run `pulse.py`, act on it, then `sleep 60` if there is nothing else to do. One pass must take less than 60 seconds of lead work. Long checks belong to workers, not to the lead.
- A worker is **idle** when it has no running process. Give it its next row in the same pass.
- A worker is **stuck** when its process is alive but it has no file change and no log line for 15 minutes. Stop it, write the last log lines into its handoff file or prompt, and restart the row. This counts as an attempt.
- If all 7 workers are busy and healthy, the pass ends at once. Do not invent work for the lead.

Repeat until Ash returns with a new instruction, or until the Sunday freeze:

1. `date`. If it is after 07:00 on Sunday 15 Nov, go to step 8.
2. Read `TASKS.md`. For each worker, find its next row: lowest tier first, dependencies done, keys present.
3. Start every worker that has no running row: Claude workers as subagents, Codex workers through `codex exec` with their handoff file (section 6). No worker is idle while a row is available. If a worker has nothing, give it an improve row (V-11, E-19) or add a new row.
4. For each row that a worker reports as finished, run the done test yourself. Pass: set `done`, commit that worker's folders. Fail: send it back with the error (counts as an attempt).
5. Every 10 minutes: run `check_keys.py`, release waiting rows, check LONG jobs.
6. Every hour: read `results/costs.jsonl` against the caps, update `COSTS.md`, update `MORNING.md`, write one line to `STATE.md`.
7. When a test result shows a real problem (for example a kind with low accuracy), add a row for it. Record why in `DECISIONS.md`.
8. Sunday freeze (07:00 on 15 Nov only): no new features. Fix only what the demo script needs. Make sure the deployed app works. Finish `README`, `docs/DEMO.md`, `MORNING.md`. Stop at 08:30.

In run 1 there is no freeze. If every row is done or blocked before Ash returns, add improve rows: raise accuracy on the weakest bench cell, polish the demo path of section 12, and test the app on more drawings from the full dataset.

---

## 11. Project files to create in PHASE A

| File | Content |
|---|---|
| `CLAUDE.md` | Short entry point every agent reads first: mission (section 1), fixed decisions (2), rules (4), where each file is. Under 150 lines. Points to the other files. |
| `AGENTS.md` | Codex reads this file by default. Start with the rules of section 4 in short form and a pointer to `CLAUDE.md`, then section 6. |
| `CONTRACT.md` | Section 5, version 1. |
| `TASKS.md` | Section 7 with `Status` and `Notes` columns. Status values: `todo`, `doing`, `done`, `blocked`, `waiting-key`, `blocked-human`. |
| `handoff/WEB.md`, `handoff/3D.md`, `handoff/IOS.md` | One handoff file per Codex worker (section 6). Start with an empty template. |
| `DECISIONS.md` | Seeded with section 2, one line each. New lines: time, decision, reason. |
| `LESSONS.md` | Empty. What worked and what failed. |
| `GOTCHAS.md` | Seeded with: 24 GB memory: heavy jobs go through `scripts/heavy.sh`, no training on the Mac; IfcConvert drops IfcSpace and openings unless included; GLB holds no names or storeys; GlobalIds are not valid USD prim names; index build must reuse GLB boxes; `ultralytics` and `PyMuPDF` are AGPL; ND-licensed models must not be published; the questions file has Finnish copies; Vercel cannot hold WebSockets; AR does not run in the simulator. |
| `COSTS.md` | Caps for run 1 (edit freely; the lead may not raise them, only Ash): Runware 300 USD, Anthropic 15 USD, Gemini 20 USD, Modal 80 USD, ElevenLabs 5 USD, Context.dev 10,000 credits, NVIDIA free tier with backoff. Then the hourly spend table. |
| `STATE.md` | Paths found, tool versions, preflight table, hourly one-line log. |
| `MORNING.md` | Template of section 13. It is the report for the end of each run. |
| `docs/MODELS.md`, `docs/ACCURACY.md`, `docs/API.md`, `docs/DEMO.md`, `docs/sponsors/` | Start empty with a title. |
| `.env.example`, `.gitignore`, `LICENSE` (MIT, "2026 Team RS3") | As described. |

---

## 12. The demo the build must produce

1. The judge opens the web app. It looks and reads like Stoa's product.
2. The judge asks a count question about a raster floor plan. Status lines run. The answer appears with the key fact in bold and citation chips.
3. A click on a chip opens the drawing with numbered boxes. The judge checks the answer in seconds. The cost chip shows a tiny number.
4. "Visualise it": the plan rises into 3D. The same numbered items glow.
5. The judge picks up the iPhone. The same chat is there. "Show on table": the building stands on the table with the same items glowing.
6. On the IFC building: "Where is the fire exit on level 2?" The camera flies there. At 1:1 scale the judge walks to it.
7. The dashboard: accuracy by source and type on the question set, before and after fine-tuning, and cost per answer.
8. If tier 3 is done: remove a ramp or narrow a door in 3D, and a sourced suggestion card appears.

---

## 13. `MORNING.md` template (kept current every hour)

1. **What works** (one line per demo step of section 12: works / partly / no).
2. **Numbers:** accuracy by source and type, cost per answer, fine-tune before and after. Each with its `results/` file.
3. **Deployed URLs.**
4. **Rows blocked,** with one line each.
5. **Keys that failed.**
6. **What Ash must do by hand next:** keys still missing, logins, install or trust the iOS app, test AR on a table, run the demo script once. Before Sunday 10:00: record the 2-minute video, fill the submission form, switch DRAFT to FINAL, join peer review 10:30 to 14:00.
7. **Proposed plan for the next run:** the rows to do next, in order, and any decision that needs Ash.
8. **Known weak spots** to avoid in the live demo.

---

## 14. PHASE A steps (do these now)

1. Confirm the paths of section 3. Record them in `STATE.md`.
2. If `.git` is missing, run `git init`. Add `LICENSE`, `.gitignore`, `.env.example`.
3. Copy the Stoa reference pack to `refs/stoa-hero/` and `stoabuild-full-text.md` to `refs/`. Confirm `refs/` is ignored by git.
4. Write every file of section 11 from this prompt. Save this prompt itself as `docs/MASTER_PROMPT.md`.
5. Write `scripts/check_keys.py` (section 9), `scripts/pulse.py` (section 10), `scripts/heavy.sh` (section 3) and `scripts/preflight.py`. The preflight prints one table with `OK`, `MISSING` or `FAILED` for:
   - Paths: repo, dataset with `questions.jsonl`, spike output, `tools/IfcConvert` runs, `refs/stoa-hero/`, `refs/stoabuild-full-text.md`.
   - Tools: git, python 3.12, uv, node 20 or later, docker running, xcodebuild, xcodegen, gh, vercel, modal, codex (run one trivial `codex exec` to prove it works unattended), Aiven CLI.
   - Logins: `gh auth status`, Vercel, Modal, Codex, Aiven.
   - Disk: at least 60 GB free.
   - Machine: chip, memory and macOS version (expected: M4 Pro, 24 GB).
   - iPhone: a connected, trusted device is listed.
   - Keys: the output of `check_keys.py`.
6. Run the preflight. Commit: `PREP: repo, docs, preflight`.
7. Print the preflight table, then a short list titled "Ash, before you send /goal" with only the items that need a human: missing tools or logins, permission mode for unattended runs, `caffeinate -dims`, charger, iPhone cable.
8. Print the `/goal` line below. Then STOP. Do not start PHASE B until Ash sends it. Missing API keys do not hold PHASE B back.

**The `/goal` line for Ash to send:**

```
/goal Follow CLAUDE.md and work through TASKS.md as the LEAD agent, in tier order, using the lead loop in docs/MASTER_PROMPT.md section 10. Run 4 Claude workers (DATA, VISION, ENGINE, SERVER) as subagents and 3 Codex workers (WEB, 3D, IOS) through codex exec with their handoff files. You run every done test and make every commit. Never ask me anything; record decisions in DECISIONS.md. Keys arrive in .env during the run: recheck every 10 minutes. This is run 1 of several: there is no deadline tonight, so work in tier order and do each row properly. The goal is reached when every Tier 1 done test passes, the app is deployed if the deploy keys are present, and every Tier 2 and Tier 3 row is done or blocked with a reason. Pulse every 60 seconds with scripts/pulse.py: no Claude or Codex worker may be idle while a row is available, and restart any worker that is stuck for 15 minutes. Until the goal is reached keep every worker busy and keep MORNING.md current every hour.
```
