# Hologram — final report draft

Team RS3 · Stoa “Make Blueprints Talk” · Junction

Draft from recorded repository results. Final submission measurements remain pending.

## What we built

Hologram answers English questions about construction drawings and BIM models, then carries evidence from **2D → 3D → AR**. Users inspect numbered regions on a drawing, select **Visualise it** for matching model elements, and use **Show on table** in the native iPhone app for AR placement and highlights.

The web app provides document browsing, chat, sources, drawing inspection, changes and uploads under our Hologram identity. Uploads must complete ingestion before questions can use their extracted data. PDF, image, DXF and IFC routes have different capabilities; an accepted extension does not establish complete processing or AR availability.

Chat has thread memory: earlier turns and their document selections are passed into question handling, so follow-ups can reuse context ([chat handling](../server/chats_routes.py), [context resolver](../engine/context.py)). PostgreSQL-backed chat and WebSocket scene events support cross-device live sync between laptop and phone ([live service](../server/live.py)). The native AR implementation includes a plan-to-building build-up and voice interaction ([build animator](../ios/Hologram/AR/BuildAnimator.swift), [voice controller](../ios/Hologram/AR/ARVoiceController.swift)). Physical-device rehearsal, observed animation behavior and current live-delivery timing remain gates in [DEMO.md](DEMO.md); these implementation references are not device-performance measurements.

## How it works

A reusable **plan map** records walls, openings, rooms, fixtures, text, positions, scale and provenance. IFC supplies element properties and geometry; raster reading combines vision and OCR. Code counts, filters and measures this structured data, with templates for numeric code answers. Later questions reuse extraction.

All inference passes through `engine.models.call()` for caching, budget enforcement and cost logging. The current [task configuration](../engine/models/models.yaml) uses **Claude Sonnet 5.5** through Runware's Anthropic-compatible `/v1/messages` for written answers and chat; **Opus 5.5** for recount boxes (the current YAML replaces the handoff’s **Fable 5.2**); and **Gemini 3.1 Flash-Lite via Runware** for cheap recounts and forced answers. Nemotron handles model-assisted routing, advisor writing and scene intent; ElevenLabs handles TTS. Verda Nemotron VL is a slow last resort wherever included. Haiku resolves context-dependent follow-ups; Opus also handles long-form chat and task writing. [MODELS.md](MODELS.md) lists the complete chains.

Production uses **no direct Gemini or Anthropic keys**. Those providers remain configured for other environments and are skipped without credentials. Voice input uses device recognition when direct Gemini audio input is unavailable; this is separate from ElevenLabs speech output.

The zero-abstention ladder adds recounting, reader recovery and a final best-effort answer when ordinary document routes cannot answer. Estimates state their uncertainty and basis. A labelled default without readable evidence is not a measured quantity. The recorded sample has no abstentions; coverage and correctness remain separate.

## Accuracy

These are recorded real-provider snapshots, not guaranteed final-build scores. Numeric accuracy excludes text and counts numeric abstentions as unsuccessful. Later model-chain or evidence changes require a fresh benchmark before claiming the same performance.

| Run | Scope | Numeric accuracy | Correct numeric answers | Numeric abstentions |
|---|---|---|---|---|
| [sample200-r10](../results/bench/sample200-r10.json) | Earlier sample | [66.31%](../results/bench/sample200-r10.json#/cells/ALL%20x%20ALL/accuracy) | [124](../results/bench/sample200-r10.json#/cells/ALL%20x%20ALL/correct) | [16](../results/bench/sample200-r10.json#/cells/ALL%20x%20ALL/abstained) |
| [e-s200-z1](../results/bench/e-s200-z1.json) | Zero-abstention sample | **[76.47%](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/accuracy)** | [143](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/correct) | **[0](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/abstained)** |
| [full_1](../results/bench/full_1.json) | Earlier full numeric set; text subsampled | [56.71%](../results/bench/full_1.json#/cells/ALL%20x%20ALL/accuracy) | [35,900](../results/bench/full_1.json#/cells/ALL%20x%20ALL/correct) | [6,071](../results/bench/full_1.json#/cells/ALL%20x%20ALL/abstained) |
| [e-ifc-full5](../results/bench/e-ifc-full5.json) | IFC numeric subset | [94.27%](../results/bench/e-ifc-full5.json#/cells/ALL%20x%20ALL/accuracy) | [1,612](../results/bench/e-ifc-full5.json#/cells/ALL%20x%20ALL/correct) | [64](../results/bench/e-ifc-full5.json#/cells/ALL%20x%20ALL/abstained) |

The zero-abstention sample contains [200 questions](../results/bench/e-s200-z1.json#/totals/questions). Its separate text judge records [9 correct](../results/bench/e-s200-z1.json#/text/ALL/correct) among [13 text answers](../results/bench/e-s200-z1.json#/text/ALL/n), or [69.23%](../results/bench/e-s200-z1.json#/text/ALL/accuracy), and [0 text abstentions](../results/bench/e-s200-z1.json#/text/ALL/abstained). This small model-judged text sample is separate from numeric accuracy. Earlier full and IFC runs do not establish universal zero abstentions.

Vision remains a bottleneck. The [held-out reader evaluation](../results/vision/v09_final.json) records default exact-count accuracy of [32.0% for windows](../results/vision/v09_final.json#/default_free_pass/window), [44.3% for doors](../results/vision/v09_final.json#/default_free_pass/door), and [12.3% for showers/bathtubs](../results/vision/v09_final.json#/default_free_pass/shower_bathtub). Its optional bathroom crop check records [33.0% for showers/bathtubs](../results/vision/v09_final.json#/free_pass_plus_bathroom_crop_check/shower_bathtub). These are reader scores, not whole-system accuracy.

Final full benchmark after the latest changes: **pending**. Matched fine-tuning gain: **not established**; the [segmenter](../results/vision/seg_finetuned.json) and [detector](../results/vision/det_finetuned.json) result snapshots still have `after: null`.

## Visual verifiability

For boxed object counts, **the headline count always equals the numbered boxes**: the recount path drops low-confidence detections when lowering a count and requires drawable boxes before increasing it (row `E-25`; [implementation](../engine/answer.py), [regressions](../engine/tests/test_answer.py)). Stable item IDs connect boxes, citations and scene highlights. This is a consistency safeguard, not proof that the underlying detections are correct. Text-schedule totals, scene commands and forced best-effort estimates can lack object-level boxes; do not extend the boxed-count claim to them.

Citations open the source; **Sources** and **Show thought process** expose evidence and execution traces. Cutaway/storey controls expose internal elements. Scene commands use stable item tags independently of answer numbers.

## Creativity

The same evidence becomes a spatial interface: inspect a counted object, locate it in a building, then place the model on a table. Natural-language hide, restore and isolate commands modify a persistent chat edit layer while preserving source data. Advisor cards cite quoted sources. Shared chat, thread memory, AR build-up and voice connect this flow across devices. Recordings must identify any fallback or separate prepared scene.

## Inference cost

The [zero-abstention sample](../results/bench/e-s200-z1.json) records [$0.00010339 per answer](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/cost_usd_per_answer), [$0.020677 for answers](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/cost_usd_total), and [$0.000248 for text judging](../results/bench/e-s200-z1.json#/text/ALL/judge_usd): [$0.020925 total](../results/bench/e-s200-z1.json#/totals/cost_usd). The [earlier sample](../results/bench/sample200-r10.json) records [$0 per answer](../results/bench/sample200-r10.json#/cells/ALL%20x%20ALL/cost_usd_per_answer).

These are incremental model charges, including cache effects. They exclude earlier extraction, training, hosting and separately billed services, and do not price the latest model chain. The answer-card cost is not the total operating cost. Fresh-upload extraction plus answer spend remains pending.

## Honesty, provenance and limits

Our fine-tuning policy excludes drawings referenced by evaluation questions and checks overlap. Pretrained checkpoints may already have seen evaluation drawings; our split checks cannot establish their full training provenance. English evaluation uses exact counts, tolerance-based measurement scoring and a separate cached text judge; gold answers can also contain errors.

Low-confidence estimates retain their qualifications. Missing data is disclosed. Synthetic documents carry **“generated for demo”**; prepared examples must never be presented as answers to a judge's unseen upload.

Repository code is MIT; dataset, model and library terms remain separate. [MODELS.md](MODELS.md) records the noncommercial treatment of derived fine-tunes, unresolved FloorPlanCAD declarations and geometry-library notices. Restricted drawings and Stoa reference code, logos and drawings are excluded from publishing.

Raster omissions, uncertain scale, unsupported conversions and incomplete IFC properties limit answers. An extruded plan is inferred geometry. Rule checks cover available properties and sources, and do not establish building compliance. Remaining work is physical-iPhone rehearsal, a final benchmark, matched training evaluation and measured fresh-upload cost.
