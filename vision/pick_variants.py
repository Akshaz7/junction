"""Score recount variants (plain / sharp / high) and their combos with the plan map on the same clean-calib subset, 2-fold."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
plan = {(r["doc"], r["kind"]): r["got"] for r in json.loads((ROOT / "results/vision/calib_counts_after.json").read_text())["rows"]}
plain = {(r["doc"], r["kind"]): r["value"] for r in json.loads((ROOT / "results/vision/recount_plain.json").read_text()) if r["value"] is not None}
var = {}
for r in json.loads((ROOT / "results/vision/recount_variants.json").read_text()):
    if r["value"] is not None:
        var.setdefault(r["var"], {})[(r["doc"], r["kind"])] = (r["value"], r["gold"])
for kind in ("door", "window"):
    for v in var:
        keys = sorted(k for k in var[v] if k[1] == kind and k in plain)
        if not keys: continue
        g = lambda k: var[v][k][1]
        M = {"plan": lambda k: plan[k], "plain": lambda k: plain[k], v: lambda k: var[v][k][0],
             f"max(plan,{v})": lambda k: max(plan[k], var[v][k][0]), f"min(plan,{v})": lambda k: min(plan[k], var[v][k][0]),
             f"{v} if plan<{v}": lambda k: var[v][k][0] if plan[k] < var[v][k][0] else plan[k],
             f"{v} if |d|>1 else plan": lambda k: var[v][k][0] if abs(plan[k] - var[v][k][0]) > 1 else plan[k],
             f"median(plan,plain,{v})": lambda k: sorted([plan[k], plain[k], var[v][k][0]])[1]}
        sc = lambda S, f: round(sum(f(k) == g(k) for k in S) / max(1, len(S)), 3)
        A, B = keys[::2], keys[1::2]
        print(kind, v, "n", len(keys))
        for n, f in M.items():
            print(f"   {n:28s} all {sc(keys, f)}  foldA {sc(A, f)}  foldB {sc(B, f)}")
