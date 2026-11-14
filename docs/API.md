# API (S-03, stub engine)

Base: `http://localhost:8000`. All JSON unless noted. Errors: `{"detail": "..."}`; missing artifacts return
`404 {"status": "not_built", "detail": "..."}`. DB-backed endpoints return `503` if Postgres is down.
Answers come from `server/stub_engine.py` until S-04 (the trace is marked `"stub": true`).
The only question the stub answers is "how many windows" on `cubicasa5k__colorful-11397` (13 fake boxes);
anything else returns a valid abstained answer.

### GET /api/health
`curl localhost:8000/api/health` -> `{"ok": true, "db": true}`

### GET /api/docs
-> `{"total": 1, "sources": [{"source": "cubicasa5k", "count": 1, "docs": [{"doc_id": "cubicasa5k__colorful-11397", "source": "cubicasa5k", "title": "...", "kind": "raster", "formats": ["png"], "pages": 1, "licence": "CC BY-NC-SA 4.0", "credit": "...", "heldout": false, "files": {"png": "data/cubicasa5k/..."}}]}]}`

### GET /api/docs/{doc_id}
`curl localhost:8000/api/docs/cubicasa5k__colorful-11397` -> one doc object (as above). 404 if unknown.

### GET /api/docs/{doc_id}/pages/{n}/image
`curl -o p.png localhost:8000/api/docs/cubicasa5k__colorful-11397/pages/1/image` -> `image/png`
(`artifacts/<doc_id>/page-<n>.png`). Else `404 {"status":"not_built"}`.

### GET /api/docs/{doc_id}/planmap/{n}
-> plan map JSON (CONTRACT 5.4) from `planmap-<n>.json`, e.g. `{"doc_id": "...", "page": 1, "image": {"w": 1200, "h": 900}, "scale": {...}, "items": [...]}`. Else not_built.

### GET /api/docs/{doc_id}/scene
-> `scene.json` (CONTRACT 5.5). Else `404 {"status": "not_built"}` (S-04 will trigger extrusion).

### GET /api/docs/{doc_id}/files/{name}
`name` is `scene.glb`, `scene.usdz`, `scene.json` or `page-<n>.thumb.png`. Returns the file bytes. Other names 404.

### POST /api/upload
`curl -F file=@plan.pdf localhost:8000/api/upload`
-> `{"doc_id": "uploads__plan-3fa2b1", "status": "stored", "detail": "ingestion not started (S-04)"}`
Accepts ifc, dxf, dwg, pdf, svg, png, jpg, tif (max 100 MB; 415 otherwise). Stored in `artifacts/uploads/`; a documents row is inserted (source `uploads`).

### POST /api/chats
`curl -X POST localhost:8000/api/chats -H 'content-type: application/json' -d '{"doc_ids":["cubicasa5k__colorful-11397"],"title":"Windows"}'`
-> `{"id": "<uuid>", "doc_id": "cubicasa5k__colorful-11397", "title": "Windows", "created_at": "2026-11-14T03:00:00+00:00"}`
(only the first doc_id is stored on the chat; unknown doc -> 404).

### GET /api/chats
-> `{"chats": [{"id": "<uuid>", "doc_id": "...", "title": "...", "created_at": "..."}]}` newest first.

### GET /api/chats/{id}
-> chat plus `"messages": [{"id", "role": "user|assistant", "content", "created_at", "answer": null | <answer object 5.7>}]`.

### POST /api/chats/{id}/messages
`curl -N -X POST localhost:8000/api/chats/<id>/messages -H 'content-type: application/json' -d '{"content":"How many windows are there?"}'`
Optional `"doc_ids"` overrides the chat's doc. Response is `text/event-stream`:
```
event: status
data: {"text": "Thinking…"}

event: status
data: {"text": "Exploring document: cubicasa5k__colorful-11397"}

event: trace
data: {"step": "route", "detail": "stub engine: no real routing", "ms": 1, "model": null, "cost_usd": 0, "stub": true}

event: answer
data: {"answer_id": "...", "question": "How many windows are there?", "doc_ids": ["cubicasa5k__colorful-11397"],
       "answer": {"text_md": "There are **13 windows** on this floor plan. [1]", "value": 13, "unit": "count", "confidence": 0.5, "abstained": false},
       "citations": [...], "evidence": {"boxes": [{"item_id": "window-001", "page": 1, "bbox_px": [40,40,90,56], "label": "1"}, ...], "scene": {...}},
       "trace": [...], "route": "planmap", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": 2}
```
`status` and `trace` events repeat; `answer` is always last. If the engine fails an `error` event `{"detail": ...}` ends the stream. The user message and the answer are stored.

### GET /api/changes, GET /api/changes/{id}
-> `{"changes": []}` (empty until the changes engine writes rows). One change: `{"id", "doc_a", "doc_b", "summary", "created_at"}`; 404 if unknown.

### GET /api/bench/latest
-> `{"file": "run1.json", "data": {...}}` from the newest `results/bench/*.json|jsonl`. 404 `{"status": "no_bench"}` if none.

### GET /api/costs
-> `{"total_usd": 0.035, "calls": 3, "by_provider": {"gemini": {"calls": 2, "usd": 0.03}}, "by_task": {"read_drawing": {"calls": 2, "usd": 0.015}}}` from `results/costs.jsonl` (fields `provider`, `task`, `cost_usd`).

### Not yet
`POST /api/tts` and findings/advise (tier 3).

### WS /ws (live sync, S-06)
`ws://localhost:8000/ws` (use `wss://` when deployed). Server-to-client events are small JSON objects; refetch the thing they name.
```
{"type": "chat.message", "chat_id": "<uuid>", "message_id": "<uuid>", "role": "user|assistant"}   // refetch GET /api/chats/{id}
{"type": "chat.status",  "chat_id": "<uuid>", "text": "Thinking…"}                                // same lines as the SSE status events
{"type": "scene.highlight", "doc_id": "...", "item_ids": ["window-001", "window-002"]}
{"type": "doc.new", "doc_id": "uploads__plan-3fa2b1"}                                              // refetch GET /api/docs
{"type": "changes.new", "id": "<uuid>"}                                                           // refetch GET /api/changes
{"type": "ping"}                                                                                    // every 20 s; any reply is optional
```
Client-to-server: `{"type": "scene.highlight", "doc_id": "...", "item_ids": [...]}` is re-broadcast to every client, including the sender
(web 3D viewer and iOS AR follow it). `{"type": "ping"}` gets `{"type": "pong"}`. Other types are ignored.
Mechanism: writers call `pg_notify('hologram_events', ...)`; each server process holds one LISTEN connection and fans out to its sockets
(works across several server instances; reconnects after a drop). `changes.new` comes from a DB trigger, so any writer of `changes` fires it.
Without a database the server broadcasts to its own sockets directly. Delivery is well under 2 s.
