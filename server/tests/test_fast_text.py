"""Quick pdfium text layer (ingest on a small container) agrees with pdfminer, for every page rotation; the exact
pdfminer text replaces it after ingest (refine_text)."""
import json

import pytest

def _pdf(path, rotate):
    """Hand-built one-page PDF (Helvetica text), so the test needs no PDF writer library."""
    texts = [(40, 330, "DOOR 101"), (260, 200, "WINDOW W7"), (80, 80, "ROOM Kitchen 12.5 m2")]
    stream = "BT /F1 14 Tf " + " ".join(f"1 0 0 1 {x} {y} Tm ({t}) Tj" for x, y, t in texts) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 360] /Rotate {rotate} /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    path.write_bytes(out)


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u else 0


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_pdfium_words_match_pdfminer(tmp_path, rotate):
    from pipeline import pages
    pdf = tmp_path / "a.pdf"
    _pdf(pdf, rotate)
    res = {}
    for fast in (False, True):
        out = tmp_path / ("fast" if fast else "slow")
        out.mkdir()
        pages.do_pdf(pdf, "d", out, fast_text=fast)
        res[fast] = json.loads((out / "text-1.json").read_text())
    assert res[True]["extractor"] == "pdfium" and res[False]["extractor"] == "pdfminer"
    fast = res[True]["words"]
    assert {"DOOR", "101", "WINDOW", "W7", "Kitchen"} <= {w["text"] for w in fast}
    if rotate in (90, 270):
        # pdfminer breaks sideways text into single letters, so only check the geometry: "Kitchen" reads
        # along the displayed vertical axis, inside the page.
        k = next(w for w in fast if w["text"] == "Kitchen")["bbox_px"]
        assert (k[3] - k[1]) > (k[2] - k[0]) and min(k) >= 0
        return
    assert {w["text"] for w in fast} == {w["text"] for w in res[False]["words"]}
    for w in fast:
        same = [v["bbox_px"] for v in res[False]["words"] if v["text"] == w["text"]]
        assert any(_iou(w["bbox_px"], b) > 0.3 for b in same), (rotate, w)


def test_refine_replaces_quick_text(tmp_path, monkeypatch):
    from pipeline import pages
    from server import ingest_job
    monkeypatch.setattr(ingest_job, "REPO", tmp_path)
    (tmp_path / "up").mkdir()
    pdf = tmp_path / "up" / "a.pdf"
    _pdf(pdf, 0)
    d = tmp_path / "doc"
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"doc_id": "d", "files": {"pdf": "up/a.pdf"}}))
    pages.do_pdf(pdf, "d", d, fast_text=True)
    assert json.loads((d / "text-1.json").read_text())["extractor"] == "pdfium"
    assert ingest_job.refine_text("d", d) == 1
    assert json.loads((d / "text-1.json").read_text())["extractor"] == "pdfminer"
    assert "Kitchen" in json.loads((d / "text.json").read_text())["pages"][0]["text"]
