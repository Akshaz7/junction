# Handoff: WEB (Codex worker)

Row ID: W-05 (attempt 1)
Task: Chat screen against the REAL backend (S-03 is done: read docs/API.md; the API runs on http://localhost:8000, proxied by Vite at /api and /ws; start it yourself for local checks with `uv run uvicorn server.app:app --port 8000` only if nothing is on :8000 — `make db-up` first; the database is seeded). Keep the mock as a fallback when the API is unreachable.
- Start screen with four starter cards (as in the reference pack; English copy, our voice per CONTRACT 5.8 and refs/stoabuild-full-text.md), e.g. "Count something on a plan", "Find a room's area", "Where is it on level N?", "What does this drawing say about …".
- Composer with an `@` document picker (type @ to search /api/docs; selected docs become chips; sent as doc_ids). Create a chat with POST /api/chats, then POST /api/chats/{id}/messages and read the SSE stream.
- Live status lines from `status` events ("Thinking…", "Exploring document: <name>"), trace lines feed "Show thought process".
- Answer: key fact bold (markdown bold from text_md), citation chips [1] [2] inline after sentences, "Where it is set out" list, "Sources (n)", "Show thought process", a cost chip (answer.cost.usd_total formatted like "$0.0000" or "< $0.0001", tooltip with calls), "AI can make mistakes. Verify important information." under the composer.
- Abstained answers render the plain sentence with no chips.
- Clicking a chip must call a prop/callback `onOpenCitation(citation)` (W-06 builds the viewer next; for now open nothing or log).
The backend currently uses a STUB engine: "How many windows are there?" on doc `cubicasa5k__colorful-11397` returns 13 boxes; other questions abstain. That is enough for the e2e test.
Playwright can't run in your sandbox: write `e2e/chat.spec.ts` (asks the fixture question against the real API, sees the bold answer, at least one citation chip and the cost chip); make it type-check; the LEAD runs it with the API up.
Rules: only edit web/ except web/src/viewer3d/ and web/src/main.tsx (LEAD wired a dev route there). Never copy code from refs/stoa-hero/source/.
Done test (LEAD runs, API up): `cd web && npm run build && npx vitest run && npx playwright test e2e/chat.spec.ts`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: W-05 implemented real chat creation/content+doc_ids SSE, four starters, searchable @ document chips, live status/trace, citation callbacks, sources, cost tooltip, plain abstentions and labeled offline fallback; npm run build and npx vitest run pass (29 tests), direct localhost:8000 create/stream/stored fixture answer check passes; e2e/chat.spec.ts written and type-checked, browser execution remains for LEAD outside sandbox. No commits; web/src/main.tsx and web/src/viewer3d/ untouched by WEB.
