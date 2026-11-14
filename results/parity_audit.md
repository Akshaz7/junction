# Parity audit: Hologram vs Stoa (read-only audit, 2026-11-14)

Sources: refs/stoa-hero/02-phase-map.md, 03-build-guide.md, 01-design-tokens-and-shell.md; our code in web/src, server/, engine/, pipeline/, ios/. Status key: LIVE works on real data; PARTIAL real but incomplete; FAKE mock/synthetic/decorative; MISSING absent.

## 0. Fake / synthetic inventory (grep results)
| Where | What | Verdict |
|---|---|---|
| web/src/mock/handler.ts:4-47, web/src/lib/api.ts:56,174 | `demo__garden-room` "generated for demo" doc, canned answer, inline SVG; on when `VITE_USE_MOCK` is set or API down (`workspaceApi.isDemo`) | FAKE, only a fallback. Must be off on Vercel build; the "Local demo" badge (App.tsx:53) shows it |
| web/src/components/chat-screen.tsx:306 | "Offline sample content generated for demo" note | FAKE, shown only in demo mode |
| server/changes_source.py:1-90, pipeline/revisions.py, artifacts/revisions/ | Changes feed is built from 3 synthetic v1/v2 pairs of swiss DXF (`swiss_dwellings__site11861-bldg18508-floor50415`, `...site1869-bldg2903-floor13293`, `...site289-bldg536-floor2149`) made by editing the DXF (remove wall, add door, rename room). Payload carries `generated_for_demo: true` | FAKE input; the diff engine (engine/changes.py) is real. The 412-document "New documents" feed has no real source |
| web/src/components/data-screen.tsx:79 | Viewer toolbar search / scan-text / pen icons are `aria-hidden` spans with no handler | FAKE (decorative controls) |
| web/src/components/data-screen.tsx:218-221 | Folder tree = dataset `source` (cubicasa5k, habs...), counts from client docs list; not project folders/disciplines | PARTIAL/fake structure |
| web/src/components/data-screen.tsx:225-229 | File rows show `source · N pages` + licence/credit; no size, date, versions, checkbox does nothing (`file-checkbox` aria-hidden) | PARTIAL |
| web/src/components/workspace-navigation.tsx:5-33 | "Compare documents" nav item is routed to `#/accuracy`; "Library" -> `#/skills`; "Tools" -> `#/automations`; "More" -> `#/accuracy`. Label/route mismatch (Compare opens Accuracy bench) | FAKE (mislabelled) |
| web/src/components/placeholder-page.tsx, App.tsx:73 | PlaceholderPage still imported; every route is now handled so it is dead code, but "Demo workspace" copy remains | Dead, delete |
| web/src/viewer3d/ViewerTestPage.tsx:73-108 | offline fixtures `digital_hub`, `colorful-11397`, "Fake answer" | Test page only; confirm not routed in prod |
| ios/Hologram/AR/DemoScenes.swift | Bundled demo scenes for AR | Check it is a fallback only |
| web/src/components/workspace-navigation.tsx:21-27 | Project switcher is a one-option `<select defaultValue="demo">` "Construction project" | FAKE (single hard-coded project) |
| web/src/components/workspace-navigation.tsx (footer) | Avatar "AK" hard-coded | Cosmetic |

## 1. Real data that can back the features
- Registry: artifacts/registry.jsonl, 14,545 docs. opening_design = 982 docs (660 pdf, 265 dwg, 48 ifc, 9 dxf), from ~40 real projects (data/full/junction-dataset/data/opening_design/<Project>/Transfer/...). Doc ids encode project, issue date and a sender/recipient: `<project>-transfer-<YYYYMMDD>-<from|to-discipline>-<sheet>`.
- No xlsx/docx/csv anywhere in data/full or the preview (find returned none). "Schedules" are PDF sheets only: 18 opening_design ids contain `schedule`, e.g. `opening_design__aalseth-residence-transfer-20190321-to-lumber-yard-latest-plans-with-door-and-window-schedule-sheet-a600-3196-aalseth-lane-schedules`, `opening_design__ctr-most-current-set-full-size-sheets-a700-schedules`, `opening_design__ctr-transfer-20191007-1800-from-struct-schedules-footing-schedule-grp`. Spec-like PDFs: 9 ids contain `spec`, e.g. `opening_design__ctr-transfer-20190813-to-spec-consultant-draft-of-details-ctr-draft-of-details`. Whether any is a text spec book (vs drawing) must be tested with pdfminer; likely none is a 48-page spec like Stoa's "Specification.pdf".
- REAL revisions (same sheet re-issued on several dates), no synthesis needed:
  - `opening_design__sports-complex-transfer-archive-20150811-restroom-markups-locker-rooms-and-restrooms` (7 p) -> `...20150812-...` (6 p) -> `...20150813-restroom-markup-20150812-xsc-progress-set` (6 p)
  - `sports-complex ... phase-2-site-layout--xsc-2nd-phase-site-plan` issued 20150824 / 20150825 / 20150826 (3 versions)
  - `vacation-rental-transfer-20170517/20170518 ... gis-the-downtowner-arch-exterior-details-s400..s403` (4 sheets x 2 dates)
  - `vacation-rental ...20170430 ...-800-framing-markup-od-markup-kdf-comments` and `...-round-2` (+ v1 `20170429-...framing-markup-od-markup`)
  - `crema-cafe-transfer-20170509-markup-to-maira-a-100-floor-plans-v2` and `...a-101-elevations-v2` vs `20170427-pdf-markups-to-maira-a-101-elevations-1-`
  - `ctr-transfer-20190701-from-arch-to-struct-foundation-markups-20190630-ctr-foundation-plans-od-markups` (4 p) -> `...from-struct-to-arch-foundation-markups-reply-20190701...` -> `ctr-transfer-20190707-...marked-up-foundation-plans-...` (4 p)
  - `koshkonong-home ... owner-review--haubenschild-kitchen` 20160205 (4 p) / 20160226 (1 p); `5-unit-conversion ... internal-review--5-unit-conversion-opt-a` 20190311 / 20190312; `sports-complex ... glazing-types--xsc-glazing` 20150615 / 20150625.
  - 14 such multi-date series found by heuristic grouping; 64 ids contain `markup` (e.g. `aalseth-residence-transfer-20190603-to-steel-fabricator-steel-details-20190603-1300-...-kdf-markups`, 7 p, and the 1600 re-issue `...rs-markups`, 7 p). Real "new versions" feed = diff of consecutive dates within a series.
- Disciplines for folders: `opening_design` ids carry discipline in the sender/recipient (86 contain `structural`, 27 `civil`, plus `arch`, `mep`, `electrical`). IFC series: `ifc_bench__digital-hub-arc/-heating/-plumbing/-ventilation`, `ifc_bench__sixty5-arc/-electrical/-facade/-kitchen/-plumbing/-str/-ventilation`, `ifc_bench__dental-clinic-arc/-mep/-str`, `ifc_bench__duplex-arc/-mep`; ifc_models `bsc-clinic-clinic-plumbing`, `bsc-duplex-duplex-mep-20110907`, `bsc-duplex-duplex-plumbing-20121113`. Folder tree: Project (e.g. CTR, Sports_Complex, Digital Hub, Sixty5) > Architecture / Structural / MEP (Plumbing, Ventilation, Heating, Electrical) > files.
- Dates and sizes: dates are in the id (YYYYMMDD) and file mtime; size from `files` on disk. Neither is exposed by `GET /api/docs` (docs/API.md:12-16: only doc_id/source/title/kind/formats/pages/licence/credit/heldout/files).
- Held-out guard: cubicasa5k 4787, swiss_dwellings 1040, ifc_models 98, ifc_bench 25, opening_design 3 are `heldout`; do not show training-only claims on them. Swiss DXF + PDF + PNG triplets are real, can drive "Compare" across formats.
- questions.jsonl (127k Qs, count/area/text) = test truth for the "numbers only from results/" rule; types text=836 only.

## 2. Parity checklist
### 2a. Shell / navigation
| # | Stoa feature | Stoa behaviour | Ours | Needed |
|---|---|---|---|---|
| 1 | Left rail 8 icons: Overview, Chat, Compare documents, Changes, Library, Data, Tools, More | 64px dark rail, active pill | PARTIAL (workspace-navigation.tsx): icons present but Compare/Library/Tools/More point at Accuracy/Skills/Automations/Accuracy (FAKE labels) | Real Compare page; map Library to docs library; Tools menu; More menu |
| 2 | Overview | Project home with recents/changes | LIVE (overview-screen.tsx, lib/overview.ts, GET /api/changes + /api/docs) | Add real recent chats/files |
| 3 | Project mark + org badge | Photo + "C" badge | FAKE: "D" tile, single `<option>` | Real project list from folder roots (CTR, Sports Complex, ...) |
| 4 | Avatar/account | "AK" | FAKE static (no accounts by decision) | Leave, decided |
| 5 | Phone bottom tabs | Tab bar incl. More sheet | LIVE-ish (mobile-navigation, first 4 + More menu) | Match Stoa tab set (Overview, Chat, Changes, Data, More) |
### 2b. Data
| # | Stoa feature | Stoa behaviour | Ours | Needed |
|---|---|---|---|---|
| 6 | Breadcrumb Data > Documents pill | Folder switcher pill | MISSING | Add header pill |
| 7 | Upload button | Uploads file, appears in tree | LIVE (data-screen.tsx:196, POST /api/upload, ingest_job.py, WS doc.new) | Disabled only in demo mode; add upload-as-new-version into a series |
| 8 | Folders tree + new folder + search | Tree with counts; folder-plus; search | PARTIAL: tree of `source`; folder-plus icon decorative (data-screen.tsx:218); search is live | Discipline tree from ids/IFC names; real folder-plus or hide |
| 9 | "All Files" + count (184) | Layers row, total | LIVE (count from /api/docs, 14.5k) | OK |
| 10 | File rows: checkbox, type tile, name, "size · date", "3 versions" | Meta line + revisions | PARTIAL: no size/date/versions; checkbox inert; thumbnail LIVE | Add `size`, `updated_at`, `version_count` to /api/docs; multi-select actions |
| 11 | Pagination | Scroll list | LIVE (PAGE_SIZE) | OK |
| 12 | File viewer header: name, path, Compare chip, version switcher "2 of 3", file-symlink | Header cluster | PARTIAL: name + `/source` + credit popover; Compare chip/version switcher MISSING | Wire to version series (see sec 1) |
| 13 | Toolbar page nav ‹ 1 / N › | Multi-page | PARTIAL: static "1"; chevrons inert, image is page 1 only (`pages/1/image` hard-coded in download link) | Page nav for multi-page PDFs (opening_design 4-13 pages) |
| 14 | Toolbar search | Find text in doc | FAKE icon | pdfminer text layer search + highlight |
| 15 | Toolbar scan-text | OCR/text layer toggle | FAKE icon | Show extracted text/OCR layer |
| 16 | Toolbar pen / highlighter | Annotations | FAKE icon | Client annotation overlay (stored per user in DB) or remove |
| 17 | Download | Download file | PARTIAL: downloads page PNG, not source file (GET /api/docs/{id}/files/{name} exists) | Download original |
| 18 | Zoom -, 65%, + | Zoom | LIVE (zoom state) | OK |
| 19 | 3D / "Visualise it" | (our extra) | LIVE (viewer3d, scene) | n/a |
### 2c. Chat
| # | Stoa feature | Stoa behaviour | Ours | Needed |
|---|---|---|---|---|
| 20 | Greeting "Where shall we start?" + 4 starters (Draft claim, Meeting prep, Plan work phase, Review contract) | Cards fill composer | PARTIAL: starter-grid exists (chat-screen.tsx:303) but our starters are drawing questions; verify the four Stoa titles/icons | Match the 4 titles; back with real skills (skills_routes.py) |
| 21 | Composer, @ mention docs | `@` inserts document | LIVE (chat-screen.tsx:214, 331, 357) | Mention folders/disciplines |
| 22 | Mic | Dictation | LIVE (voice-controls.tsx, /api/speech-intent, Gemini) | OK |
| 23 | New / History / Share | Top-right actions | PARTIAL: chat-header-actions.tsx, chat-history.ts, GET /api/chats LIVE; verify Share creates a real link/PDF (server/report_pdf.py exists) | Share = signed read-only chat URL |
| 24 | Thinking text "Searching: ..." shimmer | Animated status | LIVE (thinking-text.tsx, statuses from SSE) | Server must emit "Searching: <doc names>" statuses; "Searching" grep found no emitter in server/engine |
| 25 | Answer cites several documents in a project-wide answer | Multi-doc retrieval with [n] | PARTIAL: answer-card groups by doc; engine answers per selected doc (engine/answer.py, textqa.py: IFC only). No cross-document retrieval/index | Project-wide retrieval over opening_design PDFs (text layer + readdraw), multi-doc citations |
| 26 | Citation chips [n] | Toggle on/off | LIVE (answer-card.tsx:14) | OK |
| 27 | File chips (Specification.pdf) | Chip per source file | PARTIAL (source-document list, no chip row) | Add chips |
| 28 | Sources pill + count | Expands list | LIVE (answer-card.tsx:55) | OK |
| 29 | Show thought process | Collapsible trace | LIVE (chat-screen.tsx:322 from `trace`) | OK |
| 30 | Spec PDF panel with highlighted passage, "2 of 3" source stepper, page 12/48 | Split view, yellow passage highlight | PARTIAL: document-viewer.tsx has source prev/next + bbox highlight on drawings; passage highlight on text PDFs MISSING (needs text bboxes) | pdfminer word boxes -> highlight `quote`; needs real spec PDF |
| 31 | Disclaimer line | caption | LIVE | OK |
### 2d. Changes
| # | Stoa feature | Stoa behaviour | Ours | Needed |
|---|---|---|---|---|
| 32 | "Checked just now" + Refresh | Rescans | PARTIAL: label hard-coded text (changes-screen.tsx:59); refresh refetches only, no rescan | Real last-checked timestamp; Refresh triggers series re-detect |
| 33 | Search + filter button | Filters list | PARTIAL: search LIVE (changes-screen.tsx:61); filter button sliders MISSING/inert | Filters (discipline, type, date) |
| 34 | Groups Today / New versions (n) / New documents (n) | Date groups | PARTIAL: "Today" is a static heading (:62); counts live but only from 3 synthetic pairs; New documents has no real feed | Group by real dates; feed from series detection over registry/uploads |
| 35 | Version row: tile, name, meta, AI mark + discipline | Rich row | PARTIAL (change-row, no discipline/AI mark data) | Add discipline from id; "Inferred" mark |
| 36 | Detail header: tag New version, "Version 5 -> Version 6", Uploaded date, Discipline | Meta | PARTIAL (comparison-header; labels v1/v2 not dated) | Real version labels/dates |
| 37 | Plain / Wipe / Overlay | 3 modes | LIVE UI (changes-screen.tsx:85-108) on synthetic data | Feed real revisions |
| 38 | Wipe seam, grip, "Drag to compare" hint | Draggable | LIVE (wipe-range) ; hint pill unverified | Add pill |
| 39 | Change boxes toggle + zoom | Boxes overlay | PARTIAL: boxes from truth bboxes; no zoom control seen | Zoom + toggle |
| 40 | Numbered markers + readings pane with paired thumbnails + Export | 3 readings, numbered | PARTIAL: readings + exportChanges LIVE; thumbnails of region unverified | Region thumbnails |
| 41 | Non-DXF/raster comparison (PDF vs PDF) | Real PDF revisions | MISSING: engine/changes.py only works on revision dirs with plan maps (DXF) | PDF raster diff (align + pixel/segment diff) for opening_design series; cite real ids above |
| 42 | Empty state "Nothing open" | Placeholder | LIVE (assumed) | OK |
### 2e. Compare documents / Library / Tools / More
| # | Stoa feature | Ours | Needed |
|---|---|---|---|
| 43 | Compare documents (pick two docs, diff) | MISSING (nav goes to Accuracy). engine/compare.py is model comparison, unrelated | Compare page reusing the Changes comparison component for any two docs |
| 44 | Library | MISSING as Stoa meaning (goes to Skills) | Library of saved/pinned files and reports |
| 45 | Tools | PARTIAL: Automations (automations-screen.tsx, LIVE), Findings, Skills LIVE | Tools hub linking them |
| 46 | More | MISSING (points to Accuracy; mobile More menu lists real pages) | Settings/help/menu |
### 2f. iOS
| # | Feature | Ours | Needed |
|---|---|---|---|
| 47 | App with same tabs | PARTIAL: ios/Hologram is a WebShell + AR (WebShell.swift, LiveSocket.swift) | Check native tab bar parity vs phone-frames |
| 48 | AR "Show on table" with same numbered items | LIVE (AR/ARScreen.swift, HighlightController.swift; models <10 MB shipped, bf61bff). DemoScenes.swift is a fallback | Confirm no bundled-only scenes in release |

## 3. Prioritised build list (top 12)
**Pipeline**
1. Real version series: group opening_design pdfs by project + normalised sheet name + date (list in sec 1), write `artifacts/series/<series_id>.json` {versions: [doc_id, date, size]}. Replaces the 3 synthetic swiss pairs. (pipeline/revisions.py successor)
2. Discipline + folder metadata per doc: parse project and discipline from opening_design ids and IFC names (-arc/-str/-plumbing/-ventilation/-heating/-electrical/-mep); add size and date. Output into registry or a side file.
3. PDF text layer + word boxes (pdfminer.six) for all opening_design PDFs; needed for search, spec passage highlight, project-wide Q&A.
**Engine**
4. PDF revision diff (raster align + connected-component boxes, optional vision read) producing the same change schema as engine/changes.py, so real series show numbered change boxes.
5. Project-wide retrieval: question -> candidate docs via text layer/plan maps -> per-doc answer -> merged answer citing several docs; emit "Searching: <names>" status events.
**Server**
6. Extend `GET /api/docs` (and /api/docs/{id}) with `size`, `updated_at`, `folder`, `discipline`, `versions[]`; add `GET /api/folders` tree; serve source file download.
7. Changes feed from series detection (+ uploads that match a series become "new version"); real `checked_at`, Refresh endpoint re-scans; date groups; discipline per entry; drop `generated_for_demo` from the live path.
8. `GET /api/docs/{id}/text?page=` and search endpoint for in-document find with boxes.
**Web**
9. Fix nav: real Compare documents page (reuse changes comparison component), Library, Tools hub, More menu; remove PlaceholderPage; project switcher from real projects. (workspace-navigation.tsx, App.tsx, router.ts)
10. Data screen: discipline tree, file rows with size/date/"N versions", header pill, Compare chip + "2 of 3" version switcher, multi-page nav, functioning search/scan-text/highlighter/pen or remove the decorative icons (data-screen.tsx:79).
11. Chat: four Stoa starters, file chips row, spec/text PDF panel with yellow passage highlight (document-viewer.tsx), Share link. Changes: date groups, filter popover, "Drag to compare" pill, zoom.
**iOS**
12. Verify native tab/screens against phone-frames and that AR uses the same series/items as web; make sure demo scenes and `VITE_USE_MOCK` are not in the shipped builds (also web Vercel env).

## 4. Honesty notes
- The Changes screen is the single largest "fake" surface: UI is real, but the data is 3 generated DXF pairs. Real series exist (sec 1) but need pipeline items 1, 3 and engine item 4.
- Stoa's spec-PDF scenes cannot be matched with a true spec book from this dataset (no text spec found); use real text-heavy PDFs from opening_design (verify with pdfminer) and label honestly.
