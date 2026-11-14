import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from engine import answer as A
from engine.answer import answer

FIX = Path(__file__).parent / "fixtures"
DOC = "cubicasa5k__colorful-11397"


@pytest.fixture(autouse=True)
def root(monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(FIX))
    monkeypatch.setenv("MODELS_FAKE", "1")


def test_signature_matches_stub():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    import stub_engine
    a, b = inspect.signature(answer).parameters, inspect.signature(stub_engine.answer).parameters
    base = [(n, p.default, p.kind) for n, p in a.items() if p.kind is not inspect.Parameter.KEYWORD_ONLY]
    assert base == [(n, p.default, p.kind) for n, p in b.items()]
    assert all(p.default is None for p in a.values() if p.kind is inspect.Parameter.KEYWORD_ONLY)  # extras are optional


def test_windows_with_events():
    ev = []
    a = answer("How many windows are shown on this floor plan?", [DOC], lambda k, p: ev.append((k, p)))
    assert a["answer"]["value"] == 13 and len(a["evidence"]["boxes"]) == 13 and a["cost"]["usd_total"] == 0
    st = [p["text"] for k, p in ev if k == "status"]
    assert st[0] == "Thinking…" and st[1].startswith("Exploring document: ")
    assert [p for k, p in ev if k == "trace"] == a["trace"]
    assert a["trace"][0]["step"] == "route"


def test_abstentions_are_plain():
    n = answer("How many windows?", [])  # no document: plain chat (or the hint), never a project number or citation
    assert n["answer"]["value"] is None and n["citations"] == [] and n["doc_ids"] == []
    t = answer("What materials are used in the walls?", [DOC])   # forced last rung: always an answer, low confidence, says so
    assert not t["answer"]["abstained"] and t["answer"]["confidence"] <= 0.25 and "Low confidence" in t["answer"]["text_md"] and t["route"] == "hybrid"
    m = answer("How many windows are there?", ["missing__doc"])
    assert not m["answer"]["abstained"] and m["answer"]["value"] == 0 and "low confidence" in m["answer"]["text_md"]
    import os
    os.environ["FORCE_ANSWER"] = "0"
    try:
        assert answer("How many windows are there?", ["missing__doc"])["answer"]["abstained"]
    finally:
        del os.environ["FORCE_ANSWER"]


def test_unparsed_goes_to_model_fallback_and_never_raises(monkeypatch):
    a = answer("hello there", [DOC])
    assert a["answer"]["abstained"] is False and a["route"] == "hybrid" and any(s["step"] == "route" for s in a["trace"])
    import engine.solvers as S
    monkeypatch.setattr(A, "solve", lambda *x, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    b = answer("How many windows are shown?", [DOC])
    assert any(x["step"] == "error" for x in b["trace"]) and b["route"] == "hybrid"


def test_answer_path_imports_no_heavy_packages():
    code = ("import sys, engine.answer; bad=[m for m in ('torch','ifcopenshell','numpy','PIL','cv2') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_empty_question_abstains():
    from engine.answer import answer
    for q in ("", "   "):
        a = answer(q, ["cubicasa5k__high-quality-108"])
        assert a["answer"]["abstained"] and a["citations"] == [] and a["evidence"]["boxes"] == []
        assert "Ask a question" in a["answer"]["text_md"]


def test_question_naming_unselected_doc_abstains():
    from engine.answer import answer
    a = answer("How many windows are in ifc_bench__ac20-arc? Only high-quality-108 is selected.", ["cubicasa5k__high-quality-108"])
    assert a["answer"]["abstained"] and "ifc_bench__ac20-arc" in a["answer"]["text_md"]
    b = answer("How many windows in ifc_bench__ac20-arc?", ["ifc_bench__ac20-arc"])
    assert not b["answer"]["abstained"] or "not among the selected" not in b["answer"]["text_md"]


def test_no_document_chat_uses_system_prompt_and_history(monkeypatch):
    """Plain conversation without a document: Hologram's system prompt + earlier turns, no project facts."""
    import engine.assistant as AS
    from engine.models.core import Result
    seen = {}

    def fake_call(task, messages, *a, **k):
        seen["task"], seen["messages"] = task, messages
        return Result(text="Hi! Select a drawing with @ and I'll count it.", provider="fake", model="fake", task=task)
    monkeypatch.setattr("engine.models.call", fake_call)
    out = answer("Hello", [], history=[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}])
    assert seen["task"] == "chat" and seen["messages"][0]["role"] == "system"
    assert "Hologram" in seen["messages"][0]["content"] and seen["messages"][1]["content"] == "earlier"
    assert out["answer"]["abstained"] is False and out["answer"]["text_md"].startswith("Hi!") and out["citations"] == []


def test_cited_answers_keep_inline_markers():
    from engine.answer import ensure_markers
    r = ensure_markers({"answer": {"text_md": "There are **10 windows**.", "abstained": False}, "citations": [{"n": 1}, {"n": 2}]})
    assert r["answer"]["text_md"].endswith("[1] [2]")
    kept = ensure_markers({"answer": {"text_md": "Ten [1].", "abstained": False}, "citations": [{"n": 1}]})
    assert kept["answer"]["text_md"] == "Ten [1]."
    assert ensure_markers({"answer": {"text_md": "x", "abstained": True}, "citations": [{"n": 1}]})["answer"]["text_md"] == "x"


def _count_rows(n=60):
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "data/sets/sample200.jsonl"
    return [r for r in map(json.loads, p.open()) if r["type"] == "count"][:n] if p.exists() else []


def test_count_headline_equals_numbered_boxes(monkeypatch):
    """Visual verifiability: the number in the headline is the number of boxes drawn (planmap/IFC counts, no model calls)."""
    monkeypatch.setenv("RECOUNT", "0")
    monkeypatch.setenv("FORCE_ANSWER", "0")
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    bad = []
    for r in _count_rows():
        a = answer(r["question"], [r["doc_id"]])
        v, boxes = a["answer"].get("value"), a["evidence"]["boxes"]
        if not a["answer"].get("abstained") and isinstance(v, (int, float)) and boxes and "**" in a["answer"]["text_md"] and len(a["citations"]) == 1:
            if v != len(boxes) and len(a["evidence"]["scene"]["highlight_item_ids"]) == len(boxes):
                bad.append((r["question"], v, len(boxes)))
    assert not bad, bad[:5]


def test_recount_keeps_boxes_in_step_with_the_number(monkeypatch):
    import engine.recount as RC
    from engine import answer as A
    from engine.answer import answer
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    monkeypatch.setenv("FORCE_ANSWER", "0")
    doc = "cubicasa5k__colorful-11397"
    from engine.solvers import ARTIFACTS
    if not (Path(ARTIFACTS) / doc / "page-1.png").exists():
        pytest.skip("real artifacts not present")
    monkeypatch.setenv("ARTIFACTS_DIR", str(ARTIFACTS))
    monkeypatch.setattr(RC, "detect", lambda img, kind: ([[5, 5, 60, 25], [900, 900, 960, 925]], 0.0, "m"))   # two extra boxes drawn by vision
    # a drop of one is only taken when a box is clearly weak (want 0 = either outcome, still consistent)
    for vision, want in [(8, 8), (9, 9), (10, 0), (15, 11)]:
        monkeypatch.setattr(RC, "recount", lambda q, img, kind=None, v=vision: (v, 0.0, "m"))
        a = answer("How many windows are there?", [doc])
        n = len(a["evidence"]["boxes"])
        assert a["answer"]["value"] == n == len(a["evidence"]["scene"]["highlight_item_ids"])
        if want:
            assert n == want and f"**{want} windows**" in a["answer"]["text_md"] and a["answer"]["text_md"].rstrip().endswith("[1]")
