# API smoke: FAIL

Base: https://hologram-khaki.vercel.app

79 checks; 2 failures. Times exclude pacing.

| Method | Endpoint | Status | ms | Result |
| --- | --- | ---: | ---: | --- |
| GET | /api/health | 200 | 517.7 | PASS: shape OK |
| GET | /api/docs | 200 | 1513.4 | PASS: shape OK |
| GET | /api/folders | 200 | 353.0 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc | 200 | 60599.3 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/source | 404 | 295.8 | PASS: documented fallback: not_built |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1/image | 200 | 213.5 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1.png | 200 | 383.8 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/planmap/1 | 200 | 436.8 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/scene | 200 | 344.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.glb | 200 | 953.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.usdz | 200 | 428.8 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.json | 200 | 405.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/elements.json | 200 | 515.8 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/page-1.thumb.png | 200 | 248.7 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/ingest | 200 | 217.4 | PASS: shape OK |
| POST | /api/upload | 200 | 328.7 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-130311-4f823e-generated-for-demo-49a103 | 200 | 250.7 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-130311-4f823e-generated-for-demo-49a103/ingest | 200 | 226.8 | PASS: shape OK |
| GET | /api/chats | 200 | 414.2 | PASS: shape OK |
| POST | /api/chats | 200 | 285.6 | PASS: shape OK |
| GET | /api/chats/be5344bf-15e2-4703-b7f2-440134679ce4 | 200 | 200.1 | PASS: shape OK |
| GET | /api/chats/be5344bf-15e2-4703-b7f2-440134679ce4/scene-state | 200 | 226.9 | PASS: shape OK |
| POST | /api/chats/be5344bf-15e2-4703-b7f2-440134679ce4/messages | 200 | 2105.5 | PASS: shape OK |
| GET | /api/chats/be5344bf-15e2-4703-b7f2-440134679ce4 | 200 | 290.2 | PASS: shape OK |
| GET | /api/changes | 200 | 1025.9 | PASS: shape OK |
| POST | /api/changes/refresh | 200 | 486.5 | PASS: shape OK |
| GET | /api/changes/ser%3Avacation-rental--s400-9872c2%3A3 | 200 | 271.6 | PASS: shape OK |
| GET | /api/changes/ser%3Avacation-rental--s400-9872c2%3A3?page=1 | 200 | 215.5 | PASS: shape OK |
| GET | /api/skills | 200 | 334.9 | PASS: shape OK |
| POST | /api/skills | 201 | 334.0 | PASS: shape OK |
| POST | /api/skills/7f1ec1ad-e8e6-4000-afa2-319b6040f026/run | 200 | 2462.7 | PASS: shape OK |
| GET | /api/automations | 200 | 925.0 | PASS: shape OK |
| POST | /api/automations | 201 | 275.2 | PASS: shape OK |
| GET | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80 | 200 | 178.6 | PASS: shape OK |
| PATCH | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80 | 200 | 279.5 | PASS: shape OK |
| POST | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80/run | 200 | 781.5 | PASS: shape OK |
| GET | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80/report.md | 200 | 240.5 | PASS: shape OK |
| GET | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80/report.pdf | 200 | 367.2 | PASS: shape OK |
| DELETE | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80 | 204 | 207.4 | PASS: shape OK |
| GET | /api/automations/69b286de-582e-4b69-b09e-e9def89fbc80 | 404 | 264.9 | PASS: shape OK |
| DELETE | /api/skills/7f1ec1ad-e8e6-4000-afa2-319b6040f026 | 204 | 282.6 | PASS: shape OK |
| GET | /api/skills | 200 | 383.8 | PASS: shape OK |
| POST | /api/findings/run | 200 | 1342.2 | PASS: shape OK |
| GET | /api/findings?doc_id=ifc_bench__ac20-arc | 200 | 522.8 | PASS: shape OK |
| POST | /api/advise | 200 | 1474.1 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/items/3qloCPnZDEQBom1ZjBlwJP | 200 | 300.5 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/tags/D8 | 200 | 2713.8 | PASS: shape OK |
| GET | /api/bench | 200 | 272.5 | PASS: shape OK |
| GET | /api/bench/latest | 404 | 382.4 | FAIL: unexpected HTTP status |
| GET | /api/costs | 200 | 372.1 | PASS: shape OK |
| GET | /api/costs/summary | 200 | 1141.8 | PASS: shape OK |
| POST | /api/tts | 200 | 390.7 | PASS: shape OK |
| POST | /api/speech-intent | 200 | 318.0 | PASS: documented fallback: device |
| GET | /api/watch/monitors | 200 | 443.8 | PASS: shape OK |
| POST | /api/watch/sync | 200 | 427.3 | PASS: documented fallback: no_key |
| POST | /api/watch/webhook | 503 | 269.1 | PASS: shape OK |
| WS | /ws | 101 | 543.6 | PASS: WebSocket upgrade and JSON pong |
| POST | /api/chats | 200 | 216.0 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 696.1 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 667.4 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 562.3 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 556.9 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 470.4 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 679.1 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 984.3 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 600.6 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 632.4 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 421.4 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 855.9 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 667.6 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 595.3 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 673.2 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 1313.2 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 1827.2 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 1770.6 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 1555.0 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 1377.2 | PASS: shape OK |
| POST | /api/chats/02e0c09c-57bc-41f7-8b5c-73806c04c09c/messages | 200 | 748.2 | PASS: shape OK |
| GET | /api/health | 200 | 819.2 | FAIL: unexpected deployed build revision |

AC20 end-to-end latency (nearest-rank percentiles):

| Questions | Successful / requested | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| cached | 10 / 10 | 667.6 | 1313.2 |
| novel | 5 / 5 | 1555.0 | 1827.2 |

Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.
Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.
No chat or uploaded-document delete API exists; created IDs are recorded for the lead.
HTTP 429 retries are recorded per check; latency includes Retry-After waits. A check passes only after its response validator passes.
Latency: end-to-end HTTP through terminal SSE answer, excluding pacing; p50/p95 use nearest rank. 'Cached' means exact questions repeated after warmup; the API exposes no cache-hit flag, so a response/model cache hit is not claimed. Novel questions have unique run labels; IFC code routes may use the same loaded index.

Created resources:

- upload `uploads__smoke-130311-4f823e-generated-for-demo-49a103`: no delete API
- chat `be5344bf-15e2-4703-b7f2-440134679ce4`: no delete API
- skill `7f1ec1ad-e8e6-4000-afa2-319b6040f026`: deleted
- automation `69b286de-582e-4b69-b09e-e9def89fbc80`: deleted
- chat `02e0c09c-57bc-41f7-8b5c-73806c04c09c`: no delete API

Vercel measurements only; deployment changed during the run, so timings cannot be attributed to revision 0254cc0. Cached means warmed repeated questions; cache hits are not observable.
