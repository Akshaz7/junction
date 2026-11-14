# Judge Q&A — X-16

Short answers for Ash. Measurements belong to named snapshots; current deployment behavior and final benchmark still need verification. Use [DEMO.md](DEMO.md) for the live sequence.

### Q01 · How accurate is it?

Recorded `e-s200-z1` has [76.47% numeric accuracy](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/accuracy), with [143 correct numeric answers](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/correct). Its [200 questions](../results/bench/e-s200-z1.json#/totals/questions) include separately graded text. This sample predates later changes; it is not a final system-wide score. The earlier full numeric run scored [56.71%](../results/bench/full_1.json#/cells/ALL%20x%20ALL/accuracy). See [scoring and scope](REPORT.md).

### Q02 · Is text accuracy included in that score?

No. The sample's text judge records [9 correct](../results/bench/e-s200-z1.json#/text/ALL/correct) among [13 text answers](../results/bench/e-s200-z1.json#/text/ALL/n), with stored accuracy [69.23%](../results/bench/e-s200-z1.json#/text/ALL/accuracy). This small model-judged result is separate from numeric scoring and can itself contain judge errors.

### Q03 · What does an answer cost?

The sample reports [$0.00010339 incremental model cost per answer](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/cost_usd_per_answer), [$0.020677 answer spend](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/cost_usd_total) and [$0.000248 text-judging spend](../results/bench/e-s200-z1.json#/text/ALL/judge_usd). Cache effects are included; extraction, training, hosting and separate services are excluded. This does not price the latest chain or a fresh upload. Check actual answer cards/traces.

### Q04 · Why is inference cheap?

We extract reusable structured evidence, then code counts, filters and measures it. Later questions reuse the plan map or IFC index. The earlier sample records [$0 model cost per answer](../results/bench/sample200-r10.json#/cells/ALL%20x%20ALL/cost_usd_per_answer); that excludes prior extraction and does not mean uploads, voice or operation are free. Model calls share a cached, budgeted [entry point](../engine/models/__init__.py).

### Q05 · How can I verify an answer?

Open its citation, inspect numbered drawing regions and sources, then use **Visualise it** and **Show on table** when scenes exist. Stable item IDs connect evidence across views ([contract](../CONTRACT.md)). Boxed object counts keep headline and boxes consistent; detection can still be wrong. IFC element answers, text totals and forced estimates can lack boxes. Scene tags are separate from citation numbers.

### Q06 · How do you handle hallucinations and missing data?

Normal numeric routes calculate from structured evidence; advisor cards require a source. Recovery can return an explicitly uncertain best-effort estimate. If readable evidence is absent, say so; a labelled default is not a measurement. The sample records [0 numeric abstentions](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/abstained), but answering every question does not make every answer correct. See [limitations](REPORT.md).

### Q07 · What did you build versus use off the shelf?

We built ingestion adapters, plan-map/evidence contract, solvers, routing/recovery, linked web/model/AR views, shared chat, scene edits and sourced advisor integration. Foundation models, OCR, geometry libraries, rendering frameworks and pretrained vision backbones are external. We also created fine-tuning pipelines/checkpoints; a matched accuracy gain remains unestablished ([model provenance](MODELS.md)).

### Q08 · Which models do you use, and why?

Code handles applicable structured questions first. Current [configuration](../engine/models/models.yaml) assigns Claude writing/chat and box recounts, Gemini via Runware cheap recount/recovery, and Nemotron routing/advisor/scene intent. Voice input can use device recognition; ElevenLabs supplies speech output. Exact IDs and fallbacks are in [MODELS.md](MODELS.md). Choices separate task needs and budget; they do not establish universal model superiority.

### Q09 · Did fine-tuning improve results?

We cannot claim a matched improvement yet. Recorded [segmenter](../results/vision/seg_finetuned.json) and [detector](../results/vision/det_finetuned.json) snapshots have `after: null`. Our fine-tunes use a ResNet-UNet segmenter and RT-DETR detector; [MODELS.md](MODELS.md) records training/checkpoint terms. Training completion alone is not an accuracy gain.

### Q10 · Did you train on test drawings?

Our fine-tuning builder excludes question-referenced and calibration drawings and checks identities/hashes ([builder](../train/build_v05.py), [overlap checker](../train/check_overlap.py), [provenance](MODELS.md)). Evaluation examples are not training examples. We cannot establish all pretrained checkpoints' original membership, so disclose possible upstream overlap. Sample-driven solver changes also mean recorded runs should not be called untouched blind tests.

### Q11 · Can this be used commercially? What are the licences?

Our code is MIT; assets, libraries and weights keep separate terms. CubiCasa-derived data/checkpoints receive noncommercial treatment; FloorPlanCAD declarations still need resolution. Restricted drawings and Stoa reference code, logos and drawings are excluded from publishing. [MODELS.md](MODELS.md) records provenance/release restrictions; MIT code does not commercially clear every model or dataset.

### Q12 · What fails most often?

Raster reading, small fixtures, missing scale, incomplete IFC properties and unsupported conversions. The held-out reader snapshot records [44.3% door exact-count accuracy](../results/vision/v09_final.json#/default_free_pass/door) and [12.3% for showers/bathtubs](../results/vision/v09_final.json#/default_free_pass/shower_bathtub). These reader scores are not whole-system scores. Code can be exact over an incorrectly read map; inspect evidence and confidence.

### Q13 · Is the compliance result authoritative?

It is a limited check of available model properties against sourced rules. The demo's [recorded front-door response](../results/qa/judge_run-r4.json#/13/got) flags the exit check under `848/2017 §33`; the [rule entry](../engine/rules/fire_escape.yaml) records applicability exceptions. Missing properties/untested rules prevent complete determination. Show source, severity and “not checkable” notes; no findings does not establish compliance.

### Q14 · Is the AR geometry real, and does the phone stay in sync?

IFC scenes use source geometry; raster scenes are inferred extrusions with scale uncertainty. Item IDs link evidence to elements. Chat/scene events use the shared backend; native AR preserves originating chat through **Show on table** ([bridge contract](../CONTRACT.md), [live service](../server/live.py)). Physical-device build-up, voice and delivery rehearsal remain pending in [DEMO.md](DEMO.md); recordings and offline AR_DEMO are identified explicitly.

### Q15 · Can I try my own drawing now?

Yes: **Data → Upload → Choose file**, wait for ready status, then **Ask about it** with uploaded source selected. Start with PDF, image, DXF or IFC; outputs depend on ingestion. Ask in English and inspect actual evidence. We do not promise a prepared example's accuracy, cost or AR availability for your file. If processing fails or remains incomplete, we show that and name any prepared fallback ([upload test record](../results/upload_live.json)).
