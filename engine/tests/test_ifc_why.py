"""IFC-WHY: IFC dimension answers cite the exact IFC field; no door-prior noise on IFC pages."""
import json
import os
from pathlib import Path

import pytest

from engine import ifc_why
from engine.solvers.data import Item

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"
DOOR = "18PQUIFELEARLM4c0brquf"
need = pytest.mark.skipif(not (ROOT / DOC / "elements.json").is_file(), reason="ac20 artifacts missing")


def test_dimension_words():
    assert ifc_why.dimension("How wide is the main entrance door?") == "width"
    assert ifc_why.dimension("How thick is the thickest wall?") == "thickness"
    assert ifc_why.dimension("How long is the longest wall?") == "length"
    assert ifc_why.dimension("How tall is the door?") == "height"
    assert ifc_why.dimension("How many doors?") is None


def test_pick_and_origin():
    it = Item("g", "wall", q={"width_m": 0.3, "length_m": 18.0},
              props={"quantity_source": {"width_m": "qto", "length_m": "bbox"}}, source="ifc")
    assert ifc_why.pick(it, "thickness") == (0.3, "width_m")
    assert ifc_why.origin(it, "width_m") == "IFC base quantity Width"
    assert "bounding box" in ifc_why.origin(it, "length_m")


def _res(value, ids):
    return {"answer": {"value": value, "unit": "m", "text_md": f"**{value} m**"}, "doc_ids": [DOC], "route": "hybrid",
            "citations": [{"n": 1, "doc_id": DOC, "page": 1, "kind": "element", "item_ids": ids}], "trace": []}


@need
def test_door_width_calc_complete_and_measured_step():
    from engine.calc import validate
    res = _res(2.0, [DOOR])
    calc = ifc_why.dimension_calc(res, "How wide is the main entrance door?", ROOT)
    assert calc and calc["rows"][0]["source"]["field"] == "quantities.width_m"
    assert validate(calc, ROOT) == []
    res["reasoning"] = {"steps": [{"kind": "found", "title": "Found", "text": "One door"}]}
    ifc_why.add_measured_step(res, calc, ROOT)
    m = res["reasoning"]["steps"][1]
    assert m["kind"] == "measured" and DOOR in m["text"] and "quantities.width_m" in m["text"]
    assert "no drawing scale needed" in m["text"]


@need
def test_longest_wall_max_not_sum():
    from engine.calc import validate
    walls = [e for e in json.loads((ROOT / DOC / "elements.json").read_text())["elements"]
             if e["kind"] == "wall" and e["quantities"].get("length_m") == 41.7]
    calc = ifc_why.dimension_calc(_res(41.7, [w["item_id"] for w in walls]), "How long is the longest wall?", ROOT)
    assert calc and any(s["id"] == "ifc-max" for s in calc["steps"])
    assert validate(calc, ROOT) == []


@need
def test_no_door_prior_on_ifc_pages():
    from engine.scale_proof import enrich, read_json
    pm = read_json(ROOT / DOC / "planmap-1.json")
    proof = enrich({**pm, "doc_id": DOC, "page": 1}, ROOT / DOC)["proof"]
    assert not any(s["label"] == "door prior" for s in proof["steps"])


def test_area_basis_text_says_used_and_why():
    rooms = [Item("r1", "room", q={"selected_floor_area_m2": 24.64, "net_floor_area_m2": 23.9, "gross_floor_area_m2": 24.64},
                  props={"selected_area_basis": "stored gross floor area"}, source="ifc")]
    text = ifc_why.area_basis_text(rooms)
    assert text.startswith("Used: stored gross floor area for 1 room") and "because" in text and "GrossFloorArea" in text


@need
def test_element_height_is_not_building_height():
    from engine.complex_q import h_height
    from engine.solvers.data import load_doc
    doc = load_doc(DOC, ROOT)
    assert h_height("How tall is the main entrance door?", doc) is None
    assert h_height("How tall is the building?", doc) is not None
    calc = ifc_why.dimension_calc({**_res(2.1, [DOOR])}, "How tall is the main entrance door?", ROOT)
    assert calc and calc["rows"][0]["source"]["field"] == "quantities.height_m"
