import numpy as np
import pytest

from vision.rooms_scale import apply_scale, estimate_scale, label_rooms


def room(box=(0, 0, 100, 100)):
    x0, y0, x1, y1 = box
    return {"kind": "room", "label": None, "polygon_px": [[x0,y0],[x1,y0],[x1,y1],[x0,y1]], "bbox_px": list(box),
            "props": {"area_px": (x1-x0)*(y1-y0), "room_type": "undefined"}}


def text(value, box=(10, 10, 40, 20)):
    return {"text": value, "bbox": list(box)}


def test_printed_area_beats_a_wrong_door_prior():
    rooms = [room(), room((100, 0, 200, 100))]
    doors = [{"bbox_px": [0, 0, 90, 90]}] * 2
    scale = estimate_scale(rooms, [text("100 m²"), text("100 m2", (110,10,150,20))], doors)
    assert scale["m_per_px"] == .1
    assert scale["confidence"] == .8
    apply_scale(rooms, scale)
    assert [r["props"]["area_m2"] for r in rooms] == [100, 100]


def test_imperial_room_area_and_missing_units():
    rooms = [room()]
    scale = estimate_scale(rooms, [text("100 ft²")], [])
    apply_scale(rooms, scale)
    assert rooms[0]["props"]["area_m2"] == pytest.approx(9.29)
    assert estimate_scale([room()], [text("3.20 m")], [])["method"] == "none"
    assert estimate_scale([room()], [text("100")], [])["method"] == "none"


def test_conflicting_or_total_area_is_not_assigned_to_one_room():
    assert estimate_scale([room()], [text("10 m²"), text("20 m²")], [])["method"] == "none"
    assert estimate_scale([room()], [text("TOTAL 200 m²")], [])["method"] == "none"


@pytest.mark.parametrize("label,kind", [("CHAMBRE 2", "bedroom"), ("KITCHEN", "kitchen"), ("KÖK", "kitchen"), ("KÜCHE", "kitchen"), ("MH1", "bedroom")])
def test_multilingual_room_label(label, kind):
    r = room()
    label_rooms([r], [text(label)])
    assert r["label"] == label
    assert r["props"]["room_type"] == kind


def test_semantic_changes_do_not_create_a_wall():
    from vision.scan_rooms import room_regions
    r = np.zeros((100, 100), np.uint8)
    r[10:90, 10:90] = 3
    r[10:90, 50:90] = 4
    out = room_regions(r, np.ones(r.shape), [])
    assert len(out) == 1
    assert out[0]["props"]["area_px"] == 80 * 80


def test_printed_ratio_with_dpi_precedes_door_prior():
    doors = [{"bbox_px": [0, 0, 30, 30]}] * 2
    s = estimate_scale([room()], [text("1:200")], doors, image_size=(2000, 1500), dpi=200)
    assert s["method"] == "dimension"
    assert s["m_per_px"] == pytest.approx(.0254)
    assert "1:200" in s["evidence"]
