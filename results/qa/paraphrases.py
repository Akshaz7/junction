"""Demo robustness: paraphrases of the demo questions against a deployed backend (read-only; one chat per paraphrase).
JUDGE_BASE=https://... python3 results/qa/paraphrases.py [out.json]"""
import os, sys, json, time
import httpx
BASE = os.environ["JUDGE_BASE"]; DOC = "ifc_bench__ac20-arc"
CASES = {
 "doors_windows_gf": ["how many doors & windows does the ground floor have", "count the doors and windows on the ground floor", "ground floor: how many windows and doors?",
                      "number of doors and windows in the erdgeschoss", "tell me how many doors plus windows there are downstairs on the ground level"],
 "toilets": ["where's the loo", "where are the toilets", "show me all the WCs", "locate the restrooms in this building", "which rooms are toilets and where"],
 "remove_door": ["take away the main door, are we still ok?", "remove the front door. is it still compliant?", "what if I delete the main entrance, does it still meet the fire rules",
                 "hide the front door and check the building rules", "get rid of the entrance door - any violation?"],
 "reset": [["remove the front door", "reset"], ["remove the front door", "put it back"], ["remove the front door", "restore everything"],
           ["remove the front door", "undo that"], ["remove the front door", "show the original model again"]],
 "first_floor": [["how many doors and windows on the ground floor", "and the first floor?"], ["how many doors are on the ground floor", "what about the first floor"],
                 ["count windows on the ground floor", "same for the 1st floor"], ["ground floor doors", "now the floor above"],
                 ["how many windows are on the ground floor", "and upstairs?"]],
}
def post(c, *a, **k):
    for _ in range(6):
        r = c.post(*a, **k)
        if r.status_code != 429: return r
        time.sleep(int(r.headers.get("retry-after", "30")) + 2)
    return r
out = []
with httpx.Client(base_url=BASE, timeout=180) as c:
    for name, items in CASES.items():
        if os.environ.get("ONLY") and name not in os.environ["ONLY"].split(","): continue
        for it in items:
            qs = [it] if isinstance(it, str) else it
            rec = {"case": name, "qs": qs, "answers": []}
            try:
                chat = None
                for _t in range(5):
                    r = post(c, "/api/chats", json={"doc_ids": [DOC]})
                    try:
                        chat = r.json()["id"]; break
                    except Exception:
                        time.sleep(10)
                if chat is None: raise RuntimeError(f"chat create failed {r.status_code}")
                for q in qs:
                    ev, ans = None, None
                    with c.stream("POST", f"/api/chats/{chat}/messages", json={"content": q, "doc_ids": [DOC]}) as s:
                        for line in s.iter_lines():
                            if line.startswith("event:"): ev = line[6:].strip()
                            elif line.startswith("data:") and ev == "answer": ans = json.loads(line[5:].strip())
                    a = ans or {}; an = a.get("answer") or {}; sc = (a.get("evidence") or {}).get("scene") or {}
                    rec["answers"].append({"q": q, "text": an.get("text_md"), "value": an.get("value"), "abstained": an.get("abstained"), "route": a.get("route"),
                        "boxes": len((a.get("evidence") or {}).get("boxes") or []), "hl": len(sc.get("highlight_item_ids") or []), "hidden": sc.get("hidden_item_ids"),
                        "cards": len(a.get("advisor_cards") or []), "ms": a.get("latency_ms")})
                    time.sleep(2.5)
            except Exception as e:
                rec["error"] = repr(e)
            out.append(rec)
            print(name, "|", " -> ".join(qs)); 
            for x in rec["answers"]: print("   ", x["route"], "boxes", x["boxes"], "hl", x["hl"], "cards", x["cards"], "|", (x["text"] or "")[:230].replace("\n", " "))
            if rec.get("error"): print("   ERROR", rec["error"])
            sys.stdout.flush()
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "results/qa/paraphrases.json", "w"), indent=1, ensure_ascii=False)
