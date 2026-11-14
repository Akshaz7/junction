"""pdf_to_ifc: synthetic plan map (4 walls, 1 door, 1 window, 1 room) -> IFC4 with voids, fillings, space area."""
import json

import ifcopenshell
import ifcopenshell.util.element as uel
import pytest

from pipeline import pdf_to_ifc

MPP = 0.01  # 1 px = 1 cm


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _planmap():
    # 5 m x 4 m room inside 20 cm walls; px coordinates, y down
    walls = [_rect(0, 0, 520, 20), _rect(0, 420, 520, 440), _rect(0, 20, 20, 420), _rect(500, 20, 520, 420)]
    items = [{"item_id": f"wall-{i + 1:03d}", "kind": "wall", "label": "", "polygon_px": p,
              "bbox_px": [p[0][0], p[0][1], p[2][0], p[2][1]], "props": {"thickness_m": 0.2}, "conf": 0.9,
              "source": "pdf_vector"} for i, p in enumerate(walls)]
    items.append({"item_id": "door-001", "kind": "door", "polygon_px": _rect(200, 420, 290, 440),
                  "bbox_px": [200, 420, 290, 440], "props": {"width_m": 0.9}, "conf": 0.9, "source": "pdf_vector"})
    # window in a gap of the right wall the vector reader left open (wall drawn over it here: overlap case)
    items.append({"item_id": "window-001", "kind": "window", "polygon_px": _rect(500, 150, 520, 270),
                  "bbox_px": [500, 150, 520, 270], "props": {"width_m": 1.2}, "conf": 0.9, "source": "pdf_vector"})
    items.append({"item_id": "room-001", "kind": "room", "label": "Living", "polygon_px": _rect(20, 20, 500, 420),
                  "bbox_px": [20, 20, 500, 420], "props": {"number": "1.01", "area_m2_geom": 19.2}, "conf": 0.85,
                  "q": {"area_m2": 19.2, "area_m2_printed": 19.5}, "source": "pdf_vector"})
    items.append({"item_id": "text-001", "kind": "text", "label": "Living", "bbox_px": [200, 200, 260, 220]})
    return {"doc_id": "synthetic", "page": 1, "image": {"w": 600, "h": 500},
            "scale": {"m_per_px": MPP, "m_per_pt": 0.0352778, "method": "printed 1:100", "confidence": 0.98},
            "items": items}


def test_build_counts_relations_and_area(tmp_path):
    out = pdf_to_ifc.build(_planmap(), tmp_path / "x.ifc", storey_name="Level 2", storey_elevation=3.0)
    f = ifcopenshell.open(str(out))
    assert f.schema == "IFC4"
    assert len(f.by_type("IfcWall")) == 4
    assert len(f.by_type("IfcOpeningElement")) == 2
    assert len(f.by_type("IfcDoor")) == 1 and len(f.by_type("IfcWindow")) == 1
    assert len(f.by_type("IfcSpace")) == 1 and len(f.by_type("IfcSlab")) == 1
    for o in f.by_type("IfcOpeningElement"):
        assert o.VoidsElements and o.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")
        assert o.HasFillings
    door, win = f.by_type("IfcDoor")[0], f.by_type("IfcWindow")[0]
    assert door.OverallWidth == pytest.approx(0.9) and door.OverallHeight == pytest.approx(2.1)
    assert win.OverallHeight == pytest.approx(1.2)  # sill 0.9, head 2.1
    sp = f.by_type("IfcSpace")[0]
    assert sp.Name == "1.01" and sp.LongName == "Living"
    q = uel.get_psets(sp)["Qto_SpaceBaseQuantities"]
    assert q["NetFloorArea"] == pytest.approx(19.5)  # printed wins
    assert q["GrossFloorArea"] == pytest.approx(19.2)
    st = f.by_type("IfcBuildingStorey")[0]
    assert st.Name == "Level 2" and st.Elevation == pytest.approx(3.0)
    assert uel.get_psets(door)["Hologram_Provenance"]["source"] == "pdf_vector"
    assert uel.get_psets(door)["Pset_DoorCommon"]["IsExternal"] is True
    assert pdf_to_ifc.validate(out)["openings_not_voiding_wall"] == 0


def test_guids_stable_and_link_planmap(tmp_path):
    pm = _planmap()
    a = pdf_to_ifc.build(pm, tmp_path / "a.ifc")
    b = pdf_to_ifc.build(pm, tmp_path / "b.ifc")
    ga = sorted(e.GlobalId for e in ifcopenshell.open(str(a)).by_type("IfcRoot") if e.is_a("IfcProduct"))
    gb = sorted(e.GlobalId for e in ifcopenshell.open(str(b)).by_type("IfcProduct"))
    assert ga == gb
    door = ifcopenshell.open(str(a)).by_type("IfcDoor")[0]
    assert door.GlobalId == pdf_to_ifc.guid_for("synthetic", "door-001", 1)
    p = tmp_path / "planmap-1.json"
    p.write_text(json.dumps(pm))
    assert pdf_to_ifc.link_planmap(p) == 7
    assert pdf_to_ifc.link_planmap(p) == 7  # idempotent
    items = {(i.get("props") or {}).get("pdf_item_id", i["item_id"]): i for i in json.loads(p.read_text())["items"]}
    assert items["door-001"]["item_id"] == door.GlobalId
    assert items["text-001"]["item_id"] == "text-001"


def test_gap_opening_without_wall_gets_filler_and_no_scale_raises(tmp_path):
    pm = _planmap()
    pm["items"] = [i for i in pm["items"] if i["kind"] != "wall"]
    out = pdf_to_ifc.build(pm, tmp_path / "g.ifc")
    v = pdf_to_ifc.validate(out)
    assert v["IfcWall"] == 2 and v["openings_not_voiding_wall"] == 0
    pm["scale"] = {}
    with pytest.raises(ValueError):
        pdf_to_ifc.build(pm, tmp_path / "n.ifc")
