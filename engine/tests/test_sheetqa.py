"""FIX-14: engineering-sheet answers from the text layer (synthetic sheets, plus the real HVAC sheet when present)."""
import json
from pathlib import Path

import pytest

from engine import sheetqa


def _mk(tmp_path, name, lines, title=None):
    """lines: [(text, x, y)] -> text-1.json with one word per entry (spaces split into words on the same row)."""
    d = tmp_path / name
    d.mkdir()
    words = []
    for text, x, y in lines:
        for i, t in enumerate(text.split(" ")):
            words.append({"text": t, "bbox_px": [x + i * 60, y, x + i * 60 + 50, y + 20]})
    (d / "text-1.json").write_text(json.dumps({"doc_id": name, "page": 1, "image": {"w": 3000, "h": 2000}, "dpi": 150,
                                               "source": "pdf-text-layer", "words": words}))
    (d / "pages.json").write_text(json.dumps({"pages": [{"page": 1}]}))
    (d / "doc.json").write_text(json.dumps({"title": title or name}))
    return name


def test_fuel_pumps_unique_tags(tmp_path):
    ln = [(f"FP-{i}", 100 + i * 200, 100) for i in range(1, 6)] + [("FP-1", 100, 600)] + [(f"FSR-{i}", 100 + i * 100, 900) for i in (1, 2)] \
        + [(f"FSI-{i}", 100 + i * 100, 1200) for i in range(1, 6)] + [("PIPING PLAN M-101A", 50, 50)]
    d = _mk(tmp_path, "m101", ln, "Fuel farm M-101A")
    assert sheetqa.is_sheet(d, tmp_path)
    r = sheetqa.answer("How many fuel pumps are there?", [d], tmp_path)
    assert r["answer"]["value"] == 5 and len(r["citations"]) == 5 and r["cost"]["usd_total"] == 0
    r = sheetqa.answer("How many filter separator vessels?", [d], tmp_path)
    assert r["answer"]["value"] == 7


@pytest.mark.parametrize("txt,ratio", [('SCALE 1/4" = 1\'-0"', 48), ('1" = 40\'', 480), ("SCALE 1:50", 50)])
def test_scale(txt, ratio):
    assert sheetqa.parse_scale(txt)[1] == ratio


def test_area_table_total_and_share(tmp_path):
    ln = [("SUMMARY", 100, 100), ("NORTH 7,009 SF", 100, 200), ("SOUTH 7,005 SF", 100, 300), ("EAST 7,688 SF", 100, 400),
          ("WEST 4,479 SF", 100, 500), ("CIRCULATION 4,470 SF", 100, 600), ("TOTAL 26,562 SF", 100, 700)]
    d = _mk(tmp_path, "a2", ln, "Dormitory A-2")
    r = sheetqa.answer("What is the second floor area in m2?", [d], tmp_path)
    assert r and abs(r["answer"]["value"] - 2467.7) < 0.2
    r = sheetqa.answer("What share of the floor is circulation?", [d], tmp_path)
    assert r and abs(r["answer"]["value"] - 16.8) < 0.1


def test_trench_sum_and_rebar(tmp_path):
    ln = [("1. TOTAL TRENCH 4275 + 1825 + 1750 MM", 100, 100), ("150 SLAB D13 @ 300 EW", 100, 300)]
    d = _mk(tmp_path, "s100", ln, "Foundation S-100F")
    r = sheetqa.answer("What is the total trench length?", [d], tmp_path)
    assert r and r["answer"]["value"] == 7850
    r = sheetqa.answer("What is the reinforcement of the 150 mm slab?", [d], tmp_path)
    assert r and "D13 @ 300" in r["answer"]["text_md"]


def test_cross_sheet_not_uploaded(tmp_path):
    d = _mk(tmp_path, "m101b", [("PIPE PENETRATION DETAIL SEE M-303", 100, 100)], "Piping M-101A")
    r = sheetqa.answer("Where is the pipe penetration detail?", [d], tmp_path)
    assert r and "M-303" in r["answer"]["text_md"] and "not part of this upload" in r["answer"]["text_md"]


def test_non_sheet_returns_none(tmp_path):
    d = _mk(tmp_path, "plain", [("LIVING 20 M2", 100, 100)], "Apartment")
    assert not sheetqa.is_sheet(d, tmp_path)


def test_size_lookup(tmp_path):
    d = _mk(tmp_path, "sz", [("16\" SUCTION HEADER", 100, 100), ("SUMP 600 X 600 X 300 DEEP", 100, 300)], "Piping M-101A")
    assert "16" in sheetqa.answer("What is the suction header size?", [d], tmp_path)["answer"]["value"]
    assert "600" in sheetqa.answer("What is the sump size?", [d], tmp_path)["answer"]["value"]


def test_room_count_and_width(tmp_path):
    ln = [(str(201 + i), 100 + (i % 12) * 80, 100 + (i // 12) * 100) for i in range(48)] + [("52'-8\" NORTH WING", 100, 900), ("30'-0\"", 100, 950)]
    d = _mk(tmp_path, "dorm", ln, "Dormitory A-2")
    r = sheetqa.answer("How many dorm rooms are on this floor?", [d], tmp_path)
    assert r and r["answer"]["value"] == 48
    r = sheetqa.answer("What is the width of the north wing?", [d], tmp_path)
    assert r and "52'-8" in r["answer"]["value"]
    assert sheetqa.answer("How many toilet rooms?", [d], tmp_path) is None


def test_room_row_not_total_and_schedule_rows(tmp_path):
    ln = [("DINING 164 SF", 100, 100), ("KITCHEN 300 SF", 100, 200), ("OFFICE 90 SF", 100, 300), ("TOTAL 554 SF", 100, 400)]
    d = _mk(tmp_path, "gro", ln, "Floor plan A-101")
    r = sheetqa.answer("What is the area of the dining room in square metres?", [d], tmp_path)
    assert r and abs(r["answer"]["value"] - 15.2) < 0.1
    assert sheetqa.answer("What is the area of the library?", [d], tmp_path) is None  # no row: never the total
    r = sheetqa.answer("How many rooms are in the schedule?", [d], tmp_path)
    assert r and r["answer"]["value"] == 3


def test_shower_and_vent_size(tmp_path):
    ln = [("SH-1", 100, 100), ("SH-1", 300, 100), ("SH - SHOWER", 100, 900), ("1-1/2\"V FROM KS-1", 100, 300), ("3\"VTR", 100, 500), ("3\"VTR", 300, 500)]
    d = _mk(tmp_path, "plb", ln, "Plumbing P-1.02")
    assert sheetqa.answer("How many showers are there?", [d], tmp_path)["answer"]["value"] == 2
    assert sheetqa.answer("How many 3 inch roof vents (VTR) are there?", [d], tmp_path)["answer"]["value"] == 2
    assert "1-1/2" in sheetqa.answer("What size is the vent from the kitchen sink?", [d], tmp_path)["answer"]["value"]


def test_toilet_and_sink_counts_use_wc_ks_tags(tmp_path):
    ln = [("WC-1", 100, 100), ("WC-1", 300, 100), ("WC-1", 500, 100), ("KS-1", 100, 300), ("KS-1", 300, 300), ("3\"VTR", 100, 500)]
    d = _mk(tmp_path, "plb2", ln, "Plumbing P-1.02")
    assert sheetqa.answer("how many toilets are there?", [d], tmp_path)["answer"]["value"] == 3
    assert sheetqa.answer("how many sinks?", [d], tmp_path)["answer"]["value"] == 2


def test_sheet_identity_and_pipe_sizes(tmp_path, monkeypatch):
    d = _mk(tmp_path, "plb3", [("WC-1", 100, 100)] * 1 + [("P1.02", 100, 900)], "Plumbing P1.02")
    sh = {"sheet": {"id": "P1.02", "title": "SECOND FLOOR PLANS", "id_box": [1, 2, 3, 4], "title_box": [5, 6, 7, 8], "confidence": 0.9},
          "tags": {"pipe_size": {'3"VTR': {"count": 3, "boxes": [[1, 1, 2, 2]]}, '2"ø': {"count": 1, "boxes": [[3, 3, 4, 4]]}}}}
    import vision.sheet_text as vs
    monkeypatch.setattr(vs, "read_sheet", lambda p, *a, **k: sh)
    r = sheetqa.answer("what is this drawing?", [d], tmp_path)
    assert r["answer"]["value"] == "P1.02" and "Second Floor Plans" in r["answer"]["text_md"] and len(r["citations"]) == 2
    r = sheetqa.answer("what are the pipe sizes?", [d], tmp_path)
    assert '3"VTR x3' in r["answer"]["text_md"] and r["cost"]["usd_total"] == 0
    sh["sheet"]["title"] = "x" * 90  # garbage title block -> reader
    assert sheetqa.answer("what is this drawing?", [d], tmp_path) is None


def test_area_by_type_lists_table_rows(tmp_path):
    ln = [("DINING", 100, 100), ("164 SF", 500, 100), ("KITCHEN", 100, 200), ("254 SF", 500, 200), ("STORAGE ROOM", 100, 300), ("901 SF", 500, 300),
          ("OFFICE 1 (MEZZ.)", 100, 400), ("222 SF", 500, 400), ("TOTAL", 100, 500), ("1541 SF", 500, 500)]
    d = _mk(tmp_path, "arch1", ln, "A-201 floor plan")
    r = sheetqa.answer("What is the floor area of each room type?", [d], tmp_path)
    t = r["answer"]["text_md"]
    assert r["answer"]["value"] == 4 and "DINING: 164 SF = 15.2 m²" in t and "OFFICE 1" in t and "1541" not in t and len(r["citations"]) == 4
    assert sheetqa.answer("What is the slab area by type?", [d], tmp_path) is None
