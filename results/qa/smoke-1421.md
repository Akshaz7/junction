# API smoke: PASS

Base: http://localhost:8000

55 checks; 0 failures. Times exclude pacing.

| Method | Endpoint | Status | ms | Result |
| --- | --- | ---: | ---: | --- |
| GET | /api/health | 200 | 25.5 | PASS: shape OK |
| GET | /api/docs | 200 | 107.2 | PASS: shape OK |
| GET | /api/folders | 200 | 24.2 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc | 200 | 3.1 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/source | 200 | 16.6 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1/image | 200 | 2.2 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/planmap/1 | 200 | 2.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/scene | 200 | 137.0 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.glb | 200 | 8.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.usdz | 200 | 5.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.json | 200 | 205.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/elements.json | 200 | 6.3 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/page-1.thumb.png | 200 | 5.2 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/ingest | 200 | 1.4 | PASS: shape OK |
| POST | /api/upload | 200 | 6.7 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-121944-49d1d8-generated-for-demo-f30fd7 | 200 | 3.8 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-121944-49d1d8-generated-for-demo-f30fd7/ingest | 200 | 2.3 | PASS: shape OK |
| GET | /api/chats | 200 | 4.5 | PASS: shape OK |
| POST | /api/chats | 200 | 3.6 | PASS: shape OK |
| GET | /api/chats/ede48c7a-6edb-43b8-9206-29f7d57160c6 | 200 | 4.2 | PASS: shape OK |
| GET | /api/chats/ede48c7a-6edb-43b8-9206-29f7d57160c6/scene-state | 200 | 3.8 | PASS: shape OK |
| POST | /api/chats/ede48c7a-6edb-43b8-9206-29f7d57160c6/messages | 200 | 42.1 | PASS: shape OK |
| GET | /api/chats/ede48c7a-6edb-43b8-9206-29f7d57160c6 | 200 | 11.7 | PASS: shape OK |
| GET | /api/changes | 200 | 30.4 | PASS: shape OK |
| POST | /api/changes/refresh | 200 | 63.1 | PASS: shape OK |
| GET | /api/changes/ser%3Actr--t-binder-29602f%3A1 | 200 | 11.2 | PASS: shape OK |
| GET | /api/changes/ser%3Actr--t-binder-29602f%3A1?page=3 | 200 | 13.6 | PASS: shape OK |
| GET | /api/skills | 200 | 9.3 | PASS: shape OK |
| POST | /api/skills | 201 | 5.4 | PASS: shape OK |
| POST | /api/skills/6168aa9a-482e-4a3a-98c3-1e5aaf9065dd/run | 200 | 77.0 | PASS: shape OK |
| GET | /api/automations | 200 | 4.1 | PASS: shape OK |
| POST | /api/automations | 201 | 7.0 | PASS: shape OK |
| GET | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61 | 200 | 3.3 | PASS: shape OK |
| PATCH | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61 | 200 | 23.1 | PASS: shape OK |
| POST | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61/run | 200 | 15.3 | PASS: shape OK |
| GET | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61/report.md | 200 | 4.4 | PASS: shape OK |
| GET | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61/report.pdf | 200 | 5.9 | PASS: shape OK |
| DELETE | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61 | 204 | 12.3 | PASS: shape OK |
| GET | /api/automations/abb0d41c-897e-4ca0-a0a4-cfcbc50caf61 | 404 | 4.8 | PASS: shape OK |
| DELETE | /api/skills/6168aa9a-482e-4a3a-98c3-1e5aaf9065dd | 204 | 6.7 | PASS: shape OK |
| GET | /api/skills | 200 | 3.5 | PASS: shape OK |
| POST | /api/findings/run | 200 | 59.3 | PASS: shape OK |
| GET | /api/findings?doc_id=ifc_bench__ac20-arc | 200 | 4.2 | PASS: shape OK |
| POST | /api/advise | 200 | 55.5 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/items/3qloCPnZDEQBom1ZjBlwJP | 200 | 12.4 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/tags/D8 | 200 | 9.7 | PASS: shape OK |
| GET | /api/bench | 200 | 4.5 | PASS: shape OK |
| GET | /api/bench/latest | 200 | 2.7 | PASS: shape OK |
| GET | /api/costs | 200 | 28.1 | PASS: shape OK |
| POST | /api/tts | 200 | 225.4 | PASS: shape OK |
| POST | /api/speech-intent | 200 | 3.6 | PASS: documented fallback: device |
| GET | /api/watch/monitors | 200 | 11.4 | PASS: shape OK |
| POST | /api/watch/sync | 200 | 1350.9 | PASS: shape OK |
| POST | /api/watch/webhook | 503 | 1.6 | PASS: shape OK |
| WS | /ws | 101 | 1.8 | PASS: WebSocket upgrade and JSON pong |

Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.
Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.
No chat or uploaded-document delete API exists; created IDs are recorded for the lead.

Created resources:

- upload `uploads__smoke-121944-49d1d8-generated-for-demo-f30fd7`: no delete API
- chat `ede48c7a-6edb-43b8-9206-29f7d57160c6`: no delete API
- skill `6168aa9a-482e-4a3a-98c3-1e5aaf9065dd`: deleted
- automation `abb0d41c-897e-4ca0-a0a4-cfcbc50caf61`: deleted
