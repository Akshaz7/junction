"""Prefetch model checks (cache warm) for a set. usage: verify_run.py calib|held [lo hi]"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).parent.parent))
from PIL import Image
import verify as V, verify_eval as VE
import engine.models.core as _core  # bulk run: verify_item goes straight to Runware (NVIDIA free tier rate-limits); this process only
_orig_chain = _core.chain_for
_core.chain_for = lambda t: sorted(_orig_chain(t), key=lambda s: s["provider"] != "runware") if t == "verify_item" else _orig_chain(t)
which = sys.argv[1]; lo = float(sys.argv[2]) if len(sys.argv) > 2 else 0.45; hi = float(sys.argv[3]) if len(sys.argv) > 3 else 0.85
P = {"dup_gap_frac": 0.006}
jobs = []
if which == "calib":
    for pm, _ in VE.calib_set():
        img = Image.open(ROOT := V.ROOT / "data/cubicasa5k/calib" / (pm["doc_id"][7:] + ".png")).convert("RGB")
        for i in V.zone_items(V.apply_rules(pm, ["dup"], P), lo, hi):
            jobs.append((img, i, "V-09-calib"))
else:
    import build_planmaps as B
    for pm, _ in VE.heldout_set():
        img = Image.open(B.image_path(pm["doc_id"])).convert("RGB")
        for i in V.zone_items(V.apply_rules(pm, ["dup"], P), lo, hi):
            jobs.append((img, i, "V-09-heldout"))
print(len(jobs), "calls to check", flush=True)
# chunk so the cache is saved regularly
for s in range(0, len(jobs), 100):
    V.prefetch(jobs[s:s + 100], workers=14); print(s + 100, flush=True)
