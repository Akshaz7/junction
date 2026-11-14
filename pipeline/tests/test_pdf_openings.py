"""pdf_openings: doors / windows / gate on a synthetic hand-written vector PDF and on synthetic page dicts."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from pipeline import pdf_openings as po

K = 0.5523  # Bezier quarter-circle constant


def _pdf(path: Path, ops: list[str], texts: list[tuple[float, float, float, str]], W=600, H=400):
    """Minimal one-page PDF (PDF y-up coordinates) with stroke/fill ops and Helvetica text."""
    body = "\n".join(ops)
    for x, y, size, t in texts:
        body += f"\nBT /F1 {size} Tf {x} {y} Td ({t}) Tj ET"
    stream = body.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents 4 0 R "
        f"/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def _plan_ops():
    ops = ["0 g"]
    walls = [(50, 300, 150, 10), (245, 300, 105, 10), (420, 300, 130, 10),   # top wall: door gap 200-245, window 350-420
             (50, 100, 10, 200), (540, 100, 10, 200),                        # sides
             (50, 100, 250, 10), (340, 100, 210, 10),                        # bottom wall: door gap 300-340
             (450, 110, 10, 190)]                                            # partition
    ops += [f"{x} {y} {w} {h} re f" for x, y, w, h in walls]
    ops.append("0 G 0.5 w")
    # door 1: Bezier swing, hinge (200,300), closed end (245,300), open leaf to (200,255)
    ops.append(f"245 300 m 245 {300 - K * 45:.3f} {200 + K * 45:.3f} 255 200 255 c S")
    ops.append("200 300 m 200 255 l S")
    # door 2: CAD-style flattened swing (12 separate segments), hinge (300,110), closed (340,110), open (300,150)
    pts = [(300 + 40 * math.cos(math.radians(a)), 110 + 40 * math.sin(math.radians(a))) for a in range(0, 91, 90 // 12 + 1)]
    pts[-1] = (300.0, 150.0)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        ops.append(f"{x0:.3f} {y0:.3f} m {x1:.3f} {y1:.3f} l S")
    ops.append("300 110 m 300 150 l S")
    # window: 3 glazing lines across the top-wall gap 350-420
    ops.append("0.25 w")
    ops += [f"350 {y} m 420 {y} l S" for y in (301, 305, 309)]
    # stair-like parallel lines far from walls (spacing too wide for glazing) + a furniture circle-ish arc
    ops += [f"100 {y} m 180 {y} l S" for y in range(150, 260, 20)]
    return ops


TEXTS = [(120, 200, 8, "LIVING"), (120, 190, 8, "20.5 m2"), (480, 200, 8, "BATH"), (480, 190, 8, "4.1 m2"),
         (60, 60, 10, "GROUND FLOOR PLAN 1:50")]


@pytest.fixture(scope="module")
def plan_page(tmp_path_factory):
    from pipeline import pdf_vector as pv
    pdf = _pdf(tmp_path_factory.mktemp("op") / "plan.pdf", _plan_ops(), TEXTS)
    page = pv.load_page(pdf, 0)
    if not page.get("W_pt"):
        pytest.skip("pdf_vector.load_page is still a stub")
    return page


def _walls():
    rects = [(50, 300, 150, 10), (245, 300, 105, 10), (420, 300, 130, 10), (50, 100, 10, 200), (540, 100, 10, 200),
             (50, 100, 250, 10), (340, 100, 210, 10), (450, 110, 10, 190)]
    out = []
    for x, y, w, h in rects:  # to top-left / y-down (H = 400)
        y0 = 400 - (y + h)
        out.append({"polygon": [[x, y0], [x + w, y0], [x + w, y0 + h], [x, y0 + h]], "thickness_pt": float(min(w, h)),
                    "style": "fill"})
    return out


def test_doors_and_window_on_synthetic_pdf(plan_page):
    ops = po.openings(plan_page, _walls())
    doors = [o for o in ops if o["kind"] == "door"]
    wins = [o for o in ops if o["kind"] == "window"]
    assert len(doors) == 2, doors
    widths = sorted(d["props"]["width_pt"] for d in doors)
    assert widths[0] == pytest.approx(40, abs=1.5) and widths[1] == pytest.approx(45, abs=1.5)
    assert all(d["props"]["leaf"] for d in doors)
    d1 = next(d for d in doors if d["props"]["width_pt"] > 42)
    # gap rectangle spans the wall gap x 200..245 and lies within the wall band y 90..100 (y-down)
    b = d1["bbox"]
    assert b[0] == pytest.approx(200, abs=1) and b[2] == pytest.approx(245, abs=1)
    assert 89 <= b[1] and b[3] <= 101
    assert d1["props"]["hinge"] == pytest.approx([200, 100], abs=0.6)
    assert len(wins) == 1, wins
    w = wins[0]
    assert w["props"]["n_lines"] == 3 and w["props"]["width_pt"] == pytest.approx(70, abs=1)
    assert w["bbox"][0] == pytest.approx(350, abs=1) and w["bbox"][2] == pytest.approx(420, abs=1)


def test_gate_plan(plan_page):
    rooms = [{"polygon": None, "label": "LIVING", "number": None, "area_printed_m2": 20.5, "label_bbox": None},
             {"polygon": None, "label": "BATH", "number": None, "area_printed_m2": 4.1, "label_bbox": None}]
    ok, why = po.gate(plan_page, _walls(), rooms)
    assert ok, why


def _page(words, n_paths=500, cover=0.0):
    seg = {"pts": [[0, 0], [1, 1]], "closed": False, "fill": None, "stroke": [0, 0, 0], "width": 0.2,
           "n_curves": 0, "is_arc": False}
    return {"W_pt": 1000, "H_pt": 700, "rotate": 0, "paths": [seg] * n_paths, "image_cover": cover,
            "words": [{"text": t, "bbox": [10, 10 + 40 * i, 10 + 12 * len(t), 34 + 40 * i]} for i, t in enumerate(words)]
            + [{"text": t, "bbox": [300, 300 + 12 * i, 330, 308 + 12 * i]}                      # body-size notes
               for i, t in enumerate(["SEE", "SECTION", "3/A301", "ELEVATION", "NOTE", "TYP.", "GWB", "EQ"])]}


ROOMS = [{"label": "Kitchen", "area_printed_m2": 12.0}, {"label": "Bed", "area_printed_m2": 14.0}]


@pytest.mark.parametrize("title", ["SOUTH ELEVATION", "DOOR SCHEDULE", "Schnitt A-A", "Ansicht Nord",
                                   "WALL SECTION", "julkisivu etelään", "leikkaus A-A", "TYPICAL DETAILS"])
def test_gate_rejects_headings(title):
    ok, why = po.gate(_page([title, "A-201", "1:50"]), _walls(), ROOMS)
    assert not ok and "heading" in why


def test_gate_rejects_scanned_and_sparse():
    ok, why = po.gate(_page(["FLOOR PLAN"], n_paths=20, cover=0.95), _walls(), ROOMS)
    assert not ok and "scanned" in why
    ok, why = po.gate(_page(["FLOOR PLAN"]), _walls()[:3], ROOMS)
    assert not ok and "wall" in why
    ok, why = po.gate(_page(["FLOOR PLAN"]), _walls(), ROOMS[:1])
    assert not ok and "room" in why
    ok, why = po.gate(_page(["FLOOR PLAN"]), _walls(), [{"label": "Hall", "area_printed_m2": 900.0},
                                                        {"label": "Yard", "area_printed_m2": 1500.0}])
    assert not ok and "area" in why
    ok, why = po.gate(_page(["FLOOR PLAN"]), _walls(), ROOMS)
    assert ok, why


def test_gate_ignores_body_size_callouts():
    ok, why = po.gate(_page(["FLOOR PLAN"]), _walls(), ROOMS)   # notes say SECTION / ELEVATION at body size
    assert ok, why
    ok, why = po.gate(_page(["FLOOR PLAN", "DOOR SCHEDULE", "DETAILS"]), _walls(), ROOMS)  # schedules outrank plan
    assert not ok


def test_empty_inputs():
    assert po.openings({}, []) == []
    assert po.gate({}, [], [])[0] is False
