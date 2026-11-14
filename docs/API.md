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
`name` is `scene.glb`, `scene.usdz`, `scene.json`, `elements.json` (IFC element index), `planmap-<n>.json`, `page-<n>.png` or `page-<n>.thumb.png`. Returns the file bytes; 404 `{"status":"not_built"}` if the file does not exist yet. Other names 404.

### POST /api/upload
`curl -F file=@plan.pdf localhost:8000/api/upload`
-> `{"doc_id": "uploads__plan-3fa2b1", "status": "ingesting", "detail": "..."}` (`"stored"` on a server without the pipeline, e.g. the deployed container).
Accepts ifc, dxf, dwg, pdf, svg, png, jpg, tif (max 100 MB; 415 otherwise). Stored in `artifacts/uploads/`; a documents row is inserted (source `uploads`) and `doc.new` fires. Where the pipeline is installed, a background job then builds pages, plan map, scene and USDZ (raster about 6 s, DXF seconds, IFC minutes), one job at a time, and fires `doc.new` again when done.

### GET /api/docs/{doc_id}/ingest
-> `{"status": "none|running|ready|partial|failed", "stages": [{"stage": "pages", "ok": true, "s": 0.1}], "detail": ""}`. `partial` = page image only (pdf/svg have no plan map yet).

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

### GET /api/changes, GET /api/changes/{id} (S-07)
Feed, newest first: `{"changes": [{"id", "type": "new_version"|"new_document", "doc_a", "doc_b", "summary", "created_at"}]}`.
`new_version`: `doc_a`/`doc_b` are `<doc_id>@v1` / `<doc_id>@v2`, `summary` = `{"doc_id", "source", "generated_for_demo", "n_changes", "headline"}`. `new_document`: an upload (`id` is `doc:<doc_id>`, no detail view). Rows are seeded at server start from the revisions on disk, and `changes.new` fires on each insert.
One comparison (`new_version` ids only; 404 otherwise):
```
{"id": "<uuid>", "type": "new_version", "doc_id": "swiss_dwellings__site289-bldg536-floor2149",
 "source": "truth", "generated_for_demo": true, "image": {"w": 1583, "h": 3000},
 "v1": {"label": "v1", "page_image": "/api/docs/<doc_id>/revisions/v1/page-1.png", "thumb": ".../page-1.thumb.png", "planmap": ".../planmap-1.json"},
 "v2": {...},
 "changes": [{"n": 1, "change_id": "c1", "type": "removed|added|modified", "kind": "wall|door|room|...",
              "sentence": "Wall 14 (3.1 m long) reads absent where it read present.",
              "v1": {"item_id": "wall-14", "bbox_px": [798, 1228, 819, 1498]}, "v2": null,
              "field": null, "old": null, "new": null}]}
```
`n` numbers the boxes on both pages; `bbox_px` is in the shared page-image pixel frame (same frame in v1 and v2). A side is `null` when the item does not exist in that version. Sentences follow CONTRACT 5.8: `The area of room 205 reads 47.0 m2 where it read 23.5 m2.`
`source` is `"truth"` (DATA's synthetic revisions, generated for demo) until E-11's `engine.changes.compare(doc_id, revision_dir)` exists; then `engine` (override with env `CHANGE_SOURCE=truth|engine`).

### GET /api/docs/{doc_id}/revisions/{vN}/{name}
`name` is `page-<n>.png`, `page-<n>.thumb.png` or `planmap-<n>.json`; `vN` matches `v<digits>`. Other names 404; a missing file 404 `{"status":"not_built"}`.

### GET /api/bench/latest
-> `{"file": "fake200.json", "tag": "fake200", "data": {set, tag, fake, totals, cells}}`: the newest summary `results/bench/<tag>.json`. The `<tag>.rows.jsonl` row dumps are ignored. `?tag=<tag>` picks one (matches the file name or the `tag` field). 404 `{"status": "no_bench"}` if none or the tag is unknown.

### GET /api/bench
-> `{"benches": [{"tag", "set", "fake", "file", "mtime"}]}`, newest first (summaries only, ISO-8601 UTC `mtime`).

### GET /api/costs
-> `{"total_usd": 0.035, "calls": 3, "by_provider": {"gemini": {"calls": 2, "usd": 0.03}}, "by_task": {"read_drawing": {"calls": 2, "usd": 0.015}}}` from `results/costs.jsonl` (fields `provider`, `task`, `cost_usd`).

### POST /api/tts (S-08)
Body `{"text": "...", "voice": "<elevenlabs voice id, optional>"}` (text 1-1500 chars; 400 empty or bad voice, 413 too long).
-> `200 audio/mpeg` bytes (headers `X-TTS-Provider`, `X-TTS-Cache: hit|miss`, `Cache-Control: public, max-age=86400`). Play with `new Audio(URL.createObjectURL(await r.blob()))`.
-> `200 {"fallback": "device", "reason": "..."}` (JSON) when no TTS key is set, the budget cap is hit or the provider fails: the client must use the browser's `speechSynthesis`. Check `content-type` to tell the two apart.
Backend: ElevenLabs `eleven_flash_v2_5` (about 0.00017 USD per character, logged in `results/costs.jsonl`), fallback Runware fishaudio. Identical text is served from the disk cache and costs nothing.

### POST /api/speech-intent (S-08)
Multipart upload, field `file`, audio/wav, mpeg, mp4, ogg, webm, flac, aac or aiff, max 5 MB.
-> `{"text": "how many windows are there", "intent": "ask", "provider": "gemini"}`; `intent` is one of `ask`, `visualise`, `show_on_table`, `changes`, `other`.
-> `200 {"fallback": "device", "reason": "..."}` when no provider can take audio. Only Gemini accepts audio (the NVIDIA and Runware adapters reject it), so without `GEMINI_API_KEY` this always returns the fallback: the client should use the browser's `SpeechRecognition` and send the text to `/api/chats/{id}/messages`.

### Not yet
Findings/advise (tier 3).

### WS /ws (live sync, S-06)
`ws://localhost:8000/ws` (use `wss://` when deployed). Server-to-client events are small JSON objects; refetch the thing they name.
```
{"type": "chat.message", "chat_id": "<uuid>", "message_id": "<uuid>", "role": "user|assistant"}   // refetch GET /api/chats/{id}
{"type": "chat.status",  "chat_id": "<uuid>", "text": "Thinking…"}                                // same lines as the SSE status events
{"type": "scene.highlight", "doc_id": "...", "item_ids": ["window-001", "window-002"], "labels": {"window-001": "1", "window-002": "2"}}
{"type": "doc.new", "doc_id": "uploads__plan-3fa2b1"}                                              // refetch GET /api/docs
{"type": "changes.new", "id": "<uuid>"}                                                           // refetch GET /api/changes
{"type": "ping"}                                                                                    // every 20 s; any reply is optional
```
Client-to-server: `{"type": "scene.highlight", "doc_id": "...", "item_ids": [...], "labels": {...}}` is re-broadcast to every client, including the sender. `labels` is optional (the 2D citation numbers): item_id -> string of 1-8 characters, only for ids in `item_ids`; invalid entries are dropped and the key is omitted when none remain
(web 3D viewer and iOS AR follow it). `{"type": "ping"}` gets `{"type": "pong"}`. Other types are ignored.
Mechanism: writers call `pg_notify('hologram_events', ...)`; each server process holds one LISTEN connection and fans out to its sockets
(works across several server instances; reconnects after a drop). `changes.new` comes from a DB trigger, so any writer of `changes` fires it.
Without a database the server broadcasts to its own sockets directly. Delivery is well under 2 s.

## Scene edits (S-10, CONTRACT 5.11)

An edit layer per chat: "show all windows tagged W1..Wn", "remove window W7". Edits never change source data.

Client-to-server over `/ws`:
`{"type":"scene.edit","doc_id":"...","chat_id":"<uuid, optional>","op":"highlight|hide|restore|reset|isolate","item_ids":[...],"labels":{"id":"W7"},"edit_id":"<optional, up to 64 chars>"}`.
- `item_ids`: strings, at most 500, duplicates dropped. Required (non-empty) for `highlight`, `hide`, `isolate`; `restore` with none restores everything hidden; `reset` takes none.
- `labels` (only for `highlight` and `isolate`): same rules as `scene.highlight` labels.
- With `chat_id` the edit is stored (table `scene_edits`) and a repeated `edit_id` is applied once. Without it the edit is only relayed.
- An invalid edit gets `{"type":"scene.error","detail":"invalid scene.edit"}` back to the sender only.

Server-to-client (to every socket, including the sender): `{"type":"scene.edit","doc_id","chat_id"?,"op","item_ids","labels"?,"edit_id","ts"}`. Clients apply edits in arrival order.

State (what the layer looks like after folding all edits of a chat, per doc):
`{"type":"scene.state","chat_id","doc_id","hidden":[...],"highlighted":[...],"labels":{...},"isolated":[...]|null}`.
`highlight` replaces highlighted and labels; `hide` adds to hidden and removes from highlighted, labels and isolated; `restore` removes from hidden; `isolate` sets isolated and highlighted to the ids (only these should stay visible) and unhides them; `reset` clears everything. `isolated` is an addition to the contract text: null unless `isolate` was used.
Late joiners get it by connecting to `/ws?chat_id=<uuid>[&doc_id=...]` (sent first, one message per doc with edits; with `doc_id` always one message), or by sending `{"type":"scene.join","chat_id":"...","doc_id":"..."?}` later.

`GET /api/chats/{id}/scene-state[?doc_id=]` -> `{"chat_id","states":[{doc_id,hidden,highlighted,labels,isolated}]}` (no `type` key; `states` is empty when the chat has no edits and no `doc_id` is given; 404 for an unknown chat).

Answers: `evidence.scene.commands` (`[{op,item_ids,labels?}]`) is stored and relayed by the server when the answer is saved, as `scene.edit` events with `edit_id` `<answer_id>-<n>`, so clients that already apply the answer's commands should ignore a `scene.edit` whose `edit_id` they have seen.

## Advisor cards (CONTRACT 5.12)

`POST /api/advise` `{"doc_id", "chat_id"?, "edit"?: {"op", "item_ids"}}` -> `{"cards": [Card]}`, at most 3. 404 for an unknown document or chat, 422 for an invalid edit. The same cards are pushed over `/ws` as `{"type":"advisor.cards","doc_id","chat_id"|null,"cards":[...]}` after every call (also when empty, so clients can clear).
Card: `{card_id, kind: warning|option|info, title (<=60), body (<=200), item_ids, source: {type: rule|material_table|document, ref, title, quote (<=200, verbatim)}}`.
The cards come from `engine.advisor.advise(doc_id, edit, chat_id) -> list[dict]` (E-16); until it exists the answer is `{"cards": []}`. The server enforces the hard rule on what the engine returns: a card without type, ref, title and quote in its source is dropped; a `rule` card must name an id from `engine/rules/*.yaml` and quote text found in that rule (`quote`, `quote_en` or `finnish_quote`); a card with a quote over 200 characters is dropped; title and body are cut to their limits. An engine error gives no cards.

## Findings, skills and automations (S-09)

Findings (rule checks, engine hook `engine.findings.run(doc_id)`; until E-15 lands the run answers `{"status":"no_checks","findings":[]}`):
- `POST /api/findings/run {doc_id}` runs the checks, replaces that document's findings, publishes `findings.updated`. Findings that cite no rule from `engine/rules/*.yaml` or name no item are dropped. Returns `{status, findings}`.
- `GET /api/findings[?doc_id=&rule_id=&severity=]` returns `{findings:[{id, doc_id, rule_id, item_ids, severity, message, detail, rule:{id,text,source_title,section,url,quote,translation}, created_at}]}`. Severity is `info`, `suggestion` or `violation`.

Skills (saved prompts; four builtin starters from the start screen cannot be deleted):
- `GET /api/skills`, `POST /api/skills {name, prompt, description?}` (201), `DELETE /api/skills/{id}` (204, 403 for builtin).
- `POST /api/skills/{id}/run {doc_ids}` runs the prompt through the chat engine, returns `{skill_id, prompt, answer}` (a full answer object).

Automations (a prompt on a schedule; the latest run is kept as a report):
- `GET/POST /api/automations`, `GET/PATCH/DELETE /api/automations/{id}`. Body: `{name, prompt, doc_ids, interval_minutes (default 1440), enabled}`.
- `POST /api/automations/{id}/run` runs now. `GET /api/automations/{id}/report.md` returns the report as Markdown (404 before the first run).
- `GET /api/automations/{id}/report.pdf` returns the same report as a PDF (`application/pdf`, built without extra dependencies; 404 before the first run).
- A background loop checks every 30 s and runs due automations (`AUTOMATIONS=0` turns it off). A failed run is stored as a report with `ok: false`. Each run publishes `automation.report`.

## Watch loop (E-17)

Context.dev monitors (docs.context.dev, `POST /v1/monitors`, Bearer `CONTEXT_DEV_API_KEY`) watch every rule `url` in `engine/rules/*.yaml` (exact page change, every 6 h). `python -m engine.watch` (or `POST /api/watch/sync`) creates them idempotently (reuses by name/target URL) and writes ids to `results/watch/monitors.json`; signing secrets go to `artifacts/watch/secrets.json` (git-ignored). Set `WATCH_WEBHOOK_URL` to the public `https://<api>/api/watch/webhook` before syncing to attach the webhook (Context.dev refuses non-public URLs).
- `POST /api/watch/webhook` receives `change.detected`. Verified with `X-Context-Signature: t=<unix>,v1=hex(HMAC-SHA256(secret, "t.body"))` (5 min tolerance). Fallback: env `WATCH_WEBHOOK_SECRET` as `?secret=` or `X-Watch-Secret`. No secret known: 503; bad signature: 401. A valid event inserts a `changes` row (fires `changes.new`), dedupes on the event id, and reruns findings for all documents. Returns `{status: ok|duplicate|ignored, change_id, findings_rerun_docs}`.
- Feed entries appear in `GET /api/changes` with `type: "rule_change"` and `summary: {kind: "rule_change", source: "context.dev", url, rule_ids, title, summary, importance, headline, monitor_id, event_id}`; `doc_a`/`doc_b` are null.
- `GET /api/watch/monitors` returns the monitor list and rule URLs.
