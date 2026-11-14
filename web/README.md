# Hologram web

Vite + React + TypeScript, Tailwind v4, lucide-react. Node 26; install with `npm ci`.

- `npm run dev` starts the Vite server.
- `npm run build` checks TypeScript and builds `dist/`.
- `npm test` runs API, stream, evidence rendering and mock contract checks with Vitest.
- `npm run test:e2e` runs one headless Chromium worker. From the repo root, use `scripts/heavy.sh npm --prefix web run test:e2e`. Install the browser once with `cd web && npx playwright install chromium` if it is missing.

You can use an installed Chromium-based browser by setting `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable path.

The app connects to the real backend by default. `GET /api/docs` loads its grouped document list; the first question creates a chat with `POST /api/chats`, and messages send `{content, doc_ids}` to `POST /api/chats/{id}/messages`. Status, trace, answer and error events are read from its SSE stream. Follow-up questions reuse the chat; New chat creates a fresh conversation. Type `@` to search document titles, IDs and sources, then click or use arrow keys and Enter to select a document. Remove chips to restore all-document context.

If the API is unreachable when loading documents, the app uses a clearly labeled offline fixture. It never replaces a failed answer for a real document with a generated answer. `VITE_USE_MOCK=true` forces the offline demo; `VITE_USE_MOCK=false` requires the backend and disables automatic fallback. All offline sample content is generated for demo, not a benchmark result. Unsupported questions abstain. Vite proxies `/api` and WebSocket `/ws` to `http://localhost:8000`.

`App` accepts an optional `onOpenCitation(citation)` callback. Inline citation buttons and source controls pass the full CONTRACT 5.7 citation to it; the drawing viewer is assigned to W-06. Cost chips show the API's `usd_total`, with model call details on hover/focus. Backend answers marked `trace.stub` are labeled generated for demo.

With the seeded API running, from `web` run `../scripts/heavy.sh npx playwright test e2e/chat.spec.ts` to check the real fixture question, selected document IDs, bold answer, citation, cost, trace, follow-up persistence and abstention. The LEAD runs Playwright outside the worker sandbox. `npm run build` also type-checks the browser tests. CubiCasa5K drawings are CC BY-NC-SA and for non-commercial use only; the UI carries document credits and licences on the Data page.

The shell uses hash routes (`#/overview`, `#/chat`, `#/changes`, `#/data`, `#/accuracy`, `#/skills`, `#/automations`), with Chat as the default. Chat and Data use the backend with an offline demo fallback; the other pages are empty states for their later rows. Desktop navigation uses the reference's expanded rail token and collapses to the 64px rail on tablets. On phones, four tabs and a More menu reach every page.

Reusable Button, Card, Badge, Chip, Input and Tooltip components live in `src/components/ui/`. Button supports the guide's variants, sizes and pill shape; `primary` remains an alias for `default`. Tooltips appear on hover and keyboard focus. The project selector currently holds the single Demo workspace.

`e2e/shell.spec.ts` checks all routes, reload and browser history, phone navigation, the existing demo flow, and ten root CSS variables against `../refs/stoa-hero/theme-tokens.css`. The LEAD runs the browser test outside the worker sandbox. The 3D worker owns `src/viewer3d/`.

UI design follows Stoa's product, with permission from Stoa Technologies Oy. Only supplied CSS design values were copied; no Stoa source, logos, or drawings are included. Product typography loads Inter 400/500/600/700 from Google Fonts with a system sans-serif fallback.
