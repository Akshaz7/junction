"""Clean-set count eval: 156 CubiCasa5K calibration drawings (all inside the 213 clean ids, none held out) with SVG-derived gold
(data/cubicasa5k/calib/gt.json). Runs the real engine count solver (planmap route, MODELS_FAKE=1, no vision recount) on plan maps
rebuilt with the build-time free pass, using the same question templates as the benchmark.
  .venv/bin/python vision/eval_calib.py [--pm-dir data/cubicasa5k/calib_pm] [--no-post] [--out results/vision/calib_counts.json]
Caveat: gold is from the CubiCasa SVG annotations, not from the dataset's question definitions; the official CubiCasa model was
trained on the 'train' split, so some calib drawings may be in its training data."""
import argparse, json, os, shutil, sys, tempfile
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "vision"))
os.environ["MODELS_FAKE"] = "1"
GT = json.loads((ROOT / "data/cubicasa5k/calib/gt.json").read_text())
Q = {
    "door": "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways without a door leaf do not count.",
    "window": "How many windows are shown on this floor plan?",
    "toilet": "How many toilet bowls (WC seats) are drawn on this floor plan?",
    "sink": "How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan?",
    "shower_bathtub": "How many showers and bathtubs are drawn on this floor plan in total?",
    "room:bedroom": "How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?",
    "room:kitchen": "How many kitchens (including kitchenettes, open kitchens and utility kitchens) are on this floor plan?",
    "room:bathroom": "How many bathrooms or washrooms (e.g. KH, KPH, PH, PESUH, SH) are on this floor plan, not counting separate WC rooms?",
}


def stage(pm_dir, post):
    import verify as VF
    tmp = Path(tempfile.mkdtemp(prefix="calib_art_"))
    for k in GT:
        src = Path(pm_dir) / ("calib__" + k) / "planmap-1.json"
        if not src.exists():
            continue
        d = tmp / ("calib__" + k); d.mkdir()
        pm = json.loads(src.read_text())
        if post:
            pm["items"] = VF.free_pass(pm["items"], pm["image"]["w"], pm["image"]["h"])
        (d / "planmap-1.json").write_text(json.dumps(pm))
    return tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pm-dir", default=str(ROOT / "data/cubicasa5k/calib_pm")); ap.add_argument("--no-post", action="store_true"); ap.add_argument("--out")
    a = ap.parse_args()
    from engine.solvers import solve
    from engine.router import parse
    tmp = stage(a.pm_dir, not a.no_post)
    stats = defaultdict(lambda: defaultdict(int)); rows = []
    for d in sorted(tmp.iterdir()):
        k = d.name[7:]
        for key, q in Q.items():
            try:
                v = solve(q, d.name, parsed=parse(q), root=tmp)["answer"].get("value")
            except Exception as e:  # noqa: BLE001
                v = None
            g = GT[k].get(key, 0)
            s = stats[key]; s["n"] += 1
            if v is None:
                s["none"] += 1; v = 0
            s["exact"] += v == g; s["over"] += v > g; s["under"] += v < g; s["abs_err"] += abs(v - g)
            rows.append({"doc": k, "kind": key, "gold": g, "got": v})
    shutil.rmtree(tmp, ignore_errors=True)
    out = {}
    for key, s in stats.items():
        out[key] = dict(s); out[key]["acc"] = round(s["exact"] / s["n"], 3)
        print(f"{key:15s} n={s['n']} exact={s['exact']} ({out[key]['acc']}) over={s['over']} under={s['under']} abs_err={s['abs_err']}")
    print("overall", round(sum(s["exact"] for s in stats.values()) / sum(s["n"] for s in stats.values()), 3))
    if a.out:
        (ROOT / a.out).write_text(json.dumps({"summary": out, "rows": rows}, indent=1))


main()
