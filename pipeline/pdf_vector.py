"""Vector PDF page reader for the PDF -> plan map path: drawing paths, text-layer words, walls.

Coordinate system (shared by pdf_rooms / pdf_openings / pdf_planmap): page points, top-left origin, y down, after
the page's /Rotate and CropBox. ``px = pt * s`` with ``s = W_px / W_pt`` lands on page-<n>.png as rendered by
pipeline/pages.py do_pdf (pypdfium2 ``page.render(scale=s)``); ``to_px`` does that.

load_page(pdf, i) -> {"W_pt","H_pt","rotate","paths":[...],"words":[...],"image_cover","reader","n_objects"}
  path: {"pts":[[x,y],...], "closed", "fill":[r,g,b]|None (0..1), "stroke":[r,g,b]|None, "width" (pt, page space),
         "n_curves", "is_arc", "obj" (draw-object id: subpaths of one PDF path share it), "dashed", "pattern"}
  One entry per subpath; curves are flattened (4 points per Bezier) so pts is a polyline.
  word: {"text","bbox":[x0,y0,x1,y1]}
walls(page) -> [{"polygon":[[x,y],...],"thickness_pt","style":"fill"|"double"|"stroke"}]

Readers: pypdfium2's raw path API (default; recurses into form XObjects), pdfminer.six as fallback.
No PyMuPDF (AGPL).
"""
from __future__ import annotations

import ctypes
import math
import re
from collections import defaultdict

import numpy as np

# ---------------------------------------------------------------- coordinates


def to_px(xy, s: float):
    """Page points (top-left, y down) -> render pixels of page-<n>.png (s = W_px / W_pt)."""
    return [xy[0] * s, xy[1] * s]


def to_pt(xy, s: float):
    return [xy[0] / s, xy[1] / s]


def render_scale(W_pt: float, H_pt: float, dpi: int = 150, max_side: int = 7000) -> float:
    """The scale pages.do_pdf renders with (kept in sync with pages.DPI / MAX_SIDE)."""
    try:
        from pipeline import pages
        dpi, max_side = pages.DPI, pages.MAX_SIDE
    except Exception:  # noqa: BLE001
        pass
    s = dpi / 72
    if max(W_pt, H_pt) * s > max_side:
        s = max_side / max(W_pt, H_pt)
    return s


def _displayer(rot: int, W0: float, H0: float, ox: float, oy: float):
    """Map unrotated PDF user space (origin bottom-left) -> displayed top-left y-down points. /Rotate is clockwise."""
    rot %= 360
    if rot == 90:
        return lambda x, y: (y - oy, x - ox)
    if rot == 180:
        return lambda x, y: (W0 - (x - ox), y - oy)
    if rot == 270:
        return lambda x, y: (H0 - (y - oy), W0 - (x - ox))
    return lambda x, y: (x - ox, H0 - (y - oy))


# ---------------------------------------------------------------- pypdfium2 reader

def _mat_mul(a, b):
    """Compose affine (a,b,c,d,e,f) matrices: apply a then b."""
    a1, b1, c1, d1, e1, f1 = a
    a2, b2, c2, d2, e2, f2 = b
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _bez(p0, p1, p2, p3, n=4):
    out = []
    for k in range(1, n + 1):
        t = k / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _load_pdfium(pdf_path, page_index):
    import pypdfium2 as pdfium
    import pypdfium2.raw as R

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        rot = page.get_rotation() % 360
        cl, cb, cr, ct = page.get_cropbox()
        W0, H0 = cr - cl, ct - cb
        disp = _displayer(rot, W0, H0, cl, cb)
        Wd, Hd = (H0, W0) if rot in (90, 270) else (W0, H0)

        paths, images = [], []
        fx, fy = ctypes.c_float(), ctypes.c_float()
        ri, gi, bi, ai = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        fm, sk = ctypes.c_int(), ctypes.c_int()
        wv = ctypes.c_float()
        M = R.FS_MATRIX()
        l_, b_, r_, t_ = ctypes.c_float(), ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        counter = [0, 0]

        def matrix(obj):
            if R.FPDFPageObj_GetMatrix(obj, ctypes.byref(M)):
                return (M.a, M.b, M.c, M.d, M.e, M.f)
            return (1, 0, 0, 1, 0, 0)

        def colour(getter, obj):
            if getter(obj, ctypes.byref(ri), ctypes.byref(gi), ctypes.byref(bi), ctypes.byref(ai)):
                if ai.value == 0:
                    return None, False
                return [ri.value / 255, gi.value / 255, bi.value / 255], False
            return None, True  # no plain colour: pattern / shading

        def do_path(obj, parent):
            m = _mat_mul(matrix(obj), parent)
            a, b, c, d, e, f = m
            n = R.FPDFPath_CountSegments(obj)
            if n <= 0:
                return
            R.FPDFPath_GetDrawMode(obj, ctypes.byref(fm), ctypes.byref(sk))
            fill_on, stroke_on = fm.value != 0, bool(sk.value)
            if not fill_on and not stroke_on:
                return  # clip-only path
            fill = stroke = None
            pattern = False
            if fill_on:
                fill, pattern = colour(R.FPDFPageObj_GetFillColor, obj)
                if pattern:
                    fill = [0.3, 0.3, 0.3]  # pattern (hatch) fill: treated as a mid-dark fill
            if stroke_on:
                stroke, _ = colour(R.FPDFPageObj_GetStrokeColor, obj)
            width = 0.0
            if stroke_on and R.FPDFPageObj_GetStrokeWidth(obj, ctypes.byref(wv)):
                width = wv.value * math.sqrt(abs(a * d - b * c))
            dashed = stroke_on and R.FPDFPageObj_GetDashCount(obj) > 0
            oid = counter[0]
            counter[0] += 1
            subs = []
            cur, closed, ncurv, bez = [], False, 0, []

            def flush():
                if len(cur) >= 2:
                    subs.append((cur, closed, ncurv))

            for k in range(n):
                seg = R.FPDFPath_GetPathSegment(obj, k)
                R.FPDFPathSegment_GetPoint(seg, ctypes.byref(fx), ctypes.byref(fy))
                x, y = fx.value, fy.value
                X, Y = disp(a * x + c * y + e, b * x + d * y + f)
                t = R.FPDFPathSegment_GetType(seg)
                if t == R.FPDF_SEGMENT_MOVETO:
                    flush()
                    cur, closed, ncurv, bez = [(X, Y)], False, 0, []
                elif t == R.FPDF_SEGMENT_BEZIERTO:
                    bez.append((X, Y))
                    if len(bez) == 3:
                        p0 = cur[-1] if cur else bez[0]
                        cur.extend(_bez(p0, bez[0], bez[1], bez[2]))
                        bez = []
                        ncurv += 1
                else:
                    cur.append((X, Y))
                if R.FPDFPathSegment_GetClose(seg):
                    closed = True
            flush()
            for pts, cl_, nc in subs:
                if fill_on:
                    cl_ = True
                if cl_ and len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                    pts = pts[:-1]
                paths.append({"pts": [[round(p[0], 3), round(p[1], 3)] for p in pts], "closed": bool(cl_),
                              "fill": fill, "stroke": stroke, "width": round(width, 4), "n_curves": nc,
                              "is_arc": nc > 0 and nc * 4 >= len(pts) - 1, "obj": oid, "dashed": bool(dashed),
                              "pattern": pattern})

        def do_image(obj, parent):
            # unit square [0,1]^2 through the image matrix
            m = _mat_mul(matrix(obj), parent)
            a, b, c, d, e, f = m
            q = [disp(a * x + c * y + e, b * x + d * y + f) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
            images.append(q)

        def walk(get_count, get_obj, parent, depth):
            for k in range(get_count()):
                obj = get_obj(k)
                t = R.FPDFPageObj_GetType(obj)
                counter[1] += 1
                if t == R.FPDF_PAGEOBJ_PATH:
                    do_path(obj, parent)
                elif t == R.FPDF_PAGEOBJ_IMAGE:
                    do_image(obj, parent)
                elif t == R.FPDF_PAGEOBJ_FORM and depth < 12:
                    m = _mat_mul(matrix(obj), parent)
                    walk(lambda o=obj: R.FPDFFormObj_CountObjects(o), lambda j, o=obj: R.FPDFFormObj_GetObject(o, j),
                         m, depth + 1)

        raw = page.raw
        walk(lambda: R.FPDFPage_CountObjects(raw), lambda j: R.FPDFPage_GetObject(raw, j), (1, 0, 0, 1, 0, 0), 0)
        words = _words_pdfium(page, disp)
        page.close()
    finally:
        doc.close()
    return {"W_pt": float(Wd), "H_pt": float(Hd), "rotate": rot, "paths": paths, "words": words,
            "image_cover": _cover(images, Wd, Hd), "reader": "pypdfium2", "n_objects": counter[1]}


def _words_pdfium(page, disp):
    tp = page.get_textpage()
    n = tp.count_chars()
    txt = tp.get_text_range(0, n) if n else ""
    words, cur = [], []

    def flush():
        if cur:
            xs = [v for _, b in cur for v in (b[0], b[2])]
            ys = [v for _, b in cur for v in (b[1], b[3])]
            words.append({"text": "".join(c for c, _ in cur),
                          "bbox": [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]})
            cur.clear()

    for i, ch in enumerate(txt[:n]):
        if ch.isspace() or ch in "￾\x00":
            flush()
            continue
        l, b, r, t = tp.get_charbox(i)
        X0, Y0 = disp(l, b)
        X1, Y1 = disp(r, t)
        cur.append((ch, (min(X0, X1), min(Y0, Y1), max(X0, X1), max(Y0, Y1))))
    flush()
    tp.close()
    return words


def _cover(quads, W, H, g=256):
    """Fraction of the page covered by image objects (union, on a g x g grid)."""
    if not quads or W <= 0 or H <= 0:
        return 0.0
    from PIL import Image, ImageDraw
    im = Image.new("L", (g, g), 0)
    dr = ImageDraw.Draw(im)
    for q in quads:
        dr.polygon([(x / W * g, y / H * g) for x, y in q], fill=255)
    return float((np.asarray(im) > 0).mean())


# ---------------------------------------------------------------- pdfminer fallback

def _mcol(c):
    if c is None:
        return None
    if isinstance(c, (int, float)):
        return [float(c)] * 3
    try:
        c = [float(v) for v in c]
    except Exception:  # noqa: BLE001  pattern name
        return [0.3, 0.3, 0.3]
    if len(c) == 1:
        return c * 3
    if len(c) == 3:
        return c
    if len(c) == 4:
        k = c[3]
        return [(1 - c[0]) * (1 - k), (1 - c[1]) * (1 - k), (1 - c[2]) * (1 - k)]
    return None


def _load_pdfminer(pdf_path, page_index):
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTCurve, LTFigure, LTImage, LTTextContainer, LTTextLine, LTChar

    pg = next(iter(extract_pages(str(pdf_path), page_numbers=[page_index], laparams=LAParams(char_margin=1.5))))
    x0b, y0b, x1b, y1b = pg.bbox
    W, H = x1b - x0b, y1b - y0b
    T = lambda x, y: (x - x0b, H - (y - y0b))  # noqa: E731  pdfminer already applies /Rotate
    paths, images, words = [], [], []
    oid = [0]

    def walk(o):
        for e in o:
            if isinstance(e, LTCurve):
                pts = [list(map(lambda v: round(v, 3), T(*p))) for p in e.pts]
                if len(pts) < 2:
                    continue
                closed = bool(e.fill) or (len(pts) > 2 and pts[0] == pts[-1])
                if closed and len(pts) > 2 and pts[0] == pts[-1]:
                    pts = pts[:-1]
                paths.append({"pts": pts, "closed": closed, "fill": _mcol(e.non_stroking_color) if e.fill else None,
                              "stroke": _mcol(e.stroking_color) if e.stroke else None, "width": float(e.linewidth or 0),
                              "n_curves": 0, "is_arc": False, "obj": oid[0], "dashed": bool(getattr(e, "dashing_style", None)),
                              "pattern": False})
                oid[0] += 1
            elif isinstance(e, LTImage):
                bx = e.bbox
                images.append([T(bx[0], bx[1]), T(bx[2], bx[1]), T(bx[2], bx[3]), T(bx[0], bx[3])])
            elif isinstance(e, LTFigure):
                walk(e)
            elif isinstance(e, LTTextContainer):
                for line in (e if not isinstance(e, LTTextLine) else [e]):
                    if not isinstance(line, LTTextLine):
                        continue
                    cur = []
                    for ch in list(line) + [None]:
                        if ch is None or not isinstance(ch, LTChar) or ch.get_text().isspace():
                            if cur:
                                xa, ya = T(min(c.x0 for c in cur), max(c.y1 for c in cur))
                                xb, yb = T(max(c.x1 for c in cur), min(c.y0 for c in cur))
                                words.append({"text": "".join(c.get_text() for c in cur),
                                              "bbox": [round(xa, 2), round(ya, 2), round(xb, 2), round(yb, 2)]})
                            cur = []
                        else:
                            cur.append(ch)
    walk(pg)
    return {"W_pt": float(W), "H_pt": float(H), "rotate": int(getattr(pg, "rotate", 0)) % 360, "paths": paths,
            "words": words, "image_cover": _cover(images, W, H), "reader": "pdfminer", "n_objects": len(paths)}


def load_page(pdf_path, page_index: int = 0, reader: str = "auto") -> dict:
    if reader in ("auto", "pdfium"):
        try:
            return _load_pdfium(pdf_path, page_index)
        except Exception:  # noqa: BLE001
            if reader == "pdfium":
                raise
    return _load_pdfminer(pdf_path, page_index)


def is_scanned(page: dict) -> bool:
    """A page that is mostly a raster image with little vector drawing."""
    n_seg = sum(len(p["pts"]) for p in page.get("paths", []))
    return page.get("image_cover", 0) > 0.5 and n_seg < 2000 or (n_seg < 50 and page.get("image_cover", 0) > 0.2)


# ---------------------------------------------------------------- walls

DIGIT = re.compile(r"\d")
# dimension strings: 3'-4 1/2", 1200, 3.45, 12'6", 4 13/16 ... (not tags like W4B or room numbers with letters)
DIMW = re.compile(r"^[\d\s'\"\u2019\u201d\-/.,:\u00bd\u00bc\u00be\u215b+=]+$")


def _grey(c):
    return None if c is None else 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _frame_and_titleblock(page):
    """Drawing area box (x0,y0,x1,y1) inside the border frame and outside the title block."""
    W, H = page["W_pt"], page["H_pt"]
    vx, hy = [], []  # long vertical lines (x, len), long horizontal lines (y, len)
    for p in page["paths"]:
        pts = p["pts"]
        segs = list(zip(pts, pts[1:] + (pts[:1] if p["closed"] else [])))
        for (x0, y0), (x1, y1) in segs:
            if abs(x0 - x1) < 0.5 and abs(y1 - y0) > 0.4 * H:
                vx.append(((x0 + x1) / 2, abs(y1 - y0)))
            elif abs(y0 - y1) < 0.5 and abs(x1 - x0) > 0.4 * W:
                hy.append(((y0 + y1) / 2, abs(x1 - x0)))
    x0, y0, x1, y1 = 0.0, 0.0, W, H
    m = 0.08
    left = [x for x, L in vx if x < m * W and L > 0.7 * H]
    right = [x for x, L in vx if x > (1 - m) * W and L > 0.7 * H]
    top = [y for y, L in hy if y < m * H and L > 0.7 * W]
    bot = [y for y, L in hy if y > (1 - m) * H and L > 0.7 * W]
    if left:
        x0 = max(left)
    if right:
        x1 = min(right)
    if top:
        y0 = max(top)
    if bot:
        y1 = min(bot)
    # title block: a long divider near the right/bottom edge with a text-dense strip beyond it
    words = page["words"]
    nw = max(1, len(words))
    cx = np.array([(w["bbox"][0] + w["bbox"][2]) / 2 for w in words]) if words else np.zeros(0)
    cy = np.array([(w["bbox"][1] + w["bbox"][3]) / 2 for w in words]) if words else np.zeros(0)
    fw, fh = x1 - x0, y1 - y0
    best = None
    for x, L in vx:
        if x0 + 0.6 * fw < x < x1 - 0.02 * fw and L > 0.6 * fh:
            strip = (x1 - x) / fw
            frac = float(((cx > x) & (cx < x1)).sum()) / nw
            if frac > max(0.15, 2.0 * strip) and (best is None or x < best):
                best = x
    if best is not None:
        x1 = best
    best = None
    for y, L in hy:
        if y0 + 0.7 * fh < y < y1 - 0.02 * fh and L > 0.6 * fw:
            strip = (y1 - y) / fh
            frac = float(((cy > y) & (cy < y1) & (cx < x1)).sum()) / nw
            if frac > max(0.15, 2.0 * strip) and (best is None or y < best):
                best = y
    if best is not None:
        y1 = best
    return (x0, y0, x1, y1)


def _raw_segments(page, box, max_grey=0.8):
    """All straight stroked pieces inside box: rows (x0,y0,x1,y1,width,grey)."""
    bx0, by0, bx1, by1 = box
    rows = []
    ap = rows.append
    for p in page["paths"]:
        if p["stroke"] is None or p["dashed"] or p["is_arc"]:
            continue
        g = _grey(p["stroke"])
        if g is not None and g > max_grey:
            continue
        g = g or 0.0
        w = p["width"]
        pts = p["pts"]
        if p["closed"]:
            pts = pts + pts[:1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            ap((x0, y0, x1, y1, w, g))
    if not rows:
        return np.zeros((0, 6))
    r = np.array(rows, dtype=float)
    k = ((r[:, [0, 2]] >= bx0) & (r[:, [0, 2]] <= bx1)).all(1) & ((r[:, [1, 3]] >= by0) & (r[:, [1, 3]] <= by1)).all(1)
    k &= np.hypot(r[:, 2] - r[:, 0], r[:, 3] - r[:, 1]) > 0.02
    return r[k]


def _merge_collinear(R, ang_q=math.radians(0.5), off_q=0.25, gap=0.6):
    """Join collinear touching pieces (CAD exporters often break one line into hundreds of tiny strokes).
    Returns rows (x0,y0,x1,y1,width,grey,len,angle)."""
    if not len(R):
        return np.zeros((0, 8))
    dx, dy = R[:, 2] - R[:, 0], R[:, 3] - R[:, 1]
    ang = np.arctan2(dy, dx) % math.pi
    ang[ang > math.pi - ang_q / 2] -= math.pi
    ux, uy = np.cos(ang), np.sin(ang)
    off = -uy * R[:, 0] + ux * R[:, 1]
    t0 = ux * R[:, 0] + uy * R[:, 1]
    t1 = ux * R[:, 2] + uy * R[:, 3]
    lo, hi = np.minimum(t0, t1), np.maximum(t0, t1)
    ka = np.round(ang / ang_q).astype(np.int64)
    ko = np.round(off / off_q).astype(np.int64)
    order = np.lexsort((lo, ko, ka))
    out = []
    cur = None
    kal, kol, lol, hil = ka.tolist(), ko.tolist(), lo.tolist(), hi.tolist()
    wl, gl, offl, angl = R[:, 4].tolist(), R[:, 5].tolist(), off.tolist(), ang.tolist()
    for i in order.tolist():
        key = (kal[i], kol[i])
        if cur is not None and key == cur[0] and lol[i] <= cur[2] + gap:
            if hil[i] > cur[2]:
                cur[2] = hil[i]
            if wl[i] > cur[3]:
                cur[3] = wl[i]
            if gl[i] < cur[4]:
                cur[4] = gl[i]
            cur[5] += offl[i]; cur[8] += 1
            continue
        if cur is not None:
            out.append(cur)
        cur = [key, lol[i], hil[i], wl[i], gl[i], offl[i], angl[i], None, 1]
    out.append(cur)
    rows = []
    for key, l, h, w, g, osum, a_, _, cnt in out:
        ux_, uy_ = math.cos(a_), math.sin(a_)
        # offset: mean of members (keeps sub-quantum precision)
        o_ = osum / cnt
        x0, y0 = l * ux_ - o_ * uy_, l * uy_ + o_ * ux_
        x1, y1 = h * ux_ - o_ * uy_, h * uy_ + o_ * ux_
        rows.append((x0, y0, x1, y1, w, g, h - l, a_ % math.pi))
    return np.array(rows, dtype=float).reshape(-1, 8)


def _segments(page, box):
    """Merged straight stroked segments inside box: rows (x0,y0,x1,y1,width,grey,len,angle)."""
    return _merge_collinear(_raw_segments(page, box))


def _pairs(S, dmin, dmax, ang_tol=math.radians(2.0), min_ov=0.5):
    """Parallel segment pairs dmin..dmax apart that overlap in projection. For each segment and side, partners
    are taken nearest first, and a farther one only where nearer ones leave its stretch uncovered, so a tiny
    piece next to a long wall line does not hide the long partner. A pair must be accepted from both ends.
    Returns (pairs [(i, j, d, signed_d, t0, t1)] with t on i's axis from its start, neighbour count per seg)."""
    from shapely import STRtree, box as sbox
    n = len(S)
    if n == 0:
        return [], np.zeros(0, int)
    xmin = np.minimum(S[:, 0], S[:, 2]); xmax = np.maximum(S[:, 0], S[:, 2])
    ymin = np.minimum(S[:, 1], S[:, 3]); ymax = np.maximum(S[:, 1], S[:, 3])
    tree = STRtree(sbox(xmin, ymin, xmax, ymax))
    qi, qj = tree.query(sbox(xmin - dmax, ymin - dmax, xmax + dmax, ymax + dmax))
    keep = qi != qj
    qi, qj = qi[keep], qj[keep]
    da = np.abs(S[qi, 7] - S[qj, 7])
    da = np.minimum(da, math.pi - da)
    keep = da < ang_tol
    qi, qj = qi[keep], qj[keep]
    ux = (S[qi, 2] - S[qi, 0]) / S[qi, 6]
    uy = (S[qi, 3] - S[qi, 1]) / S[qi, 6]
    d0 = (S[qj, 0] - S[qi, 0]) * -uy + (S[qj, 1] - S[qi, 1]) * ux
    d1 = (S[qj, 2] - S[qi, 0]) * -uy + (S[qj, 3] - S[qi, 1]) * ux
    d = (d0 + d1) / 2
    ad = np.abs(d)
    keep = (ad >= dmin) & (ad <= dmax) & (np.abs(d0 - d1) < 0.15 * ad + 0.3)
    qi, qj, d, ux, uy = qi[keep], qj[keep], d[keep], ux[keep], uy[keep]
    ti1 = S[qi, 6]
    tj0 = (S[qj, 0] - S[qi, 0]) * ux + (S[qj, 1] - S[qi, 1]) * uy
    tj1 = (S[qj, 2] - S[qi, 0]) * ux + (S[qj, 3] - S[qi, 1]) * uy
    lo = np.maximum(0, np.minimum(tj0, tj1))
    hi = np.minimum(ti1, np.maximum(tj0, tj1))
    ov = hi - lo
    shorter = np.minimum(S[qi, 6], S[qj, 6])
    keep = (ov > min_ov * shorter) & (ov > 2.0)
    qi, qj, d, lo, hi = qi[keep], qj[keep], d[keep], lo[keep], hi[keep]
    order = np.lexsort((np.abs(d), d > 0, qi))
    acc = set()
    nb = np.zeros(n, int)
    cur_key, covered = None, []
    for k in order.tolist():
        i, j, dd, l, h = int(qi[k]), int(qj[k]), float(d[k]), float(lo[k]), float(hi[k])
        key = (i, dd > 0)
        if key != cur_key:
            cur_key, covered = key, []
        # uncovered length of [l, h]
        free = h - l
        for cl, ch in covered:
            free -= max(0.0, min(h, ch) - max(l, cl))
        if free > 0.35 * (h - l):
            acc.add((i, j))
            nb[i] += 1
            covered.append((l, h))
    out = []
    for k in range(len(qi)):
        i, j = int(qi[k]), int(qj[k])
        if i < j and ((i, j) in acc or (j, i) in acc):
            out.append((i, j, abs(float(d[k])), float(d[k]), float(lo[k]), float(hi[k])))
    return out, nb


def _series(S, pairs):
    """Segments in a run of >= 5 equally spaced parallel lines (stairs, hatching, tiles)."""
    nxt = defaultdict(list)
    for a, b, d, sd, l, h in pairs:
        nxt[a].append((b, d))
        nxt[b].append((a, d))
    bad = set()
    for a, lst in nxt.items():
        if len(lst) == 2 and abs(lst[0][1] - lst[1][1]) < 0.2 * max(lst[0][1], lst[1][1]):
            # walk outwards both ways
            run = {a}
            for start, dd in lst:
                prev, cur_ = a, start
                while cur_ not in run:
                    run.add(cur_)
                    nb = [(o, x) for o, x in nxt[cur_] if o != prev and abs(x - dd) < 0.2 * dd]
                    if len(nb) != 1:
                        break
                    prev, cur_ = cur_, nb[0][0]
            if len(run) >= 5:
                bad |= run
    return bad


def _detail_points(page, box, S_all=None):
    """Midpoints of short drawn pieces after collinear merging (hatch strokes, stipple, squiggles) plus tiny
    filled dots: evidence of wall poche."""
    if S_all is None:
        S_all = _merge_collinear(_raw_segments(page, box, max_grey=0.95))
    out = []
    sh = S_all[S_all[:, 6] < 12.0]
    if len(sh):
        out.append(np.column_stack([(sh[:, 0] + sh[:, 2]) / 2, (sh[:, 1] + sh[:, 3]) / 2]))
    bx0, by0, bx1, by1 = box
    for p in page["paths"]:
        if p["fill"] is not None and p["stroke"] is None and len(p["pts"]) >= 3:
            a = np.asarray(p["pts"], float)
            x0, y0 = a.min(0); x1, y1 = a.max(0)
            if max(x1 - x0, y1 - y0) < 3 and bx0 <= x0 <= bx1 and by0 <= y0 <= by1:
                out.append(np.array([[(x0 + x1) / 2, (y0 + y1) / 2]]))
    return np.vstack(out) if out else np.zeros((0, 2))


def _grid_lines(page, S):
    """Mask of segments that are column-grid / section-cut lines: their axis runs into a grid bubble (a small
    circle with a short label inside) beyond one of their ends."""
    mask = np.zeros(len(S), bool)
    circles = []
    for p in page["paths"]:
        if p["n_curves"] >= 4 and p["closed"] or (p["n_curves"] >= 4 and len(p["pts"]) >= 16):
            a = np.asarray(p["pts"], float)
            x0, y0 = a.min(0); x1, y1 = a.max(0)
            dx, dy = x1 - x0, y1 - y0
            if 6 <= dx <= 50 and abs(dx - dy) < 0.15 * dx:
                circles.append(((x0 + x1) / 2, (y0 + y1) / 2, dx / 2))
    if not circles or not len(S):
        return mask
    words = page["words"]
    wc = np.array([((w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2) for w in words]) \
        if words else np.zeros((0, 2))
    C = []
    for cx, cy, r in circles:
        if len(wc) and (np.hypot(wc[:, 0] - cx, wc[:, 1] - cy) < 0.8 * r).any():
            C.append((cx, cy, r))
    if not C:
        return mask
    C = np.array(C)
    L = S[:, 6]
    long_ = np.where(L > 40)[0]
    if not len(long_):
        return mask
    ux = (S[long_, 2] - S[long_, 0]) / L[long_]
    uy = (S[long_, 3] - S[long_, 1]) / L[long_]
    for k in range(len(C)):
        cx, cy, r = C[k]
        vx, vy = cx - S[long_, 0], cy - S[long_, 1]
        perp = np.abs(vx * -uy + vy * ux)
        t = vx * ux + vy * uy
        # bubble centred on the axis, just past an end (or straddling it)
        hit = (perp < 0.3 * r) & (((t > L[long_] - r) & (t < L[long_] + 4 * r)) | ((t < r) & (t > -4 * r)))
        mask[long_[hit]] = True
    return mask


def _thickness(poly):
    """Short side of the rectangle with this polygon's area and perimeter (works for bars and for rings)."""
    A, P = poly.area, poly.length
    if P <= 0 or A <= 0:
        return 0.0
    h = P / 4  # (L + t) / 2
    disc = h * h - A
    return h - math.sqrt(disc) if disc > 0 else math.sqrt(A)


def _no_holes(poly, depth=0):
    """Split a polygon with holes into hole-free pieces (cuts through each hole), so consumers that read only
    the outer ring (extrusion, rooms) never see a wall ring as a solid block."""
    from shapely.geometry import LineString
    from shapely.ops import split
    if not poly.interiors or depth > 40:
        return [poly]
    h = poly.interiors[0]
    c = h.centroid
    x0, y0, x1, y1 = poly.bounds
    hx0, hy0, hx1, hy1 = h.bounds
    if hx1 - hx0 >= hy1 - hy0:
        cut = LineString([(c.x, y0 - 1), (c.x, y1 + 1)])
    else:
        cut = LineString([(x0 - 1, c.y), (x1 + 1, c.y)])
    try:
        parts = split(poly, cut).geoms
    except Exception:  # noqa: BLE001
        return [poly]
    out = []
    for q in parts:
        if q.geom_type == "Polygon" and q.area > 1e-6:
            out.extend(_no_holes(q, depth + 1))
    return out




MAX_WALL_PT = 32.0  # thickest plausible cut wall on paper (60 cm at 1:50 is 34 pt)


def _drop_blobs(cands, max_t=MAX_WALL_PT):
    """Cut away parts thicker than any wall (filled plazas, stair blocks, column clusters, dense tag fields)
    by morphological opening; keep the thin remainder."""
    out = []
    r = max_t / 2
    for p, t, style in cands:
        core = p.buffer(-r, join_style=2)
        if not core.is_empty:
            p = p.difference(core.buffer(r + 0.5, join_style=2))
        for q in getattr(p, "geoms", [p]):
            if q.geom_type == "Polygon" and q.area > 4:
                tq = _thickness(q)
                if tq >= 0.5:
                    out.append((q, tq, style))
    return out


def _quad(Sx, a, sd, l, h):
    """Strip between segment a of Sx and its parallel partner at signed offset sd, over [l, h] on a's axis.
    Returns (polygon, centreline p0, centreline p1)."""
    from shapely.geometry import Polygon
    x0, y0, x1, y1 = Sx[a, :4]
    L = Sx[a, 6]
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy * sd, ux * sd
    p0 = (x0 + ux * l, y0 + uy * l)
    p1 = (x0 + ux * h, y0 + uy * h)
    q = Polygon([p0, p1, (p1[0] + nx, p1[1] + ny), (p0[0] + nx, p0[1] + ny)])
    return q, (p0[0] + nx / 2, p0[1] + ny / 2), (p1[0] + nx / 2, p1[1] + ny / 2)


def _fill_shapes(page, area_box, page_area):
    """Closed filled shapes as (polygon, grey, obj), even-odd holes per draw object, white fills skipped."""
    from shapely.geometry import Polygon
    from shapely import make_valid
    groups = defaultdict(list)
    for p in page["paths"]:
        if p["fill"] is None or not p["closed"] or len(p["pts"]) < 3:
            continue
        groups[p["obj"]].append(p)
    out = []
    for oid, ps in groups.items():
        geom = None
        for p in ps:
            try:
                pg = make_valid(Polygon(p["pts"]))
            except Exception:  # noqa: BLE001
                continue
            if not pg.is_empty:
                geom = pg if geom is None else geom.symmetric_difference(pg)
        if geom is None or geom.is_empty or geom.area < 4:
            continue
        geom = geom.intersection(area_box)
        if geom.is_empty or geom.area > 0.2 * page_area:
            continue
        g = _grey(ps[0]["fill"])
        for poly in getattr(geom, "geoms", [geom]):
            if poly.geom_type == "Polygon" and poly.area >= 4:
                out.append((poly, g, oid))
    return out


def _segments_from_polys(polys):
    rows = []
    for k, poly in enumerate(polys):
        for ring in [poly.exterior] + list(poly.interiors):
            c = list(ring.coords)
            for (x0, y0), (x1, y1) in zip(c, c[1:]):
                if math.hypot(x1 - x0, y1 - y0) > 0.02:
                    rows.append((x0, y0, x1, y1, 0.0, float(k)))
    return np.array(rows, float).reshape(-1, 6)


def walls(page: dict) -> list:
    """Walls in page points: one straight piece per wall run, from a pair of parallel edges.
    Each: {"polygon": rectangle, "centerline": [[x,y],[x,y]], "thickness_pt": edge distance, "style"}.
    Evidence, in order of trust: (a) dark/hatch filled wall shapes (pairs of opposite edges inside the fill; the
    fill's grey is the page's wall grey, lighter fills and fills holding fixture symbols are not walls),
    (b) double outlines (CAD style), gated by poche hatching when the page hatches its walls, never where a fill
    wall already is, (c) thick strokes. Thickness is always the distance between the two edges (or the stroke
    width), never a union of fill and outline."""
    from shapely.geometry import LineString, Polygon, box as sbox
    from shapely.ops import unary_union
    from shapely import STRtree

    W, H = page["W_pt"], page["H_pt"]
    if W <= 0 or not page["paths"]:
        return []
    box = _frame_and_titleblock(page)
    area_box = sbox(*box)
    page_area = W * H
    word_boxes = [w["bbox"] for w in page["words"]]

    # ---------- (a) fill walls
    shapes = _fill_shapes(page, area_box, page_area)
    circles = []  # fixture symbols: burners, basins, WC bowls
    for p in page["paths"]:
        if p["n_curves"] >= 4 and p["closed"]:
            a_ = np.asarray(p["pts"], float)
            x0, y0 = a_.min(0); x1, y1 = a_.max(0)
            w_, h_ = x1 - x0, y1 - y0
            if 1.5 <= max(w_, h_) < 30 and max(w_, h_) <= 1.8 * max(min(w_, h_), 1e-6):
                circles.append(((x0 + x1) / 2, (y0 + y1) / 2))
    ctree = STRtree([sbox(x - 0.1, y - 0.1, x + 0.1, y + 0.1) for x, y in circles]) if circles else None
    cand = []
    for poly, g, oid in shapes:
        if g > 0.85:
            continue
        t = _thickness(poly)
        x0, y0, x1, y1 = poly.bounds
        span = max(x1 - x0, y1 - y0)
        if t < 0.5 or t > 40 or span < 8 or (span < 2.5 * t and poly.area < 400):
            continue
        if ctree is not None and len(ctree.query(poly, predicate="contains")):
            continue  # holds a fixture symbol: counter, bath, basin
        cand.append((poly, g, t))
    fill_polys = []
    if cand:
        # the page's wall grey: the darkest grey that carries a real share of the elongated fill area
        by_g = defaultdict(float)
        for poly, g, t in cand:
            by_g[round(g, 2)] += poly.area
        tot = sum(by_g.values())
        wall_g = min((k for k, v in by_g.items() if v >= 0.2 * tot), default=None)
        fill_polys = [poly for poly, g, t in cand if g <= wall_g + 0.06] if wall_g is not None else []
    pieces = []  # (polygon, c0, c1, d, style)
    fill_u = None
    if fill_polys:
        fill_u = unary_union(fill_polys)
        FE = _merge_collinear(_segments_from_polys(fill_polys), gap=0.3)
        pairs_f, _ = _pairs(FE, 0.5, MAX_WALL_PT, min_ov=0.3)
        fq = []
        for a_, b_, d, sd, l, h in pairs_f:
            q, c0, c1 = _quad(FE, a_, sd, l, h)
            if q.is_valid and q.area > 0 and q.intersection(fill_u).area >= 0.85 * q.area:
                fq.append((q, c0, c1, d, "fill"))
        fq.sort(key=lambda r: r[3])  # thinnest first: a fill rectangle's short side is its thickness
        pieces += _accept(fq, [])

    # ---------- (b) double outlines, (c) thick strokes
    S = _segments(page, box)
    stroke_pieces = []
    if len(S):
        widths = S[:, 4]
        wmed = float(np.median(widths))
        thick_min = max(1.4, 2.5 * wmed)
        thick = (widths >= thick_min) & (S[:, 6] >= np.maximum(6.0, 3 * widths))
        bx0, by0, bx1, by1 = box
        on_frame = (((np.abs(S[:, 0] - bx0) < 1) & (np.abs(S[:, 2] - bx0) < 1)) | ((np.abs(S[:, 0] - bx1) < 1) & (np.abs(S[:, 2] - bx1) < 1))
                    | ((np.abs(S[:, 1] - by0) < 1) & (np.abs(S[:, 3] - by0) < 1)) | ((np.abs(S[:, 1] - by1) < 1) & (np.abs(S[:, 3] - by1) < 1)))
        cidx = np.where(~thick & ~on_frame & (S[:, 6] >= 4.0) & ~_grid_lines(page, S))[0]
        Sc = S[cidx]
        pairs, nb = _pairs(Sc, 1.0, MAX_WALL_PT)
        bad = _series(Sc, pairs)
        digit_boxes = [b_ for b_, w in zip(word_boxes, page["words"]) if DIMW.match(w["text"]) and DIGIT.search(w["text"])]
        dim_seg = set()
        if digit_boxes:
            dtree = STRtree([sbox(*b_) for b_ in digit_boxes])
            for k, (x0, y0, x1, y1, *_r) in enumerate(Sc):
                hits = dtree.query(LineString([(x0, y0), (x1, y1)]).buffer(4.0))
                horiz = abs(x1 - x0) >= abs(y1 - y0)
                if any(((digit_boxes[h_][2] - digit_boxes[h_][0]) >= (digit_boxes[h_][3] - digit_boxes[h_][1])) == horiz
                       for h_ in hits.tolist()):
                    dim_seg.add(k)
        oq = []
        for a_, b_, d, sd, l, h in pairs:
            if a_ in bad or b_ in bad or (a_ in dim_seg and b_ in dim_seg):
                continue
            if h - l < 1.5 * d:
                continue  # stub
            q, c0, c1 = _quad(Sc, a_, sd, l, h)
            if q.is_valid and q.area > 0:
                oq.append((q, c0, c1, d, "double"))
        # tag boxes
        if oq and word_boxes:
            wb = [sbox(*b_) for b_ in word_boxes]
            wtree = STRtree(wb)
            qs = [r[0] for r in oq]
            qi_, wi_ = wtree.query(qs, predicate="intersects")
            cover = np.zeros(len(qs))
            for x_, y_ in zip(qi_.tolist(), wi_.tolist()):
                cover[x_] += qs[x_].intersection(wb[y_]).area
            oq = [r for r, c in zip(oq, cover) if c < 0.25 * r[0].area]
        # poche hatching inside each strip (Revit/ArchiCAD cut walls); when the page hatches its walls, demand it
        hatched = np.zeros(len(oq), bool)
        page_hatches = False
        if oq:
            from shapely import points as spoints
            dp = _detail_points(page, box)
            from shapely.geometry import Polygon as _P
            halves = []
            for q, c0, c1, d, st in oq:
                p0, p1, p2, p3 = list(q.exterior.coords)[:4]
                halves.append(_P([p0, p1, c1, c0]))
                halves.append(_P([c0, c1, p2, p3]))
            if len(dp):
                qi_, _ = STRtree(spoints(dp)).query(halves, predicate="contains")
                cnt = np.bincount(qi_, minlength=len(halves))
            else:
                cnt = np.zeros(len(halves), int)
            qlen = np.array([r[0].area / max(r[3], 0.5) for r in oq])
            # poche fills the whole strip: both halves hatched (a wall + an empty band beside it is not a wall)
            # density per paper area (hatch spacing is a paper quantity): cut-wall poche ~0.2-0.35 marks/pt^2,
            # floor stipple and finish patterns beside a wall ~0.02-0.08
            harea = np.array([h_.area for h_ in halves])
            dens_h = cnt / np.maximum(harea, 1e-6)
            hatched = np.minimum(dens_h[0::2], dens_h[1::2]) >= 0.1
            # looser: marks per unit length (round-1 rule) for strips no wider than the page's typical hatched
            # wall (exterior walls whose poche is sparse on one side, e.g. next to glazing)
            if hatched.any():
                dd = np.array([r[3] for r in oq])
                t_ref = float(np.median(dd[hatched]))
                loose = ((cnt[0::2] + cnt[1::2]) / np.maximum(qlen, 1e-6) >= 0.3) & (dd <= 1.3 * t_ref)
                hatched = hatched | loose
            hl = float(qlen[hatched].sum())
            page_hatches = hl > 0.25 * float(qlen.sum()) and hl > 300
            if page_hatches:
                oq = [r for r, h_ in zip(oq, hatched) if h_]
                hatched = np.ones(len(oq), bool)
        # fixtures / casework (un-hatched strips only): a small light-filled shape covering the strip, or
        # fixture symbols (burners, basins, bowls) inside it
        _lg = [(poly, g) for poly, g, oid in shapes if g > 0.5 and poly.area < 0.01 * page_area]
        light = [p_ for p_, _ in _lg]
        white = {k for k, (_, g) in enumerate(_lg) if g >= 0.97}  # white fills: room/mask backgrounds, not slabs
        _tw = [r[3] for r in pieces] or [r[3] for r, h_ in zip(oq, hatched) if h_]
        t_wall = float(np.median(_tw)) if _tw else None
        if oq and (light or ctree is not None):
            ltree = STRtree(light) if light else None
            keep = []
            for r, h_ in zip(oq, hatched):
                q = r[0]
                if not h_:
                    if ltree is not None:
                        hits = ltree.query(q).tolist()
                        cov = sum(light[k].intersection(q).area for k in hits)
                        if cov >= 0.5 * q.area:
                            if _is_parapet(r, light, hits, ctree, t_wall, white):
                                keep.append((q, r[1], r[2], r[3], "parapet"))
                            continue
                    if ctree is not None and len(ctree.query(q, predicate="contains")):
                        continue
                keep.append(r)
            oq = keep
        # thickness floor from the page's own walls: strips much thinner than its walls are face/dimension
        # line pairs or hatch bands (the "fins")
        ref = [(r[3], r[0].area) for r in (oq if page_hatches or not pieces else pieces) if r[4] != "parapet"]
        if ref:
            ref.sort()
            half, acc = sum(a_ for _, a_ in ref) / 2, 0.0
            for t0, a_ in ref:
                acc += a_
                if acc >= half:
                    break
            lt = STRtree(light) if light else None
            oq = [r if r[3] >= max(1.0, 0.4 * t0) or r[4] == "parapet" else (r[0], r[1], r[2], r[3], "parapet")
                  for r in oq
                  if r[3] >= max(1.0, 0.4 * t0) or r[4] == "parapet"
                  or (lt is not None and _is_parapet(r, light, lt.query(r[0].buffer(2 * r[3] + 1)).tolist(), ctree, t_wall, white))]
        oq.sort(key=lambda r: -r[3])  # widest valid pair first: inner hatch bands of a wall then overlap it
        stroke_pieces += oq
        for x0, y0, x1, y1, w, g, L, ang in S[thick]:
            q = LineString([(x0, y0), (x1, y1)]).buffer(w / 2, cap_style=2)
            stroke_pieces.append((q, (x0, y0), (x1, y1), float(w), "stroke"))
    pieces = _accept(stroke_pieces, pieces)
    if not pieces:
        return []
    segs = _merge_pieces(pieces)
    segs = _drop_isolated(segs)
    segs = _extend_ends(segs)
    out = []
    for (x0, y0), (x1, y1), t, style in segs:
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1.0:
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = -uy * t / 2, ux * t / 2
        rect = [[x0 + nx, y0 + ny], [x1 + nx, y1 + ny], [x1 - nx, y1 - ny], [x0 - nx, y0 - ny]]
        out.append({"polygon": [[round(float(x), 3), round(float(y), 3)] for x, y in rect],
                    "centerline": [[round(float(x0), 3), round(float(y0), 3)], [round(float(x1), 3), round(float(y1), 3)]],
                    "thickness_pt": round(float(t), 3), "style": style})
        if style == "parapet":
            out[-1]["height_m"] = 1.0  # balcony / terrace parapet: low wall
    return out


def _is_parapet(r, light, hits, ctree, t_wall=None, white=frozenset()):
    """A thin strip running along the edge of a large light-filled slab with no fixture symbols in it
    (balcony / terrace / loggia floor), or itself drawn as a thin light-filled bar much thinner than the page's
    walls: a parapet, kept as a low wall."""
    q, d = r[0], r[3]
    if t_wall and d <= 0.6 * t_wall:
        for k in hits:
            L = light[k]
            tl = _thickness(L)
            if 0.7 * d <= tl <= 1.3 * d and L.area >= 10 * d * d and L.intersection(q).area >= 0.8 * q.area \
                    and not (ctree is not None and len(ctree.query(L, predicate="contains"))):
                return True
    for k in hits:
        L = light[k]
        if k in white or _thickness(L) < 6 * d or L.area < 400:
            continue
        if ctree is not None and len(ctree.query(L, predicate="contains")):
            continue  # bath tub, shower tray, counter
        if L.exterior.buffer(1.5 * d + 0.5).contains(q):
            return True
    return False


def _accept(cands, accepted, max_overlap=0.3):
    """Greedy: take candidates in the given order unless they overlap already taken pieces by > max_overlap
    of their own area (one shape per wall: fill wins over outline, a wall over its inner hatch bands)."""
    from shapely import STRtree
    out = list(accepted)
    if not cands:
        return out
    allq = [r[0] for r in out] + [r[0] for r in cands]
    tree = STRtree(allq)
    taken = np.zeros(len(allq), bool)
    taken[:len(out)] = True
    for k, r in enumerate(cands):
        gi = len(accepted) + k
        q = r[0]
        ov = 0.0
        for j in tree.query(q).tolist():
            if taken[j] and j != gi:
                ov += allq[j].intersection(q).area
                if ov > max_overlap * q.area:
                    break
        if ov <= max_overlap * q.area:
            taken[gi] = True
            out.append(r)
    return out


def _merge_pieces(pieces, ang_q=math.radians(1.0), off_q=0.6, gap=1.0):
    """Join collinear pieces of equal thickness into wall runs: [(c0, c1, t, style)]."""
    rows = []
    for q, c0, c1, d, style in pieces:
        dx, dy = c1[0] - c0[0], c1[1] - c0[1]
        L = math.hypot(dx, dy)
        if L <= 0:
            continue
        ang = math.atan2(dy, dx) % math.pi
        if ang > math.pi - ang_q / 2:
            ang -= math.pi
        ux, uy = math.cos(ang), math.sin(ang)
        off = -uy * c0[0] + ux * c0[1]
        t0, t1 = ux * c0[0] + uy * c0[1], ux * c1[0] + uy * c1[1]
        rows.append((round(ang / ang_q), round(off / off_q), round(d / max(0.3, 0.12 * d)), min(t0, t1),
                     max(t0, t1), ang, off, d, style))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    out = []
    cur = None
    for r in rows:
        if cur is not None and r[:3] == cur[0] and r[3] <= cur[2] + gap:
            cur[2] = max(cur[2], r[4]); cur[5].append(r[6]); cur[6].append(r[7]); cur[7][r[8]] += r[4] - r[3]
            continue
        if cur is not None:
            out.append(cur)
        st = defaultdict(float); st[r[8]] += r[4] - r[3]
        cur = [r[:3], r[3], r[4], r[5], None, [r[6]], [r[7]], st]
    if cur is not None:
        out.append(cur)
    segs = []
    for key, lo, hi, ang, _, offs, ds, st in out:
        ux, uy = math.cos(ang), math.sin(ang)
        o = float(np.mean(offs))
        segs.append(((lo * ux - o * uy, lo * uy + o * ux), (hi * ux - o * uy, hi * uy + o * ux), float(np.median(ds)),
                     max(st, key=st.get)))
    return segs


def _seg_rect(c0, c1, t, ext=0.0):
    from shapely.geometry import LineString
    return LineString([c0, c1]).buffer(t / 2 + ext, cap_style=2)


def _drop_isolated(segs):
    """Keep the connected wall network: drop small isolated pieces (furniture, symbols, stray pairs)."""
    from shapely import STRtree
    if not segs:
        return segs
    rects = [_seg_rect(c0, c1, t, 1.5) for c0, c1, t, _ in segs]
    tree = STRtree(rects)
    n = len(segs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    qi, qj = tree.query(rects, predicate="intersects")
    for a, b in zip(qi.tolist(), qj.tolist()):
        if a != b:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    comp = defaultdict(float)
    for i, (c0, c1, t, _) in enumerate(segs):
        comp[find(i)] += math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    top = max(comp.values())
    return [s for i, s in enumerate(segs) if comp[find(i)] >= max(40.0, 0.02 * top)]


def _extend_ends(segs):
    """Close corners and T-junctions: an end that runs into another wall is extended by up to half that wall's
    thickness (+ its own half), so the pieces overlap instead of leaving a notch. Free ends (door jambs) stay."""
    from shapely import STRtree
    from shapely.geometry import Point
    if not segs:
        return segs
    rects = [_seg_rect(c0, c1, t, 0.3) for c0, c1, t, _ in segs]
    tree = STRtree(rects)
    out = []
    for i, (c0, c1, t, st) in enumerate(segs):
        L = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
        ux, uy = (c1[0] - c0[0]) / L, (c1[1] - c0[1]) / L
        ends = [list(c0), list(c1)]
        for e, sgn in ((0, -1), (1, 1)):
            best = 0.0
            for j in tree.query(Point(ends[e]).buffer(t / 2 + 0.5)).tolist():
                if j == i:
                    continue
                tj = segs[j][2]
                for k in range(1, 9):
                    ext = k * (t / 2 + tj) / 8
                    p = Point(ends[e][0] + sgn * ux * ext, ends[e][1] + sgn * uy * ext)
                    if rects[j].contains(p):
                        best = max(best, ext)
            if best > 0:
                ends[e] = [ends[e][0] + sgn * ux * best, ends[e][1] + sgn * uy * best]
        out.append((tuple(ends[0]), tuple(ends[1]), t, st))
    return out


def wall_length_pt(ws) -> float:
    """Centre-line length estimate: area / thickness, thickness from the wall's whole (pre-split) shape."""
    from shapely.geometry import Polygon
    tot = 0.0
    for w in ws:
        p = Polygon(w["polygon"], w.get("holes") or None)
        if w["thickness_pt"] > 0:
            tot += p.area / w["thickness_pt"]
    return tot


# ---------------------------------------------------------------- debug overlay

def overlay(pdf_path, page_index, page, ws, out_png, max_side=3000):
    """Render the page with pypdfium2 and draw walls in dark red (screenshots for the team)."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    doc = pdfium.PdfDocument(str(pdf_path))
    pg = doc[page_index]
    s = min(150 / 72, max_side / max(page["W_pt"], page["H_pt"]))
    img = pg.render(scale=s).to_pil().convert("RGB")
    doc.close()
    mask = Image.new("L", img.size, 0)
    dr = ImageDraw.Draw(mask)
    for w in ws:
        dr.polygon([tuple(to_px(p, s)) for p in w["polygon"]], fill=200)
        for h in w.get("holes") or []:
            dr.polygon([tuple(to_px(p, s)) for p in h], fill=0)
    red = Image.new("RGB", img.size, (140, 0, 0))
    img = Image.composite(red, img, mask)
    dr = ImageDraw.Draw(img)
    styles = defaultdict(int)
    for w in ws:
        styles[w["style"]] += 1
    dr.rectangle([0, 0, 900, 40], fill="white")
    dr.text((8, 8), f"walls={len(ws)} {dict(styles)} len={wall_length_pt(ws):.0f}pt reader={page.get('reader')}",
            fill=(0, 0, 0))
    img.save(out_png)
    return out_png


if __name__ == "__main__":
    import sys
    import time
    pdf, i = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0
    t = time.time()
    pg = load_page(pdf, i)
    t1 = time.time()
    ws = walls(pg)
    t2 = time.time()
    print(f"paths={len(pg['paths'])} words={len(pg['words'])} cover={pg['image_cover']:.2f} load={t1-t:.2f}s "
          f"walls={len(ws)} {t2-t1:.2f}s len={wall_length_pt(ws):.0f}pt")
    if len(sys.argv) > 3:
        overlay(pdf, i, pg, ws, sys.argv[3])
