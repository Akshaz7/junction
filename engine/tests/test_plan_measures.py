import json
from pathlib import Path

import pytest

from engine.plan_measures import measures, shoelace_area, wall_from_polygon

SWISS = Path("/home/ar/junction/artifacts/uploads__swiss-site289-floor2149-bff698/planmap-1.json")
CUBI = Path("/home/ar/junction/artifacts/cubicasa5k__colorful-11397/planmap-1.json")


def _item(kind, polygon=None, bbox=None, props=None):
    if bbox is None and polygon:
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    return {"item_id": f"{kind}-001", "kind": kind, "bbox_px": bbox,
            "polygon_px": polygon, "props": props or {}}


def test_rectangle_wall():
    # 400 x 20 px wall at 0.01 m/px -> 4.0 m long, 0.2 m thick
    m = measures(_item("wall", [[0, 0], [400, 0], [400, 20], [0, 20]]), 0.01)
    assert m["length_m"] == pytest.approx(4.0, abs=1e-3)
    assert m["thickness_m"] == pytest.approx(0.2, abs=1e-3)
    assert m["source"] == "geometry"
    assert m["m_per_px"] == 0.01
    assert "face_area_m2" not in m


def test_l_shaped_wall():
    # outer arms 300 and 200 px, thickness 20 px -> centreline 300 + 200 - 20 = 480 px
    poly = [[0, 0], [300, 0], [300, 20], [20, 20], [20, 200], [0, 200]]
    m = measures(_item("wall", poly), 0.01)
    assert m["thickness_m"] == pytest.approx(0.2, abs=1e-3)
    assert m["length_m"] == pytest.approx(4.8, abs=1e-3)
    # bbox-only would say 3.0 x 2.0: the polygon path must not do that
    t, length = wall_from_polygon(shoelace_area(poly), 2 * (300 + 200))
    assert (t, length) == pytest.approx((20, 480))


def test_wall_bbox_only_and_height():
    m = measures(_item("wall", None, [10, 10, 30, 510], {"height_m": 2.5}), 0.01)
    assert m["length_m"] == pytest.approx(5.0)
    assert m["thickness_m"] == pytest.approx(0.2)
    assert m["face_area_m2"] == pytest.approx(12.5)


def test_wall_props_win_over_geometry():
    poly = [[0, 0], [400, 0], [400, 20], [0, 20]]
    m = measures(_item("wall", poly, props={"length_m": 4.2, "thickness_m": 0.25}), 0.01)
    assert m == {"length_m": 4.2, "thickness_m": 0.25, "source": "drawing"}
    # props win even with no scale
    assert measures(_item("wall", poly, props={"length_m": 4.2}), None) == {
        "length_m": 4.2, "source": "drawing"}
    # half from props, half from geometry -> mixed
    m = measures(_item("wall", poly, props={"length_m": 4.2}), 0.01)
    assert m["length_m"] == 4.2 and m["thickness_m"] == pytest.approx(0.2)
    assert m["source"] == "mixed" and m["m_per_px"] == 0.01


def test_room_area_matches_shoelace():
    poly = [[0, 0], [500, 0], [500, 300], [200, 300], [200, 400], [0, 400]]  # L room
    area_px = 500 * 300 + 200 * 100
    m = measures(_item("room", poly), 0.02)
    assert m["area_m2"] == pytest.approx(area_px * 0.0004, abs=1e-3)
    assert m["area_measured_m2"] == m["area_m2"]
    assert m["perimeter_m"] == pytest.approx((500 + 300 + 300 + 100 + 200 + 400) * 0.02, abs=1e-3)
    assert m["source"] == "geometry"


def test_room_props_area_wins_and_measured_kept():
    poly = [[0, 0], [100, 0], [100, 100], [0, 100]]
    m = measures(_item("room", poly, props={"area_m2": 12.09}), 0.03)
    assert m["area_m2"] == 12.09
    assert m["area_measured_m2"] == pytest.approx(9.0)
    assert m["source"] == "mixed"


def test_openings_and_fixtures():
    door = measures(_item("door", None, [0, 0, 10, 90]), 0.01)
    assert door["width_m"] == pytest.approx(0.9) and door["depth_m"] == pytest.approx(0.1)
    assert "size_m" not in door
    assert measures(_item("door", None, [0, 0, 10, 90], {"width_m": 0.96}), 0.01)["width_m"] == 0.96
    wc = measures(_item("toilet", None, [0, 0, 40, 70]), 0.01)
    assert wc["size_m"] == [0.4, 0.7]
    assert wc["width_m"] == pytest.approx(0.7) and wc["depth_m"] == pytest.approx(0.4)


def test_no_scale_geometry_only_is_empty():
    assert measures(_item("wall", [[0, 0], [400, 0], [400, 20], [0, 20]]), None) == {}
    assert measures(_item("room", [[0, 0], [1, 0], [1, 1]]), None) == {}
    assert measures(_item("door", None, [0, 0, 10, 90]), None) == {}
    assert measures(_item("sink", None, [0, 0, 10, 10]), None) == {}
    assert measures(_item("text", None, [0, 0, 10, 10]), 0.01) == {}


def _load(path):
    if not path.exists():
        pytest.skip(f"{path} not present")
    return json.loads(path.read_text())


def test_real_swiss_walls_agree_with_props():
    d = _load(SWISS)
    scale = d["scale"]["m_per_px"]
    walls = [w for w in d["items"] if w["kind"] == "wall" and w["props"].get("length_m")]
    assert walls
    ok = 0
    for w in walls:
        m = measures(dict(w, props={}), scale)  # strip props -> geometry only
        assert m["source"] == "geometry"
        ok += abs(m["length_m"] - w["props"]["length_m"]) / w["props"]["length_m"] <= 0.15
    frac = ok / len(walls)
    print(f"swiss walls: {ok}/{len(walls)} within 15% of props.length_m ({frac:.0%})")
    assert frac >= 0.8


def test_real_raster_plan_gives_values():
    d = _load(CUBI)
    scale = d["scale"]["m_per_px"]
    kinds = {}
    for it in d["items"]:
        m = measures(it, scale)
        if it["kind"] == "text":
            assert m == {}
        else:
            assert m, it["item_id"]
            kinds[it["kind"]] = m
    assert {"wall", "room", "door"} <= set(kinds)
