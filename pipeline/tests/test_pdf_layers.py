"""pdf_layers on synthetic pages only."""
import os

import numpy as np

from pipeline import pdf_layers, pdf_vector


def _p(pts, stroke=(0, 0, 0), width=0.5, fill=None, closed=False, dashed=False):
    return {"pts": [tuple(map(float, q)) for q in pts], "closed": closed, "fill": fill, "stroke": stroke,
            "width": width, "n_curves": 0, "is_arc": False, "obj": 0, "dashed": dashed, "pattern": None}


def _page():
    paths = []
    # wall pen: double lines 6 pt apart around a 100x80 room
    for off in (0, 6):
        a, b = 100 + off, 200 - off
        c, d = 100 + off, 180 - off
        paths += [_p([(a, c), (b, c)]), _p([(b, c), (b, d)]), _p([(b, d), (a, d)]), _p([(a, d), (a, c)])]
    # light background grid, single lines far apart
    for x in range(50, 550, 60):
        paths.append(_p([(x, 20), (x, 380)], stroke=(0.8, 0.8, 0.8), width=0.2))
    # dashed pen
    paths.append(_p([(120, 200), (380, 200)], width=0.3, dashed=True))
    # white mask
    paths.append(_p([(150, 150), (160, 150), (160, 160), (150, 160)], stroke=None, width=0, fill=(1, 1, 1), closed=True))
    return {"W_pt": 600.0, "H_pt": 400.0, "paths": paths, "words": [], "rotate": 0}


def test_layers_roles_and_cache():
    page = _page()
    Ls = pdf_layers.layers(page)
    roles = {L["role"] for L in Ls}
    assert {"wall", "background", "grid", "mask"} <= roles
    assert sum(L["n"] for L in Ls) == len(page["paths"])
    assert pdf_layers.layers(page) is Ls
    m = pdf_layers.role_mask(page, "wall")
    assert m.dtype == bool and m.sum() == 8


def test_never_raises():
    assert pdf_layers.layers({}) == []
    assert pdf_layers.layers({"paths": [{"bad": 1}], "W_pt": 1, "H_pt": 1}) == []
    assert not pdf_layers.role_mask({"paths": [{"bad": 1}]}, "wall").any()


def test_wall_page_drops_background_only():
    page = _page()
    q = pdf_layers.wall_page(page, 1)
    assert q is not page and len(q["paths"]) < len(page["paths"])
    assert all(p["stroke"] != (0.8, 0.8, 0.8) for p in q["paths"])
    assert len(page["paths"]) == 19  # original untouched


def test_switch_off_is_default(monkeypatch):
    monkeypatch.delenv("PDF_PEN_LAYERS", raising=False)
    page = _page()
    a = pdf_vector.walls(page)
    monkeypatch.setenv("PDF_PEN_LAYERS", "1")
    b = pdf_vector.walls(_page())
    assert isinstance(a, list) and isinstance(b, list)
    assert np.isfinite([w["thickness_pt"] for w in b]).all()
