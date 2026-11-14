from engine.reasoning_parts import measured
from engine.solvers.data import Item


def _ctx(**kw):
    base = dict(res={}, question="", ans={}, cites=[{"n": 1}], route=None, trace=[], unit="", value=None, doc=None, items={}, cited=[],
                first_cite={}, models_used=False, is_ifc=False, sc=None, scale_w="the printed scale", scale_c=1.0, from_cad=False,
                steps=[], checked=None, area_q=None, rooms=[])
    base.update(kw)
    return base


def _texts(ctx):
    measured.run(ctx)
    return [s["text"] for s in ctx["steps"]]


def test_ifc_single_stored_area():
    it = Item(item_id="r1", kind="room", label="Office", q={"area_m2": 128.27})
    t = _texts(_ctx(unit="m2", value=None, question="area of the largest room", cited=[it], is_ifc=True, first_cite={"r1": 1}))
    assert t == ["Floor area stored in the model's room data: 128.3 m²"]


def test_ifc_bbox_fallback():
    it = Item(item_id="r1", kind="room", bbox_m=[[0, 0, 0], [4, 3, 5]])
    t = _texts(_ctx(unit="m2", value=20.0, cited=[it], is_ifc=True))
    assert "No stored area" in t[0] and "20" in t[0]


def test_raster_single_matches_value():
    poly = [[0, 0], [100, 0], [100, 100], [0, 100]]
    it = Item(item_id="r1", kind="room", label="kitchen", q={"area_m2": 1.0}, polygon_px=poly)
    t = _texts(_ctx(unit="m2", value=1.0, cited=[it], sc={"m_per_px": 0.01}, scale_w="door widths (about 0.9 m each)"))
    assert t == ["Outline 10,000 px² × (0.01 m/px)² = 1 m²; scale from door widths (about 0.9 m each)"]


def test_multi_total_uses_headline_and_top3():
    rooms = [Item(item_id=f"r{i}", kind="room", label=f"R{i}", q={"area_m2": float(i + 1)}) for i in range(5)]
    t = _texts(_ctx(unit="m2", value=15.0, cited=rooms, sc={"m_per_px": 0.01}))
    assert t[0].startswith("Added 5 room outlines: 15.0 m²") and "largest R4 5" in t[0]


def test_kitchens_not_added_when_no_value():
    rooms = [Item(item_id=f"r{i}", kind="room", q={"area_m2": 7.5 + i}) for i in range(2)]
    t = _texts(_ctx(unit="m2", value=None, cited=rooms, sc={"m_per_px": 0.0339}))
    assert "not added together" in t[0]


def test_count_filter_and_plain_count():
    t = _texts(_ctx(unit="count", value=10, trace=[{"step": "filter", "detail": "10 of 77 doors wider than 1 m"}]))
    assert t == ["Kept doors wider than 1 m: 10 of 77"]
    assert _texts(_ctx(unit="count", value=77, trace=[{"step": "count", "detail": "77 door"}])) == []


def test_length_walls_exterior():
    tr = [{"step": "scope", "detail": "exterior walls: 44 left"}, {"step": "length", "detail": "sum over 44 wall = 557.7000 m"}]
    t = _texts(_ctx(unit="m", value=557.7, trace=tr))
    assert t == ["Added the lengths of 44 walls, exterior only: 557.7 m"]


def test_zero_length_no_step():
    assert _texts(_ctx(unit="m", value=0.0, trace=[{"step": "length", "detail": "sum over 0 wall = 0 m"}])) == []


def test_room_area_in_count_explanation_gets_measured_step():
    room = Item("r", "room", label="Bathroom", q={"area_m2": 2.34}, polygon_px=[[0, 0], [100, 0], [100, 234], [0, 234]])
    ctx = _ctx(unit="count", value=1, question="How many bathrooms?", ans={"text_md": "**1 bathroom**, 2.34 m². [1]"},
               cited=[room], sc={"m_per_px": .01}, first_cite={"r": 1})
    texts = _texts(ctx)
    assert "23,400 px²" in texts[0] and "2.34 m²" in texts[0] and "scale from" in texts[0]
    assert ctx["area_q"] and ctx["steps"][0]["cite"] == 1
