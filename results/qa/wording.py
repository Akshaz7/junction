"""E-60: run the demo/judge hard cases plus a spread of sample200 questions through the local engine and dump every answer text.
MODELS_FAKE=1 .venv/bin/python results/qa/wording.py out.json"""
import os, sys, json
os.environ.setdefault("MODELS_FAKE", "1")
from engine.answer import answer
rows = [json.loads(l) for l in open("results/hard_cases.jsonl")]
qs = [(r["id"], r["doc_id"], [r["question"], *r.get("followups", [])]) for r in rows]
s200 = [json.loads(l) for l in open("data/sets/sample200.jsonl")]
for i, r in enumerate(s200[::7][:30]):
    qs.append((f"s200-{i}", r["doc_id"], [r["question"]]))
out = []
for cid, doc, questions in qs:
    hist = []
    for q in questions:
        try:
            a = answer(q, [doc], history=hist)
            t = a["answer"]["text_md"]
            out.append({"id": cid, "doc": doc, "q": q, "text": t, "route": a["route"], "value": a["answer"].get("value"), "unit": a["answer"].get("unit"),
                        "abstained": a["answer"].get("abstained"), "boxes": len(a["evidence"]["boxes"])})
            hist += [{"role": "user", "content": q, "doc_ids": [doc]}, {"role": "assistant", "content": t, "doc_ids": [doc]}]
        except Exception as e:
            out.append({"id": cid, "doc": doc, "q": q, "text": f"ERROR {e!r}"})
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
for o in out:
    print(f"[{o['id']}] {o['q']}\n   -> {o['text'][:260]!r}")
