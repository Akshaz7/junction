"""FIX-6 (Awais, issue #1): storey counts, zero-count honesty, library questions, app-feature requests, typo tolerance. All $0, no model."""
import os

import pytest

os.environ.setdefault("MODELS_FAKE", "1")
from engine.answer import answer
from engine.library import fix_typos, app_feature, wants_library
from server.schema import validate_answer

AC = "ifc_bench__ac20-arc"
C1 = "cubicasa5k__colorful-11397"


@pytest.mark.parametrize("q", ["how many floors are there", "How many storeys does the building have?", "number of levels"])
def test_ifc_storey_count(q):
    a = answer(q, [AC])
    validate_answer(a)
    assert a["answer"]["value"] == 5 and a["answer"]["unit"] == "count"
    t = a["answer"]["text_md"]
    for name in ("Keller", "Erdgeschoss", "Dachgeschoss", "-3.0 m", "+9.0 m"):
        assert name in t
    assert a["citations"] and "[1]" in t and a["cost"]["usd_total"] == 0


def test_zero_count_is_not_certain():
    a = answer("how many stairs are there", [C1])
    validate_answer(a)
    if a["answer"]["value"] == 0 and not a["answer"]["abstained"]:
        assert a["answer"]["confidence"] <= 0.5
        assert "searched" in a["answer"]["text_md"]


@pytest.mark.parametrize("q", ["how many designs are in the database", "what is stored", "which documents are processed"])
def test_library_questions(q):
    a = answer(q, [])
    validate_answer(a)
    assert not a["answer"]["abstained"] and a["cost"]["usd_total"] == 0
    assert "documents" in a["answer"]["text_md"] and "By source" in a["answer"]["text_md"]
    assert a["answer"]["value"] > 100


def test_library_does_not_catch_element_questions():
    assert not wants_library("how many windows are in the database room")
    assert not wants_library("how many doors are there")


@pytest.mark.parametrize("q,which", [("render this 2D blueprint into 3D", "3d"), ("show it in 3D", "3d"), ("show on table", "ar"), ("show this in AR", "ar")])
def test_app_feature(q, which):
    a = answer(q, [C1])
    validate_answer(a)
    assert a["evidence"]["scene"]["open"] == which and not a["answer"]["abstained"]
    assert ("Visualise it" in a["answer"]["text_md"]) if which == "3d" else ("Show on table" in a["answer"]["text_md"])


def test_app_feature_leaves_measurements_alone():
    for q in ("how many windows", "show only the doors", "what is the area in 3D"):
        assert app_feature(q) is None


@pytest.mark.parametrize("bad,good", [("windos", "windows"), ("dors", "doors"), ("deisng", "design"), ("databse", "database")])
def test_typos(bad, good):
    assert good in fix_typos(f"how many {bad}")[0]


def test_typos_leave_real_words():
    for q in ("what is stored", "how many storeys", "how many bathrooms", "show the floors"):
        assert fix_typos(q)[0] == q


def test_typo_question_answers():
    a = answer("How many windos are there?", [C1])
    validate_answer(a)
    assert a["answer"]["value"] == 11 and a["question"] == "How many windos are there?"
