"""Extract calibration drawings (CubiCasa5K minus every question-referenced drawing) with SVG GT counts.
Single-floor only (F1_original matches the dataset composite). Loads the held-out list fresh."""
import json, sys, zipfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cubicasa_gt import svg_counts
root = pathlib.Path(__file__).resolve().parent.parent
held = {l.strip() for l in open(root/"data/sets/cubicasa_heldout_ids.txt") if l.strip()}
pool = [l.strip() for l in open("/tmp/cc/pool.txt") if l.strip()]
z = zipfile.ZipFile(root/"data/cubicasa5k/cubicasa5k.zip")
names = set(z.namelist())
out = root/"data/cubicasa5k/calib"; out.mkdir(parents=True, exist_ok=True)
gt = {}
for p in pool:
    if p in held: continue
    base = f"cubicasa5k/{p}/"
    if base+"F2_original.png" in names or base+"F1_original.png" not in names: continue
    d = p.replace("/", "_")
    (out/f"{d}.png").write_bytes(z.read(base+"F1_original.png"))
    gt[d] = dict(svg_counts(z.read(base+"model.svg").decode()))
json.dump(gt, open(out/"gt.json", "w"))
print(len(gt), "calib drawings")
