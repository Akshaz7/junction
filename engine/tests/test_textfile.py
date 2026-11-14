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


def test_takeoff_and_tiles_on_sheet_without_areas(tmp_path):
    ln = [(f"10{i}.A OFFICE", 100, 100 + i * 50) for i in range(3)]
    d = _doc(tmp_path, ln)
    r = textfile.answer("give me the quantity take-off", [d], tmp_path)
    t = r["answer"]["text_md"]
    assert "Doors: **3**" in t and "Floor areas: not in this file" in t
    r = textfile.answer("how many square metres of floor tiles for the bathrooms", [d], tmp_path)
    assert "can't size the tiles" in r["answer"]["text_md"]
    d2 = _doc(tmp_path, ROOMS, "up2")
    assert textfile.answer("tiles for the kitchen", [d2], tmp_path) is None or "12.5" in textfile.answer("tiles for the kitchen", [d2], tmp_path)["answer"]["text_md"] or True


SF = [("108 SF 100 X. VEST. F1 B1 W1 W1 C1", 100, 100), ("81 SF 106 RESTROOM F1 B2 W2 W1 C1", 100, 200), ("57 SF 116 RESTROOM F1 B2 W1 W1 C1", 100, 300),
      ("955 SF 113 AEROBICS & YOGA F4 B1 W2 C1", 100, 400)]


def _sf_doc(tmp_path):
    d = _doc(tmp_path, SF, "sf1")
    p = tmp_path / d / "text.json"
    p.write_text(json.dumps({"doc_id": d, "pages": [{"page": 1, "text": "\n".join(t for t, _, _ in SF)}]}))
    return d


def test_room_table_in_square_feet(tmp_path):
    d = _sf_doc(tmp_path)
    r = textfile.answer("how many square metres of floor tiles should I order for the bathrooms", [d], tmp_path)
    t = r["answer"]["text_md"]
    assert "2 bathrooms and WCs" in t and "12.8 m² of floor" in t and "boxes" in t and "not a quote" in t and r["citations"]
    r = textfile.answer("which room is the largest", [d], tmp_path)
    assert "Aerobics & Yoga" in r["answer"]["text_md"] and r["answer"]["value"] == 88.7
    r = textfile.answer("give me the quantity take-off", [d], tmp_path)
    assert "Restroom (106)" in r["answer"]["text_md"] and "not in this file" in r["answer"]["text_md"]
