import os

os.environ.setdefault("MODELS_FAKE", "1")

import pytest

from engine.answer import _teach_in_chat

DOC = ["ifc_models__kit-fzk-haus-ac20-fzk-haus"]


@pytest.mark.parametrize("q", [
    "Tell Stoa: the left bedroom should be called Bedroom West. Remember this correction",
    "Remember this: room 3 is the Kitchen",
    "Rename the left bedroom to Bedroom West",
])
def test_correction_is_not_claimed_as_remembered(q):
    r = _teach_in_chat(q, DOC, [], 0.0)
    t = r["answer"]["text_md"]
    assert r["answer"]["abstained"] and "have not saved" in t and "Tell Stoa" in t and "Noted" not in t


@pytest.mark.parametrize("q", [
    "How many rooms are called Bedroom?",
    "Which room should be called the kitchen?",
    "What is the left bedroom called?",
    "How many doors are there?",
])
def test_ordinary_questions_are_untouched(q):
    assert _teach_in_chat(q, DOC, [], 0.0) is None


def test_through_answer():
    from engine.answer import answer
    r = answer("Tell Stoa: the left bedroom should be called Bedroom West. Remember this correction", DOC)
    assert "have not saved" in r["answer"]["text_md"] and r["cost"]["usd_total"] == 0
