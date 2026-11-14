# API smoke: FAIL

Base: https://obviously-present-piglet.eur-1.aiven.app

47 checks; 47 failures. Times exclude pacing.

| Method | Endpoint | Status | ms | Result |
| --- | --- | ---: | ---: | --- |
| GET | /api/health | 200 | 771.3 | FAIL: unexpected deployed build revision |
| GET | /api/docs | - | 0 | FAIL: not reached |
| GET | /api/folders | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id} | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/source | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/pages/{n}/image | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/pages/{n}.png | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/planmap/{n} | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/scene | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/files/{name} | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/ingest | - | 0 | FAIL: not reached |
| POST | /api/upload | - | 0 | FAIL: not reached |
| GET | /api/chats | - | 0 | FAIL: not reached |
| POST | /api/chats | - | 0 | FAIL: not reached |
| GET | /api/chats/{chat_id} | - | 0 | FAIL: not reached |
| GET | /api/chats/{chat_id}/scene-state | - | 0 | FAIL: not reached |
| POST | /api/chats/{chat_id}/messages | - | 0 | FAIL: not reached |
| GET | /api/changes | - | 0 | FAIL: not reached |
| POST | /api/changes/refresh | - | 0 | FAIL: not reached |
| GET | /api/changes/{change_id} | - | 0 | FAIL: not reached |
| GET | /api/skills | - | 0 | FAIL: not reached |
| POST | /api/skills | - | 0 | FAIL: not reached |
| POST | /api/skills/{skill_id}/run | - | 0 | FAIL: not reached |
| DELETE | /api/skills/{skill_id} | - | 0 | FAIL: not reached |
| GET | /api/automations | - | 0 | FAIL: not reached |
| POST | /api/automations | - | 0 | FAIL: not reached |
| GET | /api/automations/{automation_id} | - | 0 | FAIL: not reached |
| PATCH | /api/automations/{automation_id} | - | 0 | FAIL: not reached |
| POST | /api/automations/{automation_id}/run | - | 0 | FAIL: not reached |
| GET | /api/automations/{automation_id}/report.md | - | 0 | FAIL: not reached |
| GET | /api/automations/{automation_id}/report.pdf | - | 0 | FAIL: not reached |
| DELETE | /api/automations/{automation_id} | - | 0 | FAIL: not reached |
| POST | /api/findings/run | - | 0 | FAIL: not reached |
| GET | /api/findings | - | 0 | FAIL: not reached |
| POST | /api/advise | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/items/{item_id:path} | - | 0 | FAIL: not reached |
| GET | /api/docs/{doc_id}/tags/{tag:path} | - | 0 | FAIL: not reached |
| GET | /api/bench | - | 0 | FAIL: not reached |
| GET | /api/bench/latest | - | 0 | FAIL: not reached |
| GET | /api/costs | - | 0 | FAIL: not reached |
| GET | /api/costs/summary | - | 0 | FAIL: not reached |
| POST | /api/tts | - | 0 | FAIL: not reached |
| POST | /api/speech-intent | - | 0 | FAIL: not reached |
| GET | /api/watch/monitors | - | 0 | FAIL: not reached |
| POST | /api/watch/sync | - | 0 | FAIL: not reached |
| POST | /api/watch/webhook | - | 0 | FAIL: not reached |
| WS | /ws | - | 0 | FAIL: not reached |

Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.
Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.
No chat or uploaded-document delete API exists; created IDs are recorded for the lead.
HTTP 429 retries are recorded per check; latency includes Retry-After waits. A check passes only after its response validator passes.

Created resources:


The revision check stopped the smoke before remaining routes and latency samples.
