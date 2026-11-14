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
