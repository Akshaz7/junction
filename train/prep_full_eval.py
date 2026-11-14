"""Resize all held-out CubiCasa drawings (4,787) to 1024x1024 PNG for batch inference on Modal. Output dir arg (kept out of git)."""
import sys, json
from pathlib import Path
sys.path.insert(0, "vision")
from PIL import Image
import build_planmaps as B
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
ids = sorted({json.loads(l)["doc_id"] for l in open("data/sets/questions_en.full.jsonl") if json.loads(l).get("source") == "cubicasa5k"})
for i, d in enumerate(ids):
    p = out / (d + ".png")
    if not p.exists():
        Image.open(B.image_path(d)).convert("RGB").resize((1024, 1024), Image.BILINEAR).save(p, optimize=False, compress_level=3)
    if i % 500 == 0: print(i, flush=True)
print("n", len(ids))
