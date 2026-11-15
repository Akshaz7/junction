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
