"""F-WETROOM: compound wet-room labels ("KHH+PH") and wet labels with no room outline."""
from pipeline.room_labels import label_type, wet_label_rooms
from engine.solvers.data import Item


def test_compound_label_wet_wins():
    assert label_type("KHH+PH") == "bathroom"
    assert label_type("WC/KPH") in ("wc", "bathroom")
    assert label_type("KHH") == "storage"
    assert label_type("OH + RT + K") == "living"
    assert label_type("PESUH") == "bathroom"
    assert label_type("Ikrc") is None


def _items(text_box=(247, 802, 316, 825), toilet=(245, 858, 289, 886), room=None):
    its = [Item("text-1", "text", "KHH+PH", bbox_px=list(text_box), conf=.9),
           Item("toilet-1", "toilet", bbox_px=list(toilet), conf=.9)]
    if room:
        its.append(Item("room-1", "room", bbox_px=room, polygon_px=None, conf=.9))
    return its


def test_orphan_wet_label_with_fixture_counts():
    out = wet_label_rooms(_items())
    assert len(out) == 1 and out[0].props["room_type"] == "bathroom" and out[0].label == "KHH+PH"
    assert out[0].props["evidence_items"] == ["text-1", "toilet-1"]


def test_no_fixture_no_room():
    its = [i for i in _items() if i.kind != "toilet"]
    assert wet_label_rooms(its) == []
    far = _items(toilet=(900, 1500, 940, 1540))
    assert wet_label_rooms(far) == []


def test_label_inside_room_outline_not_duplicated():
    assert wet_label_rooms(_items(room=[200, 780, 400, 900])) == []


def test_dry_label_never_synthesised():
    its = _items()
    its[0].label = "MH"
    assert wet_label_rooms(its) == []
