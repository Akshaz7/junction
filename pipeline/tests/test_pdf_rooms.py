"""pipeline/pdf_rooms.py: room regions, printed areas and the scale ladder on synthetic PDFs and page dicts."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from pipeline import pdf_rooms as R

PT_M = 25.4 / 72 / 1000


# ------------------------------------------------------------ a tiny raw PDF writer (no deps)

def _pdf(path: Path, W: float, H: float, ops: list[str]):
    """ops are PDF content operators in a y-UP page space (PDF native)."""
    content = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents 4 0 R "
        f"/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def _plan_ops(H, rooms_m, n=100, wall_m=0.2, door_m=0.9, ox=100.0, oy=100.0, label=True, area_fmt="{:.2f} m²",
              area_scale=1.0, ratio_text=True):
    """A row of rectangular rooms (widths in metres, depth 4 m) at 1:n, walls black-filled, one door gap per
    partition. Returns (ops, true areas m² of the clear interiors). Coordinates handed to PDF in y-up."""
    mpt = PT_M * n
    t = wall_m / mpt
    depth = 4.0 / mpt
    ops = ["0 g"]
    x = ox
    xs = [x]
    for w in rooms_m:
        x += t + w / mpt
        xs.append(x)
    total_w = x + t - ox
    # y-down rectangles -> y-up for PDF
    def rect(x0, y0, w, h):
        ops.append(f"{x0:.4f} {H - y0 - h:.4f} {w:.4f} {h:.4f} re f")
    rect(ox, oy, total_w, t)                     # top wall
    rect(ox, oy + t + depth, total_w, t)         # bottom wall
    d = door_m / mpt
    for i, xx in enumerate(xs):                  # vertical walls; inner ones get a door gap
        if 0 < i < len(xs) - 1:
            rect(xx, oy + t, t, depth / 2 - d / 2)
            rect(xx, oy + t + depth / 2 + d / 2, t, depth / 2 - d / 2)
        else:
            rect(xx, oy + t, t, depth)
    areas = []
    names = ["Kitchen", "Bedroom", "Living", "Bath", "Office"]
    for i, w in enumerate(rooms_m):
        a = w * 4.0
        areas.append(a)
        cx = xs[i] + t + w / mpt / 2
        cy = oy + t + depth / 2
        if label:
            txt = area_fmt.format(a * area_scale).replace("²", "\\262")
            ops.append(f"BT /F1 8 Tf {cx - 15:.3f} {H - cy - 4:.3f} Td ({txt}) Tj ET")
            ops.append(f"BT /F1 8 Tf {cx - 15:.3f} {H - cy + 8:.3f} Td ({names[i % 5]}) Tj ET")
    if ratio_text:
        ops.append(f"BT /F1 10 Tf {ox:.3f} {H - oy - depth - 60:.3f} Td (GROUND FLOOR PLAN  1:{n}) Tj ET")
    return ops, areas


def _load(path):
    from pipeline import pdf_vector as V
    page = V.load_page(str(path), 0)
    if not page.get("paths"):
        pytest.skip("pdf_vector.load_page not ready")
    return page


# ------------------------------------------------------------ pure maths

def test_shoelace_exact():
    assert R.shoelace([[0, 0], [10, 0], [10, 5], [0, 5]]) == 50
    assert R.shoelace([[0, 0], [0, 5], [10, 5], [10, 0]]) == 50  # orientation independent
    assert math.isclose(R.shoelace([[0, 0], [4, 0], [0, 3]]), 6)


def test_m_per_pt_from_ratio():
    assert math.isclose(R.m_per_pt_from_ratio(100), 0.035278, rel_tol=1e-4)
    assert math.isclose(R.m_per_pt_from_ratio(200), 0.070556, rel_tol=1e-4)


@pytest.mark.parametrize("text,val", [
    ("15.61 m²", 15.61), ("15,6 m2", 15.6), ("15.61m²", 15.61), ("NF 12.40 m2", 12.4), ("8.5 qm", 8.5),
    ("150 SF", 150 * 0.09290304), ("1,250 sq ft", 1250 * 0.09290304), ("191 S.F.", 191 * 0.09290304),
    ("22 ft²", 22 * 0.09290304), ("Bedroom", None), ("1:100", None),
])
def test_parse_area(text, val):
    v = R.parse_area(text)
    if val is None:
        assert v is None
    else:
        assert v is not None and math.isclose(v, val, rel_tol=1e-6)


def test_label_blocks_name_number_area():
    words = [{"text": "Kitchen", "bbox": [100, 100, 130, 108]}, {"text": "1.03", "bbox": [104, 110, 120, 118]},
             {"text": "12.50", "bbox": [100, 120, 120, 128]}, {"text": "m²", "bbox": [122, 120, 130, 128]}]
    bl = R.label_blocks(words)
    assert len(bl) == 1
    assert bl[0]["label"] == "Kitchen" and bl[0]["number"] == "1.03" and bl[0]["area_printed_m2"] == 12.5


def test_area_fit_least_squares():
    m = 0.05
    rooms = [{"polygon": [[0, 0]], "pts_area": a, "area_printed_m2": a * m * m, "split": False} for a in (4000, 9000, 2500)]
    rooms.append({"polygon": [[0, 0]], "pts_area": 5000, "area_printed_m2": 99.0, "split": False})  # mislabelled
    f = R._area_fit(rooms)
    assert math.isclose(f["m_per_pt"], m, rel_tol=1e-9) and f["n"] == 3


# ------------------------------------------------------------ rooms on page dicts (no PDF parsing)

def _page_from_ops_free(rooms_m, n=100):
    """Page dict built directly (y-down), mirroring _plan_ops."""
    mpt = PT_M * n
    t, depth, ox, oy = 0.2 / mpt, 4.0 / mpt, 100.0, 100.0
    xs = [ox]
    for w in rooms_m:
        xs.append(xs[-1] + t + w / mpt)
    total_w = xs[-1] + t - ox
    walls = []

    def rect(x0, y0, w, h):
        walls.append({"polygon": [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]], "thickness_pt": t,
                      "style": "fill"})
    rect(ox, oy, total_w, t)
    rect(ox, oy + t + depth, total_w, t)
    d = 0.9 / mpt
    for i, xx in enumerate(xs):
        if 0 < i < len(xs) - 1:
            rect(xx, oy + t, t, depth / 2 - d / 2)
            rect(xx, oy + t + depth / 2 + d / 2, t, depth / 2 - d / 2)
        else:
            rect(xx, oy + t, t, depth)
    words = []
    for i, w in enumerate(rooms_m):
        cx, cy = xs[i] + t + w / mpt / 2, oy + t + depth / 2
        words += [{"text": f"Room{i}", "bbox": [cx - 15, cy - 12, cx + 10, cy - 4]},
                  {"text": f"{w * 4:.2f}", "bbox": [cx - 15, cy, cx + 3, cy + 8]},
                  {"text": "m²", "bbox": [cx + 4, cy, cx + 12, cy + 8]}]
    words.append({"text": f"1:{n}", "bbox": [ox, oy + depth + 60, ox + 30, oy + depth + 70]})
    return {"W_pt": 1190, "H_pt": 842, "rotate": 0, "paths": [], "words": words, "image_cover": 0.0}, walls


def test_rooms_regions_areas_and_scale():
    widths = [3.0, 4.5, 2.5]
    page, walls = _page_from_ops_free(widths)
    rs = R.rooms(page, walls)
    assert len(rs) == 3 and all(r["polygon"] for r in rs)
    sc = R.scale(page, rs)
    assert sc["method"] == "printed 1:100" and sc["ratio"] == "1:100"
    assert math.isclose(sc["m_per_pt"], PT_M * 100, rel_tol=1e-9)
    for r, w in zip(sorted(rs, key=lambda r: r["label_xy"][0]), widths):
        meas = r["pts_area"] * sc["m_per_pt"] ** 2
        assert abs(meas / (w * 4) - 1) < 0.03, (meas, w * 4)  # door-gap regrowth adds a sliver
        assert r["area_printed_m2"] == pytest.approx(w * 4)
    assert sc["check"]["agree_2pct"] is True


def test_scale_falls_back_to_area_fit_without_ratio():
    page, walls = _page_from_ops_free([3.0, 4.5, 2.5], n=50)
    page["words"] = [w for w in page["words"] if not w["text"].startswith("1:")]
    rs = R.rooms(page, walls)
    sc = R.scale(page, rs)
    assert sc["method"].startswith("printed areas fit")
    assert abs(sc["m_per_pt"] / (PT_M * 50) - 1) < 0.02
    assert sc["ratio"] == "1:50"   # a fit within 3% of a standard ratio snaps to it


def test_wrong_printed_ratio_is_flagged():
    page, walls = _page_from_ops_free([3.0, 4.5, 2.5], n=100)
    for w in page["words"]:
        if w["text"] == "1:100":
            w["text"] = "1:50"   # a detail scale elsewhere on the sheet
    rs = R.rooms(page, walls)
    sc = R.scale(page, rs)
    assert "flag" in sc["check"]
    assert sc["method"] == "printed areas fit" and abs(sc["m_per_pt"] / (PT_M * 100) - 1) < 0.02


def test_label_without_region_falls_back_to_point():
    page, walls = _page_from_ops_free([3.0, 4.5])
    page["words"] += [{"text": "Balcony", "bbox": [900, 700, 930, 708]}, {"text": "6.00 m²", "bbox": [900, 712, 930, 720]}]
    rs = R.rooms(page, walls)
    bal = [r for r in rs if r["label"] == "Balcony"]
    assert bal and bal[0]["polygon"] is None and bal[0]["area_printed_m2"] == 6.0


def test_scale_ladder_dimensions_and_door_guess():
    mpt = PT_M * 50
    paths, words = [], []
    for i, L_m in enumerate([3.6, 4.2, 2.4, 5.0]):
        L = L_m / mpt
        y = 100 + 30 * i
        paths.append({"pts": [[100, y], [100 + L, y]], "closed": False})
        words.append({"text": f"{L_m:.2f}", "bbox": [100 + L / 2 - 8, y - 9, 100 + L / 2 + 8, y - 1]})
    page = {"W_pt": 1190, "H_pt": 842, "paths": paths, "words": words}
    sc = R.scale(page, [])
    assert sc["method"] == "dimensions" and abs(sc["m_per_pt"] / mpt - 1) < 0.01
    r = 0.85 / mpt
    page = {"W_pt": 1190, "H_pt": 842, "words": [],
            "paths": [{"pts": [[0, 0], [r * 0.7, r * 0.3], [r, r]], "is_arc": True, "n_curves": 1}] * 3}
    sc = R.scale(page, [])
    assert sc["method"] == "door guess" and sc["check"]["approximate"] and abs(sc["m_per_pt"] / mpt - 1) < 0.01


# ------------------------------------------------------------ end to end through a real (synthetic) PDF

def test_synthetic_pdf_end_to_end(tmp_path):
    W, H = 1190.0, 842.0
    ops, areas = _plan_ops(H, [3.0, 4.5, 2.5], n=100)
    f = tmp_path / "plan.pdf"
    _pdf(f, W, H, ops)
    page = _load(f)
    walls = R.simple_walls(page)  # this test is about rooms/scale; pdf_vector.walls has its own tests
    rs = R.rooms(page, walls)
    sc = R.scale(page, rs)
    assert sc["ratio"] == "1:100" and math.isclose(sc["m_per_pt"], PT_M * 100, rel_tol=1e-9)
    printed = sorted(r["area_printed_m2"] for r in rs if r["area_printed_m2"])
    assert printed == pytest.approx(sorted(areas))
    with_poly = [r for r in rs if r["polygon"]]
    assert len(with_poly) == 3
    for r in with_poly:
        meas = r["pts_area"] * sc["m_per_pt"] ** 2
        assert abs(meas / r["area_printed_m2"] - 1) < 0.03


def test_scale_bar_irregular_steps_feet():
    k = 9.0  # pt per foot
    words = [{"text": t, "bbox": [500 + v * k - 3, 800, 500 + v * k + 3, 807]}
             for t, v in (("0", 0), ("4'", 4), ("8'", 8), ("16'", 16))]
    sc = R.scale({"W_pt": 1190, "H_pt": 842, "paths": [], "words": words}, [])
    assert sc["method"] == "scale bar" and abs(sc["m_per_pt"] / (0.3048 / k) - 1) < 1e-6


# ------------------------------------------------------------ r3: vertical tags, splits, partitions, door arcs

def _box_page(partition=False, labels=(("KITCHEN", "101", 2.5), ("BEDROOM", "102", 7.5))):
    """A 10 m x 4 m box at 1:100 (walls 0.2 m), labels at x metres along it, optional light partition at 5 m
    drawn as two thin parallel lines 0.1 m apart."""
    m = 1 / (PT_M * 100)          # pt per metre
    ox, oy, t = 100.0, 100.0, 0.2 * m

    def rect(x0, y0, x1, y1):
        return {"polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "thickness_pt": t}
    W, H = 10 * m, 4 * m
    walls = [rect(ox, oy, ox + W + 2 * t, oy + t), rect(ox, oy + t + H, ox + W + 2 * t, oy + 2 * t + H),
             rect(ox, oy, ox + t, oy + 2 * t + H), rect(ox + W + t, oy, ox + W + 2 * t, oy + 2 * t + H)]
    paths = []
    if partition:
        for dx in (5.0, 5.1):
            x = ox + t + dx * m
            paths.append({"pts": [[x, oy + t], [x, oy + t + H]], "closed": False, "stroke": [0, 0, 0], "fill": None,
                          "width": 0.3, "dashed": False})
    words = [{"text": "1:100", "bbox": [800, 600, 830, 610]}]
    for name, num, xm in labels:
        x, y = ox + t + xm * m, oy + t + 2 * m
        words += [{"text": name, "bbox": [x - 20, y - 6, x + 20, y + 2]}, {"text": num, "bbox": [x - 8, y + 4, x + 8, y + 12]}]
    return {"W_pt": 1000, "H_pt": 700, "rotate": 0, "paths": paths, "words": words, "image_cover": 0.0}, walls


def test_vertical_room_tag_is_read():
    # text turned 90 deg counter-clockwise: columns left to right, each read bottom to top
    words = [{"text": "K105", "bbox": [100, 150, 107, 167]}, {"text": "OFFICE", "bbox": [110, 140, 117, 170]},
             {"text": "16.5", "bbox": [120, 153, 127, 167]}, {"text": "m²", "bbox": [120, 141, 127, 150]}]
    bl = R.label_blocks(words)
    assert len(bl) == 1
    assert (bl[0]["label"], bl[0]["number"], bl[0]["area_printed_m2"]) == ("OFFICE", "K105", 16.5)


def test_two_labels_in_one_region_are_split():
    page, walls = _box_page(partition=False)
    rs = [r for r in R.rooms(page, walls) if r["labels"]]
    assert sorted(r["label"] for r in rs) == ["BEDROOM", "KITCHEN"]
    assert all(r["polygon"] and not r["merged"] for r in rs)
    a = [r["pts_area"] * (PT_M * 100) ** 2 for r in rs]
    assert abs(sum(a) - 40) < 2.5 and min(a) > 12


def test_light_partition_drawn_as_line_pair_separates_rooms():
    page, walls = _box_page(partition=True)
    rs = [r for r in R.rooms(page, walls) if r["labels"]]
    a = sorted(r["pts_area"] * (PT_M * 100) ** 2 for r in rs)
    assert len(a) == 2 and all(18 < v < 21 for v in a)   # 5.0 m and 4.9 m wide, 4 m deep


def test_one_name_and_number_per_room():
    r = R._room(None, [{"label": "WC", "number": "K117", "area_printed_m2": 1.5, "bbox": [0, 0, 1, 1], "xy": [0, 0]},
                       {"label": "CLEANER", "number": "K114", "area_printed_m2": 2.5, "bbox": [0, 0, 1, 1], "xy": [0, 0]}])
    assert (r["label"], r["number"]) == ("CLEANER", "K114") and len(r["labels"]) == 2


def test_door_guess_ignores_closed_circles():
    circ = [[10 + 5 * math.cos(a / 8 * math.pi), 10 + 5 * math.sin(a / 8 * math.pi)] for a in range(17)]
    page = {"paths": [{"pts": circ, "is_arc": True, "n_curves": 4, "closed": True}] * 5}
    assert R._door_guess(page) is None
    q = [[10 * math.cos(a / 8 * math.pi / 2), 10 * math.sin(a / 8 * math.pi / 2)] for a in range(9)]
    page["paths"] += [{"pts": q, "is_arc": True, "n_curves": 1, "closed": False}] * 3
    g = R._door_guess(page)
    assert g and abs(g["m_per_pt"] - 0.085) < 1e-6


def test_area_cut_frees_cubicle_from_lobby():
    """A WC cubicle whose front partition was not read joins the lobby: the tag's printed area guides a straight
    cut, the cubicle keeps its tag and the lobby is left as a separate piece."""
    from shapely.geometry import MultiLineString, Point, box
    from pipeline.pdf_rooms import _neck_split
    m = 0.01   # 1 pt = 1 cm
    g = box(0, 0, 166, 90).union(box(-10, 90, 250, 250))
    # no drawn line where the cut would go: no cut (cuts follow drawn linework, never just the printed number)
    assert _neck_split(g, 1.5, Point(83, 40), m, 1.5, 0.3, drawn=None) is None
    front = MultiLineString([[(0, 90), (60, 90)], [(140, 90), (166, 90)]])   # cubicle front with a door gap
    cut = _neck_split(g, 1.5, Point(83, 40), m, 1.5, 0.3, drawn=front)
    assert cut is not None
    room, rest = cut
    assert abs(room.area * m * m - 1.5) < 0.2
    assert room.bounds[3] <= 95 and rest.area * m * m > 3.5


def test_wall_run_gap_tells_a_facade_chord_from_a_partition():
    """A drawn line across a gap in a wall run (door / glazing bay on the facade line) is a room boundary; a
    partition ending in T-junctions on cross walls is not on a wall run."""
    import numpy as np
    from pipeline.pdf_rooms import _wall_run_gap
    ppm = 40.0                                  # px per metre
    mask = np.zeros((400, 800), np.uint8)
    mask[200:208, 0:300] = 255                  # facade wall, gap 300..460 (4 m), wall again
    mask[200:208, 460:800] = 255
    assert _wall_run_gap(mask, (300, 204), (460, 204), ppm)
    mask2 = np.zeros((400, 800), np.uint8)
    mask2[:, 100:108] = 255                     # two cross walls (0.2 m thick)
    mask2[:, 300:308] = 255
    assert not _wall_run_gap(mask2, (108, 150), (300, 150), ppm)
