"""Free-form judge questions on raster plans. MODELS_FAKE=1 PYTHONPATH=. .venv/bin/python results/qa/raster_judge.py out.json"""
import os, sys, json
os.environ.setdefault("MODELS_FAKE", "1")
from engine.answer import answer
DOCS = ["cubicasa5k__colorful-11397", "cubicasa5k__high-quality-10306"]
QS = ["how many rooms are there", "what is the area of the kitchen", "how big is this flat", "how many bathrooms", "how many doors", "how many windows",
      "where is the kitchen", "what is the largest room", "how many bedrooms are there", "total floor area", "is this accessible", "is this plan wheelchair accessible",
      "how many toilets", "waht is the area of the livng room", "hw many windws are there", "list all the rooms", "which room has the most windows",
      "what is the smallest room", "how many doors does the bedroom have", "is there a balcony", "how many floors", "what is the ceiling height",
      "and how big is it", "show me the bathroom", "does this meet fire code"]
out = []
for d in DOCS:
    hist = []
    for q in QS:
        try:
            a = answer(q, [d], history=hist); t = a["answer"]["text_md"]
            out.append({"doc": d, "q": q, "text": t, "route": a["route"], "abst": a["answer"].get("abstained"), "conf": a["answer"].get("confidence"), "boxes": len(a["evidence"]["boxes"])})
            hist = (hist + [{"role": "user", "content": q, "doc_ids": [d]}, {"role": "assistant", "content": t, "doc_ids": [d]}])[-6:]
        except Exception as e:
            out.append({"doc": d, "q": q, "text": f"ERROR {e!r}"})
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
for o in out: print(f"[{o['doc'][-10:]}] {o['q']}\n   -> {o['text'][:330]!r} ({o.get('route')},abst={o.get('abst')},c={o.get('conf')})")
