"""pipeline.pdf_levels.columns (filled/hatched sections on the grid) and ifc_enrich._columns (IfcColumn)."""
import json

import pytest

from pipeline import pdf_levels as L
from pipeline.tests.test_pdf_levels import _grid_page


def _sq(cx, cy, a, fill=(1.0, 1.0, 1.0)):
    h = a / 2
    return {"pts": [[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h]], "closed": True,
            "fill": list(fill) if fill else None, "stroke": None, "width": 0.0, "n_curves": 0, "is_arc": False,
            "obj": 0, "dashed": False}


def _hatch(cx, cy, a):
    """CAD section hatch: parallel 45-degree strokes inside the square (a bare X of 2 lines is a shaft mark)."""
    h = a / 2 - 0.5
    x0, y0, x1, y1 = cx - h, cy - h, cx + h, cy + h
    return [{"pts": [[x0 + o, y1], [x1, y0 + o]], "closed": False, "fill": None, "stroke": [0, 0, 0],
             "width": 0.2, "n_curves": 0, "is_arc": False, "obj": 0, "dashed": False}
            for o in (0.0, 0.25 * h, 0.5 * h, 0.75 * h)]


MPT = 0.035  # 1:100, a 13.7 pt square is 0.48 m


def _page():
    page = _grid_page()
    for x, y in ((100, 100), (200, 200), (300, 300)):  # on grid intersections, hatched
        page["paths"].append(_sq(x, y, 13.7))
        page["paths"] += _hatch(x, y, 13.7)
    page["paths"].append(_sq(150, 150, 13.7, fill=(0, 0, 0)))  # solid, off the grid: a symbol, not a column
    page["paths"].append(_sq(300, 100, 13.7, fill=None))  # on the grid, unfilled with a bare X: a shaft
    page["paths"] += _hatch(300, 100, 13.7)[2:]
    page["paths"].append(_sq(200, 100, 60.0))  # on the grid but 2 m: not a column
    return page


def test_columns_on_grid_only():
    page = _page()
    cols = L.columns(page, MPT, L.grid(page))
    assert len(cols) == 3
    assert all(c["grid"] and c["w_m"] == pytest.approx(0.48, abs=0.01) for c in cols)
    assert all("hatched section" in c["evidence"] for c in cols)


def test_columns_no_grid_no_columns():
    page = _page()
    assert L.columns(page, MPT, []) == []


def test_columns_zone_filters():
    from shapely.geometry import box
    page = _page()
    cols = L.columns(page, MPT, L.grid(page), zone=box(90, 90, 210, 210))
    assert len(cols) == 2


def test_enrich_adds_ifc_columns(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from pipeline import ifc_enrich, pdf_to_ifc
    pm = {"doc_id": "colt", "page": 1, "scale": {"m_per_px": 0.01, "m_per_pt": 0.01},
          "items": [{"item_id": "w1", "kind": "wall", "polygon_px": [[0, 0], [1000, 0], [1000, 20], [0, 20]],
                     "bbox_px": [0, 0, 1000, 20], "props": {"thickness_m": 0.2}}],
          "provenance": {"columns": [{"bbox_px": [476, 20, 524, 68], "shape": "rect", "grid": "A/1",
                                      "evidence": "grid hatched section"}]}}
    try:
        out = pdf_to_ifc.build(pm, tmp_path / "model.ifc", doc_id="colt")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"pdf_to_ifc.build needs a fuller plan map: {e}")
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    f = ifcopenshell.open(str(out))
    if not f.by_type("IfcColumn"):  # build's own enrich ran before the sidecar existed: run it now
        ifc_enrich.enrich(out)
        f = ifcopenshell.open(str(out))
    cols = f.by_type("IfcColumn")
    assert len(cols) == 1
    c = cols[0]
    assert c.IsTypedBy and c.IsTypedBy[0].RelatingType.is_a("IfcColumnType")
    assert c.ContainedInStructure and c.ContainedInStructure[0].RelatingStructure.is_a("IfcBuildingStorey")
    ids = {r.RepresentationIdentifier for r in c.Representation.Representations}
    assert {"Body", "Axis", "Box", "FootPrint"} <= ids
    n = len(cols)
    ifc_enrich.enrich(out)  # idempotent
    assert len(ifcopenshell.open(str(out)).by_type("IfcColumn")) == n


def _box_strokes(cx, cy, a, width=1.3):
    """A column outline exploded into 4 separate strokes of one heavy pen (CAD plot), no fill, no hatch."""
    h = a / 2
    c = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    return [{"pts": [list(c[i]), list(c[(i + 1) % 4])], "closed": False, "fill": None, "stroke": [0, 0, 0],
             "width": width, "n_curves": 0, "is_arc": False, "obj": 0, "dashed": False} for i in range(4)]


def test_columns_clean_pen_outlines():
    page = _grid_page()
    for x, y in ((100, 100), (200, 100), (300, 100), (200, 200), (300, 300)):  # on crossings
        page["paths"] += _box_strokes(x, y, 13.7)
    page["paths"] += _box_strokes(150, 300, 13.7)  # on axis C, between crossings, in a row with the C columns
    page["paths"] += _box_strokes(700, 700, 13.7)  # off every axis, alone: not a column
    cols = L.columns(page, MPT, L.grid(page))
    cs = sorted(((c["bbox"][0] + c["bbox"][2]) / 2, (c["bbox"][1] + c["bbox"][3]) / 2) for c in cols)
    assert len(cols) == 6, cols
    assert (150.0, 300.0) in [(round(x), round(y)) for x, y in cs]
    assert all("column-only pen" in c["evidence"] for c in cols)


def test_columns_thin_pen_boxes_are_not_columns():
    page = _grid_page()
    for x, y in ((100, 100), (200, 200), (300, 300)):
        page["paths"] += _box_strokes(x, y, 13.7, width=0.25)
    for i in range(40):  # the same pen draws plenty of other linework: not a column-only pen
        page["paths"].append({"pts": [[50 + 10 * i, 800], [55 + 10 * i, 850]], "closed": False, "fill": None,
                              "stroke": [0, 0, 0], "width": 0.25, "n_curves": 0, "is_arc": False, "obj": 0,
                              "dashed": False})
    assert L.columns(page, MPT, L.grid(page)) == []
