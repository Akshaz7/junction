"""Build plan maps for many docs in chunks (memory-safe). Run via scripts/heavy.sh.
  scripts/heavy.sh uv run python vision/run_batch.py --source cubicasa5k [--chunk 25] [--limit N]
Docs = every artifacts/<doc_id> whose doc.json source matches and that has a question in data/sets/questions_en.jsonl.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_planmaps as B

ROOT = B.ROOT
ap = argparse.ArgumentParser()
ap.add_argument("--source", default="cubicasa5k")
ap.add_argument("--chunk", type=int, default=25)
ap.add_argument("--limit", type=int)
ap.add_argument("--stage", default="merged")
a = ap.parse_args()
qdocs = sorted({json.loads(l)["doc_id"] for l in open(ROOT / "data/sets/questions_en.jsonl") if json.loads(l)["source"] == a.source})
docs = [d for d in qdocs if (ROOT / f"artifacts/{d}/doc.json").exists()][: a.limit]
print(len(docs), "docs", flush=True)
allt, bad = {}, {}
for i in range(0, len(docs), a.chunk):
    t, p = B.run(docs[i:i + a.chunk], ("seg",) if a.stage == "seg" else ("seg", "merged"))
    allt.update(t); bad.update({k: v for k, v in p.items() if v})
    print(i + a.chunk, "done", flush=True)
(ROOT / "results/vision").mkdir(parents=True, exist_ok=True)
(ROOT / f"results/vision/timing_{a.source}.json").write_text(json.dumps(allt))
print("invalid:", bad)
