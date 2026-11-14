# Hologram × Aiven

**Aiven PostgreSQL stores Hologram's shared workspace data.** The backend uses the managed `hologram-pg` database for documents, chats, messages and answers. Its live-event code uses PostgreSQL notifications to send updates to connected web and iOS clients.

**Where it is set out:**

- `deploy/README.md` records the created and seeded `hologram-pg` service and a local API container check against that database.
- `server/config.py::database_url` reads the database setting; `server/db.py::get_pool` opens an asyncpg pool and `db_ok` checks connectivity.
- `server/seed.py::seed_documents` loads the document registry. `server/chats_routes.py::create_chat`, `get_chat` and `ask` persist and retrieve conversations and answers.
- `server/live.py::Hub._run` listens for PostgreSQL notifications, while `publish` sends them and `Hub.broadcast` forwards events to WebSocket clients. `server/migrations/` defines the stored data and notification setup.

**Recorded evidence:** deployment evidence is the local container check documented in `deploy/README.md`; it reports a healthy API and database connection against Aiven. No Aiven availability, latency or cost measurement was found in `results/`, so this page publishes no such number. The deployment note is a recorded check, not a fresh connectivity test in this documentation task.

Screenshot placeholder: `docs/sponsors/img/aiven.png` — LEAD to capture the database service and connected Hologram workspace without credentials.

**Honest limits:** `deploy/README.md` says the Aiven Runtime API service has not yet been created. Managed PostgreSQL use is supported; a deployed Runtime API and its WebSocket behavior are not demonstrated. `server/live.py::publish` can broadcast within the local server when the database listener is unavailable; that fallback does not prove database-backed cross-instance delivery.
