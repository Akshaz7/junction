"""Local real-file ingest/answer measurement. Run via scripts/heavy.sh /usr/bin/time -l.

Source files stay read-only; all derived files go to this worktree's .scratch.
No live model calls. The CLI accepts any IFC; there are no document-specific paths.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("label")
    parser.add_argument("--end-only", action="store_true")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    root = base / ".scratch" / args.label
    doc_id = "uploads__validation"
    out = root / doc_id
    if out.exists():
        import shutil
        shutil.rmtree(out)  # only this runner's private worktree scratch directory
    out.mkdir(parents=True, exist_ok=True)
    source = args.file.resolve()
    meta = {"doc_id": doc_id, "kind": "ifc", "files": {"ifc": str(source)},
            "title": "Local IFC validation", "formats": ["ifc"], "licence": "local validation only"}
    (out / "doc.json").write_text(json.dumps(meta))
    os.environ.update(ARTIFACTS_DIR=str(root), INGEST_MODE="vlm", MODELS_FAKE="1", HEAVY_SLOT_HELD="1",
                      MODELS_CACHE_DIR=str(root / "model-cache"), MODELS_COSTS_LOG=str(root / "costs.jsonl"))
    from server.ingest_job import run
    start = time.perf_counter()
    status = run(doc_id)
    elapsed = time.perf_counter() - start
    state = json.loads((out / "ingest.json").read_text())
    record = {"file": str(args.file), "size_bytes": source.stat().st_size, "end_only": args.end_only,
              "status": status, "ingest_s": round(elapsed, 3), "state": state,
              "validation_note": "Only code answers without model calls are verified here. Fake-provider fallbacks are not source observations."}
    if (out / "elements.json").is_file():
        index = json.loads((out / "elements.json").read_text())
        record.update(schema=index["schema"], applications=index["building"].get("applications"),
                      elements=len(index["elements"]), kinds=dict(Counter(e["kind"] for e in index["elements"])),
                      rooms_with_area=sum(e["kind"] == "room" and "area_m2" in e["quantities"] for e in index["elements"]))
        from server.chats_routes import _selected_engine
        from server.schema import validate_answer
        questions = ["How many doors are there?", "How many windows are there?", "What is the total floor area of all rooms?"]
        answers = []
        for question in questions:
            answer = _selected_engine(question, [doc_id], lambda *a: None)
            validate_answer(answer)
            answers.append({"question": question, "answer": answer["answer"], "cost": answer["cost"],
                            "reasoning": answer.get("reasoning"),
                            "citations": len(answer["citations"]),
                            "cited_item_count": len({i for c in answer["citations"] for i in c.get("item_ids", [])})})
        record["answers"] = answers
    else:
        from server.chats_routes import _no_data_answer
        answer = _no_data_answer("How many doors are there?", [doc_id])
        record["failure_answer"] = answer["answer"] if answer else None
    cgroup = Path("/sys/fs/cgroup")
    if (cgroup / "memory.peak").is_file():
        record["container"] = {"limit_bytes": int((cgroup / "memory.max").read_text()),
                               "peak_bytes": int((cgroup / "memory.peak").read_text()),
                               "events": {k: int(v) for k, v in (line.split() for line in (cgroup / "memory.events").read_text().splitlines())}}
    report = base / f"{args.label}.json"
    report.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
