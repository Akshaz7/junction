"""E-60: several floor plans on one sheet, quoted labels kept literal, room text inside an outline."""
from types import SimpleNamespace as NS

from engine import storeys
from engine.library import fix_typos
from engine.solvers.solve import _pt_in_poly


def _plan(x0, y0, n=8, size=100):
    out = []
    for k in range(n):
        out.append(NS(kind="wall" if k % 2 else "room", bbox_px=[x0 + (k % 4) * size, y0 + (k // 4) * size, x0 + (k % 4) * size + size, y0 + (k // 4) * size + size], conf=0.9, label=None))
    return out


def test_one_plan_is_one_floor():
    assert storeys.count_storeys(_plan(0, 0))["n"] == 1


def test_two_plans_side_by_side():
    r = storeys.count_storeys(_plan(0, 0) + _plan(700, 0))
    assert r["n"] == 2 and r["basis"] == "layout"


def test_two_plans_stacked():
    assert storeys.count_storeys(_plan(0, 0) + _plan(0, 600))["n"] == 2


def test_tiny_fragment_is_not_a_floor():
    frag = [NS(kind="wall", bbox_px=[900 + k * 5, 0, 905 + k * 5, 5], conf=0.9, label=None) for k in range(8)]
    assert storeys.count_storeys(_plan(0, 0) + frag)["n"] == 1


def test_floor_names_only_when_consecutive_from_ground():
    t = lambda s: NS(kind="text", bbox_px=[0, 0, 5, 5], conf=0.9, label=s)
    base = _plan(0, 0)
    assert storeys.count_storeys(base + [t("1. KERROS"), t("2. KERROS")])["n"] == 2
    assert storeys.count_storeys(base + [t("GROUND FLOOR"), t("UPPER FLOOR")])["n"] == 2
    assert storeys.count_storeys(base + [t("3 KRS"), t("4 KRS")])["n"] == 1   # room numbering, not floors
    assert storeys.count_storeys(base + [t("KELLARI")])["n"] == 1


def test_quoted_label_is_not_typo_fixed():
    q, fx = fix_typos("How many rooms labelled 'Balcone' and dors?")
    assert "'Balcone'" in q and "doors" in q and fx == [("dors", "doors")]


def test_point_in_polygon():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert _pt_in_poly((5, 5), sq) and not _pt_in_poly((15, 5), sq)


def test_door_window_same_opening_keeps_higher_confidence():
    from engine.solvers.data import Item, dedupe_openings
    d = Item(item_id="door-003", kind="door", page=1, bbox_px=[185, 666, 263, 680], conf=0.69)
    w = Item(item_id="window-002", kind="window", page=1, bbox_px=[186, 670, 259, 684], conf=0.63)
    far = Item(item_id="window-001", kind="window", page=1, bbox_px=[400, 100, 480, 120], conf=0.9)
    out = dedupe_openings([d, w, far])
    assert [i.item_id for i in out] == ["door-003", "window-001"]
