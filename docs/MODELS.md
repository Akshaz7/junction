# Models, providers and datasets

The task chains below follow the current [engine/models/models.yaml](../engine/models/models.yaml), including working-tree changes. They describe configuration, not a claim that every candidate has been called successfully. Hosted API access does not grant redistribution rights to model weights.

## Production roles

- **Claude Sonnet 5.5** (`claude-sonnet-5-5`) is first for written answers and general chat through Runware's Anthropic-compatible `/v1/messages` endpoint (`runware_claude`).
- **Opus 5.5** (`claude-opus-5-5`) is now first for `recount_boxes`, with Sonnet then Runware Gemini Flash as fallbacks. The handoff named **Fable 5.2** (`claude-fable-5-2`); the shared YAML changed during this refresh. Fable remains a recorded candidate, not the current primary. This task returns object boxes when a raster recount needs additional drawable evidence.
- **Gemini 3.1 Flash-Lite via Runware** (`google:gemini@3.1-flash-lite`) is first for cheap raster recounts and forced best-effort answers, and supplies several task fallbacks.
- **Nemotron via NVIDIA** handles model-assisted routing, advisor writing and scene intent after applicable code/rule paths. These tasks select different Nemotron models; exact IDs are below.
- **ElevenLabs** is first for TTS, with Runware Fish Audio then device speech as recovery paths.
- **Verda Nemotron VL** remains last in every chain that includes it. It is a slow recovery service, not the normal answer path. Do not quote a latency without a recorded result.

Production uses **no direct Gemini or Anthropic keys**. Runware serves their production routes through `RUNWARE_API_KEY`. The YAML retains direct-provider entries for other environments: missing credentials skip those entries. In particular, `read_drawing` and `verify_item` still list direct Gemini first in configuration; in production their next credentialed candidates are tried. This is different from changing the YAML order.

Haiku handles `context_rewrite`; Opus handles `task_write` and `chat_long`, with the ordered fallbacks listed below. These additions do not have a new system benchmark here.

Thread history is passed into chat and document-question handling by [server/chats_routes.py](../server/chats_routes.py), [engine/assistant.py](../engine/assistant.py) and [engine/context.py](../engine/context.py). Follow-up resolution can reuse the earlier document; a failed rewrite has a limited rule fallback. This does not establish that every ambiguous follow-up is resolved correctly.

## Providers and adapters

All inference goes through `engine.models.call()` for caching, budget caps, provider fallback and cost logging; see [core.py](../engine/models/core.py) and [providers.py](../engine/models/providers.py). Keys are read fresh; values are never copied into documentation or logs.

| Provider key | Credential variable | Adapter / role |
|---|---|---|
| `fake` | None | Deterministic local tests; no hosted inference |
| `runware_claude` | `RUNWARE_API_KEY` | Anthropic-compatible Messages through Runware; shares the Runware credential |
| `runware` | `RUNWARE_API_KEY` | Dedicated `textInference` / `audioInference` task API; separate from the Messages adapter |
| `nvidia` | `NVIDIA_API_KEY` | OpenAI-compatible Nemotron service |
| `elevenlabs` | `ELEVENLABS_API_KEY` | Speech synthesis |
| `verda` | `VERDA_INFERENCE_KEY` | OpenAI-compatible dedicated Nemotron VL container |
| `featherless` | `FEATHERLESS_API_KEY` | OpenAI-compatible vision fallback |
| `gemini` | `GEMINI_API_KEY` | Direct Gemini REST; credential absent in production |
| `anthropic` | `ANTHROPIC_API_KEY` | Direct Anthropic Messages; credential absent in production |

## Task chains

Arrows show configured fallback order. Candidates without credentials are skipped. Exact model IDs below are identifiers, not measured performance or published prices. Task parameters and accounting rates remain in the linked YAML rather than being quoted as measured results.

| Task | Ordered provider/model chain |
|---|---|
| `route` | `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `runware:google:gemini@3.1-flash-lite` |
| `reader_plan` | `runware:anthropic:claude@sonnet-4.6` → `runware:google:gemini@3.5-flash` → `gemini:gemini-3.5-flash-lite` → `verda:nemotron-3.5-super-vl` |
| `read_drawing` | `gemini:gemini-3.8-flash` → `featherless:Qwen/Qwen3-VL-30B-A3B-Instruct` → `runware:google:gemini@3.5-flash` → `verda:nemotron-3.5-super-vl` |
| `recount` | `runware:google:gemini@3.1-flash-lite` → `gemini:gemini-3.5-flash-lite` → `runware:google:gemini@3.5-flash` |
| `recount_boxes` | `runware_claude:claude-opus-5-5` → `runware_claude:claude-sonnet-5-5` → `runware:google:gemini@3.5-flash` |
| `forced_answer` | `runware:google:gemini@3.1-flash-lite` → `gemini:gemini-3.5-flash-lite` → `verda:nemotron-3.5-super-vl` |
| `verify_item` | `gemini:gemini-3.5-flash-lite` → `nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b` → `runware:google:gemini@3.1-flash-lite` → `verda:nemotron-3.5-super-vl` |
| `write_answer` | `runware_claude:claude-sonnet-5-5` → `anthropic:claude-sonnet-5-5` → `gemini:gemini-3.8-flash` → `runware:anthropic:claude@sonnet-4.6` → `verda:nemotron-3.5-super-vl` |
| `chat` | `runware_claude:claude-sonnet-5-5` → `anthropic:claude-sonnet-5-5` → `runware:anthropic:claude@sonnet-4.6` → `runware:google:gemini@3.1-flash-lite` → `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `verda:nemotron-3.5-super-vl` |
| `scene_intent` | `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `runware:google:gemini@3.1-flash-lite` |
| `judge_text` | `gemini:gemini-3.5-flash-lite` → `runware:google:gemini@3.1-flash-lite` → `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` |
| `advise` | `nvidia:nvidia/nemotron-3-super-120b-a12b` → `anthropic:claude-sonnet-5-5` → `runware:anthropic:claude@sonnet-4.6` |
| `speech_intent` | `gemini:gemini-3.5-flash-lite` → `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `runware:google:gemini@3.1-flash-lite` |
| `tts` | `elevenlabs:eleven_flash_v2_5` → `runware:fishaudio:s2.1@pro` |
| `context_rewrite` | `runware_claude:claude-haiku-5-5` → `runware_claude:claude-sonnet-5-5` → `anthropic:claude-haiku-5-5` → `runware:google:gemini@3.1-flash-lite` |
| `task_write` | `runware_claude:claude-opus-5-5` → `runware_claude:claude-sonnet-5-5` → `anthropic:claude-sonnet-5-5` → `runware:anthropic:claude@sonnet-4.6` |
| `chat_long` | `runware_claude:claude-opus-5-5` → `runware_claude:claude-sonnet-5-5` → `anthropic:claude-sonnet-5-5` → `runware:anthropic:claude@sonnet-4.6` |

`route` and `scene_intent` disable model thinking in their request parameters. `reader_plan` is the tool-using drawing reader planner. `judge_text` grades benchmark text; it does not write user answers. Numeric/code routes can answer without hosted inference. `recount_boxes` reconciles drawable objects with a recount; the headline count follows the numbered evidence boxes in that path ([implementation](../engine/answer.py), [regressions](../engine/tests/test_answer.py), row `E-25`). Consistency does not prove detections are correct; text-schedule totals and forced estimates can lack object-level boxes.

`forced_answer` is the final best-effort rung when normal document routes cannot answer. It labels uncertainty and basis; a default without readable evidence is not a measured quantity. The [sample benchmark](../results/bench/e-s200-z1.json) records [76.47% numeric accuracy](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/accuracy) with [0 numeric abstentions](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/abstained) and [0 text abstentions](../results/bench/e-s200-z1.json#/text/ALL/abstained). This predates later configuration changes and does not certify every fallback or the final build.

Fake mode can be forced by `MODELS_FAKE`; it also applies when all non-fake credentials are absent. Per-provider caps come from [COSTS.md](../COSTS.md). Provider-reported costs override estimates, and cache hits record no incremental model charge. Verda token accounting excludes container charges; ElevenLabs uses character accounting. YAML price comments include provisional assumptions, so no unverified price table is reproduced here. Measured benchmark cost is in [REPORT.md](REPORT.md).

Speech recognition and TTS are separate. [speech_routes.py](../server/speech_routes.py) accepts hosted audio input only through direct Gemini. With that key absent in production, input falls back to device recognition; the resulting text can use normal chat/scene routes. ElevenLabs can still synthesize output. [ARVoiceController.swift](../ios/Hologram/AR/ARVoiceController.swift) implements native voice interaction. AR build-up, shared chat and scene synchronization are described in [REPORT.md](REPORT.md); physical-device rehearsal remains a separate gate in [DEMO.md](DEMO.md).

## Datasets and training provenance

| Dataset | Source and licence | Use / limits |
|---|---|---|
| CubiCasa5K dataset | [Official data deposit](https://zenodo.org/records/2613548), [project](https://github.com/CubiCasa/CubiCasa5k); `CC BY-NC-SA 4.0` for the dataset used here | Raster/SVG training annotations. `train/build_v05.py` uses clean drawings only, excluding question-referenced and calibration IDs. The GitHub implementation/official baseline's separate licence says CC BY-NC 4.0; do not conflate it with the dataset terms. |
| FloorPlanCAD, Voxel51 mirror | [Dataset card](https://huggingface.co/datasets/Voxel51/FloorPlanCAD): narrative says `CC BY-NC 4.0`, while HF metadata says `CC BY-SA 4.0` | Treat as **noncommercial** because the sources conflict; do not infer commercial permission from metadata. Used for detector boxes, not segmentation masks. `train/manifest.json` currently records only the SA metadata and does not resolve this conflict. |
| Synthetic plans — **generated for demo** | [pipeline/synth.py](../pipeline/synth.py), local `data/synth/`; originating IFC/DXF documents and their individual licences remain relevant | Geometric labels for detector/segmenter training. The label is provenance, not a blanket licence or a claim of real surveyed geometry. Preserve upstream document attribution/restrictions. |

Local provenance is in [train/manifest.json](../train/manifest.json), [train/build_v05.py](../train/build_v05.py), [train/check_overlap.py](../train/check_overlap.py), and `results/vision/v05_overlap.json`. The builder re-reads held-out lists from `data/sets/`, excludes calibration drawings, and checks IDs, SHA-256 and perceptual hashes before output. Both Modal training scripts recheck IDs. These checks address our own fine-tuning data; they do not prove the pretrained Yytsi checkpoint never saw an evaluation drawing. Do not train or tune on held-out drawings, or present source-model training overlap as independent held-out accuracy.

## Local vision models and fine-tunes

| Model / status | Source and base licence | Training data / implementation | Resulting checkpoint treatment |
|---|---|---|---|
| ResNet34-UNet, Yytsi base and V-06 fine-tune | [Yytsi/floorplan-to-3d-walls](https://huggingface.co/Yytsi/floorplan-to-3d-walls), [upstream code](https://github.com/Yytsi/floorplan-to-3d): model card labels weights MIT | Base: ImageNet-pretrained ResNet34, then CubiCasa5K high-quality and high-quality-architectural splits; exact train/evaluation drawing membership is unclear. Our [train/modal_seg.py](../train/modal_seg.py) loads `/data/yytsi_best.safetensors` into [vision/unet_resnet34.py](../vision/unet_resnet34.py); trains only mask-capable clean CubiCasa5K and synthetic records. Classes floor/wall/door/window. | `weights/unet_ft/best.safetensors`; upstream MIT declaration does not remove CubiCasa training-data restrictions. Treat fine-tuned weights as noncommercial; retain upstream notices and data attribution. |
| RT-DETR V-07 detector fine-tune | [PekingU/rtdetr_r50vd](https://huggingface.co/PekingU/rtdetr_r50vd), **Apache-2.0**; base card lists COCO training | [train/modal_det.py](../train/modal_det.py) uses Transformers RTDetrForObjectDetection/processor and V-05 clean CubiCasa5K + FloorPlanCAD + synthetic records. Classes door/window/toilet/sink/shower/bathtub. Trains on Modal; no local training. | Script saves `/out/det/best` (model and processor); local inference checkpoints include `weights/rtdetr_ep/`. Preserve Apache licence/NOTICE and mark modifications; combined training data requires conservative noncommercial treatment. |
| CubiCasa5K official `hg_furukawa_original` baseline | [Official repository and licence](https://github.com/CubiCasa/CubiCasa5k); `CC BY-NC 4.0` implementation/checkpoint source | CubiCasa5K train split; segmentation, icons and room baseline in `weights/cubicasa_official/` | Internal baseline; not a permissively licensed final detector. |
| RF-DETR-medium `2dplan2strct` (evaluated, not selected) | [OsamaMo/2dplan2strct](https://huggingface.co/OsamaMo/2dplan2strct); prior project record: rfdetr code Apache-2.0, checkpoint noncommercial research only | Training data undisclosed; wall/room/door/window candidate | No commercial weight permission established by the code licence. |
| SegFormer-B0 floorplan (rejected candidate) | [Patnev71/segformer-b0-finetuned-floorplan](https://huggingface.co/Patnev71/segformer-b0-finetuned-floorplan); card marked `other` in prior project record | Training data unknown; room/background candidate | Not used; no permissive weight licence established. |
| RapidOCR (`rapidocr-onnxruntime`) | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR), Apache-2.0 project | Local OCR; exact bundled OCR checkpoint/training provenance not recorded here | Retain package/model notices; project code licence alone is not evidence for an unidentified checkpoint. |

### Licence consequences for our fine-tuned weights

Repository code is MIT; third-party code, datasets, pretrained weights and our derived checkpoints keep their separate terms. Treat both fine-tunes as **noncommercial research/demo checkpoints**, not MIT-only assets and not commercially cleared models. The project conservatively carries CubiCasa5K's attribution, noncommercial and share-alike obligations into adapted training artifacts/weights where applicable. If distributing such adaptations, retain credits, identify changes and use the same/compatible share-alike terms; do not offer them under MIT alone. This is our conservative release treatment, not a categorical legal determination that every trained weight is automatically a copyright adaptation. See the [licence terms](https://creativecommons.org/licenses/by-nc-sa/4.0/).

FloorPlanCAD's conflicting declarations leave commercial permission unresolved; the detector cannot become commercially cleared merely because its RT-DETR initialization is Apache-2.0. Yytsi's card declares MIT but also identifies CubiCasa5K training, so the original model card is not evidence that the training-data restrictions disappeared. Keep model/dataset provenance with any checkpoint; resolve rights or retrain on commercially cleared data before changing this treatment. Weights/data remain outside git under project rules. Synthetic samples still carry **generated for demo** and originating-document terms.

## Geometry libraries in the deploy image

[deploy/Dockerfile](../deploy/Dockerfile) defines the IFC and USD geometry dependencies. The image uses VLM ingestion without torch or local fine-tuned vision weights. The minimal Vercel API requirements are separate.

IfcOpenShell is LGPL; keep its library notices and applicable source/replacement obligations when distributing it. OpenUSD uses its own licence; preserve the licence and third-party notices for the wheel actually shipped. Check [uv.lock](../uv.lock) and installed distribution metadata for versions; an unpinned Docker dependency does not prove the contents of an earlier deployment. These geometry libraries are not hosted answer models.
