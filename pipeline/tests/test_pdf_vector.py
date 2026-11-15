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
    # pieces overlap only in the corner squares (ends are extended into the crossing wall to close corners)
    assert sum(p.area for p in polys) - unary_union(polys).area <= 4 * 8 * 8 + 1


def test_centerlines_and_exact_thickness(tmp_path):
    """Each wall carries a centreline and the edge-to-edge thickness (fill width), for IfcWall export."""
    ws = V.walls(V.load_page(write_pdf(tmp_path / "c.pdf", room_filled(100, 100, 400, 300, 8)), 0))
    assert len(ws) == 4
    for w in ws:
        (x0, y0), (x1, y1) = w["centerline"]
        assert w["thickness_pt"] == pytest.approx(8, abs=0.05)
        assert x0 == pytest.approx(x1, abs=0.01) or y0 == pytest.approx(y1, abs=0.01)
    xs = sorted({round(w["centerline"][0][0]) for w in ws if abs(w["centerline"][0][0] - w["centerline"][1][0]) < 0.01})
    assert xs == [104, 396]  # centres of the 8 pt side walls


def test_fixture_fill_not_wall(tmp_path):
    """A light-grey counter holding burner circles, against a wall, is not a wall."""
    k = 0.5523 * 4
    burner = (f"0 G 0.3 w 254 140 m 254 {140 + k} {250 + k} 144 250 144 c {250 - k} 144 246 {140 + k} 246 140 c "
              f"246 {140 - k} {250 - k} 136 250 136 c {250 + k} 136 254 {140 - k} 254 140 c h S\n")
    body = room_filled(100, 100, 400, 300, 8) + "0.85 g 0 G 0.5 w 200 108 120 18 re B\n" + burner
    ws = V.walls(V.load_page(write_pdf(tmp_path / "k.pdf", body), 0))
    assert all(w["thickness_pt"] < 10 for w in ws)
    assert wall_len(ws) == pytest.approx(wall_len(V.walls(V.load_page(
        write_pdf(tmp_path / "k0.pdf", room_filled(100, 100, 400, 300, 8)), 0))), rel=0.03)


def test_polygons_have_no_holes(tmp_path):
    ws = V.walls(V.load_page(write_pdf(tmp_path / "r.pdf", room_filled(100, 100, 400, 300, 8)), 0))
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    u = unary_union([Polygon(w["polygon"]) for w in ws])
    assert u.area == pytest.approx(2 * 8 * 300 + 2 * 8 * 184, rel=0.02)  # ring area, not the filled box


def _w(x0, y0, x1, y1, t, style):
    from pipeline.pdf_vector import _wall_rect
    return {"polygon": _wall_rect([x0, y0], [x1, y1], t), "centerline": [[x0, y0], [x1, y1]], "thickness_pt": t,
            "style": style, **({"height_m": 1.0} if style == "parapet" else {})}


def test_settle_parapets_enclosed_open_and_layers():
    from pipeline.pdf_vector import _settle_parapets
    box = [_w(0, 0, 400, 0, 10, "double"), _w(0, 300, 400, 300, 10, "double"),
           _w(0, 0, 0, 300, 10, "double"), _w(400, 0, 400, 300, 10, "double")]
    inner = _w(200, 10, 200, 290, 3, "parapet")          # partition between two rooms: walls on both sides
    edge = _w(-150, -150, -150, 450, 3, "parapet")        # balcony edge: nothing beyond it
    layer = _w(10, 6.5, 390, 6.5, 3, "parapet")           # inner layer lying flat against the top wall
    out = _settle_parapets([*box, inner, edge, layer])
    st = {(tuple(w["centerline"][0]), w["style"]) for w in out}
    assert ((200, 10), "fill") in st and "height_m" not in next(w for w in out if w["centerline"][0] == [200, 10])
    assert ((-150, -150), "parapet") in st
    assert len(out) == 6  # the layer merged into the top wall
    top = next(w for w in out if abs(w["centerline"][0][1]) < 5 and w["style"] == "double")
    assert abs(top["thickness_pt"] - 13.0) < 0.01 and top["centerline"][0][0] == 0 and top["centerline"][1][0] == 400


def test_path_form_and_wipeouts():
    from pipeline import pdf_vector as pv
    paths = [{"pts": [[0, 0], [10, 0]], "stroke": [0, 0, 0], "fill": None, "obj": 0},
             {"pts": [[20, 20], [30, 20]], "stroke": [0, 0, 0], "fill": None, "obj": 1},
             {"pts": [[-1, -1], [11, -1], [11, 1], [-1, 1]], "stroke": None, "fill": [1, 1, 1], "obj": 2, "closed": True}]
    assert pv._white_over(paths) == [2]
    kept = pv.drop_wiped(paths)
    assert len(kept) == 2 and kept[0]["obj"] == 1  # the line under the later white mask is gone
    assert pv.path_form({"obj_form": [0, 3]}, {"obj": 1}) == 3 and pv.path_form({}, {"obj": 1}) == -1


def _wc(c0, c1, t, style="double"):
    w = {"style": style}
    V._set_geom(w, c0, c1, t)
    return w


def test_thickness_classes_and_known_sizes():
    ws = [_wc((0, 0), (100, 0), 4.0), _wc((0, 10), (100, 10), 4.2), _wc((0, 20), (80, 20), 8.0),
          _wc((0, 30), (90, 30), 8.3), _wc((0, 40), (5, 40), 6.0)]
    cl = V.thickness_classes(ws)
    assert len(cl) == 2 and 3.9 < cl[0] < 4.3 and 7.9 < cl[1] < 8.4
    mpt = 0.1 / 4.1  # 4.1 pt = 100 mm: the known built size wins
    cl2 = V.thickness_classes(ws, mpt)
    assert abs(cl2[0] - 4.1) < 1e-6


def test_clean_walls_duplicates_join_and_classes():
    page = {"paths": []}
    ws = [_wc((0, 0), (50, 0), 6.0), _wc((50.5, 0), (100, 0), 6.0),  # collinear pieces, small gap -> one run
          _wc((10, 0), (30, 0), 3.0),                              # inside the wider wall -> duplicate
          _wc((0, 0), (0, 80), 6.0), _wc((100, 0), (100, 80), 6.0),
          _wc((0, 80), (40, 80), 6.0), _wc((140, 80), (100, 80), 6.0)]  # 60 pt door gap stays open
    out = V._clean_walls(page, ws)
    horiz0 = [w for w in out if abs(w["centerline"][0][1]) < 1 and abs(w["centerline"][1][1]) < 1]
    assert len(horiz0) == 1 and abs(horiz0[0]["centerline"][1][0] - horiz0[0]["centerline"][0][0]) >= 99
    top = [w for w in out if abs(w["centerline"][0][1] - 80) < 1 and abs(w["centerline"][1][1] - 80) < 1]
    assert len(top) == 2
    assert all(w["props"]["thickness_class"] is not None for w in out)


def _partition_page(tmp_path, glazing=False):
    # room 300 x 200 pt (6 pt walls, our y-down frame y 100..300); a thin partition (faces 3 pt apart) at x 250
    # from the top wall to a 30 pt door gap (our y 200..230), then on to the bottom wall
    faces = "".join(f"{x} 294 m {x} 200 l S {x} 170 m {x} 106 l S " for x in (248.5, 251.5))
    if glazing:
        faces += "250 294 m 250 200 l S 250 170 m 250 106 l S "
    pdf = write_pdf(tmp_path / "p.pdf", room_double(100, 100, 400, 300, 6) + "0 G 0.3 w " + faces + "\n")
    page = V.load_page(pdf, 0)
    walls = [_wc((100, 103), (400, 103), 6.0), _wc((100, 297), (400, 297), 6.0),
             _wc((103, 100), (103, 300), 6.0), _wc((397, 100), (397, 300), 6.0)]
    door = {"kind": "door", "bbox": [248.5, 200.0, 251.5, 230.0],
            "props": {"hinge": [250.0, 200.0], "axis_deg": 90.0, "width_pt": 30.0, "wall_index": None}}
    return page, walls, door


def test_partitions_for_unhosted_door(tmp_path):
    page, walls, door = _partition_page(tmp_path)
    mpt = 0.1 / 3.0  # the 3 pt face spacing = 100 mm
    out = V.partitions_for_doors(page, [door], walls, mpt)
    assert len(out) == 2 and all(w["style"] == "double" for w in out)
    spans = sorted(sorted(p[1] for p in w["centerline"]) for w in out)
    assert spans[0] == pytest.approx([106, 200], abs=1.0) and spans[1] == pytest.approx([230, 294], abs=1.0)
    for w in out:  # drawn stretches only: the door gap stays open; measured faces 3 pt apart on x 250
        assert w["thickness_pt"] == pytest.approx(3.0, abs=0.2)
        assert all(abs(p[0] - 250) < 0.3 for p in w["centerline"])
        ev = w["props"]["evidence"]
        assert ev["source"] == "measured" and ev["rule"] == "partition_for_unhosted_door" and ev["paths"]
    # a hosted door asks for nothing
    hosted = dict(door, props=dict(door["props"], wall_index=0))
    assert V.partitions_for_doors(page, [hosted], walls, mpt) == []


def test_partitions_for_doors_skip_glazing(tmp_path):
    page, walls, door = _partition_page(tmp_path, glazing=True)
    assert V.partitions_for_doors(page, [door], walls, 0.1 / 3.0) == []
