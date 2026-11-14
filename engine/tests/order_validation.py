"""Reproducible, model-free F-ORDER checks on real source files.

Run through scripts/heavy.sh. Writes only results/final/ORDER in this worktree.
The reserved end-only document is read after the other validation has finished.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

os.environ.update(MODELS_FAKE="1", EXPLAIN="0", READER="0", FORCE_ANSWER="0", VERIFY="0")

from engine import reasoning
from engine.answer import answer
from engine.order import answer_order
from engine.plainwords import apply
from engine.reasoning_parts import measured, found, confidence
from engine.solvers.data import load_doc

OUT = Path("results/final/ORDER")
ROOT = Path("artifacts").resolve()


def main():
    # Baseline functions run in memory; no source checkout or shared-file writes.
    modules = (measured, found, confidence)
    baselines, currents = [], []
    for module in modules:
        baseline = {"__name__": "baseline_part"}
        file = module.__name__.rsplit(".", 1)[-1]
        exec(subprocess.check_output(["git", "show", f"HEAD:engine/reasoning_parts/{file}.py"], text=True), baseline)
        baselines.append(baseline["run"])
        currents.append(module.run)
    groups = defaultdict(list)
    for line in Path("data/sets/sample200.jsonl").read_text().splitlines():
        row = json.loads(line)
        if (ROOT / row["doc_id"]).is_dir():
            groups[(row["source"], row["type"])].append(row)
    ordered = []
    while groups:
        for key in list(groups):
            ordered.append(groups[key].pop(0))
            if not groups[key]:
                del groups[key]
    review = []
    skipped = []
    for row in ordered:
        res = answer(row["question"], [row["doc_id"]])
        if res["answer"].get("abstained") or not res.get("reasoning"):
            skipped.append({"doc_id": row["doc_id"], "question": row["question"], "reason": "No supported source answer/card with model calls disabled."})
            continue
        for module, run in zip(modules, baselines):
            module.run = run
        try:
            before = reasoning.build(res, row["question"], ROOT)
        finally:
            for module, run in zip(modules, currents):
                module.run = run
        after = res["reasoning"]
        text = res["answer"]["text_md"]
        evidence_text = " ".join(s["text"] for s in after["steps"]) + " " + after["confidence"]["reason"]
        issues = []
        if re.search(r"\bIfc[A-Z]\w*", evidence_text):
            issues.append("IFC jargon")
        if len({s["kind"] for s in after["steps"]}) != len(after["steps"]):
            issues.append("duplicate evidence step")
        if not after["confidence"]["reason"].endswith("."):
            issues.append("reason is not a sentence")
        review.append({"doc_id": row["doc_id"], "source": row["source"], "type": row["type"], "question": row["question"],
                       "answer": text, "before_step_kinds": [s["kind"] for s in (before or {}).get("steps", [])],
                       "before_reasoning": before, "reasoning": after, "issues": issues, "cost_usd": res["cost"]["usd_total"]})
        if len(review) == 20:
            break
    (OUT / "sample200_cards.json").write_text(json.dumps({"reviewed": review, "unsupported_candidates": skipped}, indent=2, ensure_ascii=False) + "\n")
    assert len(review) == 20
    assert not any(r["issues"] for r in review)
    assert not any(r["cost_usd"] for r in review)

    from engine.tests.test_reasoning_measured import _ctx
    from engine.solvers.data import Item
    bathroom = Item("room-test", "room", label="Bathroom", q={"area_m2": 2.34}, polygon_px=[[0, 0], [100, 0], [100, 234], [0, 234]])
    ctx = _ctx(unit="count", value=1, ans={"text_md": "1 bathroom, 2.34 m²"}, cited=[bathroom], sc={"m_per_px": .01})
    before_ctx = copy.deepcopy(ctx)
    baselines[0](before_ctx)
    measured.run(ctx)
    regression = {"source": "unit-test fixture; not a real-file measurement", "before_steps": before_ctx["steps"], "after_steps": ctx["steps"]}
    (OUT / "bathroom_regression.json").write_text(json.dumps(regression, indent=2, ensure_ascii=False) + "\n")
    assert not before_ctx["steps"] and ctx["steps"][0]["kind"] == "measured"

    generality = []
    # Different origins: a building model, a CAD drawing, then the preselected unseen scan.
    candidates = []
    for source in ("ifc_bench", "swiss_dwellings"):
        candidates.append(next(r["doc_id"] for r in review if r["source"] == source))
    reserved = json.loads((OUT / "selection.json").read_text())["end_only_doc_id"]
    for index, did in enumerate(candidates + [reserved]):
        root = Path("data/vision_gen") if index == 2 else ROOT
        doc = load_doc(did, root)
        assert doc is not None
        checks = []
        for q in ("Order flooring for all rooms with 10% waste", "Order plasterboard for all rooms with 10% waste", "Order skirting for all rooms with 10% waste", "How many doors do I need to order?"):
            res = answer_order(q, doc, root=root)
            assert res is not None and res["cost"]["usd_total"] == 0
            reasoning.attach(res, q, root)
            apply(res)
            assert res.get("reasoning")
            assert "| Item | Quantity | Unit | Waste % | How measured | Source |" in res["answer"]["text_md"]
            if isinstance(res["answer"]["value"], (int, float)):
                assert res["citations"]
            if res["answer"]["value"] is None:
                assert res["reasoning"]["confidence"]["label"] != "Verified"
            checks.append({"question": q, "value": res["answer"]["value"], "text": res["answer"]["text_md"],
                           "citations": len(res["citations"]), "highlighted_items": len(res["evidence"]["scene"]["highlight_item_ids"]), "confidence": res["reasoning"]["confidence"]})
        generality.append({"doc_id": did, "mode": doc.mode, "end_only": index == 2, "checks": checks})
    (OUT / "real_files.json").write_text(json.dumps(generality, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"cards_reviewed": len(review), "issues": sum(len(r["issues"]) for r in review), "unsupported_candidates": len(skipped),
                      "real_files": len(generality), "real_order_questions": sum(len(r["checks"]) for r in generality), "end_only_doc_id": reserved, "live_cost_usd": 0}))


if __name__ == "__main__":
    main()
