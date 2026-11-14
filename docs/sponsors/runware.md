# Hologram × Runware

**Runware supplies model calls for drawing reading and item checks.** Hologram sends a drawing page or a cropped symbol through the shared model layer and uses the response alongside the plan map. Runware also serves as a fallback for question routing and other configured tasks.

**Where it is set out:**

- `engine/answer.py::answer` sends supported nonnumeric plan questions to `engine/readdraw.py::read_drawing`, which calls `engine.models.call("read_drawing", ...)` and checks returned regions against plan-map items.
- `vision/verify.py::model_check` and `wet_count` call the `verify_item` task on image crops; `vision/verify_run.py` and `vision/verify_wet.py` prefer Runware for their verification runs.
- `engine/models/providers.py::runware` and `_runware_call` implement Runware's native `textInference` and `audioInference` requests, including returned usage and cost.
- `engine/models/models.yaml` declares task fallbacks. `engine/models/core.py::call` selects an available provider, caches responses, enforces budgets and logs results.

**Recorded evidence:** `results/costs.jsonl` contains an uncached `read_drawing` record at `2026-11-14T05:09:10+0200`: `provider: runware`, model `google:gemini@3.5-flash`, `cost_usd: 0.021347`, `latency_ms: 10600`. It also contains an uncached `verify_item` record at `2026-11-14T03:58:12+0200`, request `V-09-pilot`, using `google:gemini@3.1-flash-lite`, with `cost_usd: 0.000314`. These are individual recorded requests, not average costs.

Screenshot placeholder: `docs/sponsors/img/runware.png` — LEAD to capture a drawing answer with its sources and cost.

**Honest limits:** the recorded Google Gemini models ran through Runware; they do not establish direct Gemini API usage. The current default configuration puts other providers before Runware for drawing reading and verification. Numeric solvers use stored drawing data without a model call. Crop checks are optional, model output can be wrong, and `read_drawing` labels answers without backed regions as unchecked. The adapter's audio support alone does not prove Runware speech generation ran.
