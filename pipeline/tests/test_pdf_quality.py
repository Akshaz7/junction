"""Synthetic checks for pipeline/pdf_quality.assess (no PDFs needed)."""
from pipeline import pdf_quality

MPT = 0.0254 / 72 * 100  # 1:100


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _box_walls(t=7.0, L=200.0):
    """Four walls of a square room, page pt."""
    return [_rect(0, 0, L, t), _rect(0, L - t, L, L), _rect(0, 0, t, L), _rect(L - t, 0, L, L)]


def _page(walls):
    return {"W_pt": 400.0, "H_pt": 400.0, "rotate": 0, "words": [], "image_cover": 0.0,
            "paths": [{"pts": p, "closed": True, "fill": [0, 0, 0], "stroke": None, "width": 0, "n_curves": 0,
                       "is_arc": False} for p in walls]}


def _pm(walls, s=2.0, area=None, printed=None):
    items = [{"item_id": f"wall-{k:03d}", "kind": "wall", "polygon_px": [[x * s, y * s] for x, y in p],
              "bbox_px": [0, 0, 1, 1]} for k, p in enumerate(walls)]
    items.append({"item_id": "room-001", "kind": "room", "polygon_px": [[10, 10], [380, 10], [380, 380]],
                  "bbox_px": [10, 10, 380, 380], "q": {"area_m2": area, "area_m2_printed": printed}})
    return {"image": {"w": 800, "h": 800}, "provenance": {"px_per_pt": s}, "items": items,
            "scale": {"m_per_pt": MPT, "method": "printed 1:100", "ratio": "1:100", "confidence": 0.95,
                      "check": {"fit_vs_printed_rel": 0.01, "fit_n": 3}}}


def test_perfect_match_scores_high():
    w = _box_walls()
    raw = [{"polygon": p} for p in w]
    q = pdf_quality.assess(_page(w), _pm(w, area=20.0, printed=20.2), n_boot=50, raw_walls=raw)
    assert q["components"]["walls"]["precision"] > 0.95 and q["components"]["walls"]["recall"] > 0.95
    assert q["components"]["walls"]["closed_exterior"]
    assert q["score"] >= 0.85 and q["ci95"][0] <= q["score"] <= q["ci95"][1]
    assert q["label"] == "medium" and "fewer than 3 openings to check" in q["label_capped_by"]  # no openings: capped
    assert q["summary"].startswith("3D matches the drawing:")


def test_missing_walls_lower_recall_and_score():
    w = _box_walls()
    raw = [{"polygon": p} for p in w]
    full = pdf_quality.assess(_page(w), _pm(w, area=20.0, printed=20.2), n_boot=20, raw_walls=raw)
    half = pdf_quality.assess(_page(w), _pm(w[:2], area=20.0, printed=28.0), n_boot=20, raw_walls=raw)
    assert half["components"]["walls"]["recall"] < 0.8
    assert half["score"] < full["score"]


def test_no_scale_does_not_crash():
    w = _box_walls()
    pm = _pm(w)
    pm["scale"] = {"m_per_pt": None, "method": None}
    q = pdf_quality.assess(_page(w), pm, n_boot=5, raw_walls=[])
    assert 0.0 <= q["score"] <= 1.0


def test_no_printed_areas_widens_ci_and_caps_label():
    w = _box_walls()
    raw = [{"polygon": p} for p in w]
    a = pdf_quality.assess(_page(w), _pm(w, area=20.0, printed=20.2), n_boot=100, raw_walls=raw)
    b = pdf_quality.assess(_page(w), _pm(w, area=20.0, printed=None), n_boot=100, raw_walls=raw)
    assert (b["ci95"][1] - b["ci95"][0]) > (a["ci95"][1] - a["ci95"][0])
    assert "no printed room areas" in b["label_capped_by"] and b["label"] != "high"


def test_extra_wall_lowers_precision():
    w = _box_walls()
    raw = [{"polygon": p} for p in w]
    extra = w + [_rect(60, 60, 140, 67)]  # a wall the drawing does not have
    q = pdf_quality.assess(_page(w), _pm(extra, area=20.0, printed=20.2), n_boot=10, raw_walls=raw)
    assert q["components"]["walls"]["precision"] < 0.95


def _flat_arc(cx, cy, r, a0=0.0, a1=90.0, n=12):
    """A door swing exported as a flattened polyline (no Bezier curves, is_arc False), as CAD PDFs usually do."""
    import math
    return [[cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))]
            for k in range(n + 1)]


def _door_page_pm(door_at):
    """Square room, a 0.9 m flattened door swing hinged on the top wall at (60, 7); one door item at door_at (pt)."""
    w = _box_walls()
    r = 0.9 / MPT
    page = _page(w)
    page["paths"].append({"pts": _flat_arc(60, 7, r), "closed": False, "fill": None, "stroke": [0, 0, 0],
                          "width": 0.3, "n_curves": 0, "is_arc": False})
    pm = _pm(w, area=20.0, printed=20.2)
    x, y = door_at
    s = pm["provenance"]["px_per_pt"]
    pm["items"].append({"item_id": "door-1", "kind": "door", "bbox_px": [x * s, y * s, (x + r) * s, (y + 7) * s],
                        "polygon_px": [[x * s, y * s], [(x + r) * s, y * s], [(x + r) * s, (y + 7) * s], [x * s, (y + 7) * s]],
                        "props": {"hinge": [x, y + 7]}})
    return page, pm, [{"polygon": p} for p in w]


def test_flattened_door_arc_matches_door_item():
    page, pm, raw = _door_page_pm((60, 0))
    o = pdf_quality.assess(page, pm, n_boot=5, raw_walls=raw)["components"]["openings"]
    assert o["door_arcs"] == 1 and o["door_arcs_matched"] == 1


def test_door_arc_far_from_door_item_is_unmatched():
    page, pm, raw = _door_page_pm((150, 190))  # door item on the opposite wall
    o = pdf_quality.assess(page, pm, n_boot=5, raw_walls=raw)["components"]["openings"]
    assert o["door_arcs"] == 1 and o["door_arcs_matched"] == 0


def test_edt_morphology_matches_scipy_disk():
    """_dil / _close_fill use a distance transform for big radii: must equal scipy's disk-structure morphology."""
    import numpy as np
    from scipy import ndimage
    rng = np.random.default_rng(3)
    m = ndimage.binary_dilation(rng.random((120, 170)) < 0.004, iterations=2) | (rng.random((120, 170)) < 0.002)
    for r in (1, 3, 4, 9):
        y, x = np.ogrid[-r:r + 1, -r:r + 1]
        st = (x * x + y * y) <= r * r
        assert (pdf_quality._dil(m, r) == ndimage.binary_dilation(m, structure=st)).all()
        pad = np.pad(m, r + 1)
        ref = ndimage.binary_fill_holes(ndimage.binary_erosion(ndimage.binary_dilation(pad, structure=st),
                                                               structure=st)[r + 1:-r - 1, r + 1:-r - 1])
        assert (pdf_quality._close_fill(m, r) == ref).all()
    assert not pdf_quality._dil(np.zeros((5, 5), bool), 6).any()
