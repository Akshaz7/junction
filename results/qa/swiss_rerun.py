"""E-39 one-shot evaluation, run through scripts/heavy.sh. No tuning or model calls.

Generated for demo tests define the fixes; held-out documents are read only here for evaluation.
Run: PYTHONPATH=. scripts/heavy.sh .venv/bin/python results/qa/swiss_rerun.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import types
from collections import Counter, defaultdict
from pathlib import Path

from engine.bench import load_set, run, summarize
from engine.solvers.solve import solve
from pipeline.dxf_planmap import process

ROOT = Path(__file__).resolve().parents[2]
BASE = "54f0cb545e0a07054a3e8b0ac44010b1cc2d43a9"
OUT = ROOT / "results/qa"
ARCHIVE = ROOT / "results/bench/e-s200-z2.rows.jsonl"


def old_module(path, name):
    source = subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT, text=True)
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def question_class(row):
    q = row["question"].casefold()
    if "apartment" in q:
        kind = "apartments"
    elif "rooms labelled" in q:
        kind = "labelled rooms"
    else:
        kind = next((noun for noun in ("toilets", "washbasins", "bathtubs", "showers", "windows", "doors")
                     if noun in q), "rooms")
    return f"{row['type']} / {kind}"


def failure_report(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[question_class(row)].append(row)
    lines = ["# Swiss DXF failures — E-39", "",
             "Source: `results/bench/e-s200-z2.rows.jsonl`, Swiss rows only. "
             "Gold values below are copied from saved results, not used in the reader or solver.", "",
             "| Question type / kind | Total | Wrong |", "|---|---:|---:|"]
    ranked = sorted(groups.items(), key=lambda pair: (-sum(r["outcome"] == "wrong" for r in pair[1]), pair[0]))
    for key, values in ranked:
        lines.append(f"| {key} | {len(values)} | {sum(r['outcome'] == 'wrong' for r in values)} |")
    wrong = [r for r in rows if r["outcome"] == "wrong"]
    fixture_n = sum(r["type"] == "count" and question_class(r).split(" / ")[1] in
                    {"toilets", "washbasins", "bathtubs", "showers"} for r in wrong)
    lines += ["", f"{len(wrong)} wrong of {len(rows)} rows. Fixture counts share one reader path ({fixture_n} failures); "
              "room-label counts are the next shared path (tied with apartment areas). "
              "Individually, bathtubs rank first; toilets tie labelled rooms and apartment areas next.", "",
              "## Examples (up to two per failing class)", ""]
    for key, values in ranked:
        examples = [r for r in values if r["outcome"] == "wrong"][:2]
        if not examples:
            continue
        lines += [f"### {key}", ""]
        for r in examples:
            lines.append(f"- `{r['doc_id']}` — {r['question']} Gold: **{r['gold']}**; ours: **{r['value']}**.")
        if len(examples) == 1:
            lines.append("- Only one wrong example exists in this class.")
        lines.append("")
    lines += ["## Every wrong row", "", "| Document | Question | Gold | Ours |", "|---|---|---:|---:|"]
    lines += [f"| {r['doc_id']} | {r['question']} | {r['gold']} | {r['value']} |" for r in wrong]
    lines += ["", "## Code causes and scope", "",
              "- Fixtures: the old reader only kept closed FIXTURE polylines, discarded curves/blocks, "
              "and assigned every retained symbol kind=other. It discarded explicit layer/block types too. "
              "The solver then reported zero for unknown fixture types. Named symbols now retain their type; "
              "one INSERT counts once. Anonymous geometry stays unknown and the code solver abstains.",
              "- Rooms: the old reader used align_point whenever present, even for left/baseline TEXT; "
              "polygon attribution excluded boundary labels and took the first containing outline. "
              "TEXT placement, MTEXT, boundary coverage and nested outlines now have generated regressions. "
              "Explicit ROOM_TEXT counts also survive labels outside polygons; evidence cites the source labels.",
              "- All Swiss sample documents are held out; no Swiss drawings or plan maps were inspected to choose fixes. "
              "Only saved bench rows, source code and generated-for-demo DXFs were used in development. "
              "The frozen reader/solver is then evaluated once on the held-out rows. "
              "No room areas, fixture sizes, colour mappings, or document-specific overrides were fitted to gold.",
              "- Apartment membership/areas and untyped fixture classification remain data gaps. "
              "The general app's reader/forced-answer policies are outside this code-only evaluation.", ""]
    (OUT / "swiss-failures.md").write_text("\n".join(lines))


def main():
    rows = [json.loads(line) for line in ARCHIVE.read_text().splitlines()
            if json.loads(line)["source"] == "swiss_dwellings"]
    questions = [r for r in load_set("sample200") if r["source"] == "swiss_dwellings"]
    key = lambda r: (r["doc_id"], r["question"])
    assert Counter(map(key, questions)) == Counter(map(key, rows))
    held = set((ROOT / "data/sets/heldout_docs.txt").read_text().splitlines())
    held_n = len({r["doc_id"] for r in rows} & held)
    failure_report(rows)
    old_reader = old_module("pipeline/dxf_planmap.py", "pipeline._swiss_before")
    old_solver = old_module("engine/solvers/solve.py", "engine.solvers._swiss_before")
    all_results, conversion_errors = {}, {}
    with tempfile.TemporaryDirectory(prefix="swiss-e39-evaluation-") as temporary:
        for phase, reader, solver in [("before", old_reader.process, old_solver.solve), ("after", process, solve)]:
            root = Path(temporary) / phase
            root.mkdir()
            errors = {}
            for doc_id in sorted({r["doc_id"] for r in questions}):
                source = ROOT / "artifacts" / doc_id
                dest = root / doc_id
                dest.mkdir()
                for name in ("doc.json", "pages.json", "text-1.json"):
                    if (source / name).exists():
                        shutil.copyfile(source / name, dest / name)
                meta = json.loads((source / "doc.json").read_text())
                relative = meta["files"]["dxf"]
                paths = [ROOT / "data/junction-dataset-preview" / relative,
                         ROOT / "data/full/junction-dataset" / relative]
                path = next((p for p in paths if p.exists()), None)
                try:
                    if path is None:
                        raise FileNotFoundError(relative)
                    reader(doc_id, dest, path)
                except Exception as exc:
                    errors[doc_id] = f"{type(exc).__name__}: {exc}"

            def answer_fn(question, doc_ids, on_event):
                doc_id = doc_ids[0]
                if doc_id in errors:
                    raise RuntimeError(errors[doc_id])
                return solver(question, doc_id, root=root)

            result = run(questions, answer_fn=answer_fn, concurrency=1)
            all_results[phase] = result
            conversion_errors[phase] = errors
            (OUT / f"swiss-{phase}.rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                                                     for r in result["results"]))
    summary = {
        "row": "E-39", "set": "sample200 / swiss_dwellings", "baseline_commit": BASE,
        "heldout_documents_evaluated": held_n, "development_data": "generated for demo DXFs only",
        "method": "Frozen reader+code solver; rebuild both sides in temporary directories. No model layer imported or called. "
                  "Archived model-backed results shown separately; abstentions count as incorrect.",
        "archive": summarize(rows)["ALL x ALL"],
        "before": all_results["before"]["cells"]["ALL x ALL"],
        "after": all_results["after"]["cells"]["ALL x ALL"],
        "conversion_errors": conversion_errors,
        "cells": {phase: result["cells"] for phase, result in all_results.items()},
        "cost_usd": sum(result["totals"]["cost_usd"] for result in all_results.values()),
        "production_artifacts_modified": False,
    }
    before = {key(r): r for r in all_results["before"]["results"]}
    after = {key(r): r for r in all_results["after"]["results"]}
    summary["changed_rows"] = [{"doc_id": k[0], "question": k[1], "gold": before[k]["gold"],
                                "before": {f: before[k][f] for f in ("outcome", "value")},
                                "after": {f: after[k][f] for f in ("outcome", "value")}}
                               for k in before if any(before[k][f] != after[k][f] for f in ("outcome", "value"))]
    (OUT / "swiss-before-after.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: summary[k] for k in ("archive", "before", "after", "cost_usd", "conversion_errors")}, indent=2))


if __name__ == "__main__":
    main()
