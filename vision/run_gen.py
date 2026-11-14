"""V-10: build plan maps (vision only, free pass on) for swiss PNGs + samples of wikimedia/habs/finna into data/vision_gen/.
  scripts/heavy.sh uv run python vision/run_gen.py [--n 40]
"""
import argparse, glob, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_planmaps as B
ROOT = B.ROOT
ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=40); a = ap.parse_args()
sw = sorted({json.loads(l)["doc_id"] for l in open(ROOT / "data/sets/questions_en.jsonl") if json.loads(l)["source"] == "swiss_dwellings"})
docs = list(sw)
for s in ("wikimedia", "habs", "finna"):
    ds = sorted(Path(p).parent.name for p in glob.glob(str(ROOT / f"artifacts/{s}__*/doc.json")))
    step = max(1, len(ds) // a.n)
    docs += ds[::step][: a.n]
out = ROOT / "data/vision_gen"
allt, bad = {}, {}
for i in range(0, len(docs), 15):
    t, p = B.run(docs[i:i + 15], ("seg", "merged"), out)
    allt.update(t); bad.update({k: v for k, v in p.items() if v})
    print(i + 15, "of", len(docs), flush=True)
(out / "timing.json").write_text(json.dumps(allt)); print("invalid:", bad)
