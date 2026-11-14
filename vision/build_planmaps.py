"""Build plan maps for raster docs.

  uv run python vision/build_planmaps.py --fixtures            # the 4 cubicasa fixtures
  uv run python vision/build_planmaps.py DOC_ID [DOC_ID ...] [--stage seg|merged] [--out DIR]
Writes artifacts/<doc_id>/planmap-seg.json (V-01, seg only) and planmap-1.json (V-02, merged) and
results/vision/timing.json (ms per image, per stage).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import infer  # noqa: E402
import planmap as P  # noqa: E402
import rooms_scale as RS  # noqa: E402

ROOT = infer.ROOT


def image_path(doc_id):
    doc = json.loads((ROOT / f"artifacts/{doc_id}/doc.json").read_text())
    rel = doc["files"]["png"]
    for base in (ROOT / "data/junction-dataset-preview", ROOT):
        p = base / rel
        if p.exists():
            return p
    p = ROOT / "data/junction-dataset-preview/data" / rel.split("data/", 1)[-1]
    return p


def run(doc_ids, stages=("seg", "merged"), out_root=None):
    out_root = Path(out_root) if out_root else ROOT / "artifacts"
    imgs = {d: Image.open(image_path(d)).convert("RGB") for d in doc_ids}
    seg_res, timing = {}, {}
    if "seg" in stages or "merged" in stages:
        seg = infer.SegModel(P.PARAMS["seg_size"])
        seg.classes(next(iter(imgs.values())))  # warm-up
        for d, img in imgs.items():
            t = time.perf_counter()
            probs = seg.probs(img)
            items = P.seg_items(probs.argmax(0).astype(np.uint8), probs, *img.size)
            ms = (time.perf_counter() - t) * 1000
            seg_res[d] = (items, ms)
        seg.release()
    det_res = {}
    if "merged" in stages:
        off = infer.OfficialModel(P.PARAMS["det_size"])
        off.maps(next(iter(imgs.values())))
        for d, img in imgs.items():
            t = time.perf_counter()
            rooms, icons = off.maps(img)
            items = P.det_items(rooms, icons, off.icon_conf, *img.size, P.PARAMS["det_size"])
            items += P.det_walls(rooms, off.room_conf, *img.size)  # kept only when the seg model finds no walls
            det_res[d] = (items, (time.perf_counter() - t) * 1000, rooms, off.room_conf.copy())
        off.release()
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
        ocr_res = {}
        for d, img in imgs.items():
            t = time.perf_counter()
            ocr_res[d] = (RS.run_ocr(ocr, np.asarray(img)), (time.perf_counter() - t) * 1000)
    problems = {}
    for d, img in imgs.items():
        W, H = img.size
        dd = out_root / d
        dd.mkdir(parents=True, exist_ok=True)
        s_items, s_ms = seg_res[d]
        models = {"seg": infer.SegModel.NAME}
        pm_seg = P.assemble(d, W, H, s_items, models, s_ms)
        (dd / "planmap-seg.json").write_text(json.dumps(pm_seg))
        timing[d] = {"image": [W, H], "seg_ms": round(s_ms, 1)}
        problems[d] = P.validate(pm_seg)
        if "merged" in stages:
            d_items, d_ms, rooms_map, room_conf = det_res[d]
            texts, ocr_ms = ocr_res[d]
            t = time.perf_counter()
            room_list, _ = RS.room_items(rooms_map, room_conf, W, H, P.PARAMS["det_size"])
            RS.label_rooms(room_list, texts)
            scale = RS.estimate_scale(room_list, texts, [i for i in d_items if i["kind"] == "door"])
            RS.apply_scale(room_list, scale)
            text_items = [dict(kind="text", label=x["text"], bbox_px=x["bbox"], polygon_px=None, props={}, conf=round(x["conf"], 3), source="ocr") for x in texts]
            rooms_ms = (time.perf_counter() - t) * 1000
            seg_walls = [i for i in s_items if i["kind"] == "wall"]
            wall_frac = sum((i["bbox_px"][2] - i["bbox_px"][0]) * (i["bbox_px"][3] - i["bbox_px"][1]) for i in seg_walls) / (W * H)
            use_det_walls = wall_frac < P.PARAMS["seg_wall_min_frac"]  # UNet fails on scans/hand-drawn plans
            keep = ([] if use_det_walls else seg_walls) + [i for i in d_items if i["kind"] != "wall" or use_det_walls]
            timing[d]["walls_from"] = "det" if use_det_walls else "seg"
            pm = P.assemble(d, W, H, keep + room_list + text_items, {**models, "det": infer.OfficialModel.NAME, "ocr": "rapidocr-onnxruntime"},
                            s_ms + d_ms + ocr_ms + rooms_ms, scale=scale)
            (dd / "planmap-1.json").write_text(json.dumps(pm))
            timing[d]["det_ms"] = round(d_ms, 1)
            timing[d]["ocr_ms"] = round(ocr_ms, 1)
            timing[d]["scale"] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in scale.items()}
            problems[d] += P.validate(pm)
        else:
            (dd / "planmap-1.json").write_text(json.dumps(pm_seg))
    return timing, problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("docs", nargs="*")
    ap.add_argument("--fixtures", action="store_true")
    ap.add_argument("--stage", default="merged", choices=["seg", "merged"])
    ap.add_argument("--out")
    a = ap.parse_args()
    docs = a.docs
    if a.fixtures:
        docs = [f for f in json.loads((ROOT / "tests/fixtures.json").read_text()) if f.startswith("cubicasa5k__")]
    timing, problems = run(docs, ("seg",) if a.stage == "seg" else ("seg", "merged"), a.out)
    (ROOT / "results/vision").mkdir(parents=True, exist_ok=True)
    tp = ROOT / "results/vision/timing.json"
    if a.fixtures:
        tp.write_text(json.dumps({"device": str(infer.device()), "params": P.PARAMS, "per_doc": timing,
                                  "mean_ms": {k: round(float(np.mean([v[k] for v in timing.values() if k in v])), 1) for k in ("seg_ms", "det_ms", "ocr_ms")}}, indent=1))
    for d in docs:
        print(d, timing[d], "VALID" if not problems[d] else problems[d])
    sys.exit(1 if any(problems.values()) else 0)
