# Hologram × Nemotron

**Nemotron classifies questions when Hologram's parsing rules are unsure.** Its structured answer selects the question type, object kind and scope used by the drawing solvers. The normal path uses rules first, then NVIDIA's Nemotron model, with Runware available if the model call fails.

**Where it is set out:**

- `engine/answer.py::answer` uses the rules parser before invoking the model router.
- `engine/router/route.py::route` and `_from_model` call `engine.models.call("route", ...)` and validate the classification against a schema.
- `engine/models/models.yaml`, task `route`, selects `nvidia/nemotron-3.5-lightning-30b-a3b` with thinking disabled, followed by Runware.
- `engine/models/providers.py::openai_compat` sends NVIDIA requests; `engine/models/core.py::call` handles caching, budgets, logging and fallbacks.

**Recorded evidence:** `results/router_cost.json` records `unique_questions: 420`, `accuracy_type_and_kind: 0.9786` and `model_calls: 0`: this is a rules result, not a Nemotron score. `results/router_model_only.json` records `unique_questions: 120`, `accuracy_type_and_kind: 0.95`, provider counts `nvidia: 118` and `runware: 2`, and `total_cost_usd: 0.000295`. The latter score belongs to that mixed-provider forced-model run. `results/costs.jsonl` also records `provider: nvidia`, task `route`, model `nvidia/nemotron-3.5-lightning-30b-a3b`.

Screenshot placeholder: `docs/sponsors/img/nemotron.png` — LEAD to capture the question trace and route in Hologram.

**Honest limits:** routing accuracy does not measure drawing recognition or final answer accuracy. Most questions in the recorded normal router run needed no model. If providers fail, `route` returns the rules' best guess with source `rules-guess`; configured advisor models are not evidence of advisor calls.
