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

## Hosted model licences

Checked against upstream model cards and service terms on 14 November 2026. These rows cover the YAML's configured chains **and catalog/price-only candidates**; a listed candidate is not evidence of successful use. Proprietary models have no open weight licence. Training corpus membership for hosted proprietary models is not disclosed here, and no independent evaluation-overlap claim is made.

| Model family / exact configured or recorded IDs | Licence / service terms | Training provenance / use |
|---|---|---|
| Claude via Runware: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`; catalog candidates `claude-fable-5-2`, `claude-opus-5`; task-API `anthropic:claude@sonnet-4.6`, price entry `anthropic:claude@haiku-4.5` | **Proprietary hosted service**, [Runware terms](https://runware.ai/terms); direct-provider entries use [Anthropic commercial terms](https://www.anthropic.com/legal/commercial-terms). No weights redistributed. | Anthropic pretraining corpus not enumerated in this repo; answer writing, planning, recount evidence, context rewrite and long tasks. |
| Gemini 3.x via Runware: `google:gemini@3.1-flash-lite`, `google:gemini@3.5-flash`; direct fallback entries `gemini-3.5-flash-lite`, `gemini-3.8-flash` | **Proprietary hosted service**, [Runware terms](https://runware.ai/terms); direct Gemini uses [Gemini API terms](https://ai.google.dev/gemini-api/terms). No open weight grant. | Google corpus not enumerated here; raster reading, recount/verification, judging and fallback reasoning. |
| Gemini 4 via Runware (`runware_oai`): `gemini-4-hydrogen`, `gemini-4-carbon` | **Proprietary hosted service**, [Runware terms](https://runware.ai/terms), [Carbon compatible-endpoint documentation](https://runware.ai/docs/models/google-gemini-4-carbon) | Catalog/price entries in current YAML; not selected by the current task chains. Google corpus not enumerated here. |
| NVIDIA `nvidia/nemotron-3.5-lightning-30b-a3b` | **OpenMDW-1.1** per [NVIDIA card](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/modelcard); hosted API trial has separate service terms | NVIDIA curated public/licensed/synthetic text and code; model-assisted routing and scene intent. |
| NVIDIA `nvidia/nemotron-3-super-120b-a12b` | **NVIDIA Nemotron Open Model License**, [official checkpoint card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16); hosted service terms also apply | NVIDIA pre/post-training mixtures described in the card; advisor writing. Preserve exact checkpoint notices if self-hosted/distributed. |
| NVIDIA `nvidia/nemotron-3.5-super-vl-120b-a12b`; Verda alias `nemotron-3.5-super-vl` | **OpenMDW-1.1** for NVIDIA's [3.5 Super VL card](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b/modelcard); NVIDIA API trial / Verda hosting terms are separate | Public/licensed/synthetic multimodal training; verification and last-resort vision. Verda alias alone does not identify an exact quantization/checkpoint digest. |
| Featherless `Qwen/Qwen3-VL-30B-A3B-Instruct`, price candidate `Qwen/Qwen3-Next-80B-A3B-Instruct` | **Apache-2.0** per [Qwen3-VL card](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct), [Qwen3-Next card](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct); hosted-service terms remain separate | Qwen text/multimodal pre/post-training; exact corpus membership not recorded locally. Vision fallback; Next is price-only here. |
| ElevenLabs `eleven_flash_v2_5` | **Proprietary hosted speech service**, [ElevenLabs terms](https://elevenlabs.io/terms-of-use). [Publication terms](https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform): paid non-beta output can have commercial rights; free-plan output is noncommercial and requires attribution. | Training corpus not enumerated here; TTS. Voice-specific permissions still apply; repository MIT does not license voices or weights. |
| Runware `fishaudio:s2.1@pro` | **Hosted API terms**, [Runware](https://runware.ai/terms) / [Fish Audio](https://fish.audio/terms/). No permission to redistribute S2.1 Pro weights is established here. | Training corpus not enumerated here; TTS fallback. Do not infer the hosted API's rights from a separately released Fish Speech checkpoint. |
| `fake` deterministic provider; device speech | Project fake adapter is **MIT**; OS speech is governed by the device platform's terms | Fake produces test responses without model training; device speech downloads no project-owned weights. |

## Datasets and training provenance

The challenge distribution's own README limits its use to the noncommercial Junction challenge. File licences and credits come from `data/<source>/LICENSE.md` in both the preview and full distribution; they remain attached to rendered plans and questions. Those local manifests, rather than a source-wide default, decide the rights for an individual drawing. The dataset itself is excluded from git.

| Drawing / evaluation source | Licence and original source | Required credit / publication treatment |
|---|---|---|
| `cubicasa5k` | **CC BY-NC-SA 4.0**, [CubiCasa5K](https://github.com/CubiCasa/CubiCasa5k) | Credit CubiCasa; noncommercial; retain share-alike on shared adaptations. The official code/checkpoint has separate terms below. |
| `swiss_dwellings` | **CC BY 4.0**, [Swiss Dwellings v3](https://doi.org/10.5281/zenodo.7788422) | Credit Matthias Standfest and collaborators / Archilyse AG; identify the dataset-builder's geometry rendering, labels and numbering changes. |
| `opening_design` (including retained Aalseth samples) | **CC BY-SA 4.0**, or **MIT** for 104_Janesville / Schultz_Residence; [OpeningDesign](https://github.com/OpeningDesign) | Credit the named project team/title block; preserve each file's licence. Aalseth is CC BY-SA 4.0. |
| `ifc_models` | Per file: **KIT unrestricted**, **MIT**, **CC BY 4.0**, **CC BY-ND 3.0**; [KIT examples](https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples), [buildingSMART samples](https://github.com/buildingsmart-community/Community-Sample-Test-Files), [ResBIM](https://github.com/RogerLiang0725/ResBIM) | Credit IAI/KIT, buildingSMART/project author, RWTH E3D or Xing Liang as listed. Do not publish Duplex / Dental Clinic conversions (project applies the stricter ND terms). |
| `ifc_bench` models and questions | [IFC-Bench](https://huggingface.co/datasets/sylvainhellin/ifc-bench): questions **CC BY 4.0**, Sylvain Hellin; models retain individual terms | AC20: KIT unrestricted, credit IAI/KIT. DigitalHub: MIT, copyright RWTH Aachen E3D. Fantasy Office 3: MIT, TUM Students. Duplex: CC BY-ND 3.0, no converted publication. HITOS: **GPL-3.0-or-later data**, no redistribution under project rules. This data licence is not a code dependency. |
| `habs` / HAER / HALS | **Public domain in the US / PDM**, [Library of Congress](https://www.loc.gov/pictures/collection/hh/) | Courtesy credit National Park Service / Library of Congress and retain the item's rights statement; identify renamed/downscaled sheets. |
| `finna` | **CC BY 4.0**, [Finna](https://finna.fi/) | Credit the specific creator and Helsinki City Archives or Architecture & Design Museum as the file manifest specifies. |
| `europeana` | Per item: **CC0, PDM, CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA**, including version/jurisdiction variants; [Europeana](https://www.europeana.eu/) | Preserve creator/institution attribution and exact item terms. NC items remain noncommercial; SA adaptations retain the applicable licence. No blanket public-domain claim. |
| `wikimedia` / WAFFLE file selection | Per item: **CC0, PDM, CC BY, CC BY-SA, OGL-UK-1.0**, Commons copyrighted-free-use or no-known-copyright-restrictions statements; [WAFFLE](https://github.com/TAU-VAILab/WAFFLE), [Commons](https://commons.wikimedia.org/) | The Commons drawing's author and exact licence/rights statement control, including version/jurisdiction variants; WAFFLE selection does not replace those terms. |

The following training datasets supplement the drawing sources. COCO/ImageNet below are upstream pretraining provenance, not additional local fine-tuning downloads.

| Dataset | Source and licence | Use / limits |
|---|---|---|
| CubiCasa5K dataset | [Official data deposit](https://zenodo.org/records/2613548), [project](https://github.com/CubiCasa/CubiCasa5k); `CC BY-NC-SA 4.0` for the dataset used here | Raster/SVG training annotations. `train/build_v05.py` uses clean drawings only, excluding question-referenced and calibration IDs. The GitHub implementation/official baseline's separate licence says CC BY-NC 4.0; do not conflate it with the dataset terms. |
| FloorPlanCAD, Voxel51 mirror | [Dataset card](https://huggingface.co/datasets/Voxel51/FloorPlanCAD): narrative says `CC BY-NC 4.0`, while HF metadata says `CC BY-SA 4.0` | Treat as **noncommercial** because the sources conflict; do not infer commercial permission from metadata. Used for detector boxes, not segmentation masks. `train/manifest.json` currently records only the SA metadata and does not resolve this conflict. |
| Synthetic plans — **generated for demo** | [pipeline/synth.py](../pipeline/synth.py), local `data/synth/`; originating IFC/DXF documents and their individual licences remain relevant | Geometric labels for detector/segmenter training. The label is provenance, not a blanket licence or a claim of real surveyed geometry. Preserve upstream document attribution/restrictions. |
| COCO (upstream RT-DETR base pretraining) | [COCO terms](https://cocodataset.org/#termsofuse): annotations CC BY 4.0; images retain their individual Flickr terms | No COCO image redistribution here; the RT-DETR checkpoint's Apache-2.0 declaration is separate. |
| ImageNet (upstream ResNet34 encoder pretraining) | [ImageNet access terms](https://www.image-net.org/download.php): research/education access; original image rights remain with owners | No ImageNet images redistributed; exact source checkpoint membership is not recorded. |

Local provenance is in [train/manifest.json](../train/manifest.json), [train/build_v05.py](../train/build_v05.py), [train/check_overlap.py](../train/check_overlap.py), and `results/vision/v05_overlap.json`. The builder re-reads held-out lists from `data/sets/`, excludes calibration drawings, and checks IDs, SHA-256 and perceptual hashes before output. Both Modal training scripts recheck IDs. These checks address our own fine-tuning data; they do not prove the pretrained Yytsi checkpoint never saw an evaluation drawing. Do not train or tune on held-out drawings, or present source-model training overlap as independent held-out accuracy.

## Local vision models and fine-tunes

| Model / status | Source and base licence | Training data / implementation | Resulting checkpoint treatment |
|---|---|---|---|
| ResNet34-UNet, Yytsi base and V-06 fine-tune | [Yytsi/floorplan-to-3d-walls](https://huggingface.co/Yytsi/floorplan-to-3d-walls), [upstream code](https://github.com/Yytsi/floorplan-to-3d): model card labels weights MIT | Base: ImageNet-pretrained ResNet34, then CubiCasa5K high-quality and high-quality-architectural splits; exact train/evaluation drawing membership is unclear. Our [train/modal_seg.py](../train/modal_seg.py) loads `/data/yytsi_best.safetensors` into [vision/unet_resnet34.py](../vision/unet_resnet34.py); trains only mask-capable clean CubiCasa5K and synthetic records. Classes floor/wall/door/window. | `weights/unet_ft/best.safetensors`; upstream MIT declaration does not remove CubiCasa training-data restrictions. Treat fine-tuned weights as noncommercial; retain upstream notices and data attribution. |
| RT-DETR V-07 detector fine-tune | [PekingU/rtdetr_r50vd](https://huggingface.co/PekingU/rtdetr_r50vd), **Apache-2.0**; base card lists COCO training | [train/modal_det.py](../train/modal_det.py) uses Transformers RTDetrForObjectDetection/processor and V-05 clean CubiCasa5K + FloorPlanCAD + synthetic records. Classes door/window/toilet/sink/shower/bathtub. Trains on Modal; no local training. | Script saves `/out/det/best` (model and processor); local inference checkpoints include `weights/rtdetr_ep/`. Preserve Apache licence/NOTICE and mark modifications. Project release treatment: **CC BY-NC-SA 4.0 obligations from CubiCasa5K**, with FloorPlanCAD permission unresolved; not commercially cleared. |
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

## Dependency licence check — X-18

Checked the declared packages in [web/package.json](../web/package.json), [pyproject.toml](../pyproject.toml), [requirements.txt](../requirements.txt), [Vercel requirements](../deploy/vercel_api/requirements.txt) and [Dockerfile](../deploy/Dockerfile), plus npm lockfile licences and local Python distribution metadata. **No direct dependency declares GPL or AGPL as its package licence; `ultralytics` and `PyMuPDF` are absent.** This is a manifest/installed-metadata check, not a binary or legal compliance audit.

| Component / declared packages | Licence / evidence |
|---|---|
| IfcOpenShell `0.9.0.post1` | **LGPL-3.0-or-later**, installed distribution metadata and [upstream LGPL text](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/COPYING.LESSER); preserve notices and applicable source/relinking obligations. LGPL is separate from GPL/AGPL. |
| three.js | **MIT**, [upstream licence](https://github.com/mrdoob/three.js/blob/dev/LICENSE) |
| React, React DOM, Tailwind, Vite, Vitest, jsdom, pixelmatch, pngjs; React/Three types and Vite React plugin | MIT package metadata; lucide-react ISC; TypeScript and Playwright Apache-2.0; Node types MIT |
| Python MIT family | ezdxf, fastapi, jsonschema, langdetect, onnxruntime, pydantic, pygltflib, pyyaml, trimesh, fast-simplification; Pillow MIT-CMU |
| Python Apache-2.0 family | asyncpg, onnx, opencv-python-headless, python-multipart, rapidocr-onnxruntime, transformers; torch records a multi-licence expression including Apache/BSD/LLVM-exception notices |
| Python BSD family | httpx, numpy, python-dotenv, scipy, shapely, sse-starlette, torchvision, uvicorn; retain bundled notices as well as top-level licences |
| PDF tools | pdfminer.six MIT; pypdfium2 BSD-3-Clause / Apache-2.0 plus bundled PDFium third-party notices |
| OpenUSD `usd-core` | Installed `26.11` metadata: **LicenseRef-TOST-1.0**. Preserve that wheel's OpenUSD and third-party notices; do not label all versions Apache or MIT. |
| Development tools | pytest MIT, pytest-asyncio Apache-2.0, ruff MIT; npm transitive metadata includes **MPL-2.0**, which is separate from GPL/AGPL |
| **Bundled runtime exception to a blanket “no GPL anywhere” claim** | Local SciPy `1.18.1` metadata explicitly lists GCC `libgfortran`/`libgcc` as **GPL-3.0-or-later WITH GCC-exception-3.1**, and `libquadmath` as **LGPL-2.1-or-later**. Retain these notices; this is not a GPL-only application dependency. Shapely's GEOS native library is also LGPL. No dependency was changed for this row. |

The npm lockfile has no GPL/AGPL licence entries. Python installed metadata does contain the SciPy runtime notices above, so **“no GPL/AGPL direct packages” must not be shortened to “all dependencies are MIT” or “no GPL text anywhere.”** The noncommercial/share-alike fine-tuned checkpoints and GPL-licensed HITOS data remain separate from the code dependency result.

## Dependencies: knowledge graph view (F-KG-UI)
- d3-force 3.0.0 (ISC licence, permissive) runs the force layout of the project Graph tab on a canvas. Types: @types/d3-force (MIT). No GPL/AGPL code.

## Detector experiment (experiments/detector, off by default)
- **ultralytics YOLO11** (code and pretrained weights): AGPL-3.0, https://github.com/ultralytics/ultralytics. Used only in `experiments/detector/` (Modal training/inference). It runs only when `PDF_DETECT` is set; the default product path does not import it. Allowed by team decision (15 Nov, 06:53) with this credit.
- Training data: Swiss dataset drawings rendered by our own renderer (no held-out/question drawings in the clean run). No weights are committed.
