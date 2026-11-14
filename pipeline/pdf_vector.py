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
        bfx, bfy = ctypes.byref(fx), ctypes.byref(fy)
        seg_api = (R.FPDFPath_GetPathSegment, R.FPDFPathSegment_GetPoint, R.FPDFPathSegment_GetType,
                   R.FPDFPathSegment_GetClose)
        MOVETO, BEZIERTO = R.FPDF_SEGMENT_MOVETO, R.FPDF_SEGMENT_BEZIERTO
        rnd = round

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

            # hot loop (a million segments on a MEP sheet): bound locals, reused byref, displayer inlined
            GetSeg, GetPt, GetType, GetClose = seg_api
            for k in range(n):
                seg = GetSeg(obj, k)
                GetPt(seg, bfx, bfy)
                x, y = fx.value, fy.value
                u, v = a * x + c * y + e, b * x + d * y + f
                if rot == 0:
                    X, Y = u - cl, H0 - (v - cb)
                else:
                    X, Y = disp(u, v)
                t = GetType(seg)
                if t == MOVETO:
                    flush()
                    cur, closed, ncurv, bez = [(X, Y)], False, 0, []
                elif t == BEZIERTO:
                    bez.append((X, Y))
                    if len(bez) == 3:
                        p0 = cur[-1] if cur else bez[0]
                        cur.extend(_bez(p0, bez[0], bez[1], bez[2]))
                        bez = []
                        ncurv += 1
                else:
                    cur.append((X, Y))
                if GetClose(seg):
                    closed = True
            flush()
            for pts, cl_, nc in subs:
                if fill_on:
                    cl_ = True
                if cl_ and len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                    pts = pts[:-1]
                paths.append({"pts": [[rnd(px, 3), rnd(py, 3)] for px, py in pts], "closed": bool(cl_),
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


_FLAT = None  # (paths list, table) for the page walls() is working on


def _flat(page):
    """All path segments of the page as numpy arrays (built once per walls() call): "seg" (n,4) x0,y0,x1,y1 in
    path order, closing edge of closed paths last; "sp" path index per segment; per path: "grey" (stroke grey,
    nan = no stroke), "width", "dashed", "arc", "fill", "closed", "npts", "n_curves", "bbox" (x0,y0,x1,y1)."""
    paths = page["paths"]
    if _FLAT is not None and _FLAT[0] is paths:
        return _FLAT[1]
    m = len(paths)
    npts = np.fromiter((len(p["pts"]) for p in paths), np.int64, m)
    P = np.array([q for p in paths for q in p["pts"]], float).reshape(-1, 2)
    closed = np.fromiter((bool(p["closed"]) for p in paths), bool, m)
    pid = np.repeat(np.arange(m), npts)
    start = np.cumsum(npts) - npts
    if len(P) > 1:
        ia = np.flatnonzero(pid[:-1] == pid[1:])
    else:
        ia = np.zeros(0, np.int64)
    cl = np.flatnonzero(closed & (npts >= 2))
    ic = start[cl] + npts[cl] - 1
    a = np.concatenate([ia, ic])
    bnd = np.concatenate([ia + 1, start[cl]])
    o = np.argsort(np.concatenate([ia * 2.0, ic * 2.0 + 1.0]), kind="stable")
    a, bnd = a[o], bnd[o]
    seg = np.column_stack([P[a], P[bnd]]) if len(a) else np.zeros((0, 4))
    stroke = [p["stroke"] for p in paths]
    grey = np.array([np.nan if c is None else 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] for c in stroke], float)
    if m and len(P):
        nz = npts > 0
        st_nz = start[nz]
        bbox = np.full((m, 4), np.nan)
        bbox[nz, 0] = np.minimum.reduceat(P[:, 0], st_nz); bbox[nz, 1] = np.minimum.reduceat(P[:, 1], st_nz)
        bbox[nz, 2] = np.maximum.reduceat(P[:, 0], st_nz); bbox[nz, 3] = np.maximum.reduceat(P[:, 1], st_nz)
    else:
        bbox = np.zeros((m, 4))
    return {"seg": seg, "sp": pid[a] if len(a) else np.zeros(0, np.int64), "grey": grey,
            "width": np.fromiter((p["width"] for p in paths), float, m),
            "dashed": np.fromiter((bool(p["dashed"]) for p in paths), bool, m),
            "arc": np.fromiter((bool(p["is_arc"]) for p in paths), bool, m),
            "fill": np.fromiter((p["fill"] is not None for p in paths), bool, m),
            "closed": closed, "npts": npts, "n_curves": np.fromiter((p["n_curves"] for p in paths), np.int64, m),
            "bbox": bbox}


def _frame_and_titleblock(page):
    """Drawing area box (x0,y0,x1,y1) inside the border frame and outside the title block."""
    W, H = page["W_pt"], page["H_pt"]
    sg = _flat(page)["seg"]
    ax, ay = np.abs(sg[:, 0] - sg[:, 2]), np.abs(sg[:, 3] - sg[:, 1])
    kv = (ax < 0.5) & (ay > 0.4 * H)
    kh = ~kv & (ay < 0.5) & (ax > 0.4 * W)
    # long vertical lines (x, len), long horizontal lines (y, len)
    vx = list(zip(((sg[kv, 0] + sg[kv, 2]) / 2).tolist(), ay[kv].tolist()))
    hy = list(zip(((sg[kh, 1] + sg[kh, 3]) / 2).tolist(), ax[kh].tolist()))
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
    F = _flat(page)
    okp = ~np.isnan(F["grey"]) & ~F["dashed"] & ~F["arc"] & ~(F["grey"] > max_grey)
    sp = F["sp"]
    ks = okp[sp]
    if not ks.any():
        return np.zeros((0, 6))
    r = np.column_stack([F["seg"][ks], F["width"][sp[ks]], F["grey"][sp[ks]]])
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
    # vectorised run-length join (was a Python loop over every piece: 7 s on a 650k-piece MEP sheet). Within a
    # (angle, offset) key, sorted by start, a new run starts where the start lies beyond the running max end + gap;
    # the running max over the whole key prefix equals the current run's max (earlier runs end before it starts).
    ka_s, ko_s, lo_s, hi_s = ka[order], ko[order], lo[order], hi[order]
    m = len(order)
    newkey = np.ones(m, bool)
    newkey[1:] = (ka_s[1:] != ka_s[:-1]) | (ko_s[1:] != ko_s[:-1])
    gid = np.cumsum(newkey) - 1
    # group-wise running max of hi, exact: on integer ranks of hi, each key group shifted above all earlier ones
    oh = np.argsort(hi_s, kind="stable")
    rank = np.empty(m, np.int64)
    rank[oh] = np.arange(m)
    base = gid.astype(np.int64) * m
    cm = hi_s[oh][np.maximum.accumulate(rank + base) - base]
    start = newkey.copy()
    start[1:] |= lo_s[1:] > cm[:-1] + gap
    st = np.flatnonzero(start)
    hi_r = np.maximum.reduceat(hi_s, st)
    lo_r = lo_s[st]
    w_r = np.maximum.reduceat(R[order, 4], st)
    g_r = np.minimum.reduceat(R[order, 5], st)
    cnt = np.diff(np.append(st, m))
    # offset: mean of members (keeps sub-quantum precision); summed left to right like the scalar version
    offl = off[order].tolist()
    o_sum = [offl[k] for k in st.tolist()]
    for r in np.flatnonzero(cnt > 1).tolist():
        s0 = int(st[r])
        acc = offl[s0]
        for t in range(s0 + 1, s0 + int(cnt[r])):
            acc += offl[t]
        o_sum[r] = acc
    o_ = np.asarray(o_sum) / cnt
    a_ = ang[order][st].tolist()
    ux_ = np.asarray([math.cos(v) for v in a_]); uy_ = np.asarray([math.sin(v) for v in a_])
    out = np.column_stack([lo_r * ux_ - o_ * uy_, lo_r * uy_ + o_ * ux_, hi_r * ux_ - o_ * uy_, hi_r * uy_ + o_ * ux_,
                           w_r, g_r, hi_r - lo_r, np.asarray([v % math.pi for v in a_])])
    return out.reshape(-1, 8)


def _segments(page, box):
    """Merged straight stroked segments inside box: rows (x0,y0,x1,y1,width,grey,len,angle)."""
    return _merge_collinear(_raw_segments(page, box))


def _parallel_candidates(S, dmax, ang_tol):
    """Directed candidate pairs (i, j), i != j, for _pairs: j within ang_tol of i's angle and near i's strip.
    Segments are bucketed by angle; each bucket is rotated onto its own axis so the boxes are thin (an axis-aligned
    box of a long diagonal line covers half the page, which made the plain STRtree query quadratic on busy MEP
    sheets). The query boxes are padded generously, so this is a superset of every pair _pairs can accept.
    Returns (qi, qj) sorted by qi."""
    from shapely import STRtree, box as sbox
    n = len(S)
    nb = max(1, int(math.pi // ang_tol))
    bw = math.pi / nb
    b = np.minimum((np.mod(S[:, 7], math.pi) / bw).astype(np.int64), nb - 1)
    members = [np.where(b == k)[0] for k in range(nb)]
    L = S[:, 6]
    out_i, out_j = [], []
    for k in range(nb):
        A = members[k]
        if not len(A):
            continue
        B = np.concatenate([members[(k - 1) % nb], A, members[(k + 1) % nb]]) if nb > 2 else np.arange(n)
        th = (k + 0.5) * bw
        c, s = math.cos(th), math.sin(th)

        def rot(idx):
            u0 = S[idx, 0] * c + S[idx, 1] * s
            u1 = S[idx, 2] * c + S[idx, 3] * s
            v0 = -S[idx, 0] * s + S[idx, 1] * c
            v1 = -S[idx, 2] * s + S[idx, 3] * c
            return np.minimum(u0, u1), np.minimum(v0, v1), np.maximum(u0, u1), np.maximum(v0, v1)
        bu0, bv0, bu1, bv1 = rot(B)
        tree = STRtree(sbox(bu0, bv0, bu1, bv1))
        au0, av0, au1, av1 = rot(A)
        pa = 2.0 + 0.1 * dmax + 0.004 * L[A]          # along the axis
        pp = 1.25 * dmax + 1.0 + 0.06 * L[A]          # across it
        a_, t_ = tree.query(sbox(au0 - pa, av0 - pp, au1 + pa, av1 + pp))
        gi, gj = A[a_], B[t_]
        keep = gi != gj
        out_i.append(gi[keep]); out_j.append(gj[keep])
    if not out_i:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    qi, qj = np.concatenate(out_i), np.concatenate(out_j)
    o = np.lexsort((qj, qi))
    return qi[o], qj[o]


def _pairs(S, dmin, dmax, ang_tol=math.radians(2.0), min_ov=0.5):
    """Parallel segment pairs dmin..dmax apart that overlap in projection. For each segment and side, partners
    are taken nearest first, and a farther one only where nearer ones leave its stretch uncovered, so a tiny
    piece next to a long wall line does not hide the long partner. A pair must be accepted from both ends.
    Returns (pairs [(i, j, d, signed_d, t0, t1)] with t on i's axis from its start, neighbour count per seg)."""
    n = len(S)
    if n == 0:
        return [], np.zeros(0, int)
    # a pair needs an overlap > 2 pt, so pieces of <= 2 pt never pair (flattened curves: 90% of a MEP sheet's edges)
    live = np.flatnonzero(S[:, 6] > 2.0)
    qi, qj = _parallel_candidates(S[live], dmax, ang_tol)
    qi, qj = live[qi], live[qj]
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
    order = np.lexsort((qj, np.abs(d), d > 0, qi))
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
    F = _flat(page)
    bb = F["bbox"]
    k = F["fill"] & np.isnan(F["grey"]) & (F["npts"] >= 3)
    with np.errstate(invalid="ignore"):
        k &= (np.maximum(bb[:, 2] - bb[:, 0], bb[:, 3] - bb[:, 1]) < 3) & (bx0 <= bb[:, 0]) & (bb[:, 0] <= bx1) \
            & (by0 <= bb[:, 1]) & (bb[:, 1] <= by1)
    if k.any():
        out.append(np.column_stack([(bb[k, 0] + bb[k, 2]) / 2, (bb[k, 1] + bb[k, 3]) / 2]))
    return np.vstack(out) if out else np.zeros((0, 2))


def _grid_lines(page, S):
    """Mask of segments that are column-grid / section-cut lines: their axis runs into a grid bubble (a small
    circle with a short label inside) beyond one of their ends."""
    mask = np.zeros(len(S), bool)
    F = _flat(page)
    bb = F["bbox"]
    k = np.flatnonzero((F["n_curves"] >= 4) & (F["closed"] | (F["npts"] >= 16)))
    dx, dy = bb[k, 2] - bb[k, 0], bb[k, 3] - bb[k, 1]
    ok = (6 <= dx) & (dx <= 50) & (np.abs(dx - dy) < 0.15 * dx)
    k, dx = k[ok], dx[ok]
    circles = list(zip(((bb[k, 0] + bb[k, 2]) / 2).tolist(), ((bb[k, 1] + bb[k, 3]) / 2).tolist(), (dx / 2).tolist()))
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


def _quads(Sx, pairs):
    """_quad for many pairs at once: (object array of polygons, list of c0, list of c1)."""
    import shapely
    if not len(pairs):
        return np.empty(0, dtype=object), [], []
    P = np.asarray([(r[0], r[3], r[4], r[5]) for r in pairs], float)
    a = P[:, 0].astype(np.int64)
    sd, l, h = P[:, 1], P[:, 2], P[:, 3]
    x0, y0, x1, y1 = Sx[a, 0], Sx[a, 1], Sx[a, 2], Sx[a, 3]
    L = Sx[a, 6]
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy * sd, ux * sd
    p0x, p0y = x0 + ux * l, y0 + uy * l
    p1x, p1y = x0 + ux * h, y0 + uy * h
    C = np.stack([np.column_stack([p0x, p0y]), np.column_stack([p1x, p1y]),
                  np.column_stack([p1x + nx, p1y + ny]), np.column_stack([p0x + nx, p0y + ny])], axis=1)
    polys = shapely.polygons(C)
    c0 = list(zip((p0x + nx / 2).tolist(), (p0y + ny / 2).tolist()))
    c1 = list(zip((p1x + nx / 2).tolist(), (p1y + ny / 2).tolist()))
    return polys, c0, c1


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


def _areas_in(Q, ok, polys, tree, deadline=None, flag=None):
    """For each polygon Q[k] with ok[k]: its area inside the union of polys (object array); others 0. Single
    overlaps are read directly; a union is formed only where the summed overlap could reach the threshold."""
    import shapely
    out = np.zeros(len(Q))
    idx = np.flatnonzero(ok)
    if not len(idx):
        return out
    qa_, pb = tree.query(Q[idx])
    if not len(qa_):
        return out
    inter = shapely.area(shapely.intersection(Q[idx][qa_], polys[pb]))
    tot = np.bincount(qa_, weights=inter, minlength=len(idx))
    cnt = np.bincount(qa_, minlength=len(idx))
    out[idx] = tot
    area = shapely.area(Q[idx])
    multi = np.flatnonzero((cnt > 1) & (tot >= 0.85 * area))
    if len(multi):
        starts = np.searchsorted(qa_, multi)  # tree.query output is sorted by input index
        ends = np.searchsorted(qa_, multi, side="right")
        for n_, (m, s0, s1) in enumerate(zip(multi.tolist(), starts.tolist(), ends.tolist())):
            if n_ % 200 == 0 and deadline is not None and _over(deadline, flag):
                out[idx[multi[n_:]]] = 0.0
                break
            q = Q[idx[m]]
            out[idx[m]] = float(shapely.union_all(shapely.intersection(q, polys[pb[s0:s1]])).area)
    return out


def _segments_from_polys(polys):
    """Edges of the polygons' rings: rows (x0,y0,x1,y1,0,k) with k the polygon index (vectorised)."""
    import shapely
    if not len(polys):
        return np.zeros((0, 6))
    arr = np.empty(len(polys), dtype=object)
    arr[:] = list(polys)
    nint = shapely.get_num_interior_rings(arr)
    ext = shapely.get_exterior_ring(arr)
    if not nint.any():
        rings, own = ext, np.arange(len(arr))
    else:
        rl, ol = [], []
        for k in range(len(arr)):
            rl.append(ext[k]); ol.append(k)
            for h in range(int(nint[k])):
                rl.append(shapely.get_interior_ring(arr[k], h)); ol.append(k)
        rings = np.empty(len(rl), dtype=object)
        rings[:] = rl
        own = np.asarray(ol)
    c, ri = shapely.get_coordinates(rings, return_index=True)
    if len(c) < 2:
        return np.zeros((0, 6))
    same = ri[1:] == ri[:-1]
    x0, y0, x1, y1 = c[:-1, 0], c[:-1, 1], c[1:, 0], c[1:, 1]
    k = same & (np.hypot(x1 - x0, y1 - y0) > 0.02)
    return np.column_stack([x0[k], y0[k], x1[k], y1[k], np.zeros(int(k.sum())), own[ri[:-1][k]].astype(float)])


class WallList(list):
    """walls() result: a list with .truncated (True when the time budget cut the search short)."""
    truncated = False


WALLS_BUDGET_S = 25.0  # default per-page budget for walls(); env PDF_WALLS_BUDGET_S overrides


def walls(page: dict, budget_s: float | None = None) -> list:
    """See _walls. budget_s (default env PDF_WALLS_BUDGET_S or WALLS_BUDGET_S): when the evidence stages run past
    it, the remaining stages are skipped and the walls found so far are returned with .truncated = True (also
    page["walls_truncated"]), instead of running for minutes on a dense MEP sheet."""
    import os
    import time
    global _FLAT
    if budget_s is None:
        try:
            budget_s = float(os.environ.get("PDF_WALLS_BUDGET_S", WALLS_BUDGET_S))
        except ValueError:
            budget_s = WALLS_BUDGET_S
    deadline = time.monotonic() + budget_s if budget_s and budget_s > 0 else None
    _FLAT = None
    if page.get("paths"):
        _FLAT = (page["paths"], _flat(page))
    flag = [False]
    try:
        out = WallList(_walls(page, deadline, flag))
    finally:
        _FLAT = None
    out.truncated = flag[0]
    page["walls_truncated"] = flag[0]
    return out


def _over(deadline, flag):
    import time
    if deadline is not None and time.monotonic() > deadline:
        flag[0] = True
        return True
    return flag[0]


def _walls(page: dict, deadline=None, flag=None) -> list:
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
    F = _flat(page)
    bb = F["bbox"]
    k = np.flatnonzero((F["n_curves"] >= 4) & F["closed"])
    if len(k):
        w_, h_ = bb[k, 2] - bb[k, 0], bb[k, 3] - bb[k, 1]
        mx = np.maximum(w_, h_)
        ok = (1.5 <= mx) & (mx < 30) & (mx <= 1.8 * np.maximum(np.minimum(w_, h_), 1e-6))
        circles = list(zip(((bb[k, 0] + bb[k, 2]) / 2)[ok].tolist(), ((bb[k, 1] + bb[k, 3]) / 2)[ok].tolist()))
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
    if fill_polys:
        # area of each quad inside the union of the fills, from the fills that touch it (one page-wide union of
        # thousands of duct/hatch fills took 18 s on MEP sheets)
        ftree = STRtree(fill_polys)
        farr = np.empty(len(fill_polys), dtype=object)
        farr[:] = fill_polys
        FE = _merge_collinear(_segments_from_polys(fill_polys), gap=0.3)
        pairs_f, _ = _pairs(FE, 0.5, MAX_WALL_PT, min_ov=0.3)
        fq = []
        Q, C0, C1 = _quads(FE, pairs_f)
        if len(Q):
            import shapely
            qa = shapely.area(Q)
            ok = shapely.is_valid(Q) & (qa > 0)
            inside = _areas_in(Q, ok, farr, ftree, deadline, flag)
            for k in np.flatnonzero(ok & (inside >= 0.85 * qa)).tolist():
                fq.append((Q[k], C0[k], C1[k], pairs_f[k][2], "fill"))
        fq.sort(key=lambda r: r[3])  # thinnest first: a fill rectangle's short side is its thickness
        pieces += _accept(fq, [])

    # ---------- (b) double outlines, (c) thick strokes
    if flag is None:
        flag = [False]
    S = _segments(page, box) if not _over(deadline, flag) else np.zeros((0, 8))
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
        if digit_boxes and len(Sc):
            import shapely
            dtree = STRtree([sbox(*b_) for b_ in digit_boxes])
            lines = shapely.linestrings(np.stack([Sc[:, 0:2], Sc[:, 2:4]], axis=1))
            qa, qb = dtree.query(shapely.buffer(lines, 4.0))
            DB = np.asarray(digit_boxes, float)
            horiz = np.abs(Sc[:, 2] - Sc[:, 0]) >= np.abs(Sc[:, 3] - Sc[:, 1])
            dh = (DB[:, 2] - DB[:, 0]) >= (DB[:, 3] - DB[:, 1])
            dim_seg = set(qa[horiz[qa] == dh[qb]].tolist())
        oq = []
        sel = [r for r in pairs if not (r[0] in bad or r[1] in bad or (r[0] in dim_seg and r[1] in dim_seg))
               and not (r[5] - r[4] < 1.5 * r[2])]  # stubs out
        if sel and not _over(deadline, flag):
            import shapely
            Q, C0, C1 = _quads(Sc, sel)
            ok = shapely.is_valid(Q) & (shapely.area(Q) > 0)
            oq = [(Q[k], C0[k], C1[k], sel[k][2], "double") for k in np.flatnonzero(ok).tolist()]
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
    import shapely
    allq = np.empty(len(out) + len(cands), dtype=object)
    allq[:] = [r[0] for r in out] + [r[0] for r in cands]
    tree = STRtree(allq)
    taken = np.zeros(len(allq), bool)
    taken[:len(out)] = True
    n0 = len(accepted)
    # all overlaps of a candidate with earlier-or-accepted shapes, computed in one vectorised pass (only pairs whose
    # boxes meet and where the other shape comes first can ever count)
    ci, cj = tree.query(allq[n0:])
    gi_ = ci + n0
    m = (cj != gi_) & ((cj < n0) | (cj < gi_))
    ci, cj = ci[m], cj[m]
    inter = shapely.area(shapely.intersection(allq[n0 + ci], allq[cj])) if len(ci) else np.zeros(0)
    starts = np.searchsorted(ci, np.arange(len(cands)))
    ends = np.searchsorted(ci, np.arange(len(cands)), side="right")
    cjl, il = cj.tolist(), inter.tolist()
    areas = shapely.area(allq[n0:]).tolist()
    for k, r in enumerate(cands):
        gi = n0 + k
        lim = max_overlap * areas[k]
        ov = 0.0
        for t in range(starts[k], ends[k]):
            if taken[cjl[t]]:
                ov += il[t]
                if ov > lim:
                    break
        if ov <= lim:
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
        # np.mean / np.median cost ~20 us each; one- and two-member runs (most of them) need neither
        o = float(offs[0]) if len(offs) == 1 else float(np.mean(offs))
        md = float(ds[0]) if len(ds) == 1 else float(np.median(ds))
        segs.append(((lo * ux - o * uy, lo * uy + o * ux), (hi * ux - o * uy, hi * uy + o * ux), md,
                     max(st, key=st.get)))
    return segs


def _seg_rect(c0, c1, t, ext=0.0):
    from shapely.geometry import LineString
    return LineString([c0, c1]).buffer(t / 2 + ext, cap_style=2)


def _seg_rects(segs, ext=0.0):
    """_seg_rect for every (c0, c1, t, style) at once (object array)."""
    import shapely
    C = np.asarray([(c0[0], c0[1], c1[0], c1[1]) for c0, c1, t, _ in segs], float).reshape(-1, 2, 2)
    T = np.asarray([t for _, _, t, _ in segs], float)
    return shapely.buffer(shapely.linestrings(C), T / 2 + ext, cap_style="flat")


def _drop_isolated(segs):
    """Keep the connected wall network: drop small isolated pieces (furniture, symbols, stray pairs)."""
    from shapely import STRtree
    if not segs:
        return segs
    rects = _seg_rects(segs, 1.5)
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
    import shapely
    rects = _seg_rects(segs, 0.3)
    tree = STRtree(rects)
    n = len(segs)
    A = np.asarray([(c0[0], c0[1], c1[0], c1[1], t) for c0, c1, t, _ in segs], float)
    L = np.asarray([math.hypot(c1[0] - c0[0], c1[1] - c0[1]) for c0, c1, _, _ in segs], float)
    with np.errstate(invalid="ignore", divide="ignore"):
        ux, uy = (A[:, 2] - A[:, 0]) / L, (A[:, 3] - A[:, 1]) / L
    # end e of seg i: (x, y, direction sign); every (end, other wall) pair, 8 probe points along the axis
    EX = np.concatenate([A[:, 0], A[:, 2]]); EY = np.concatenate([A[:, 1], A[:, 3]])
    SG = np.concatenate([-np.ones(n), np.ones(n)]); SI = np.concatenate([np.arange(n), np.arange(n)])
    probes = shapely.buffer(shapely.points(np.column_stack([EX, EY])), A[SI, 4] / 2 + 0.5)
    pe, pj = tree.query(probes)
    m = pj != SI[pe]
    pe, pj = pe[m], pj[m]
    best = np.zeros(2 * n)
    if len(pe):
        i_ = SI[pe]
        k8 = np.arange(1, 9)
        ext = k8[None, :] * (A[i_, 4] / 2 + A[pj, 4])[:, None] / 8          # (m, 8)
        px = EX[pe][:, None] + (SG[pe] * ux[i_])[:, None] * ext
        py = EY[pe][:, None] + (SG[pe] * uy[i_])[:, None] * ext
        inside = shapely.contains_xy(np.repeat(rects[pj], 8).reshape(-1, 8), px, py)
        e_best = np.where(inside, ext, 0.0).max(1)
        np.maximum.at(best, pe, e_best)
    out = []
    for i, (c0, c1, t, st) in enumerate(segs):
        ends = [list(c0), list(c1)]
        for e, sgn in ((0, -1), (1, 1)):
            b_ = float(best[i + e * n])
            if b_ > 0:
                ends[e] = [ends[e][0] + sgn * float(ux[i]) * b_, ends[e][1] + sgn * float(uy[i]) * b_]
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
