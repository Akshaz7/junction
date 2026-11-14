# API smoke: FAIL

Base: https://hologram-khaki.vercel.app

55 checks; 8 failures. Times exclude pacing.

| Method | Endpoint | Status | ms | Result |
| --- | --- | ---: | ---: | --- |
| GET | /api/health | 200 | 201.3 | PASS: shape OK |
| GET | /api/docs | 200 | 1031.6 | PASS: shape OK |
| GET | /api/folders | 200 | 747.3 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc | 200 | 259.2 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/source | 404 | 461.9 | PASS: documented fallback: not_built |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1/image | 200 | 212.0 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/planmap/1 | 200 | 327.1 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/scene | 200 | 1352.4 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.glb | 200 | 1114.6 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.usdz | 200 | 1535.1 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.json | 200 | 1393.7 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/elements.json | 200 | 892.7 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/page-1.thumb.png | 200 | 187.0 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/ingest | 200 | 161.5 | PASS: shape OK |
| POST | /api/upload | 200 | 394.2 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-122304-f736ed-generated-for-demo-8fc5f2 | 200 | 195.1 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-122304-f736ed-generated-for-demo-8fc5f2/ingest | 200 | 339.5 | PASS: shape OK |
| GET | /api/chats | 200 | 861.4 | PASS: shape OK |
| POST | /api/chats | 200 | 201.0 | PASS: shape OK |
| GET | /api/chats/af3f899e-75a5-4aea-93b1-ce8ac9002374 | 200 | 205.8 | PASS: shape OK |
| GET | /api/chats/af3f899e-75a5-4aea-93b1-ce8ac9002374/scene-state | 200 | 268.5 | PASS: shape OK |
| POST | /api/chats/af3f899e-75a5-4aea-93b1-ce8ac9002374/messages | 200 | 409.9 | PASS: shape OK |
| GET | /api/chats/af3f899e-75a5-4aea-93b1-ce8ac9002374 | 200 | 307.0 | PASS: shape OK |
| GET | /api/changes | 200 | 413.6 | PASS: shape OK |
| POST | /api/changes/refresh | 200 | 350.7 | PASS: shape OK |
| GET | /api/changes/ser%3Avacation-rental--s400-9872c2%3A3 | 200 | 246.6 | PASS: shape OK |
| GET | /api/changes/ser%3Avacation-rental--s400-9872c2%3A3?page=1 | 200 | 244.6 | PASS: shape OK |
| GET | /api/skills | 200 | 221.1 | PASS: shape OK |
| POST | /api/skills | 201 | 478.4 | PASS: shape OK |
| POST | /api/skills/4eae87ad-1954-4e66-9667-2b0836073ef3/run | 200 | 366.4 | PASS: shape OK |
| GET | /api/automations | 200 | 194.7 | PASS: shape OK |
| POST | /api/automations | 201 | 309.4 | PASS: shape OK |
| GET | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10 | 200 | 257.3 | PASS: shape OK |
| PATCH | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10 | 200 | 204.3 | PASS: shape OK |
| POST | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10/run | 200 | 551.5 | PASS: shape OK |
| GET | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10/report.md | 200 | 162.9 | PASS: shape OK |
| GET | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10/report.pdf | 200 | 189.0 | PASS: shape OK |
| DELETE | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10 | 204 | 189.8 | PASS: shape OK |
| GET | /api/automations/6c06c856-10aa-49f1-ae36-82aa0d990a10 | 404 | 314.4 | PASS: shape OK |
| DELETE | /api/skills/4eae87ad-1954-4e66-9667-2b0836073ef3 | 204 | 208.0 | PASS: shape OK |
| GET | /api/skills | 200 | 182.6 | PASS: shape OK |
| POST | /api/findings/run | 200 | 1257.3 | PASS: shape OK |
| GET | /api/findings?doc_id=ifc_bench__ac20-arc | 429 | 183.3 | FAIL: unexpected HTTP status |
| POST | /api/advise | 200 | 1214.8 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/items/3qloCPnZDEQBom1ZjBlwJP | 429 | 272.1 | FAIL: unexpected HTTP status |
| GET | /api/docs/ifc_bench__ac20-arc/tags/D8 | 429 | 211.0 | FAIL: unexpected HTTP status |
| GET | /api/bench | 429 | 231.2 | FAIL: unexpected HTTP status |
| GET | /api/bench/latest | 404 | 234.9 | PASS: documented fallback: no_bench |
| GET | /api/costs | 429 | 219.3 | FAIL: unexpected HTTP status |
| POST | /api/tts | 200 | 442.7 | PASS: shape OK |
| POST | /api/speech-intent | 429 | 170.8 | FAIL: unexpected HTTP status |
| GET | /api/watch/monitors | 200 | 300.9 | PASS: shape OK |
| POST | /api/watch/sync | 200 | 258.8 | PASS: documented fallback: no_key |
| POST | /api/watch/webhook | 429 | 167.5 | FAIL: unexpected HTTP status |
| WS | /ws | - | 133.8 | FAIL: WebSocket upgrade did not return 101 |

Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.
Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.
No chat or uploaded-document delete API exists; created IDs are recorded for the lead.

Created resources:

- upload `uploads__smoke-122304-f736ed-generated-for-demo-8fc5f2`: no delete API
- chat `af3f899e-75a5-4aea-93b1-ce8ac9002374`: no delete API
- skill `4eae87ad-1954-4e66-9667-2b0836073ef3`: deleted
- automation `6c06c856-10aa-49f1-ae36-82aa0d990a10`: deleted
