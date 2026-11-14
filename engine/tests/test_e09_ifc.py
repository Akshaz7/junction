"""E-09 follow-ups on a synthetic IFC doc written to tmp_path (no real artifacts)."""
import json

import pytest

from engine.solvers.data import load_doc
from engine.solvers.solve import solve
from engine.textqa import facts_for

ST = {"name": "Ground", "elevation_m": 0.0}
ST2 = {"name": "Level 1", "elevation_m": 3.0}


def el(i, kind, name, storey=ST, q=None, props=None, type_name=None, bbox=None, cls=None, pre=None):
    return {"item_id": i, "name": name, "ifc_class": cls or "Ifc" + kind.title(), "kind": kind, "predefined_type": pre,
            "type_name": type_name, "storey": storey, "bbox_m": bbox, "quantities": q or {}, "props": props or {}}


@pytest.fixture()
def root(tmp_path):
    d = tmp_path / "fx__doc"
    d.mkdir()
    box = lambda x0, z0, x1, z1, y0=0.0, y1=2.6: [[x0, y0, z0], [x1, y1, z1]]
    els = [
        el("w1", "wall", "W1", q={"length_m": 10.0}, props={"is_external": True, "is_external_source": "space_boundary", "load_bearing": True}),
        el("w2", "wall", "W2", q={"length_m": 4.0}, props={"is_external": False, "load_bearing": False}),
        el("w3", "wall", "W3", q={"length_m": 6.0}, props={"is_external": True, "load_bearing": True}),
        el("r1", "room", "101", q={"net_floor_area_m2": 12.0}, props={"long_name": "WC Damen"}, type_name="Sanitaer", bbox=box(0, 0, 4, 3)),
        el("r2", "room", "102", q={"net_floor_area_m2": 20.0}, props={"long_name": "Open-plan office 1"}, bbox=box(5, 0, 15, 5)),
        el("r3", "room", "201", storey=ST2, q={"net_floor_area_m2": 9.0}, props={"long_name": "Toilette"}, bbox=box(0, 0, 3, 3, 3.0, 5.6)),
        el("f1", "furniture", "Desk", type_name="Desk A", bbox=box(6, 1, 7, 2, 0.0, 0.8)),
        el("f2", "furniture", "Desk", type_name="Desk A", bbox=box(8, 1, 9, 2, 0.0, 0.8)),
        el("f3", "furniture", "Chair", type_name="Chair", bbox=box(20, 1, 21, 2, 0.0, 0.8)),
        el("b1", "beam", "B1"), el("c1", "column", "C1"),
        el("s1", "slab", "S1", pre="FLOOR"), el("s2", "slab", "S2", pre="ROOF"),
    ]
    (d / "elements.json").write_text(json.dumps({
        "doc_id": "fx__doc", "version": 2, "schema": "IFC4", "units": "m", "storeys": [ST, ST2], "elements": els,
        "building": {"schema": "IFC4", "applications": ["Autodesk Revit 2024 (DEU)"], "header": {"originating_system": "Revit 24"},
                     "project": {"name": "P1", "long_name": "Office tower"}, "building": {"name": "HQ", "object_type": "Office"},
                     "building_common": {"OccupancyType": "Office"}}}))
    return tmp_path


def test_exterior_wall_length_uses_flag(root):
    r = solve("What is the total length of the outside walls?", "fx__doc", root=root)
    assert r["answer"]["value"] == 16.0 and not r["answer"]["abstained"]
    r = solve("How many interior walls are there?", "fx__doc", root=root)
    assert r["answer"]["value"] == 1


def test_exterior_abstains_without_flag(root, tmp_path):
    d = json.loads((root / "fx__doc" / "elements.json").read_text())
    for e in d["elements"]:
        e["props"].pop("is_external", None)
    (root / "fx__doc" / "elements.json").write_text(json.dumps(d))
    r = solve("length of exterior walls", "fx__doc", root=root)
    assert r["answer"]["abstained"]


def test_toilets_found_by_multilingual_room_names(root):
    r = solve("How many toilets are on the ground floor?", "fx__doc", root=root)
    assert r["answer"]["value"] == 1
    r = solve("How many toilets are in the building?", "fx__doc", root=root)
    assert r["answer"]["value"] == 2


def test_toilet_fixtures_win_over_rooms(root):
    d = json.loads((root / "fx__doc" / "elements.json").read_text())
    d["elements"].append(el("t1", "sanitary", "WC-Becken", cls="IfcSanitaryTerminal"))
    (root / "fx__doc" / "elements.json").write_text(json.dumps(d))
    assert solve("How many toilets are in the building?", "fx__doc", root=root)["answer"]["value"] == 1


def test_building_type_from_metadata(root):
    f = facts_for("What is the building's type and function?", load_doc("fx__doc", root))
    assert f.available and any("Office" in l for l in f.lines)


def test_building_type_abstains_when_nothing(tmp_path):
    d = tmp_path / "e__doc"
    d.mkdir()
    (d / "elements.json").write_text(json.dumps({"doc_id": "e", "storeys": [], "elements": [el("x", "wall", "W")], "building": {}}))
    assert not facts_for("What is the building type and function?", load_doc("e__doc", tmp_path)).available


def test_software_and_standard(root):
    f = facts_for("Which software and modeling standards were applied?", load_doc("fx__doc", root))
    text = "\n".join(f.lines)
    assert f.available and "IFC4" in text and "Revit 2024" in text


def test_load_bearing_share(root):
    f = facts_for("What proportion of walls are load-bearing?", load_doc("fx__doc", root))
    assert f.available and "Total walls: 3" in f.lines[0] and "2 (66.7%)" in f.lines[1]


def test_structural_summary(root):
    f = facts_for("What structural elements are in this building, grouped by type?", load_doc("fx__doc", root))
    t = "\n".join(f.lines)
    assert "Beams: 1" in t and "Floor slabs: 1" in t and "Roof slabs: 1" in t and "Columns: 1" in t


def test_furniture_in_named_room_uses_geometry(root):
    f = facts_for("What furniture is available in Open-plan office on the ground floor?", load_doc("fx__doc", root))
    assert f.topic == "furniture-in-room" and f.lines[0].startswith("2 furniture items")


def test_ceiling_height_from_room_extent(root):
    f = facts_for("What is the height of the ceiling in room 102?", load_doc("fx__doc", root))
    assert f.available and "2.60 m" in f.lines[0]
