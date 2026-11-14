"""V-09 done test: accuracy per kind rises or stays equal after the verify step, cost per drawing logged.
usage: .venv/bin/python vision/v09_done.py   (writes results/vision/v09_final.json from verify.json)"""
import json
from pathlib import Path
R = Path(__file__).resolve().parent.parent / "results/vision"
v = json.load(open(R / "verify.json"))
b, a, w = v["before"], v["after_free_pass"], v["after_free_pass_plus_wet_check"]
for k in b:
    assert a[k] >= b[k] and w[k] >= b[k], f"{k} fell"
out = {"set": "241 held-out CubiCasa5K drawings (exact count accuracy)", "before": b, "default_free_pass": a,
       "free_pass_plus_bathroom_crop_check": w, "cost_usd_per_drawing": v["cost_usd_per_drawing"],
       "cost_usd_total_experiments": v["cost_usd_total"],
       "note": "free pass is default (cost 0); bathroom crop check (verify_item, ~0.0006 USD/drawing) lifts showers+bathtubs 0.123 to 0.330 and is opt-in"}
json.dump(out, open(R / "v09_final.json", "w"), indent=1)
print("V-09 OK; no kind falls;", {k: (b[k], w[k]) for k in b}, "cost/drawing", v["cost_usd_per_drawing"])
