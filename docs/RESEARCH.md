# Research

We used research papers, dataset records, standards, documentation and engineering articles to guide drawing parsing, quantity checks and evidence reporting. The table records what we used, tested or rejected. Dates describe our first reference to a source, not its publication date: ordinary dates come from repository history; “local record” dates describe untracked experiments; “source check” dates record the first documented public-source check.

The verification sections report source measurements and focused consistency checks. They do not establish general answer accuracy. Dataset, model and service rights remain separate from the repository's MIT licence; see [Models and licences](MODELS.md).

## Source summary

| Source | What it is | How we used it | First referenced | Verdict |
| --- | --- | --- | --- | --- |
| D1 [CubiCasa5K](https://github.com/CubiCasa/CubiCasa5k) | Annotated raster plans | Drawing evaluation and eligible training examples | 2026-11-14 | Used; restricted training pool |
| D2 [FloorPlanCAD mirror](https://huggingface.co/datasets/Voxel51/FloorPlanCAD) | Vector CAD dataset | Detector training boxes | 2026-11-14 | Used; licence conflict unresolved |
| D3 [Swiss Dwellings v3](https://zenodo.org/records/7788422) | Apartment and room geometries | Drawing questions, paired examples and CAD inspection | 2026-11-14 | Used; CC BY 4.0 |
| D4 [ResBIM](https://github.com/RogerLiang0725/ResBIM) | Residential BIM dataset | IFC inputs | 2026-11-14 | Used; per-file credits |
| D5 [KIT IFC examples](https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples) | Sample IFC buildings | IFC ingestion and demo building family | 2026-11-14 | Used |
| D6 [buildingSMART community samples](https://github.com/buildingsmart-community/Community-Sample-Test-Files) | IFC test models | Multi-storey, services and rebar checks | 2026-11-14 | Used; per-file terms |
| D7 [OpeningDesign](https://github.com/OpeningDesign) | Open architecture projects | CAD and IFC inputs; unsupported-convention checks | 2026-11-14 | Used; per-project terms |
| D8 [IFC-Bench](https://huggingface.co/datasets/sylvainhellin/ifc-bench) | IFC models and questions | Structured-model evaluation | 2026-11-14 | Used; publication exclusions apply |
| D9 [WAFFLE](https://github.com/TAU-VAILab/WAFFLE) | Floor-plan collection | Selecting source drawings | 2026-11-14 | Used for selection |
| D10 [Wikimedia Commons](https://commons.wikimedia.org/) | Media archive | Drawing inputs selected through WAFFLE | 2026-11-14 | Used; per-item rights |
| D11 [Europeana](https://www.europeana.eu/) | Cultural archive catalogue | Historical drawing inputs | 2026-11-14 | Used; per-item rights |
| D12 [Finna](https://finna.fi/) | Finnish archive catalogue | Archive drawing inputs | 2026-11-14 | Used; selected files CC BY 4.0 |
| D13 [HABS/HAER/HALS](https://www.loc.gov/pictures/collection/hh/) | Survey drawing archive | Historical drawing inputs | 2026-11-14 | Used; retain item rights and credits |
| D14 [CVC-FP](https://dag.cvc.uab.es/dataset/cvc-fp-database-for-structural-floor-plan-analysis/) | Scanned plans and structural annotations | Held-out stress testing | 2026-11-15, local record | Evaluation only |
| D15 [ResPlan](https://github.com/m-agour/ResPlan) | Vector residential plans | Held-out stress testing | 2026-11-15, local record | Evaluation only; rendering limitations |
| D16 [PID2Graph](https://zenodo.org/records/14803338) | Piping and instrumentation diagrams | Held-out cross-domain stress testing | 2026-11-15, local record | Evaluation only |
| D17 [Additional IFC samples](https://github.com/buildingsmart-community/Community-Sample-Test-Files) | Building and services models | Format and hierarchy stress testing | 2026-11-15, local record | Local evaluation; restricted files unpublished |
| V1 [RT-DETR r50vd](https://huggingface.co/PekingU/rtdetr_r50vd) | Object detector | Fine-tuning for openings and sanitary fixtures | 2026-11-14 | Tested; fine-tune disabled |
| V2 [Floorplan-to-3D walls](https://huggingface.co/Yytsi/floorplan-to-3d-walls) | ResNet34-UNet segmenter | Wall-segmentation base | 2026-11-14 | Tested; fine-tune disabled |
| V3 [2dplan2strct](https://huggingface.co/OsamaMo/2dplan2strct) | RF-DETR checkpoint | Alternative detector evaluation | 2026-11-14 | Not selected |
| V4 [SegFormer-B0 floorplan](https://huggingface.co/Patnev71/segformer-b0-finetuned-floorplan) | Room segmenter | Candidate screening | 2026-11-14 | Rejected; weight rights unclear |
| V5 [RapidOCR](https://github.com/RapidAI/RapidOCR) | OCR toolkit | Local text reading | 2026-11-14 | Used; checkpoint provenance incomplete |
| V6 [COCO](https://cocodataset.org/#termsofuse) | Upstream image dataset | RT-DETR base pretraining provenance | 2026-11-14 | Upstream only |
| V7 [ImageNet](https://www.image-net.org/download.php) | Upstream image dataset | ResNet34 encoder provenance | 2026-11-14 | Upstream only |
| T1 [IfcOpenShell / IfcConvert](https://github.com/IfcOpenShell/IfcOpenShell) | IFC library and converter | Reading models and producing scene geometry | 2026-11-14 | Used; LGPL notices apply |
| T2 [three.js](https://github.com/mrdoob/three.js) | 3D rendering library | Browser model view | 2026-11-14 | Used |
| T3 [pypdfium2](https://github.com/pypdfium2-team/pypdfium2), [pdfminer.six](https://github.com/pdfminer/pdfminer.six) | PDF libraries | Rendering pages and extracting text | 2026-11-14 | Used |
| T4 [Ultralytics](https://www.ultralytics.com/license), [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) | Alternative parsing libraries | Dependency screening | 2026-11-14 | Rejected under project licence policy |
| R1 [Decree 241/2017](https://www.finlex.fi/fi/lainsaadanto/2017/241) | Finnish accessibility regulation | Source for accessibility checks | 2026-11-14 | Rule source |
| R2 [Decree 848/2017](https://www.finlex.fi/fi/lainsaadanto/2017/848) | Finnish fire-safety regulation | Source for exit checks | 2026-11-14 | Rule source |
| R3 [Decree 1007/2017](https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2017/1007) | Finnish safety-in-use regulation | Source for stair and safety checks | 2026-11-14 | Rule source |
| R4 [EU TRIS 2017/0221/FIN](https://technical-regulation-information-system.ec.europa.eu/en/notification/18529/text/F/EN) | Notified English regulatory text | English wording for fire-safety checks | 2026-11-14 | Translation reference |
| R5 [Ministry safety-in-use translation](https://ym.fi/documents/1410903/0/YMa+k%C3%A4ytt%C3%B6turvallisuus+1007_2017+EN.pdf/ee85f7a4-0ef7-d489-a450-70a2469a2361?t=1668155648754) | Unofficial English translation | English wording for safety-in-use checks | 2026-11-14 | Translation reference; unofficial |
| P1 [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [terms](https://ai.google.dev/gemini-api/terms) | Provider documentation | Drawing reading, item checks and voice configuration | 2026-11-14 | Used; vendor documentation |
| P2 [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), [terms](https://www.anthropic.com/legal/commercial-terms) | Provider documentation | Written answers and reasoning configuration | 2026-11-14 | Used; vendor documentation |
| P3 [Runware catalogue](https://runware.ai/docs/models/), [terms](https://runware.ai/terms) | Hosted-model documentation | Bulk requests and provider fallbacks | 2026-11-14 | Used; vendor documentation |
| P4 [Nemotron Lightning](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/modelcard), [Super VL](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b/modelcard), [3 Super](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16) | Model cards | Routing, advice and checking candidates | 2026-11-14 | Used; model-specific terms |
| P5 [Qwen3-VL](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct), [Qwen3-Next](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct) | Model cards | Hosted vision fallback and price candidate | 2026-11-14 | Fallback / candidate |
| P6 [ElevenLabs terms](https://elevenlabs.io/terms-of-use), [publication guidance](https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform) | Speech-service documentation | Answer playback | 2026-11-14 | Used; service terms apply |
| P7 [Fish Audio terms](https://fish.audio/terms/) | Speech-service documentation | Speech fallback through Runware | 2026-11-14 | Fallback; weight rights not established |
| P8 Verda-hosted Nemotron VL | Dedicated model hosting | Last-resort vision fallback | 2026-11-14 | Retained last; reliability limitations |
| L1 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) | Dataset licence | Conservative release treatment of derived checkpoints | 2026-11-14 | Attribution, noncommercial and share-alike terms retained |
| M1 [Held-out separation](../train/build_v05.py) | Evaluation method | Excluding question-referenced drawings from training | 2026-11-14 | Applied; upstream overlap remains uncertain |
| M2 [Quick regression evaluation](../engine/bench.py) | Evaluation method | Exact counts, stated area tolerance and explicit abstentions | 2026-11-14 | Applied; development evidence |
| A1 [CubiCasa5K paper](https://arxiv.org/abs/1904.01920) | Floor-plan analysis research | Distinguishing rooms, icons and openings | 2026-11-15, source check | Supports task formulation |
| A2 [Raster-to-Vector, ICCV 2017](https://jiajunwu.com/papers/im2cad_iccv.pdf) | Floor-plan vectorization research | Structured wall, opening and icon primitives | 2026-11-15, source check | Supports structural approach |
| A3 IPMS landing page | Standards organisation homepage | Assessed as support for dwelling-area rules | 2026-11-15, source check | Does not support those rules; not cited for them |
| A4 [DIN 277 area-type summary](https://normraum.de/wissen/en/din-277-flaechenarten) | Secondary standards explainer | Terminology and comparison with our indoor-only scope | 2026-11-15, source check | Partial; not normative text |
| A5 [Swiss Dwellings record](https://zenodo.org/records/7788422) | Publisher's dataset deposit | Apartment/room structure and dataset rights | 2026-11-15, source check | Supports dataset description |
| A6 [buildingSMART IfcStair source](https://github.com/buildingSMART/IFC4.3.x-development/blob/master/docs/schemas/shared/IfcSharedBldgElements/Entities/IfcStair.md) | Official schema documentation | Assembly-versus-part counting | 2026-11-15, source check | Supports relationship-based counting |
| A7 [IfcOpenShell element utilities](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html) | API documentation | Reading aggregate parents and descendants | 2026-11-15, source check | Partial; decomposition is broader than aggregation |
| A8 [ForensicBIM quantity check](https://forensicbim.business/help/quantity-check/) | Vendor engineering article; non-peer-reviewed | Comparing declared quantities with geometry | 2026-11-15, source check | Supports cross-checking; our policy differs |
| A9 [Door swing-arc detection](https://indoor-mapping-wayfinding.com/automated-floor-plan-parsing-vectorization/wall-door-detection-algorithms/detecting-doors-from-swing-arc-blocks/) | Vendor engineering article; non-peer-reviewed | Avoiding arc-only doors and grouping door symbols | 2026-11-15, source check | Supports engineering rationale; no accuracy claims adopted |
| A10 [scikit-learn common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) | Official methodology documentation | Separating fitting from final evaluation | 2026-11-15, source check | Supports leakage prevention |
| A11 [CubiCasa5K official repository](https://github.com/CubiCasa/CubiCasa5k) | Dataset implementation and split files | Preserving training, validation and test separation | 2026-11-15, source check | Supports split discipline |

## Datasets and publication scope

We use [CubiCasa5K](https://github.com/CubiCasa/CubiCasa5k) for raster analysis and [FloorPlanCAD](https://huggingface.co/datasets/Voxel51/FloorPlanCAD) for detector boxes. We exclude drawings referenced by question files from our training pool. FloorPlanCAD's card narrative and licence metadata conflict, so we treat those inputs as noncommercial and do not claim commercial clearance. The [model inventory](MODELS.md) records the separate data, code and checkpoint terms.

The stable citation for Swiss Dwellings is its [Zenodo v3 record](https://zenodo.org/records/7788422). It describes apartment models, room geometry and typology, and provides the dataset licence. We use those structures to inspect apartment membership and room areas. The source record describes the dataset; it does not prove that our derived CAD reader is correct.

ResBIM, KIT examples, buildingSMART samples, OpeningDesign and IFC-Bench supply different IFC and CAD representations. We retain per-file credits and publication restrictions. Converted Duplex and Dental Clinic files with no-derivatives terms, and the GPL-licensed HITOS data, are excluded from publication under our project policy. Inputs with no established licence stay local. See [Models and licences](MODELS.md).

WAFFLE guides file selection; the selected archive item's rights still control. We retain the original rights statements for Commons, Europeana, Finna and Library of Congress drawings. CVC-FP, ResPlan and PID2Graph were used for held-out stress testing. Our simplified ResPlan rendering omitted opening symbols, and CVC-FP room definitions were ambiguous, which limits conclusions from those experiments. We do not treat cross-domain stress tests as evidence of general floor-plan accuracy.

## Vision, tools and service choices

We tested RT-DETR and a ResNet34-UNet base, but disabled our fine-tuned detector and segmenter after evaluation. The alternative RF-DETR checkpoint was not selected; the SegFormer candidate lacked established permissive weight rights. RapidOCR supplies local text reading, although the exact bundled OCR checkpoint provenance remains incomplete. COCO and ImageNet appear only as upstream pretraining provenance; we do not redistribute their images. Exact model identifiers and rights are in [Models and licences](MODELS.md).

We use IfcOpenShell and IfcConvert for model reading and conversion, three.js for the browser scene, and pypdfium2/pdfminer.six for PDF rendering and text extraction. We rejected Ultralytics and PyMuPDF under the project's dependency policy. IfcOpenShell's LGPL terms remain separate from the repository's MIT licence.

Provider documentation informed task routing, fallbacks, price configuration and output-rights handling. The Gemini, Claude, Runware, NVIDIA, Qwen, ElevenLabs, Fish Audio and hosting pages are vendor materials, non-peer-reviewed. A configured candidate does not prove that it ran. We keep hosted-service rights separate from model-weight rights, and route model requests through the shared [model layer](../engine/models/core.py). We retain Verda-hosted vision last in the fallback chain because of recorded latency and structured-output limitations; no general provider performance claim follows.

## Regulations and area terminology

We use the Finnish texts of [241/2017](https://www.finlex.fi/fi/lainsaadanto/2017/241), [848/2017](https://www.finlex.fi/fi/lainsaadanto/2017/848) and [1007/2017](https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2017/1007) as references for selected advisor checks. English wording comes from the notified [EU TRIS text](https://technical-regulation-information-system.ec.europa.eu/en/notification/18529/text/F/EN), the ministry's unofficial translation, or our explicitly marked unofficial translation. These references explain our rule sources; a model with missing dimensions cannot establish compliance. The checked sources and quotations are retained in the [rule library](../engine/rules/).

The [DIN 277 explainer](https://normraum.de/wissen/en/din-277-flaechenarten) is a secondary source, not the standard itself or peer-reviewed evidence. It helps distinguish clear room measurements and enclosure categories. Our requested indoor-only room sum is an explicit application scope: DIN does not universally exclude outdoor areas. The IPMS homepage did not establish dwelling-area rules, so we do not use it as their authority or claim IPMS compliance.

## Accuracy topics

### Fixtures on vector plans

**Sources.** The [CubiCasa5K paper](https://arxiv.org/abs/1904.01920) treats icons separately from rooms and openings. [Raster-to-Vector](https://jiajunwu.com/papers/im2cad_iccv.pdf) assembles structured primitives from junction predictions. We adopted the idea of structural constraints, without reproducing either neural architecture or the latter paper's integer program. The [swing-arc article](https://indoor-mapping-wayfinding.com/automated-floor-plan-parsing-vectorization/wall-door-detection-algorithms/detecting-doors-from-swing-arc-blocks/) supplies engineering rationale and is non-peer-reviewed vendor material.

**Implemented.** We group existing CAD vectors using closed frames, containment, bowl contours, drain circles and elongated rounded contours. Kitchen hob rings alone do not identify a sink; uncertain crossed boxes remain uncertain. Four anatomy thresholds are midpoints between observed development distributions, and recognition confidence is uncalibrated. We do not require a particular raw vertex count. See [implementation notes](../results/final/ACC-VECTOR/research.md) and [recorded constants](../results/final/ACC-VECTOR/constants.json).

**Verified on our data.** Inspection of 12 eligible Swiss drawings recorded 203 enclosing fixture rectangles, including 81 bowl curves and 30 rounded tub curves. Those are source-geometry observations, not detector accuracy. Their distributions and provenance are in [constants.json](../results/final/ACC-VECTOR/constants.json) and [measurements.json](../results/final/ACC-VECTOR/measurements.json). The reserved Swiss check still produced abstentions where an uncertain symbol remained; an unrelated CAD file exercised safe fallback. Positive fixture transfer to an independent CAD origin remains unverified. See [blind checks](../results/final/ACC-VECTOR/blind.json).

### Apartment membership and net area

**Sources.** The [Swiss Dwellings deposit](https://zenodo.org/records/7788422) documents apartment and room structure. The [DIN area-type summary](https://normraum.de/wissen/en/din-277-flaechenarten) informs terminology, with the secondary-source limitation described above. Neither establishes our indoor-only sum as a universal dwelling-area standard.

**Implemented.** We resolve apartment labels through same-page containment, assign room outlines to units, and use even-odd topology for nested voids. We retain written and measured areas, compare them at the written precision, and keep balconies, loggias and terraces separate when the question requests indoor area. Unknown room use lowers confidence. The geometry rules have no fitted size or coordinate thresholds. See [implementation notes](../results/final/ACC-UNITS/research.md).

**Verified on our data.** The 12 inspected drawings contained 36 unit outlines, 415 room outlines and one unlabelled nested void. Unit tags included 32 occurrences of `Whg.` and two of `App.`; outdoor labels included 19 `Balkon`, three `Balcon` and 13 `Loggia`. Other supported vocabulary is explicitly marked unobserved. These counts are recorded in [constants.json](../results/final/ACC-UNITS/constants.json). German, French and Italian examples support the documented Swiss convention; other CAD origins exercise fallback and do not establish positive apartment recognition outside it. See [source checks and limitations](../results/final/ACC-UNITS/research.md).

### IFC count hygiene

**Sources.** The official [IfcStair schema source](https://github.com/buildingSMART/IFC4.3.x-development/blob/master/docs/schemas/shared/IfcSharedBldgElements/Entities/IfcStair.md) allows an assembly of flights and landings or an undecomposed stair. [IfcOpenShell utilities](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html) distinguish aggregate-parent lookup from broader decomposition. We used the official source repository because the requested IFC4 HTML page blocked access; we do not describe that page as independently verified.

**Implemented.** We follow actual aggregate-parent relationships and suppress related components of the same product family, while preserving independent flights and distinct products such as doors in walls. We retain cited element IDs and report unavailable classification explicitly. Broad decomposition alone is insufficient because it also includes openings and fills. See [source checks](../results/final/ACC-IFC/research.md).

**Verified on our data.** The recorded source validation walks relationships in 12 real files and checks that counts and cited IDs agree with that walk; missing classifications remain unavailable. Schema regressions cover IFC2x3, IFC4 and IFC4x3, including nested stairs and independent flights. This validates relationship handling on those files, without establishing completeness of every model's product classification. See [source validation summary](../results/final/ACC-IFC/summary.json) and [blind-file validation](../results/final/ACC-IFC/real-blind.json).

### IFC room areas

**Sources.** The [ForensicBIM quantity-check article](https://forensicbim.business/help/quantity-check/) motivates comparing declared quantities with independently measured geometry and accounting for units and measurement conventions. It is a non-peer-reviewed vendor article. Its area tolerance is 5%; our 2% comparison policy is an application choice, not a requirement from that article or buildingSMART. The [DIN explainer](https://normraum.de/wissen/en/din-277-flaechenarten) provides terminology only.

**Implemented.** We convert declared area units independently of length units, measure projected mesh unions, preserve declared and measured quantities, and expose their difference relative to the measured footprint. We reuse converted scene geometry where available. Missing geometry produces an explicit partial estimate. Gross footprints are not presented as verified usable net areas. See [policies and observed distributions](../results/final/ACC-IFC/constants.json).

**Verified on our data.** Of 244 spaces in four room-bearing development files, 236 had measurable footprints and eight lacked usable geometry. All 126 simple-profile checks matched an independent shoelace-area calculation. That independent reference covers simple vertical extrusions; it does not supply ground truth for every mesh. See [source validation summary](../results/final/ACC-IFC/summary.json).

The AC20 source audit contains 82 spaces: measured footprints total 2,266.66 m² and match the declared gross quantities, while declared net quantities total approximately 1,939.384 m². We therefore preserve the distinct conventions in answers. The measurements and interpretation are in [demo-source-audit.json](../results/final/ACC-IFC/round2/demo-source-audit.json). A later scene-reuse check compared 186 footprints with source geometry without mismatches; source agreement is a consistency check, not independent ground truth. See [scene validation summary](../results/final/ACC-IFC/round2/summary.json).

### Door and window deduplication

**Sources.** The [swing-arc article](https://indoor-mapping-wayfinding.com/automated-floor-plan-parsing-vectorization/wall-door-detection-algorithms/detecting-doors-from-swing-arc-blocks/) warns that arcs also occur in furniture and fillets, and discusses grouped double doors. This is non-peer-reviewed engineering guidance. [IfcOpenShell's aggregate-parent API](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html) supports checking explicit IFC assembly relationships. Neither source justifies merging nearby objects indiscriminately.

**Implemented.** CAD opening counts use closed source frames or explicit opening blocks, never swing arcs alone. We preserve distinct coincident source entities. IFC component exclusion follows actual same-family parent links. Raster duplicate merging retains its existing settings because the tested alternatives did not justify a change. See [vector notes](../results/final/ACC-VECTOR/research.md), [IFC notes](../results/final/ACC-IFC/research.md) and [raster experiment notes](../results/final/SCANACC2/research.md).

**Verified on our data.** Focused CAD checks cover arc-only fillets, a double-door block containing separate leaf frames, and coincident but distinct entities. The reserved Swiss source retained 28 door objects and 16 window objects through fixture classification; these are object-inventory checks. See [reserved-file record](../results/final/ACC-VECTOR/blind.json). Raster development experiments retained the existing 0.7 confidence cut, 1024-pixel input, 0.003 duplicate-gap fraction and 0.3 duplicate IoU; the IoU was not swept independently. Rotation/flip averaging, larger-gap merging, resizing and nested suppression were not adopted. See [recorded settings and limitations](../results/final/SCANACC2/constants.json). Raster opening fragmentation remains unresolved.

### Value-field plumbing and reporting

**Sources.** [scikit-learn's leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) and the [official CubiCasa5K repository](https://github.com/CubiCasa/CubiCasa5k) support separating fitting, validation and final testing. The [quantity-check article](https://forensicbim.business/help/quantity-check/) supports disclosing how values were obtained and comparing compatible quantities; it supplies no validation of our implementation.

**Implemented.** We preserve numeric values through answer formatting, recover omitted values from cited structured evidence where supported, and validate that returned measurements match the requested quantity. Apartment resolution uses exact labels and same-page containment. We retain declared-versus-measured provenance and reserve blind inputs before final inspection. No fitted numeric constants were introduced for value handling. See [implementation notes](../results/final/ACC-VALUE/research.md) and [constants.json](../results/final/ACC-VALUE/constants.json).

**Verified on our data.** Across three eligible CAD files, 11 unit outlines had empty labels, while 11 room labels and 11 text labels identified their apartments. That observation supports label-anchor resolution; it does not justify guessing apartment identities. See [label provenance](../results/final/ACC-VALUE/constants.json). Twelve focused consistency probes across four real documents passed checks for public value reporting, measurement-mismatch retry and recovery of missing reader values. The injected reader answers were **generated for demo**. These probes use deterministic providers and validate source consistency, not independent answer accuracy or live-model reliability. See [final_checks.json](../results/final/ACC-VALUE/final_checks.json).

## Evaluation limits

We preserve upstream splits and exclude question-referenced drawings from our own training and fitting. A pretrained model may already have seen a project-held-out drawing; where upstream membership is unknown, we record that uncertainty. Our additional reserved-file checks supplement the existing splits and do not create a new official dataset split. [CubiCasa5K's repository](https://github.com/CubiCasa/CubiCasa5k) and [scikit-learn's documentation](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) support those precautions.

Development regression checks, geometry agreement, synthetic cases and answer accuracy measure different things. We report missing data and abstentions explicitly. A source quantity agreeing with a mesh does not independently establish the correct physical measurement convention, and an uncalibrated confidence score is not an accuracy probability. Our source records identify the observations, application policies and unresolved limits behind each implemented check.
