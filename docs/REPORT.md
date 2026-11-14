# Hologram — final report draft

Team RS3 · Stoa “Make Blueprints Talk” · Junction 2026

Draft from recorded repository results; final submission measurements remain pending.

## What we built

Hologram answers English questions about construction drawings and BIM models, then carries their evidence from **2D → 3D → AR**. Users inspect numbered regions on a drawing, select **Visualise it** to see matching model elements, and use **Show on table** in the native iPhone app for AR placement and highlights.

The web app recreates Stoa-style document browsing, chat, sources, drawing inspection, changes and upload flows under our own Hologram identity. Uploads feed ingestion before questions can use their extracted data. PDF, image, DXF and IFC routes have different capabilities; accepting an extension does not establish complete processing or AR availability.

Shared chat and scene events connect laptop and phone through PostgreSQL and the backend WebSocket service. Voice in AR can continue the conversation and select elements. Physical-device rehearsal, current live delivery timing and the plan build-up/highlight animations remain submission gates in [DEMO.md](DEMO.md), rather than measured claims here.

## How it works

We read a drawing into a reusable **plan map**: walls, openings, rooms, fixtures, text, positions, scale and provenance. IFC supplies element properties and geometry; raster reading combines vision and OCR. Plain code then counts, filters and measures this structured data. Numeric code answers use templates. Repeated questions reuse extraction instead of requiring a complete model reading each time.

The model ladder starts with code, then local vision or targeted checks, then a document reader and larger reasoning/writing models where needed. Gemini, Nemotron, Claude and Runware-backed alternatives have task-specific roles and fallbacks. All calls pass through `engine/models.call()` for caching, budget enforcement and cost logging; [MODELS.md](MODELS.md) records the configuration.

The newer **zero-abstention ladder** adds image recounting, reader recovery and a final best-effort response when ordinary routes cannot answer. It labels estimates with low confidence and their basis. If no readable numeric evidence survives, the final rung can emit a labelled default; that is not a measured quantity. Answer coverage must therefore be reported separately from correctness and evidence coverage.

## Accuracy

These are recorded snapshots, not the final build's guaranteed performance. Benchmarks below use real-provider mode (`fake: false`). Numeric accuracy includes abstentions as unsuccessful and excludes text.

| Tag and result file | Scope | Numeric result | Numeric abstentions |
| --- | --- | --- | --- |
| [sample200-r10](../results/bench/sample200-r10.json) | Earlier sample; basis of [ACCURACY.md](ACCURACY.md) | 124/187 correct, 66.31% | 16 |
| [e-s200-z1](../results/bench/e-s200-z1.json) | Newer zero-abstention sample | 143/187 correct, 76.47% | 0 |
| [full_1](../results/bench/full_1.json) | Earlier full numeric set; text subsampled every sixth question | 35,900/63,307 correct, 56.71% | 6,071 |
| [e-ifc-full5](../results/bench/e-ifc-full5.json) | IFC numeric subset | 1,612/1,710 correct, 94.27% | 64 |

The newer sample also records zero text abstentions. Its text judge marks **9/13 correct (69.23%)**, one partial and three wrong. This small, model-judged sample is separate from numeric accuracy. The IFC subset and earlier full run do not establish universal zero abstentions.

Vision remains a bottleneck. [v09_final.json](../results/vision/v09_final.json), which has no tag field, reports exact-count evaluation over a held-out CubiCasa5K drawing set: default window accuracy **32.0%**, door **44.3%**, and shower/bathtub **12.3%**. Its optional bathroom crop check reaches **33.0%** for showers/bathtubs. These are reader measurements, not whole-system scores.

`[PENDING: final full benchmark tag/file and accuracy after the latest changes]`

`[PENDING: matched fine-tuning before/after evaluation]` — [seg_finetuned.json](../results/vision/seg_finetuned.json) and [det_finetuned.json](../results/vision/det_finetuned.json) still record blocked snapshots with `after: null`; newer training work does not establish a gain without updated results.

## Visual verifiability

Stable item IDs connect page boxes, GLB nodes and USDZ prims. Answer numbers persist across views; scene commands use separate tags such as W3. Citations open the source, while **Sources** and **Show thought process** expose evidence and execution trace. Cutaway/storey controls make internal elements visible. An incorrect reading can still produce consistent highlights, so visual consistency supports inspection without proving accuracy. Best-effort answers may lack item-level evidence.

## Creativity

The same evidence becomes a spatial interface: inspect a counted window, locate it in the building, then place the model on a table. Natural-language hide, restore and isolate commands modify a persistent per-chat layer. Source data stays intact. Advisor cards link observations to quoted sources. The demo combines shared chat, voice and spatial selection; its recordings must identify any fallback or separate prepared scene.

## Inference cost

The [e-s200-z1 result](../results/bench/e-s200-z1.json) records **$0.00010339 per answer**, **$0.020677** for answers and **$0.000248** for text judging: **$0.020925 total**. The [sample200-r10 result](../results/bench/sample200-r10.json) records **$0 per answer**. These are recorded incremental model charges; they exclude earlier extraction, training, hosting and separately billed services. Cache hits can cost zero.

The answer card displays model cost, and its trace identifies code/model work. That figure is not the total cost of operating the system. `[PENDING: fresh-upload extraction plus answer cost]`

## Honesty

Our fine-tuning policy excludes drawings referenced by any evaluation question set, with ID/hash overlap checks. Pretrained models may already have seen evaluation drawings; we disclose that limitation. English-only evaluation uses exact counts and a **2% relative or 0.05 absolute** tolerance for area, length and volume. Text uses a separate cached model judge comparing facts against human gold answers, which may themselves contain errors.

Low-confidence estimates retain their qualifications. Missing data is disclosed. Generated samples carry **“generated for demo”**; prepared examples must never be presented as answers to a judge's unseen upload.

## Licences

Repository code is MIT. Dataset, model and library terms remain separate: CubiCasa5K carries noncommercial/share-alike restrictions; FloorPlanCAD declarations conflict. We conservatively treat derived fine-tunes as noncommercial research/demo assets, as documented in [MODELS.md](MODELS.md). IfcOpenShell is LGPL, with separate distribution obligations; OpenUSD has its own licence. Restricted ND/GPL drawings are excluded from publishing. Stoa reference code, logos and drawings are not redistributed.

## Limits and next steps

Raster omissions, uncertain scale, unsupported conversions and incomplete IFC properties limit answers. Prioritize unseen judge uploads, complex questions spanning documents, evidence completeness and reliable cross-device continuation. Complete physical-iPhone rehearsal and final benchmarks, publish matched training results, and resolve commercial dataset rights before a commercial model release. An extruded plan is an inferred scene, not surveyed BIM geometry or verified compliance advice.
