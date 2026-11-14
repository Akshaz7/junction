# WEB4: row W-25 (Codex). Upload UX for judges' own files
Scope: web/src/components/upload*.tsx/.css (create them if the upload UI lives elsewhere; find it with grep "Upload"), and web/src/lib/upload*.ts. Do NOT edit data-screen.tsx, document-viewer.*, chat-screen.tsx or viewer3d/; other workers own them. Expose a component they can mount.
Build a Stoa-style upload dialog:
- drag and drop plus a file picker; accepts pdf, png, jpg, dxf, ifc
- client-side checks for size and type, with clear messages
- a progress bar for the upload, then the ingest progress from GET /api/docs/{id}/ingest ({status, step, progress, reason?}, being added by the server worker; handle the endpoint missing with a graceful fallback to polling /api/docs/{id})
- on success: "Ready — Ask about it" (opens chat with the doc selected) and "Open" (opens the viewer)
- on failure: a readable reason and "Try again"
Use the app tokens (tokens.css), and make it work on a phone.
Done test: `cd web && npx tsc --noEmit && npx vitest run` with unit tests for the state machine (idle → uploading → processing → ready/failed). The LEAD runs Playwright.
Do not commit. Append a RESULT: line.
NEEDS: WEB owner mount UploadDialog from web/src/components/upload-dialog.tsx beside the upload trigger with open/onClose, onAsk(Document) to select the doc and open chat, onOpen(Document) to open the viewer, and optional onReady(Document) to refresh Data; data-screen.tsx is outside WEB4 scope. LEAD runs Playwright after mounting.
RESULT: W-25 passed `cd web && npx tsc --noEmit && npx vitest run` (42 files, 251 tests). Added upload-dialog.tsx/.css and lib/upload-state.ts, upload-client.ts plus their .test.ts files: mobile dialog, drag/drop and picker, 100 MiB/type/empty checks, measured upload progress, ingestion polling with legacy document/artifact fallback, readable failures, retry/cancellation, and ready navigation callbacks. No commit.
