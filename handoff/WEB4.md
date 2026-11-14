# WEB4: row W-27 (Codex). Mount the finished components (minimal edits)
Scope: tiny, additive edits ONLY in web/src/components/answer-card.tsx, overview-screen.tsx (or the History screen; grep for "History") and wherever the "Upload" button lives (grep "Upload" in data-screen.tsx / workspace-navigation.tsx). Other workers are editing nearby code: change only the lines needed, never reformat, never revert.
1. Mount <ExportAnswerButton/> (web/src/components/answer-export.tsx) in the answer card's action row.
2. Mount <FollowToggle/> (web/src/components/follow-banner.tsx) in the History list header, or in the overview chat list if there is no History screen.
3. Make the existing Upload button open <UploadDialog/> (web/src/components/upload-dialog.tsx). If an older upload flow exists, replace its trigger so there is ONE upload path; keep that flow's code only if something else still uses it.
Done test: tsc + vitest pass. The LEAD runs Playwright.
Do not commit. Append a RESULT: line.
RESULT: W-27 mounted ExportAnswerButton in answer-card.tsx, FollowToggle in chat-header-actions.tsx History header, and UploadDialog in data-screen.tsx, replacing its unused legacy upload flow; npx tsc --noEmit and npm test pass (45 files, 268 tests). No commit; LEAD runs Playwright.
