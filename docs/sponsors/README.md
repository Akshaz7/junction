# Hologram sponsor evidence

These pages describe integrations supported by the working tree and recorded results at the time of writing. Configuration alone does not establish that a provider ran. Screenshot paths are placeholders for the LEAD; no screenshots are supplied here.

| Tool | What is supported | Evidence page |
|---|---|---|
| Nemotron | Model fallback after question-parsing rules, with recorded NVIDIA calls | [Nemotron](nemotron.md) |
| Runware | Recorded drawing-reading, item-checking and routing calls through its native API | [Runware](runware.md) |
| ElevenLabs | Recorded speech generation behind the web answer playback control | [ElevenLabs](elevenlabs.md) |
| Aiven | Managed PostgreSQL used by the backend; Runtime deployment remains pending in the deployment notes | [Aiven](aiven.md) |
| Codex | Build workflow for the WEB, 3D and IOS workers, documented in their handoffs | [Codex](codex.md) |

**Not integrated yet / not demonstrated:**

- **Cloudinary:** no application upload or delivery call found in `pipeline/`, `engine/`, `server/`, `web/src/` or `ios/`. `scripts/check_keys.py` checks credentials with a ping; that is not an app integration. `TASKS.md` row D-14 remains the planned upload work. No challenge page.
- **Context.dev:** no monitor or webhook integration found in the application code. `TASKS.md` row E-17 describes future work; the credit cap in `COSTS.md` is not evidence of use. No challenge page.
- **Modal:** `train/modal_seg.py::train` and `train/modal_det.py::train` define remote training jobs, but `COSTS.md` records no Modal spend and the inspected `results/` has no completed fine-tuning report (`results/vision/seg_finetuned.json` or `results/vision/det_finetuned.json`). Scripts and login status do not prove a run happened. No challenge page until a completed run is recorded.
- **Gemini direct API:** `engine/models/providers.py::gemini` and `engine/models/models.yaml` provide an adapter and task configuration, but the inspected `results/costs.jsonl` contains no record with `provider: gemini`. Recorded `google:gemini` models have `provider: runware` and count as Runware usage. No separate Gemini challenge page.

Recheck the evidence before submission, especially the append-only cost log and deployment status. [Submission draft](../SUBMISSION.md) deliberately leaves final numbers to the LEAD.
