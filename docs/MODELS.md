# Models, providers and datasets

Snapshot: 2026-11-14. API IDs, provider settings, prices and fallback order below are transcribed from [engine/models/models.yaml](../engine/models/models.yaml), including working-tree changes. These are **configured accounting rates**, not a fresh price quote or a claim that every model was successfully called. Usage/cost measurements belong in `results/`. Hosted API access does not grant rights to redistribute model weights.

## Provider configuration

All model inference goes through `engine.models.call(task, messages, images=None, schema=None, *, request_id=None, only=None)`; see [core.py](../engine/models/core.py) and [providers.py](../engine/models/providers.py). Keys are read fresh from the process environment, then `.env`; values are never documented or logged here.

| Provider key | Credential environment variable | Configured base URL | Adapter / terms and catalogue source |
|---|---|---|---|
| `fake` | None | Local | Deterministic local adapter; no external service or key; — |
| `gemini` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta` | Gemini REST; hosted service terms; [models](https://ai.google.dev/gemini-api/docs/models), [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `nvidia` | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` | OpenAI-compatible; configured free-tier accounting; [NVIDIA catalogue](https://build.nvidia.com/models) |
| `anthropic` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` | Anthropic Messages; configured API version `2026-10-21`; [models](https://platform.claude.com/docs/en/about-claude/models), [pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `runware` | `RUNWARE_API_KEY` | `https://api.runware.ai/v1` | Dedicated task API (`textInference` / `audioInference`), not OpenAI-compatible; [Runware docs](https://runware.ai/docs/) |
| `runware_claude` | `RUNWARE_API_KEY` | `https://api.runware.ai/v1` | Anthropic Messages format through Runware; shared RUNWARE_API_KEY, Bearer auth, version `2026-10-21`; [Runware docs](https://runware.ai/docs/) |
| `verda` | `VERDA_INFERENCE_KEY` | `https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1` | OpenAI-compatible dedicated container; time-billed outside per-token accounting; [Verda docs](https://docs.verda.com/) |
| `featherless` | `FEATHERLESS_API_KEY` | `https://api.featherless.ai/v1` | OpenAI-compatible; [model catalogue](https://api.featherless.ai/v1/models) |
| `elevenlabs` | `ELEVENLABS_API_KEY` | `https://api.elevenlabs.io/v1` | ElevenLabs REST; default voice `SAz9YHcvj6GT2YYXdXww` (River); [ElevenLabs docs](https://elevenlabs.io/docs/overview) |

## Configured model prices

USD per **one million input/output tokens**, except the explicitly stated audio units. Every entry in YAML `prices` is listed, including models not selected by a current task. The source of each number is the linked local configuration, whose comments cite provider catalogues; the external provider links above are reference links, not evidence of a new pricing check.

| Provider | Exact model ID | Input USD / 1M | Output USD / 1M | Tasks using it (primary or fallback) |
|---|---|---:|---:|---|
| `gemini` | `gemini-3.8-flash` | 1.500 | 7.500 | `read_drawing`, `write_answer` |
| `gemini` | `gemini-3.5-flash-lite` | 0.300 | 2.500 | `reader_plan`, `recount`, `forced_answer`, `verify_item`, `judge_text`, `speech_intent` |
| `nvidia` | `nvidia/nemotron-3.5-lightning-30b-a3b` | 0.000 | 0.000 | `route`, `chat`, `scene_intent`, `judge_text`, `speech_intent` |
| `nvidia` | `nvidia/nemotron-3-super-120b-a12b` | 0.000 | 0.000 | `advise` |
| `nvidia` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | 0.000 | 0.000 | `verify_item` |
| `verda` | `nemotron-3.5-super-vl` | 0.000 | 0.000 | `reader_plan`, `read_drawing`, `forced_answer`, `verify_item`, `write_answer`, `chat` |
| `anthropic` | `claude-sonnet-5-5` | 2.000 | 10.000 | `write_answer`, `chat`, `advise` |
| `anthropic` | `claude-haiku-5-5` | 0.100 | 0.500 | Configured price only; no current task |
| `runware_claude` | `claude-haiku-5-5` | 0.100 | 0.500 | Configured price only; no current task |
| `runware_claude` | `claude-sonnet-5-5` | 2.000 | 10.000 | Configured price only; no current task |
| `runware_claude` | `claude-opus-5-5` | 4.000 | 20.000 | Configured price only; no current task |
| `runware_claude` | `claude-fable-5-2` | 8.000 | 40.000 | Configured price only; no current task |
| `runware_claude` | `claude-opus-5` | 5.000 | 25.000 | Configured price only; no current task |
| `featherless` | `Qwen/Qwen3-VL-30B-A3B-Instruct` | 0.150 | 0.500 | `read_drawing` |
| `featherless` | `Qwen/Qwen3-Next-80B-A3B-Instruct` | 0.125 | 1.150 | Configured price only; no current task |
| `elevenlabs` | `eleven_flash_v2_5` | 170.000 | 0.000 | `tts` |
| `runware` | `google:gemini@3.5-flash` | 1.500 | 9.000 | `reader_plan`, `read_drawing`, `recount` |
| `runware` | `google:gemini@3.1-flash-lite` | 0.250 | 1.500 | `route`, `recount`, `forced_answer`, `verify_item`, `chat`, `scene_intent`, `judge_text`, `speech_intent` |
| `runware` | `anthropic:claude@sonnet-4.6` | 3.000 | 15.000 | `reader_plan`, `write_answer`, `chat`, `advise` |
| `runware` | `anthropic:claude@haiku-4.5` | 1.000 | 5.000 | Configured price only; no current task |
| `runware` | `fishaudio:s2.1@pro` | 0.000 | 0.000 | `tts` |

`fake` uses runtime model ID `fake-1`, zero cost; it has no `prices` entry or configured task chain. `claude-haiku-5-5`, Runware `anthropic:claude@haiku-4.5`, and Featherless `Qwen/Qwen3-Next-80B-A3B-Instruct` are price-table entries without a current task.

Accounting qualifications from the YAML and adapters:

- Gemini `gemini-3.8-flash` uses 1.50/7.50 in the table; the config comment records a 0.75/3.75 promotion through 2026-12-31. No promotion adjustment is made by the price table.
- Anthropic `claude-haiku-5-5` uses the configured ≤100k-prompt-token rate 0.10/0.50; the comment records 0.50/2.50 above that threshold. The code does not select a price tier dynamically.
- NVIDIA free-tier model calls record zero USD. Verda's zero token rates do not include dedicated-container time charges; they do not mean that hosting is free.
- ElevenLabs `eleven_flash_v2_5`: one input accounting unit is one **character**. 170 USD per million characters = 0.00017 USD/character, output zero. This is the config's conservative Creator-plan estimate, not an LLM token price.
- Runware `fishaudio:s2.1@pro`: table entries are zero because the provider returns request cost. The YAML records 0.000015 USD per UTF-8 byte; returned cost takes precedence. Other Runware models also use returned request cost when available.
- `runware_claude` prices are newly configured, not independently verified here. The YAML marks the output estimates for `claude-opus-5-5`, `claude-fable-5-2`, `claude-opus-5` **UNVERIFIED** (five times input), and the `claude-opus-5` input price is also assumed/unverified. Treat these as provisional accounting assumptions, not published prices; no current task selects this provider.
- A provider response's `cost_usd` overrides token estimates. Cache hits are logged at zero cost. Costs are not benchmarks of accuracy or availability.

## Task chains

Each arrow means “try the next provider/model on failure”; a missing key is skipped. Task parameters (`max_tokens`, temperature, extra body) come from the primary task configuration and apply across its chain. `—` means unset, not zero.

| Task | Ordered provider/model chain | max_tokens | temperature |
|---|---|---:|---:|
| `route` | `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `runware:google:gemini@3.1-flash-lite` | 512 | 0 |
| `reader_plan` | `runware:anthropic:claude@sonnet-4.6` → `runware:google:gemini@3.5-flash` → `gemini:gemini-3.5-flash-lite` → `verda:nemotron-3.5-super-vl` | 1200 | 0 |
| `read_drawing` | `gemini:gemini-3.8-flash` → `featherless:Qwen/Qwen3-VL-30B-A3B-Instruct` → `runware:google:gemini@3.5-flash` → `verda:nemotron-3.5-super-vl` | 8192 | — |
| `recount` | `runware:google:gemini@3.1-flash-lite` → `gemini:gemini-3.5-flash-lite` → `runware:google:gemini@3.5-flash` | 200 | 0 |
| `forced_answer` | `runware:google:gemini@3.1-flash-lite` → `gemini:gemini-3.5-flash-lite` → `verda:nemotron-3.5-super-vl` | 500 | 0 |
| `verify_item` | `gemini:gemini-3.5-flash-lite` → `nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b` → `runware:google:gemini@3.1-flash-lite` → `verda:nemotron-3.5-super-vl` | 512 | — |
| `write_answer` | `anthropic:claude-sonnet-5-5` → `gemini:gemini-3.8-flash` → `runware:anthropic:claude@sonnet-4.6` → `verda:nemotron-3.5-super-vl` | 1024 | — |
| `chat` | `anthropic:claude-sonnet-5-5` → `runware:anthropic:claude@sonnet-4.6` → `runware:google:gemini@3.1-flash-lite` → `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `verda:nemotron-3.5-super-vl` | 700 | — |
| `scene_intent` | `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `runware:google:gemini@3.1-flash-lite` | 128 | 0 |
| `judge_text` | `gemini:gemini-3.5-flash-lite` → `runware:google:gemini@3.1-flash-lite` → `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` | 512 | — |
| `advise` | `nvidia:nvidia/nemotron-3-super-120b-a12b` → `anthropic:claude-sonnet-5-5` → `runware:anthropic:claude@sonnet-4.6` | 1024 | — |
| `speech_intent` | `gemini:gemini-3.5-flash-lite` → `nvidia:nvidia/nemotron-3.5-lightning-30b-a3b` → `runware:google:gemini@3.1-flash-lite` | 256 | — |
| `tts` | `elevenlabs:eleven_flash_v2_5` → `runware:fishaudio:s2.1@pro` | — | — |

`route` and `scene_intent` set `extra_body.chat_template_kwargs.enable_thinking=false`. Verda remains last in each chain that includes it. `reader_plan` is the tool-using reader planner; `recount` counts a raster object kind; `forced_answer` is a best-effort final rung, so its output must not be described as a verified code result. `chat` handles conversation without a selected document. `judge_text` is bench grading, not the answer writer. Numeric/code routes can avoid model calls entirely.

The runtime can override these chains: `MODELS_FAKE=1` (also `true`/`yes`) or absence of **all** non-fake provider keys forces `fake:fake-1`. `only=(provider,model)` pins a model when fake mode is not forced. Per-provider budget caps are read from [COSTS.md](../COSTS.md); a cap failure moves to the next candidate or raises when exhausted. Rate-limit retries have backoff (at most five retries). Successful calls and cache hits log to `results/costs.jsonl` by default; a registered DB logger can also receive the records. Cache is keyed by full request/model/parameters. `MODELS_YAML`, `MODELS_CACHE_DIR`, `MODELS_COSTS_LOG` and `MODELS_COSTS_MD` override paths.

For speech input, [speech_routes.py](../server/speech_routes.py) only considers Gemini usable: other text-model fallback entries do not establish audio capability. TTS falls back to device speech if the configured audio chain cannot serve the request.

## Datasets and training provenance

| Dataset | Source and licence | Use / limits |
|---|---|---|
| CubiCasa5K dataset | [Official data deposit](https://zenodo.org/records/2613548), [project](https://github.com/CubiCasa/CubiCasa5k); **CC BY-NC-SA 4.0** for the dataset used here | Raster/SVG training annotations. `train/build_v05.py` uses clean drawings only, excluding question-referenced and calibration IDs. The GitHub implementation/official baseline's separate licence says CC BY-NC 4.0; do not conflate it with the dataset terms. |
| FloorPlanCAD, Voxel51 mirror | [Dataset card](https://huggingface.co/datasets/Voxel51/FloorPlanCAD): narrative says **CC BY-NC 4.0**, while HF metadata says **CC BY-SA 4.0** | Treat as **noncommercial** because the sources conflict; do not infer commercial permission from metadata. Used for detector boxes, not segmentation masks. `train/manifest.json` currently records only the SA metadata and does not resolve this conflict. |
| Synthetic plans — **generated for demo** | [pipeline/synth.py](../pipeline/synth.py), local `data/synth/`; originating IFC/DXF documents and their individual licences remain relevant | Geometric labels for detector/segmenter training. The label is provenance, not a blanket licence or a claim of real surveyed geometry. Preserve upstream document attribution/restrictions. |

Local provenance is in [train/manifest.json](../train/manifest.json), [train/build_v05.py](../train/build_v05.py), [train/check_overlap.py](../train/check_overlap.py), and `results/vision/v05_overlap.json`. The builder re-reads held-out lists from `data/sets/`, excludes calibration drawings, and checks IDs, SHA-256 and perceptual hashes before output. Both Modal training scripts recheck IDs. These checks address our own fine-tuning data; they do not prove the pretrained Yytsi checkpoint never saw an evaluation drawing. Do not train or tune on held-out drawings, or present source-model training overlap as independent held-out accuracy.

## Local vision models and fine-tunes

| Model / status | Source and base licence | Training data / implementation | Resulting checkpoint treatment |
|---|---|---|---|
| ResNet34-UNet, Yytsi base and V-06 fine-tune | [Yytsi/floorplan-to-3d-walls](https://huggingface.co/Yytsi/floorplan-to-3d-walls), [upstream code](https://github.com/Yytsi/floorplan-to-3d): model card labels weights MIT | Base: ImageNet-pretrained ResNet34, then CubiCasa5K high-quality and high-quality-architectural splits; exact train/evaluation drawing membership is unclear. Our [train/modal_seg.py](../train/modal_seg.py) loads `/data/yytsi_best.safetensors` into [vision/unet_resnet34.py](../vision/unet_resnet34.py); trains only mask-capable clean CubiCasa5K and synthetic records. Classes floor/wall/door/window. | `weights/unet_ft/best.safetensors`; upstream MIT declaration does not remove CubiCasa training-data restrictions. Treat fine-tuned weights as noncommercial; retain upstream notices and data attribution. |
| RT-DETR V-07 detector fine-tune | [PekingU/rtdetr_r50vd](https://huggingface.co/PekingU/rtdetr_r50vd), **Apache-2.0**; base card lists COCO training | [train/modal_det.py](../train/modal_det.py) uses Transformers RTDetrForObjectDetection/processor and V-05 clean CubiCasa5K + FloorPlanCAD + synthetic records. Classes door/window/toilet/sink/shower/bathtub. Trains on Modal; no local training. | Script saves `/out/det/best` (model and processor); local inference checkpoints include `weights/rtdetr_ep/`. Preserve Apache licence/NOTICE and mark modifications; combined training data requires conservative noncommercial treatment. |
| CubiCasa5K official `hg_furukawa_original` baseline | [Official repository and licence](https://github.com/CubiCasa/CubiCasa5k); **CC BY-NC 4.0** implementation/checkpoint source | CubiCasa5K train split; segmentation, icons and room baseline in `weights/cubicasa_official/` | Internal baseline; not a permissively licensed final detector. |
| RF-DETR-medium `2dplan2strct` (evaluated, not selected) | [OsamaMo/2dplan2strct](https://huggingface.co/OsamaMo/2dplan2strct); prior project record: rfdetr code Apache-2.0, checkpoint noncommercial research only | Training data undisclosed; wall/room/door/window candidate | No commercial weight permission established by the code licence. |
| SegFormer-B0 floorplan (rejected candidate) | [Patnev71/segformer-b0-finetuned-floorplan](https://huggingface.co/Patnev71/segformer-b0-finetuned-floorplan); card marked `other` in prior project record | Training data unknown; room/background candidate | Not used; no permissive weight licence established. |
| RapidOCR (`rapidocr-onnxruntime`) | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR), Apache-2.0 project | Local OCR; exact bundled OCR checkpoint/training provenance not recorded here | Retain package/model notices; project code licence alone is not evidence for an unidentified checkpoint. |

### Licence consequences for our fine-tuned weights

Repository code is MIT; third-party code, datasets, pretrained weights and our derived checkpoints keep their separate terms. Treat both fine-tunes as **noncommercial research/demo checkpoints**, not MIT-only assets and not commercially cleared models. The project conservatively carries CubiCasa5K's attribution, noncommercial and share-alike obligations into adapted training artifacts/weights where applicable. If distributing such adaptations, retain credits, identify changes and use the same/compatible share-alike terms; do not offer them under MIT alone. This is our conservative release treatment, not a categorical legal determination that every trained weight is automatically a copyright adaptation. See the [CC BY-NC-SA 4.0 terms](https://creativecommons.org/licenses/by-nc-sa/4.0/).

FloorPlanCAD's conflicting declarations leave commercial permission unresolved; the detector cannot become commercially cleared merely because its RT-DETR initialization is Apache-2.0. Yytsi's card declares MIT but also identifies CubiCasa5K training, so the original model card is not evidence that the training-data restrictions disappeared. Keep model/dataset provenance with any checkpoint; resolve rights or retrain on commercially cleared data before changing this treatment. Weights/data remain outside git under project rules. Synthetic samples still carry **generated for demo** and originating-document terms.

## Geometry libraries in the deploy image

[deploy/Dockerfile](../deploy/Dockerfile) installs `ifcopenshell==0.9.0.post1`, `pygltflib==1.16.5` and unpinned `usd-core` for IFC upload geometry and AR conversion. The image uses VLM ingestion without torch or local fine-tuned vision weights. The minimal Vercel API requirements are separate and do not themselves install these geometry packages.

| Package | Observed version / licence | Deploy use and redistribution consequence |
|---|---|---|
| `ifcopenshell` | **0.9.0.post1**, **LGPL-3.0-or-later**, confirmed in installed distribution metadata and [that release's metadata](https://pypi.org/project/ifcopenshell/0.9.0.post1/) | IFC parsing/geometry via `pipeline/ifc_scene.py`. LGPL is a distinct library licence, not the GPL-only Bonsai application. Keep LGPL/copyright notices and licence texts; when conveying a combined image, provide required corresponding library source/modifications and allow replacement/relinking of the library. It does not automatically relicense independent application code as GPL. |
| `usd-core` (OpenUSD) | **26.11** in `uv.lock` and installed metadata; **LicenseRef-TOST-1.0**, Tomorrow Open Source Technology License 1.0 | USD/USDZ creation. [Release licence](https://github.com/PixarAnimationStudios/OpenUSD/blob/v26.11/LICENSE.txt) states that it differs from Apache-2.0 in the trademark section; preserve its actual licence, required notices, attribution and modification notices. Do not label this installed version plain Apache-2.0 or MIT. |

The Dockerfile does not pin `usd-core`, so 26.11 is the checked local/lockfile version, not proof of the version inside a previously built deployment. Retain the notices for the wheel actually shipped, including bundled third-party components; the OpenUSD licence file includes their notices. See [usd-core metadata](https://pypi.org/project/usd-core/26.11/) and [IfcOpenShell LGPL text](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/COPYING.LESSER).
