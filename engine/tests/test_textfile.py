"""Text-layer uploads with no plan map are answered from the printed text; 'not shown' only when the text lacks it."""
import json

from engine import textfile
from engine.answer import answer
from engine.tests.test_sheetqa import _mk


def _doc(tmp_path, lines, name="up1"):
    return _mk(tmp_path, name, lines, "Uploaded plan")


ROOMS = [("ROOM TABLE", 100, 100), ("KITCHEN 12.5 m2 PERIMETER 14.2 m", 100, 200), ("BEDROOM 16.0 m2 PERIMETER 16.0 m", 100, 300),
         ("SLAB 150 mm D16 @ 300 BOTTOM", 100, 400), ("UNFINISHED CONCRETE SLAB", 100, 500)]


def test_room_table_areas_and_perimeters(tmp_path):
    d = _doc(tmp_path, ROOMS)
    r = textfile.answer("what is the area of the kitchen", [d], tmp_path)
    assert r and "12.5" in r["answer"]["text_md"] and r["citations"] and not r["answer"]["abstained"]
    r = textfile.answer("what are the room perimeters", [d], tmp_path)
    assert r and "14.2" in r["answer"]["text_md"] and "16.0 m" in r["answer"]["text_md"]


def test_slab_and_rebar_quoted(tmp_path):
    d = _doc(tmp_path, ROOMS)
    r = textfile.answer("what are the slab types and rebar", [d], tmp_path)
    t = r["answer"]["text_md"]
    assert "D16" in t and "UNFINISHED CONCRETE SLAB" in t and r["citations"]


def test_not_shown_only_when_absent(tmp_path):
    d = _doc(tmp_path, [("DOOR SCHEDULE", 100, 100)])
    r = textfile.answer("what is the rebar in the slab", [d], tmp_path)
    assert "Not shown" in r["answer"]["text_md"] and not r["citations"]
    r = textfile.answer("what is the area of the rooms", [d], tmp_path)
    assert "does not show areas" in r["answer"]["text_md"]


def test_door_schedule_count(tmp_path):
    ln = [(f"10{i}.A OFFICE", 100, 100 + i * 50) for i in range(5)] + [("100.A OFFICE", 100, 600)]
    d = _doc(tmp_path, ln)
    r = textfile.answer("how many doors are in the schedule", [d], tmp_path)
    assert r["answer"]["value"] == 5


def test_pipeline_uses_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    d = _doc(tmp_path, ROOMS)
    a = answer("what are the room perimeters", [d])
    assert "14.2" in a["answer"]["text_md"]
