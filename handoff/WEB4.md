# WEB4 (Codex) — current row

ROW: W-34 no decorative (fake) controls — Ash: "a feature that doesn't work end to end must not be shown"
Audit every visible control in web/src that has no working handler (results/parity_audit.md section 0 lists some; re-check, it is older than the code). For each: make it work with an existing real API/handler if a few lines do it, else remove it. Known candidates:
- Data viewer toolbar search / scan-text / pen icons (aria-hidden spans, no handler): search = filter the open document's page text if the API gives text (check docs/API.md), else remove.
- File-row checkbox that does nothing: make it select rows for "Ask about selected" (open chat with those doc ids, the existing ?doc= path supports one; check whether chat supports several) or remove.
- Project switcher one-option select: replace with a plain project name label (no fake dropdown).
- Hard-coded avatar "AK": keep only if it has no menu promise; no dead click.
- placeholder-page.tsx: delete if no route uses it (help is mounted); keep tsc clean.
Write a list in this file: control → kept (how it works) / removed.
Allowed: web/src/** except viewer3d/ and chat-screen.tsx, answer-card.tsx (others are working there).
Done test: cd web && npx tsc --noEmit && npx vitest run (0 failures), plus a click test for each kept control.
Never commit. Write one line at the end: RESULT: ...

W-34 control audit (current source, excluding the files reserved for other workers):
- Data toolbar search → kept: opens page-text search; reads the existing text-<page>.json / planmap artifacts and filters real extracted text. Reports missing text honestly; changing page reloads text.
- Data toolbar scan-text / pen icons → removed: no handlers in this viewer.
- Data page chevrons → kept: real previous/next buttons update preview, page number, search text and download URL; disabled at page boundaries.
- Data download, zoom −/+, Fit, Ask, credit disclosure and Close → kept: current-page PNG link, real zoom state/reset, existing onAsk callback, native details disclosure and existing close handler. Click-tested in data-controls.test.tsx.
- File-row checkbox → removed: decorative span; no row-selection state or multi-selection action.
- Folder-plus, file-row ellipsis, mobile folder-back/filter icons → removed: no working actions. Existing folder tree/select and document-name search remain functional.
- Project dropdown → removed: replaced with static Construction project label (compact rail mark retains accessible project text).
- AK avatar → kept: static span; no focus target, link, menu cue or click handler.
- Notification bell, Documents breadcrumb dropdown chevron, drawing-source dropdown chevron → removed: no menu/actions behind them.
- Drawing viewer Open source page → kept only after an actual image URL exists; avoids a dead anchor during loading/error.
- Data Visualise it → kept only for a confirmed scene; removed the missing-scene button that merely displayed an unavailable message. Existing 2D/3D controls and native AR action use their working handlers.
- PlaceholderPage → removed with its import and unreachable fallback; every valid route already mounts its real screen, including Help.
- Other navigation, upload, chat-header, Changes/Compare, Library/Skills/Automations, Findings, Accuracy, Help, voice, evidence/annotation and export controls → kept: existing links, form submissions, state changes or real API handlers; no additional inert controls found within allowed scope. chat-screen.tsx, answer-card.tsx and viewer3d/ were untouched.

Files: web/src/App.tsx; web/src/components/{data-screen.tsx,data-screen.css,data-controls.test.tsx,document-viewer.tsx,workspace-navigation.tsx,placeholder-page.tsx (deleted)}; web/src/styles/app.css.
Validation: cd web && npx tsc --noEmit && npx vitest run — passed on first run, 55 files / 314 tests, 0 failures. New jsdom click tests exercise retained Data controls and assert fake controls are absent. No browser/Playwright run was needed for this done test.
RESULT: W-34 passed; decorative controls removed, real page-text search and page navigation wired, static project/avatar labels retained; tsc and all 314 Vitest tests pass; no commit.
