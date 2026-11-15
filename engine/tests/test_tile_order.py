import math
from engine.order import answer_order
from engine.solvers.data import Doc, Item


def _doc():
    return Doc("t", "ifc", [
        Item("b", "room", name="Bathroom", q={"net_floor_area_m2": 4.5396}),
        Item("l", "room", name="Laundry closet", q={"net_floor_area_m2": 3.2592}),
        Item("p", "room", name="Porch", q={"net_floor_area_m2": 5.95}),
    ], storeys=[])


def test_tile_count_from_size_and_waste_with_steps():
    res = answer_order("Order bathroom floor tiles, 300 x 300 mm, with 10% waste", _doc())
    t = res["answer"]["text_md"]
    assert "56 tiles" in t and "11.11 tiles per m²" in t and "rounded up" in t
    assert res["answer"]["value"] == 5.0   # area incl. waste, rounded up to 0.01


def test_pack_rounding():
    res = answer_order("Order bathroom floor tiles, 300 x 300 mm, 10 tiles per box, with 10% waste", _doc())
    assert "6 packs" in res["answer"]["text_md"]


def test_exclusion_is_honoured():
    res = answer_order("Order floor tiles for all rooms excluding the porch, 300 x 300 mm, 10% waste", _doc())
    assert "Left out as asked" in res["answer"]["text_md"]
    assert res["answer"]["value"] == math.ceil((4.5396 + 3.2592) * 1.1 * 100) / 100


def _plan():
    # Generated for demo: two bathroom-type boxes; the second holds a printed LAUNDRY CLOSET label.
    mk = lambda i, n, b, t: Item(i, "room", name=t, bbox_px=b, conf=.9, props={"room_type": "bathroom", "area_m2_geom_bbox": 1.0})
    items = [mk("b", 0, [0, 0, 100, 100], "bathroom"), mk("w", 1, [200, 0, 300, 100], "wc"),
             Item("t1", "text", label="LAUNDRY CLOSET", bbox_px=[230, 40, 270, 60], conf=.9)]
    for r in items[:2]:
        r.q = {"area_m2": 4.0 if r.item_id == "b" else 3.0}
    return Doc("p", "planmap", items, scale={"m_per_px": .01, "method": "printed"})


def test_printed_label_inside_room_excludes_it_even_if_type_misread():
    res = answer_order("Order bathroom floor tiles, 300 x 300 mm, 10% waste. Use the bathroom, not the laundry closet.", _plan())
    assert res["answer"]["value"] == 4.4


def test_unlabelled_bathroom_type_room_dropped_when_exclusion_names_nothing():
    d = _plan()
    d.items = [i for i in d.items if i.kind != "text"]
    d.items[0].label = "BATHROOM"
    res = answer_order("Order bathroom floor tiles with 10% waste, not the laundry closet.", d)
    assert res["answer"]["value"] == 4.4
    assert "only the labelled bathroom" in res["answer"]["text_md"]


def test_overlapping_boxes_counted_once():
    d = _plan()
    d.items = [i for i in d.items if i.kind == "room"]
    d.items[1].bbox_px = [50, 0, 150, 100]   # half overlaps the first box
    res = answer_order("Order floor tiles with 0% waste", d)
    assert "counted once" in res["answer"]["text_md"] or "no area is counted twice" in res["answer"]["text_md"]
    assert res["answer"]["value"] == 1.5
