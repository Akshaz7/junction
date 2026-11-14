"""Live reader timing; specify arbitrary real document ids after before|after.

Only engine.models.call invokes a provider. Cost logs/model cache use a private
temporary directory. Inputs are read-only; output includes evidence item counts.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
scratch = tempfile.TemporaryDirectory(prefix="f-perf-reader-")
os.environ.update(MODELS_FAKE="0", MODELS_CACHE_DIR=scratch.name + "/models",
                  MODELS_COSTS_LOG=scratch.name + "/costs.jsonl")
from engine.reader.agent import read_answer
from engine.models import providers as P
from server.schema import validate_answer

phase, ids = sys.argv[1], sys.argv[2:]
if phase == "before":
    baseline_commit = json.loads((Path(__file__).parent / "selection.json").read_text())["baseline_commit"]
    namespace = {"__name__": "perf_baseline_reader", "__file__": str(ROOT / "engine/reader/agent.py")}
    exec(compile(subprocess.check_output(["git", "show", f"{baseline_commit}:engine/reader/agent.py"], cwd=ROOT),
                 namespace["__file__"], "exec"), namespace)
    read_answer = namespace["read_answer"]
events, snapshots, tokens = [], [], []
started = time.perf_counter()


def emit(kind, payload):
    events.append({"kind": kind, "ms": round((time.perf_counter() - started) * 1000, 3)})
    if kind == "answer.partial":
        validate_answer(payload)
        snapshots.append({"text": payload["answer"]["text_md"], "value": payload["answer"]["value"],
                          "citations": len(payload["citations"]), "cost_usd": payload["cost"]["usd_total"]})


token = P.DELTA_SINK.set(lambda txt: tokens.append(round((time.perf_counter() - started) * 1000, 3)))
try:
    result = read_answer("How many doors are there in each of the first two models? Use the IFC tool for both and cite the two separate counts.",
                         ids, ROOT / "artifacts", on_event=emit)
finally:
    P.DELTA_SINK.reset(token)
validate_answer(result)
report = {"phase": phase, "models": "live", "doc_ids": ids, "events": events, "snapshots": snapshots,
          "first_status_ms": next((e["ms"] for e in events if e["kind"] == "status"), None),
          "first_finding_ms": next((e["ms"] for e in events if e["kind"] == "answer.partial"), None),
          "first_final_token_ms": tokens[0] if tokens else None, "final_ms": round((time.perf_counter() - started) * 1000, 3),
          "answer": result["answer"], "cost": result["cost"], "citations": len(result["citations"])}
(Path(__file__).parent / f"reader-{phase}.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report), flush=True)
