"""Run with scripts/heavy.sh; writes only results/final/CALC in this worktree."""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

os.environ.update(MODELS_FAKE="1", READER="0", RECOUNT="0", EXPLAIN="0", ANSWER_TIMEOUT_S="0")

from engine.answer import answer
from engine.calc import number, validate
from engine.tests.calc_cases import CASES


def include_wallarea(out):
    path = Path("results/final/CALC/wallarea.json")
    if not path.is_file(): return out
    wall = json.loads(path.read_text())
    out["answers"] = [e for e in out["answers"] if not e["route"].startswith("wallarea/")]
    for index, entry in enumerate(wall["answers"]):
        route = f"wallarea/case-{index + 1}"
        e = {**entry, "route": route, "docs": [entry["doc_id"]], "numeric": number(entry.get("value")),
             "eligible": number(entry.get("value")), "has_calc": bool(entry.get("complete")), "upstream_commit": wall["upstream_commit"]}
        out["answers"].append(e)
        out["routes"][route] = {"answers": 1, "numeric_answers": int(e["numeric"]), "numeric_or_table_answers": int(e["eligible"]),
                               "with_complete_calc": int(e.get("complete", False)), "complete_pct": 100.0 if e.get("complete") else 0.0}
    out["totals"] = {"answers": len(out["answers"]), "numeric_or_table_answers": sum(bool(e.get("eligible")) for e in out["answers"]),
                     "complete": sum(e.get("complete", False) for e in out["answers"])}
    return out


def run(blind=False):
    root = Path("artifacts")
    entries, by_route = [], defaultdict(list)
    cases = list(CASES)
    if blind:
        did = json.loads(Path("results/final/CALC/blind.json").read_text())["doc_id"]
        cases.extend(("blind/cad/" + label, did, q) for label, q in [("count", "How many doors are there?"), ("area", "What is the total area of all rooms?"), ("baseboard", "How many linear metres of baseboard per room?")])
    for route, dids, q in cases:
        dids = dids if isinstance(dids, list) else [dids]
        if not all((root / d).is_dir() for d in dids):
            entries.append({"route": route, "question": q, "docs": dids, "skipped": "artifact missing"})
            continue
        try:
            res = answer(q, dids)
            value = res["answer"]["value"]
            numeric = number(value) or isinstance(value, dict) and value and all(number(v) for v in value.values())
            calc = res.get("reasoning", {}).get("calc")
            issues = validate(calc, root) if calc else ["no calculation"]
            entry = {"route": route, "question": q, "docs": dids, "value": value, "unit": res["answer"].get("unit"),
                     "numeric": bool(numeric), "has_calc": bool(calc), "complete": bool(calc) and not issues,
                     "eligible": bool(numeric or calc),
                     "rows": len(calc.get("rows", [])) if calc else 0, "issues": issues,
                     "answer_trace": [{"step": s["step"], "detail": s["detail"]} for s in res.get("trace", []) if not s.get("model")][:5]}
        except Exception as e:
            entry = {"route": route, "question": q, "docs": dids, "complete": False, "error": f"{type(e).__name__}: {e}"}
        entries.append(entry)
        by_route[route].append(entry)
    routes = {r: {"answers": len(es), "numeric_answers": sum(bool(e.get("numeric")) for e in es), "numeric_or_table_answers": sum(bool(e.get("eligible")) for e in es),
                  "with_complete_calc": sum(e.get("complete", False) for e in es),
                  "complete_pct": 100 * sum(e.get("complete", False) for e in es) / sum(bool(e.get("eligible")) for e in es) if any(e.get("eligible") for e in es) else None} for r, es in by_route.items()}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "models": "fake; recount/reader/explain disabled; no live calls", "blind_run": blind,
           "scope": "Observed numeric code routes in the listed real-file cases; not a claim that unseen route variants are covered.",
           "totals": {"answers": len(entries), "numeric_or_table_answers": sum(bool(e.get("eligible")) for e in entries), "complete": sum(e.get("complete", False) for e in entries)}, "routes": routes, "answers": entries}
    out = include_wallarea(out)
    Path("results/final/CALC/coverage.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(out["totals"]))
    for e in entries:
        if not e.get("complete"): print(e["route"], e.get("value"), e.get("issues") or e.get("error"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--blind", action="store_true")
    parser.add_argument("--merge-wallarea", action="store_true", help="Merge completed audit summaries without running questions again")
    args = parser.parse_args()
    if args.merge_wallarea:
        path = Path("results/final/CALC/coverage.json")
        result = include_wallarea(json.loads(path.read_text()))
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(result["totals"]))
    else:
        run(args.blind)
