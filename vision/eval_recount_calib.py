"""Recount on the 156 clean calibration drawings (gt.json): plain vision count, and 2x2 overlapping tiles with box dedupe.
  scripts/heavy.sh .venv/bin/python vision/eval_recount_calib.py --mode plain|tiles [--limit N] [--out results/vision/recount_plain.json]
Real models through engine.models.call (budget caps apply). Concurrency <= 4. Results are appended per row (resumable)."""
import argparse, json, os, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RESULTS_DIR", str(ROOT / "results/recount_cache"))
from PIL import Image  # noqa: E402
from engine import recount as R  # noqa: E402

GT = json.loads((ROOT / "data/cubicasa5k/calib/gt.json").read_text())
Q = {"door": "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways without a door leaf do not count.",
     "window": "How many windows are shown on this floor plan?",
     "toilet": "How many toilet bowls (WC seats) are drawn on this floor plan?",
     "sink": "How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan?",
     "shower_bathtub": "How many showers and bathtubs are drawn on this floor plan in total?"}
TMP = Path(tempfile.mkdtemp(prefix="tiles_"))


def tiles(img, ov=0.15):
    W, H = img.size
    tw, th = int(W * (0.5 + ov / 2)), int(H * (0.5 + ov / 2))
    return [(x0, y0, img.crop((x0, y0, x0 + tw, y0 + th))) for x0, y0 in ((0, 0), (W - tw, 0), (0, H - th), (W - tw, H - th))]


def tile_boxes(k, kind):
    img = Image.open(ROOT / f"data/cubicasa5k/calib/{k}.png").convert("RGB")
    out, usd = [], 0.0
    for n, (x0, y0, c) in enumerate(tiles(img)):
        p = TMP / f"{k}_{n}.png"; c.save(p)
        key = R._cache_key("boxes", p, kind); hit = R._cache_get(key)
        if hit is not None:
            bx, u = hit[0], 0.0
        else:
            bx, u, m = R._detect_model(p, kind)
            if bx is None:
                return None, usd
            R._cache_put(key, [bx, m])
        usd += u
        out += [[b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0] for b in bx]
    keep = []
    for b in sorted(out, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if any(R._iou(b, q) >= 0.25 or (q[0] <= cx <= q[2] and q[1] <= cy <= q[3]) for q in keep):
            continue
        keep.append(b)
    return keep, usd


def job(a):
    k, kind, mode = a
    try:
        if mode == "plain":
            n, usd, model = R.recount(Q[kind], ROOT / f"data/cubicasa5k/calib/{k}.png", kind)
        else:
            bx, usd = tile_boxes(k, kind); n, model = (None if bx is None else len(bx)), "tiles"
    except Exception as e:  # noqa: BLE001
        n, usd, model = None, 0.0, "err:" + str(e)[:60]
    return {"doc": k, "kind": kind, "gold": GT[k].get(kind, 0), "value": n, "usd": usd, "model": model}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--mode", default="plain"); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--out"); ap.add_argument("--kinds", default=",".join(Q))
    a = ap.parse_args()
    out = Path(a.out or ROOT / f"results/vision/recount_{a.mode}.json")
    ks = sorted(GT)[: a.limit or None]
    jobs = [(k, kind, a.mode) for k in ks for kind in a.kinds.split(",")]
    rows = []
    with ThreadPoolExecutor(4) as ex:
        for i, r in enumerate(ex.map(job, jobs)):
            rows.append(r)
            if i % 40 == 0:
                print(i, len(jobs), sum(x["usd"] for x in rows), flush=True); out.write_text(json.dumps(rows))
    out.write_text(json.dumps(rows))
    for kind in Q:
        rr = [r for r in rows if r["kind"] == kind and r["value"] is not None]
        if rr:
            print(kind, len(rr), "exact", round(sum(r["value"] == r["gold"] for r in rr) / len(rr), 3))
    print("usd", sum(r["usd"] for r in rows))
main()
