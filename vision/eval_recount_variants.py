"""Recount prompt/effort variants on a clean calib subset (every 3rd drawing), doors and windows.
  scripts/heavy.sh .venv/bin/python vision/eval_recount_variants.py [--step 3]  -> results/vision/recount_variants.json"""
import argparse, copy, json, os, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import recount as R  # noqa: E402
from engine.models import call, core  # noqa: E402

GT = json.loads((ROOT / "data/cubicasa5k/calib/gt.json").read_text())
SHARP = {"door": "Count a door only when you can see its door leaf: a swing arc with the leaf line drawn in a wall gap. Do not count empty openings without a leaf, "
                 "window symbols, or dimension ticks.",
         "window": "Windows are thin parallel (double or triple) lines or glazed bars set INTO an outer or inner wall. Count each separate window opening once. "
                   "Ignore doors, dimension ticks and wall lines."}
cfg = core.config(); cfg["tasks"]["recount_hi"] = {**copy.deepcopy(cfg["tasks"]["recount"]), "max_tokens": 4000, "extra_body": {"reasoning_effort": "high"}}


def run(a):
    k, kind, var = a
    img = ROOT / f"data/cubicasa5k/calib/{k}.png"
    hint = SHARP[kind] if var == "sharp" else R.HINTS[kind]
    task = "recount_hi" if var == "high" else "recount"
    try:
        r = call(task, [{"role": "user", "content": R.PROMPT % (hint, R.Q_FOR[kind] if hasattr(R, "Q_FOR") else kind)}], images=[img], schema=R.SCHEMA)
        n = (r.json or {}).get("count"); usd = r.cost_usd
    except Exception:  # noqa: BLE001
        n, usd = None, 0.0
    return {"doc": k, "kind": kind, "var": var, "gold": GT[k].get(kind, 0), "value": n, "usd": usd}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--step", type=int, default=3); a = ap.parse_args()
    ks = sorted(GT)[::a.step]
    Qs = {"door": "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways without a door leaf do not count.", "window": "How many windows are shown on this floor plan?"}
    R.Q_FOR = Qs
    jobs = [(k, kind, v) for v in ("sharp", "high") for k in ks for kind in ("door", "window")]
    rows = []
    out = ROOT / "results/vision/recount_variants.json"
    with ThreadPoolExecutor(4) as ex:
        for i, r in enumerate(ex.map(run, jobs)):
            rows.append(r)
            if i % 20 == 0:
                out.write_text(json.dumps(rows)); print(i, len(jobs), flush=True)
    out.write_text(json.dumps(rows))
