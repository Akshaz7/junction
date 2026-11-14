"""Read-only local timing probe; run via scripts/heavy.sh, never writes shared artifacts.

Usage: python results/final/PERF/measure.py before|after [--validation]
"""
import cProfile
import io
import json
import os
from pathlib import Path
import pstats
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).parent
ART = ROOT / "artifacts"
os.environ.update(MODELS_FAKE="1", EXPLAIN="0", ARTIFACTS_DIR=str(ART))
scratch = tempfile.TemporaryDirectory(prefix="f-perf-")
os.environ.update(MODELS_CACHE_DIR=scratch.name + "/models", MODELS_COSTS_LOG=scratch.name + "/costs.jsonl")

from engine.answer import answer
from engine.reader.tools import Session
from engine.solvers.data import load_doc
from engine.project_index import Index

# Index refresh normally persists newly discovered uploads. Timing must not
# rewrite the shared artifact index used by other workers.
Index.save = lambda *args, **kwargs: None


def clock(fn):
    t = time.perf_counter()
    value = fn()
    return value, round((time.perf_counter() - t) * 1000, 3)


def ask(ids, question):
    events = []
    t = time.perf_counter()
    def emit(kind, payload):
        events.append((kind, round((time.perf_counter() - t) * 1000, 3)))
    res, ms = clock(lambda: answer(question, ids, emit))
    return {"question": question, "doc_ids": ids, "final_ms": ms,
            "first_status_ms": next((ms for k, ms in events if k == "status"), None),
            "first_answer_token_ms": next((ms for k, ms in events if k in ("answer.delta", "answer.partial")), None),
            "value": res["answer"]["value"], "abstained": res["answer"]["abstained"],
            "cost_usd": res["cost"]["usd_total"], "citation_count": len(res["citations"]),
            "route": res["route"], "event_count": len(events)}


def measure(did):
    doc, cold = clock(lambda: load_doc(did, ART))
    _, warm = clock(lambda: load_doc(did, ART))
    session = Session([did], ART)
    obs, tool_cold = clock(lambda: session.run("ifc", {"doc": "d1", "kind": "door"}))
    _, tool_warm = clock(lambda: session.run("ifc", {"doc": "d1", "kind": "door"}))
    glb = ART / did / "scene.glb"
    return {"doc_id": did, "items": len(doc.items), "elements_bytes": (ART / did / "elements.json").stat().st_size,
            "scene_glb_bytes": glb.stat().st_size if glb.exists() else None,
            "ingest_conversion_ms": None, "ingest_note": "Already converted; shared artifacts left unchanged",
            "load_first_ms": cold, "load_repeat_ms": warm, "reader_ifc_first_ms": tool_cold,
            "reader_ifc_repeat_ms": tool_warm, "reader_observation_first_line": obs.splitlines()[0],
            "answer": ask([did], "How many doors are in this model?")}


phase = sys.argv[1]
selected = json.loads((OUT / "selection.json").read_text())["validation_only_doc_id"]
files = sorted(ART.glob("*/elements.json"), key=lambda p: p.stat().st_size, reverse=True)
# General largest-index selection, reserving the random file until final validation.
ids = [p.parent.name for p in files if p.parent.name != selected][:10]
extra = [p.parent.name for p in files if any(k in p.parent.name for k in ("bsc-esplanades", "resbim-388"))]
cases = list(dict.fromkeys(ids[:3] + extra))
if "--validation" in sys.argv:
    cases.append(selected)
report = {"phase": phase, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          "mode": "Real artifact data, fake models, explanations disabled; Python engine entry point (no HTTP)",
          "first_token_note": "Null means the code route emits no answer text before returning its final answer",
          "documents": []}
for did in cases:
    row = measure(did)
    report["documents"].append(row)
    print(json.dumps(row), flush=True)
profile = cProfile.Profile()
profile.enable()
report["multi_document"] = ask(ids, "How many doors are there across all models?")
profile.disable()
buf = io.StringIO()
pstats.Stats(profile, stream=buf).strip_dirs().sort_stats("cumtime").print_stats(18)
report["profile"] = buf.getvalue()
report["max_rss_bytes"] = __import__("resource").getrusage(__import__("resource").RUSAGE_SELF).ru_maxrss
path = OUT / "timings.json"
saved = json.loads(path.read_text()) if path.exists() else {}
saved[phase] = report
path.write_text(json.dumps(saved, indent=2) + "\n")
print(json.dumps(report["multi_document"]), flush=True)
print(report["profile"], flush=True)
