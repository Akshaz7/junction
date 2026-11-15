"""Read-only PDF room and sample200 checks; all side effects stay in a private snapshot."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


def pdf_rooms(paths: list[Path], output: Path, baseline: str):
    from engine.analytics import filtered_question
    from engine.solvers.data import load_doc
    from engine.solvers.filters import fold, room_filter
    from pipeline import pdf_planmap, pdf_rooms, pdf_vector

    namespace = {"__package__": "engine.solvers"}
    source = subprocess.check_output(["git", "show", f"{baseline}:engine/solvers/filters.py"], text=True)
    exec(compile(source, "baseline_filters.py", "exec"), namespace)
    previous = namespace["room_filter"]
    type_requests = {"kitchen": "kitchen", "bathroom": "bathroom", "wc": "bathroom",
                     "hall": "corridor", "living": "living room", "bedroom": "bedroom",
                     "office": "office", "storage": "storage", "balcony": "balcony",
                     "laundry": "laundry room", "dining": "dining room", "stairs": "stairs"}
    reports = []
    for path in paths:
        print(f"Reading {path}", flush=True)
        page = pdf_vector.load_page(path, 0)
        assert not pdf_vector.is_scanned(page), path
        walls = pdf_vector.walls(page)
        extracted = pdf_rooms.rooms(page, walls)
        scale = pdf_rooms.scale(page, extracted)
        assert scale and scale.get("m_per_pt"), (path, "no verified scale")
        pm = pdf_planmap.build("pdf-validation", 1, round(page["W_pt"] * 2), round(page["H_pt"] * 2),
                               page, walls, extracted, [], scale)
        with tempfile.TemporaryDirectory(prefix="pdfspaces-rooms-") as temp:
            root = Path(temp)
            docdir = root / "pdf-validation"
            docdir.mkdir()
            (docdir / "doc.json").write_text(json.dumps({"kind": "pdf", "formats": ["pdf"]}))
            (docdir / "planmap-1.json").write_text(json.dumps(pm))
            doc = load_doc("pdf-validation", root)
            assert doc is not None
        rooms = [r for r in doc.items if r.kind == "room"]
        assert rooms, (path, "no indexed rooms")
        queries = []
        for r in rooms:
            label, number = r.label, r.props.get("number")
            if label and fold(label) not in {"room", "rooms", "space", "spaces"}:
                expected = [i for i in rooms if i.label and re.search(rf"(?<!\w){re.escape(fold(label))}(?!\w)", fold(i.label))]
                # Source type names can legitimately select translated/typed rooms too.
                # Use full drawn-name checks only for non-type, unique names below.
                if not any(fold(label) == fold(k) for k in type_requests):
                    queries.append((f"What is the area of {label}?", expected, "drawn label"))
            if number:
                for num in str(number).split(" / "):
                    same_number = [i for i in rooms if num in str(i.props.get("number") or "").split(" / ")]
                    queries.append((f"What is the area of room {num}?", same_number, "source number"))
                    if label and fold(label) not in {"room", "rooms", "space", "spaces"} and len(str(number).split(" / ")) == 1:
                        same_name = [i for i in same_number if i.label and re.search(rf"(?<!\w){re.escape(fold(label))}(?!\w)", fold(i.label))]
                        queries.append((f"What is the area of {label} {num}?", same_name, "source name and number"))
                    target = type_requests.get(r.props.get("room_type"))
                    if target:
                        same_type = [i for i in same_number if type_requests.get(i.props.get("room_type")) == target]
                        queries.append((f"Where is {target} {num}?", same_type, "translated producer type and number"))
        # Independent expectations use only the producer's documented room_type values.
        for typed in sorted({r.props.get("room_type") for r in rooms} & type_requests.keys()):
            target = type_requests[typed]
            expected = [r for r in rooms if type_requests.get(r.props.get("room_type")) == target]
            # Merged producer labels may contain several room types while exposing one
            # room_type. Avoid asserting an invented split or incomplete typed total.
            if any(" / " in (r.label or "") for r in rooms):
                continue
            queries.append((f"What is the area of {target}?", expected, "producer type"))
        unique = {}
        for question, expected, kind in queries:
            if question in unique:
                assert sorted(i.item_id for i in unique[question][0]) == sorted(i.item_id for i in expected)
            else:
                unique[question] = (expected, kind)
        queries = [(q, expected, kind) for q, (expected, kind) in unique.items()]
        checks = []
        for question, expected, kind in queries:
            ids = lambda result: sorted(r.item_id for r in result[1]) if result is not None else None
            before, after = previous(question, rooms), room_filter(question, rooms)
            expected_ids = sorted(i.item_id for i in expected)
            checks.append({"question": question, "kind": kind, "expected": expected_ids,
                           "before": ids(before), "after": ids(after),
                           "before_pass": ids(before) == expected_ids, "after_pass": ids(after) == expected_ids})
        # The real answer path must cite exactly the selected source rooms and boxes.
        evidence = []
        for check in checks:
            if not check["after_pass"] or not check["expected"]:
                continue
            result = filtered_question(check["question"], doc, time.perf_counter())
            if result is None:
                continue
            cited = sorted({iid for c in result["citations"] for iid in c["item_ids"]})
            boxed = sorted(b["item_id"] for b in result["evidence"]["boxes"])
            assert cited == check["expected"] == boxed, (path, check, cited, boxed)
            evidence.append({"question": check["question"], "item_ids": cited, "value": result["answer"]["value"],
                             "cost_usd": result["cost"]["usd_total"]})
        report = {"pdf": str(path), "page": 1, "vector_paths": len(page["paths"]), "indexed_rooms": len(rooms),
                  "source": "pdf_vector", "scale": scale, "checks": checks, "evidence": evidence,
                  "before_pass": sum(c["before_pass"] for c in checks),
                  "after_pass": sum(c["after_pass"] for c in checks), "total": len(checks)}
        reports.append(report)
        print(json.dumps({k: v for k, v in report.items() if k not in {"checks", "evidence", "scale"}}), flush=True)
    output.write_text(json.dumps({"baseline": baseline, "documents": reports}, indent=2) + "\n")
    assert all(r["after_pass"] == r["total"] for r in reports), "See recorded failed checks"


def sample(output: Path, snapshot: Path | None):
    os.environ["MODELS_FAKE"] = "1"
    from engine import bench
    questions = bench.load_set("sample200")
    if snapshot is None:
        snapshot = Path(tempfile.mkdtemp(prefix="pdfspaces-sample-"))
        for did in {q["doc_id"] for q in questions}:
            src, dst = Path("artifacts") / did, snapshot / did
            if not src.is_dir():
                continue
            dst.mkdir()
            for p in src.iterdir():
                if p.suffix == ".json":
                    shutil.copyfile(p, dst / p.name)
                elif p.suffix in {".png", ".glb"}:
                    (dst / p.name).symlink_to(p.resolve())
    os.environ.update(ARTIFACTS_DIR=str(snapshot), MODELS_CACHE_DIR=str(snapshot / "cache"),
                      MODELS_COSTS_LOG=str(snapshot / "costs.jsonl"))
    result = bench.run(questions, concurrency=2)
    result["snapshot"] = str(snapshot)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"totals": result["totals"], "scores": result["cells"]["ALL x ALL"], "snapshot": str(snapshot)}))


def compare(paths: list[Path], output: Path):
    before, after = [json.loads(p.read_text()) for p in paths]
    key = lambda row: (row["doc_id"], row["question"])
    old = {key(r): r for r in before["results"]}
    new = {key(r): r for r in after["results"]}
    assert old.keys() == new.keys()
    assert before["snapshot"] == after["snapshot"], "Compare the same isolated source snapshot"
    changes = [{"doc_id": did, "question": q, "before": old[(did, q)]["outcome"],
                "after": new[(did, q)]["outcome"]} for did, q in old
               if old[(did, q)]["outcome"] != new[(did, q)]["outcome"]]
    result = {"questions": len(old), "before": before["cells"]["ALL x ALL"],
              "after": after["cells"]["ALL x ALL"], "changes": changes,
              "correct_to_wrong": sum(c["before"] == "correct" and c["after"] == "wrong" for c in changes),
              "lost_correct": sum(c["before"] == "correct" for c in changes),
              "cost_usd": before["totals"]["cost_usd"] + after["totals"]["cost_usd"]}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    assert result["lost_correct"] == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--pdf", nargs="+", type=Path)
    parser.add_argument("--baseline", default="2ba8777")
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.sample:
        sample(args.output, args.snapshot)
    if args.pdf:
        pdf_rooms(args.pdf, args.output, args.baseline)
    if args.compare:
        compare(args.compare, args.output)


if __name__ == "__main__":
    main()
