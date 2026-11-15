"""pdf_to_ifc: synthetic plan map (4 walls, 1 door, 1 window, 1 room) -> IFC4 with voids, fillings, space area."""
import json

import ifcopenshell
import ifcopenshell.util.element as uel
import pytest

from pipeline import pdf_to_ifc


def _slabs(f):
    """Floor slabs only: the enrich pass may add a ROOF slab under an IfcRoof (PDF_IFC_ROOF, default on)."""
    return [s for s in f.by_type("IfcSlab") if uel.get_predefined_type(s) != "ROOF"]

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
    assert len(f.by_type("IfcSpace")) == 1 and len(_slabs(f)) == 1
    for o in f.by_type("IfcOpeningElement"):
        assert o.VoidsElements and o.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")
        assert o.HasFillings
    door, win = f.by_type("IfcDoor")[0], f.by_type("IfcWindow")[0]
    assert door.OverallWidth == pytest.approx(0.9) and door.OverallHeight == pytest.approx(2.1)
    assert win.OverallHeight == pytest.approx(1.2)  # sill 0.9, head 2.1
    sp = f.by_type("IfcSpace")[0]
    assert sp.Name == "1.01" and sp.LongName == "Living"
    q = uel.get_psets(sp)["Qto_SpaceBaseQuantities"]
    assert q["NetFloorArea"] == pytest.approx(19.2)  # measured, like a native export (PDF_IFC_NET_AREA=measured)
    assert q["GrossFloorArea"] == pytest.approx(19.2)
    assert uel.get_psets(sp)["Hologram_RoomArea"]["PrintedArea"] == pytest.approx(19.5)
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


def test_gap_opening_without_wall_no_filler_by_default_and_no_scale_raises(tmp_path, monkeypatch):
    pm = _planmap()
    pm["items"] = [i for i in pm["items"] if i["kind"] != "wall"]
    # DATA RULE: no wall without drawn linework; the unhosted openings are listed, not walled in
    out = pdf_to_ifc.build(pm, tmp_path / "g.ifc")
    assert pdf_to_ifc.validate(out)["IfcWall"] == 0
    monkeypatch.setattr(pdf_to_ifc, "WG_FILLERS", True)  # PDF_IFC_FILLERS=1: the old filler walls
    out = pdf_to_ifc.build(pm, tmp_path / "g2.ifc")
    v = pdf_to_ifc.validate(out)
    assert v["IfcWall"] == 2 and v["openings_not_voiding_wall"] == 0
    pm["scale"] = {}
    with pytest.raises(ValueError):
        pdf_to_ifc.build(pm, tmp_path / "n.ifc")


def _cl_wall(i, a, b, t_px=20):
    (x0, y0), (x1, y1) = a, b
    h = t_px / 2
    if y0 == y1:
        poly = _rect(min(x0, x1), y0 - h, max(x0, x1), y0 + h)
    else:
        poly = _rect(x0 - h, min(y0, y1), x0 + h, max(y0, y1))
    return {"item_id": f"wall-{i:03d}", "kind": "wall", "polygon_px": poly, "bbox_px": [*poly[0], *poly[2]],
            "props": {"thickness_m": t_px * MPP, "centerline_px": [list(a), list(b)], "style": "double"},
            "conf": 0.9, "source": "pdf_vector"}


def _graph_planmap():
    # 6 m x 4 m box drawn as broken pieces: the bottom wall is split by a door gap (200-290) and a small break
    # (400-420), the right wall stops 30 cm short of the corner, a window sits in a gap the reader left empty
    # with no jamb walls on its line (left wall missing between 150 and 270)
    W = [((10, 10), (610, 10)),
         ((10, 410), (200, 410)), ((290, 410), (400, 410)), ((420, 410), (610, 410)),
         ((610, 40), (610, 410)),
         ((10, 10), (10, 150)), ((10, 270), (10, 410))]
    items = [_cl_wall(i + 1, a, b) for i, (a, b) in enumerate(W)]
    items.append({"item_id": "door-001", "kind": "door", "polygon_px": _rect(200, 400, 290, 420),
                  "bbox_px": [200, 400, 290, 420], "props": {"width_m": 0.9, "leaf": True, "operation": "SINGLE_SWING_RIGHT", "swing_dir": [0, -1]},
                  "conf": 0.9, "source": "pdf_vector"})
    items.append({"item_id": "door-002", "kind": "door", "polygon_px": _rect(300, 0, 440, 20),
                  "bbox_px": [300, 0, 440, 20], "props": {"width_m": 1.4, "sliding": True, "n_leaves": 2},
                  "conf": 0.9, "source": "pdf_vector"})
    items.append({"item_id": "window-001", "kind": "window", "polygon_px": _rect(0, 160, 20, 260),
                  "bbox_px": [0, 160, 20, 260], "props": {"width_m": 1.0}, "conf": 0.8, "source": "pdf_vector"})
    items.append({"item_id": "room-001", "kind": "room", "label": "Living", "polygon_px": _rect(20, 20, 600, 400),
                  "bbox_px": [20, 20, 600, 400], "props": {"number": "1.01"}, "conf": 0.85, "source": "pdf_vector"})
    pm = _planmap()
    pm["items"] = items
    return pm


def test_wall_graph_merges_joins_and_hosts(tmp_path):
    out = pdf_to_ifc.build(_graph_planmap(), tmp_path / "w.ifc")
    f = ifcopenshell.open(str(out))
    walls = f.by_type("IfcWall")
    # top, bottom (3 pieces -> 1), right, left (2 pieces + the window gap -> 1)
    assert len(walls) == 4, [w.Name for w in walls]
    assert all(w.is_a("IfcWallStandardCase") for w in walls)
    lens = sorted(uel.get_psets(w)["Qto_WallBaseQuantities"]["Length"] for w in walls)
    assert lens[-1] == pytest.approx(6.0, abs=0.01) and lens[-2] == pytest.approx(6.0, abs=0.01)
    assert lens[0] == pytest.approx(4.0, abs=0.01) and lens[1] == pytest.approx(4.0, abs=0.01)
    conns = f.by_type("IfcRelConnectsPathElements")
    assert len(conns) == 4
    assert {(c.RelatingConnectionType, c.RelatedConnectionType) for c in conns} <= {
        ("ATSTART", "ATSTART"), ("ATSTART", "ATEND"), ("ATEND", "ATSTART"), ("ATEND", "ATEND")}
    for e in f.by_type("IfcDoor") + f.by_type("IfcWindow"):
        assert e.FillsVoids and e.FillsVoids[0].RelatingOpeningElement.VoidsElements
    ops = {d.Name: uel.get_type(d).OperationType for d in f.by_type("IfcDoor")}
    assert all(d.OperationType is None and d.PredefinedType is None for d in f.by_type("IfcDoor"))
    assert sorted(ops.values()) == ["DOUBLE_DOOR_SLIDING", "SINGLE_SWING_RIGHT"]
    win = f.by_type("IfcWindow")[0]
    assert win.OverallWidth == pytest.approx(1.0)
    usage = uel.get_material(walls[0])
    assert usage.is_a("IfcMaterialLayerSetUsage") and usage.OffsetFromReferenceLine == pytest.approx(-0.1)
    # mitred corners: total footprint = outer ring minus inner ring, no overlap
    a = sum(uel.get_psets(w)["Qto_WallBaseQuantities"]["NetFootprintArea"] for w in walls)
    assert a == pytest.approx(6.2 * 4.2 - 5.8 * 3.8, rel=0.01)
    slab = _slabs(f)[0]
    assert uel.get_psets(slab)["Qto_SlabBaseQuantities"]["GrossArea"] == pytest.approx(6.2 * 4.2, rel=0.03)
    assert pdf_to_ifc.build.last_stats["storeys"][0]["wall_graph_error"] is None


def test_duplicates_glass_in_wall_touch_joins_names_and_storey(tmp_path):
    pm = _graph_planmap()
    items = pm["items"]
    # the top wall drawn a second time, thinner, over its left 2 m (duplicate -> dropped)
    items.append(_cl_wall(90, (10, 10), (210, 10), t_px=12))
    # a glass panel the openings reader tagged as a partition, lying inside the right wall (-> window in that wall)
    items.append({"item_id": "glass-001", "kind": "window", "polygon_px": _rect(605, 200, 615, 300),
                  "bbox_px": [605, 200, 615, 300], "props": {"kind": "glass_partition"}, "conf": 0.8,
                  "source": "pdf_vector"})
    # a short wall continuing the bottom wall to the right, thicker, end to end (no L/T: touch connection)
    items.append(_cl_wall(91, (620, 410), (800, 410), t_px=30))
    # unnumbered, unlabelled room: no placeholder name
    items.append({"item_id": "room-002", "kind": "room", "polygon_px": _rect(620, 300, 800, 400),
                  "bbox_px": [620, 300, 800, 400], "props": {"room_type": "other"}, "conf": 0.6,
                  "source": "pdf_vector"})
    pm["provenance"] = {"storey": {"name": "BASEMENT", "elevation_m": -3.5, "source": "title"}}
    out = pdf_to_ifc.build(pm, tmp_path / "d.ifc")
    f = ifcopenshell.open(str(out))
    walls = f.by_type("IfcWall")
    assert len(walls) == 5, [w.Name for w in walls]
    wins = f.by_type("IfcWindow")
    assert len(wins) == 2
    g = next(w for w in wins if w.GlobalId == pdf_to_ifc.guid_for("synthetic", "glass-001", 1))
    assert g.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")
    assert g.OverallWidth == pytest.approx(1.0, abs=0.05)
    conns = f.by_type("IfcRelConnectsPathElements")
    connected = {c.RelatingElement.id() for c in conns} | {c.RelatedElement.id() for c in conns}
    assert len(connected) == 5
    sp = {s.GlobalId: s for s in f.by_type("IfcSpace")}
    s1 = sp[pdf_to_ifc.guid_for("synthetic", "room-001", 1)]
    s2 = sp[pdf_to_ifc.guid_for("synthetic", "room-002", 1)]
    assert (s1.Name, s1.LongName) == ("1.01", "Living")
    assert s2.Name == "001" and s2.LongName == "Room"  # unnumbered room gets a generated number (PDF_IFC_SPACE_NUMBERS=1)
    st = f.by_type("IfcBuildingStorey")[0]
    assert st.Name == "Basement" and st.Elevation == pytest.approx(-3.5)
    assert st.ObjectPlacement.RelativePlacement.Location.Coordinates[2] == pytest.approx(0.0)
    v = pdf_to_ifc.validate(out)
    assert v["duplicate_guids"] == 0 and v["fillings_without_opening"] == 0 and v["openings_not_voiding_wall"] == 0
