# Hologram

Junction 2026 · Team RS3 · Stoa challenge: **Make Blueprints Talk**

“We rebuilt Stoa's product in two days. Then we built the part that does not exist yet.” — [project brief](CLAUDE.md)

Hologram answers English questions about construction drawings and BIM models with visible proof. The same numbered items connect **2D drawing boxes**, **3D highlights** through “Visualise it”, and **AR on an iPhone** through “Show on table”. A drawing is read once into a structured **plan map**; most subsequent answers use plain code over that map rather than another model call. Missing or unreliable evidence should produce an abstention. See [CONTRACT.md](CONTRACT.md) for the answer format and shared item IDs.

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

Numbers last refreshed: 2026-11-14 03:33:12 UTC.

These are recorded local results, not a claim that every drawing is answered accurately. The latest available non-fake benchmark is `sample200-r2`, with **200 questions**, **48 correct**, **96 wrong**, **43 numeric abstentions**, and **13 text questions excluded from numeric scoring**, in [results/bench/sample200-r2.json](results/bench/sample200-r2.json).

| Numeric metric or question type | Recorded accuracy | Accuracy among answered | Abstained | Evidence |
| --- | --- | --- | --- | --- |
| Overall | 0.2567 | 0.3333 | 43 | [results/bench/sample200-r2.json](results/bench/sample200-r2.json), `cells["ALL x ALL"]` |
| Count | 0.3219 | 0.3406 | 8 | [results/bench/sample200-r2.json](results/bench/sample200-r2.json), `cells["ALL x count"]` |
| Area | 0.0 | 0.0 | 34 | [results/bench/sample200-r2.json](results/bench/sample200-r2.json), `cells["ALL x area"]` |
| Length | 1.0 | 1.0 | 0 | [results/bench/sample200-r2.json](results/bench/sample200-r2.json), `cells["ALL x length"]`; a single question |
| Volume | 0.0 | null (all abstained) | 1 | [results/bench/sample200-r2.json](results/bench/sample200-r2.json), `cells["ALL x volume"]` |

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
| Yytsi ResNet34-UNet, floorplan-to-3d-walls | MIT code and weights |
| CubiCasa5K official multi-task, hg_furukawa_original | CC BY-NC 4.0 code and weights; internal baseline, not shipped as the final detector |
| CubiCasa5K dataset | **CC BY-NC-SA 4.0**; non-commercial use and share-alike obligations apply |
| RF-DETR-medium “2dplan2strct” | rfdetr Apache-2.0; checkpoint non-commercial research only; evaluated, not used |
| Patnev71 SegFormer-B0 floorplan | Licence listed as “other”; rejected |
| RapidOCR / rapidocr-onnxruntime | Apache-2.0 |

The same [inventory](docs/MODELS.md) lists configured NVIDIA Nemotron, Google Gemini, Anthropic Claude, Featherless Qwen, Runware/Fish Audio, and ElevenLabs API models and provider documentation; configuration alone does not prove a provider ran. API access does not make hosted model weights MIT.

The retained `samples/aalseth_stairs.*` derive from OpeningDesign's [Aalseth Residence](https://github.com/OpeningDesign/Aalseth_Residence), credited to the entire project team under CC BY-SA 4.0. `samples/digital_hub_arc.*` derive from DigitalHub, copyright RWTH Aachen University, E3D Institute of Energy Efficiency and Sustainable Building, under MIT; see the source `LICENSE.md` files under `data/junction-dataset-preview/data/` for original dataset credits.

Only publishable sources belong in the published app. Scenes marked `publishable: false`, including Duplex and Dental Clinic (CC BY-ND) and hitos (GPL data), must stay out of app publication and redistribution ([CLAUDE.md](CLAUDE.md), [pipeline/ifc_scene.py](pipeline/ifc_scene.py), [pipeline/extrude.py](pipeline/extrude.py)). The dataset and local reference pack are not redistributed here. Generated samples must be labelled **“generated for demo”** ([CLAUDE.md](CLAUDE.md)).

Built for the Stoa challenge at Junction 2026 with Stoa's permission to reference their product flow; no Stoa code, logo or drawings are included.

The app's wordmark is **Hologram**.

## Sponsor tools

See [docs/sponsors/README.md](docs/sponsors/README.md) for integration evidence and limitations for Nemotron, Runware, ElevenLabs, Aiven, and Codex, plus the status of other planned tools.
