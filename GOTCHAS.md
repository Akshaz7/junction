# GOTCHAS

- 24 GB memory: heavy jobs go through `scripts/heavy.sh` (max 2 at once). No training on the Mac; fine-tune on Modal.
- IfcConvert drops IfcSpace and IfcOpeningElement unless explicitly included.
- GLB holds no names, types or storeys; those come from the IFC via `elements.json`.
- IFC GlobalIds are not valid USD prim names: use `usd_name = "i_" + sha1(item_id)[:16]`.
- Index build must reuse the GLB node boxes, not a second geometry pass.
- `ultralytics` and `PyMuPDF` are AGPL: do not use. Use pypdfium2 + pdfminer.six; RT-DETR or YOLOX.
- ND-licensed models/files (duplex_arc, Dental Clinic) must not be published. hitos_arc is GPL data: do not redistribute.
- `questions.jsonl` has Finnish copies of many questions: filter for English.
- Vercel cannot hold WebSockets: live sync lives on the Aiven Runtime backend.
- AR does not run in the iOS simulator: AR tests are unit tests on the scene; real AR needs the iPhone.
- `stoabuild-full-text.md` (scraped site text) is not on the Mac. Until it is, the voice guide (CONTRACT 5.8) uses `refs/stoa-hero/02-phase-map.md` (on-screen text per phase) and `refs/stoa-hero/source/tour-copy-strings.en.js` as a style reference only (read, never copy code).
- No `python3.12` on PATH by default: use `uv run --python 3.12` (uv-managed 3.12.14 installed).
