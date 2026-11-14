"""Stratified 60-question run on the real dataset (data/sets/questions_en.jsonl), held-out docs are eval-only here (no training), never sample200 rows.
usage: python results/qa/real60.py <tag> [--build]   writes results/qa/real60-<tag>.json (+ data/sets/real60.jsonl on --build)"""
import json, random, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine import bench
from engine.solvers.solve import ARTIFACTS
from engine.answer import answer
from server.schema import validate_answer

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "data/sets/real60.jsonl"
PLAN = {("cubicasa5k", "count"): 14, ("swiss_dwellings", "count"): 12, ("swiss_dwellings", "area"): 8, ("ifc_models", "area"): 8,
        ("ifc_models", "count"): 5, ("ifc_models", "volume"): 2, ("ifc_models", "length"): 2, ("ifc_bench", "text"): 5, ("opening_design", "count"): 4}


def build():
    # every doc with a question is in heldout_docs.txt (held out of TRAINING); this run only evaluates, nothing is trained or tuned per doc
    seen = {json.loads(l)["question"] + json.loads(l)["doc_id"] for l in open(ROOT / "data/sets/sample200.jsonl")}
    rows = [json.loads(l) for l in open(ROOT / "data/sets/questions_en.jsonl")]
    rows = [r for r in rows if r["question"] + r["doc_id"] not in seen and (ROOT / ARTIFACTS / r["doc_id"]).exists()]
    random.Random(7).shuffle(rows)
    out, per_doc, cnt = [], collections.Counter(), collections.Counter()
    for r in rows:
        k = (r["source"], r["type"])
        if cnt[k] >= PLAN.get(k, 0) or per_doc[r["doc_id"]] >= 2:
            continue
        out.append(r); cnt[k] += 1; per_doc[r["doc_id"]] += 1
    SET.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n")
    print(len(out), dict(cnt))


def validated(q, docs, ev=None):
    a = answer(q, docs, ev)
    validate_answer(a)
    return a


if __name__ == "__main__":
    tag = sys.argv[1]
    if "--build" in sys.argv or not SET.exists():
        build()
    qs = [json.loads(l) for l in open(SET)]
    res = bench.run(qs, answer_fn=validated, concurrency=2, max_usd=3.0)
    (ROOT / f"results/qa/real60-{tag}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    for r in res["results"]:
        print(r["outcome"], r.get("text_verdict") or "", r["source"], r["type"], r["route"], "gold", r["gold"] if r["type"] != "text" else "...", "got", r["value"], "|", r["question"][:70], r["error"] or "")
    print(res["cells"]); print(res["totals"])
