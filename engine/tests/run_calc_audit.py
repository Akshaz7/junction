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
                     "rows": len(calc.get("rows", [])) if calc else 0, "issues": issues,
                     "answer_trace": [{"step": s["step"], "detail": s["detail"]} for s in res.get("trace", []) if not s.get("model")][:5]}
        except Exception as e:
            entry = {"route": route, "question": q, "docs": dids, "complete": False, "error": f"{type(e).__name__}: {e}"}
        entries.append(entry)
        by_route[route].append(entry)
    routes = {r: {"answers": len(es), "numeric_answers": sum(bool(e.get("numeric")) for e in es),
                  "with_complete_calc": sum(e.get("complete", False) for e in es),
                  "complete_pct": 100 * sum(e.get("complete", False) for e in es) / len(es)} for r, es in by_route.items()}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "models": "fake; recount/reader/explain disabled; no live calls", "blind_run": blind,
           "scope": "Observed numeric code routes in the listed real-file cases; not a claim that unseen route variants are covered.",
           "totals": {"answers": len(entries), "complete": sum(e.get("complete", False) for e in entries)}, "routes": routes, "answers": entries}
    Path("results/final/CALC/coverage.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(out["totals"]))
    for e in entries:
        if not e.get("complete"): print(e["route"], e.get("value"), e.get("issues") or e.get("error"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--blind", action="store_true")
    run(parser.parse_args().blind)
