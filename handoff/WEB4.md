# WEB4 (Codex) — current row

ROW: W-30 empty states with a next step (no dead ends)
Goal: every empty state gives one working action, in Stoa's copy style (short, plain):
- Data, no search results: "No documents match" + Clear search button (+ Upload, which opens the existing upload dialog).
- Changes, empty feed: Upload action; Clear filters enabled whenever any filter (type/folder too) is set.
- Library > Automations with no documents: one line of guidance + Upload.
- Compare, no versions: Upload a new version action; after zero differences: "Ask about this drawing" opens chat with the doc.
- History popover empty: "New chat" button.
Each action must call the real existing handler (no new fake flows). Add one vitest per empty state that clicks the action and asserts the handler ran.
Allowed files: web/src/components/{data-screen,changes-screen,library-screen,compare-screen,workspace-navigation,chat-screen}.tsx and their .css/.test.tsx, plus this file.
Done test: cd web && npx tsc --noEmit && npm test -- --run (all pass).
Write one line at the end: RESULT: ...

NEEDS: W-30 History is in web/src/components/chat-header-actions.tsx, outside this row's allowed files. Add a New chat button beside "No saved chats yet." calling the existing setOpen(false), setToast(''), onNew() handler, with a click test.
NEEDS: W-30 component click tests need web/vite.config.ts to include src/**/*.test.tsx (currently only .test.ts) and a DOM test environment dependency (jsdom or happy-dom) in web/package.json/package-lock.json; both are outside WEB4 scope.
RESULT: W-30 permitted changes implemented in data/changes/library/compare/chat/workspace-navigation components and their CSS; Data search clears or uploads, Changes uploads and clears type/folder-only filters, Library Automations guides to upload, Compare uploads or opens Chat with its drawing. Done command passed (tsc; 46 files/273 tests); all 9 new click tests in data-screen.test.tsx passed separately with /private/tmp/junction-web4-vitest.config.mts and temporary jsdom 31.0.1. Row remains incomplete pending the two NEEDS above; no commits or out-of-scope source edits.

---
ROW: W-30b finish (LEAD widened scope)
LEAD enabled .test.tsx tests: web/vite.config.ts now includes src/**/*.test.tsx and jsdom is a devDependency. Full suite now: 1 failure:
data-screen.test.tsx "opens chat with the drawing after a comparison finds no differences": hash becomes #/chat?doc=<id> but .selected-documents stays empty. Find out whether ChatScreen really ignores ?doc= on a hash change (real bug → fix in chat-screen.tsx / App.tsx) or the test renders the wrong tree (fix the test). A real user path must work: Compare → "Ask about this drawing" → chat opens with that drawing selected.
Also: History empty popover "New chat" button in web/src/components/chat-header-actions.tsx calling the existing setOpen(false), setToast(''), onNew(), with a click test.
Allowed files: the W-30 list plus web/src/App.tsx, web/src/components/chat-header-actions.tsx(+test).
Done test: cd web && npx tsc --noEmit && npx vitest run (all pass, 0 failures).
Write one line at the end: RESULT2: ...
RESULT2: W-30b complete. Compare → Ask about this drawing works through App with the drawing selected; the failing test used a permanently hidden ChatScreen and asserted before jsdom delivered hashchange, so it now renders App and awaits navigation (no production routing change needed). Empty History now offers New chat calling setOpen(false), setToast(''), onNew(), with a click test asserting the callback, closed popover, and cleared toast. Done test passed: cd web && npx tsc --noEmit && npx vitest run (49 files, 285 tests, 0 failures). Changed only data-screen.test.tsx, chat-header-actions.tsx, chat-header-actions.test.tsx and this handoff; no commits.
