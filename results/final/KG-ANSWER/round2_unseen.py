"""End-only regression on the randomly reserved, previously unopened IFC.

Uses round 1's independent IFC relationship truth reader. Run via heavy.sh.
No tuning or product-code changes follow this evaluation.
"""
import importlib.util
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kg_answer_real_eval", OUT / "evaluate.py")
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)
selection = json.loads((OUT / "round2-selection.json").read_text())
source = Path(selection["random_unseen_path"])
did = source.parent.name + "__" + re.sub(r"[^a-z0-9]+", "-", source.stem.lower()).strip("-")
questions = evaluator.ifc_truth(did)
evaluator.write("round2-unseen-questions.json", questions)
reports = evaluator.evaluate([questions])
evaluator.write("round2-unseen-results.json", reports)
for report in reports:
    print(did, report["passed"], "/", report["total"], "build", report["build_s"], "s")
    for q in report["questions"]:
        if not q["pass"]:
            print("FAIL", q["question"], q["error"])
