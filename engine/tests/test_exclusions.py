import json
from pathlib import Path

import pytest

from engine import exclusions
from engine.answer import answer

FIX = Path(__file__).parent / "fixtures" / "dxf_vlm_cottage_planmap.json"
TOTAL_Q = "What is the total net indoor floor area excluding the porch? List the room areas used."
TILE_Q = ("Order bathroom floor tiles, 300 x 300 mm tiles, with 10% waste. "
          "Use the bathroom dimensions shown in the drawing, not the laundry closet.")


@pytest.fixture
def cottage(tmp_path, monkeypatch):
    d = tmp_path / "uploads__qs"
    d.mkdir()
    (d / "planmap-1.json").write_text(FIX.read_text())
    (d / "doc.json").write_text(json.dumps({"doc_id": "uploads__qs", "kind": "dxf", "pages": 1}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    return "uploads__qs"


def test_split_finds_exclusion_clause():
    assert exclusions.split(TOTAL_Q)[1] == "the porch"
    assert exclusions.split(TILE_Q)[1] == "the laundry closet"
    assert exclusions.split("Area of all rooms except the WC and kitchen?")[1] == "the WC and kitchen"
    assert exclusions.split("How many doors are there?") == ("How many doors are there?", None)


def test_total_excludes_porch_counts_overlap_once_and_lists_rooms(cottage):
    a = answer(TOTAL_Q, [cottage])["answer"]
    assert a["value"] < 62.77            # plain sum of indoor rooms (overlaps counted twice)
    assert a["value"] < 68.16            # old answer, porch included
    t = a["text_md"]
    assert "overlap" in t and "Left out as asked" in t and "Rooms used" in t
    assert "terrace" not in t.split("Rooms used")[1]


def test_bathroom_order_does_not_add_the_wc_when_laundry_excluded(cottage):
    a = answer(TILE_Q, [cottage])["answer"]
    assert a["value"] == pytest.approx(4.04 * 1.1, abs=0.1)
    assert "not a labelled room" in a["text_md"]


def test_plain_questions_unchanged(cottage):
    a = answer("What is the total floor area?", [cottage])["answer"]
    assert a["value"] is not None
