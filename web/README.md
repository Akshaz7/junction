# Hologram web

Vite + React + TypeScript, Tailwind v4, lucide-react. Node 26; install with `npm ci`.

- `npm run dev` starts the Vite server.
- `npm run build` checks TypeScript and builds `dist/`.
- `npm test` runs the mock contract checks with Vitest.
- `npm run test:e2e` runs one headless Chromium worker. From the repo root, use `scripts/heavy.sh npm --prefix web run test:e2e`. Install the browser once with `cd web && npx playwright install chromium` if it is missing.

You can use an installed Chromium-based browser by setting `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable path.

Until S-03 is available, a small local mock handles `GET /api/docs` and `POST /api/chats/{id}/messages`. The latter emits `status`, `trace`, and `answer` server-sent events. The same handler supports browser-local builds and the Vite HTTP endpoints. All sample content is generated for demo; it is not a benchmark result. Unsupported questions abstain.

Run `VITE_USE_MOCK=false npm run dev` to use the backend. Set `VITE_USE_MOCK=false` when building for a backend deployment too. The Vite proxy sends `/api` and WebSocket `/ws` to `http://localhost:8000`. The temporary chat ID is `demo`; backend chat creation and persistence belong to later rows. Message request fields (`question`, `doc_ids`) are provisional because contract v1 does not specify the request body.

The shell uses hash routes (`#/overview`, `#/chat`, `#/changes`, `#/data`, `#/accuracy`, `#/skills`, `#/automations`), with Chat as the default. Chat and Data retain the local demo flows; the other pages are empty states for their later rows. Desktop navigation uses the reference's expanded rail token and collapses to the 64px rail on tablets. On phones, four tabs and a More menu reach every page.

Reusable Button, Card, Badge, Chip, Input and Tooltip components live in `src/components/ui/`. Button supports the guide's variants, sizes and pill shape; `primary` remains an alias for `default`. Tooltips appear on hover and keyboard focus. The project selector currently holds the single Demo workspace.

`e2e/shell.spec.ts` checks all routes, reload and browser history, phone navigation, the existing demo flow, and ten root CSS variables against `../refs/stoa-hero/theme-tokens.css`. The LEAD runs the browser test outside the worker sandbox. The 3D worker owns `src/viewer3d/`.

UI design follows Stoa's product, with permission from Stoa Technologies Oy. Only supplied CSS design values were copied; no Stoa source, logos, or drawings are included. Product typography loads Inter 400/500/600/700 from Google Fonts with a system sans-serif fallback.
