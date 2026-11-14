"""Runs engine.answer on judge_questions.jsonl, grades, writes results/qa/judge_run-<tag>.json"""
import sys, json, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine.answer import answer

tag = sys.argv[1] if len(sys.argv) > 1 else "r1"
only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
qs = [json.loads(l) for l in open("results/qa/judge_questions.jsonl")]
if only: qs = [q for q in qs if q["id"] in only]

def nums(s): return [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*\.?\d*", s)]

def text_of(a):
    ans = a.get("answer") or {}
    parts = [str(ans.get("text_md") or "")]
    v = ans.get("value")
    parts.append(json.dumps(v) if isinstance(v, (dict, list)) else str(v if v is not None else ""))
    for c in a.get("citations") or []:
        parts.append(str(c.get("quote") or c.get("text") or ""))
    for c in a.get("advisor_cards") or []:
        parts.append(json.dumps(c, ensure_ascii=False))
    return " ".join(parts)

def grade(q, a):
    txt = text_of(a); low = txt.lower()
    ans = a.get("answer") or {}
    abst = bool(ans.get("abstained"))
    if q["expect_abstain"]: return "correct" if abst else "wrong"
    if abst and not txt.strip(): return "wrong"
    hits = []
    if q["value"] is not None:
        t = q["value"]; tol = q["tol"]
        ns = nums(str(ans.get("text_md") or "")) + nums(str(ans.get("value") if not isinstance(ans.get("value"), (dict, list)) else ""))
        ok = any(abs(n - t) <= max(tol * abs(t), 0.051 if tol else 0.0) for n in ns)
        near = any(abs(n - t) <= 0.25 * max(abs(t), 1) for n in ns)
        hits.append(("val", ok, near))
    for m in q["must"]:
        alts = m.lower().split("|")
        hits.append(("must", any(a in low or a.replace(" ", "") in low.replace(" ", "") for a in alts), False))
    if not hits: return "wrong"
    if all(h[1] for h in hits): return "correct"
    if any(h[1] or h[2] for h in hits): return "partial"
    return "wrong"

def run(q):
    t0 = time.time()
    try:
        a = answer(q["question"], [q["doc_id"]], lambda *x, **k: None)
    except Exception as e:
        return dict(q, grade="wrong", err=repr(e), secs=round(time.time() - t0, 1))
    ans = a.get("answer") or {}
    c = a.get("cost") or {}
    return dict(q, grade=grade(q, a), got=str(ans.get("text_md"))[:500], value_got=ans.get("value"), route=a.get("route"),
                cost=c.get("usd") if isinstance(c, dict) else c, abstained=bool(ans.get("abstained")),
                n_boxes=len((a.get("evidence") or {}).get("boxes") or []), secs=round(time.time() - t0, 1))

with ThreadPoolExecutor(3) as ex: res = list(ex.map(run, qs))
json.dump(res, open(f"results/qa/judge_run-{tag}.json", "w"), indent=1, ensure_ascii=False)
from collections import Counter
print(Counter(r["grade"] for r in res))
for r in res: print(r["id"], r["grade"], r["type"], "|", r["question"][:50], "=>", (r.get("got") or r.get("err") or "")[:110].replace("\n", " "), r.get("secs"))
