# Hologram web

Vite + React + TypeScript, Tailwind v4, lucide-react. Node 26; install with `npm ci`.

- `npm run dev` starts the Vite server.
- `npm run build` checks TypeScript and builds `dist/`.
- `npm test` runs the mock contract checks with Vitest.
- `npm run test:e2e` runs one headless Chromium worker. From the repo root, use `scripts/heavy.sh npm --prefix web run test:e2e`. Install the browser once with `cd web && npx playwright install chromium` if it is missing.

You can use an installed Chromium-based browser by setting `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable path.

Until S-03 is available, a small local mock handles `GET /api/docs` and `POST /api/chats/{id}/messages`. The latter emits `status`, `trace`, and `answer` server-sent events. The same handler supports browser-local builds and the Vite HTTP endpoints. All sample content is generated for demo; it is not a benchmark result. Unsupported questions abstain.

Run `VITE_USE_MOCK=false npm run dev` to use the backend. Set `VITE_USE_MOCK=false` when building for a backend deployment too. The Vite proxy sends `/api` and WebSocket `/ws` to `http://localhost:8000`. The temporary chat ID is `demo`; backend chat creation and persistence belong to later rows. Message request fields (`question`, `doc_ids`) are provisional because contract v1 does not specify the request body.

The 3D worker owns `src/viewer3d/`. Only a README is scaffolded here.

UI design follows Stoa's product, with permission from Stoa Technologies Oy. Only supplied CSS design values were copied; no Stoa source, logos, or drawings are included. Typography uses Inter when available locally and system sans-serif otherwise.
