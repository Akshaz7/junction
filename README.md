# Hologram

Junction 2026 · Team RS3 · Stoa challenge: **Make Blueprints Talk**

“We rebuilt Stoa's product in two days. Then we built the part that does not exist yet.” — [project brief](CLAUDE.md)

Hologram answers English questions about construction drawings and BIM models with visible proof. The same numbered items connect **2D drawing boxes**, **3D highlights** through “Visualise it”, and **AR on an iPhone** through “Show on table”. A drawing is read into a structured **plan map** so supported counts and measurements can use code; models handle questions needing interpretation. Answers must make missing evidence and uncertainty explicit. See [CONTRACT.md](CONTRACT.md) for the answer format and shared item IDs.

Open the [live app](https://hologram-khaki.vercel.app/), upload a drawing through **Data → Upload**, then ask and inspect its citations. The judging flow continues from laptop proof to the same phone chat, table AR, and a spoken question returning to the laptop. The [demo script](docs/DEMO.md) gives exact clicks, two-minute and five-minute takes, backup questions, and device checks still required for the AR build-up and voice animation. The [submission checklist](docs/SUBMISSION.md) tracks links, video, report and licences for Sunday 15 November at 10:00 EET. Recorded accuracy and cost evidence are in [docs/ACCURACY.md](docs/ACCURACY.md); final metrics remain pending until tied to a selected result run.

## Research

Our [research record](docs/RESEARCH.md) links the sources, implementation choices and source-data checks.
[CubiCasa5K](https://arxiv.org/abs/1904.01920) and [Raster-to-Vector](https://jiajunwu.com/papers/im2cad_iccv.pdf) informed floor-plan parsing.
[Swiss Dwellings](https://zenodo.org/records/7788422) supplies apartment and room geometry.
[buildingSMART](https://github.com/buildingSMART/IFC4.3.x-development/blob/master/docs/schemas/shared/IfcSharedBldgElements/Entities/IfcStair.md) and [IfcOpenShell](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html) informed assembly counting.
We distinguish research papers, official documentation and non-peer-reviewed vendor articles, and state what our checks establish.

## Run locally

Install Python and uv, Node.js/npm, and Docker with Compose; the Python version is pinned in [pyproject.toml](pyproject.toml). Start Docker, then run from the repo root:

```sh
uv sync
npm --prefix web ci
make dev
```

No provider keys are required: the model layer selects its deterministic `fake` provider when none are available ([engine/models/core.py](engine/models/core.py)). `make dev` starts Docker PostgreSQL on **localhost:5433**, the web app at **http://localhost:5173**, and FastAPI at **http://localhost:8000**; API health is `/api/health` ([Makefile](Makefile), [docker-compose.yml](docker-compose.yml), [server/config.py](server/config.py)). The web dev server proxies `/api` and `/ws` to the API ([web/vite.config.ts](web/vite.config.ts)). Stop the stack with Ctrl-C; `make db-down` stops PostgreSQL.

Drawings and derived artifacts are local inputs, not bundled with the code. Use an authorised dataset under `data/junction-dataset-preview/`, derived files under `artifacts/`, or the app's upload control. See [pipeline/registry.py](pipeline/registry.py) and [pipeline/batch.py](pipeline/batch.py) for dataset preparation. Starting the stack alone does not create plan maps or demonstrate real-model accuracy.

For optional services, copy [.env.example](.env.example) to a local `.env` and fill only the settings you need. Never commit `.env`. Its setting names are:

```text
ANTHROPIC_API_KEY  GEMINI_API_KEY  NVIDIA_API_KEY  RUNWARE_API_KEY
FEATHERLESS_API_KEY  HF_TOKEN  ELEVENLABS_API_KEY
MODAL_TOKEN_ID  MODAL_TOKEN_SECRET  CLOUDINARY_URL  CONTEXT_DEV_API_KEY
DATABASE_URL  AIVEN_TOKEN  AIVEN_PROJECT
GOOGLE_APPLICATION_CREDENTIALS  DRIVE_FOLDER_ID  APPLE_TEAM_ID
```

Leave `DATABASE_URL` unset or empty for local PostgreSQL; configured credentials enable the corresponding providers ([server/config.py](server/config.py), [engine/models/core.py](engine/models/core.py)).

### iOS

Follow [ios/README.md](ios/README.md) for Xcode, XcodeGen, signing, network URLs, phone pairing, and Developer Mode. Install on a connected, trusted iPhone with:

```sh
bash ios/scripts/install_on_device.sh
```

The installer routes its build through the heavy-job wrapper. Physical AR placement requires an iPhone; simulator tests exercise scene and bridge logic ([ios/README.md](ios/README.md), [ios/HologramUITests/README.md](ios/HologramUITests/README.md)).

### Tests

```sh
make test

# List Playwright e2e tests, then run them.
bash scripts/heavy.sh npm --prefix web run test:e2e -- --list
bash scripts/heavy.sh npm --prefix web run test:e2e

# Generate the iOS project and test on the configured simulator.
xcodegen generate --spec ios/project.yml
bash scripts/heavy.sh xcodebuild test \
  -project ios/Hologram.xcodeproj -scheme Hologram \
  -destination 'platform=iOS Simulator,name=Hologram iPhone' \
  -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO
```

`make test` runs Python tests and web unit tests ([Makefile](Makefile)). Specs in [web/e2e/](web/e2e/) cover the shell, chat, document viewer, data/upload, dashboard, overview, voice, linked drawing/model selection, scene commands, live updates, cutaway, performance, and visual fidelity. Playwright reuses a running web server or starts one ([web/playwright.config.ts](web/playwright.config.ts)). Some specs use fixtures; live flows need the API and prepared artifacts. The fidelity suite also needs the local reference pack. iOS UI tests need the running web app and API; see [ios/HologramUITests/README.md](ios/HologramUITests/README.md) for URL overrides. Browser and simulator launches may require a normal terminal outside the worker sandbox ([GOTCHAS.md](GOTCHAS.md)).

## Architecture

```text
pipeline/ (document ingestion; vision/ reads raster drawings)
    ↓
artifacts/<doc_id>/
    planmap-<page>.json + elements.json (IFC) + scene.json
    scene.glb + scene.usdz
    ↓
engine/
    router: rules → Nemotron → Runware
    solvers over plan maps / IFC metadata
    model tasks only through engine/models call()
    ↓
server/ — FastAPI + PostgreSQL + /ws live events
    ├── web/ — Vite + React; three.js in src/viewer3d/
    └── ios/ — SwiftUI web shell + RealityKit / ARKit
```

[CONTRACT.md](CONTRACT.md) defines document IDs, shared item IDs, coordinates, artifact formats, answers, scene commands, and the native AR bridge. [docs/API.md](docs/API.md) describes endpoints. Model configuration and fallback chains live in [engine/models/models.yaml](engine/models/models.yaml); the provider layer owns caching and logged costs. Available artifacts depend on the input and completed ingestion stages.

## Accuracy and cost

Numbers last refreshed: 2026-11-14 08:25 EET.

These are recorded local results, not a claim that every drawing is answered accurately. Latest sample (200 questions, `e09_text`) and the first full run (`full_1`, all 63,307 numeric questions; text questions subsampled 1 in 6):

| Metric | sample200 accuracy | answered | abstained | full_1 accuracy | answered | abstained |
| --- | --- | --- | --- | --- | --- | --- |
| Overall | 0.6631 | 0.7251 | 16 | 0.5671 | 0.6272 | 6071 |
| Count | 0.6301 | 0.6715 | 9 | 0.5608 | 0.6002 | 3677 |
| Area | 0.7949 | 0.9394 | 6 | 0.6234 | 0.9098 | 2293 |
| Length | 1.0 | 1.0 | 0 | 0.0 | None | 32 |
| Volume | 0.0 | None | 1 | 0.0 | None | 69 |
| Text (model-judged, `text.ALL`) | 0.7273 | – | 2 | 0.4205 (140-question subsample) | – | 52 |

Evidence: [results/bench/e09_text.json](results/bench/e09_text.json), [results/bench/full_1.json](results/bench/full_1.json) (`cells`). Numeric answers cost $0 (plan-map code); the full run cost $0.05 in total. Stress run [results/stress/stress-r2.json](results/stress/stress-r2.json): 421 cases, 0 crashes, 0 server errors, 0 invalid answers, 0 prompt-injection leaks.

Numeric accuracy includes abstentions as unsuccessful; answered accuracy excludes them, and text questions are unscored in those cells ([engine/bench.py](engine/bench.py)). The source/type cells with numeric abstentions are `ifc_models × area` (**15**), `ifc_models × count` (**2**), `ifc_models × volume` (**1**), `opening_design × area` (**1**), `opening_design × count` (**2**), `swiss_dwellings × area` (**18**), and `swiss_dwellings × count` (**4**), all in [results/bench/sample200-r2.json](results/bench/sample200-r2.json).

**Text answers are reported separately:** **3 correct**, **1 partial**, **4 wrong**, **5 abstained**, and **0 unjudged**, with answered-text accuracy **0.375** and partial-credit score **0.4375**, in `text.ALL` of [results/bench/sample200-r2.json](results/bench/sample200-r2.json). The `ifc_bench` text cell abstains on **4** questions and the `opening_design` text cell on **1**; the latter has null accuracy because every answer abstained, in [results/bench/sample200-r2.json](results/bench/sample200-r2.json). These text metrics exclude abstentions from their denominator ([engine/bench.py](engine/bench.py)).

**Routing:** the rules-only run records type-and-kind accuracy **0.9786** over **420** questions, with **0 model calls** and **$0.0** logged cost, in [results/router_cost.json](results/router_cost.json). The forced-model run records accuracy **0.95** over **120** questions, using **118 NVIDIA** calls and **2 Runware** calls, at total cost **$0.000295** and mean cost **$0.00000246** per question, in [results/router_model_only.json](results/router_model_only.json). These measure routing, not answer accuracy.

**Raster vision:** the baseline records exact-count accuracy **0.52** over **1894** questions; its official unseen validation/test subset records **0.542** over **321**, in [results/vision/baseline.json](results/vision/baseline.json). Project-held-out drawings may still have appeared in a pretrained model's original training; known splits and uncertainties are recorded in [docs/MODELS.md](docs/MODELS.md).

The default free verification pass records exact-count accuracy of **0.32 windows**, **0.817 toilets**, **0.594 sinks**, **0.123 showers/bathtubs**, and **0.443 doors**; the optional bathroom-crop check raises showers/bathtubs to **0.33** at recorded cost **$0.00062 per drawing**, in [results/vision/v09_final.json](results/vision/v09_final.json). Generalisation remains limited: abstain rates are **0.446** for Swiss dwellings, **0.925** for Wikimedia, **1.0** for HABS, and **0.975** for Finna; Wikimedia, HABS, and Finna have no ground-truth answers in the dataset, so no accuracy is claimed for them, in [results/vision/generalisation.json](results/vision/generalisation.json).

**Logged model cost snapshot:** summing `cost_usd` across the first **4949 records** of [results/costs.jsonl](results/costs.jsonl) gives **$2.420721**: **$2.406951 Runware**, **$0.01377 ElevenLabs**, **$0.0 NVIDIA**, and **$0.0 fake**. This is the append-only model log's reported cost, not total infrastructure spend; later records will change the total.

The benchmark records total cost **$0.000455**, including text judging, while numeric-cell answer cost is **$0.0**, in [results/bench/sample200-r2.json](results/bench/sample200-r2.json). These are separate scopes from the cumulative model log.

**Visual fidelity is currently failing:** counting phase statuses gives **33 pass**, **5 fail**, and **7 not applicable** out of **45 total phases**, with **38 measured** and **7 unexplained regions**, in [results/fidelity/report.json](results/fidelity/report.json). This comparison measures appearance against the local reference pack, not drawing-answer accuracy.

## IFC conversion

Install the standalone IfcConvert binary in `tools/`; the Python `ifcopenshell` package does not supply that executable. Keep element GUIDs as node names and export with Y up. Run conversions through the shared heavy-job wrapper ([CLAUDE.md](CLAUDE.md), [pipeline/ifc_scene.py](pipeline/ifc_scene.py)):

```sh
bash scripts/heavy.sh ./tools/IfcConvert \
  --exclude entities IfcOpeningElement -j 4 \
  --use-element-guids --y-up model.ifc model.glb
```

Use a fresh output path: an existing output can cause IfcConvert to wait on stdin. Its default exclusions drop spaces as well as openings; explicitly excluding only `IfcOpeningElement` retains `IfcSpace`. GLB node names join geometry to IFC metadata in `elements.json`; names, classes, storeys, and property sets come from the IFC metadata pass. Current scenes use metres, Y up, and a recorded origin offset, as specified in [CONTRACT.md](CONTRACT.md). See [GOTCHAS.md](GOTCHAS.md) for converter caveats and [pipeline/ifc_scene.py](pipeline/ifc_scene.py) for the current exporter. The old spike helpers, [scripts/extract_elements.py](scripts/extract_elements.py) and [scripts/validate_glb.py](scripts/validate_glb.py), use a legacy index schema.

## Credits and licences

Repository code is **MIT**, see [LICENSE](LICENSE). Dataset and model rights are separate. The inventory in [docs/MODELS.md](docs/MODELS.md) records:

| Name | Licence / status |
| --- | --- |
| Claude via Runware (Sonnet/Opus/Haiku; recorded Fable candidate) | Proprietary hosted API; [Runware terms](https://runware.ai/terms). Direct fallback: [Anthropic commercial terms](https://www.anthropic.com/legal/commercial-terms). No weights redistributed. |
| Gemini 3.x and Gemini 4 Hydrogen/Carbon via Runware | Proprietary hosted API; [Runware terms](https://runware.ai/terms). Direct fallback: [Gemini API terms](https://ai.google.dev/gemini-api/terms). Gemini 4 entries are catalog/price candidates in current config. |
| Nemotron 3.5 Lightning / 3.5 Super VL (NVIDIA; VL recovery hosted on Verda) | **OpenMDW-1.1**, [Lightning card](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/modelcard), [VL card](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b/modelcard); hosting/API terms separate |
| Nemotron 3 Super | **NVIDIA Nemotron Open Model License**, [official card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16) |
| Featherless Qwen3-VL / Qwen3-Next candidate | **Apache-2.0** model cards; hosted-service terms separate |
| ElevenLabs Flash v2.5 | Proprietary TTS; [publication terms](https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform). Paid non-beta output can have commercial rights; free-plan output is noncommercial with attribution. |
| Runware Fish Audio S2.1 Pro | Hosted API terms; no S2.1 Pro weight redistribution permission established here |
| Yytsi ResNet34-UNet, floorplan-to-3d-walls | Base card declares MIT; CubiCasa5K training restrictions remain relevant |
| Our RT-DETR detector and UNet fine-tuned weights | RT-DETR base **Apache-2.0**; project carries **CC BY-NC-SA 4.0** obligations from CubiCasa5K into derived checkpoints. Noncommercial demo/research treatment; FloorPlanCAD rights conflict remains unresolved. |
| CubiCasa5K official multi-task, hg_furukawa_original | CC BY-NC 4.0 code and weights; internal baseline, not shipped as the final detector |
| CubiCasa5K dataset | **CC BY-NC-SA 4.0**; non-commercial use and share-alike obligations apply |
| FloorPlanCAD training data | Card narrative CC BY-NC 4.0 vs metadata CC BY-SA 4.0: treat as noncommercial; commercial permission unresolved |
| Swiss Dwellings | **CC BY 4.0**, credit Standfest and collaborators / Archilyse AG; identify rendered/labelled changes |
| OpeningDesign / Aalseth | **CC BY-SA 4.0**, or MIT for the individual projects listed in the dataset manifest; retain project-team credits |
| IFC models / IFC-Bench | Per model: KIT unrestricted (AC20; credit IAI/KIT), MIT (DigitalHub; RWTH E3D), CC BY 4.0, CC BY-ND 3.0 or GPL data. IFC-Bench questions CC BY 4.0, Sylvain Hellin. ND conversions and HITOS GPL data are excluded from publication. |
| HABS / HAER / HALS | Public domain in the US / PDM; courtesy credit National Park Service / Library of Congress |
| Finna | **CC BY 4.0**, exact creator/archive credit per file |
| Europeana | Per file: CC0/PDM, CC BY/SA/NC/NC-SA and version/jurisdiction variants; retain exact institution/creator terms |
| Wikimedia / WAFFLE-selected drawings | Per file: CC0/PDM, CC BY/SA, OGL-UK-1.0 or individual Commons rights statements; retain author and exact terms |
| Synthetic training/demo plans | **generated for demo**; inherit originating document restrictions |
| Upstream COCO / ImageNet pretraining | COCO annotations CC BY 4.0, images retain individual rights; ImageNet research/education access terms. Images are not redistributed here. |
| RF-DETR-medium “2dplan2strct” | rfdetr Apache-2.0; checkpoint non-commercial research only; evaluated, not used |
| Patnev71 SegFormer-B0 floorplan | Licence listed as “other”; rejected |
| RapidOCR / rapidocr-onnxruntime | Apache-2.0 |
| IfcOpenShell / three.js | **LGPL-3.0-or-later** / **MIT**, respectively; preserve library and third-party notices |
| Deterministic fake provider / device speech | Fake adapter MIT; platform speech service terms apply to device recognition/synthesis |

The same [inventory](docs/MODELS.md) records exact model IDs, source links, training provenance and dependency licences; configuration alone does not prove a provider ran. API access does not make hosted model weights MIT. The challenge distribution is for noncommercial Junction use; each drawing keeps its own `data/<source>/LICENSE.md` credit and terms.

**Dependency check (X-18):** `web/package.json`, Python project/requirements, the Dockerfile, npm lockfile licences and installed Python metadata show **no direct GPL/AGPL package dependencies** (`ultralytics` and `PyMuPDF` are absent). LGPL IfcOpenShell is present. Local SciPy metadata lists bundled **GPL-3.0-or-later WITH GCC-exception-3.1** runtimes and **LGPL-2.1-or-later** libquadmath; these notices must be retained. See the [dependency table](docs/MODELS.md#dependency-licence-check--x-18) for scope and other licences, including OpenUSD and native-library notices.

The retained `samples/aalseth_stairs.*` derive from OpeningDesign's [Aalseth Residence](https://github.com/OpeningDesign/Aalseth_Residence), credited to the entire project team under CC BY-SA 4.0. `samples/digital_hub_arc.*` derive from DigitalHub, copyright RWTH Aachen University, E3D Institute of Energy Efficiency and Sustainable Building, under MIT; see the source `LICENSE.md` files under `data/junction-dataset-preview/data/` for original dataset credits.

Only publishable sources belong in the published app. Scenes marked `publishable: false`, including Duplex and Dental Clinic (CC BY-ND) and hitos (GPL data), must stay out of app publication and redistribution ([CLAUDE.md](CLAUDE.md), [pipeline/ifc_scene.py](pipeline/ifc_scene.py), [pipeline/extrude.py](pipeline/extrude.py)). The dataset and local reference pack are not redistributed here. Generated samples must be labelled **“generated for demo”** ([CLAUDE.md](CLAUDE.md)).

Built for the Stoa challenge at Junction 2026 with Stoa's permission to reference their product flow; no Stoa code, logo or drawings are included.

The app's wordmark is **Hologram**.

## Sponsor tools

See [docs/sponsors/README.md](docs/sponsors/README.md) for integration evidence and limitations for Nemotron, Runware, ElevenLabs, Aiven, and Codex, plus the status of other planned tools.
