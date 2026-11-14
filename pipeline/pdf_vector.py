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
        if free > 0.5 * (h - l):
            acc.add((i, j))
            nb[i] += 1
            covered.append((l, h))
    out = []
    for k in range(len(qi)):
        i, j = int(qi[k]), int(qj[k])
        if i < j and (i, j) in acc and (j, i) in acc:
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


def walls(page: dict) -> list:
    """Wall polygons in page points. Styles: dark/pattern filled shapes, double parallel lines, thick strokes."""
    from shapely.geometry import Polygon, LineString, box as sbox
    from shapely.ops import unary_union
    from shapely import make_valid

    W, H = page["W_pt"], page["H_pt"]
    if W <= 0 or not page["paths"]:
        return []
    box = _frame_and_titleblock(page)
    area_box = sbox(*box)
    page_area = W * H
    # text boxes (for dropping glyph-like fills and dimension strings)
    word_boxes = [w["bbox"] for w in page["words"]]

    # ---- (a) filled polygons, grouped per draw object (even-odd holes)
    groups = defaultdict(list)
    for p in page["paths"]:
        if p["fill"] is None or not p["closed"] or len(p["pts"]) < 3:
            continue
        g = _grey(p["fill"])
        if g > 0.8:
            continue
        groups[p["obj"]].append(p)
    fills = []
    for oid, ps in groups.items():
        geom = None
        for p in ps:
            try:
                pg = make_valid(Polygon(p["pts"]))
            except Exception:  # noqa: BLE001
                continue
            if pg.is_empty:
                continue
            geom = pg if geom is None else geom.symmetric_difference(pg)
        if geom is None or geom.is_empty or geom.area < 4:
            continue
        geom = geom.intersection(area_box)
        if geom.is_empty or geom.area > 0.2 * page_area:
            continue
        g = _grey(ps[0]["fill"])
        for poly in getattr(geom, "geoms", [geom]):
            if poly.geom_type != "Polygon" or poly.area < 4:
                continue
            t = _thickness(poly)
            x0, y0, x1, y1 = poly.bounds
            span = max(x1 - x0, y1 - y0)
            if t < 0.5 or t > 40 or span < 8 or span < 2.5 * t and poly.area < 400:
                continue
            if g > 0.55 and t > 12:
                continue  # light fill, thick: room/area tint
            fills.append((poly, t, g))

    # ---- segments for (b) and (c)
    S = _segments(page, box)
    out = []
    if len(S):
        widths = S[:, 4]
        wmed = float(np.median(widths))
        # (c) thick strokes: clearly heavier than the typical line and not text sized
        thick_min = max(1.4, 2.5 * wmed)
        thick = (widths >= thick_min) & (S[:, 6] >= np.maximum(6.0, 3 * widths))
        # (b) double lines among non-thick, non-hairline-vs-heavy segments
        cand = np.where(~thick & (S[:, 6] >= 4.0) & ~_grid_lines(page, S))[0]
        Sc = S[cand]
        pairs, nb = _pairs(Sc, 1.0, 30.0)
        bad = _series(Sc, pairs)
        # dimension lines: digit words lying along the segment
        digit_boxes = [b for b, w in zip(word_boxes, page["words"]) if DIMW.match(w["text"]) and DIGIT.search(w["text"])]
        dim_seg = set()
        if digit_boxes:
            from shapely import STRtree
            dtree = STRtree([sbox(*b) for b in digit_boxes])
            for k, (x0, y0, x1, y1, *_r) in enumerate(Sc):
                ls = LineString([(x0, y0), (x1, y1)])
                hits = dtree.query(ls.buffer(4.0))
                horiz = abs(x1 - x0) >= abs(y1 - y0)
                hits = [h for h in hits.tolist() if (lambda b: (b[2] - b[0] >= b[3] - b[1]) == horiz)(digit_boxes[h])]
                if hits:
                    dim_seg.add(k)
        quads = []
        thick_of = []
        for a, b, d, sd, l, h in pairs:
            if a in bad or b in bad:
                continue
            if a in dim_seg and b in dim_seg:
                continue
            if h - l < 1.5 * d:
                continue  # stub: dash-drawn grid/section lines side by side, mullions, comb teeth
            x0, y0, x1, y1 = Sc[a, :4]
            L = Sc[a, 6]
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            nx, ny = -uy * sd, ux * sd
            p0 = (x0 + ux * l, y0 + uy * l)
            p1 = (x0 + ux * h, y0 + uy * h)
            q = Polygon([p0, p1, (p1[0] + nx, p1[1] + ny), (p0[0] + nx, p0[1] + ny)])
            if q.is_valid and q.area > 0:
                quads.append(q)
                thick_of.append(d)
        # tag / label boxes: a word covering a large part of the strip
        if quads and word_boxes:
            from shapely import STRtree
            wb = [sbox(*b) for b in word_boxes]
            wtree = STRtree(wb)
            qi_, wi_ = wtree.query(quads, predicate="intersects")
            cover = np.zeros(len(quads))
            for a_, b_ in zip(qi_.tolist(), wi_.tolist()):
                cover[a_] += quads[a_].intersection(wb[b_]).area
            ok = cover < 0.25 * np.array([q.area for q in quads])
            quads = [q for q, k in zip(quads, ok) if k]
            thick_of = [t for t, k in zip(thick_of, ok) if k]
        # hatch / pattern density inside each pair: Revit/ArchiCAD walls carry insulation or poche hatching,
        # furniture and casework outlines are empty. When a page hatches its walls, demand it.
        if quads:
            from shapely import STRtree, points as spoints
            dp = _detail_points(page, box)
            if len(dp):
                ptree = STRtree(spoints(dp))
                qi_, pi_ = ptree.query(quads, predicate="contains")
                cnt = np.bincount(qi_, minlength=len(quads))
            else:
                cnt = np.zeros(len(quads), int)
            qlen = np.array([q.area / max(t, 0.5) for q, t in zip(quads, thick_of)])
            dens = cnt / np.maximum(qlen, 1e-6)
            hatched = dens >= 0.3
            hl = float(qlen[hatched].sum())
            if hl > 0.25 * float(qlen.sum()) and hl > 300:
                quads = [q for q, h in zip(quads, hatched) if h]
        dbl = []
        if quads:
            u = unary_union([q.buffer(0.3, join_style=2) for q in quads]).buffer(-0.3, join_style=2)
            for poly in getattr(u, "geoms", [u]):
                if poly.geom_type == "Polygon" and poly.area > 2:
                    dbl.append(poly)
        # thick stroke polygons
        stk = []
        for x0, y0, x1, y1, w, g, L, ang in S[thick]:
            stk.append(LineString([(x0, y0), (x1, y1)]).buffer(w / 2, cap_style=2))
        stk_u = unary_union(stk) if stk else None
        cand_polys = [(p, _thickness(p), "fill") for p, t, g in fills]
        cand_polys += [(p, _thickness(p), "double") for p in dbl]
        if stk_u is not None and not stk_u.is_empty:
            for p in getattr(stk_u, "geoms", [stk_u]):
                if p.geom_type == "Polygon":
                    cand_polys.append((p, _thickness(p), "stroke"))
    else:
        cand_polys = [(p, _thickness(p), "fill") for p, t, g in fills]

    cand_polys = _drop_blobs(cand_polys)
    if not cand_polys:
        return []
    # ---- keep the connected wall network: drop isolated small pieces (furniture, symbols)
    polys = [c[0] for c in cand_polys]
    from shapely import STRtree
    tree = STRtree([p.buffer(1.5) for p in polys])
    n = len(polys)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    qi, qj = tree.query([p.buffer(1.5) for p in polys], predicate="intersects")
    for a, b in zip(qi.tolist(), qj.tolist()):
        if a != b:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    comp_len = defaultdict(float)
    lens = [p.area / max(c[1], 0.5) for p, c in zip(polys, cand_polys)]
    for i in range(n):
        comp_len[find(i)] += lens[i]
    top = max(comp_len.values())
    kept = []
    for (poly, t, style), i in zip(cand_polys, range(n)):
        cl = comp_len[find(i)]
        if cl < max(40.0, 0.02 * top) or t < 0.5:
            continue
        kept.append((poly, style, t))
    if not kept:
        return out
    # one shape per wall: a wall drawn as a hatch fill AND as two outline strokes yields overlapping fill and
    # double candidates; union them so area and length are counted once. Style = the style covering most.
    from shapely import STRtree
    u = unary_union([k[0].buffer(0.05, join_style=2) for k in kept]).buffer(-0.05, join_style=2)
    ktree = STRtree([k[0] for k in kept])
    for poly in getattr(u, "geoms", [u]):
        if poly.geom_type != "Polygon" or poly.area < 1.0:
            continue
        votes = defaultdict(float)
        tw = []
        for k in ktree.query(poly).tolist():
            a_ = kept[k][0].intersection(poly).area
            if a_ > 0:
                votes[kept[k][1]] += a_
                tw.append((kept[k][2], a_))
        style = max(votes, key=votes.get) if votes else "double"
        # thickness: area-weighted median of the contributing simple shapes (a branched union's own
        # area/perimeter rectangle underestimates it)
        if tw:
            tw.sort()
            half, acc = sum(a for _, a in tw) / 2, 0.0
            for t, a_ in tw:
                acc += a_
                if acc >= half:
                    break
        else:
            t = _thickness(poly)
        if t < 0.5:
            continue
        for piece in _no_holes(poly.simplify(0.05)):
            if piece.area < 1.0:
                continue
            out.append({"polygon": [[round(x, 3), round(y, 3)] for x, y in list(piece.exterior.coords)[:-1]],
                        "thickness_pt": round(t, 3), "style": style})
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
