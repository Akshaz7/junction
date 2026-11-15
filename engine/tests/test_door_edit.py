import json
from pathlib import Path

import pytest

from engine.answer import answer
from engine.door_edit import parse

FIX = Path(__file__).parent / "fixtures" / "dxf_vlm_cottage_planmap.json"
Q = ("Create a proposed change to widen the Bathroom door from 760 mm to 900 mm. Show what would change and "
     "flag source or geometry limitations. Do not claim the result is code-compliant.")


@pytest.fixture
def cottage(tmp_path, monkeypatch):
    pm = json.loads(FIX.read_text())
    doors = [i for i in pm["items"] if i["kind"] == "door"]
    doors[0]["label"], doors[0]["props"]["width_m"] = "Bathroom door", 0.76
    doors[1]["label"], doors[1]["props"]["width_m"] = "Entry door", 0.9
    d = tmp_path / "uploads__qs"
    d.mkdir()
    (d / "planmap-1.json").write_text(json.dumps(pm))
    (d / "doc.json").write_text(json.dumps({"doc_id": "uploads__qs", "kind": "dxf", "pages": 1}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    return "uploads__qs", doors[0]["item_id"]


def test_parse_only_matches_door_width_edits():
    assert parse(Q)["to_mm"] == 900 and parse(Q)["words"] == ["bathroom"]
    assert parse("Make door D3 900 mm wide")["tag"] == "D3"
    assert parse("Make D3 wider by 100 mm")["by_mm"] == 100
    for q in ["How wide is the door?", "How many doors are 900 mm wide?", "Which doors are below 900 mm?", "Highlight the bathroom"]:
        assert parse(q) is None


def test_proposed_width_change_highlights_the_door_not_a_room(cottage):
    doc_id, door_id = cottage
    r = answer(Q, [doc_id])
    a, t = r["answer"], r["answer"]["text_md"]
    assert not a["abstained"] and "760 mm -> 900 mm" in t and "+140 mm" in t
    assert "nothing is saved" in t and "code compliance" in t
    assert r["evidence"]["scene"]["highlight_item_ids"] == [door_id]
    assert r["evidence"]["scene"]["commands"] == []
    assert r["cost"]["usd_total"] == 0


def test_unknown_or_ambiguous_door_is_not_guessed(cottage):
    doc_id, _ = cottage
    r = answer("Widen the garage door to 900 mm", [doc_id])
    assert r["answer"]["abstained"] and "could not find" in r["answer"]["text_md"]
    assert r["evidence"]["scene"]["highlight_item_ids"] == []
