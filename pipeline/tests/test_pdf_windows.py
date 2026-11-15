"""pdf_windows: glass panes (2 close parallel lines) in wall gaps; merge learns the window pen from known windows."""
from pipeline import pdf_windows

MPT = 0.02  # 1 pt = 2 cm


def _ln(a, b, w=0.25):
    return {"pts": [list(a), list(b)], "stroke": (0, 0, 0), "width": w, "fill": None, "closed": False}


def _wall(x0, x1, y0=0.0, t=15.0):
    return {"polygon": [[x0, y0], [x1, y0], [x1, y0 + t], [x0, y0 + t]],
            "centerline": [[x0, y0 + t / 2], [x1, y0 + t / 2]], "thickness_pt": t}


def _page():
    # wall pieces 0-100, 150-250, 300-400 (y 0..15); a pane (lines 1 pt = 2 cm apart) in each 50 pt (1 m) gap
    paths = []
    for x0 in (100, 250):
        paths += [_ln((x0, 7.0), (x0 + 50, 7.0)), _ln((x0, 8.0), (x0 + 50, 8.0))]
    paths += [_ln((0, 0), (400, 0), 0.5), _ln((0, 15), (400, 15), 0.5)]  # wall faces (not panes: 30 cm apart)
    return {"paths": paths, "W_pt": 500, "H_pt": 100, "words": []}


WALLS = [_wall(0, 100), _wall(150, 250), _wall(300, 400)]


def test_panes_in_gaps():
    ws = pdf_windows.windows(_page(), WALLS, MPT)
    assert len(ws) == 2
    for w in ws:
        assert w["kind"] == "window" and len(w["polygon"]) == 4
        assert abs(w["props"]["width_m"] - 1.0) < 0.05
        assert w["props"]["support"] == "gap" and w["props"]["sill_m"] == 0.9
        assert w["bbox"][1] <= 1 and w["bbox"][3] >= 14   # spans the wall band


def test_never_raises():
    assert pdf_windows.windows({}, WALLS, MPT) == []
    assert pdf_windows.windows(_page(), [], MPT) == []
    assert pdf_windows.windows({"paths": [{"pts": None}]}, WALLS, MPT) == []


def test_merge_learns_pen_and_skips_duplicates():
    ws = pdf_windows.windows(_page(), WALLS, MPT)
    known = [dict(w, props=dict(w["props"])) for w in ws]   # both already found
    assert len(pdf_windows.merge(known, ws, MPT)) == 2       # no duplicates
    assert pdf_windows.merge([], ws, MPT) == []              # no known window -> pen not learnt -> nothing added


def _rect(x0, y0, x1, y1):
    return {"polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "thickness_pt": min(x1 - x0, y1 - y0)}


def _label(x, y, name, no):
    return [{"text": name, "bbox": [x, y, x + 30, y + 5]}, {"text": no, "bbox": [x, y + 6, x + 20, y + 11]},
            {"text": "16.0", "bbox": [x, y + 12, x + 10, y + 17]}, {"text": "m2", "bbox": [x + 11, y + 12, x + 18, y + 17]}]


def _building(roof=False):
    """8 x 4 m building (MPT 0.02): north facade with a glazed gap, an interior wall with a glazed gap; optionally
    an unlabelled roof outline drawn with walls against the north facade."""
    walls = [_rect(0, 0, 100, 15), _rect(150, 0, 400, 15), _rect(0, 185, 400, 200), _rect(0, 0, 15, 200),
             _rect(385, 0, 400, 200), _rect(192, 15, 207, 80), _rect(192, 130, 207, 185)]
    if roof:
        walls += [_rect(0, -600, 5, 0), _rect(395, -600, 400, 0), _rect(0, -600, 400, -595)]   # 8 x 12 m
    facade = {"kind": "window", "polygon": [[100, 0], [150, 0], [150, 15], [100, 15]], "props": {"pen": "L1"}}
    inner = {"kind": "window", "polygon": [[192, 80], [207, 80], [207, 130], [192, 130]], "props": {"pen": "L1"}}
    page = {"paths": [], "words": _label(80, 90, "OFFICE", "B101") + _label(280, 90, "OFFICE", "B102") +
            _label(250, 40, "STORE", "B103")}
    return walls, [facade, inner], page


def test_envelope_drops_interior_glazing():
    walls, (facade, inner), page = _building()
    pdf_windows.tag_envelope([facade, inner], walls, MPT, page=page)
    assert facade["props"]["envelope"] is True and inner["props"]["envelope"] is False
    south = {"kind": "window", "polygon": [[250, 185], [300, 185], [300, 200], [250, 200]], "props": {"pen": "L1"}}
    pdf_windows.tag_envelope([south], walls, MPT, page=page)
    known = [dict(w, props={"from": "jambs"}) for w in (facade, south)]   # the pen L1 is learnt from these two
    out = pdf_windows.merge(known, [facade, south, inner], MPT)
    assert len(out) == 2 and all(w is not inner for w in out)            # dupes skipped, the partition dropped
    inner["props"]["envelope"] = True                                    # (an envelope pane would be added)
    assert any(w is inner for w in pdf_windows.merge(known, [facade, south, inner], MPT))


def test_envelope_unlabelled_roof_outline_is_outside():
    walls, (facade, inner), page = _building(roof=True)
    pdf_windows.tag_envelope([facade, inner], walls, MPT, page=page)
    assert facade["props"]["envelope"] is True and inner["props"]["envelope"] is False
    # no printed labels: every enclosed hole is a room, so the roof outline hides the facade (documented fallback)
    page["words"] = []
    pdf_windows.tag_envelope([facade, inner], walls, MPT, page=page)
    assert facade["props"]["envelope"] is False
