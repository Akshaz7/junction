# CONTRACT — version 2

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
