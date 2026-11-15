"""Read-only real-data checks for ACC-VECTOR; not an automatic pytest test.

Run through scripts/heavy.sh. Requires the ACC forbidden list, filters every
document before opening it, and writes plan maps ONLY in a temporary directory.
``--blind`` opens the files reserved in selection.json, only after development.
No training or live model calls. No PDF reader or shared artifact writes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import types
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path):
    return json.loads(path.read_text())


def _write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def real_files(selection, forbidden, out, baseline_ref, blind=False):
    import ezdxf
    from pipeline import dxf_planmap, pages
    from engine.bench import score
    from engine.solvers import solve
    code = subprocess.check_output(["git", "show", f"{baseline_ref}:pipeline/dxf_planmap.py"], cwd=ROOT, text=True)
    legacy = types.ModuleType("acc_vector_baseline")
    legacy.__file__ = str(ROOT / "pipeline/dxf_planmap.py")
    exec(compile(code, legacy.__file__, "exec"), legacy.__dict__)
    cases = ([selection["blind"], selection["additional_blind"]] if blind
             else selection["development_candidates"][:12] + selection["other_origin_development"])
    ids = {c["doc_id"] for c in cases}
    if ids & forbidden:
        raise ValueError("Selected file violates benchmark exclusion; no source opened")
    questions = []
    with (ROOT / "data/sets/questions_en.full.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            if row["doc_id"] in ids and row.get("type") == "count" and any(
                    word in row["question"].lower() for word in ("toilet", "sink", "shower", "bathtub", "door", "window")):
                questions.append(row)
    records = []
    with tempfile.TemporaryDirectory(prefix="acc-vector-real-") as scratch:
        roots = [Path(scratch) / "before", Path(scratch) / "after"]
        for case in cases:
            path = ROOT / case["path"]
            doc = ezdxf.readfile(path)
            _, _, _, w, h = pages.dxf_frame(pages.dxf_lines(doc))
            counts = []
            for root, converter in zip(roots, (legacy.process, dxf_planmap.process)):
                art = root / case["doc_id"]
                art.mkdir(parents=True)
                _write(art / "pages.json", {"source": "dxf", "pages": [{"w": w, "h": h}]})
                counts.append(converter(case["doc_id"], art, path)["counts"])
            items = _read(roots[1] / case["doc_id"] / "planmap-1.json")["items"]
            checks = []
            for row in questions:
                if row["doc_id"] != case["doc_id"]:
                    continue
                pair = [solve(row["question"], case["doc_id"], root=root) for root in roots]
                checks.append({"question": row["question"], "gold": row["answer"],
                               "before": {"value": pair[0]["answer"]["value"], "outcome": score(row, pair[0])},
                               "after": {"value": pair[1]["answer"]["value"], "outcome": score(row, pair[1]),
                                         "boxes": len(pair[1]["evidence"]["boxes"])}})
            records.append({**case, "units_code": int(doc.units), "before": counts[0], "after": counts[1],
                            "uncertain_symbols": sum(i["props"].get("classification") == "unknown" for i in items),
                            "fixture_classifications": dict(Counter(i["props"].get("classification") for i in items if i["kind"] not in ("room", "wall", "text") and i["props"].get("role") != "unit")),
                            "questions": checks})
    result = {"phase": "blind" if blind else "development", "baseline_ref": baseline_ref, "files": records,
              "files_checked": len(records), "dataset_origins": sorted({r["source"] for r in records}),
              "before_correct": sum(q["before"]["outcome"] == "correct" for r in records for q in r["questions"]),
              "after_correct": sum(q["after"]["outcome"] == "correct" for r in records for q in r["questions"]),
              "questions": sum(len(r["questions"]) for r in records)}
    _write(out / (result["phase"] + ".json"), result)
    print({k: v for k, v in result.items() if k != "files"}, flush=True)


def sample200(forbidden, out, baseline_ref):
    """Use fresh identical-input ingestion in both arms; no artifact drift."""
    import shutil
    from engine.bench import run
    from engine.answer import answer
    from pipeline.dxf_planmap import process
    rows = [json.loads(line) for line in (ROOT / "data/sets/sample200.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["doc_id"] not in forbidden]
    code = subprocess.check_output(["git", "show", f"{baseline_ref}:pipeline/dxf_planmap.py"], cwd=ROOT, text=True)
    legacy = types.ModuleType("acc_vector_sample_baseline")
    legacy.__file__ = str(ROOT / "pipeline/dxf_planmap.py")
    exec(compile(code, legacy.__file__, "exec"), legacy.__dict__)
    summaries = {}
    with tempfile.TemporaryDirectory(prefix="acc-vector-sample-") as scratch:
        for arm, converter in (("before", legacy.process), ("after", process)):
            root = Path(scratch) / arm
            root.mkdir()
            os.environ["ARTIFACTS_DIR"] = str(root)
            os.environ["MODELS_CACHE_DIR"] = str(Path(scratch) / "model-cache")
            os.environ["MODELS_LOG_PATH"] = str(Path(scratch) / "model-log.jsonl")
            for did in sorted({r["doc_id"] for r in rows}):
                source = ROOT / "artifacts" / did
                target = root / did
                meta = _read(source / "doc.json")
                if meta.get("files", {}).get("dxf") and did.startswith("swiss_dwellings__"):
                    target.mkdir()
                    for path in source.iterdir():
                        if path.name != "planmap-1.json":
                            (target / path.name).symlink_to(path.resolve(), target_is_directory=path.is_dir())
                    converter(did, target, ROOT / "data/full/junction-dataset" / meta["files"]["dxf"])
                else:
                    target.symlink_to(source.resolve(), target_is_directory=True)
            result = run(rows, concurrency=1, max_usd=.01)
            _write(out / f"sample200-{arm}-fresh.json", result)
            summaries[arm] = result["cells"]["ALL x ALL"]
            if arm == "after":
                prior = _read(out / "sample200-before-fresh.json")
                bm = {(r["doc_id"], r["question"]): r for r in prior["results"]}
                changed = [r for r in result["results"] if r["outcome"] != bm[r["doc_id"], r["question"]]["outcome"]]
                evidence = []
                for row in changed:
                    response = answer(row["question"], [row["doc_id"]])
                    if row["outcome"] == "correct":
                        assert len(response["evidence"]["boxes"]) == response["answer"]["value"]
                        assert response["reasoning"]["confidence"]["label"] == "Estimate"
                    evidence.append(response)
                _write(out / "sample200-evidence.json", evidence)
                summaries["correct_to_wrong"] = sum(bm[r["doc_id"], r["question"]]["outcome"] == "correct"
                                                     and r["outcome"] != "correct" for r in result["results"])
    _write(out / "sample200-summary.json", summaries)
    print(summaries, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forbidden", type=Path, required=True)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "results/final/ACC-VECTOR")
    parser.add_argument("--phase", choices=("development", "blind", "sample200"), required=True)
    args = parser.parse_args()
    if os.environ.get("MODELS_FAKE") != "1":
        raise ValueError("MODELS_FAKE=1 is required")
    forbidden = {s.strip() for s in args.forbidden.read_text().splitlines() if s.strip() and not s.startswith("#")}
    if args.phase == "sample200":
        sample200(forbidden, args.out, args.baseline_ref)
    else:
        real_files(_read(args.out / "selection.json"), forbidden, args.out, args.baseline_ref, args.phase == "blind")


if __name__ == "__main__":
    main()
