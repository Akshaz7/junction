# Handoff: WEB (Codex worker)

Row ID: W-06 (attempt 2)
Task: Document viewer beside the chat (desktop: chat left, viewer right, resizable split; phone: full-screen sheet):
- Shows the page image `GET /api/docs/{doc_id}/pages/{n}/image` (docs/API.md; page images now exist for 739 docs, D-05) with pan and zoom (wheel/pinch, drag, double-click zoom, fit button).
- Numbered boxes from `answer.evidence.boxes` (bbox_px in page-image pixels, CONTRACT 5.2) drawn as an SVG overlay that scales with zoom; label = box.label ("1","2",… same numbers as the citations and the 3D labels). Text highlights for citations of kind "text" (bbox_px).
- "n of m" source navigation (previous/next box; the viewer pans to centre the box).
- Licence credit line under the image from doc.json `credit` + `licence` (GET /api/docs/{doc_id}); always visible when a drawing is shown (licence rule).
- Clicking a citation chip in the answer (W-05's `onOpenCitation`) opens the right doc + page and focuses its first box.
- Leave a slot in the viewer toolbar for "Visualise it" (3D is building `VisualiseItButton` in web/src/viewer3d/VisualiseIt.tsx right now; import it if it exists when you finish, otherwise leave a TODO slot; do not edit viewer3d files).
The backend still uses the stub engine: "How many windows are there?" on `cubicasa5k__colorful-11397` returns 13 boxes (fake coordinates spread over the page; good enough to test the overlay). The real engine (E-04) lands soon with real boxes.
Tests: unit tests for the coordinate transform (page px → screen at zoom/pan); e2e `e2e/viewer.spec.ts`: ask the fixture question, click chip 1, the viewer shows the page image, box "1" is inside the viewport, and the credit line is visible.
Rules: only web/ except web/src/viewer3d/ and web/src/main.tsx. Shared dev servers run on :5173/:8000; don't start your own. Playwright can't run in your sandbox; type-check it; the LEAD runs it.
Done test (LEAD runs): `cd web && npm run build && npx vitest run && npx playwright test e2e/viewer.spec.ts e2e/chat.spec.ts`
Last failed attempt (if any): attempt 1 — build OK, vitest 41 pass, chat + shell e2e pass; e2e/viewer.spec.ts 2 FAILED:
  1) viewer.spec.ts:27 "citation opens its page beside chat with numbered evidence, navigation and permanent credit"
     line 41: expect(imageRequests).toHaveLength(1) → Received length 2: the page image URL /api/docs/cubicasa5k__colorful-11397/pages/1/image is requested twice. Likely React StrictMode double-mount in dev or two <img>/preload paths. Fix the double load (one image element, stable key, or cache the object URL); don't just relax the test unless the second request is a real browser cache hit you can prove.
  2) viewer.spec.ts:66 "phone opens a full-screen sheet and returns focus to the citation when closed"
     line 8: expect(page.getByText('Connected workspace', { exact: true })).toBeVisible() → not visible at phone width (the badge is hidden or collapsed in the mobile header). Either show the connection state on phone or make the test wait for a phone-visible indicator; the user should be able to see they're connected on phone too.

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: W-06 implemented citation-linked desktop resizable split/mobile sheet, page pan/wheel/pinch/double-click zoom/fit, numbered SVG boxes/text highlights, source centring/navigation, persistent API credit and VisualiseItButton; npm run build + npx vitest run passed (41 tests), viewer/chat e2e type-checked and listed (3 tests), fixture metadata/PNG HTTP 200; LEAD must run browser e2e outside sandbox per handoff.
RESULT: W-06 attempt 2 defers page loading until after StrictMode effect replay (disposed setup sends no requests; single-request e2e assertion unchanged) and keeps the connection badge visible on phones with a shrinking project selector; npm run build and npx vitest run passed (42 tests), including e2e TypeScript checks; LEAD must run e2e/viewer.spec.ts and e2e/chat.spec.ts outside sandbox per handoff.
