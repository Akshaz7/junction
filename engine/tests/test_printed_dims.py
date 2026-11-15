import json
from pathlib import Path

import pytest

from engine.solvers import solve
from pipeline.printed_dims import room_sizes

FIX = Path(__file__).parent / "fixtures" / "scan_printed_dims_planmap.json"


def _doc(tmp_path, mutate=None):
    pm = json.loads(FIX.read_text())
    if mutate:
        mutate(pm)
    d = tmp_path / "uploads__scan"
    d.mkdir()
    (d / "planmap-1.json").write_text(json.dumps(pm))
    (d / "doc.json").write_text(json.dumps({"doc_id": "uploads__scan", "kind": "raster", "pages": 1}))
    return pm


def test_room_sizes_pair_only_the_dimensions_that_span_the_room():
    sizes = room_sizes(json.loads(FIX.read_text()))
    k = sizes["room-003"]
    assert (k["width_m"], k["depth_m"]) == (2.55, 2.23)
    assert k["area_m2"] == pytest.approx(5.6865)
    assert sizes["room-001"]["depth_m"] == 2.5   # dining room uses its own 2.50, not the kitchen's 2.23


def test_kitchen_area_uses_printed_dimensions_and_shows_them(tmp_path):
    _doc(tmp_path)
    a = solve("What is the area of the kitchen in square metres? Show the dimensions used.", "uploads__scan", root=tmp_path)
    assert a["answer"]["value"] == pytest.approx(5.6865, abs=1e-3)
    text = a["answer"]["text_md"]
    assert "2.55 m × 2.23 m" in text and "aren't available" not in text
    assert "5.69" in text


def test_conflicting_or_implausible_dimensions_are_not_used():
    pm = json.loads(FIX.read_text())
    pm["dimension_evidence"].append({"text": "2.90", "meters": 2.9, "bbox_px": [114.9, 141.0, 119.0, 208.2]})
    assert "room-003" not in room_sizes(pm)
    pm = json.loads(FIX.read_text())
    pm["scale"]["m_per_px"] = 0.1   # printed 2.55 m vs 7.7 m measured: not the same thing
    assert "room-003" not in room_sizes(pm)


def test_rooms_without_matching_dimensions_keep_the_scale_area(tmp_path):
    _doc(tmp_path)
    a = solve("What is the area of the corridor in square metres?", "uploads__scan", root=tmp_path)
    assert "Printed dimensions" not in a["answer"]["text_md"] and "Dimensions used" not in a["answer"]["text_md"]
