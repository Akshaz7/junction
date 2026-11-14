"""Calibration of vision-supplied boxes: count of merged boxes vs gold on the clean CubiCasa calibration drawings (never held-out).
python -m engine.box_calib [--limit N] [--kinds ...] --tag T -> results/<T>.json"""
import argparse, json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from engine.recount import detect, merge_boxes

ROOT = Path(__file__).resolve().parents[1]
PM_KINDS = {"window": ("window",), "door": ("door",), "toilet": ("toilet",), "sink": ("sink",), "shower_bathtub": ("shower", "bathtub")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=40); ap.add_argument("--kinds", default="window,door,sink,shower_bathtub"); ap.add_argument("--tag", default="box_calib")
    a = ap.parse_args()
    gt = json.load(open(ROOT / "data/cubicasa5k/calib/gt.json"))
    jobs = []
    for d in sorted(gt)[: a.limit]:
        pm = json.load(open(ROOT / "data/cubicasa5k/calib_pm" / f"calib__{d}" / "planmap-1.json"))
        for k in a.kinds.split(","):
            pb = [i["bbox_px"] for i in pm["items"] if i["kind"] in PM_KINDS[k] and i.get("conf", 1) >= 0.25]
            jobs.append((d, k, gt[d].get(k, 0), pb))

    def run(j):
        d, k, gold, pb = j
        bx, usd, m = detect(ROOT / "data/cubicasa5k/calib" / f"{d}.png", k)
        return {"doc": d, "kind": k, "gold": gold, "plan": len(pb), "vision_boxes": None if bx is None else len(bx),
                "merged": None if bx is None else len(merge_boxes(pb, bx)), "usd": usd}
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    out = {"rows": rows, "usd": round(sum(r["usd"] for r in rows), 4)}
    for k in a.kinds.split(","):
        rs = [r for r in rows if r["kind"] == k and r["merged"] is not None]
        if rs:
            f = lambda key: round(sum(r[key] == r["gold"] for r in rs) / len(rs), 3)
            out[k] = {"n": len(rs), "plan": f("plan"), "vision_boxes": f("vision_boxes"), "merged": f("merged")}
    (ROOT / "results" / f"{a.tag}.json").write_text(json.dumps(out, indent=1))
    print({k: v for k, v in out.items() if k != "rows"})

main()
