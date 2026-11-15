# Detector experiment (door / window / fixture): OFF by default, not part of the product

**Status:** labelled experiment. The door-confirm hook is wired into `pipeline/pdf_planmap.py` (`pipeline/pdf_detect.py`) but is **off unless `PDF_DETECT=1`**. To run it: `PDF_DETECT=1`, `PDF_DETECT_PY=<python with the modal package and a Modal token>`, optional `PDF_DETECT_RUN=<run>` (e.g. `y11l`, `y11l_clean`, `y11l_mix_a`; default = newest finished run). It never adds or moves geometry; it only adds `props.det_conf` to doors it agrees with, plus a `detector` summary in the plan map.
**Licence:** training and inference use `ultralytics` (AGPL-3.0), which the repo rules ban from the product. Don't merge this into the product without a licence decision. The alternative is retraining the same data on RT-DETR (Apache-2.0).

## What is here
| Path | What |
|---|---|
| `modal/fetch.py` | Downloads the public Junction dataset zip straight onto a Modal volume |
| `modal/swisslab.py`, `modal/build.py` | Swiss PDF+DXF twins become exact YOLO labels: DXF DOOR/WINDOW/FIXTURE layers aligned to the PDF by FFT cross-correlation, rendered at 40 px/m, 1280 px tiles, split by building |
| `modal/crender.py`, `modal/cbuild.py` | Clean set: Swiss Dwellings v3 (CC BY 4.0) floors drawn as plans with exact boxes. Excludes every site/building referenced by the dataset's questions.jsonl (asserted) |
| `modal/train.py`, `modal/train_clean.py` | YOLO11l, 3xH100 DDP, 1280 px, cosine LR, close_mosaic 10, dataset copied to local NVMe and cached in RAM |
| `modal/evaluate.py` | Thresholds per class picked on VAL (max F1); TEST scored once with them |
| `modal/detect.py` | Modal GPU class `junction-det/Detector.detect(pdf_bytes, page, m_per_pt)`. Returns door/window/fixture boxes in page points, with confidence |
| `hook/pdf_detect.py`, `hook/pdf_detect_client.py`, `hook/pdf_planmap-hook.patch` | Plan-map hook, **door confirm only**, off unless `PDF_DETECT=1`. Adds `props.det_conf` to vector doors the detector agrees with. It never adds or moves geometry |
| `hook/modal_gold.py` | Gold on/off check (IFC->SVG twins) |

## Results so far (run `y11l`)
This run was trained on dataset Swiss drawings that the questions reference, so **these are not held-out accuracies**.
- Swiss test split (unseen buildings): P 0.960, R 0.951, mAP50 0.964.
- Gold sheets (IFC-rendered plans): the detector confirms 79-100% of true vector doors, with door precision 0.94-1.00. Windows: 0 true positives, so windows and fixtures are not usable yet.
- With the hook on vs off, plan-map gold metrics and IFC element counts are identical.

No weights, datasets, private sheets or keys are in this folder.
