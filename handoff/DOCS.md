# DOCS (Codex): row X-11. API + models docs current
Scope: docs/API.md and docs/MODELS.md only.
1. docs/API.md: document every route that exists now in server/*_routes.py and server/app.py. Read the code, never guess. New since the last update: /api/folders, /api/docs/{id}/source, /api/docs/{id}/ingest, POST /api/changes/refresh, compare, linked items/tags, advise (ops hide/restore/move/material/undo + detail), bench list/latest, health fields (build_rev, uptime_s, models_ok), RATE_LIMIT_PER_MIN, and the upload error codes 413/415. Give each one's request, response and errors.
2. docs/MODELS.md: list every model and provider in engine/models/models.yaml with its task chain and price, plus:
   - datasets: CubiCasa5K (CC BY-NC-SA 4.0), FloorPlanCAD (Voxel51 mirror; its card says CC BY-NC 4.0 while the metadata says CC BY-SA 4.0, so treat it as NC), synthetic plans (generated for demo)
   - fine-tunes: RT-DETR PekingU/rtdetr_r50vd (Apache-2.0) and the ResNet34-UNet (Yytsi weights; check train/ for the source and licence)
   - the licence consequences for the fine-tuned weights
   - the ifcopenshell (LGPL) and usd-core licences used in the deploy image
Do not commit. Append a RESULT: line.
NEEDS: VISION/LEAD: train/manifest.json lists FloorPlanCAD only as CC BY-SA 4.0; record the Voxel51 card's conflicting CC BY-NC 4.0 narrative and conservative noncommercial treatment (documented in docs/MODELS.md).
RESULT: X-11 PASS — docs/API.md covers all 45 declared HTTP/WS routes with requests, responses and errors; docs/MODELS.md covers 9 providers, 21 configured prices, 13 exact task chains, training/dataset terms and deploy-library licences. Local done check `.venv/bin/python /tmp/junction_docs_done.py` and `git diff --check -- docs/API.md docs/MODELS.md handoff/DOCS.md` passed; no commit.
