from engine import rastersanity as rs
from engine.solvers.data import Doc, Item


def room(i, a, label="Room"):
    return Item(item_id=f"room-{i}", kind="room", label=label, bbox_px=[0, 0, 10, 10], q={"area_m2": a})


def doc(items, method="door-prior", conf=0.3, did="uploads__t"):
    return Doc(doc_id=did, mode="planmap", items=items, title="t", storeys=[], scale={"m_per_px": 0.05, "method": method, "confidence": conf}, pages=1, meta={})


def res(value, ids, unit="m2", text="The area is x."):
    return {"answer": {"text_md": text, "value": value, "unit": unit, "abstained": False, "confidence": 0.8},
            "evidence": {"scene": {"highlight_item_ids": ids}}, "trace": []}


def test_tiny_room_from_guessed_scale_is_flagged():
    d = doc([room(1, 0.8), room(2, 20), room(3, 15)])
    r = rs.guard(res(0.8, ["room-1"]), "area of the closet", d)
    assert "scale looks wrong" in r["answer"]["text_md"] and r["answer"]["value"] is None and "0.8 m²" in r["answer"]["text_md"]


def test_huge_plan_from_guessed_scale_is_flagged():
    d = doc([room(1, 900), room(2, 1500), room(3, 20)])
    r = rs.guard(res(900, ["room-1"]), "area of the largest room", d)
    assert "scale looks wrong" in r["answer"]["text_md"] and "2,420" in r["answer"]["text_md"]


def test_printed_scale_is_trusted():
    d = doc([room(1, 0.8), room(2, 20), room(3, 15)], method="scalebar", conf=0.9)
    r = rs.guard(res(0.8, ["room-1"]), "area of the closet", d)
    assert r["answer"]["value"] == 0.8 and "scale looks wrong" not in r["answer"]["text_md"]


def test_plausible_guessed_scale_stays():
    d = doc([room(i, 12 + i) for i in range(4)] + [Item(item_id=f"door-{i}", kind="door", bbox_px=[0, 0, 1, 1]) for i in range(3)])
    r = rs.guard(res(13, ["room-0"]), "area of the largest room", d)
    assert r["answer"]["value"] == 13


def test_sparse_upload_says_what_was_found():
    d = doc([room(1, 20)], method="scalebar", conf=0.9)
    r = rs.guard(res(1, [], unit="count", text="There is **1 room**."), "how many rooms are there", d)
    assert "automatic reader found 1 room, 0 doors and 0 windows" in r["answer"]["text_md"]
    assert "Try: how many rooms are there, where is the room, area of the room." in r["answer"]["text_md"]


def test_non_upload_and_rich_plans_get_no_note():
    d = doc([room(i, 12) for i in range(5)] + [Item(item_id=f"door-{i}", kind="door", bbox_px=[0, 0, 1, 1]) for i in range(4)])
    assert "reader found" not in rs.guard(res(5, [], "count", "x"), "how many rooms", d)["answer"]["text_md"]
    s = doc([room(1, 20)], did="cubicasa5k__x")
    assert "reader found" not in rs.guard(res(1, [], "count", "x"), "how many rooms", s)["answer"]["text_md"]
