"""Read-only room-identifier regression on real artifacts; emit small before/after JSON."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from engine.solvers.data import load_doc
from engine.solvers.filters import fold, room_filter, room_name


def validate(doc_id, artifacts, baseline):
    doc = load_doc(doc_id, artifacts)
    assert doc is not None, doc_id
    rooms = [r for r in doc.items if r.kind == "room"]
    number_of = lambda r: str(r.props.get("number") or r.name or "").strip()
    numbered = [r for r in rooms if re.fullmatch(r"[\w.\-]*\d[\w.\-]*", number_of(r))]
    queries = []
    if numbered:
        for room in numbered[:3]:
            number = number_of(room)
            same_number = [r for r in rooms if number_of(r) == number]
            queries.append((f"What is the area of room {number}?", same_number))
            name = room_name(room)
            if name != number:
                same_name = [r for r in same_number if fold(room_name(r)) == fold(name)]
                queries.append((f"What is the area of {name} {number}?", same_name))
                compact = re.sub(r"[.\-]", "", number)
                if compact != number and not any(str(r.props.get("number") or r.name) == compact for r in rooms):
                    queries.append((f"What is the area of {name} {compact}?", same_name))
    else:
        labels = list(dict.fromkeys(r.label for r in rooms if r.label))[:3]
        queries = [(f"What is the area of {label}?", [r for r in rooms if r.label == label]) for label in labels]
    assert queries, f"{doc_id}: no labelled rooms to test"
    results = []
    for question, expected in queries:
        before, after = baseline(question, rooms), room_filter(question, rooms)
        ids = lambda result: sorted(r.item_id for r in result[1]) if result is not None else None
        expected_ids = sorted(r.item_id for r in expected)
        results.append({"question": question, "expected": expected_ids, "before": ids(before), "after": ids(after),
                        "before_pass": ids(before) == expected_ids, "after_pass": ids(after) == expected_ids})
        assert ids(after) == expected_ids, (doc_id, question, results[-1])
    return {"doc_id": doc_id, "mode": doc.mode, "questions": results,
            "before_pass": sum(r["before_pass"] for r in results), "after_pass": sum(r["after_pass"] for r in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--docs", nargs="+", required=True)
    args = parser.parse_args()
    source = subprocess.check_output(["git", "show", f"{args.baseline}:engine/solvers/filters.py"], text=True)
    namespace = {"__package__": "engine.solvers"}
    exec(compile(source, "baseline_filters.py", "exec"), namespace)
    results = [validate(doc_id, args.artifacts, namespace["room_filter"]) for doc_id in args.docs]
    args.output.write_text(json.dumps({"baseline": args.baseline, "documents": results}, indent=2) + "\n")
    print(json.dumps([{k: v for k, v in row.items() if k != "questions"} for row in results]))


if __name__ == "__main__":
    main()
