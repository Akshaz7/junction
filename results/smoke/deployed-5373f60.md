# API smoke: FAIL

Base: https://obviously-present-piglet.eur-1.aiven.app

89 checks; 11 failures. Times exclude pacing.

| Method | Endpoint | Status | ms | Result |
| --- | --- | ---: | ---: | --- |
| GET | /api/health | 200 | 291.2 | PASS: shape OK |
| GET | /api/docs | 200 | 61867.3 | PASS: shape OK |
| GET | /api/folders | 200 | 350.3 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc | 200 | 244.4 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/source | 404 | 282.5 | PASS: documented fallback: not_built |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1/image | 200 | 325.7 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/pages/1.png | 200 | 328.0 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/planmap/1 | 200 | 406.2 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/scene | 200 | 1738.9 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.glb | 200 | 1515.5 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.usdz | 200 | 1400.0 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/scene.json | 200 | 522.0 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/elements.json | 200 | 648.5 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/files/page-1.thumb.png | 200 | 873.1 | PASS: shape/signature OK |
| GET | /api/docs/ifc_bench__ac20-arc/ingest | 200 | 313.9 | PASS: shape OK |
| POST | /api/upload | 200 | 275.9 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-124408-93cb8c-generated-for-demo-c08af8 | 200 | 257.5 | PASS: shape OK |
| GET | /api/docs/uploads__smoke-124408-93cb8c-generated-for-demo-c08af8/ingest | 200 | 243.0 | PASS: shape OK |
| GET | /api/chats | 200 | 1561.2 | PASS: shape OK |
| POST | /api/chats | 200 | 60604.2 | PASS: shape OK |
| GET | /api/chats/f7aff2c9-f127-4686-b341-5cf1bc3205d9 | 200 | 444.8 | PASS: shape OK |
| GET | /api/chats/f7aff2c9-f127-4686-b341-5cf1bc3205d9/scene-state | 200 | 707.9 | PASS: shape OK |
| POST | /api/chats/f7aff2c9-f127-4686-b341-5cf1bc3205d9/messages | 200 | 536.4 | PASS: shape OK |
| GET | /api/chats/f7aff2c9-f127-4686-b341-5cf1bc3205d9 | 200 | 285.1 | PASS: shape OK |
| GET | /api/changes | 200 | 460.1 | PASS: shape OK |
| POST | /api/changes/refresh | 200 | 407.0 | PASS: shape OK |
| GET | /api/changes/ser%3Avacation-rental--s400-9872c2%3A3 | 200 | 237.8 | PASS: shape OK |
| GET | /api/changes/ser%3Avacation-rental--s400-9872c2%3A3?page=1 | 200 | 416.8 | PASS: shape OK |
| GET | /api/skills | 200 | 370.7 | PASS: shape OK |
| POST | /api/skills | 201 | 305.6 | PASS: shape OK |
| POST | /api/skills/3c8757d3-d0a1-4d08-a4de-e8b7eb5f1508/run | 200 | 529.5 | PASS: shape OK |
| GET | /api/automations | 200 | 1222.3 | PASS: shape OK |
| POST | /api/automations | 201 | 716.0 | PASS: shape OK |
| GET | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb | 200 | 241.6 | PASS: shape OK |
| PATCH | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb | 200 | 249.3 | PASS: shape OK |
| POST | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb/run | 200 | 658.2 | PASS: shape OK |
| GET | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb/report.md | 200 | 597.5 | PASS: shape OK |
| GET | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb/report.pdf | 200 | 60708.3 | PASS: shape OK |
| DELETE | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb | 204 | 297.4 | PASS: shape OK |
| GET | /api/automations/79b78dc4-8277-4911-b136-255958ef11fb | 404 | 417.8 | PASS: shape OK |
| DELETE | /api/skills/3c8757d3-d0a1-4d08-a4de-e8b7eb5f1508 | 204 | 960.1 | PASS: shape OK |
| GET | /api/skills | 200 | 260.6 | PASS: shape OK |
| POST | /api/findings/run | 200 | 1202.6 | PASS: shape OK |
| GET | /api/findings?doc_id=ifc_bench__ac20-arc | 200 | 269.8 | PASS: shape OK |
| POST | /api/advise | 200 | 1613.3 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/items/3qloCPnZDEQBom1ZjBlwJP | 200 | 339.7 | PASS: shape OK |
| GET | /api/docs/ifc_bench__ac20-arc/tags/D8 | 200 | 405.9 | PASS: shape OK |
| GET | /api/bench | 200 | 120927.7 | PASS: shape OK |
| GET | /api/bench/latest | 404 | 236.6 | PASS: documented fallback: no_bench |
| GET | /api/costs | 200 | 215.1 | PASS: shape OK |
| POST | /api/tts | 200 | 356.1 | PASS: shape OK |
| POST | /api/speech-intent | 200 | 559.2 | PASS: documented fallback: device |
| GET | /api/watch/monitors | 200 | 384.0 | PASS: shape OK |
| POST | /api/watch/sync | 200 | 341.7 | PASS: documented fallback: no_key |
| POST | /api/watch/webhook | 503 | 228.3 | PASS: shape OK |
| WS | /ws | 101 | 585.2 | PASS: WebSocket upgrade and JSON pong |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s400-bracing-elevation | 200 | 214.3 | PASS: S-16 vacation-rental--s400-9872c2 revision 1/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s400-bracing-elevation/source | 404 | 243.8 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s400-bracing-elevation/pages/1.png | 200 | 614.8 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400 | 200 | 247.4 | PASS: S-16 vacation-rental--s400-9872c2 revision 2/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/source | 404 | 222.9 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/pages/1.png | 200 | 7275.6 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400 | 200 | 312.8 | PASS: S-16 vacation-rental--s400-9872c2 revision 3/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/source | 404 | 220.5 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s400/pages/1.png | 200 | 714.9 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s400-bracing-elevation | 200 | 218.6 | PASS: S-16 vacation-rental--s400-9872c2 revision 4/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s400-bracing-elevation/source | 404 | 257.1 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s400-bracing-elevation/pages/1.png | 200 | 688.6 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s401-bracing-details | 200 | 211.4 | PASS: S-16 vacation-rental--s401-9b69ee revision 1/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s401-bracing-details/source | 404 | 255.3 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-s401-bracing-details/pages/1.png | 200 | 614.7 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401 | 200 | 229.2 | PASS: S-16 vacation-rental--s401-9b69ee revision 2/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/source | 404 | 214.7 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170517-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/pages/1.png | 200 | 781.8 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401 | 200 | 231.5 | PASS: S-16 vacation-rental--s401-9b69ee revision 3/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/source | 404 | 225.2 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170518-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401/pages/1.png | 200 | 757.1 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s401-bracing-details | 200 | 223.5 | PASS: S-16 vacation-rental--s401-9b69ee revision 4/4 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s401-bracing-details/source | 404 | 231.3 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170519-issue-for-bid-permit-the-downtowner-arch-exterior-details-sheet-s401-bracing-details/pages/1.png | 200 | 803.9 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170410-submitted-to-state-for-early-start-and-footing-and-foundation-the-downtowner-sheet-a100-demolition-plans | 200 | 223.3 | PASS: S-16 vacation-rental--a100-8f1f68 revision 1/2 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170410-submitted-to-state-for-early-start-and-footing-and-foundation-the-downtowner-sheet-a100-demolition-plans/source | 404 | 211.8 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170410-submitted-to-state-for-early-start-and-footing-and-foundation-the-downtowner-sheet-a100-demolition-plans/pages/1.png | 200 | 1037.2 | PASS: revision page PNG signature OK |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-a100-demolition-plans | 200 | 260.6 | PASS: S-16 vacation-rental--a100-8f1f68 revision 2/2 |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-a100-demolition-plans/source | 404 | 227.0 | FAIL: unexpected HTTP status |
| GET | /api/docs/opening_design__vacation-rental-transfer-20170503-issue-for-permit-a100-demolition-plans/pages/1.png | 200 | 1012.7 | PASS: revision page PNG signature OK |
| POST | /api/chats | 200 | 205.5 | PASS: shape OK |
| POST | /api/chats/241d0263-7377-4842-8a1a-0ab3b915321c/messages | 200 | 3211.4 | PASS: front door hidden; sourced advisor card cites 848/2017 §33 |
| GET | /api/health | 200 | 239.7 | FAIL: unexpected deployed build revision |

Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.
Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.
No chat or uploaded-document delete API exists; created IDs are recorded for the lead.

Created resources:

- upload `uploads__smoke-124408-93cb8c-generated-for-demo-c08af8`: no delete API
- chat `f7aff2c9-f127-4686-b341-5cf1bc3205d9`: no delete API
- skill `3c8757d3-d0a1-4d08-a4de-e8b7eb5f1508`: deleted
- automation `79b78dc4-8277-4911-b136-255958ef11fb`: deleted
- chat `241d0263-7377-4842-8a1a-0ab3b915321c`: no delete API

S-18 disposition: blocked. All 10 original revision PDFs are missing from the image; the build changed from 5373f60 to 0a945e5 during the run. The front-door edit and sourced §33 advisor passed. Local packaging/advisor verification: results/smoke/local-source-advisor.json (11 PASS).
