# DOCS (Codex): row X-13. Judge's guide (one page)
Scope: docs/JUDGES.md (new) and web/public/judges.md (copy of the same text, so the app can link it).
Stoa's judges will test our interface with their OWN drawings and harder questions. Write a one-page guide, under 500 words:
- the link
- no login needed
- how to upload (pdf, png, jpg, dxf, ifc; the size cap from server/files_routes.py; typical ready time 17–30 s, and IFC in seconds)
- what to ask, with 8 example questions across counts, areas, multi-kind, take-offs, "where is", spec text, rule checks and edits ("remove the front door")
- how to verify an answer: numbered boxes ↔ citations, Visualise it in 3D, the cost on each answer, "best estimate" labels
- cross-device (open the same site on a phone)
- known limits, stated honestly: scans without a scale, very large IFCs, non-English text
Plain, friendly English, no marketing fluff. Check the facts against the code and docs (API.md, DEMO.md, REPORT.md).
Do not commit. Append a RESULT: line.

RESULT: X-13 passed local content check: 422 words, eight examples, required topics, byte-identical docs/JUDGES.md and web/public/judges.md, server-verified upload formats/100 MiB cap; git diff --check passed. No done-test command supplied, so used these checks.
