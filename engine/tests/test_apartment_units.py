"""Generated-for-demo CAD fixtures; no benchmark drawings or counts."""
import json

import ezdxf
import pytest

from engine.solvers import solve
from engine.solvers.apartment import centroid, indoor_rooms
from engine.solvers.data import Doc, Item
from pipeline.dxf_planmap import process
from pipeline.dxf_units import analyse, outdoor_room, unit_key


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def drawing(tmp_path, rooms, units, texts, *, unit_code=6):
    doc = ezdxf.new()
    doc.units = unit_code
    ms = doc.modelspace()
    for layer, shapes in [("ROOM_OUTLINE", rooms), ("UNIT_OUTLINE", units)]:
        for shape in shapes:
            ms.add_lwpolyline(shape, close=True, dxfattribs={"layer": layer})
    for text, x, y in texts:
        ms.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (x, y)})
    art = tmp_path / "generated-for-demo"
    art.mkdir()
    (art / "pages.json").write_text(json.dumps({"source": "dxf", "pages": [{"w": 3000, "h": 3000}]}))
    path = art / "drawing.dxf"
    doc.saveas(path)
    process(art.name, art, path)
    return json.loads((art / "planmap-1.json").read_text())


@pytest.mark.parametrize("label", ["Whg. A", "App. A", "Appt. A", "Apt A", "Wohnung A", "Appartement A", "Appartamento A", "Logement A", "unit A", "Asunto A", "Huoneisto A", "Lgh. A", "Lägenhet A"])
def test_multilingual_unit_membership_and_evidence(tmp_path, label):
    pm = drawing(tmp_path, [rect(0, 0, 4, 3)], [rect(-1, -1, 6, 5)],
                 [(label, 1, 2), ("Zimmer", 1, 1)])
    room = next(i for i in pm["items"] if i["kind"] == "room")
    unit = next(i for i in pm["items"] if i["props"].get("role") == "unit")
    assert room["label"] == "Zimmer"
    assert room["props"]["unit_item_id"] == unit["item_id"]
    assert room["props"]["unit_membership_method"] == "label"
    answer = solve("What is the net floor area of apartment A?", "generated-for-demo", root=tmp_path)
    assert answer["answer"]["value"] == 12
    assert answer["cost"]["usd_total"] == 0
    assert answer["citations"][0]["item_ids"] == [room["item_id"]]
    assert answer["evidence"]["boxes"][0]["item_id"] == room["item_id"]


def test_nested_voids_toggle_area_and_keep_proof(tmp_path):
    pm = drawing(tmp_path, [rect(0, 0, 10, 10), rect(2, 2, 6, 6), rect(3, 3, 2, 2)],
                 [rect(-1, -1, 12, 12)], [("Whg. A", 1, 1), ("Wohnen", 1, 2), ("68.00 m²", 1, 3)])
    rooms = [i for i in pm["items"] if i["kind"] == "room"]
    assert len(rooms) == 1
    props = rooms[0]["props"]
    assert props["area_m2_geom"] == 100 - 36 + 4
    assert props["void_area_m2"] == 32
    assert props["area_crosscheck"]["agrees_at_written_precision"]
    assert len(props["void_polygons_px"]) == 2
    voids = [i for i in pm["items"] if i["props"].get("role") == "room_void"]
    assert len(voids) == 2
    assert all(i["props"]["parent_room_item_id"] == rooms[0]["item_id"] for i in voids)


def test_explicit_endpoint_closure_without_dxf_closed_bit(tmp_path):
    drawing(tmp_path, [rect(0, 0, 4, 3)], [rect(-1, -1, 6, 5)], [("App. A", 1, 2), ("Room", 1, 1)])
    art = tmp_path / "generated-for-demo"
    doc = ezdxf.readfile(art / "drawing.dxf")
    unit = doc.modelspace().query('LWPOLYLINE[layer=="UNIT_OUTLINE"]')[0]
    pts = list(unit.get_points("xy"))
    unit.set_points(pts + pts[:1])
    unit.closed = False
    doc.saveas(art / "drawing.dxf")
    process(art.name, art, art / "drawing.dxf")
    answer = solve("What is the net floor area of apartment A?", art.name, root=tmp_path)
    assert answer["answer"]["value"] == 12


def test_open_unit_outline_is_retained_with_invalid_geometry_flag():
    rooms, units = analyse([rect(0, 0, 4, 3)], [("Room", 1, 1)],
                           [rect(-1, -1, 6, 5)], [("App. A", 1, 2)], 1, unit_closed=[False])
    assert len(units) == 1
    assert not units[0]["props"]["geometry_valid"]
    assert units[0]["props"]["area_m2_geom"] is None
    assert rooms[0]["props"]["unit_index"] is None


def test_unit_assignment_uses_label_before_centroid():
    # The large part of this room is in B, but its room label is in A.
    rooms, _ = analyse([rect(0, 0, 10, 2)], [("Room", 1, 1)],
                       [rect(0, 0, 2, 3), rect(2, 0, 9, 3)], [], 1)
    assert rooms[0]["props"]["unit_index"] == 0
    assert rooms[0]["props"]["unit_membership_method"] == "label"


def test_centroid_fallback_uses_polygon_not_bounding_box():
    shape = [(0, 0), (6, 0), (6, 1), (1, 1), (1, 6), (0, 6)]
    assert centroid(shape) == pytest.approx((20.5 / 11, 20.5 / 11))
    rooms, _ = analyse([shape], [], [rect(0, 0, 2.5, 2.5)], [], 1)
    assert rooms[0]["props"]["unit_index"] == 0
    assert rooms[0]["props"]["unit_membership_method"] == "centroid"


def test_overlapping_units_do_not_choose_arbitrarily():
    rooms, _ = analyse([rect(0, 0, 4, 4)], [("Room", 1, 1)],
                       [rect(0, 0, 5, 5), rect(0, 0, 6, 6)], [], 1)
    assert rooms[0]["props"]["unit_index"] is None
    assert rooms[0]["props"]["unit_membership_method"] == "ambiguous"


@pytest.mark.parametrize("name", ["Balkon", "Balcon", "Balcone", "Balcony", "Loggia", "Terrasse", "Terrazza", "Terrace", "Dachterrasse", "Sitzplatz", "Veranda", "Wintergarten", "Jardin", "Garten", "Giardino", "Patio", "Parveke", "Balkong"])
def test_multilingual_outdoor_names(name):
    assert outdoor_room(name)
    assert not outdoor_room("Zimmer")


def test_outdoor_rooms_are_excluded_from_apartment_area(tmp_path):
    drawing(tmp_path, [rect(0, 0, 4, 3), rect(4, 0, 2, 3)], [rect(-1, -1, 8, 5)],
            [("App. A", 1, 2), ("Soggiorno", 1, 1), ("Terrazza", 5, 1)])
    answer = solve("What is the net floor area of apartment A?", "generated-for-demo", root=tmp_path)
    assert answer["answer"]["value"] == 12
    assert len(answer["evidence"]["boxes"]) == 1


@pytest.mark.parametrize("unit_code,factor", [(6, 1), (4, .001), (1, .0254), (2, .3048)])
def test_geometry_area_respects_declared_units(tmp_path, unit_code, factor):
    pm = drawing(tmp_path, [rect(0, 0, 100, 100), rect(10, 10, 20, 20)], [],
                 [("Room", 1, 1)], unit_code=unit_code)
    room = next(i for i in pm["items"] if i["kind"] == "room")
    assert room["props"]["area_m2_geom"] == pytest.approx(9600 * factor ** 2, abs=0.5e-6)


def test_written_area_disagreement_is_preserved():
    rooms, _ = analyse([rect(0, 0, 4, 3)], [("Room", 1, 1), ("10,0 m²", 1, 2)], [], [], 1)
    props = rooms[0]["props"]
    assert props["area_m2_label"] == 10
    assert props["area_m2_geom"] == 12
    assert props["area_crosscheck"] == {"difference_m2": 2, "agrees_at_written_precision": False}


def test_invalid_outline_does_not_invent_area():
    rooms, _ = analyse([[(0, 0), (3, 3), (0, 3), (3, 0)]], [], [], [], 1)
    assert rooms[0]["props"]["area_m2_geom"] is None
    assert not rooms[0]["props"]["geometry_valid"]


def test_missing_units_do_not_infer_apartment_labels():
    assert unit_key("App. Kitchen") is None
    assert unit_key("Appt. AB102") == "ab102"
    assert unit_key("Whg.") is None
    assert unit_key("Wohnen") is None
    rooms, units = analyse([rect(0, 0, 4, 3)], [("Room", 1, 1)], [], [], None)
    assert units == []
    assert rooms[0]["props"]["unit_index"] is None
    assert rooms[0]["props"]["area_m2_geom"] is None


def test_missing_member_area_prevents_partial_total():
    unit = Item("unit", "other", label="App. A", polygon_px=rect(0, 0, 10, 10), props={"role": "unit"})
    rooms = [Item("room", "room", label="Bedroom", polygon_px=rect(1, 1, 3, 3))]
    found, missing = indoor_rooms(Doc("generated-for-demo", "planmap", [unit, *rooms]), unit)
    assert not found
    assert missing == rooms


def test_unlabelled_standalone_outlines_keep_geometry_but_flag_uncertainty(tmp_path):
    drawing(tmp_path, [rect(0, 0, 4, 3), rect(5, 0, 2, 2)], [rect(-1, -1, 9, 5)],
            [("App. A", 1, 2), ("Room", 1, 1)])
    answer = solve("What is the net floor area of apartment A?", "generated-for-demo", root=tmp_path)
    assert answer["answer"]["value"] == 16
    assert answer["answer"]["confidence"] == .4
    assert "unlabelled outlines" in answer["answer"]["text_md"]
    from engine.reasoning import attach
    attach(answer, answer["question"], tmp_path)
    assert answer["reasoning"]["confidence"]["label"] == "Estimate"
    assert "unknown" in answer["reasoning"]["confidence"]["reason"]


def test_uncertain_total_still_exposes_written_area_crosscheck():
    from engine.solvers.apartment import uncertain_hint
    rooms = [Item("unknown", "room", conf=.4, props={"classification": "unlabelled"}),
             Item("labelled", "room", props={"area_crosscheck": {"agrees_at_written_precision": False}})]
    hint = uncertain_hint(rooms, 20)
    assert hint["steps"][-1]["ok"] is False
    assert "0 of 1 written room areas" in hint["steps"][-1]["text"]


def test_duplicate_apartment_labels_do_not_select_first(tmp_path):
    drawing(tmp_path, [rect(0, 0, 4, 3)], [rect(-1, -1, 6, 5), rect(10, 0, 6, 5)],
            [("App. A", 1, 2), ("Room", 1, 1), ("App. A", 11, 1)])
    answer = solve("What is the net floor area of apartment A?", "generated-for-demo", root=tmp_path)
    assert answer["answer"]["abstained"]
    assert "More than one" in answer["answer"]["text_md"]
