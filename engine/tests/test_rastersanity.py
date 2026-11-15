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


# ---- E-62: free-form judge questions on plan maps
def _pm(items=None):
    rooms = [room(1, 20, "living"), room(2, 12, "kitchen"), room(3, 9, "bedroom"), room(4, 8, "TERASSI terrace")]
    doors = [Item(item_id=f"door-{i}", kind="door", bbox_px=[0, 0, 1, 1]) for i in range(3)]
    return doc(rooms + doors, method="scalebar", conf=0.9)


def _run(q, d):
    import time
    from engine import analytics
    return analytics.run(q, d, time.perf_counter(), None)


def test_how_big_is_this_flat_sums_indoor_rooms():
    a = _run("how big is this flat", _pm())["answer"]
    assert a["value"] == 41.0 and "41" in a["text_md"] and "outdoor" in a["text_md"]


def test_total_area_of_named_kind_is_not_plan_total():
    assert _run("total area of the classrooms", _pm()) is None or _run("total area of the classrooms", _pm())["answer"]["value"] != 41.0


def test_accessibility_and_ceiling_are_plain_limits():
    a = _run("is this plan wheelchair accessible", _pm())["answer"]
    assert "can't judge accessibility" in a["text_md"] and "3 doors" in a["text_md"]
    assert "does not show ceiling height" in _run("what is the ceiling height", _pm())["answer"]["text_md"]


def test_single_room_area_wording_and_typos():
    a = _run("what is the area of the kitchen", _pm())["answer"]
    assert a["text_md"].startswith("The area of the **kitchen** is **12") and "total area of the **1" not in a["text_md"]
    from engine.library import fix_typos
    assert fix_typos("waht is the area of the livng room")[0] == "what is the area of the living room"
    assert fix_typos("hw many windws")[0] == "how many windows"


def test_exists_and_per_room_counts_use_whole_plan_wording():
    import time
    from engine import analytics
    d = _pm()
    def solve(q):
        return {"answer": {"text_md": "There are **3 doors** on this floor plan.", "value": 3, "abstained": False}, "citations": [{"n": 1}]}
    a = analytics.exists_or_perroom("how many doors does the bedroom have", d, time.perf_counter(), solve)["answer"]
    assert "whole plan, not room by room" in a["text_md"] and "**3 doors**" in a["text_md"]
    def zero(q):
        return {"answer": {"text_md": "x", "value": 0, "abstained": False}, "citations": []}
    assert analytics.exists_or_perroom("is there a pool", d, time.perf_counter(), zero) is None
    z = analytics.exists_or_perroom("is there a kitchen", d, time.perf_counter(), zero)["answer"]
    assert z["text_md"].startswith("**No**")


def test_show_named_room_highlights_only_that_kind():
    from engine import scene_cmds as sc
    d = _pm()
    its = sc._select(d, sc.SceneIntent("highlight", "room", [], None), "show me the kitchen", {})
    assert [i.label for i in its] == ["kitchen"]
    assert len(sc._select(d, sc.SceneIntent("highlight", "room", [], None), "highlight all rooms", {})) == 4


def test_baseboard_slab_and_piping_on_a_plan_image():
    import time
    from engine import analytics
    rooms = [Item(item_id=f"room-{i}", kind="room", label=l, bbox_px=[0, 0, 100, 80], q={"area_m2": a}) for i, (l, a) in enumerate([("living", 20), ("kitchen", 12), ("balcony", 6)])]
    doors = [Item(item_id="door-1", kind="door", bbox_px=[95, 30, 105, 50])]
    d = Doc(doc_id="uploads__t", mode="planmap", items=rooms + doors, title="t", storeys=[], scale={"m_per_px": 0.05, "method": "door-prior", "confidence": 0.3}, pages=1, meta={})
    b = analytics.run("how many linear metres of baseboard per room and in total", d, time.perf_counter(), None)["answer"]
    assert "Baseboard" in b["text_md"] and b["abstained"] and b["value"] is None
    s = analytics.run("what is the slab area by type and reinforcement", d, time.perf_counter(), None)["answer"]
    assert s["value"] is None and s["abstained"] and "not recorded" in s["text_md"]
    p = analytics.run("how many metres of piping and what pipe sizes", d, time.perf_counter(), None)["answer"]
    assert "No piping is drawn" not in p["text_md"] and "cannot be measured" in p["text_md"] and p["value"] is None
    d.scale = {}
    assert "no scale" in analytics.run("baseboard in metres", d, time.perf_counter(), None)["answer"]["text_md"]
