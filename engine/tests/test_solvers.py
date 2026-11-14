import json
import shutil
from pathlib import Path

import pytest

from engine.solvers import SolverUnsupported, ARTIFACTS, solve

FIX = Path(__file__).parent / "fixtures"
AC20 = "ifc_bench__ac20-arc"
needs_ac20 = pytest.mark.skipif(not (ARTIFACTS / AC20 / "elements.json").exists(), reason="ac20 artifacts not built")


def test_fixture_windows_13_boxes():
    a = solve("How many windows are shown on this floor plan?", "cubicasa5k__colorful-11397", root=FIX)
    assert a["answer"]["value"] == 13 and a["answer"]["unit"] == "count" and not a["answer"]["abstained"]
    assert len(a["evidence"]["boxes"]) == 13
    assert [b["label"] for b in a["evidence"]["boxes"]] == [str(i) for i in range(1, 14)]
    assert len(a["evidence"]["scene"]["highlight_item_ids"]) == 13
    assert {b["item_id"] for b in a["evidence"]["boxes"]} == set(a["evidence"]["scene"]["highlight_item_ids"])
    assert a["cost"]["usd_total"] == 0 and all(s["cost_usd"] == 0 and s["model"] is None for s in a["trace"])
    assert a["answer"]["text_md"].startswith("There are **13 windows**") and a["answer"]["text_md"].rstrip().endswith("[1]")
    assert a["citations"][0]["item_ids"] == a["evidence"]["scene"]["highlight_item_ids"]


def test_fixture_other_kinds_and_zero():
    assert solve("How many toilets are drawn on this floor plan?", "cubicasa5k__colorful-11397", root=FIX)["answer"]["value"] == 2
    a = solve("How many bathtubs are drawn on this floor plan?", "cubicasa5k__colorful-11397", root=FIX)
    assert a["answer"]["value"] == 0 and "no bathtubs" in a["answer"]["text_md"]


def test_planmap_area_without_rooms_abstains():
    a = solve("What is the total area of all rooms?", "cubicasa5k__colorful-11397", root=FIX)
    assert a["answer"]["abstained"] and a["answer"]["value"] is None


def test_planmap_area_with_scale(tmp_path):
    d = tmp_path / "x__y"
    d.mkdir()
    pm = {"doc_id": "x__y", "page": 1, "image": {"w": 10, "h": 10}, "scale": {"m_per_px": 0.1, "method": "dimension", "confidence": 0.9},
          "items": [{"item_id": "room-001", "kind": "room", "label": "KÜCHE", "bbox_px": [0, 0, 5, 5], "props": {"area_m2": 12.5}, "conf": 0.9},
                    {"item_id": "room-002", "kind": "room", "label": None, "bbox_px": [5, 5, 9, 9], "props": {"area_m2": 7.5}, "conf": 0.9}]}
    (d / "planmap-1.json").write_text(json.dumps(pm))
    a = solve("What is the total net area of all rooms on this floor plan?", "x__y", root=tmp_path)
    assert a["answer"]["value"] == 20.0 and "**20.0 m²**" in a["answer"]["text_md"]
    b = solve("What is the net floor area of the room 'Küche' in m²?", "x__y", root=tmp_path)
    assert b["answer"]["value"] == 12.5
    pm["scale"] = {"m_per_px": None, "method": "none", "confidence": 0.0}
    (d / "planmap-1.json").write_text(json.dumps(pm))
    assert solve("What is the total area of all rooms?", "x__y", root=tmp_path)["answer"]["abstained"]


def test_missing_doc_abstains_and_non_numeric_raises(tmp_path):
    assert solve("How many doors are there?", "nope__nope", root=tmp_path)["answer"]["abstained"]
    with pytest.raises(SolverUnsupported):
        solve("What materials are used in the walls?", "nope__nope", root=tmp_path)


@needs_ac20
def test_ac20_counts():
    for q, n in (("How many doors are in this building?", 77), ("How many windows are in this building?", 206),
                 ("How many walls are in this building?", 121)):
        a = solve(q, AC20)
        assert a["answer"]["value"] == n and a["cost"]["usd_total"] == 0
        assert len(a["evidence"]["scene"]["highlight_item_ids"]) == n and a["route"] == "index"


@needs_ac20
def test_ac20_storey_scope_and_sums():
    els = json.load(open(ARTIFACTS / AC20 / "elements.json"))["elements"]
    eg = sum(1 for e in els if e["kind"] == "door" and (e["storey"] or {}).get("name") == "Erdgeschoss")
    assert solve("How many doors are on the ground floor?", AC20)["answer"]["value"] == eg
    assert solve("How many doors are on the Erdgeschoss?", AC20)["answer"]["value"] == eg
    area = solve("What is the total net floor area of all rooms in the building?", AC20)["answer"]
    exp = sum(e["quantities"].get("net_floor_area_m2", e["quantities"].get("area_m2", 0)) for e in els if e["kind"] == "room")
    assert abs(area["value"] - exp) < 0.01 and area["unit"] == "m²"
    wl = solve("What is the total length of walls in the building?", AC20)["answer"]
    assert wl["unit"] == "m" and wl["value"] > 0
    r = solve("What is the net floor area of room 001 in m²?", AC20)["answer"]
    assert not r["abstained"]


# ---- FIX-1: "how many windows and doors" returns both counts ---------------------------------------------

import pytest as _pytest

from engine.router.parser import parse as _parse


@_pytest.mark.parametrize("q", ["How many windows and doors are there?", "how many windows and how many doors", "Count the windows and doors",
                                "count the doors and windows"])
def test_multi_kind_phrasings_parse_to_kinds(q):
    p = _parse(q)
    assert p.type == "count" and len(p.kinds) == 2 and set(p.kinds) == {"window", "door"} and p.kind == p.kinds[0]


@_pytest.mark.parametrize("q", ["How many doors are in the room with the window", "How many bedrooms and bathrooms", "how many windows"])
def test_single_kind_stays_single(q):
    assert len(_parse(q).kinds) == 1


def test_multi_count_on_colorful_11397_has_both_counts_and_boxes():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "artifacts"
    if not (root / "cubicasa5k__colorful-11397").exists():
        _pytest.skip("artifact missing")
    from engine.solvers.solve import solve
    a = solve("How many windows and doors are there?", "cubicasa5k__colorful-11397", root=root)
    assert not a["answer"]["abstained"] and a["cost"]["usd_total"] == 0
    assert a["answer"]["value"] == {"window": 11, "door": 11}
    assert "**11 windows**" in a["answer"]["text_md"] and "**11 doors**" in a["answer"]["text_md"]
    boxes = a["evidence"]["boxes"]
    assert {b["kind"] for b in boxes} == {"window", "door"} and len(boxes) == 22
    assert sorted(int(b["label"]) for b in boxes) == list(range(1, 23))
    assert set(a["evidence"]["scene"]["item_kinds"].values()) == {"window", "door"}
