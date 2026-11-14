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


def test_guessed_scale_area_gets_caveat_and_low_confidence():
    d = doc([room(i, 12 + i, "KITCHEN") for i in range(4)] + [Item(item_id=f"door-{i}", kind="door", bbox_px=[0, 0, 1, 1]) for i in range(3)])
    r = rs.guard(res(28.4, ["room-0"], text="The largest room is **KITCHEN** at **28.4 m²**."), "what is the largest room", d)
    t = r["answer"]["text_md"]
    assert "Areas are estimated from door sizes because no printed scale was found, so treat them as approximate." in t
    assert r["answer"]["confidence"] <= 0.4 and t.count("estimated from door sizes") == 1


def test_printed_scale_has_no_caveat():
    d = doc([room(i, 12 + i) for i in range(4)], method="scalebar", conf=0.9)
    r = rs.guard(res(13, ["room-0"], text="Area **13 m²**."), "area of the largest room", d)
    assert "door sizes" not in r["answer"]["text_md"] and r["answer"]["confidence"] == 0.8


def test_duplicate_label_areas_are_not_totalled():
    from engine.analytics import named_rooms
    import time
    d = doc([room(i, 25 + i, "KITCHEN") for i in range(3)])
    a = named_rooms("how much area do the kitchens take", d, time.perf_counter())
    t = a["answer"]["text_md"]
    assert "not added them up" in t and "total" not in t.lower().split("i have not")[0]


def test_undercounted_rooms_show_sparse_note():
    txt = [Item(item_id=f"t{i}", kind="text", label=w, bbox_px=[0, 0, 1, 1]) for i, w in enumerate(["KITCHEN", "BEDROOM", "BATH", "LIVING", "HALL"])]
    d = doc([room(1, 12), room(2, 14), room(3, 9)] + txt + [Item(item_id=f"d{i}", kind="door", bbox_px=[0, 0, 1, 1]) for i in range(4)])
    r = rs.guard(res(3, [], unit="count", text="There are **3 rooms**."), "how many rooms are there", d)
    assert "automatic reader found 3 rooms" in r["answer"]["text_md"]
