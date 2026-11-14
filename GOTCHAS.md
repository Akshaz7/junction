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
- No `python3.12` on PATH by default: use `uv run --python 3.12` (uv-managed 3.12.14 installed).
- Simulator: no devices existed; LEAD created "Hologram iPhone" (iPhone 16 Pro, iOS 26.1). Codex's sandbox cannot reach CoreSimulator, so IOS runs build-for-testing and the LEAD runs `xcodebuild test`.
- Playwright/Chrome cannot launch inside the Codex sandbox (SIGABRT/EPERM). Codex workers write e2e tests; the LEAD runs them outside the sandbox.
- Runware is NOT OpenAI-compatible: it uses its own task API (`textInference`, `audioInference`) at https://api.runware.ai/v1. Dedicated adapter in engine/models/providers.py.
- `.env` has empty values like `DATABASE_URL=`: `os.environ.get(k, default)` returns "" — use `os.environ.get(k) or default`.
- While `uv sync` (torch) runs, every `uv run` blocks on the venv lock. Test small things with `uv run --no-project --with <pkgs>`.
- Production API image installs only API deps (no torch/ifcopenshell): keep heavy imports out of the engine's API path or update deploy/Dockerfile.
- ENGINE's costs.jsonl records must keep fields `provider`, `task`, `cost_usd` — /api/costs aggregates on them.
