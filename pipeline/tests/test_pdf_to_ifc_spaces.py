"""pdf_to_ifc spaces / storey / wall types: free printed labels reach their IfcSpace, running numbers for unnumbered
rooms (switch), storey height from the sheet drives wall height, thickness classes give one IfcWallType each."""
import ifcopenshell
import ifcopenshell.util.element as uel
import pytest

from pipeline import pdf_to_ifc

MPP = 0.01


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _planmap(cls=None):
    walls = [_rect(0, 0, 820, 20), _rect(0, 420, 820, 440), _rect(0, 20, 20, 420), _rect(800, 20, 820, 420),
             _rect(400, 20, 410, 420)]
    items = []
    for i, p in enumerate(walls):
        pr = {"thickness_m": 0.1 if i == 4 else 0.2}
        if cls:
            pr["thickness_class"] = cls[i]
        items.append({"item_id": f"wall-{i + 1:03d}", "kind": "wall", "polygon_px": p,
                      "bbox_px": [p[0][0], p[0][1], p[2][0], p[2][1]], "props": pr, "conf": 0.9})
    items.append({"item_id": "room-001", "kind": "room", "label": "Office", "polygon_px": _rect(20, 20, 400, 420),
                  "bbox_px": [20, 20, 400, 420], "props": {"number": "A101"}, "q": {"area_m2": 15.2}})
    items.append({"item_id": "room-002", "kind": "room", "label": None, "polygon_px": _rect(410, 20, 800, 420),
                  "bbox_px": [410, 20, 800, 420], "props": {"number": None}, "q": {"area_m2": 15.6}})
    # free labels the rooms reader did not attach: name and number inside room-002, partly overlapping the wall
    items.append({"item_id": "text-001", "kind": "text", "label": "MEETING ROOM", "bbox_px": [395, 200, 600, 220],
                  "props": {"role": "room_label"}})
    items.append({"item_id": "text-002", "kind": "text", "label": "A102", "bbox_px": [500, 240, 540, 260],
                  "props": {"role": "room_label"}})
    return {"doc_id": "synthetic-spaces", "page": 1, "image": {"w": 900, "h": 500},
            "scale": {"m_per_px": MPP, "m_per_pt": 0.0352778, "method": "printed 1:100", "confidence": 0.98},
            "provenance": {"storey": {"name": "2ND FLOOR", "number": 2, "elevation_m": 9.0, "height_m": 3.5,
                                      "source": "title"}},
            "semantics": {"ceiling_heights_m": [3.05]}, "items": items}


def test_free_labels_storey_height_and_walls(tmp_path):
    out = pdf_to_ifc.build(_planmap(), tmp_path / "x.ifc")
    f = ifcopenshell.open(str(out))
    sp = {s.Name: s for s in f.by_type("IfcSpace")}
    assert sp["A101"].LongName == "Office"
    assert sp["A102"].LongName == "MEETING ROOM"
    assert uel.get_psets(sp["A102"])["Hologram_RoomArea"]["NumberSource"].startswith("printed")
    st = f.by_type("IfcBuildingStorey")[0]
    assert st.Name == "2nd Floor" or st.Name.upper() == "2ND FLOOR"
    assert st.Elevation == pytest.approx(9.0)
    q = uel.get_psets(st)["Qto_BuildingStoreyBaseQuantities"]
    assert q["GrossHeight"] == pytest.approx(3.5)
    for w in f.by_type("IfcWall"):
        assert uel.get_psets(w)["Qto_WallBaseQuantities"]["Height"] == pytest.approx(3.3)


def test_auto_numbers_and_thickness_classes(tmp_path, monkeypatch):
    pm = _planmap(cls=[0.2, 0.2, "200 mm", 200, "partition_100"])
    pm["items"] = [it for it in pm["items"] if it["item_id"] != "text-002"]
    monkeypatch.setattr(pdf_to_ifc, "AUTO_NUMBER_SPACES", True)
    f = ifcopenshell.open(str(pdf_to_ifc.build(pm, tmp_path / "y.ifc")))
    names = sorted(s.Name for s in f.by_type("IfcSpace"))
    assert names == ["2.01", "A101"]
    gen = next(s for s in f.by_type("IfcSpace") if s.Name == "2.01")
    assert uel.get_psets(gen)["Hologram_RoomArea"]["NumberSource"].startswith("generated")
    tnames = {uel.get_type(w).Name for w in f.by_type("IfcWall") if uel.get_type(w)}
    assert {"Wall 200 mm", "Partition 100 mm"} <= tnames


def test_openings_with_no_drawn_wall_are_left_out_and_listed(tmp_path, monkeypatch):
    """DATA RULE: three windows along a stretch with no drawn wall get no invented wall: they are left out of the IFC
    and listed on the storey (Hologram_Unhosted). With PDF_IFC_FILLERS=1 one filler wall hosts all three, marked
    Hologram_Evidence Source 'default'."""
    items = [{"item_id": f"window-{i + 1:03d}", "kind": "window", "polygon_px": _rect(x, 0, x + 100, 20),
              "bbox_px": [x, 0, x + 100, 20], "props": {"width_m": 1.0}, "conf": 0.9} for i, x in enumerate((0, 150, 300))]
    items += [{"item_id": "wall-001", "kind": "wall", "polygon_px": _rect(0, 200, 400, 220),
               "bbox_px": [0, 200, 400, 220], "props": {"thickness_m": 0.2}, "conf": 0.9}]
    pm = {"doc_id": "band", "page": 1, "image": {"w": 500, "h": 300},
          "scale": {"m_per_px": MPP, "m_per_pt": 0.0352778, "method": "printed 1:100", "confidence": 0.98},
          "items": items}
    out = pdf_to_ifc.build(pm, tmp_path / "band.ifc")
    v = pdf_to_ifc.validate(out)
    assert v["IfcWall"] == 1 and v["IfcWindow"] == 0 and v["IfcOpeningElement"] == 0, v
    f = ifcopenshell.open(str(out))
    ps = uel.get_psets(f.by_type("IfcBuildingStorey")[0])
    assert ps["Hologram_Unhosted"]["Count"] == 3 and ps["Hologram_Unhosted"]["ItemIds"].count("window-") == 3
    ev = uel.get_psets(f.by_type("IfcWall")[0])["Hologram_Evidence"]
    assert ev["Source"] == "measured" and "wall-001" in ev["Detail"] and ev["HeightSource"] == "default"
    assert ps["Hologram_Evidence"]["Source"] == "default"  # no level printed
    monkeypatch.setattr(pdf_to_ifc, "WG_FILLERS", True)
    out = pdf_to_ifc.build(pm, tmp_path / "band2.ifc")
    v = pdf_to_ifc.validate(out)
    assert v["IfcWall"] == 2 and v["IfcWindow"] == 3 and v["openings_not_voiding_wall"] == 0, v
    f = ifcopenshell.open(str(out))
    srcs = sorted(uel.get_psets(x)["Hologram_Evidence"]["Source"] for x in f.by_type("IfcWall"))
    assert srcs == ["default", "measured"]


def test_wall_evidence_from_pdf_vector_paths(tmp_path):
    """props.evidence from pdf_vector: Source carried to Hologram_Evidence with the path ids; a merged run is
    measured only if all its pieces are; a wall with no drawn linework (source none) is not emitted, it is listed."""
    def wall(i, x0, x1, ev, y=0):
        return {"item_id": f"wall-{i:03d}", "kind": "wall", "polygon_px": _rect(x0, y, x1, y + 20),
                "bbox_px": [x0, y, x1, y + 20], "props": {"thickness_m": 0.2, "evidence": ev, "style": "double",
                                                          "centerline_px": [[x0, y + 10], [x1, y + 10]]}, "conf": 0.9}
    items = [wall(1, 0, 200, {"source": "measured", "paths": [11, 12], "n_paths": 2}),
             wall(2, 210, 400, {"source": "derived", "paths": [13], "n_paths": 1}),       # same line: merged run
             wall(3, 0, 400, {"source": "measured", "paths": [21, 22], "n_paths": 2}, y=300),
             wall(4, 0, 400, {"source": "none", "paths": [], "n_paths": 0}, y=600)]
    pm = {"doc_id": "ev", "page": 1, "image": {"w": 500, "h": 700},
          "scale": {"m_per_px": MPP, "m_per_pt": 0.0352778, "method": "printed 1:100", "confidence": 0.98},
          "items": items}
    out = pdf_to_ifc.build(pm, tmp_path / "ev.ifc")
    f = ifcopenshell.open(str(out))
    evs = sorted((uel.get_psets(x)["Hologram_Evidence"]["Source"], uel.get_psets(x)["Hologram_Evidence"]["Detail"])
                 for x in f.by_type("IfcWall"))
    assert len(evs) == 2, evs
    assert evs[0][0] == "derived" and "paths 11,12,13" in evs[0][1]
    assert evs[1][0] == "measured" and "paths 21,22" in evs[1][1]
    dropped = uel.get_psets(f.by_type("IfcBuildingStorey")[0])["Hologram_Dropped"]
    assert dropped["Count"] == 1 and dropped["ItemIds"] == "wall-004"


def test_glass_partition_inside_a_wall_is_not_a_window(tmp_path):
    """A glazed panel (props.kind glass_partition) lying inside a drawn wall run: in an interior wall it stays that
    wall (Hologram_Glazing with its span), never an IfcWindow; in the facade it stays a window."""
    def wall(i, a, b):
        (x0, y0), (x1, y1) = a, b
        poly = _rect(x0 - 10, y0, x0 + 10, y1) if x0 == x1 else _rect(x0, y0 - 10, x1, y0 + 10)
        return {"item_id": f"wall-{i:03d}", "kind": "wall", "polygon_px": poly, "bbox_px": [*poly[0], *poly[2]],
                "props": {"thickness_m": 0.2, "centerline_px": [list(a), list(b)], "style": "double"}, "conf": 0.9}
    items = [wall(1, (10, 10), (610, 10)), wall(2, (10, 410), (610, 410)), wall(3, (10, 10), (10, 410)),
             wall(4, (610, 10), (610, 410)), wall(5, (310, 10), (310, 410)),
             {"item_id": "glass-001", "kind": "window", "polygon_px": _rect(305, 200, 315, 300),   # interior wall
              "bbox_px": [305, 200, 315, 300], "props": {"kind": "glass_partition"}, "conf": 0.8},
             {"item_id": "glass-002", "kind": "window", "polygon_px": _rect(605, 200, 615, 300),   # facade
              "bbox_px": [605, 200, 615, 300], "props": {"kind": "glass_partition"}, "conf": 0.8}]
    pm = {"doc_id": "glass", "page": 1, "image": {"w": 700, "h": 500},
          "scale": {"m_per_px": MPP, "m_per_pt": 0.0352778, "method": "printed 1:100", "confidence": 0.98},
          "items": items}
    f = ifcopenshell.open(str(pdf_to_ifc.build(pm, tmp_path / "glass.ifc")))
    wins = f.by_type("IfcWindow")
    assert [x.GlobalId for x in wins] == [pdf_to_ifc.guid_for("glass", "glass-002", 1)]
    glazed = [w for w in f.by_type("IfcWall") if uel.get_psets(w).get("Hologram_Glazing")]
    assert len(glazed) == 1 and uel.get_psets(glazed[0])["Hologram_Provenance"]["item_id"] == "wall-005"
    assert uel.get_psets(glazed[0])["Hologram_Glazing"]["GlazedSpans"].startswith("glass-001:")


def test_storey_from_page_text_when_analyse_was_cut(tmp_path):
    """semantics.storey / provenance.storey missing (stages cut by the ingest budget): the storey name, level and
    height come from the printed page words (text-<page>.json next to the IFC), marked printed."""
    import json
    walls = [_rect(0, 0, 820, 20), _rect(0, 420, 820, 440), _rect(0, 20, 20, 420), _rect(800, 20, 820, 420)]
    items = [{"item_id": f"wall-{i + 1:03d}", "kind": "wall", "polygon_px": p, "bbox_px": [*p[0], *p[2]],
              "props": {"thickness_m": 0.2}, "conf": 0.9} for i, p in enumerate(walls)]
    pm = {"doc_id": "lv", "page": 1, "image": {"w": 1200, "h": 900},
          "scale": {"m_per_px": MPP, "m_per_pt": 0.0352778, "method": "printed 1:100", "confidence": 0.98},
          "semantics": {"error": "RuntimeError: stopped: ingest budget (analyse, 0 s)",
                        "plan_region": {"polygon_px": _rect(-5, -5, 825, 445)}},
          "items": items}
    words = [{"text": t, "bbox_px": b} for t, b in (
        ("FLOOR", [900, 800, 960, 830]), ("PLAN,", [965, 800, 1020, 830]), ("2ND", [1025, 800, 1060, 830]),
        ("FLOOR", [1065, 800, 1125, 830]),
        ("+9.000", [100, 100, 140, 108]), ("+9.000", [500, 300, 540, 308]), ("+8.400", [1000, 100, 1040, 108]),
        ("h=3050", [300, 200, 330, 208]))]
    (tmp_path / "text-1.json").write_text(json.dumps({"words": words}))
    f = ifcopenshell.open(str(pdf_to_ifc.build(pm, tmp_path / "model.ifc")))
    st = f.by_type("IfcBuildingStorey")[0]
    assert st.Name.upper() == "2ND FLOOR" and st.Elevation == pytest.approx(9.0)
    ev = uel.get_psets(st)["Hologram_Evidence"]
    assert ev["Source"] == "printed" and "+9.000" in ev["Detail"] and "page text" in ev["Detail"]
