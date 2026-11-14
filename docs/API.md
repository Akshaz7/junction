# Hologram API

Source snapshot: 2026-11-14, read from [app.py](../server/app.py) and all `server/*_routes.py`, with WebSocket behavior from [live.py](../server/live.py). Base URL locally: `http://localhost:8000`; use HTTPS/WSS for deployment. No accounts or authentication. JSON unless a route states otherwise. Shapes below use type names and `?` for optional fields; they are schemas, not measured results.

## Common requests and errors

Send `Content-Type: application/json` for JSON bodies. GET and DELETE requests have no body. Successful HTTP responses are 200 unless stated. FastAPI validates typed path/query/body fields: invalid or missing required fields return **422** with `{"detail":[...]}`. Route errors normally return `{"detail":"..."}`. Unhandled failures can return 500; routes do not all translate internal failures into JSON errors.

In the tables, **DB** means **503** `{"detail":"database unavailable"}` if PostgreSQL cannot be reached. This applies only to the routes marked DB, not every endpoint. Missing derived files use **404** `{"status":"not_built","detail":"<asset> not available"}`. Artifact doc IDs allow only ASCII letters, digits, `_`, `.`, `-`; routes using `_doc_dir` return **400** `bad doc_id` otherwise.

With `RATE_LIMIT=1`, the in-memory middleware limits each IP per rolling 60-second window. `RATE_LIMIT_PER_MIN` is a positive integer, default **30** (invalid/nonpositive values fall back to 30). Excess requests return **429** `{"detail":"rate limit exceeded"}` with `Retry-After: 60`. The first `X-Forwarded-For` address is used, else the connection IP. Counters are per process. Exempt GETs: `/api/health`, `/api/docs/{doc_id}/files/{name}`, `/api/docs/{doc_id}/pages/{n}/image`, `/api/docs/{doc_id}/scene`, `/api/docs/{doc_id}/ingest`. WebSocket upgrades bypass this HTTP middleware. Local default is `RATE_LIMIT=0`; the deploy Dockerfile sets it to 1. See [ratelimit.py](../server/ratelimit.py).

## Health

### GET /api/health

Request: no parameters. Response: `{ok: true, db: bool, build_rev: string, uptime_s: number, models_ok: bool}`. `build_rev` is `BUILD_REV` or an empty string; uptime is monotonic seconds since lifespan startup. `models_ok` means at least one configured non-fake provider has a nonblank key; it does **not** probe a model or confirm credentials. `ok` stays true and HTTP status stays 200 when `db` or `models_ok` is false. No route-specific error response.

```sh
curl http://localhost:8000/api/health
```

## Documents and artifacts

Sources: [docs_routes.py](../server/docs_routes.py), [files_routes.py](../server/files_routes.py), [docmeta_store.py](../server/docmeta_store.py).

`Document` contains `doc_id, source, title, kind, formats[], pages, licence, credit, heldout, files{format:path}`. Metadata enrichment adds `size` (bytes, nullable), `updated_at`, `project`, `folder`, `folder_path[]`, `discipline`, `subdiscipline`, `sheet`, `date`, `series_id`, `version_index`, `version_count`, `versions[]`. Version entries contain `doc_id, index, date, size, label, pages`; dates/size can be unknown. Enrichment is derived from document metadata and overlaid with `artifacts/docmeta.json` and the series files.

| Route | Request | Response | Errors |
|---|---|---|---|
| GET /api/docs | None | `{total, sources:[{source,count,docs:[Document]}]}` ordered by source, title, doc ID | DB |
| GET /api/docs/{doc_id} | Document ID | `Document` | DB; 404 `document not found` |
| GET /api/folders | None | `{total,folders:[Folder]}`; `Folder={name,path,count,children:[Folder]}`; project → discipline → optional MEP subdiscipline, sorted by name, document counts | DB |
| GET /api/docs/{doc_id}/source | Safe document ID | Original file bytes as an attachment, filename from the source file; content type inferred from filename | 400 bad doc ID; DB; 404 `document not found`; 404 `{status:"not_built",detail:"original file is not available on this server"}` |
| GET /api/docs/{doc_id}/pages/{n}/image | Safe document ID; integer page `n` | `image/png` from `page-<n>.png` | 400 bad doc ID; 404 not_built |
| GET /api/docs/{doc_id}/planmap/{n} | Safe document ID; integer page `n` | Plan map JSON, [CONTRACT 5.4](../CONTRACT.md): `{doc_id,page,image,scale,items,provenance}` | 400 bad doc ID; 404 not_built |
| GET /api/docs/{doc_id}/scene | Safe document ID | Manifest JSON, [CONTRACT 5.5](../CONTRACT.md): `{doc_id,glb,usdz,units,up,origin_offset_m,storeys,items,...}` | 400 bad doc ID; 404 not_built |
| GET /api/docs/{doc_id}/files/{name} | Safe document ID; allowed filename below | File bytes, MIME inferred by `FileResponse` | 400 bad doc ID; 404 `unknown file` for disallowed names; 404 not_built for missing allowed files |
| GET /api/docs/{doc_id}/ingest | Safe document ID | Ingestion state described below | 400 bad doc ID; missing state returns 200 `status:"none"` |

The scene route serves an existing manifest; it does not currently trigger extrusion. File routes restore persisted upload artifacts from PostgreSQL when available, but do not require a document row before serving an existing file. Allowed names: `scene.glb`, `scene.usdz`, `scene.json`, `elements.json`, `text.json`, `ingest.json`, `page-<n>.png`, `page-<n>.thumb.png`, `planmap-<n>.json`, `text-<n>.json` (numeric `<n>`).

### POST /api/upload

Request: multipart field **file**; accepted filename extensions are **.pdf, .png, .jpg, .jpeg, .dxf, .ifc** (case-insensitive). The endpoint checks the extension, not the MIME type. Maximum **100 MiB (104857600 bytes)**. DWG, SVG and TIFF are not accepted by this route.

```sh
curl -F file=@plan.pdf http://localhost:8000/api/upload
```

Response: `{doc_id:"uploads__<slug>-<six hex chars>",status:"ingesting"|"stored",detail:string}`. Creates a document row and stores the original plus `doc.json`; publishes `doc.new`. With the pipeline installed and `INGEST` not `0`, ingestion runs in a background subprocess and status starts as `running`, step `queued`. Otherwise the file is stored without ingestion. The original/derived upload artifacts are mirrored to PostgreSQL for restoration after restarts. The completed job updates document metadata and publishes `doc.new` again.

Errors: **400** `File is empty. Upload a non-empty pdf, png, jpg, dxf or ifc file.`; **413** `File too large. Maximum upload size is 100 MiB (104857600 bytes).`; **415** `Unsupported file type <extension or (none)>. Supported types: pdf, png, jpg (jpeg), dxf, ifc.`; DB; 422 missing multipart field.

Poll `GET /api/docs/{doc_id}/ingest`: `{status:"none"|"running"|"ready"|"partial"|"failed",step,progress,stages:[{stage,ok,s?,error?}],detail,reason?,mode?,started_at?,cost_usd?,updated?}`. `progress` is a completed-stage fraction, not a time estimate: 1 for ready, otherwise `len(stages)/(len(stages)+1)`. Missing state gives `none`, progress 0 and an empty stage list even for an unknown doc. `partial` means some outputs are available. Failed states include a readable `reason`. Jobs are serialized and have a five-minute timeout including queue time; polling also marks stale restored jobs failed. Stage details come from [ingest_job.py](../server/ingest_job.py); `INGEST_MODE=vlm|full` selects the deployed VLM or local vision pipeline.

## Linked items and tags

Source: [linked_routes.py](../server/linked_routes.py). Encode path values in URLs; the item/tag path converters allow embedded slashes.

| Route | Request | Response | Errors |
|---|---|---|---|
| GET /api/docs/{doc_id}/items/{item_id:path} | Document ID and exact item ID | `LinkedItem` | 404 `item not found`, including missing document/artifacts or a name/tag passed instead of an exact ID |
| GET /api/docs/{doc_id}/tags/{tag:path} | Document ID and tag/reference, e.g. `W7` | `LinkedItem` resolved by `engine.linked.lookup` | 404 `tag not found`, including missing document/artifacts |

`LinkedItem={doc_id,item_id,kind,tag,name,storey,type_name,ifc_class,props,quantities,places:[{doc_id,page,bbox_px,storey}]}`. Optional source properties can be null; `props`/`quantities` default to `{}`. `bbox_px` is in page-image pixels, origin top-left, and can be null. No database is required for these lookups.

## Chats and streamed answers

Source: [chats_routes.py](../server/chats_routes.py). `Chat={id,doc_id,title,created_at}`; ID is a UUID, doc/title can be null, timestamps are ISO-8601.

| Route | Request | Response | Errors |
|---|---|---|---|
| GET /api/chats | None | `{chats:[Chat]}`, newest first | DB |
| POST /api/chats | `{doc_ids?:string[] (default []),title?:string\|null}` | `Chat` (200); only first doc ID is stored, or null for general conversation | DB; 404 `document not found` for unknown first doc ID |
| GET /api/chats/{chat_id} | UUID | `Chat` plus `messages:[{id,role,content,created_at,answer}]`; `answer` is null or a full answer object. During a request, optional `active:{question,statuses,traces}` provides this process's in-flight state | DB; 404 `chat not found` for invalid/missing UUID |
| GET /api/chats/{chat_id}/scene-state | UUID; optional query `doc_id` | `{chat_id,states:[{doc_id,hidden,highlighted,labels,isolated}]}` | DB; 404 `chat not found` |
| POST /api/chats/{chat_id}/messages | UUID; `{content:string,doc_ids?:string[]\|null}` | `text/event-stream`, described below | DB; 404 `chat not found`; engine/answer validation failure after stream opens is an SSE `error` |

Message `doc_ids` overrides the stored document only when nonempty (empty/null falls back to the chat's doc). The real engine is the default. `ENGINE_IMPL=stub` explicitly selects the fixture engine; import failure can also select it. Existing hidden scene items and up to ten earlier messages are passed to the real engine. The user message is saved before streaming; a validated answer is saved as an assistant message.

```sh
curl -N -X POST http://localhost:8000/api/chats/CHAT_UUID/messages \
  -H 'Content-Type: application/json' -d '{"content":"How many windows are there?"}'
```

Stream framing (payload shapes):

```text
event: status
data: {"text":"Thinking…"}

event: trace
data: {"step":"<step>","detail":"<detail>","ms":0,"model":null,"cost_usd":0}

event: answer
data: <full answer JSON>
```

Status/trace events repeat; a successful stream ends with `answer`. On engine/answer validation failure it ends with `event: error`, `data: {"detail":"engine failed: ..."}`. This is not an HTTP error status after headers have been sent. Trace values above illustrate framing only.

Full answer shape is [CONTRACT 5.7](../CONTRACT.md): `{answer_id,question,doc_ids,answer:{text_md,value,unit,confidence,abstained},citations,evidence:{boxes,scene},trace,route,cost:{usd_total,calls},latency_ms}`. Scene commands are saved/relayed as edits with ID `<answer_id>-<command index>`. Hide commands may attach `advisor_cards` to the answer and publish `advisor.cards`. All answer values and citations are engine results, not a fixed window-count fixture.

For scene-state, no edits and no doc filter gives `states:[]`; a supplied doc filter gives an empty state for that doc when needed. `isolated` is an array or null. State semantics are documented under WebSocket below.

## Changes and comparison

Sources: [files_routes.py](../server/files_routes.py), [changes_source.py](../server/changes_source.py).

| Route | Request | Response | Errors |
|---|---|---|---|
| GET /api/changes | None | `ChangeFeed` | DB |
| POST /api/changes/refresh | No body | Rescans series, computes diffs for matching uploads, stamps `checked_at`, returns `ChangeFeed` | DB |
| GET /api/changes/{change_id} | Feed ID; optional integer query `page` (newer version's page) | Comparison for `ser:`/`upl:` IDs; stored change row for UUIDs | DB; 404 `change not found` for unknown/malformed ID; 422 noninteger page |

`ChangeFeed={changes:[Change],checked_at,groups:[{key,label,ids}]}`; `key`/entry `group` is `today|yesterday|earlier`. `Change={id,type,doc_a,doc_b,summary,created_at,group}`; type is `new_version|new_document|rule_change`. A stored UUID detail row contains `id,type,doc_a,doc_b,summary,created_at` without the feed's added group. Summary varies by source.

Real version pairs come from `artifacts/series/*.json` and cached PDF diffs under `artifacts/series/diffs/`; `ser:<series_id>:<n>` compares version n to n+1. Uploads matching a series produce `upl:<doc_id>` comparisons; unmatched uploads are `new_document` entries with ID `doc:<doc_id>` (feed-only; there is no detail handler for those IDs). Rule-change UUIDs come from the watch webhook. Version summaries include `doc_id,series_id,title,n_changes,headline,source:"pdf-diff",generated_for_demo:false,version_a,version_b,date_a,date_b,pages_changed`; `n_changes` can be null without a computed diff.

Comparison is this GET detail route; there is no separate `/api/compare` route. It returns:

```text
{id,type:"new_version",series_id,source:"pdf-diff",generated_for_demo:false,note,
 image,image_v1,page,pages:[{page,page_v1,page_v2,n_changes}],
 v1:{label,doc_id,date,page_image,thumb},v2:{label,doc_id,date,page_image,thumb},
 changes:[{n,change_id,type,kind,sentence,description,v1,v2,field,old,new,page}],
 created_at?}
```

Each change's `v1`/`v2` is null or `{item_id:null,bbox_px:[x0,y0,x1,y1]}`. Boxes use their respective version's image coordinates. With no requested/matching page, the first changed page is selected, else the first page. Missing diff cache is **200**, with `status:"not_built"`, `image:null`, `changes:[]`, `pages:[]`, note and abbreviated `v1`/`v2` (`label,doc_id`). This differs from a missing artifact's 404.

## Benchmarks and costs

Sources: [files_routes.py](../server/files_routes.py), [bench_routes.py](../server/bench_routes.py). Only the cost summary requires PostgreSQL.

| Route | Request | Response | Errors |
|---|---|---|---|
| GET /api/bench | None | `{benches:[{tag,set,fake,file,mtime}]}` newest mtime first; UTC ISO-8601 `mtime`; empty list if absent | No route-specific error |
| GET /api/bench/latest | Optional query `tag` matching summary's tag or file stem | `{tag,n,numeric_correct,numeric_total,accuracy,abstentions,by_type,cost_usd_total,cost_per_answer,file,data:<summary JSON>}` | Default missing results: 200 `status:"no_bench"`, null measurements; explicit unmatched tag: 404 |
| GET /api/costs | None | `{total_usd,calls,by_provider:{<provider>:{calls,usd}},by_task:{<task>:{calls,usd}}}` | No route-specific error |
| GET /api/costs/summary | None | `{total_usd,calls,spend_source:"model_cost_log",window_hours:24,answers,answers_with_cost,answers_missing_cost,answer_cost_usd_total,median_cost_per_answer,cost_sources}` | DB |

Bench summaries are dictionary-valued `results/bench/*.json`, at most 1 MB; row dumps are ignored. Runtime directories follow `RESULTS_DIR`, with packaged `<repo>/results/bench` as a fallback (runtime names take precedence). The default latest result selects only `fake:false`, completed runs (`totals.questions == totals.of`, positive question count matching the overall cell, no budget stop), preferring `e-s200-z1` from `docs/REPORT.md`, otherwise newest file mtime. An explicit tag can retrieve historical or fake runs. `data` preserves the raw summary for existing clients. `numeric_total` excludes unscored text (`n - unscored`); accuracy includes numeric abstentions/errors in its denominator. `by_type` contains the `ALL x <type>` cells. Bench answer costs come from `cells["ALL x ALL"]`, excluding text-judge spend recorded separately in `totals.cost_usd`.

`/api/costs` aggregates `results/costs.jsonl` (`provider,task,cost_usd`; task falls back to row, then `unknown`); absent logs yield zero totals and empty maps. `/api/costs/summary` reports all spend recorded in the runtime model log (`MODELS_COSTS_LOG`, else `RESULTS_DIR/costs.jsonl`), including non-answer calls. This total covers the available log's lifetime, not just 24 hours, and is not a billing-account total. Its answer metrics use only rows created within the last 24 hours. The `answers` table has no separate cost column: the route reads `answer.cost.usd_total` from JSONB, falling back to summed `answer.trace[].cost_usd`. Costs are counted once; zero-cost answers are included in the median, unknown costs are excluded and reported as `answers_missing_cost`. No measured answer costs yields a null median. `cost_sources` reports counts by JSON cost source.

## Speech

Source: [speech_routes.py](../server/speech_routes.py). Both routes use `engine.models.call()` and can return **200** JSON `{fallback:"device",reason}` instead of media/transcription when no usable provider, provider failure or budget exhaustion occurs. Clients must check Content-Type and use device speech in this case.

| Route | Request | Response | Errors |
|---|---|---|---|
| POST /api/tts | `{text:string,voice?:string\|null}`; trimmed text 1–1500 chars; nonempty voice ID must match `[A-Za-z0-9]{10,40}` | `audio/mpeg` bytes, or device fallback JSON | 400 `text is empty` or `bad voice id`; 413 `text longer than 1500 characters`; 422 invalid body |
| POST /api/speech-intent | Multipart `file`, max 5 MiB (5242880 bytes); accepted MIME types below | `{text,intent,provider}` or device fallback JSON; intent `ask\|visualise\|show_on_table\|changes\|other` | 400 `empty audio`; 413 `audio too large`; 415 `unsupported audio type <type or (none)>`; 422 missing file |

TTS headers: `X-TTS-Provider`, `X-TTS-Cache: hit|miss`, `Cache-Control: public, max-age=86400`, `ETag` (audio SHA-1). Chain: ElevenLabs → Runware (see [MODELS.md](MODELS.md)). Speech MIME allowlist: `audio/wav`, `audio/x-wav`, `audio/mpeg`, `audio/mp3`, `audio/ogg`, `audio/flac`, `audio/aac`, `audio/aiff`, `audio/webm`, `audio/mp4`, `audio/x-m4a`, `video/webm`; MIME parameters are stripped. Only Gemini is considered usable for audio input; without its key, speech-intent returns device fallback even if text-model keys exist.

## Advisor

Source: [advise_routes.py](../server/advise_routes.py).

### POST /api/advise

Request: `{doc_id:string,chat_id?:UUID|null,edit?:{op:string,item_ids?:string[],detail?:object|null}|null}`. `item_ids` defaults to `[]`; up to **200**, each nonblank and at most **200 characters**. `detail` is limited to **4000 characters of JSON serialization** by the route. Accepted operations: **hide, restore, move, material, undo, resize, narrow, scale, set_width**. The route validates these operation names and size limits; interpretation of `detail` belongs to the engine. `move` may carry `delta_m`/`position_m`; `material` may carry `material`; `undo` may describe the inverse edit. These are local what-if inputs; this endpoint does not persist a scene edit or change source data.

Example body: `{"doc_id":"ifc_bench__ac20-arc","edit":{"op":"move","item_ids":["ITEM_ID"],"detail":{"delta_m":[0.2,0,0]}}}`.

Response: `{cards:[Card]}`, at most three. Also broadcasts `{type:"advisor.cards",doc_id,chat_id:null|UUID,cards}` even when empty. Engine absence/failure yields `cards:[]` with 200. Errors: DB; **404** `document not found` or `chat not found` (including invalid UUID); **422** `invalid edit` for unsupported op/size limits or FastAPI validation detail for a malformed body.

`Card={card_id,kind:"warning"|"option"|"info",title,body,item_ids,source:{type:"rule"|"material_table"|"document",ref,title,quote},severity:"violation"|"suggestion"|"info",checked?:string[]}`. Title ≤60 chars, body ≤200, quote ≤200. Cards missing a complete source are dropped; rule references must exist in `engine/rules/*.yaml` and quote actual rule text (whitespace normalized). Long quotes are dropped; title/body are shortened. Optional `checked` keeps at most 40 strings of up to 80 chars.

## Findings

Source: [findings_routes.py](../server/findings_routes.py). `Finding={id,doc_id,rule_id,item_ids,severity,message,detail,rule:{id,text,source_title,section,url,quote,translation},created_at}`. Severity is `info|suggestion|violation`.

| Route | Request | Response | Errors |
|---|---|---|---|
| POST /api/findings/run | `{doc_id:string}` | `{status:"ok",findings:[Finding]}`; replaces that doc's findings and publishes `findings.updated` | DB; 404 `document not found`; 502 `checks failed: <exception type>` |
| GET /api/findings | Optional query `doc_id`, `rule_id`, `severity` (string filters) | `{findings:[Finding]}` | DB |

Only findings naming a known library rule and at least one item survive. Unrecognized severity is normalized to suggestion. If checks cannot be imported, run returns 200 `{status:"no_checks",detail,findings:[]}`. The list endpoint does not validate the severity filter as an enum; unmatched filters yield an empty list.

## Saved skills

Source: [skills_routes.py](../server/skills_routes.py). `Skill={id,slug,name,description,prompt,builtin,created_at}`. Four built-in starter skills are seeded at startup and cannot be deleted. All routes require DB.

| Route | Request | Response | Errors (plus DB) |
|---|---|---|---|
| GET /api/skills | None | `{skills:[Skill]}`, builtins first, then creation time/ID | No additional route error |
| POST /api/skills | `{name:string (1–80 chars),prompt:string (1–2000),description?:string (≤200, default "")}` | **201** `Skill`; fields trimmed after length validation | 422 invalid body |
| DELETE /api/skills/{skill_id} | UUID | **204**, no body | 404 missing skill/invalid UUID; 403 `starter skills cannot be deleted` |
| POST /api/skills/{skill_id}/run | UUID; `{doc_ids?:string[] (default [], max 20)}` | `{skill_id,prompt,answer:<full answer object>}` | 404 missing skill/document or invalid UUID; 502 `engine failed: ...`; 422 invalid body |

Skill runs use the chat engine without storing a chat turn.

## Automations and reports

Source: [skills_routes.py](../server/skills_routes.py). All routes require DB. `Automation={id,name,prompt,doc_ids,interval_minutes,enabled,last_run_at,next_run_at,last_report,created_at}`. `last_run_at`/`last_report` can be null; `next_run_at` is null when disabled. `Report={report_id,ran_at,ok,markdown,answer}`; a failed run has `ok:false` and `answer:null`.

| Route | Request | Response | Errors (plus DB) |
|---|---|---|---|
| GET /api/automations | None | `{automations:[Automation]}`, creation time/ID order | No additional route error |
| POST /api/automations | `{name (1–80 chars),prompt (1–2000),doc_ids (1–20 IDs),interval_minutes?:integer (1–44640, default 1440),enabled?:bool (default true)}` | **201** `Automation` | 404 unknown document; 422 invalid body |
| GET /api/automations/{automation_id} | UUID | `Automation` | 404 missing automation/invalid UUID |
| PATCH /api/automations/{automation_id} | UUID; any of `{name?,prompt?,interval_minutes?,enabled?}` with same limits as creation; null fields ignored; doc_ids not editable | Updated `Automation` | 404 missing automation/invalid UUID; 422 invalid body |
| DELETE /api/automations/{automation_id} | UUID | **204**, no body | 404 missing automation/invalid UUID |
| POST /api/automations/{automation_id}/run | UUID; no body | Updated `Automation` including latest report | 404 missing automation/invalid UUID; engine failure is stored in a report, not returned as 502 |
| GET /api/automations/{automation_id}/report.md | UUID | Latest report Markdown (`text/markdown; charset=utf-8`) | 404 missing automation/invalid UUID or `no report yet` |
| GET /api/automations/{automation_id}/report.pdf | UUID | Latest report as `application/pdf`, attachment `report.pdf` | 404 missing automation/invalid UUID or `no report yet` |

Scheduler starts after five seconds, checks every 30 seconds and claims due rows before running them. `AUTOMATIONS=0` disables scheduling. Each run stores only the latest report and publishes `{type:"automation.report",automation_id,report_id}`. Manual run works even if the automation is disabled.

## Rule-source watch

Sources: [watch_routes.py](../server/watch_routes.py), [engine/watch.py](../engine/watch.py). Context.dev monitors rule URLs; sync uses `CONTEXT_DEV_API_KEY` and optional public `WATCH_WEBHOOK_URL`.

| Route | Request | Response | Errors |
|---|---|---|---|
| GET /api/watch/monitors | None | Saved `{status,monitors:[{url,rule_ids,monitor_id,created,webhook_url?}],...}` plus `rule_urls:string[]`; absent file gives `status:"none",monitors:[]` | No route-specific error |
| POST /api/watch/sync | No body | `{status:"ok"\|"partial"\|"no_key"\|"api_error"\|"unreachable",monitors:[],error?,http_status?}`; idempotently creates/reuses monitors and saves results | Provider/key failures above are reported in a **200** body |
| POST /api/watch/webhook | JSON `change.detected` event plus signature/shared secret, below | `{status:"ok",change_id,findings_rerun_docs}`; duplicate `{status:"duplicate"}`; unrecognized event `{status:"ignored"}` | 400 `invalid JSON`; 401 `invalid webhook signature`; 503 `no webhook secret configured`; DB |

Webhook body: `{id,event:"change.detected",created_at?,data:{change:{monitor_id,url,title?,summary?,importance?,detected_at?}}}`. `X-Context-Id` overrides the event ID for deduplication. A valid event inserts a rule-change row and reruns findings for documents; failed individual reruns are skipped. Feed summary carries `kind:"rule_change",source:"context.dev",event_id,monitor_id,url,rule_ids,title,summary,importance,detected_at,headline`.

Authenticate with `X-Context-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "t.body")>` with five-minute tolerance and a saved per-monitor secret, or `WATCH_WEBHOOK_SECRET`. Without a signature header, the shared secret can be supplied as `X-Watch-Secret` or query `secret`. The endpoint never accepts unsigned events when no secret is configured. Monitor IDs/results live under `results/watch/monitors.json`; signing secrets under git-ignored `artifacts/watch/secrets.json`.

## WS /ws

Connect `ws://localhost:8000/ws` (WSS in production). Optional query `chat_id=<UUID>&doc_id=<doc ID>` sends current scene states first; later send `{type:"scene.join",chat_id,doc_id?}` to request them. This does not filter the broadcast subscription: all sockets receive live events. Bad JSON, nonobject messages and unknown types are ignored. Invalid joins yield no state rather than an HTTP error. Database absence permits process-local broadcasts; persistence and initial state require a database.

Client requests and responses:

| Client message | Server behavior |
|---|---|
| `{type:"ping"}` | Replies `{type:"pong"}` to sender. After 20 seconds without an incoming message the server sends `{type:"ping"}`; reply is optional. |
| `{type:"scene.highlight",doc_id,item_ids,labels?}` | Relays to all sockets, including sender; first 500 IDs converted to strings; valid labels retained. Does not persist state. |
| `{type:"scene.edit",doc_id,chat_id?,op,item_ids?,labels?,edit_id?}` | Validates, optionally persists and broadcasts `{type:"scene.edit",doc_id,chat_id?,op,item_ids,labels?,edit_id,ts}`. Invalid edit: sender-only `{type:"scene.error",detail:"invalid scene.edit"}`. Duplicate stored edit ID is silently ignored. |
| `{type:"scene.join",chat_id,doc_id?}` | Sends `{type:"scene.state",chat_id,doc_id,hidden,highlighted,labels,isolated}` per doc with edits; supplied doc gets an empty state if none. |

Scene edit operations: `highlight|hide|restore|reset|isolate`. Safe edit `doc_id` here means a nonempty string ≤200 chars (not the artifact route's character regex). The server considers the first 500 supplied item IDs, drops duplicates/invalid strings, and retains nonempty strings ≤120 chars. `highlight`, `hide`, `isolate` require at least one surviving ID. `restore` with no IDs restores all hidden items. `reset` clears the whole layer. Labels apply only to highlight/isolate: item-ID keys must be in the selected IDs; values may be strings or integers (not booleans), converted to stripped nonblank strings ≤8 chars. `edit_id` is a nonempty string ≤64 chars or a generated UUID hex. With a valid chat UUID and database, edits persist per chat; without it they can be relayed only. A missing referenced chat is silently rejected. This operation set is separate from advisor what-if operations.

State folding: highlight replaces highlighted/labels; hide adds hidden IDs and removes them from highlighted/labels/isolated; restore clears specified hidden IDs (or all), without resetting isolation; isolate sets isolated/highlighted/labels and unhides the selected IDs; reset clears hidden/highlighted/labels and sets isolated to null. Source files never change.

Other server events:

```text
{type:"chat.message",chat_id,message_id,role,text?}   // refetch GET chat; user text may be truncated
{type:"chat.status",chat_id,text}
{type:"chat.trace",chat_id,step}                    // scalar trace fields, strings trimmed to 600 chars
{type:"chat.done",chat_id}                          // failed/abandoned active request: resync
{type:"doc.new",doc_id}                             // refetch docs/ingestion state
{type:"changes.new",id}                             // refetch changes
{type:"advisor.cards",doc_id,chat_id,cards}
{type:"findings.updated",doc_id,count}
{type:"automation.report",automation_id,report_id}
```

Successful assistant persistence publishes `chat.message`; late readers can fetch `active` from GET chat while this process is running an answer. Live traces keep at most 60 steps and statuses at most 20 entries. PostgreSQL LISTEN/NOTIFY fans out across processes; a dropped listener reconnects. Clients applying both answer commands and socket edits must deduplicate by `edit_id`.

## Framework documentation routes

FastAPI also exposes GET `/openapi.json` (JSON schema), GET `/docs` (Swagger UI), GET `/docs/oauth2-redirect` (Swagger OAuth redirect HTML) and GET `/redoc` (ReDoc HTML). No request body or route-specific errors; the HTTP rate limiter applies when enabled.
