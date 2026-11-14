"""Measure project-wide answering (no doc_ids): python -m engine.project_eval [--fake] -> results/project_search.json

Sets (deterministic picks from data/sets/questions_en.full.jsonl; gold doc = the row's doc_id):
  pdf_raw      opening_design sheet questions, verbatim (they name the sheet / project in words)
  plan_raw     numeric cubicasa / ifc_bench / swiss questions verbatim (no document named: ambiguous by design)
  plan_named   the same rows prefixed "In <doc id tail>:" (a user naming the file)
  complex      5 multi-step take-off questions (checked against an independent sum from the raw JSON)
Numbers: retrieval top-1 / top-5 (engine.project_index.search over the whole index), answer accuracy by engine.bench.score
(numeric) or judge_text (text), latency, cost from the answer objects. The questions were not used to tune the engine.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pick(rows, n):
    if len(rows) <= n:
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def load_sets():
    qs = [json.loads(l) for l in open(ROOT / "data/sets/questions_en.full.jsonl", encoding="utf-8")]
    pdf = _pick([q for q in qs if q["source"] == "opening_design"], 10)
    num = [q for q in qs if q["type"] in ("count", "area") and q["source"] in ("cubicasa5k", "ifc_bench", "swiss_dwellings")]
    plan = []
    for src in ("ifc_bench", "cubicasa5k", "swiss_dwellings"):
        plan += _pick([q for q in num if q["source"] == src], 4)
    return pdf, plan


COMPLEX = [
    ("How many square metres of tiling should I order for the toilets in fantasy-office-building-3-arc?", "ifc_bench__fantasy-office-building-3-arc", "toilet"),
    ("How much floor tile do I need for the WC in colorful-10312?", "cubicasa5k__colorful-10312", "toilet"),
    ("What is the total floor area of the bathrooms in site1004-bldg2086-floor9400 and how much tile should I buy?", "swiss_dwellings__site1004-bldg2086-floor9400", "bathroom"),
    ("How much flooring should I order for the kitchens in fantasy-office-building-3-arc?", "ifc_bench__fantasy-office-building-3-arc", "kitchen"),
    ("How many litres of paint do I need for the ceilings of the bathrooms in site1029-bldg2117-floor9641?", "swiss_dwellings__site1029-bldg2117-floor9641", "bathroom"),
]


def independent_sum(doc_id: str, cls: str) -> tuple[float, int]:
    """Room area sum straight from the raw JSON with a separate, simpler matcher (cross-check for the take-off)."""
    from engine.takeoff import ROOM_CLASSES, plan_geom
    d = ROOT / "artifacts" / doc_id
    rx = re.compile(ROOM_CLASSES[cls], re.I)
    tot, n = 0.0, 0
    el = d / "elements.json"
    if el.exists():
        geom = plan_geom(doc_id, ROOT / "artifacts")
        for x in json.loads(el.read_text())["elements"]:
            nm = (x.get("props") or {}).get("long_name") or ""
            if x["kind"] == "room" and re.search(rx, nm):
                q = x.get("quantities") or {}
                a = q.get("net_floor_area_m2") or q.get("area_m2") or (geom.get(x["item_id"]) or [None])[0]
                if a and a > 0.3:
                    tot += a
                    n += 1
        return round(tot, 2), n
    for pf in d.glob("planmap-[0-9]*.json"):
        pm = json.loads(pf.read_text())
        texts = [i for i in pm["items"] if i["kind"] in ("text", "other") and i.get("label") and re.search(rf"(?<![a-zäöüé])(?:{rx.pattern})(?![a-zäöüé])", i["label"], re.I)]
        for i in pm["items"]:
            if i["kind"] != "room":
                continue
            names = [i.get("label"), (i.get("props") or {}).get("room_type")]
            hit = any(nm and re.fullmatch(rx.pattern, str(nm).strip(), re.I) for nm in names)
            if not hit and i.get("bbox_px"):
                b = i["bbox_px"]
                hit = any(b[0] <= (t["bbox_px"][0] + t["bbox_px"][2]) / 2 <= b[2] and b[1] <= (t["bbox_px"][1] + t["bbox_px"][3]) / 2 <= b[3] for t in texts)
            pr = i.get("props") or {}
            a = pr.get("area_m2_label") or pr.get("area_m2")
            if hit and a and a > 0.3:
                tot += a
                n += 1
    return round(tot, 2), n


def main(argv):
    from engine import bench
    from engine.answer import answer
    from engine.project_index import load_index
    root = ROOT / "artifacts"
    os.environ.setdefault("ARTIFACTS_DIR", str(root))
    if "--fake" in argv:
        os.environ["MODELS_FAKE"] = "1"
    ix = load_index(root)
    if ix is None:
        print("no index: python -m engine.project_index build")
        return 1
    t = time.perf_counter()
    ix.search("warm up")
    pdf, plan = load_sets()
    rows = []

    def run(set_name, row, question):
        t0 = time.perf_counter()
        sr0 = time.perf_counter()
        hits = ix.search(question, 10)
        search_ms = (time.perf_counter() - sr0) * 1000
        ids = [h["doc_id"] for h in hits]
        ans = answer(question, [])
        ms = int((time.perf_counter() - t0) * 1000)
        a = ans["answer"]
        outcome = bench.score(row, ans) if row["type"] in bench.NUMERIC else "unscored"
        verdict = None
        if row["type"] not in bench.NUMERIC and not os.environ.get("MODELS_FAKE") and a.get("text_md"):
            verdict, _ = bench.judge_text(question, row["answer"], a["text_md"])
        r = {"set": set_name, "gold_doc": row["doc_id"], "type": row["type"], "question": question[:200], "gold": row["answer"],
             "top1": bool(ids) and ids[0] == row["doc_id"], "top5": row["doc_id"] in ids[:5], "search_ms": round(search_ms, 1),
             "answer_docs": ans["doc_ids"], "answer_doc_ok": row["doc_id"] in ans["doc_ids"], "value": a.get("value"),
             "abstained": bool(a.get("abstained")), "outcome": outcome, "text_verdict": verdict, "route": ans.get("route"),
             "cost_usd": ans["cost"]["usd_total"], "ms": ms, "citations": len(ans["citations"]), "text": (a.get("text_md") or "")[:240]}
        rows.append(r)
        print(set_name, r["top1"], r["top5"], outcome, verdict, ms, "ms", question[:70], flush=True)

    for q in pdf:
        run("pdf_raw", q, q["question"])
    for q in plan:
        run("plan_raw", q, q["question"])
    for q in plan:
        tail = q["doc_id"].split("__", 1)[1]
        run("plan_named", q, f"In {tail}: {q['question']}")

    complex_rows = []
    for question, did, cls in COMPLEX:
        t0 = time.perf_counter()
        ans = answer(question, [])
        exp, n = independent_sum(did, cls)
        a = ans["answer"]
        text = a.get("text_md") or ""
        m = re.search(r"floor area[^=]*= ([\d,.]+)", text) or re.search(r"add up to ([\d,.]+)", text)
        got_total = None
        mm = re.search(r"([\d,]+\.?\d*) m² net floor area", text)
        if mm:
            got_total = float(mm.group(1).replace(",", ""))
        ids = [c["item_ids"][0] for c in ans["citations"] if c.get("item_ids")]
        complex_rows.append({
            "question": question, "gold_doc": did, "answer_docs": ans["doc_ids"], "doc_ok": ans["doc_ids"] == [did],
            "value": a.get("value"), "unit": a.get("unit"), "abstained": bool(a.get("abstained")), "room_area_total_m2": got_total,
            "independent_total_m2": exp, "independent_rooms": n, "cited_rooms": len(ans["citations"]),
            "total_matches": (got_total is not None and abs(got_total - exp) <= max(0.1, 0.01 * exp)) or (exp == 0 and bool(a.get("abstained"))), "boxes": len(ans["evidence"]["boxes"]),
            "cost_usd": ans["cost"]["usd_total"], "ms": int((time.perf_counter() - t0) * 1000), "text": text[:500]})
        print("complex", complex_rows[-1]["doc_ok"], complex_rows[-1]["total_matches"], question[:60], flush=True)

    def agg(name):
        rs = [r for r in rows if r["set"] == name]
        num = [r for r in rs if r["outcome"] != "unscored"]
        txt = [r for r in rs if r["outcome"] == "unscored"]
        return {
            "n": len(rs), "retrieval_top1": round(sum(r["top1"] for r in rs) / len(rs), 3), "retrieval_top5": round(sum(r["top5"] for r in rs) / len(rs), 3),
            "answer_doc_correct": sum(r["answer_doc_ok"] for r in rs),
            "numeric": {"n": len(num), "correct": sum(r["outcome"] == "correct" for r in num), "wrong": sum(r["outcome"] == "wrong" for r in num),
                        "abstained": sum(r["outcome"] == "abstained" for r in num)},
            "text": {"n": len(txt), "verdicts": {v: sum(r["text_verdict"] == v for r in txt) for v in ("correct", "partial", "wrong")},
                     "abstained": sum(r["abstained"] for r in txt), "unjudged": sum(r["text_verdict"] is None for r in txt)},
            "cost_usd": round(sum(r["cost_usd"] for r in rs), 5),
        }

    ms = [r["ms"] for r in rows]
    sm = [r["search_ms"] for r in rows]
    out = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "fake_models": bool(os.environ.get("MODELS_FAKE")),
        "index": {"docs": len(ix.docs), "chunks": len(ix.chunks), "terms": len(ix.postings)},
        "summary": {n: agg(n) for n in ("pdf_raw", "plan_raw", "plan_named")},
        "latency_ms": {"answer_median": int(statistics.median(ms)), "answer_p95": int(sorted(ms)[int(len(ms) * 0.95) - 1]),
                       "search_median": round(statistics.median(sm), 1), "search_max": round(max(sm), 1)},
        "cost_usd_total": round(sum(r["cost_usd"] for r in rows) + sum(r["cost_usd"] for r in complex_rows), 5),
        "complex": complex_rows, "rows": rows,
        "notes": ["plan_raw questions do not name a document ('this floor plan'): the engine must ask which one or abstain; a wrong number is the failure.",
                  "plan_named prefixes the document id tail, as a user naming the file would.",
                  "Gold text answers are judged by judge_text; numeric by engine.bench.score (count exact, area 2%)."],
    }
    (ROOT / "results" / "project_search.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({"summary": out["summary"], "latency_ms": out["latency_ms"], "cost": out["cost_usd_total"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
