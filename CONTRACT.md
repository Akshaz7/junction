# CONTRACT — version 3.5

Only the LEAD edits this file. Each change bumps the version and adds one line to DECISIONS.md.


All workers build against this contract. If something is unclear, the lead decides and bumps the version.

### 5.1 IDs
- `doc_id`: `<source>__<file stem>`: source folder name verbatim, file stem lowercased with non-alphanumerics replaced by `-` (v2 clarification). Example: `ifc_bench__ac20-arc`. Files with the same stem in one source share one `doc_id` and are listed as `formats`.
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
| `doc.json` | `doc_id`, `source`, `formats[]`, `files` {format: path relative to dataset root} (v2), `kind` (raster, pdf, dxf, dwg, ifc, svg), `title`, `pages`, `licence`, `credit`, `heldout` (bool) |
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

### 5.11 Scene commands and tags (v3)
- `scene.json items[item_id].tag`: short stable tag per doc. IFC mark when present (e.g. door "T12"), else kind letter + number in reading order: W1.. windows, D1.. doors, R1.. rooms, WL1.. walls, WC1.. toilets, S1.. sinks, SH1.. showers, B1.. bathtubs. Unique within a doc.
- Answer object: `evidence.scene.commands`: list of `{op, item_ids, labels?}` with `op` ∈ `highlight` | `hide` | `restore` | `reset` | `isolate`. `labels` maps item_id → tag/number shown above the item.
- WebSocket event `scene.edit`: `{type:"scene.edit", doc_id, chat_id?, op, item_ids, labels?, edit_id, ts}`. Clients apply it in order; `reset` restores everything for that doc. Server persists the per-chat edit layer and sends `{type:"scene.state", doc_id, hidden:[item_ids], highlighted:[...], labels:{...}}` to a client when it joins or calls `GET /api/chats/{id}/scene-state`.
- Edits never change source data; counts after an edit carry a note ("with W7 hidden").

### 5.12 Advisor cards (v3.1)
`POST /api/advise` {doc_id, chat_id?, edit?: {op, item_ids}} → `{cards: [Card]}`, at most 3. Also pushed over `/ws` as event `advisor.cards` {doc_id, chat_id, cards}.
Card: `{card_id, kind: "warning"|"option"|"info", title (≤60 chars), body (≤200 chars, voice guide 5.8), item_ids: [item_id], source: {type: "rule"|"material_table"|"document", ref (rule id / table row / doc_id+page), title, quote (≤200 chars, verbatim)}}`.
Hard rule: no `source` → no card. Never invented. Clients show the source title and quote with the card, and highlight `item_ids` like a citation.

### 5.13 Additions in v3.2 (multi-kind answers, severity, locate)
Answer object (5.7), all optional:
- `answer.value`: a number, or for a multi-kind count ("how many windows and doors") an object `{kind: count}`, e.g. `{"window": 11, "door": 11}`; unit "count". `text_md` carries both counts.
- `evidence.boxes[].kind`: kind of the boxed item. Labels run 1..N across all kinds; clients colour by kind (shared table `web/public/kind-colors.json`).
- `evidence.scene.item_kinds`: `{item_id: kind}` for highlighted items; 3D and AR colour by it.
- `citations[].item_kind`: kind of the cited items in a multi-kind count.
- `advisor_cards` (max 3): cards for a hide/remove command in chat, computed on the edited model (all hidden in the chat so far plus this command); also published as `advisor.cards` over `/ws`.
- Forced best-effort answers use route `hybrid`, with low confidence and one line saying what they rest on.
Advisor cards (5.12) gain:
- `severity`: "violation" (rule broken; kind warning), "suggestion" (worth checking; kind option) or "info" (nothing broken or nothing checkable). Clients show severity.
- `checked`: rule ids from engine/rules checked for this result. A clean edit still returns one info card, "No rule broken by this edit" (body "Checked: <decree §>"). Raster/DXF drawings get "Checks need an IFC model" unless an entrance door was detected.
- Rule library adds engine/rules/safety_in_use.yaml (1007/2017 §3, 4, 6, 7, 14, 15). English quotes are the ministry's unofficial translation (labelled); the Finnish Finlex quotes are verified. 848/2017, 241/2017 and 1007/2017 stay in force under Act 752/2023.
- `POST /api/advise` edit: `{op: hide|restore|move|material|undo, item_ids, detail?}`.
Scene commands: "front door / main door / entrance" selects the one detected entrance door; "outer / exterior / exit doors" selects all detected outer doors.
Routes: "where is the stairs / stair core / lift / entrance (on level N)" is a code route (engine/locate.py), cost 0, route "index".
Live sync: `/ws` also carries `chat.trace`, `chat.delta` (cumulative answer text, ≤8/s) and `chat.done`. `GET /api/chats/{id}` returns `active` (statuses, traces and text so far) for an in-flight question.

### 5.14 Scene open hint (v3.3)
- `evidence.scene.open`: optional, `"3d"` or `"ar"`. Set by app-feature answers ("show it in 3D", "show on table"). Web: `"3d"` opens Visualise it for the answer's doc; `"ar"` shows the Show-on-table hint (iOS app). Absent means no action. Additive; older clients ignore it.

### 5.14 Additions in v3.4 (versions, shared edits, projects)
- Advisor card `source` gains optional `url` and `finnish_url` (links to the rule text); clients show them when present.
- Design versions (migration 006): `GET/POST /api/docs/{doc_id}/versions` (POST stores the current edit snapshot as version n, parent-linked, "generated from edits"), `GET /api/docs/{doc_id}/versions/{n}/pages/{page}/image`. `/api/changes` ids may be `dv:<doc>:<a>-<b>` (design versions) or `ser:<...>` (series); comparison objects gain optional fields (shapes in `server/design_versions.py`, `engine/design_versions.py`).
- Shared edit layer: manual 3D edits carry `chat_id` and land in the chat's `scene_edits`; `scene_state` gains `last_hidden` (ids of the most recent hide, for "restore them"); `POST /api/advise` edit ops add `reset`. Pending move/material ops are stored in the chat edit layer (migration 008_scene_edit_moves).
- Scene commands (5.11) gain two ops: `move` {offset_m:[dx,dz]} (metres from the original spot, world X/Z; [0,0] = back in place) and `material` {material: name|null}. `scene.state` gains optional `moved` {item_id:[dx,dz]} and `materials` {item_id:name}, sent only when non-empty; `reset` clears them.
- Projects (migration 007): `GET/POST /api/projects`, `GET/PATCH/DELETE /api/projects/{id}`, `POST /api/projects/{id}/docs`, `POST /api/projects/{id}/upload`, `PATCH/DELETE /api/projects/{id}/docs/{doc_id}`, `GET /api/projects/{id}/overview`. Demo projects (AC20 Institute, FZK-Haus) are seeded from library docs and flagged `demo: true`.
