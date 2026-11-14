"""pipeline/pdf_vector: synthetic PDFs written by hand (no reportlab): filled walls, double-line walls, a rotated
page, and the point -> pixel mapping against the pypdfium2 render that pages.do_pdf uses."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline import pdf_vector as V  # noqa: E402


def write_pdf(path: Path, content: str, w=600, h=400, rotate=0, cropbox=None):
    """Minimal one-page PDF with one content stream (PDF user space: origin bottom-left)."""
    data = content.encode()
    extra = f" /Rotate {rotate}" if rotate else ""
    if cropbox:
        extra += " /CropBox [%g %g %g %g]" % tuple(cropbox)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}]{extra} /Contents 4 0 R "
         f"/Resources << /Font << /F1 5 0 R >> >> >>").encode(),
        b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += b"%d 0 obj\n" % (i + 1) + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def room_filled(x0, y0, x1, y1, t):
    """A rectangular room whose walls are dark filled rectangles of thickness t (outer box x0..x1)."""
    r = [(x0, y0, x1 - x0, t), (x0, y1 - t, x1 - x0, t), (x0, y0, t, y1 - y0), (x1 - t, y0, t, y1 - y0)]
    return "0.1 g\n" + "".join(f"{a} {b} {c} {d} re f\n" for a, b, c, d in r)


def room_double(x0, y0, x1, y1, t):
    """Walls as CAD outlines: outer and inner rectangles stroked, thin lines (no fill)."""
    return (f"0 G 0.5 w {x0} {y0} {x1 - x0} {y1 - y0} re S\n"
            f"{x0 + t} {y0 + t} {x1 - x0 - 2 * t} {y1 - y0 - 2 * t} re S\n")


def wall_len(ws):
    return V.wall_length_pt(ws)


def test_filled_walls(tmp_path):
    pdf = write_pdf(tmp_path / "f.pdf", room_filled(100, 100, 400, 300, 8) + "BT /F1 10 Tf 200 200 Td (KITCHEN) Tj ET\n")
    pg = V.load_page(pdf, 0)
    assert pg["W_pt"] == 600 and pg["H_pt"] == 400 and pg["rotate"] == 0
    assert any(w["text"] == "KITCHEN" for w in pg["words"])
    ws = V.walls(pg)
    assert ws and all(w["style"] == "fill" for w in ws)
    assert all(6 <= w["thickness_pt"] <= 9 for w in ws)
    # centre-line length of a 300x200 box with 8 pt walls is about 2*(292+192)=968
    assert abs(wall_len(ws) - 968) / 968 < 0.1
    # y down: the top wall (PDF y 292..300) is at y 100..108 in our frame
    ys = [p[1] for w in ws for p in w["polygon"]]
    assert min(ys) == pytest.approx(100, abs=0.5) and max(ys) == pytest.approx(300, abs=0.5)
    assert not V.is_scanned(pg)


def test_double_line_walls(tmp_path):
    pdf = write_pdf(tmp_path / "d.pdf", room_double(100, 100, 400, 300, 6) + room_double(400, 100, 550, 300, 6)
                    + "0.2 w 200 150 m 260 150 l S\n")  # a stray thin line (furniture-ish)
    pg = V.load_page(pdf, 0)
    ws = V.walls(pg)
    assert ws and {w["style"] for w in ws} == {"double"}
    assert all(4 <= w["thickness_pt"] <= 13 for w in ws)  # shared wall: two 6 pt outlines back to back
    L = wall_len(ws)
    assert 1200 < L < 1900, L  # two rooms sharing a wall position (outlines overlap at x=400..406)


def test_rotated_page_matches_render(tmp_path):
    """A /Rotate 90 page: our coordinates must land on the pypdfium2 render's dark pixels."""
    pdf = write_pdf(tmp_path / "r.pdf", room_filled(100, 100, 400, 300, 10), rotate=90)
    pg = V.load_page(pdf, 0)
    assert pg["rotate"] == 90 and pg["W_pt"] == 400 and pg["H_pt"] == 600
    ws = V.walls(pg)
    assert ws
    import pypdfium2 as pdfium
    s = 2.0
    doc = pdfium.PdfDocument(str(pdf))
    img = np.asarray(doc[0].render(scale=s).to_pil().convert("L"))
    doc.close()
    assert img.shape == (round(600 * s), round(400 * s))
    from shapely.geometry import Polygon
    hit = tot = 0
    for w in ws:
        poly = Polygon(w["polygon"])
        c = poly.representative_point()
        x, y = V.to_px((c.x, c.y), s)
        tot += 1
        hit += img[int(y), int(x)] < 80
    assert hit == tot


def test_cropbox_offset(tmp_path):
    pdf = write_pdf(tmp_path / "c.pdf", room_filled(100, 100, 400, 300, 8), cropbox=(50, 50, 550, 350))
    pg = V.load_page(pdf, 0)
    assert pg["W_pt"] == pytest.approx(500) and pg["H_pt"] == pytest.approx(300)
    xs = [p[0] for w in V.walls(pg) for p in w["polygon"]]
    assert min(xs) == pytest.approx(50, abs=0.5)


def test_px_round_trip():
    s = V.render_scale(3024, 2160)
    for xy in [(0, 0), (12.5, 700.25), (3024, 2160)]:
        px = V.to_px(xy, s)
        assert V.to_pt(px, s) == pytest.approx(list(xy))
    assert max(3024, 2160) * s <= 7000 + 1e-6


def test_hatched_lines_not_walls(tmp_path):
    """A field of equally spaced parallel lines (floor pattern / stairs) is not a wall."""
    lines = "".join(f"0 G 0.3 w {100 + 8 * i} 100 m {100 + 8 * i} 300 l S\n" for i in range(20))
    pdf = write_pdf(tmp_path / "h.pdf", lines)
    assert V.walls(V.load_page(pdf, 0)) == []


def test_pdfminer_fallback_agrees(tmp_path):
    pdf = write_pdf(tmp_path / "m.pdf", room_filled(100, 100, 400, 300, 8), rotate=90)
    a = V.load_page(pdf, 0, reader="pdfium")
    b = V.load_page(pdf, 0, reader="pdfminer")
    assert (a["W_pt"], a["H_pt"]) == pytest.approx((b["W_pt"], b["H_pt"]))
    assert wall_len(V.walls(a)) == pytest.approx(wall_len(V.walls(b)), rel=0.05)


def test_fill_plus_outline_counted_once(tmp_path):
    """Exporters often draw a wall as a hatch/dark fill AND stroke its two faces: one wall, not two."""
    body = room_filled(100, 100, 400, 300, 8) + room_double(100, 100, 400, 300, 8)
    a = V.walls(V.load_page(write_pdf(tmp_path / "a.pdf", room_filled(100, 100, 400, 300, 8)), 0))
    b = V.walls(V.load_page(write_pdf(tmp_path / "b.pdf", body), 0))
    assert wall_len(b) == pytest.approx(wall_len(a), rel=0.08)
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = [Polygon(w["polygon"]) for w in b]
    assert unary_union(polys).area == pytest.approx(sum(p.area for p in polys), rel=0.01)  # no overlaps


def test_polygons_have_no_holes(tmp_path):
    ws = V.walls(V.load_page(write_pdf(tmp_path / "r.pdf", room_filled(100, 100, 400, 300, 8)), 0))
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    u = unary_union([Polygon(w["polygon"]) for w in ws])
    assert u.area == pytest.approx(2 * 8 * 300 + 2 * 8 * 184, rel=0.02)  # ring area, not the filled box
