# API smoke: FAIL

Base: https://obviously-present-piglet.eur-1.aiven.app

88 checks; 16 failures. Times exclude pacing.

| Method | Endpoint | Status | ms | Result |
| --- | --- | ---: | ---: | --- |
| GET | /api/health | 200 | 526.8 | PASS: shape OK |
| GET | /api/docs | 200 | 1333.0 | PASS: shape OK |
| GET | /api/folders | 200 | 346.1 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc | 200 | 477.2 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/source | 404 | 262.0 | PASS: documented fallback: not_built |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1/image | 200 | 365.7 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1.png | 200 | 349.5 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/planmap/1 | 200 | 399.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/scene | 200 | 523.4 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.glb | 200 | 1412.8 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.usdz | 200 | 954.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.json | 200 | 455.1 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/elements.json | 200 | 720.7 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/page-1.thumb.png | 200 | 266.8 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/ingest | 200 | 395.8 | PASS: shape OK |
| POST | /api/upload | 200 | 316.3 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-123849-2be33d-generated-for-demo-110652 | 200 | 229.7 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-123849-2be33d-generated-for-demo-110652/ingest | 200 | 284.4 | PASS: shape OK |
| GET | /api/chats | 200 | 618.4 | PASS: shape OK |
| POST | /api/chats | 200 | 305.4 | PASS: shape OK |
| GET | /api/chats/bec06297-5abb-4944-941b-dfff74d5a193 | 200 | 277.3 | PASS: shape OK |
| GET | /api/chats/bec06297-5abb-4944-941b-dfff74d5a193/scene-state | 200 | 269.4 | PASS: shape OK |
| POST | /api/chats/bec06297-5abb-4944-941b-dfff74d5a193/messages | 200 | 1051.1 | PASS: shape OK |
| GET | /api/chats/bec06297-5abb-4944-941b-dfff74d5a193 | 429 | 279.3 | FAIL: unexpected HTTP status |
| GET | /api/changes | 429 | 334.4 | FAIL: unexpected HTTP status |
| POST | /api/changes/refresh | 429 | 343.1 | FAIL: unexpected HTTP status |
| GET | /api/changes/857727ba-8104-465e-acc2-9cbd406f2986 | 404 | 209.5 | PASS: empty feed: checked unknown comparison 404 only |
| GET | /api/skills | 200 | 263.5 | PASS: shape OK |
| POST | /api/skills | 201 | 333.8 | PASS: shape OK |
| POST | /api/skills/b10504b8-a988-4e41-9a51-3c8e0cef6578/run | 200 | 595.0 | PASS: shape OK |
| GET | /api/automations | 200 | 214.7 | PASS: shape OK |
| POST | /api/automations | 201 | 246.3 | PASS: shape OK |
| GET | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214 | 200 | 273.5 | PASS: shape OK |
| PATCH | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214 | 200 | 761.5 | PASS: shape OK |
| POST | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214/run | 200 | 357.3 | PASS: shape OK |
| GET | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214/report.md | 200 | 600.9 | PASS: shape OK |
| GET | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214/report.pdf | 200 | 275.0 | PASS: shape OK |
| DELETE | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214 | 204 | 287.1 | PASS: shape OK |
| GET | /api/automations/d50b3fe3-cf53-494c-9adb-0f1cf1b59214 | 404 | 393.4 | PASS: shape OK |
| DELETE | /api/skills/b10504b8-a988-4e41-9a51-3c8e0cef6578 | 204 | 207.5 | PASS: shape OK |
| GET | /api/skills | 200 | 281.6 | PASS: shape OK |
| POST | /api/findings/run | 200 | 1191.0 | PASS: shape OK |
| GET | /api/findings?doc_id=ifc_bench__ac20-arc | 200 | 367.7 | PASS: shape OK |
| POST | /api/advise | 200 | 1169.7 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/items/3qloCPnZDEQBom1ZjBlwJP | 200 | 264.8 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/tags/D8 | 200 | 1383.4 | PASS: shape OK |
| GET | /api/bench | 200 | 298.1 | PASS: shape OK |
| GET | /api/bench/latest | 404 | 205.5 | PASS: documented fallback: no_bench |
| GET | /api/costs | 200 | 201.0 | PASS: shape OK |
| POST | /api/tts | 200 | 645.1 | PASS: shape OK |
| POST | /api/speech-intent | 200 | 372.3 | PASS: documented fallback: device |
| GET | /api/watch/monitors | 200 | 449.2 | PASS: shape OK |
| POST | /api/watch/sync | 200 | 393.3 | PASS: documented fallback: no_key |
| POST | /api/watch/webhook | 503 | 212.8 | PASS: shape OK |
| WS | /ws | 101 | 524.2 | PASS: WebSocket upgrade and JSON pong |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s400-bracing-elevation | 200 | 335.2 | PASS: S-16 vacation-rental--s400-9872c2 revision 1/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s400-bracing-elevation/source | 404 | 207.0 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s400-bracing-elevation/pages/1.png | 200 | 700.2 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400 | 200 | 297.5 | PASS: S-16 vacation-rental--s400-9872c2 revision 2/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/source | 404 | 377.0 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/pages/1.png | 200 | 941.6 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400 | 200 | 204.5 | PASS: S-16 vacation-rental--s400-9872c2 revision 3/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/source | 404 | 345.2 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/pages/1.png | 200 | 1574.5 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s400-bracing-elevation | 200 | 236.5 | PASS: S-16 vacation-rental--s400-9872c2 revision 4/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s400-bracing-elevation/source | 404 | 205.4 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s400-bracing-elevation/pages/1.png | 200 | 772.1 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s401-bracing-details | 200 | 327.0 | PASS: S-16 vacation-rental--s401-9b69ee revision 1/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s401-bracing-details/source | 404 | 265.0 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s401-bracing-details/pages/1.png | 200 | 717.5 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401 | 200 | 235.5 | PASS: S-16 vacation-rental--s401-9b69ee revision 2/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/source | 404 | 250.3 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/pages/1.png | 200 | 998.1 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401 | 200 | 258.5 | PASS: S-16 vacation-rental--s401-9b69ee revision 3/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/source | 404 | 203.0 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/pages/1.png | 200 | 886.5 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s401-bracing-details | 200 | 367.2 | PASS: S-16 vacation-rental--s401-9b69ee revision 4/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s401-bracing-details/source | 404 | 304.2 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s401-bracing-details/pages/1.png | 200 | 1023.2 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170410-submitted-to-state-for-early-start-and-footing-and-foundation-the-downtowner-sheet-a100-demolition-plans | 200 | 272.0 | PASS: S-16 vacation-rental--a100-8f1f68 revision 1/2 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170410-submitted-to-state-for-early-start-and-footing-and-foundation-the-downtowner-sheet-a100-demolition-plans/source | 404 | 235.6 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170410-submitted-to-state-for-early-start-and-footing-and-foundation-the-downtowner-sheet-a100-demolition-plans/pages/1.png | 200 | 4725.4 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-a100-demolition-plans | 200 | 545.2 | FAIL: missing/invalid field: doc_id |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-a100-demolition-plans/source | 200 | 459.6 | FAIL: revision source is not PDF |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-a100-demolition-plans/pages/1.png | 200 | 11263.6 | PASS: revision page PNG signature OK |
| POST | /api/chats | 200 | 284.2 | PASS: shape OK |
| POST | /api/chats/c60d7671-d8e7-41b0-a763-1fd2d5535d0f/messages | 200 | 1564.6 | FAIL: missing/invalid field: advisor_cards |
| GET | /api/health | 200 | 247.7 | FAIL: unexpected deployed build revision |

Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.
Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.
No chat or uploaded-document delete API exists; created IDs are recorded for the lead.

Created resources:

- upload `uploads__smoke-123849-2be33d-generated-for-demo-110652`: no delete API
- chat `bec06297-5abb-4944-941b-dfff74d5a193`: no delete API
- skill `b10504b8-a988-4e41-9a51-3c8e0cef6578`: deleted
- automation `d50b3fe3-cf53-494c-9adb-0f1cf1b59214`: deleted
- chat `c60d7671-d8e7-41b0-a763-1fd2d5535d0f`: no delete API
