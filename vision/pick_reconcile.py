"""Pick a plan-map/recount reconcile rule per kind on the clean calib set, with a 2-fold split (pick on one half, score on the other).
  .venv/bin/python vision/pick_reconcile.py [results/vision/recount_plain.json]"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
rec = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "results/vision/recount_plain.json").read_text())
plan = {(r["doc"], r["kind"]): r["got"] for r in json.loads((ROOT / "results/vision/calib_counts_after.json").read_text())["rows"]}
RULES = {"plan": lambda p, v: p, "vision": lambda p, v: v, "min": min, "max": max,
         "vision_if_close": lambda p, v: v if abs(v - p) <= 2 else p, "plan_if_close_else_vision": lambda p, v: p if abs(v - p) <= 1 else v,
         "mean_up": lambda p, v: -(-(p + v) // 2), "mean_down": lambda p, v: (p + v) // 2}
rows = [r for r in rec if r["value"] is not None and (r["doc"], r["kind"]) in plan]
for kind in sorted({r["kind"] for r in rows}):
    rr = sorted([r for r in rows if r["kind"] == kind], key=lambda r: r["doc"])
    sc = lambda S, f: sum(f(plan[(r["doc"], kind)], r["value"]) == r["gold"] for r in S) / max(1, len(S))
    A, B = rr[::2], rr[1::2]
    full = {n: round(sc(rr, f), 3) for n, f in RULES.items()}
    cv = []
    for tr, te in ((A, B), (B, A)):
        best = max(RULES, key=lambda n: sc(tr, RULES[n])); cv.append((best, round(sc(te, RULES[best]), 3)))
    print(kind, len(rr), full, "CV:", cv)
