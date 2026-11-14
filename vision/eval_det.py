"""V-07 evaluation: fine-tuned RT-DETR detector vs the baseline on the same held-out count metric (exact count per kind, 241 drawings).

  .venv/bin/python vision/eval_det.py weights/rtdetr_ft [--out results/vision/det_finetuned.json] [--limit N]

Confidence threshold per kind is picked on the 156 calibration drawings (never on held-out), then applied once to held-out.
Baseline numbers are recomputed here from the stored plan maps (same score() as V-09). Inference batch 1, one model loaded.
"""
import argparse, json, sys, time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np, torch
from PIL import Image
import verify as V, verify_eval as VE, build_planmaps as B, infer
KINDS = ["door", "window", "toilet", "sink", "shower", "bathtub"]
SCORED = ["door", "window", "toilet", "sink", "shower_bathtub"]
DET_KINDS = set(KINDS)


class Det:
    def __init__(self, path, size=1024):
        from transformers import RTDetrForObjectDetection, RTDetrImageProcessor
        self.dev = infer.device()
        self.proc = RTDetrImageProcessor.from_pretrained(path, size={"height": size, "width": size}, do_resize=True)
        self.m = RTDetrForObjectDetection.from_pretrained(path).to(self.dev).eval()
        self.id2 = self.m.config.id2label

    def __call__(self, img, floor=0.05):
        W, H = img.size
        with torch.no_grad():
            out = self.m(pixel_values=self.proc(images=img, return_tensors="pt")["pixel_values"].to(self.dev))
        r = self.proc.post_process_object_detection(out, threshold=floor, target_sizes=torch.tensor([[H, W]]))[0]
        return [dict(kind=self.id2[int(l)], label=None, bbox_px=[float(v) for v in b], polygon_px=None, props={}, conf=round(float(s), 3), source="det")
                for s, l, b in zip(r["scores"].cpu(), r["labels"].cpu(), r["boxes"].cpu())]


def items_with(pm, dets, cut):
    keep = [i for i in pm["items"] if i["kind"] not in DET_KINDS]
    new = [d for d in dets if d["conf"] >= cut.get(d["kind"], 0.5)]
    W, H = pm["image"]["w"], pm["image"]["h"]
    new = V.rule_dup(new, W, H, {**V.DEFAULTS, **V.FREE})
    return keep + new


def run_set(det, data, img_of):
    return [(pm, g, det(img_of(pm))) for pm, g in data]


def acc(rows, cut):
    n, ok = Counter(), Counter()
    for pm, g, dets in rows:
        p = VE.pred(items_with(pm, dets, cut))
        for k, v in g.items():
            n[k] += 1; ok[k] += p[k] == v
    return {k: round(ok[k] / n[k], 3) for k in n}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("weights"); ap.add_argument("--out", default="results/vision/det_finetuned.json"); ap.add_argument("--limit", type=int, default=10**9); ap.add_argument("--calib-only", action="store_true")
    a = ap.parse_args()
    det = Det(a.weights)
    cal, held = VE.calib_set()[:a.limit], ([] if a.calib_only else VE.heldout_set()[:a.limit])
    cal_img = lambda pm: Image.open(V.ROOT / "data/cubicasa5k/calib" / (pm["doc_id"][7:] + ".png")).convert("RGB")
    held_img = lambda pm: Image.open(B.image_path(pm["doc_id"])).convert("RGB")
    t = time.time(); rc = run_set(det, cal, cal_img); rh = run_set(det, held, held_img)
    ms = (time.time() - t) / (len(cal) + len(held)) * 1000
    grid = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    cut = {}
    for k in KINDS:
        best = (-1, 0.5)
        for c in grid:
            cc = {kk: c for kk in KINDS}
            kk = "shower_bathtub" if k in ("shower", "bathtub") else k
            s = acc(rc, cc).get(kk, 0)
            if s > best[0]: best = (s, c)
        cut[k] = best[1]
    if a.calib_only:
        res = {"weights": a.weights, "cut_picked_on_calib": cut, "finetuned_calib": acc(rc, cut), "mean_calib": round(sum(acc(rc, cut).values()) / 5, 3)}
        Path(a.out).write_text(json.dumps(res)); print(json.dumps(res)); return
    base_h = VE.score(held, V.ORDER if False else [], None, items_fn=lambda pm: V.free_pass(pm["items"], pm["image"]["w"], pm["image"]["h"]))[0]
    res = {"weights": a.weights, "n_calib": len(cal), "n_heldout": len(held), "cut_picked_on_calib": cut, "ms_per_image_mps": round(ms),
           "baseline_default_heldout": base_h, "finetuned_heldout": acc(rh, cut), "finetuned_calib": acc(rc, cut),
           "baseline_default_calib": VE.score(cal, [], None, items_fn=lambda pm: V.free_pass(pm["items"], pm["image"]["w"], pm["image"]["h"]))[0]}
    Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
