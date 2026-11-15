# Deploy (row S-05 prep)

Status 2026-11-14: database created and seeded, image builds and runs against it. The Runtime service is NOT created yet.

## What exists on Aiven (project `akshatsunita07-650d`)
| Service | Plan | Cloud | Cost |
|---|---|---|---|
| `hologram-pg` (PostgreSQL 16.16, user `avnadmin`) | hobbyist (1 CPU, 1 GB, 8 GB disk) | do-fra (Frankfurt) | $12/mo (billed hourly) |
| `pg-39dadbc6` (PostgreSQL 18, plan developer-1) | not created by SERVER; left untouched | do-fra | unknown |

`hologram-pg` has migrations 001-002 applied and 773 documents seeded. Its URI is in `.env` as `DATABASE_URL` (never printed or committed).
The CLI token cannot read service passwords (the API returns `<redacted>`), so the `avnadmin` password of `hologram-pg` was set to a
known random value with `avn service user-password-reset`. Use it from `.env`. Re-seed or migrate any time with:
`PYTHONPATH=. .venv/bin/python -m server.migrate && PYTHONPATH=. .venv/bin/python -m server.seed`
(plain `uv run` can block for minutes while another process holds the uv lock).

## Aiven Runtime (service type `application`) - findings
Source: aiven.io/docs/products/runtime (the older `/products/application` URLs are gone).
- It builds from a **GitHub repository** (Aiven Platform GitHub App). Registry images are not supported. No auto-deploy on push: redeploy by hand ("Deploy latest commit" in the console).
- Our repo `github.com/Akshaz7/junction` is public. Someone with admin rights on the Aiven organisation must install the Aiven GitHub App in the console once (Runtime -> connect GitHub account). That gives the `VCS_INTEGRATION_ID` and `REMOTE_REPOSITORY_ID` needed below. **This is the one manual step (Ash).**
- The pushed `main` must contain `deploy/Dockerfile`, `server/`, `engine/` (the LEAD pushes).
- Ports: HTTP only (HTTPS on 443 terminates at Aiven, forwarded to the container port). gRPC, HTTP/2 and TCP are not supported. **WebSocket support is not documented**: test `/ws` right after the first deploy (see below). If it fails, the fallback is polling `GET /api/chats/{id}` every 2 s, or hosting the container elsewhere (Fly.io/Render/Cloud Run) with the same image.
- Env vars: `application.environment_variables` (list of `{key,value,kind: variable|secret}`; an update replaces the whole list).
- Plans in EU regions (`aws-eu-central-1` Frankfurt, `aws-eu-west-1`, `google-europe-west1/2/3/4`): `startup-10-256` $7/mo (256 MB), `startup-20-512` $12/mo, `startup-50-1024` $28/mo. **`do-fra` has no Runtime plans**, so the app runs in `aws-eu-central-1` and reaches the DB over the public endpoint with TLS (the DB allows 0.0.0.0/0; auth is by password). Measured: the container uses about 45 MB, so `startup-10-256` should do; use `startup-20-512` if it is OOM-killed.
- Estimated total: $12 (PG) + $7 (Runtime) = about $19/mo, so a weekend costs well under $2.

## Exact deploy steps (when W-05/W-06/T-04 are in and S-04 is merged)
```bash
set -a; . ./.env; set +a
# 1. one-time, manual: install the Aiven GitHub App on the Akshaz7 account in the Aiven console, then get the two IDs
#    (console: Runtime -> create app shows them, or the Aiven API vcs-integrations endpoint)
# 2. create the app (env vars include the DB URL as a secret)
avn service create hologram-api --project "$AIVEN_PROJECT" -t application --cloud aws-eu-central-1 --plan startup-10-256 \
  -c application.source.vcs_integration_id=$VCS_INTEGRATION_ID \
  -c application.source.remote_repository_id=$REMOTE_REPOSITORY_ID \
  -c application.source.repository_url=https://github.com/Akshaz7/junction \
  -c application.source.branch=main \
  -c application.source.build_path=. \
  -c application.source.containerfile_path=deploy/Dockerfile \
  -c 'application.ports=[{"name":"http","port":8000,"protocol":"HTTP"}]' \
  -c "application.environment_variables=[{\"key\":\"RATE_LIMIT\",\"value\":\"1\",\"kind\":\"variable\"},{\"key\":\"DATABASE_URL\",\"value\":\"$DATABASE_URL\",\"kind\":\"secret\"}]"
avn service wait hologram-api --project "$AIVEN_PROJECT"
# 3. public hostname: console -> hologram-api -> Connection information. Then:
curl -s https://<host>/api/health        # {"ok":true,"db":true}
# WebSocket check (needs `uvx websocat` or any ws client):  wss://<host>/ws  -> send {"type":"ping"} -> expect {"type":"pong"}
# 4. redeploy after a push: console "Deploy latest commit".
```
Alternative to the secret above: `avn service integration-create -t application_service_credential -s hologram-pg -d hologram-api --user-config-json '{"service_type":"pg","exposed_values":{"connection_string":{"environment_variable_key":"DATABASE_URL"}}}'`.
Web (Vercel) needs the API origin as its API/WS base URL; CORS is already open (`*`).

## Open problems for the deploy
1. **Artifacts are not in the image** (`.dockerignore` excludes `artifacts/`, `data/`; they are git-ignored). The deployed API therefore has no page images, plan maps or scenes. Options: bake the small demo subset in (copy a few hundred MB into the image from a committed or CI-downloaded folder), or serve them from object storage (Cloudinary/Drive per the DATA rows) and have the API redirect. Decide in S-05; it needs DATA's list of demo docs.
2. Migrations run at API start (`lifespan`), so no separate migration step is needed. Seeding is manual: `python -m server.seed` against the Aiven `DATABASE_URL` (done once for now).
3. Rate limit is in-memory per container and keyed on the first `X-Forwarded-For` entry; fine for one instance.

## Local image check (done)
`scripts/heavy.sh docker build -f deploy/Dockerfile -t hologram-api .` (424 MB) then
`docker run -d -m 512m -p 8001:8000 -e DATABASE_URL hologram-api` against the Aiven DB: `/api/health` returned `{"ok":true,"db":true}`, `/api/docs` returned 773 docs, process runs as non-root `app`, memory about 45 MB. Container stopped and removed.


## 2026-11-14 08:55 attempt (LEAD)
`hologram-api` (aws-eu-central-1, startup-10-256) was created with only `repository_url` (public repo). Aiven accepted it but the build ended `FAILURE` / deployment `ABORTED` with no logs, and `-c application.source.commit_sha=…` is refused: "commit_sha requires a VCS integration: set vcs_integration_id and remote_repository_id". The same Dockerfile builds from a fresh public clone and runs healthy locally against hologram-pg. After installing the GitHub App: `avn service update hologram-api -c application.source.vcs_integration_id=… -c application.source.remote_repository_id=…`, then power it on (`avn service update hologram-api --power-on`).

- 09:40: Aiven API has no create endpoint for VCS integrations (OpenAPI lists only GET .../application/vcs-integrations, which returns an empty list), so this step is console-only.

## Uploads: live ingestion in the deploy image
`POST /api/upload` runs real ingestion in a subprocess (`server/ingest_job.py`), so an OOM kills only the job. `INGEST_MODE=vlm` (set in the image) uses `server/vlm_planmap.py`: the page is rendered (pypdfium2 / Pillow), read once through `call("read_drawing")` (Runware gemini fallback today), geometry-checked with `vision/verify.py` (`tiny`, `dup`), validated against `vision/planmap_schema.json`, then extruded to `scene.json`/`scene.glb`. Pages over 3000 px also get 2x2 tile passes for small items. Scale: printed dimensions read by the model, else the 0.9 m door prior (confidence 0.3). Walls are derived from room outlines (flagged `props.derived`, `DERIVE_WALLS=1`). PDF text with pixel boxes goes to `text.json`/`text-N.json` (pdfminer.six).
Why VLM and not local models: the service has 256 MB RAM (`startup-10-256`) and no weights are committed (torch/onnx weights are git-ignored). Peak container memory measured at about 195 MB during an upload, no OOM, but this is borderline: move to `startup-20-512` for headroom.
Measured (results/upload_live.json): 1-page cubicasa PNG ready in 17 s for $0.04; opening_design PDF sheet ready in 30 s for $0.10.

Deps added to the image: pillow, numpy, pypdfium2, pdfminer.six, ezdxf, trimesh, shapely (no torch, no scipy). Image about 800 MB uncompressed.

Persistence: container disk is ephemeral. Every derived file plus the original (`__original__/<file>`) is mirrored to table `doc_artifacts` (migration 005, `bytea`, 60 MB per-doc cap, `MAX_DOC_BYTES`) after ingestion and restored lazily on first access and in a startup background task. Verified: a fresh container restored earlier uploads from PostgreSQL.

Project search: `python -m engine.project_index build` runs at image build over baked artifacts (`/app/artifacts/index/project_index.pkl`, app-owned and writable). The index is loaded at startup, each finished upload is upserted, and uploads restored from PG are re-indexed at startup.

Switches: `INGEST_MODE` (vlm|full), `DERIVE_WALLS`, `MAX_VLM_PAGES` (4), `PAGES_MAX_SIDE` (4096), `TEXT_PAGE_WORDS`, `TEXT_PAGE_COVER`, `MAX_DOC_BYTES`.
Not available in the deploy image: IFC conversion (stored only, status partial), SVG, DWG, USDZ/AR for uploads (needs usd-core).

## Upload ingestion by format (deploy image)
- PDF / PNG / JPG: pages, text layer, VLM plan map, extruded scene.glb (+ scene.usdz), all persisted to `doc_artifacts`.
- DXF: Swiss Dwellings layer names use the exact DXF reader; any other DXF is rendered and read by the VLM (then extruded).
- IFC (F-IFCBIG): property indexing runs first, without geometry, for uploads up to **100 MiB** (the upload limit). `pipeline/ifc_index.py` bypasses representation and placement entities using the file's IFC schema, retaining object IDs, storeys, units, typed property measurements and Qto quantities. Native property caches are discarded after each batch of 128 objects; the complete JSON index is assembled atomically on disk. Counts and recorded measurements are readable and persisted before the optional 3D phase finishes.
- The background 3D phase streams triangles to GLB with one geometry thread. Every IFC phase runs in a separate process with a default **320 MiB RSS budget**, Linux native allocation guard, and a time limit (index 180 s, scene 120 s, previews 45 s, AR 30 s; total job budget 270 s within the API watchdog's 300 s). The supervisor reserves another 64 MiB from the cgroup's available memory. A geometry failure preserves the property index and returns `partial`, with the exact limit and what remains usable. Geometry-dependent quantities stay unknown; the engine does not estimate missing indexed measurements.
- Configuration: `INGEST_IFC_MAX_MB` (decimal MB, default 104.8576), `IFC_WORKER_MEMORY_MB` (MiB, default 320), `IFC_INDEX_TIMEOUT_S` (default 180), `IFC_SCENE_TIMEOUT_S` (default 120). Keep the worker budget below the container limit minus API/supervisor headroom. The 512 MB deployment is documented below; no service-plan change is required for property indexing.
- Large originals are saved and restored as 4 MiB database chunks (`__source_chunks__/…`), with a final size/SHA-256 manifest. Existing unchunked originals remain readable. Derived artifacts retain their existing size cap. Only metadata and derived artifacts are persisted again after indexing; the original is saved once at upload.

### Memory on Aiven (512 MB plan), measured 14 Nov
Local `docker run --memory=512m`, no model keys, image 336 MB (1.55 GB unpacked on disk). `pipeline/ifc_scene.convert_py` runs the geometry iterator with
one thread (`IFC_CONVERT_THREADS`, default 1) and keeps float32 arrays; with 4 threads a 9.6 MB IFC peaked at about 830 MB and was OOM-killed.
Now: 9.6 MB IFC ready in 55 s (peak 306 MB), 12 MB IFC in 21 s (peak 296 MB). The API idles at about 55 MB. PNG/DXF extrusion needs a VLM key to read the plan; without one they end "ready" with no plan map.

## Dataset artifacts in PostgreSQL (HIDE_EMPTY_DOCS)

The image bakes only `deploy/demo_artifacts`. All other dataset docs keep their previews, plan maps, elements, text and lean 3D in the `doc_artifacts` table and are restored to `/app/artifacts` on first request. `HIDE_EMPTY_DOCS=1` (set in the Dockerfile) lists only docs that have a preview and data in PG or on disk; questions about a doc with no data refuse in under 1 s at $0 (`FAST_REFUSE`, default on).

Load (needs `TARGET_DATABASE_URL`, never printed; dry run is the default):
`python3 deploy/load_artifacts_pg.py --docs-file <deployed /api/docs json> --apply`

Measured: 353 docs, about 700 MB in PG. Restored docs accumulate on the container's ephemeral disk.


## Current plan: startup-200-10240 (10 GB RAM, multi-CPU) - 15 Nov

The service now runs on `startup-200-10240`; the 256/512 MB figures above are historical. Settings baked into `deploy/Dockerfile`:
- `uvicorn --workers 3` (`WEB_CONCURRENCY=3`): one slow request or blocking call no longer stalls everyone. Live sync is safe across workers because events fan out through PostgreSQL NOTIFY; caches live on disk or in PG. Only one worker (flock on `$RESULTS_DIR/hologram-startup.lock`) runs migrations, seeding and the upload restore at boot. The in-memory rate limiter is per worker (effective limit is up to 3x).
- DB pool per worker: `DB_MIN_CONN=2`, `DB_MAX_CONN=6` (3 workers + 3 LISTEN connections stay near 21 connections; raise only if the PG plan allows).
- IFC budgets: `IFC_WORKER_MEMORY_MB=4096`, `IFC_INDEX_TIMEOUT_S=300`, `IFC_SCENE_TIMEOUT_S=420`, `IFC_INPROC_MAX_MB=60`; whole-job watchdog `INGEST_TIMEOUT_S=900` (was a hard 5 min; the job deadline is this minus 30 s). `HEAVY_SLOTS=3` ingests at once across workers.
- `POST /api/upload` returns as soon as the file is validated and the row exists; saving the original to PostgreSQL and the ingest both run in background tasks. Poll `GET /api/docs/{id}/ingest`.

### Update (plan startup-400-8192: 4 CPU, 8 GB)
`--workers 4`, `INGEST_CONCURRENCY=4` per worker with `HEAVY_SLOTS=4` as the real cap (box-wide), IFC jobs capped at `IFC_CONCURRENCY=2` (cross-process flock slots), `IFC_WORKER_MEMORY_MB=2500`. Uploads wait in a queue: `GET /api/docs/{id}/ingest` returns `queue_position` while queued. On boot the leader worker restores uploads from PG first, then re-queues every ingest that was running/queued when the old container stopped (`requeue_lost_ingests`).
