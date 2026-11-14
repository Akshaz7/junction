"""V-04: vision evaluation. Exact-count accuracy per kind against data/sets/questions_en.jsonl.

  uv run python vision/eval.py [--source cubicasa5k] [--fixtures] [--sample200] [--out results/vision/baseline.json]
Counts come from artifacts/<doc_id>/planmap-1.json only. Unanswerable by vision (floors) are skipped.
"""
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = [  # (question regex, label, counter(planmap) -> int)
    (r"^How many windows", "window", lambda c: c["window"]),
    (r"^How many doors", "door", lambda c: c["door"]),
    (r"^How many toilet", "toilet", lambda c: c["toilet"]),
    (r"^How many sinks", "sink", lambda c: c["sink"]),
    (r"^How many showers and bathtubs", "shower_bathtub", lambda c: c["bathtub"] + c["shower"]),
    (r"^How many bedrooms", "bedroom", lambda c: c["room:bedroom"]),
    (r"^How many kitchens", "kitchen", lambda c: c["room:kitchen"]),
    (r"^How many bathrooms", "bathroom", lambda c: c["room:bathroom"]),
    (r"^How many separate WC", "wc_room", lambda c: c["room:wc"]),
    (r"^How many saunas", "sauna", lambda c: c["room:sauna"]),
    (r"^How many balconies", "balcony", lambda c: c["room:balcony"]),
]


def counts(pm):
    c = Counter()
    for i in pm["items"]:
        c[i["kind"]] += 1
        if i["kind"] == "room":
            c["room:" + i["props"]["room_type"]] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cubicasa5k")
    ap.add_argument("--only", help="file of doc_ids to restrict to (fixtures: tests/fixtures.json)")
    ap.add_argument("--out", default="results/vision/baseline.json")
    ap.add_argument("--planmap", default="planmap-1.json")
    a = ap.parse_args()
    only = None
    if a.only:
        only = set(json.load(open(a.only))) if a.only.endswith(".json") else {l.split()[0] for l in open(a.only)}
    per = defaultdict(lambda: {"n": 0, "exact": 0, "abs_err": 0.0, "over": 0, "under": 0, "within1": 0})
    rows = []
    for l in open(ROOT / "data/sets/questions_en.jsonl"):
        q = json.loads(l)
        if q["source"] != a.source or (only is not None and q["doc_id"] not in only):
            continue
        rule = next((r for r in RULES if re.search(r[0], q["question"])), None)
        pmp = ROOT / f"artifacts/{q['doc_id']}/{a.planmap}"
        if not rule or not pmp.exists() or q.get("type") != "count":
            continue
        pred = rule[2](counts(json.load(open(pmp))))
        truth = int(q["answer"])
        s = per[rule[1]]
        s["n"] += 1; s["exact"] += pred == truth; s["abs_err"] += abs(pred - truth)
        s["over"] += pred > truth; s["under"] += pred < truth; s["within1"] += abs(pred - truth) <= 1
        rows.append({"doc_id": q["doc_id"], "kind": rule[1], "truth": truth, "pred": pred})
    out = {k: {"n": v["n"], "exact_acc": round(v["exact"] / v["n"], 3), "within1_acc": round(v["within1"] / v["n"], 3),
               "mae": round(v["abs_err"] / v["n"], 2), "over": v["over"], "under": v["under"]} for k, v in sorted(per.items())}
    tot = sum(v["n"] for v in per.values())
    out_all = {"overall_exact_acc": round(sum(v["exact"] for v in per.values()) / max(tot, 1), 3), "n_questions": tot,
               "per_kind": out, "planmap": a.planmap, "note": "all questions are on held-out drawings; no thresholds tuned on them except coarse det_size choice (4 fixtures)"}
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**out_all, "rows": rows}, indent=1))
    print(json.dumps(out_all, indent=1))


if __name__ == "__main__":
    main()
