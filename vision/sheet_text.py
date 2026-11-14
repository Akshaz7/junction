"""V-11: tags, units and title block from a drawing sheet's PDF text layer (no model, no OCR, no PyMuPDF). For FIX-14 (Stoa sheets M-101A, S-100F, A-2).

  from vision.sheet_text import read_sheet
  r = read_sheet("artifacts/<doc>/text-1.json")      # or a PDF path (uses the same pdfium extractor and DPI mapping as pipeline/pages.py)
  r["sheet"]    -> {"id": "P1.02", "title": "SECOND FLOOR AND ROOF PLUMING PLANS", "id_box": [..], "title_box": [..], "confidence": 0.9}
  r["tags"]     -> {"equipment": {"FP-1": {"count": 2, "boxes": [[x0,y0,x1,y1], ...]}}, "sheet_ref": {...}, "pipe_size": {...},
                    "rebar": {...}, "feet_inch": {...}, "area": {...}, "scale": {...}, "metric_mm": {...}}
  r["items"]    -> plan-map items (kind "text", label = tag, props.tag_type, source "ocr" = the contract enum; props.extractor says pdf-text-layer), CONTRACT coordinates.
Coordinates: bbox_px [x0,y0,x1,y1] in the page-<n>.png pixel space of pipeline/pages.py (top-left origin), same as text-<n>.json.
"unique tags" = r["tags"][type] keys. A count of unique equipment prefixes: r["groups"]["FP"] = ["FP-1", ...]. A tag is only reported when printed in the text layer; a vector-outlined or raster sheet returns r["words"] == 0 and the caller must say so.
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

Q = r"[\"”″]"
PATTERNS = [  # (type, regex, applied to a line segment)
    ("scale", re.compile(rf"\b\d+(?:/\d+)?{Q}\s*=\s*\d+'\s*-?\s*\d*{Q}?|(?<![\d:])1\s*:\s*\d{{1,4}}\b(?!\s*:)|\bSCALE\s*[:=]?\s*[\d/\"' =-]+")),
    ("feet_inch", re.compile(rf"\b\d+'\s*-\s*\d+(?:\s*\d/\d+)?{Q}?")),
    ("pipe_size", re.compile(rf"(?<![\d/])\d{{1,2}}(?:\s*-\s*\d/\d|\s\d/\d|\.\d+)?\s*{Q}\s*[ØøΦ⌀]|(?<![\d/])\d{{1,2}}(?:\s*-\s*\d/\d|\s\d/\d)?\s*{Q}\s*(?:DIA|PIPE|PVC|HDPE|CS|SS|CU)\b|\bDN\s?\d{{2,4}}\b|\b\d{{1,2}}(?:-\d/\d)?{Q}\s*(?:VENT UP|VENT DN|VENT|VTR|V UP|V DN)\b", re.I)),
    ("rebar", re.compile(r"\b[DTRH]\s?\d{2}\s*@\s*\d{2,4}\b|#\d{1,2}\s*@\s*\d{1,3}(?:\"|'')?|\b\d+\s*[-]?\s*#\d{1,2}\b")),
    ("area", re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*(?:SF|S\.F\.|SQ\.?\s?FT)\b|\b\d+(?:\.\d+)?\s*(?:SF|S\.F\.|SQ\.?\s?FT|M2|m²|SQM)\b", re.I)),
    ("metric_mm", re.compile(r"\b\d{2,6}\s*mm\b|\b\d{1,3}(?:\.\d+)?\s*m\b(?!\w)", re.I)),
    ("equipment", re.compile(r"\b[A-Z]{1,5}-\d{1,3}[A-Z]?\b")),
]
SHEET_ID = re.compile(r"^[A-Z]{1,2}[-. ]?\d{1,3}(?:[.-]\d{1,2})?[A-Z]?$")
SHEETREF_CTX = re.compile(r"\b(?:SEE|SHEET|SHT|DWG|DETAIL|REF)\b", re.I)


def _load(src, page=1):
    src = Path(src)
    if src.suffix.lower() == ".json":
        j = json.loads(src.read_text())
        return j["words"], j["image"]["w"], j["image"]["h"], j.get("extractor", "pdf-text-layer")
    import pypdfium2 as pdfium
    from pipeline import pages as P
    doc = pdfium.PdfDocument(str(src)); pg = doc[page - 1]
    w_pt, h_pt = pg.get_size(); s = P.DPI / 72
    if max(w_pt, h_pt) * s > P.MAX_SIDE:
        s = P.MAX_SIDE / max(w_pt, h_pt)
    W, H = int(round(w_pt * s)), int(round(h_pt * s))
    words = P.pdfium_words(pg, s, W, H)
    return words, W, H, "pdfium"


def _segments(words):
    """Group tokens into text lines and split at big gaps: [(text, [token idx], char offsets)]. Horizontal reading only; rotated text stays one token."""
    toks = [(i, w["text"], w["bbox_px"]) for i, w in enumerate(words)]
    toks.sort(key=lambda t: ((t[2][1] + t[2][3]) / 2, t[2][0]))
    lines, cur, cy, ch = [], [], None, None
    for t in toks:
        b = t[2]; c = (b[1] + b[3]) / 2; h = max(1.0, b[3] - b[1])
        if cur and abs(c - cy) <= 0.3 * min(h, ch):
            cur.append(t); cy = (cy * (len(cur) - 1) + c) / len(cur); ch = max(ch, h)
        else:
            if cur:
                lines.append(cur)
            cur, cy, ch = [t], c, h
    if cur:
        lines.append(cur)
    segs = []
    for ln in lines:
        ln.sort(key=lambda t: t[2][0]); seg = [ln[0]]
        for t in ln[1:]:
            gap = t[2][0] - seg[-1][2][2]; h = max(1.0, t[2][3] - t[2][1])
            if gap > 2.2 * h:
                segs.append(seg); seg = [t]
            else:
                seg.append(t)
        segs.append(seg)
    out = []
    for seg in segs:
        text, spans = "", []
        for k, (i, tx, b) in enumerate(seg):
            if k:
                text += " "
            spans.append((len(text), len(text) + len(tx), b)); text += tx
        out.append((text, spans))
    return out


def _union(boxes):
    return [round(min(b[0] for b in boxes), 1), round(min(b[1] for b in boxes), 1), round(max(b[2] for b in boxes), 1), round(max(b[3] for b in boxes), 1)]


def _norm(t, v):
    v = re.sub(r"\s+", " ", v.strip())
    if t == "equipment":
        return v.upper()
    if t == "rebar":
        return re.sub(r"\s*@\s*", " @ ", v.upper())
    if t == "pipe_size":
        return v.replace("”", '"').replace("″", '"')
    return v


def title_block(words, W, H):
    """Sheet id = id-shaped token in the bottom-right corner or right strip with the largest glyph height; title = the largest-text line(s) beside it."""
    cand = []
    for w in words:
        b = w["bbox_px"]; t = w["text"].strip()
        if SHEET_ID.match(t) and ((b[0] > 0.55 * W and b[1] > 0.70 * H) or b[0] > 0.78 * W):
            cand.append((b[3] - b[1], w))
    if not cand:
        return {"id": None, "title": None, "id_box": None, "title_box": None, "confidence": 0.0}
    cand.sort(key=lambda x: -x[0]); hid, idw = cand[0]; ib = idw["bbox_px"]
    sid = idw["text"].strip()
    # title: words in the same bottom/right title zone, glyph height >= 0.45 x the id height, not the id itself
    zone = [w for w in words if w is not idw and w["bbox_px"][1] > ib[1] - 0.6 * hid and w["bbox_px"][3] <= ib[3] + 0.3 * hid and w["bbox_px"][2] <= ib[2] + 0.5 * hid and (w["bbox_px"][3] - w["bbox_px"][1]) >= 0.55 * hid and w["bbox_px"][0] > 0.2 * W]
    if len(zone) < 2:  # title above the id in a right-hand block
        zone = [w for w in words if w is not idw and abs(w["bbox_px"][0] - ib[0]) < 0.12 * W and ib[1] - 0.25 * H < w["bbox_px"][1] < ib[1] and (w["bbox_px"][3] - w["bbox_px"][1]) >= 0.5 * hid]
    lines = _segments(zone); lines.sort(key=lambda s: s[1][0][2][0])
    ln = [(sp[0][2][1], t) for t, sp in lines]; ln.sort()
    title = " ".join(t for _, t in ln).split("|")[0].strip() or None  # drop a trailing "| project address"
    tb = _union([sp[2] for _, spans in lines for sp in spans]) if lines else None
    conf = 0.9 if title and sid else 0.5 if sid else 0.0
    return {"id": sid, "title": title, "id_box": [round(v, 1) for v in ib], "title_box": tb, "confidence": conf}


def read_sheet(src, page=1):
    words, W, H, extractor = _load(src, page)
    sheet = title_block(words, W, H)
    tags = defaultdict(lambda: defaultdict(lambda: {"count": 0, "boxes": [], "lines": []}))
    for text, spans in _segments(words):
        taken = []
        for t, rx in PATTERNS:
            for m in rx.finditer(text):
                if any(m.start() < e and m.end() > s for s, e in taken):
                    continue  # a longer pattern (pipe size, rebar, scale) already owns these characters
                ts = [b for (s, e, b) in spans if s < m.end() and e > m.start()]
                if not ts:
                    continue
                v = _norm(t, m.group(0))
                kind = t
                if t == "equipment":
                    if re.match(r"^[A-Z]-\d{3}[A-Z]?$", v) or SHEETREF_CTX.search(text[max(0, m.start() - 14):m.start()]) or _union(ts) == sheet.get("id_box"):
                        kind = "sheet_ref"
                    elif re.match(r"^(?:NO|SF|PSI|GPM|CFM|TYP|MIN|MAX|DIA|REV)-\d", v):
                        continue
                    elif re.match(r"^\d", v):
                        continue
                taken.append((m.start(), m.end()))
                e = tags[kind][v]; e["count"] += 1; e["boxes"].append(_union(ts)); e["lines"].append(text[:80])
    out = {k: {v: {"count": d["count"], "boxes": d["boxes"]} for v, d in sorted(vs.items())} for k, vs in tags.items()}
    groups = defaultdict(list)
    for v in out.get("equipment", {}):
        groups[v.split("-")[0]].append(v)
    items, n = [], 0
    for k, vs in out.items():
        for v, d in vs.items():
            for b in d["boxes"]:
                n += 1
                items.append({"item_id": f"text-tag-{n:04d}", "kind": "text", "label": v, "bbox_px": [int(round(x)) for x in b], "polygon_px": None,
                              "props": {"tag_type": k, "extractor": extractor, "from": "pdf-text-layer"}, "conf": 1.0, "source": "ocr"})
    return {"image": {"w": W, "h": H}, "words": len(words), "sheet": sheet, "tags": out, "groups": dict(groups), "items": items}


if __name__ == "__main__":
    r = read_sheet(sys.argv[1]); r.pop("items")
    print(json.dumps({"sheet": r["sheet"], "words": r["words"], "groups": r["groups"], "tags": {k: {v: d["count"] for v, d in vs.items()} for k, vs in r["tags"].items()}}, indent=1, ensure_ascii=False)[:5000])


# ---------------------------------------------------------------- engine-facing API (ENGINE-CHAT / engine/sheetqa.py)
OCR_PROMPT = """This image is part of a construction drawing sheet. List every printed equipment or fixture tag (letters, hyphen, number, e.g. FP-1, CV-3, FSI-5, PS-24, WC-1, LAV-1), every sheet reference (e.g. M-303) and every sheet id, exactly as printed, each with a bounding box [ymin,xmin,ymax,xmax] on a 0-1000 grid of this image. Do not invent tags that are not printed. Return JSON only: {"tags":[{"text":"FP-1","box":[0,0,0,0]}]}"""
OCR_SCHEMA = {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "box": {"type": "array", "items": {"type": "integer"}}}}}}}


def _norm_id(t):
    t = t.strip().upper()
    m = re.match(r"^([A-Z]{1,2})[-. ]?(\d{1,3})((?:[.-]\d{1,2})?[A-Z]?)$", t)
    return f"{m.group(1)}-{m.group(2)}{m.group(3)}" if m else t


def _pages(doc_dir):
    d = Path(doc_dir)
    nums = sorted({int(re.search(r"(\d+)", p.stem).group(1)) for p in list(d.glob("text-*.json")) + list(d.glob("page-*.png")) if re.search(r"(\d+)", p.stem) and "thumb" not in p.name})
    return nums


def sheet_ids(doc_dir):
    """Title-block sheet ids of every page that has a text layer, hyphen-normalised ('P1.02' -> 'P-1.02', 'M-101A' stays). Empty for raster-only docs."""
    out = set()
    for n in _pages(doc_dir):
        f = Path(doc_dir) / f"text-{n}.json"
        if f.exists():
            try:
                sid = read_sheet(f)["sheet"]["id"]
            except Exception:  # noqa: BLE001
                sid = None
            if sid:
                out.add(_norm_id(sid)); out.add(sid.strip().upper())
    return out


def tags(doc_dir, page=1, ocr=True):
    """One entry per printed mark: [{"tag","page","bbox_px":[x0,y0,x1,y1],"source","tag_type"}]. Same px space as text-<page>.json.
    source "pdf-text-layer" when the page has text; else, if ocr=True and page-<page>.png exists, a vision model reads the tags ("vlm-ocr", about $0.05 per page, via engine.models.call())."""
    d = Path(doc_dir); f = d / f"text-{page}.json"
    if f.exists():
        r = read_sheet(f)
        return [{"tag": i["label"], "page": page, "bbox_px": i["bbox_px"], "source": "pdf-text-layer", "tag_type": i["props"]["tag_type"]}
                for i in r["items"] if i["props"]["tag_type"] in ("equipment", "sheet_ref")]
    png = d / f"page-{page}.png"
    if not (ocr and png.exists()):
        return []
    import tempfile
    from PIL import Image
    from engine.models import call
    im = Image.open(png).convert("RGB"); W, H = im.size
    nx, ny = (3, 2) if W > 3000 else (1, 1)
    out, seen = [], []
    for j in range(ny):
        for i in range(nx):
            box = (int(max(0, (i - 0.12) * W / nx)), int(max(0, (j - 0.12) * H / ny)), int(min(W, (i + 1.12) * W / nx)), int(min(H, (j + 1.12) * H / ny)))
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "t.png"; im.crop(box).save(p)
                try:
                    r = call("read_drawing", [{"role": "user", "content": OCR_PROMPT}], images=[p], schema=OCR_SCHEMA, only=("runware_oai", "gemini-4-carbon"))
                except Exception:  # noqa: BLE001  no key, budget, network: no tags
                    continue
            tw, th = box[2] - box[0], box[3] - box[1]
            for it in (r.json or {}).get("tags", []) if isinstance(r.json, dict) else []:
                t = re.sub(r"\s+", "", str(it.get("text", ""))).upper(); bb = it.get("box") or []
                if len(bb) != 4 or not re.match(r"^[A-Z]{1,5}-\d{1,3}[A-Z]?$", t):
                    continue
                y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) for v in bb]
                b = [int(box[0] + x0 * tw / 1000), int(box[1] + y0 * th / 1000), int(box[0] + x1 * tw / 1000), int(box[1] + y1 * th / 1000)]
                if any(t == s and abs(b[0] - o[0]) < 40 and abs(b[1] - o[1]) < 40 for s, o in seen):
                    continue  # same mark seen in two overlapping tiles
                seen.append((t, b))
                out.append({"tag": t, "page": page, "bbox_px": b, "source": "vlm-ocr", "tag_type": "sheet_ref" if re.match(r"^[A-Z]-\d{3}[A-Z]?$", t) else "equipment"})
    return out
