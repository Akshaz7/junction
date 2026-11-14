"""JUDGE-QA shapes: floor comparisons, conditional counts, take-off with waste, named rooms, rule checks, edit verdict."""
import os
import pytest

os.environ.setdefault("MODELS_FAKE", "1")
from engine.answer import answer  # noqa: E402

AC = "ifc_bench__ac20-arc"
C1 = "cubicasa5k__colorful-11397"
SW = "swiss_dwellings__site1000-bldg2082-floor9385"


def A(q, d):
    return answer(q, [d])


def need(d):
    from engine.solvers import ARTIFACTS
    if not (ARTIFACTS / d).exists():
        pytest.skip("artifact not present")


@pytest.mark.parametrize("q,val", [
    ("Which floor has the most doors?", 22),
    ("How many doors are wider than 1 m?", 10),
    ("How many windows are there in total on the building and how many on the 2nd floor?", 206),
])
def test_ifc_shapes(q, val):
    need(AC)
    a = A(q, AC)
    assert a["answer"]["value"] == val and a["cost"]["usd_total"] == 0


def test_takeoff_with_waste_and_multi_target():
    need(AC), need(C1)
    a = A("How many m2 of floor tiles do I need for all the WCs including 10% waste?", AC)
    assert abs(a["answer"]["value"] - 108.9) < 0.2
    b = A("How many m2 of flooring for the living room and kitchen with 10% extra?", C1)
    assert abs(b["answer"]["value"] - 38.8) < 0.5


def test_named_rooms_and_planmap_superlative():
    need(SW), need(C1)
    assert A("How many Zimmer rooms are there and what is their total area?", SW)["answer"]["value"] == 9
    assert "TERASSI" in A("What is the biggest room in this plan?", C1)["answer"]["text_md"]


def test_rule_check_and_edit_verdict():
    need(AC)
    a = A("Do all doors meet the accessibility clear width requirement?", AC)
    assert "241/2017" in a["answer"]["text_md"]
    b = A("Remove the front door. Is the building still compliant?", AC)
    assert "Not compliant" in b["answer"]["text_md"] and b.get("advisor_cards")
