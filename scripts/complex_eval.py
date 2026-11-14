"""Honest eval of the drawing reader: old engine path (READER=0) vs the reader. Usage: python scripts/complex_eval.py [old|new|both]"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ARTIFACTS_DIR", str(ROOT / "artifacts"))


def norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("”", '"').replace("’", "'").casefold())


def judge(q, a):
    ab = a["answer"]["abstained"]
    txt = norm(a["answer"]["text_md"])
    if q["expect_abstain"]:
        return {"correct": ab, "cited": True}
    ok = (not ab) and all(norm(m) in txt for m in q["must"])
    return {"correct": ok, "cited": bool(a["citations"])}


def run(mode, qs):
    from engine.answer import answer
    os.environ["READER"] = "1" if mode == "new" else "0"
    def one(q):
        t = time.time()
        try:
            a = answer(q["question"], q["doc_ids"])
        except Exception as e:
            return {"id": q["id"], "error": str(e)[:100], "correct": False, "cited": False, "usd": 0, "s": 0}
        j = judge(q, a)
        return {"id": q["id"], "q": q["question"], **j, "abstained": a["answer"]["abstained"], "route": a["route"], "usd": a["cost"]["usd_total"],
                "s": round(time.time() - t, 1), "answer": a["answer"]["text_md"][:300]}
    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(one, qs))


def summ(rs):
    n = len(rs)
    ans = [r for r in rs]
    return {"n": n, "correct": sum(r["correct"] for r in rs), "accuracy": round(sum(r["correct"] for r in rs) / n, 3),
            "cited_when_answered": sum(1 for r in rs if r["cited"] and not r.get("abstained")),
            "usd_total": round(sum(r["usd"] for r in rs), 4), "usd_per_q": round(sum(r["usd"] for r in rs) / n, 4),
            "latency_s_median": sorted(r["s"] for r in rs)[n // 2], "latency_s_max": max(r["s"] for r in rs)}


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    qs = [json.loads(l) for l in (ROOT / "results/complex_eval/questions.jsonl").read_text().splitlines() if l.strip()]
    rep = {"questions": len(qs), "date": time.strftime("%Y-%m-%d %H:%M")}
    for m in (["old", "new"] if which == "both" else [which]):
        rs = run(m, qs)
        rep[m] = {"summary": summ(rs), "results": rs}
        print(m, rep[m]["summary"])
    p = ROOT / "results/complex_eval/report.json"
    if p.exists() and which != "both":
        old = json.loads(p.read_text()); old.update(rep); rep = old
    p.write_text(json.dumps(rep, indent=1))
