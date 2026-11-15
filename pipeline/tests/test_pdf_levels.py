"""pipeline.pdf_levels: storey names/elevations/heights, column grid, multi-page alignment (synthetic pages)."""
import math

import pytest

from pipeline import pdf_levels as L


def _w(text, x, y, h=8.0):
    return {"text": text, "bbox": [x, y, x + 0.6 * h * len(text), y + h]}


def _circle(cx, cy, r):
    pts = [[cx + r * math.cos(2 * math.pi * k / 16), cy + r * math.sin(2 * math.pi * k / 16)] for k in range(16)]
    return {"pts": pts, "closed": True, "fill": None, "stroke": [0, 0, 0], "width": 0.5, "n_curves": 4,
            "is_arc": True, "obj": 0, "dashed": False}


def _line(p, q, dashed=True):
    return {"pts": [list(p), list(q)], "closed": False, "fill": None, "stroke": [0, 0, 0], "width": 0.3,
            "n_curves": 0, "is_arc": False, "obj": 0, "dashed": dashed}


def _grid_page(dx=0.0, dy=0.0, letters="ABC", numbers="123", step=100.0, words=(), dash_pieces=False):
    paths, ws = [], list(words)
    r = 9.0
    x0, y0 = 100 + dx, 100 + dy
    span = step * (len(numbers) - 1)
    for i, t in enumerate(letters):  # horizontal axes, bubble at the left
        y = y0 + i * step
        paths.append(_circle(x0 - 30, y, r))
        if dash_pieces:
            x = x0 - 30 + r
            while x < x0 + span + 20:
                paths.append(_line((x, y), (min(x + 12, x0 + span + 20), y), dashed=False))
                x += 16
        else:
            paths.append(_line((x0 - 30 + r, y), (x0 + span + 20, y)))
        ws.append({"text": t, "bbox": [x0 - 33, y - 4, x0 - 27, y + 4]})
    spanv = step * (len(letters) - 1)
    for j, t in enumerate(numbers):  # vertical axes, bubble at the top
        x = x0 + j * step
        paths.append(_circle(x, y0 - 30, r))
        paths.append(_line((x, y0 - 30 + r), (x, y0 + spanv + 20)))
        ws.append({"text": t, "bbox": [x - 3, y0 - 34, x + 3, y0 - 26]})
    # noise: a door-tag circle with no line, a short line
    paths.append(_circle(500, 500, 8)); ws.append({"text": "D1", "bbox": [496, 496, 504, 504]})
    paths.append(_line((600, 600), (620, 600)))
    return {"W_pt": 1200.0, "H_pt": 900.0, "rotate": 0, "paths": paths, "words": ws, "image_cover": 0.0}


@pytest.mark.parametrize("text,name,num", [
    ("2ND FLOOR PLAN", "2ND FLOOR", 2), ("Level 02", "LEVEL 02", 2), ("FLOOR PLAN - SECOND FLOOR", "SECOND FLOOR", 2),
    ("1. OG", "1. OG", 1), ("3. krs", "3. KRS", 3), ("Kerros 3", "KERROS 3", 3), ("GROUND FLOOR PLAN", "GROUND FLOOR", 0),
    ("1. UG", "1. UG", -1), ("FLOOR PLAN 1ST", "1ST FLOOR", 1), ("FLOOR PLAN MEZZANINE", "MEZZANINE FLOOR", 1.5), ("MEZZANINE", "MEZZANINE", 1.5), ("BASEMENT LEVEL", "BASEMENT LEVEL", -1), ("Erdgeschoss", "ERDGESCHOSS", 0),
])
def test_parse_name(text, name, num):
    assert L.parse_name(text) == (name, num)


def test_parse_name_negative():
    assert L.parse_name("DOOR SCHEDULE") is None
    assert L.parse_name("see the plan for details") is None
    assert L.parse_name("TUB KG") is None and L.parse_name("EG") == ("EG", 0)


@pytest.mark.parametrize("text,v", [("+9.000", 9.0), ("-0,450", -0.45), ("FFL 8.950", 8.95), ("FFL +8.950", 8.95),
                                    ("EL. 100'-0\"", 30.48), ("T.O. SLAB EL. 112'-6\"", 34.29), ("±0.000", 0.0)])
def test_parse_elevation(text, v):
    assert L.parse_elevation(text) == pytest.approx(v, abs=1e-3)


def test_parse_elevation_negative():
    for t in ("12.50", "1:100", "2'-6\"", "A101"):
        assert L.parse_elevation(t) is None


def test_ceiling_and_f2f():
    assert L.parse_ceiling("h=2700") == pytest.approx(2.7)
    assert L.parse_ceiling("CLG. HT. 9'-0\"") == pytest.approx(2.743, abs=1e-3)
    assert L.parse_ceiling("9'-0\" A.F.F.") == pytest.approx(2.743, abs=1e-3)
    assert L.parse_f2f("FLOOR TO FLOOR 3300") == pytest.approx(3.3)
    assert L.parse_f2f("kerroskorkeus 3,2") == pytest.approx(3.2)


def test_storey_info_title_marks_ceiling():
    words = [_w("FLOOR", 900, 800, 20), _w("PLAN", 970, 800, 20), _w("-", 1030, 800, 20), _w("SECOND", 1050, 800, 20),
             _w("FLOOR", 1140, 800, 20), _w("+3.300", 300, 300), _w("+3.300", 500, 300), _w("h=2700", 400, 400),
             _w("2ND", 50, 50, 6), _w("FLOOR", 70, 50, 6), _w("KEY", 100, 50, 6)]
    st = L.storey_info({"words": words})
    assert st["name"] == "SECOND FLOOR" and st["number"] == 2
    assert st["elevation_m"] == pytest.approx(3.3)
    assert st["height_m"] == pytest.approx(2.7 + L.SLAB_M)


def test_grid_axes_and_noise():
    g = L.grid(_grid_page())
    tags = sorted(a["tag"] for a in g)
    assert tags == ["1", "2", "3", "A", "B", "C"]
    a = next(a for a in g if a["tag"] == "A")
    assert a["p0"][1] == pytest.approx(100, abs=0.5) and a["p1"][0] > 300


def test_grid_dash_pieces():
    tags = sorted(a["tag"] for a in L.grid(_grid_page(dash_pieces=True)))
    assert tags == ["1", "2", "3", "A", "B", "C"]


def test_grid_empty_page():
    assert L.grid({"W_pt": 100, "H_pt": 100, "paths": [], "words": []}) == []


def _pm(page, mpt=0.01, n=1):
    s = 2.0
    prov = {"px_per_pt": s, **L.planmap_provenance(page, {"semantics": {}}, s)}
    return {"doc_id": "t", "page": n, "scale": {"m_per_pt": mpt, "m_per_px": mpt / s}, "items": [], "provenance": prov}


def test_storeys_grid_alignment_and_order():
    p1 = _grid_page(words=[_w("FIRST", 900, 800, 20), _w("FLOOR", 990, 800, 20), _w("+0.000", 300, 300)])
    p2 = _grid_page(dx=37, dy=-12, words=[_w("SECOND", 900, 800, 20), _w("FLOOR", 1010, 800, 20)])
    p3 = _grid_page(dx=-5, dy=20, words=[_w("THIRD", 900, 800, 20), _w("FLOOR", 990, 800, 20), _w("+6.600", 300, 300)])
    lv = L.storeys([p3, None, p1, p2], [_pm(p3), None, _pm(p1), _pm(p2)])
    assert [r["name"] for r in lv] == ["FIRST FLOOR", "SECOND FLOOR", "THIRD FLOOR"]
    assert [r["elevation_m"] for r in lv] == pytest.approx([0.0, 3.3, 6.6])
    assert all(r["height_m"] == pytest.approx(3.3) for r in lv)
    by = {r["name"]: r for r in lv}
    ref = by["FIRST FLOOR"]["align"]["reference_page"]
    assert ref == 2  # most axes (all equal) -> the lowest storey (first floor, page 2) is the reference
    r2 = by["SECOND FLOOR"]
    assert r2["align"]["method"] == "grid" and r2["align"]["residual_m"] < 0.01
    assert r2["rotation_deg"] == pytest.approx(0, abs=0.01)
    assert r2["offset_pt"] == pytest.approx([-37, 12], abs=0.05)


def test_storeys_from_planmaps_default_heights():
    p1 = _grid_page(words=[_w("Level", 900, 800, 20), _w("01", 960, 800, 20)])
    p2 = _grid_page(words=[_w("Level", 900, 800, 20), _w("03", 960, 800, 20)])
    lv = L.storeys_from_planmaps([_pm(p2), _pm(p1)])
    assert [r["name"] for r in lv] == ["LEVEL 01", "LEVEL 03"]
    assert lv[0]["elevation_m"] == 0.0 and lv[1]["elevation_m"] == pytest.approx(L.DEFAULT_STOREY_M)
    assert lv[0]["z_m"] == 0.0


def test_level_table_on_section_sheet():
    words = [_w("SECOND", 100, 100, 10), _w("FLOOR", 145, 100, 10), _w("EL.", 100, 114, 8), _w("112'-0\"", 118, 114, 8)]
    t = L.level_table({"words": words})
    assert t and t[0]["name"] == "SECOND FLOOR" and t[0]["elevation_m"] == pytest.approx(112 * 0.3048, abs=1e-3)


def test_footprint_alignment_rotated():
    sq = [[0, 0], [20, 0], [20, 0.3], [0, 0.3]]
    def walls(dx, dy, rot):
        out = []
        for poly in (sq, [[0, 0], [0.3, 0], [0.3, 10], [0, 10]], [[19.7, 0], [20, 0], [20, 10], [19.7, 10]],
                     [[0, 9.7], [20, 9.7], [20, 10], [0, 10]]):
            pp = []
            for x, y in poly:
                if rot:
                    x, y = -y, x
                pp.append([(x + dx) / 0.005, (y + dy) / 0.005])  # px at 0.005 m/px
            out.append({"kind": "wall", "polygon_px": pp})
        return out
    pa = {"scale": {"m_per_pt": 0.01, "m_per_px": 0.005}, "items": walls(0, 0, False), "provenance": {"storey": {"name": "LEVEL 1", "number": 1}}}
    pb = {"scale": {"m_per_pt": 0.01, "m_per_px": 0.005}, "items": walls(5, 3, False), "provenance": {"storey": {"name": "LEVEL 2", "number": 2}}}
    lv = L.storeys_from_planmaps([pa, pb])
    b = lv[1]
    assert b["align"]["method"] == "footprint"
    assert b["offset_m"] == pytest.approx([-5, -3], abs=0.05) and b["align"]["residual_m"] < 0.1


def test_planmap_hook_never_breaks():
    # process() wraps the hook; the function itself must also cope with a bare page
    out = L.planmap_provenance({"W_pt": 10, "H_pt": 10, "paths": [], "words": []}, {}, 1.0)
    assert out["grid"] == [] and out["storey"]["name"] is None


@pytest.mark.parametrize("text,name,num", [
    ("PLAN 02 - KÆLDER", "KÆLDER", -1), ("Kælder", "KÆLDER", -1), ("1.korrus", "1.KORRUS", 1), ("2. korrus", "2. KORRUS", 2),
    ("Dachgeschoss", "DACHGESCHOSS", None), ("Kellergeschoss", "KELLERGESCHOSS", -1), ("1. sal", "1. SAL", 1),
    ("Stueetage", "STUEETAGE", 0), ("PLAN 02", "PLAN 02", 2),
])
def test_parse_name_more_languages(text, name, num):
    assert L.parse_name(text) == (name, num)


def test_level_table_bare_feet_inches_stacked():
    # section sheet: storey caption with a bare feet-inch datum right under it; a scale note is never a datum
    words = [_w("MEZZANINE", 900, 100, 10), _w("9'", 920, 113, 8), _w("-", 932, 113, 8), _w("3\"", 940, 113, 8),
             _w("1ST", 900, 300, 10), _w("FLOOR", 925, 300, 10), _w("0'", 920, 313, 8), _w("0\"", 935, 313, 8),
             _w("1/8\" = 1'-0\"", 100, 600, 8)]
    t = {r["name"]: r["elevation_m"] for r in L.level_table({"words": words})}
    assert t == {"MEZZANINE": pytest.approx(9 * 0.3048 + 3 * 0.0254, abs=1e-3), "1ST FLOOR": 0.0}
    assert L._bare_ft("1/8\" = 1'-0\"") is None and L._bare_ft("FLOOR PLAN 1'-0\"", True) is None


def test_storeys_take_set_level_datums_by_caption():
    # plan titles 'FLOOR PLAN 1ST' / 'FLOOR PLAN MEZZANINE', datums from an elevation sheet named '1ST FLOOR'/'MEZZANINE'
    table = [{"name": "MEZZANINE", "number": 1.5, "elevation_m": 2.819}, {"name": "1ST FLOOR", "number": 1, "elevation_m": 0.0}]
    pms = [{"scale": {"m_per_pt": 0.01, "m_per_px": 0.005}, "items": [],
            "provenance": {"storey": {"name": nm, "number": no}, "level_table": table}}
           for nm, no in (("MEZZANINE FLOOR", 1.5), ("1ST FLOOR", 1))]
    lv = L.storeys_from_planmaps(pms)
    assert [(r["name"], r["elevation_m"]) for r in lv] == [("1ST FLOOR", 0.0), ("MEZZANINE FLOOR", 2.819)]
    assert lv[0]["height_m"] == pytest.approx(2.819)


def _sheet(title_lines, body=(), sheet_no=None, W=1000.0, H=700.0):
    ws = [_w(t, 820, 600 + 12 * i, 10) for i, t in enumerate(title_lines)]
    if sheet_no:
        ws.append(_w(sheet_no, 900, 660, 16))
    ws += [_w(t, 100 + 30 * i, 100 + 20 * i, 6) for i, t in enumerate(body)]
    ws += [_w("x", 300 + 7 * i, 300, 6) for i in range(30)]  # body text sets the median height
    return ws, W, H


@pytest.mark.parametrize("lines,sheet_no,kind", [
    (["FLOOR PLAN - 1ST"], "A101", "plan"), (["BUILDING ELEVATIONS"], "A200", "elevation"),
    (["BUILDING SECTION"], None, "section"), (["DOOR SCHEDULE"], "A600", "schedule"), (["ROOF PLAN"], None, "roof"),
    (["EXISTING SITE PLAN"], None, "site"), (["DEMOLITION PLANS"], None, "demo"), (["PERSPECTIVES"], None, "cover"),
    (["FOUNDATION PLAN"], "S050", "structural"), (["Grundriss Erdgeschoss"], None, "plan"),
    (["Plan 02 - Kælder"], None, "plan"), (["Dachgeschoss"], None, "plan"), (["Lageplan"], None, "site"),
    (["Schnitt A-A"], None, "section"), (["MECHANICAL FLOOR PLAN"], "M201", "mep"),
    # the design team in the title block ('Mechanical', 'X Plumbing Engineer') does not make an MEP sheet
    (["Mechanical", "Plumbing Engineer:", "info@firm.com", "2ND FLOOR PLAN"], None, "plan"),
    (["WALL DETAILS"], "A501", "detail"),
])
def test_classify_sheet(lines, sheet_no, kind):
    ws, W, H = _sheet(lines, sheet_no=sheet_no)
    assert L.classify_sheet(ws, W, H)["kind"] == kind


def test_classify_sheet_storey_and_empty():
    ws, W, H = _sheet(["FLOOR PLAN MEZZANINE"], sheet_no="A102")
    c = L.classify_sheet(ws, W, H)
    assert c["kind"] == "plan" and c["storey"] == ("MEZZANINE FLOOR", 1.5) and c["sheet_no"] == "A102"
    assert L.classify_sheet([], 100, 100)["kind"] == "other" and L.classify_sheet(None, 0, 0)["kind"] == "other"
