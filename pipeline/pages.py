"""D-05: page images (page-<n>.png + page-<n>.thumb.png) and PDF text layer (text-<n>.json).

Usage: uv run python -m pipeline.pages [--root DATASET_ROOT] [--artifacts DIR] [--only DOC_ID ...] [-j 3]
Page source priority per doc: pdf > svg > dxf > raster. IFC-only docs get no page (see D-07). DWG: no converter.
text-<n>.json: {"doc_id","page","image":{"w","h"},"dpi","source":"pdf-text-layer","words":[{"text","bbox_px":[x0,y0,x1,y1]}]}
Word boxes are in page-image pixels, origin top-left (CONTRACT 5.2).
"""
import argparse
import json
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
DPI = 150
MAX_SIDE = 7000
MAX_PAGES = 20
THUMB = 320
Image.MAX_IMAGE_PIXELS = None


def save_page(img: Image.Image, out: Path, n: int):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.save(out / f"page-{n}.png")
    t = img.copy()
    t.thumbnail((THUMB, THUMB))
    t.save(out / f"page-{n}.thumb.png")
    return img.size


# ---------- PDF ----------
def pdf_words(pdf: Path, page_no: int, scale: float, W: int, H: int):
    """Words with bbox in render pixels. pdfminer.six (PyMuPDF is AGPL)."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTAnno, LTChar, LTTextContainer, LTTextLine, LTFigure

    words = []

    def flush(chars):
        if not chars:
            return
        txt = "".join(c.get_text() for c in chars).strip()
        if not txt:
            return
        x0 = min(c.x0 for c in chars); x1 = max(c.x1 for c in chars)
        y0 = min(c.y0 for c in chars); y1 = max(c.y1 for c in chars)
        words.append((txt, x0, y0, x1, y1))

    def walk(o):
        if isinstance(o, LTTextLine):
            cur = []
            for c in o:
                if isinstance(c, LTChar) and c.get_text().strip():
                    cur.append(c)
                else:
                    flush(cur); cur = []
            flush(cur)
        elif isinstance(o, (LTTextContainer, LTFigure)) or hasattr(o, "__iter__"):
            for c in o:
                walk(c)

    pg = next(iter(extract_pages(str(pdf), page_numbers=[page_no], laparams=LAParams(char_margin=1.5, line_margin=0.3))))
    wpt, hpt = pg.width, pg.height  # pdfminer: already rotated? it reports mediabox as stored; handle below
    for o in pg:
        walk(o)
    return words, wpt, hpt


def do_pdf(pdf: Path, doc_id: str, out: Path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    n_pages = min(len(doc), MAX_PAGES)
    pages = []
    for i in range(n_pages):
        page = doc[i]
        w_pt, h_pt = page.get_size()  # rotated size as displayed
        dpi = DPI
        s = dpi / 72
        if max(w_pt, h_pt) * s > MAX_SIDE:
            s = MAX_SIDE / max(w_pt, h_pt); dpi = round(s * 72)
        img = page.render(scale=s).to_pil()
        W, H = save_page(img, out, i + 1)
        words = []
        try:
            raw, pw, ph = pdf_words(pdf, i, s, W, H)
            rot = page.get_rotation() % 360
            for t, x0, y0, x1, y1 in raw:
                # pdfminer coords: points, origin bottom-left of the unrotated mediabox
                if rot == 0:
                    bx = (x0 * s, (ph - y1) * s, x1 * s, (ph - y0) * s)
                elif rot == 90:
                    bx = (y0 * s, x0 * s, y1 * s, x1 * s)
                elif rot == 180:
                    bx = ((pw - x1) * s, y0 * s, (pw - x0) * s, y1 * s)
                else:
                    bx = ((ph - y1) * s, (pw - x1) * s, (ph - y0) * s, (pw - x0) * s)
                bx = [round(max(0, min(v, lim)), 1) for v, lim in zip(bx, (W, H, W, H))]
                words.append({"text": t, "bbox_px": bx})
        except Exception as e:  # noqa: BLE001
            print(f"  text fail {doc_id} p{i+1}: {e!r}", file=sys.stderr)
        if words:
            (out / f"text-{i+1}.json").write_text(json.dumps(
                {"doc_id": doc_id, "page": i + 1, "image": {"w": W, "h": H}, "dpi": round(dpi),
                 "source": "pdf-text-layer", "words": words}, ensure_ascii=False))
        pages.append({"page": i + 1, "w": W, "h": H, "dpi": round(dpi), "words": len(words)})
        page.close()
    doc.close()
    return pages


# ---------- SVG / DXF / raster ----------
def do_svg(svg: Path, out: Path):
    tmp = out / "tmp"; tmp.mkdir(exist_ok=True)
    png = tmp / "svg.png"
    subprocess.run(["rsvg-convert", "-d", str(DPI), "-p", str(DPI), "-b", "white", "-o", str(png), str(svg)], check=True)
    img = Image.open(png)
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    W, H = save_page(img, out, 1)
    return [{"page": 1, "w": W, "h": H, "dpi": DPI, "words": 0}]


def dxf_lines(doc):
    """Modelspace flattened to polylines (text/hatch skipped)."""
    from ezdxf import path as ezpath
    lines = []

    def add(e):
        try:
            if e.dxftype() == "INSERT":
                for v in e.virtual_entities():
                    add(v)
                return
            if e.dxftype() in ("TEXT", "MTEXT", "HATCH", "DIMENSION", "POINT", "SOLID", "IMAGE"):
                return
            p = ezpath.make_path(e)
            pts = [(v.x, v.y) for v in p.flattening(0.05)]
            if len(pts) > 1:
                lines.append(pts)
        except Exception:
            pass

    for e in doc.modelspace():
        add(e)
    return lines


def dxf_frame(lines, px=3000):
    """(x0, y0, scale, W, H): the exact mapping do_dxf uses (y flipped, 20 px margin)."""
    xs = [x for l in lines for x, _ in l]; ys = [y for l in lines for _, y in l]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = (px - 40) / max(x1 - x0, y1 - y0)
    return x0, y0, s, int((x1 - x0) * s) + 40, int((y1 - y0) * s) + 40


def do_dxf(dxf: Path, out: Path, px=3000):
    """Plain line renderer (no matplotlib): modelspace flattened to polylines, drawn black on white."""
    import ezdxf
    from PIL import ImageDraw
    lines = dxf_lines(ezdxf.readfile(str(dxf)))
    x0, y0, s, W, H = dxf_frame(lines, px)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for l in lines:
        d.line([(20 + (x - x0) * s, H - 20 - (y - y0) * s) for x, y in l], fill="black", width=1)
    W, H = save_page(img, out, 1)
    return [{"page": 1, "w": W, "h": H, "dpi": None, "px_per_unit": s, "words": 0}]


def do_raster(f: Path, out: Path):
    img = Image.open(f)
    img.load()
    W, H = save_page(img, out, 1)
    return [{"page": 1, "w": W, "h": H, "dpi": None, "words": 0}]


def process(args):
    root, art, d = args
    out = art / d["doc_id"]
    files = {k: root / v for k, v in d["files"].items()}
    try:
        if "pdf" in files:
            src, pages = "pdf", do_pdf(files["pdf"], d["doc_id"], out)
        elif "svg" in files:
            src, pages = "svg", do_svg(files["svg"], out)
        elif "dxf" in files:
            src, pages = "dxf", do_dxf(files["dxf"], out)
        elif "png" in files or "jpg" in files:
            k = "png" if "png" in files else "jpg"
            src, pages = k, do_raster(files[k], out)
        elif "dwg" in files:
            return d["doc_id"], "skip: dwg (no converter)"
        else:
            return d["doc_id"], "skip: no page source (ifc: see D-07)"
        (out / "pages.json").write_text(json.dumps({"doc_id": d["doc_id"], "source": src, "pages": pages}, indent=1))
        return d["doc_id"], f"ok {src} {len(pages)}p"
    except Exception as e:  # noqa: BLE001
        return d["doc_id"], f"error: {e!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO / "data" / "junction-dataset-preview"))
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("-j", type=int, default=3)
    a = ap.parse_args()
    art = Path(a.artifacts)
    docs = [json.loads(l) for l in open(art / "registry.jsonl")]
    if a.only:
        docs = [d for d in docs if d["doc_id"] in a.only]
    jobs = [(Path(a.root), art, d) for d in docs]
    res = {}
    with Pool(a.j) as p:
        for did, st in p.imap_unordered(process, jobs):
            res[did] = st
            if not st.startswith("ok"):
                print(did, st, flush=True)
    from collections import Counter
    print(Counter(s.split()[0] + " " + (s.split()[1] if len(s.split()) > 1 else "") for s in res.values()))


if __name__ == "__main__":
    main()
