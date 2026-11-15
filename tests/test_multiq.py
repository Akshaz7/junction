"""F-MULTIQ: compound questions are split, every part answered, one merged answer."""
import os
from pathlib import Path

import pytest

from engine.multiq import split

Q = "what is this file how many walls does it have which of these two files has more windows?"
DOCS = ["cubicasa5k__colorful-11397", "cubicasa5k__colorful-1732"]


def test_split_example():
    assert split(Q) == ["what is this file?", "how many walls does it have?", "which of these two files has more windows?"]


@pytest.mark.parametrize("q", [
    "how many doors and windows are there?", "tell me what is the area of the kitchen", "how many walls?",
    "what is the total area of the room which has the most windows", "how many rooms are bigger than what is the kitchen area",
    "which of these two files has more windows?", "What is the area of the biggest room?"])
def test_single_not_split(q):
    assert split(q) == []


def test_split_variants():
    assert split("how many doors and how many windows?") == ["how many doors?", "how many windows?"]
    assert split("What is the area of the biggest room? How many doors are there?") == ["What is the area of the biggest room?", "How many doors are there?"]


@pytest.mark.skipif(not all((Path(__file__).resolve().parents[1] / "artifacts" / d / "doc.json").exists() for d in DOCS), reason="local artifacts")
def test_example_on_two_docs(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    r = answer(Q, DOCS)
    t = r["answer"]["text_md"]
    assert "File type" in t and "colorful-1732" in t                       # what is this file, per document
    assert "40 walls" in t and "22 walls" in t                             # walls per document
    assert "colorful-11397 has more windows" in t                          # comparison
    assert [c["n"] for c in r["citations"]] == list(range(1, len(r["citations"]) + 1))
    assert len(r["reasoning"]["parts"]) == 3


@pytest.mark.skipif(not all((Path(__file__).resolve().parents[1] / "artifacts" / d / "doc.json").exists() for d in DOCS), reason="local artifacts")
def test_single_comparison(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    assert "has more windows" in answer("which of these two files has more windows?", DOCS)["answer"]["text_md"]


def test_largest_level_question_stays_whole():
    from engine import multiq
    q = "Which level has the largest listed floor area in the page 1 schedule, and what is that area?"
    assert multiq.split(q) == []


def test_merged_route_is_in_contract_enum():
    from engine import multiq
    from server.schema import validate_answer  # noqa: F401
    import json, pathlib
    enum = json.loads(pathlib.Path("server/schemas/answer.schema.json").read_text())["properties"]["route"]["enum"]
    r = {"answer": {"text_md": "x", "abstained": False, "confidence": .5}, "citations": [], "trace": [], "cost": {"usd_total": 0, "calls": []}}
    assert multiq.merge("a b?", ["d"], ["a?", "b?"], [r, r])["route"] in enum
