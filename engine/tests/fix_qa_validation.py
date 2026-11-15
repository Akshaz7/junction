"""Reproduce F-FIX-QA checks without changing QA's runner or shared artifacts.

Run through scripts/heavy.sh. Private question files are never printed. Provider
dispatch is disabled; cached responses, if any, remain separately disclosed.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/final/FIX-QA"
PRIVATE = ROOT / ".fix-qa-private"
spec = importlib.util.spec_from_file_location("judge_hard", ROOT / "scripts/judge_hard.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("public", "bench", "final"))
    p.add_argument("--revision", default="HEAD")
    p.add_argument("--tag", required=True)
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    qa.OUT = OUT
    qa.HANDOFF = PRIVATE / "progress.md"
    qa.HANDOFF.touch(exist_ok=True)
    qa.private_state = lambda: {"directory": str(PRIVATE), "row_cap_usd": 3}
    os.environ["DATASET_ROOT"] = str(ROOT / "data/full/junction-dataset")
    if args.command == "bench":
        snapshot = PRIVATE / (args.tag + "-bench")
        snapshot.mkdir(exist_ok=True)
        sha = qa.snapshot(args.revision, snapshot)
        questions = [json.loads(l) for l in (ROOT / "data/sets/sample200.jsonl").read_text().splitlines()]
        artifacts = PRIVATE / "bench-artifacts"
        if not artifacts.exists():
            qa.artifact_copy([{"doc_ids": [q["doc_id"]]} for q in questions], artifacts)
        os.environ.update(ARTIFACTS_DIR=str(artifacts), MODELS_FAKE="1",
                          MODELS_CACHE_DIR=str(PRIVATE / "bench-cache"),
                          MODELS_COSTS_LOG=str(PRIVATE / "bench-costs.jsonl"), ANSWER_TIMEOUT_S="20")
        if not (snapshot / "data").exists():
            (snapshot / "data").symlink_to(ROOT / "data", target_is_directory=True)
        command = [sys.executable, "-m", "engine.bench", "--set", "sample200", "--fake",
                   "--tag", args.tag, "--max-usd", "3", "--concurrency", "2"]
        subprocess.run(command, cwd=snapshot, check=True)
        summary = json.loads((snapshot / f"results/bench/{args.tag}.json").read_text())
        rows = [json.loads(line) for line in (snapshot / f"results/bench/{args.tag}.rows.jsonl").read_text().splitlines()]
        result = {**summary, "results": rows}
        qa.write_json(OUT / (args.tag + "-sample200.json"),
                      {"commit": sha, "mode": "fake", "set": "sample200", **result})
        print(json.dumps({"totals": result["totals"], "overall": result["cells"].get("ALL x ALL")}))
        return
    if args.command == "final":
        # Copy the existing fixed holdout byte-for-byte only at final evaluation.
        state = json.loads((ROOT / "results/final/QA/private-state.json").read_text())
        shutil.copyfile(Path(state["directory"]) / "holdout.jsonl", PRIVATE / "holdout.jsonl")
        selection = json.loads((OUT / "selection.json").read_text())
        did = selection["reserved_doc_id"]
        raw = ROOT / "data/full/junction-dataset" / selection["raw_file"]
        reference = qa.raw_ifc(raw)
        meta = json.loads((ROOT / "artifacts" / did / "doc.json").read_text())
        cases = qa.doc_cases(did, meta, reference)
        for q in cases:
            q["split"] = "unseen"
        (PRIVATE / "unseen.jsonl").write_text("".join(json.dumps(q) + "\n" for q in cases))
        qa.write_json(OUT / "reserved-file.json", {"doc_id": did, "schema": reference.get("schema"),
                      "raw_sha256": qa.digest_file(raw), "authoring_tools": reference.get("authoring_tools"),
                      "unit_scale_m": reference.get("unit_scale_m")})
    opts = argparse.Namespace(input=qa.CASES, include_holdout=args.command == "final",
        include_unseen=args.command == "final", owner=None, limit=None, resume=None,
        revision=args.revision, mode="code", max_usd=0, timeout=20)
    report = qa.run(opts)
    qa.write_json(OUT / (args.tag + "-judge.json"), report)


if __name__ == "__main__":
    main()
