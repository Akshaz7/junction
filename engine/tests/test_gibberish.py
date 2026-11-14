import os
from pathlib import Path

import pytest

from engine.gibberish import is_gibberish

ART = Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))


@pytest.mark.parametrize("q", ["??? asdf qwerty", "asdf", "qwertyuiop", "!!!", "zxcvbnm hjkl", "bcdfgh"])
def test_nonsense_detected(q):
    assert is_gibberish(q)


@pytest.mark.parametrize("q", ["how many doors?", "doors", "area?", "hello", "thanks", "where is the lift", "ok", "what is the area of room 302?", "fire exits", "and windows?", "yes"])
def test_real_questions_not_gibberish(q):
    assert not is_gibberish(q)


def test_gibberish_does_not_carry_over_previous_answer(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    a = answer("??? asdf qwerty", ["any_doc"], history=[{"role": "user", "content": "how many doors?"}, {"role": "assistant", "content": "There are 5 doors."}])
    assert a["answer"]["abstained"] and "didn't understand" in a["answer"]["text_md"] and "doors are there" in a["answer"]["text_md"]
    assert a["citations"] == [] and a["cost"]["usd_total"] == 0 and "5 doors" not in a["answer"]["text_md"]


@pytest.mark.skipif(not (ART / "ifc_bench__fzk-house-arc" / "elements.json").exists(), reason="local artifact not present")
def test_door_counts_per_storey_table(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    a = answer("compare door counts per storey in a table", ["ifc_bench__fzk-house-arc"])
    t = a["answer"]["text_md"]
    assert "| Storey | Doors |" in t and "| Erdgeschoss | 5 |" in t and "| **Total** | 5 |" in t and a["cost"]["usd_total"] == 0
