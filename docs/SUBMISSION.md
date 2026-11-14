# Hologram — submission draft

**Project name:** Hologram

**Punchline:** We rebuilt blueprint chat, then added the missing dimension.

**Description:** Hologram lets people ask questions about construction drawings and BIM models, then inspect the evidence. It reads drawings into a structured plan map so counts and measurements can come from code. Answers link to numbered regions on the drawing and matching items in a 3D viewer. The iOS shell adds a native AR view for inspecting a model on a table. When the rules cannot understand a question, a model classifies it; drawing-reading models help with questions outside the numeric solvers. Spoken answers make the results easier to follow. Missing data leads to an explicit limitation or abstention. The current build combines a working local app with managed PostgreSQL; public API deployment and some browser and device checks remain pending.

**Tech used:** React, TypeScript, Vite, Tailwind CSS and three.js for the web interface; SwiftUI, RealityKit and ARKit for iOS; Python, FastAPI and asyncpg for the API; PostgreSQL on Aiven; IFC/DXF processing and local vision models for drawing data; Nemotron through NVIDIA, Runware model calls and ElevenLabs speech through `engine.models.call()`. Codex workers build the user interfaces alongside Claude workers. Implementation paths and limits are recorded in [the sponsor evidence index](sponsors/README.md), `AGENTS.md`, `CONTRACT.md`, `server/`, `pipeline/`, `vision/`, `web/` and `ios/`.

**Challenge list — evidenced integrations only:**

- [Nemotron](sponsors/nemotron.md): question-routing fallback after rules.
- [Runware](sponsors/runware.md): recorded drawing-reading, item-verification and routing calls. Google Gemini models accessed through Runware are attributed here.
- [ElevenLabs](sponsors/elevenlabs.md): answer speech generation behind the playback control.
- [Aiven](sponsors/aiven.md): managed PostgreSQL; Runtime deployment is pending.
- [Codex](sponsors/codex.md): scoped WEB, 3D, IOS and documentation worker workflow.

Modal, Cloudinary, Context.dev and direct Gemini API use are excluded from this draft's challenge list for the evidence reasons in [the sponsor index](sponsors/README.md). Recheck before final submission.

**Numbers — source pointers only; LEAD fills final values:**

```text
Question routing, rules-first: results/router_cost.json
Forced-model routing, with provider mix: results/router_model_only.json
Provider/task/model cost records, including cache flags: results/costs.jsonl
Answer benchmark summary and per-question evidence: results/bench/sample200-r2.json; results/bench/sample200-r2.rows.jsonl
Vision baseline: results/vision/baseline.json
Vision verification outcomes and scope: results/vision/v09_final.json
Vision generalisation: results/vision/generalisation.json
Web visual comparison status: results/fidelity/report.json
```

The LEAD should confirm the final run and its scoring scope before filling values. Router accuracy is not answer accuracy; cached calls are not new paid calls; unjudged text answers are not scored successes. Screenshot placeholders are listed in the sponsor pages for the LEAD to capture.
