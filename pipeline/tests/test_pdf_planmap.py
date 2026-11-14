"""pipeline/pdf_planmap: assembly of the vector-PDF plan map (CONTRACT 5.4 + PDF-3D addendum provenance keys)."""
import json
import math
from pathlib import Path

import pytest

from pipeline import pdf_planmap as P

M_PER_PT_100 = 25.4 / 72 / 1000 * 100  # 1:100


def synth_pdf(path: Path, w=842, h=595, rotate=0):
    """A tiny vector plan: a 300 x 200 pt flat, 10 pt walls (filled), one partition, two labelled rooms, 'SCALE 1:100'."""
    rects = [(100, 100, 300, 10), (100, 290, 300, 10), (100, 100, 10, 200), (390, 100, 10, 200), (240, 110, 10, 180)]
    ops = ["0 g"] + [f"{x} {h - y - hh} {ww} {hh} re f" for x, y, ww, hh in rects]
    txt = [(150, 200, "Kitchen"), (150, 215, "12.80 m2"), (300, 200, "Bedroom"), (300, 215, "12.80 m2"), (600, 550, "SCALE 1:100")]
    ops += [f"BT /F1 8 Tf {x} {h - y} Td ({t}) Tj ET" for x, y, t in txt]
    stream = "\n".join(ops).encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Rotate {rotate} /Contents 4 0 R "
            f"/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def page_dir(tmp_path, W=1684, H=1190):
    (tmp_path / "pages.json").write_text(json.dumps({"pages": [{"page": 1, "w": W, "h": H, "dpi": 144}]}))
    return tmp_path


PAGE = {"W_pt": 842.0, "H_pt": 595.0, "rotate": 0, "paths": [], "words": [], "image_cover": 0.0}
WALLS = [{"polygon": [[100, 100], [400, 100], [400, 110], [100, 110]], "thickness_pt": 10, "style": "fill"},
         {"polygon": [[100, 290], [400, 290], [400, 300], [100, 300]], "thickness_pt": 10, "style": "double"},
         {"polygon": [[240, 110], [250, 110], [250, 290], [240, 290]], "thickness_pt": 10, "style": "fill"},
         {"polygon": [[300, 150], [302, 150], [302, 152], [300, 152]], "thickness_pt": 2, "style": "stroke"}]  # a tick
ROOMS = [{"polygon": [[110, 110], [240, 110], [240, 290], [110, 290]], "label": "Kitchen", "number": "0.01",
          "area_printed_m2": 29.0, "label_bbox": [150, 195, 190, 220], "pts_area": 130 * 180},
         {"polygon": None, "label": "Bedroom", "number": None, "area_printed_m2": 12.8, "label_bbox": [300, 195, 340, 220]}]
OPENS = [{"kind": "door", "polygon": None, "bbox": [150, 285, 175, 300], "conf": 0.8, "props": {}},
         {"kind": "window", "polygon": [[300, 100], [340, 100], [340, 110], [300, 110]], "bbox": [300, 100, 340, 110],
          "conf": 0.7, "props": {}}]
SC = {"m_per_pt": M_PER_PT_100, "method": "printed_ratio", "confidence": 0.95, "ratio": 100,
      "check": {"printed_areas_rel_err": 0.012}}


def test_build_schema_and_provenance():
    W, H = 1684, 1190
    pm = P.build("d", 1, W, H, PAGE, WALLS, ROOMS, OPENS, SC)
    s = W / 842
    assert pm["image"] == {"w": W, "h": H} and pm["page"] == 1
    sc = pm["scale"]
    assert math.isclose(sc["m_per_px"], M_PER_PT_100 / s) and sc["m_per_pt"] == M_PER_PT_100 and sc["ratio"] == "1:100"
    assert sc["method"] == "printed_ratio" and sc["source"] == "printed 1:100" and 0 <= sc["confidence"] <= 1
    ids = [i["item_id"] for i in pm["items"]]
    assert len(ids) == len(set(ids)) and all(__import__("re").match(r"^[a-z]+-\d{3}$", i) for i in ids)
    for it in pm["items"]:
        assert set(it) >= {"item_id", "kind", "label", "bbox_px", "polygon_px", "props", "conf", "source"}
        assert len(it["bbox_px"]) == 4 and it["bbox_px"][0] <= it["bbox_px"][2] and it["bbox_px"][1] <= it["bbox_px"][3]
    kinds = [i["kind"] for i in pm["items"]]
    assert kinds.count("wall") == 3  # the 2 pt tick is dropped
    assert kinds.count("room") == 2 and kinds.count("door") == 1 and kinds.count("window") == 1
    k = next(i for i in pm["items"] if i["label"] == "Kitchen")
    assert math.isclose(k["q"]["area_m2"], round(130 * 180 * M_PER_PT_100 ** 2, 2)) and k["q"]["area_m2_printed"] == 29.0
    m = k["props"]["measure"]
    assert m["from"] == "pdf_vector" and m["pts_area"] == 130 * 180 and m["m_per_pt"] == M_PER_PT_100
    assert m["scale_source"] == "printed 1:100" and m["scale_check"]["printed_areas_rel_err"] == 0.012
    assert k["props"]["room_type"] == "kitchen" and k["props"]["area_m2_label"] == 29.0
    assert k["polygon_px"][0] == [round(110 * s, 1), round(110 * s, 1)]
    b = next(i for i in pm["items"] if i["label"] == "Bedroom")  # no polygon: placed at its label, printed area only
    assert b["polygon_px"] is None and b["q"]["area_m2"] is None and b["props"]["area_m2"] == 12.8
    w = next(i for i in pm["items"] if i["kind"] == "wall")
    assert math.isclose(w["q"]["length_m"], round(300 * M_PER_PT_100, 3)) and w["props"]["measure"]["pts_area"] == 3000
    assert w["props"]["thickness_px"] == round(10 * s, 2)
    d = next(i for i in pm["items"] if i["kind"] == "door")
    assert d["polygon_px"] and math.isclose(d["props"]["width_m"], round(25 * M_PER_PT_100, 3))


def test_pixel_mapping_round_trips():
    from pipeline import pdf_vector
    s = 1684 / 842
    for xy in ([0, 0], [842, 595], [123.25, 456.5]):
        px = pdf_vector.to_px(xy, s)
        assert math.isclose(px[0] / s, xy[0]) and math.isclose(px[1] / s, xy[1])


def _fake_modules(monkeypatch, gate=(True, "plan"), scale=SC):
    from pipeline import pdf_openings, pdf_rooms, pdf_vector
    monkeypatch.setattr(pdf_vector, "load_page", lambda pdf, i: dict(PAGE))
    monkeypatch.setattr(pdf_vector, "is_scanned", lambda page: False)
    monkeypatch.setattr(pdf_vector, "walls", lambda page: WALLS)
    monkeypatch.setattr(pdf_rooms, "rooms", lambda page, walls: ROOMS)
    monkeypatch.setattr(pdf_rooms, "scale", lambda page, rooms: scale)
    monkeypatch.setattr(pdf_openings, "gate", lambda page, walls, rooms: gate)
    monkeypatch.setattr(pdf_openings, "openings", lambda page, walls: OPENS)
    monkeypatch.setenv("PDF_PLANMAP_DRAFT", "0")


def test_process_writes_planmap(tmp_path, monkeypatch):
    _fake_modules(monkeypatch)
    pm = P.process("d", page_dir(tmp_path), tmp_path / "x.pdf", 0)
    assert pm and json.loads((tmp_path / "planmap-1.json").read_text()) == pm
    assert pm["provenance"]["gate"] == "plan" and pm["provenance"]["from"] == "pdf_vector"


def test_process_none_when_gate_rejects_or_no_scale(tmp_path, monkeypatch):
    _fake_modules(monkeypatch, gate=(False, "elevation"))
    assert P.process("d", page_dir(tmp_path), tmp_path / "x.pdf", 0) is None
    assert not (tmp_path / "planmap-1.json").exists()
    _fake_modules(monkeypatch, scale={"m_per_pt": None, "method": None, "confidence": 0, "ratio": None, "check": {}})
    assert P.process("d", page_dir(tmp_path), tmp_path / "x.pdf", 0) is None


def test_process_none_on_pixel_size_mismatch(tmp_path, monkeypatch):
    _fake_modules(monkeypatch)  # page rendered rotated (portrait) while the reader says landscape
    assert P.process("d", page_dir(tmp_path, W=1190, H=1684), tmp_path / "x.pdf", 0) is None


def test_room_type_words():
    assert P.room_type("Camera") == "bedroom" and P.room_type("BATH") == "bathroom" and P.room_type("Soggiorno") == "living"
    assert P.room_type(None) == "other"


def test_synthetic_pdf_end_to_end_real_modules(tmp_path):
    """Real role modules on a generated vector PDF: never raises; a result, if any, is a valid plan map in page pixels."""
    pdf = synth_pdf(tmp_path / "plan.pdf")
    import pypdfium2 as pdfium
    d = pdfium.PdfDocument(str(pdf))
    W_pt, H_pt = d[0].get_size()
    d.close()
    W, H = int(W_pt * 2), int(H_pt * 2)
    page_dir(tmp_path, W, H)
    pm = P.process("d", tmp_path, pdf, 0)
    if pm is not None:
        assert pm["image"] == {"w": W, "h": H} and pm["scale"]["m_per_px"] > 0
        assert all(0 <= v <= max(W, H) + 1 for i in pm["items"] for v in i["bbox_px"])
