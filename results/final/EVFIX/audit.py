"""Reproducible, offline evidence-card audit. Run via scripts/heavy.sh.

before reserves the unseen file; after tests it for the first time and compares
its card to the original code loaded from git (no source checkout).
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
BASE = "6e0419f0c902ef2ecc951e6fb22cc70c65edcda9"
SCRATCH = Path(tempfile.gettempdir()) / "junction-f-evfix-audit"
SCRATCH.mkdir(exist_ok=True)
os.environ.update(MODELS_FAKE="1", EXPLAIN="0", RECOUNT="0", READER="0",
                  ANSWER_TIMEOUT_S="0", MODELS_CACHE_DIR=str(SCRATCH / "cache"),
                  MODELS_COSTS_LOG=str(SCRATCH / "costs.jsonl"), RESULTS_DIR=str(SCRATCH))


def inventory(res):
    return dict(value=res["answer"].get("value"), unit=res["answer"].get("unit"),
                boxes=len(res.get("evidence", {}).get("boxes", [])),
                cited_items=len({(c.get("doc_id"), i) for c in res.get("citations", []) for i in c.get("item_ids", [])}),
                citation_groups=len(res.get("citations", [])))


def issues(res):
    """Independent semantic checks, rather than comparing unrelated numbers (pages, areas, floors)."""
    inv = inventory(res)
    v = inv["value"]
    if inv["unit"] != "count" or not isinstance(v, (int, float, dict)):
        return []
    total = sum(v.values()) if isinstance(v, dict) else v
    steps = (res.get("reasoning") or {}).get("steps", [])
    text = " ".join(s.get("text", "") for s in steps)
    bad = []
    if res["answer"].get("abstained"):
        return []
    if not steps:
        bad.append("count has no evidence card")
    for s in steps:
        t = s.get("text", "")
        if re.search(r"\d+ marked regions?", t):
            bad.append("citation groups described as findings")
        m = re.search(r"(?:kept(?: the)?|matches the) (\d+) boxed", t)
        if m and int(m[1]) != inv["boxes"]:
            bad.append("Checked step reports a different boxed count")
        if s.get("kind") == "found" and "each one numbered" in t:
            nums = re.findall(r"(?:^| and )(\d+) (?:\w+ )?(?:doors?|windows?|rooms?|walls?|elements?|toilets?|sinks?|slabs?)\b", t)
            if nums and sum(map(int, nums)) != inv["boxes"]:
                bad.append("Found claims every item is numbered but boxes differ")
    if total != inv["boxes"] and not re.search(r"(?:not boxed|no numbered|without.*box|not.*numbered|not all.*boxed|box.*unavailable|box.*missing|boxes.*shown|only.*boxed|boxed.*of)", text, re.I):
        bad.append("headline and boxes differ without a coverage explanation")
    if inv["cited_items"] and total != inv["cited_items"] and not re.search(r"(?:citations?|cited|linked|item links|source.*total|source.*count)", text, re.I):
        bad.append("headline and linked items differ without an explanation")
    return sorted(set(bad))


def record(row, res):
    return dict(**row, **inventory(res), headline=res["answer"].get("text_md"),
                card=res.get("reasoning"), issues=issues(res),
                abstained=res["answer"].get("abstained"), cost_usd=res.get("cost", {}).get("usd_total", 0))


@contextlib.contextmanager
def original_reasoning():
    import engine
    import engine.reasoning_parts as parts
    names = ["engine.reasoning"] + ["engine.reasoning_parts." + n for n in ("found", "measured", "checked", "confidence")]
    saved = {n: sys.modules.get(n) for n in names}
    attrs = {n: getattr(parts, n, None) for n in ("found", "measured", "checked", "confidence")}
    old = getattr(engine, "reasoning", None)
    try:
        for name in names:
            source = subprocess.check_output(["git", "show", f"{BASE}:{name.replace('.', '/')}.py"], cwd=ROOT, text=True)
            mod = types.ModuleType(name)
            mod.__package__ = name.rsplit(".", 1)[0]
            sys.modules[name] = mod
            exec(compile(source, name, "exec"), mod.__dict__)
            if name == "engine.reasoning":
                engine.reasoning = mod
            else:
                setattr(parts, name.rsplit(".", 1)[1], mod)
        yield sys.modules["engine.reasoning"]
    finally:
        engine.reasoning = old
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod
        for n, mod in attrs.items():
            if mod is None:
                delattr(parts, n)
            else:
                setattr(parts, n, mod)


def main():
    from engine.answer import answer
    from engine import reasoning
    import jsonschema
    selection = json.loads((OUT / "selection.json").read_text())
    rows = selection["questions"]
    phase = sys.argv[1]
    path = OUT / "before.json"
    if phase == "before":
        with original_reasoning():
            records = [record(r, answer(r["question"], [r["doc_id"]])) for r in rows if not r.get("reserved_unseen")]
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"tested": len(records), "cards_with_issues": sum(bool(r["issues"]) for r in records)}))
        return
    before = json.loads(path.read_text())
    after = []
    schema = json.loads((ROOT / "server/schemas/answer.schema.json").read_text())
    for row in rows:
        res = answer(row["question"], [row["doc_id"]])
        jsonschema.validate(res, schema)
        after.append(record(row, res))
        if row.get("reserved_unseen"):
            copy = json.loads(json.dumps(res))
            copy.pop("reasoning", None)
            with original_reasoning() as old:
                copy = old.attach(copy, row["question"], ROOT / "artifacts")
            before.append(record(row, copy))
    # Reproduce the original transient-box failure without a live model call.
    regression = {"doc_ids": [], "route": "planmap", "answer": {"text_md": "There are **6 doors** on this floor plan. [1]",
                  "value": 6, "unit": "count", "confidence": 0.5},
                  "citations": [{"n": 1, "item_ids": [f"vision-{i}" for i in range(6)]}],
                  "evidence": {"boxes": [{"item_id": f"vision-{i}", "label": str(i + 1), "bbox_px": [i * 2, 0, i * 2 + 1, 1]} for i in range(6)]},
                  "trace": [{"step": "recount", "detail": "plan map 4, drawing re-read 6: replaced by 6 vision-drawn boxes"}]}
    legacy = json.loads(json.dumps(regression))
    with original_reasoning() as old:
        old.attach(legacy, "How many doors?", ROOT / "artifacts")
    reasoning.attach(regression, "How many doors?", ROOT / "artifacts")
    has_contradiction = lambda r: any(i != "count has no evidence card" for i in r["issues"])
    report = dict(baseline_commit=BASE, mode="MODELS_FAKE=1; real files, no live calls",
                  scope="Card consistency only; does not grade drawing interpretation accuracy. Reserved file evaluated only after implementation.",
                  reserved_unseen_doc_id=selection["reserved_unseen_doc_id"],
                  questions=len(after), documents=len({r["doc_id"] for r in rows}),
                  before_card_issues=[r for r in before if r["issues"]], after_card_issues=[r for r in after if r["issues"]],
                  before_contradictions=[r for r in before if has_contradiction(r)],
                  after_contradictions=[r for r in after if has_contradiction(r)], before=before, after=after,
                  recount_regression={"generated_for_test": True, "before": legacy, "after": regression,
                                      "before_issues": issues(legacy), "after_issues": issues(regression)},
                  schema_validated=len(after),
                  live_cost_usd=sum(r["cost_usd"] for r in after))
    (OUT / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k not in ("before", "after", "recount_regression")}))
    assert len(after) == 60
    assert report["live_cost_usd"] == 0
    assert not report["after_contradictions"], report["after_contradictions"]
    assert not report["after_card_issues"], report["after_card_issues"]
    assert not issues(regression)


if __name__ == "__main__":
    main()
