"""Read-only integration check against the wall-area module already on main.

The calculation branch predates that module. Load its committed code for this
check without merging branches or changing a shared worktree. Run via heavy.sh.
"""
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

os.environ["MODELS_FAKE"] = "1"

from engine.calc import attach, validate


def committed_module(name, path):
    module = types.ModuleType(name)
    module.__file__ = str(Path(path).resolve())
    sys.modules[name] = module
    contents = subprocess.check_output(["git", "show", "main:" + path], text=True)
    exec(compile(contents, module.__file__, "exec"), module.__dict__)
    return module


def run():
    if importlib.util.find_spec("engine.reasoning_parts.wallarea_steps") is None:
        committed_module("engine.reasoning_parts.wallarea_steps", "engine/reasoning_parts/wallarea_steps.py")
    wallarea = committed_module("calc_wallarea_audit_source", "engine/wallarea.py")
    cases = [
        ("ifc_bench__ac20-arc", "What is the net wall area per floor?"),
        ("ifc_bench__ac20-arc", "What is the facade area of the ground floor?"),
        ("ifc_bench__ac20-arc", "How many plasterboard sheets 1200 x 2400 mm with 10% waste?"),
        ("ifc_bench__ac20-arc", "What is the gross wall surface area?"),
        ("cubicasa5k__colorful-11397", "What is the net wall surface area?"),
    ]
    reports = []
    root = Path("artifacts")
    for did, q in cases:
        res = wallarea.answer(q, [did], root)
        if res is None:
            reports.append({"doc_id": did, "question": q, "routed": False})
            continue
        res = attach(res, q, root)
        c = res.get("reasoning", {}).get("calc", {})
        reports.append({"doc_id": did, "question": q, "routed": True, "value": res["answer"]["value"],
                        "rows": len(c.get("rows", [])), "complete": c.get("status") == "complete", "issues": validate(c, root) if c else ["no calculation"]})
    out = {"upstream_commit": subprocess.check_output(["git", "rev-parse", "main"], text=True).strip(),
           "method": "Executed committed main module read-only; no source artifacts or other worktrees modified", "answers": reports}
    Path("results/final/CALC/wallarea.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__": run()
