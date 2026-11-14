"""Reader tool: page text with pixel boxes (CONTRACT 5.3 text-<n>.json format) and fuzzy find_text.

Sources, best first: text-<n>.json from the pipeline (kept only if it passes a geometry check), the reader's own cache
rtext-<n>.json, a fresh read of the source PDF (pdfium, correct for rotated pages), OCR of the page image (rapidocr).
Everything is in pixels of page-<n>.png, origin top-left. No model calls.
"""
from __future__ import annotations

import ctypes
import json
import math
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATASET_ROOTS = [REPO / "data" / "full" / "junction-dataset", REPO / "data" / "junction-dataset-preview"]
OCR_TILE, OCR_OVERLAP, OCR_MAX_TILES = 2000, 150, 16
_cache: dict[tuple, "PageText"] = {}
_ocr_engine = None


def png_size(p: Path) -> tuple[int, int] | None:
    try:
        with p.open("rb") as image:
            b = image.read(32)
        if len(b) >= 24 and b[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", b[16:24])
    except (OSError, struct.error):
        pass
    return None


def image_path(doc_id: str, page: int, root) -> Path:
    return Path(root) / doc_id / f"page-{page}.png"


@dataclass
class PageText:
    doc_id: str
    page: int
    w: int
    h: int
    words: list[dict]                       # {text, bbox_px}
    source: str = "none"
    segs: list[dict] = field(default_factory=list)   # {id, text, bbox_px, words:[idx]}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def tokens(s: str) -> list[str]:
    return [t.strip(".") for t in re.findall(r"[^\W_]+(?:[.\-/'][^\W_]+)*", norm(s), re.U) if t.strip(".")]


# ---------------------------------------------------------------------------------------------- sources
def _geometry_ok(t: dict, size: tuple[int, int] | None) -> bool:
    ws = [w["bbox_px"] for w in t.get("words") or [] if len(str(w.get("text") or "")) >= 4 and w.get("bbox_px")]
    if not ws:
        return bool(t.get("words"))
    tall = sum(1 for b in ws if (b[3] - b[1]) > 1.5 * (b[2] - b[0]))
    if tall > 0.5 * len(ws):
        return False                                    # known pipeline bug on /Rotate 90 pages: boxes transposed + clipped
    img = t.get("image") or {}
    if size and img.get("w") and abs(img["w"] - size[0]) > 2 and abs(img["h"] - size[1]) > 2:
        return False
    return True


def source_pdf(doc_id: str, root) -> Path | None:
    d = Path(root) / doc_id
    try:
        meta = json.loads((d / "doc.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    rel = (meta.get("files") or {}).get("pdf")
    cands: list[Path] = []
    if rel:
        cands += [r / rel for r in DATASET_ROOTS] + [Path(root) / rel, Path(root) / "uploads" / Path(rel).name, Path(rel)]
    cands += sorted(d.glob("*.pdf"))
    up = Path(root) / "uploads"
    if up.is_dir():
        cands += sorted(up.glob(f"{doc_id.split('__', 1)[-1]}*.pdf"))
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def pdf_words(pdf: Path, page: int, w: int, h: int) -> list[dict]:
    """Words of one PDF page in pixels of a w x h render (pdfium maps page space to device space incl. /Rotate)."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    doc = pdfium.PdfDocument(str(pdf))
    try:
        pg = doc[page - 1]
        tp = pg.get_textpage()
        n = tp.count_chars()
        txt = tp.get_text_range(0, n) if n else ""
        dx, dy = ctypes.c_int(), ctypes.c_int()

        def dev(x, y):
            raw.FPDF_PageToDevice(pg.raw, 0, 0, w, h, 0, x, y, dx, dy)
            return dx.value, dy.value
        out, cur = [], []

        def flush():
            if not cur:
                return
            xs, ys, s = [], [], []
            for i in cur:
                l, b, r, t = tp.get_charbox(i)
                for p in ((l, b), (r, t)):
                    x, y = dev(*p)
                    xs.append(x), ys.append(y)
                s.append(txt[i])
            word = "".join(s).strip()
            if word:
                out.append({"text": word, "bbox_px": [float(max(0, min(xs))), float(max(0, min(ys))), float(min(w, max(xs))), float(min(h, max(ys)))]})
            cur.clear()
        for i in range(min(n, len(txt))):
            if txt[i].isspace() or txt[i] == "\x00":
                flush()
            else:
                cur.append(i)
        flush()
        return out
    finally:
        doc.close()


def _ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_words(img_path: Path) -> list[dict]:
    """OCR in 2000 px tiles; each detected line is split into words proportionally to its width."""
    import cv2
    im = cv2.imread(str(img_path))
    if im is None:
        return []
    H, W = im.shape[:2]
    eng = _ocr()
    step = OCR_TILE - OCR_OVERLAP
    tiles = [(x, y) for y in range(0, max(1, H - OCR_OVERLAP), step) for x in range(0, max(1, W - OCR_OVERLAP), step)][:OCR_MAX_TILES]
    out: list[dict] = []
    for x0, y0 in tiles:
        crop = im[y0:y0 + OCR_TILE, x0:x0 + OCR_TILE]
        res, _ = eng(crop)
        for box, text, conf in res or []:
            if float(conf) < 0.45 or not str(text).strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            bx0, by0, bx1, by1 = min(xs) + x0, min(ys) + y0, max(xs) + x0, max(ys) + y0
            parts = str(text).split()
            total = sum(len(p) for p in parts) + max(0, len(parts) - 1)
            cx = bx0
            for p in parts:
                wlen = (bx1 - bx0) * len(p) / max(total, 1)
                out.append({"text": p, "bbox_px": [round(cx, 1), round(by0, 1), round(cx + wlen, 1), round(by1, 1)]})
                cx += wlen + (bx1 - bx0) / max(total, 1)
    # drop duplicates from tile overlaps
    seen, dedup = set(), []
    for w in out:
        b = w["bbox_px"]
        k = (w["text"], round(b[0] / 12), round(b[1] / 12))
        if k in seen:
            continue
        seen.add(k)
        dedup.append(w)
    return dedup


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_page_text(doc_id: str, page: int, root, allow_ocr: bool = True) -> PageText:
    root = Path(root)
    d = root / doc_id
    img = image_path(doc_id, page, root)
    size = png_size(img)
    # The lightweight CAD preview omits text/hatches. OCR cannot recover omitted
    # text, and starting an OCR model for every vector count can exhaust the API.
    # Existing vector/PDF text layers still take precedence below.
    preview = _read_json(d / "pages.json")
    if isinstance(preview, dict) and preview.get("source") in {"dxf", "ifc-storeys", "ifc-overview"}:
        allow_ocr = False
    stamps = tuple((p.stat().st_mtime_ns if p.exists() else 0) for p in (d / f"text-{page}.json", d / f"rtext-{page}.json"))
    key = (str(root), doc_id, page, stamps, allow_ocr)
    if key in _cache:
        return _cache[key]
    pt = None
    t = _read_json(d / f"text-{page}.json")
    if t and t.get("words") and _geometry_ok(t, size):
        sz = (t.get("image") or {})
        sx = size[0] / sz["w"] if size and sz.get("w") else 1.0
        sy = size[1] / sz["h"] if size and sz.get("h") else 1.0
        words = t["words"] if abs(sx - 1) < 0.01 and abs(sy - 1) < 0.01 else \
            [{"text": w["text"], "bbox_px": [w["bbox_px"][0] * sx, w["bbox_px"][1] * sy, w["bbox_px"][2] * sx, w["bbox_px"][3] * sy]} for w in t["words"]]
        pt = PageText(doc_id, page, *(size or (sz.get("w", 0), sz.get("h", 0))), words, t.get("source") or "text-layer")
    if pt is None:
        r = _read_json(d / f"rtext-{page}.json")
        if r and r.get("words") is not None and (not size or (r.get("image") or {}).get("w") == size[0]):
            pt = PageText(doc_id, page, r["image"]["w"], r["image"]["h"], r["words"], r.get("source", "cache"))
    if pt is None and size:
        words, src = [], ""
        pdf = source_pdf(doc_id, root)
        if pdf is not None:
            try:
                words, src = pdf_words(pdf, page, *size), "pdf-text-layer"
            except Exception:  # noqa: BLE001
                words = []
        if not words and allow_ocr:
            try:
                words, src = ocr_words(img), "ocr"
            except Exception:  # noqa: BLE001
                words = []
        pt = PageText(doc_id, page, size[0], size[1], words, src or "none")
        if words:
            try:
                (d / f"rtext-{page}.json").write_text(json.dumps({"doc_id": doc_id, "page": page, "image": {"w": size[0], "h": size[1]},
                                                                  "source": src, "words": words}, ensure_ascii=False))
            except OSError:
                pass
    if pt is None:
        pt = PageText(doc_id, page, *(size or (0, 0)), [], "none")
    pt.segs = build_segments(pt)
    _cache[key] = pt
    return pt


# ---------------------------------------------------------------------------------------------- segments
def build_segments(pt: PageText) -> list[dict]:
    """Phrases: words on one baseline with small gaps. Cells of a table stay separate phrases."""
    idx = [i for i, w in enumerate(pt.words) if str(w.get("text") or "").strip() and w.get("bbox_px")]
    idx.sort(key=lambda i: ((pt.words[i]["bbox_px"][1] + pt.words[i]["bbox_px"][3]) / 2, pt.words[i]["bbox_px"][0]))
    rows: list[list[int]] = []
    for i in idx:
        b = pt.words[i]["bbox_px"]
        cy, h = (b[1] + b[3]) / 2, max(b[3] - b[1], 1.0)
        if rows:
            last = rows[-1]
            lcy = sum((pt.words[j]["bbox_px"][1] + pt.words[j]["bbox_px"][3]) / 2 for j in last) / len(last)
            lh = max(pt.words[j]["bbox_px"][3] - pt.words[j]["bbox_px"][1] for j in last)
            if abs(cy - lcy) <= 0.45 * min(h, lh) + 1:
                last.append(i)
                continue
        rows.append([i])
    segs: list[dict] = []
    for r in rows:
        r.sort(key=lambda j: pt.words[j]["bbox_px"][0])
        cur = [r[0]]
        for j in r[1:]:
            pb, nb = pt.words[cur[-1]]["bbox_px"], pt.words[j]["bbox_px"]
            h = max(pb[3] - pb[1], nb[3] - nb[1], 1.0)
            if nb[0] - pb[2] > 0.9 * h:
                segs.append(_seg(pt, cur, len(segs)))
                cur = [j]
            else:
                cur.append(j)
        segs.append(_seg(pt, cur, len(segs)))
    return segs


def _seg(pt: PageText, ids: list[int], n: int) -> dict:
    bs = [pt.words[j]["bbox_px"] for j in ids]
    return {"id": f"t{pt.page}.{n}", "text": " ".join(str(pt.words[j]["text"]).strip() for j in ids), "words": ids,
            "bbox_px": [round(min(b[0] for b in bs), 1), round(min(b[1] for b in bs), 1), round(max(b[2] for b in bs), 1), round(max(b[3] for b in bs), 1)]}


# ---------------------------------------------------------------------------------------------- find_text
GENERIC = {"door", "doors", "room", "rooms", "sheet", "note", "notes", "level", "number", "no", "the", "of", "a", "an", "on", "in", "at", "for",
           "type", "schedule", "drawing", "plan", "page"}


def _tok_match(qt: str, st: str) -> float:
    if qt == st:
        return 1.0
    if len(qt) >= 3 and (qt in st or st in qt) and min(len(qt), len(st)) >= 0.7 * max(len(qt), len(st)):
        return 0.9
    if len(qt) >= 4:
        r = SequenceMatcher(None, qt, st).ratio()
        if r >= 0.85:
            return r * 0.9
    return 0.0


def find_text(pt: PageText, query: str, limit: int = 12) -> list[dict]:
    """Fuzzy matches of `query` on a page: [{text, bbox_px, score, seg_id}], best first. A single token returns the word box."""
    qt = tokens(query)
    core = [t for t in qt if t not in GENERIC]
    qt = core or qt
    if not qt:
        return []
    need = max(1, math.ceil(0.75 * len(qt))) if len(qt) > 2 else len(qt)
    hits = []
    for s in pt.segs:
        st = tokens(s["text"])
        if not st:
            continue
        scores = [max(_tok_match(q, t) for t in st) for q in qt]
        ok = sum(1 for x in scores if x > 0)
        if ok < need:
            continue
        sc = sum(scores) / len(qt)
        if len(qt) == 1:
            best, bw = 0.0, None
            for j in s["words"]:
                m = max((_tok_match(qt[0], t) for t in tokens(pt.words[j]["text"])), default=0.0)
                if m > best:
                    best, bw = m, j
            if bw is None:
                continue
            b = pt.words[bw]["bbox_px"]
            hits.append({"text": s["text"], "bbox_px": [round(v, 1) for v in b], "score": round(best, 3), "seg_id": s["id"], "match": pt.words[bw]["text"]})
        else:
            hits.append({"text": s["text"], "bbox_px": s["bbox_px"], "score": round(sc, 3), "seg_id": s["id"], "match": s["text"]})
    hits.sort(key=lambda h: (-h["score"], h["bbox_px"][1], h["bbox_px"][0]))
    return hits[:limit]


def lines_in(pt: PageText, bbox: list[float] | None = None, max_chars: int = 5000) -> list[dict]:
    """Segments (phrases) inside a bbox, in reading order, merged to lines of text."""
    segs = pt.segs
    if bbox:
        x0, y0, x1, y1 = bbox
        segs = [s for s in segs if (s["bbox_px"][0] + s["bbox_px"][2]) / 2 >= x0 and (s["bbox_px"][0] + s["bbox_px"][2]) / 2 <= x1
                and (s["bbox_px"][1] + s["bbox_px"][3]) / 2 >= y0 and (s["bbox_px"][1] + s["bbox_px"][3]) / 2 <= y1]
    out, n = [], 0
    for s in sorted(segs, key=lambda s: (round((s["bbox_px"][1] + s["bbox_px"][3]) / 40), s["bbox_px"][0])):
        n += len(s["text"]) + 1
        if n > max_chars:
            break
        out.append(s)
    return out
