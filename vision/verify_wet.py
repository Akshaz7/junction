"""V-09 step 3: shower+bathtub count from bathroom-room crops (model check). usage: verify_wet.py calib|held [N]"""
import sys, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).parent.parent))
from PIL import Image
import engine.models.core as _core
_o = _core.chain_for
_core.chain_for = lambda t: sorted(_o(t), key=lambda s: s["provider"] != "runware") if t == "verify_item" else _o(t)
import verify as V, verify_eval as VE, build_planmaps as B
which = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
data = VE.calib_set() if which == "calib" else VE.heldout_set()
data = [a for a in data if "shower_bathtub" in a[1]][:N]
def img_of(pm):
    return Image.open(V.ROOT / "data/cubicasa5k/calib" / (pm["doc_id"][7:] + ".png") if which == "calib" else B.image_path(pm["doc_id"])).convert("RGB")
def work(a):
    pm, g = a
    img = img_of(pm)
    rooms = V.wet_rooms(pm["items"])
    res = [V.wet_count(img, r, "V-09-wet-" + which) for r in rooms]
    return pm, g, res
with ThreadPoolExecutor(14) as ex:
    out = list(ex.map(work, data))
V.save_cache()
ok_before = ok_after = n = 0; rows = []
for pm, g, res in out:
    before = sum(1 for i in pm["items"] if i["kind"] in ("bathtub", "shower"))
    good = [r for r in res if r]
    after = sum(s + b for s, b in good) if good else before
    t = g["shower_bathtub"]; n += 1; ok_before += before == t; ok_after += after == t
    rows.append((before, after, t))
print(which, "n", n, "before", round(ok_before / n, 3), "after", round(ok_after / n, 3))
json.dump(rows, open(f"/tmp/cc/wet_{which}.json", "w"))
