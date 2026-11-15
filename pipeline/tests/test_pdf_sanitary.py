"""pdf_sanitary: WC / basin found from exploded symbol linework in a labelled wet room; nothing in a dry room."""
import math

from pipeline import pdf_sanitary

MPT = 0.0352777  # 1:100 at 72 dpi -> 1 pt = 3.53 cm


def _segs(pts, closed=True):
    q = list(pts) + ([pts[0]] if closed else [])
    return [{"pts": [list(a), list(b)], "stroke": [0, 0, 0], "fill": None, "closed": False}
            for a, b in zip(q[:-1], q[1:])]


def _wc(x, y):
    """Exploded WC at (x, y): cistern 0.35 x 0.15 m against the wall, bowl 0.35 x 0.45 m with a rounded front."""
    w, c, b = 0.35 / MPT, 0.15 / MPT, 0.45 / MPT
    out = _segs([(x, y), (x + w, y), (x + w, y + c), (x, y + c)])
    r = w / 2
    bowl = [(x, y + c), (x + w, y + c), (x + w, y + c + b - r)]
    for k in range(1, 12):  # semicircular front, 11 tiny pieces with 0.02 pt gaps like a CAD explode
        t = math.pi * k / 12
        bowl.append((x + r + r * math.cos(t) + 0.02, y + c + b - r + r * math.sin(t)))
    bowl.append((x, y + c + b - r))
    return out + _segs(bowl)


def _basin(x, y):
    """Rounded box 0.5 x 0.4 m (corner radius 4 cm) with a round bowl inside."""
    w, h, r = 0.5 / MPT, 0.4 / MPT, 0.04 / MPT
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for k in range(4):
            a = math.radians(a0 + 30 * k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    bowl = [(x + w / 2 + 0.12 / MPT * math.cos(2 * math.pi * k / 16), y + h / 2 + 0.12 / MPT * math.sin(2 * math.pi * k / 16))
            for k in range(16)]
    return _segs(pts) + _segs(bowl)


def _room(x0, y0, x1, y1, label):
    return {"polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "label": label}


def test_wc_and_basin_in_wet_room_only():
    wet = _room(100, 100, 160, 160, "WC")
    dry = _room(300, 100, 360, 160, "OFFICE")
    paths = _wc(110, 101) + _basin(135, 101) + _wc(310, 101) + _basin(335, 101)
    out = pdf_sanitary.find({"paths": paths}, MPT, [wet, dry], [], [])
    kinds = sorted(f["kind"] for f in out)
    assert kinds == ["basin", "wc"], out
    for f in out:
        xs = [p[0] for p in f["polygon"]]
        assert max(xs) < 200  # nothing from the office
        assert f["props"]["room"].startswith("WC")
    wc = next(f for f in out if f["kind"] == "wc")
    assert 0.5 <= max(wc["props"]["size_m"]) <= 0.7


def test_existing_skipped_and_never_raises():
    wet = _room(100, 100, 160, 160, "Toilette")
    paths = _wc(110, 101)
    first = pdf_sanitary.find({"paths": paths}, MPT, [wet], [], [])
    assert [f["kind"] for f in first] == ["wc"]
    assert pdf_sanitary.find({"paths": paths}, MPT, [wet], [], first) == []
    assert pdf_sanitary.find(None, MPT, [wet], [], []) == []
    assert pdf_sanitary.find({"paths": [{"pts": "bad"}]}, MPT, [{"polygon": "x"}], [{"polygon": 1}], [None]) == []
    assert pdf_sanitary.find({"paths": paths}, None, [wet], [], []) == []
