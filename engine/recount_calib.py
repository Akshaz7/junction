"""Calibration of the recount ladder on the 156 clean CubiCasa drawings (data/cubicasa5k/calib, gt.json): never the held-out set.
python -m engine.recount_calib [--limit N] [--kinds window,door,...] -> results/recount_calib.json
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine.recount import recount

ROOT = Path(__file__).resolve().parents[1]
Q = {"window": "How many windows are shown on this floor plan?",
     "door": "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways without a door leaf do not count.",
     "toilet": "How many toilet bowls (WC seats) are drawn on this floor plan?",
     "sink": "How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan?",
     "shower_bathtub": "How many showers and bathtubs are drawn on this floor plan in total?"}
PM_KINDS = {"window": ("window",), "door": ("door",), "toilet": ("toilet",), "sink": ("sink",), "shower_bathtub": ("shower", "bathtub")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--kinds", default=",".join(Q))
    ap.add_argument("--tag", default="recount_calib")
    a = ap.parse_args()
    gt = json.load(open(ROOT / "data/cubicasa5k/calib/gt.json"))
    ids = sorted(gt)[: a.limit or None]
    jobs = []
    for d in ids:
        pm = json.load(open(ROOT / "data/cubicasa5k/calib_pm" / f"calib__{d}" / "planmap-1.json"))
        for k in a.kinds.split(","):
            pc = sum(1 for i in pm["items"] if i["kind"] in PM_KINDS[k] and i.get("conf", 1) >= 0.25)
            jobs.append({"doc": d, "kind": k, "gold": gt[d].get(k, 0), "plan": pc, "img": ROOT / "data/cubicasa5k/calib" / f"{d}.png"})

    def run(j):
        n, usd, model = recount(Q[j["kind"]], j["img"], j["kind"])
        return {**{k: v for k, v in j.items() if k != "img"}, "vision": n, "usd": usd, "model": model}

    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run, jobs))
    out = {"n_docs": len(ids), "rows": rows, "usd": round(sum(r["usd"] for r in rows), 4)}
    for k in a.kinds.split(","):
        rs = [r for r in rows if r["kind"] == k and r["vision"] is not None]
        if rs:
            out[k] = {"n": len(rs), "plan_acc": round(sum(r["plan"] == r["gold"] for r in rs) / len(rs), 3),
                      "vision_acc": round(sum(r["vision"] == r["gold"] for r in rs) / len(rs), 3)}
    (ROOT / "results" / f"{a.tag}.json").write_text(json.dumps(out, indent=1))
    print({k: v for k, v in out.items() if k != "rows"})


if __name__ == "__main__":
    main()
