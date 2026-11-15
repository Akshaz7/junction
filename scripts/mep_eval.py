"""F-MEP: before/after on every MEP / structure question over IFC models (preview set, sample200, full question set). Before = code path without engine/mep.py; after = with it."""
import json, re, sys, time, os
from pathlib import Path
os.environ["MODELS_FAKE"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import analytics, mep
from engine.solvers.data import load_doc

def doc_id(path):
    p = Path(path); return f"{p.parent.name}__{p.stem.replace('_', '-')}"
def nums(t):
    return {round(float(x.replace(",", "")), 1) for x in re.findall(r"\d[\d,]*\.?\d*", str(t)) if x.strip(",")}
rows = json.load(open(sys.argv[1])); out = []; docs = {}
real_answer = mep.answer
for d in rows:
    did = doc_id(d["path"])
    if did not in docs:
        docs[did] = load_doc(did, ROOT / "artifacts")
    doc = docs[did]
    if doc is None:
        continue
    rec = {"doc": did, "q": d["question"], "ref": str(d["answer"])[:300]}
    for tag, fn in (("before", lambda: (mep.__setattr__("answer", lambda *a, **k: None), analytics.run(d["question"], doc, time.perf_counter()))[1]), ("after", lambda: (mep.__setattr__("answer", real_answer), analytics.run(d["question"], doc, time.perf_counter()))[1])):
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            r = None; rec[tag + "_err"] = str(e)[:100]
        txt = ((r or {}).get("answer") or {}).get("text_md", "")
        rn = nums(d["answer"]); an = nums(txt)
        rec[tag] = {"route": "code" if r else "reader", "text": txt[:400], "num_overlap": round(len(rn & an) / len(rn), 2) if rn else None}
    out.append(rec)
mep.answer = real_answer
json.dump(out, open(sys.argv[2], "w"), indent=1)
def stat(tag):
    c = [o for o in out if o[tag]["route"] == "code"]
    ov = [o[tag]["num_overlap"] for o in c if o[tag]["num_overlap"] is not None]
    return {"answered_by_code": len(c), "of": len(out), "mean_num_overlap_when_code": round(sum(ov) / len(ov), 2) if ov else None}
print("before", stat("before")); print("after", stat("after"))
