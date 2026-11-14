# Hologram — submission report

Team RS3 · Stoa “Make Blueprints Talk” · Junction

Hologram answers English questions about construction drawings and BIM models with inspectable evidence. A drawing becomes a reusable plan map; a question becomes a cited answer; the selected objects carry their identity from drawing to model to the table. The web app provides chat, document browsing, uploads, changes and sourced findings. The native iPhone shell adds AR placement and voice.

The sections below follow the equally weighted judging criteria. Measurements are recorded snapshots; final-build revalidation remains pending.

## Accuracy

**The recorded sample200 run reached [76.47% numeric accuracy](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/accuracy), with [0 numeric abstentions](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/abstained) and [0 text abstentions](../results/bench/e-s200-z1.json#/text/ALL/abstained).** Run `e-s200-z1` contains [200 questions](../results/bench/e-s200-z1.json#/totals/questions): [143 correct](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/correct) and [44 wrong](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/wrong) numeric answers, plus [13 separately judged text answers](../results/bench/e-s200-z1.json#/text/ALL/n). Text accuracy was [69.23%](../results/bench/e-s200-z1.json#/text/ALL/accuracy). Numeric scoring uses exact counts and tolerance-based measurements; text uses a separate model judge. Zero abstentions measures coverage, not correctness: recovery can end in an explicitly qualified best-effort estimate.

Our own [48-question judge set](../results/qa/judge_run-r4.json#/computed/n) scored **[47 correct locally](../results/qa/judge_run-r4.json#/computed/correct)**, with [1 partial answer](../results/qa/judge_run-r4.json#/computed/partial). Its [gold builder](../results/qa/build_judge_set.py) computes values from extracted elements, plan maps and page text, independently of `engine.answer`, alongside authored expected text/rule references. This is an internal regression set whose question shapes informed implementation. Shared extraction can contain shared errors; it is not independent ground truth for drawing recognition or an unseen judge evaluation. A separate [deployed snapshot](../results/qa/judge_run-dep2.json) scored only [11 correct](../results/qa/judge_run-dep2.json#/computed/correct) out of [48](../results/qa/judge_run-dep2.json#/computed/n). Local performance does not establish production performance.

Recount calibration explains why the engine combines structured extraction with selective vision rather than trusting every recount. Exact-count accuracy on the original [156-document calibration](../results/recount_calib.json#/n_docs):

| Object | Plan map | Vision recount |
| --- | --- | --- |
| Windows | [31.4%](../results/recount_calib.json#/window/plan_acc) | [24.4%](../results/recount_calib.json#/window/vision_acc) |
| Doors | [33.3%](../results/recount_calib.json#/door/plan_acc) | [31.4%](../results/recount_calib.json#/door/vision_acc) |
| Toilets | [77.6%](../results/recount_calib.json#/toilet/plan_acc) | [77.6%](../results/recount_calib.json#/toilet/vision_acc) |
| Sinks | [23.1%](../results/recount_calib.json#/sink/plan_acc) | [15.4%](../results/recount_calib.json#/sink/vision_acc) |
| Showers/bathtubs | [11.5%](../results/recount_calib.json#/shower_bathtub/plan_acc) | [65.4%](../results/recount_calib.json#/shower_bathtub/vision_acc) |

The smaller model comparison records these recount accuracies. Values use each file’s successful-response denominator; failed responses are not counted as correct:

| Recorded model | Documents attempted | Windows | Doors | Toilets | Sinks | Showers/bathtubs |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Haiku | [40](../results/rc_claude-haiku-5-5.json#/n_docs) | [30%](../results/rc_claude-haiku-5-5.json#/window/vision_acc) | [35%](../results/rc_claude-haiku-5-5.json#/door/vision_acc) | [77.5%](../results/rc_claude-haiku-5-5.json#/toilet/vision_acc) | [15%](../results/rc_claude-haiku-5-5.json#/sink/vision_acc) | [30%](../results/rc_claude-haiku-5-5.json#/shower_bathtub/vision_acc) |
| Claude Sonnet | [40](../results/rc_claude-sonnet-5-5.json#/n_docs) | [50%](../results/rc_claude-sonnet-5-5.json#/window/vision_acc) | [32.5%](../results/rc_claude-sonnet-5-5.json#/door/vision_acc) | [85%](../results/rc_claude-sonnet-5-5.json#/toilet/vision_acc) | [17.5%](../results/rc_claude-sonnet-5-5.json#/sink/vision_acc) | [60%](../results/rc_claude-sonnet-5-5.json#/shower_bathtub/vision_acc) |
| Claude Opus | [40](../results/rc_claude-opus-5-5.json#/n_docs) | [57.5%](../results/rc_claude-opus-5-5.json#/window/vision_acc) | [41%](../results/rc_claude-opus-5-5.json#/door/vision_acc) | [90%](../results/rc_claude-opus-5-5.json#/toilet/vision_acc) | [25.6%](../results/rc_claude-opus-5-5.json#/sink/vision_acc) | [42.5%](../results/rc_claude-opus-5-5.json#/shower_bathtub/vision_acc) |
| Claude Fable | [40](../results/rc_claude-fable-5-2.json#/n_docs) | [60%](../results/rc_claude-fable-5-2.json#/window/vision_acc) | [45%](../results/rc_claude-fable-5-2.json#/door/vision_acc) | [87.5%](../results/rc_claude-fable-5-2.json#/toilet/vision_acc) | [27.5%](../results/rc_claude-fable-5-2.json#/sink/vision_acc) | [80%](../results/rc_claude-fable-5-2.json#/shower_bathtub/vision_acc) |

Opus has [39 valid door responses](../results/rc_claude-opus-5-5.json#/door/n) and [39 valid sink responses](../results/rc_claude-opus-5-5.json#/sink/n); its other categories are complete. Additional [Carbon](../results/rc_gemini-4-carbon.json), [Hydrogen](../results/rc_gemini-4-hydrogen.json), [Runware Sonnet](../results/rc_runware_anthropic_claude_sonnet_4_6.json) and [Runware Flash](../results/rc_runware_google_gemini_3_5_flash.json) files include incomplete responses and should be read with their per-kind denominators. These calibration results informed tuning; they are not independent whole-system scores or a matched fine-tuning gain.

## Visual verifiability

**For boxed object counts, the headline count equals the numbered boxes** (`E-25`; [implementation](../engine/answer.py), [regressions](../engine/tests/test_answer.py)). A lower recount must reconcile the boxes; an increase requires drawable evidence. This safeguards consistency, while missed or misclassified objects can still make a count wrong. Schedule totals, element-only citations and forced estimates may lack object boxes.

Citations open the drawing; **Sources** exposes provenance and **Show thought process** exposes execution traces. Stable item IDs and answer labels connect the same numbers in **2D → 3D → AR** ([AR highlight implementation](../ios/Hologram/AR/HighlightController.swift)). Scene-command tags serve a separate purpose. The native path is implemented; physical-device continuity remains to be rehearsed.

Selected recorded screenshots:

- [Numbered drawing beside its count](../results/e2e/desktop-03-numbered-drawing.png).
- [Matching numbered highlights in the web model](../results/e2e/desktop-04-raster-3d.png).
- [Source drawing opened from a phone citation](../results/qa/shots/phac20-04-citation-open.png).
- [Phone model highlights and cross-device arrival banner](../results/qa/shots/r2-xdev-phone-3d.png).

These are web captures, including phone emulation; they do not prove physical AR or delivery latency.

## Creativity

Hologram turns evidence into an interface for exploring a building. **Visualise it** reveals a plan as a building; **Show on table** opens native AR placement with a [plan-to-building build-up](../ios/Hologram/AR/BuildAnimator.swift). The [voice controller](../ios/Hologram/AR/ARVoiceController.swift) lets users ask while looking at the model. Shared chat and [live events](../server/live.py) connect laptop questions, phone answers and scene highlights.

Natural-language hide, restore and isolate commands operate on a persistent chat edit layer. After edits, [Finnish rule checks](../engine/advisor.py) can return violation, suggestion or information cards tied to affected items and quoted sources. The [recorded front-door answer](../results/qa/judge_run-r4.json#/13/got) demonstrates the intended exit-check flow. Missing model properties are reported as uncheckable; these checks do not certify compliance. Physical-iPhone build-up, voice, edit delivery and the complete laptop-to-phone-to-laptop sequence remain validation gates in [DEMO.md](DEMO.md).

## Low inference cost

The ladder is **code → small model → large model**. Extraction creates reusable structured evidence; counts, filters and measurements run in code, and numeric code answers use templates. Models handle reading, ambiguity and recovery. Calls pass through `engine.models.call()` for caching, budget enforcement and logging ([configuration](../engine/models/models.yaml)).

Run `e-s200-z1` records **[$0.00010339 per answer](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/cost_usd_per_answer)** and [$0.020677 total answer spend](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/cost_usd_total). Including [$0.000248 for text judging](../results/bench/e-s200-z1.json#/text/ALL/judge_usd), total recorded spend is [$0.020925](../results/bench/e-s200-z1.json#/totals/cost_usd).

**[69%](../results/bench/e-s200-z1.rows.jsonl#/computed/zero_cost_share) of answers had [$0 recorded incremental model cost](../results/bench/e-s200-z1.rows.jsonl#/computed/zero_cost_usd)**: [138](../results/bench/e-s200-z1.rows.jsonl#/computed/zero_cost_answers) of [200](../results/bench/e-s200-z1.rows.jsonl#/computed/n), recomputed from row-level `cost_usd`. This includes cache effects and does not establish that every such answer avoided inference. These figures exclude prior extraction, training, hosting and separately billed services. Fresh-upload total cost and the latest model chain’s cost have not been measured here.

## Limits and provenance

Raster omissions, uncertain scale, conversion failures and incomplete IFC properties constrain answers. Extruded raster geometry is inferred. English-only evaluation does not establish multilingual performance. The [live QA record](../results/qa/live-1439.md) also documents deployment, missing-artifact and live-sync failures; the screenshots and local regression score do not establish that these are resolved.

A final full benchmark, representative unseen-upload evaluation, matched fine-tuning gain, fresh-upload cost and physical-iPhone rehearsal remain unmeasured or pending. Fine-tuning excludes drawings referenced by evaluation questions, but pretrained checkpoint overlap cannot be ruled out. Best-effort estimates retain uncertainty labels; prepared sources must be identified, and synthetic content labelled **“generated for demo”**.

Code is MIT; dataset and model rights are separate. [MODELS.md](MODELS.md) records licences and provenance. Restricted drawings and Stoa reference code, logos and drawings are excluded from publishing.
