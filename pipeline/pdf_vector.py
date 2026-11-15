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

import copy
import ctypes
import math
import os
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
        obj_form = []  # draw-object id -> enclosing Form XObject instance (0 = page level, 1.. in walk order)
        form_ctr = [0]
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

        def do_path(obj, parent, form=0):
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
            obj_form.append(form)
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

        def walk(get_count, get_obj, parent, depth, form=0):
            for k in range(get_count()):
                obj = get_obj(k)
                t = R.FPDFPageObj_GetType(obj)
                counter[1] += 1
                if t == R.FPDF_PAGEOBJ_PATH:
                    do_path(obj, parent, form)
                elif t == R.FPDF_PAGEOBJ_IMAGE:
                    do_image(obj, parent)
                elif t == R.FPDF_PAGEOBJ_FORM and depth < 12:
                    m = _mat_mul(matrix(obj), parent)
                    form_ctr[0] += 1
                    walk(lambda o=obj: R.FPDFFormObj_CountObjects(o), lambda j, o=obj: R.FPDFFormObj_GetObject(o, j),
                         m, depth + 1, form_ctr[0])

        raw = page.raw
        walk(lambda: R.FPDFPage_CountObjects(raw), lambda j: R.FPDFPage_GetObject(raw, j), (1, 0, 0, 1, 0, 0), 0)
        words = _words_pdfium(page, disp)
        page.close()
    finally:
        doc.close()
    return {"W_pt": float(Wd), "H_pt": float(Hd), "rotate": rot, "paths": paths, "words": words,
            "image_cover": _cover(images, Wd, Hd), "reader": "pypdfium2", "n_objects": counter[1],
            "obj_form": obj_form}


def path_form(page: dict, p: dict) -> int:
    """Id of the Form XObject instance (block reference) that drew path p: 0 = page level, 1.. = form instances in
    drawing order (a nested form gets its own id). Kept per draw object in page["obj_form"] rather than as a key on
    every path dict (an 11th key doubles each dict's size on a 100k-path sheet). -1 when unknown (pdfminer reader)."""
    f = page.get("obj_form")
    o = p.get("obj")
    return f[o] if f is not None and isinstance(o, int) and 0 <= o < len(f) else -1


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
    """See the module docstring. page["n_white_over"] counts opaque white fills drawn after stroked linework (print
    driver wipeouts / text masks); with env PDF_WIPEOUTS=1 the linework they fully cover is dropped (drop_wiped)."""
    page = None
    if reader in ("auto", "pdfium"):
        try:
            page = _load_pdfium(pdf_path, page_index)
        except Exception:  # noqa: BLE001
            if reader == "pdfium":
                raise
    if page is None:
        page = _load_pdfminer(pdf_path, page_index)
    try:
        whites = _white_over(page["paths"])
        page["n_white_over"] = len(whites)
        import os
        if whites and os.environ.get("PDF_WIPEOUTS", "0") == "1":
            n0 = len(page["paths"])
            page["paths"] = drop_wiped(page["paths"], whites)
            page["n_wiped"] = n0 - len(page["paths"])
    except Exception:  # noqa: BLE001  optional clean-up: the page as read
        pass
    return page


WHITE_MIN = 0.98      # fill channels >= this: white (paper) fill
WHITE_MIN_AREA = 2.0  # pt^2: smaller white fills are glyph/hatch details, not masks


def _white_over(paths: list) -> list[int]:
    """Indexes of opaque white closed fills that are drawn after (higher draw-object id than) the first stroked,
    non-white path: wipeouts and text masks that hide earlier linework on the printed sheet."""
    first = None
    out = []
    for i, p in enumerate(paths):
        f, st = p.get("fill"), p.get("stroke")
        white = f is not None and not p.get("pattern") and min(f) >= WHITE_MIN and (st is None or min(st) >= WHITE_MIN)
        if white:
            if first is not None and p.get("obj", i) > first and len(p["pts"]) >= 3:
                x = [q[0] for q in p["pts"]]
                y = [q[1] for q in p["pts"]]
                if (max(x) - min(x)) * (max(y) - min(y)) >= WHITE_MIN_AREA:
                    out.append(i)
        elif st is not None and first is None:
            first = p.get("obj", i)
    return out


def drop_wiped(paths: list, whites: list[int] | None = None) -> list:
    """Paths minus the non-white linework that a LATER opaque white fill covers completely (what the printed sheet
    hides). Partly covered paths are kept whole (no trimming)."""
    import shapely
    whites = _white_over(paths) if whites is None else whites
    if not whites:
        return paths
    wpolys = []
    wobj = []
    for i in whites:
        g = shapely.make_valid(shapely.Polygon(paths[i]["pts"]))
        if not g.is_empty and g.area > 0:
            wpolys.append(g)
            wobj.append(paths[i].get("obj", i))
    if not wpolys:
        return paths
    wset = set(whites)
    cand = [i for i in range(len(paths)) if i not in wset and len(paths[i]["pts"]) >= 1]
    geoms = [shapely.LineString(paths[i]["pts"]) if len(paths[i]["pts"]) >= 2 else shapely.Point(paths[i]["pts"][0])
             for i in cand]
    tree = shapely.STRtree(wpolys)
    pi, wi = tree.query(geoms, predicate="covered_by")
    wobj = np.asarray(wobj)
    drop = set()
    for a, w in zip(pi.tolist(), wi.tolist()):
        k = cand[a]
        if wobj[w] > paths[k].get("obj", k):
            drop.add(k)
    return [p for i, p in enumerate(paths) if i not in drop] if drop else paths


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
WALL_MIN_M = 0.06   # with a known scale: thinner line pairs are linework (a 66-70 mm stud partition still counts)
WALL_MAX_M = 0.65   # with a known scale: wider pairs are not one wall
DOOR_GAP_MAX_M = 1.6   # widest door opening bridged inside a wall run (double doors are 1.6-1.8 m)
HEAVY_PAGE_FRAC = 0.5    # share of wall face length drawn in the heavy pen above which the sheet "draws walls heavy"
HATCHED_PAGE_FRAC = 0.6  # share of long-wall length hatched / poche-filled above which the sheet "hatches walls"
SIDE_BLOCK_MIN_M = 0.3  # side blocks (radiator / sill / bulkhead beside a wall) at least this deep
BLOCK_MIN_M = 0.45   # labelled blocks at least this deep and shorter than 5x their depth are not walls
PARTITION_MIN_M = 0.06  # thin partition pairs spanning between walls: face spacing range
PARTITION_MAX_M = 0.22
OUTLINE_MAX_M = 0.35  # heavy-pen outline pairs (layered partitions) are at most this thick
KNOWN_WALL_MM = (80, 100, 125, 150, 200, 250, 300, 400, 500)  # preferred thickness classes when the scale is known


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
    """Closed filled shapes as (polygon, grey, obj), even-odd holes per draw object, white fills skipped.
    Vectorised (all rings built and made valid in one shapely call); the per-path loop is the fallback."""
    try:
        return _fill_shapes_vec(page, area_box, page_area)
    except Exception:  # noqa: BLE001
        return _fill_shapes_loop(page, area_box, page_area)


def _fill_shapes_vec(page, area_box, page_area):
    import shapely
    groups = defaultdict(list)
    for p in page["paths"]:
        if p["fill"] is None or not p["closed"] or len(p["pts"]) < 3:
            continue
        groups[p["obj"]].append(p)
    if not groups:
        return []
    plist = [p for ps in groups.values() for p in ps]
    lens = np.fromiter((len(p["pts"]) for p in plist), int, len(plist))
    coords = np.array([q for p in plist for q in p["pts"]], float)
    rings = shapely.linearrings(coords, indices=np.repeat(np.arange(len(plist)), lens))
    valid = shapely.make_valid(shapely.polygons(rings))
    empty = shapely.is_empty(valid)
    geoms, gid, k = [], [], 0
    for oid, ps in groups.items():
        geom = None
        for _ in ps:
            pg = valid[k]
            if not empty[k]:
                geom = pg if geom is None else geom.symmetric_difference(pg)
            k += 1
        if geom is not None:
            geoms.append(geom)
            gid.append(oid)
    if not geoms:
        return []
    G = np.empty(len(geoms), dtype=object)
    G[:] = geoms
    keep = ~shapely.is_empty(G) & (shapely.area(G) >= 4)
    G, gid = G[keep], [o for o, k_ in zip(gid, keep) if k_]
    X = shapely.intersection(G, area_box)
    ok = ~shapely.is_empty(X) & (shapely.area(X) <= 0.2 * page_area)
    out = []
    for geom, oid, k_ in zip(X, gid, ok):
        if not k_:
            continue
        g = _grey(groups[oid][0]["fill"])
        for poly in getattr(geom, "geoms", [geom]):
            if poly.geom_type == "Polygon" and poly.area >= 4:
                out.append((poly, g, oid))
    return out


def _fill_shapes_loop(page, area_box, page_area):
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
DEADLINE = None  # time.monotonic() deadline set by the ingest job (whole-ingest budget); walls() never runs past it
LAST_WALLS = {}  # last walls() call: {"n", "s", "truncated", "budget_s"} (the ingest job copies it into its notes)


def walls(page: dict, budget_s: float | None = None, m_per_pt: float | None = None) -> list:
    """See _walls. budget_s (default env PDF_WALLS_BUDGET_S or WALLS_BUDGET_S): when the evidence stages run past
    it, the remaining stages are skipped and the walls found so far are returned with .truncated = True (also
    page["walls_truncated"]), instead of running for minutes on a dense MEP sheet.
    m_per_pt (optional, from the printed scale): line pairs closer than WALL_MIN_M or wider than WALL_MAX_M on
    the ground are not wall candidates, and thickness classes prefer the usual built sizes (KNOWN_WALL_MM)."""
    import os
    import time
    global _FLAT
    if budget_s is None:
        try:
            budget_s = float(os.environ.get("PDF_WALLS_BUDGET_S", WALLS_BUDGET_S))
        except ValueError:
            budget_s = WALLS_BUDGET_S
    t0 = time.monotonic()
    deadline = t0 + budget_s if budget_s and budget_s > 0 else None
    if DEADLINE is not None:
        deadline = DEADLINE if deadline is None else min(deadline, DEADLINE)
    _FLAT = None
    page.pop("_walls_unsettled", None)  # set again by this call only when parapet settling runs
    src = page
    if os.environ.get("PDF_PEN_LAYERS", "0") not in ("", "0"):  # research test: drop non-wall pen layers first
        try:
            from pipeline import pdf_layers
            src = pdf_layers.wall_page(page, int(os.environ["PDF_PEN_LAYERS"]))
        except Exception:  # noqa: BLE001
            src = page
    if src.get("paths"):
        _FLAT = (src["paths"], _flat(src))
    flag = [False]
    try:
        mpt = float(m_per_pt) if m_per_pt and m_per_pt > 0 else None
        out = _walls(src, deadline, flag, m_per_pt=mpt)
        # the cleanup always runs (deterministic output, DATA RULE; ~1-3 s on a 60k-path sheet)
        if os.environ.get("PDF_WALL_CLEAN", "1") != "0" and out:
            try:
                out = _clean_walls(page, out, m_per_pt=mpt)
            except Exception:  # noqa: BLE001  the detected walls as before
                pass
        out = WallList(out)
    finally:
        _FLAT = None
    if src is not page and "_walls_unsettled" in src:
        page["_walls_unsettled"] = src["_walls_unsettled"]
    out.truncated = flag[0]
    page["walls_truncated"] = flag[0]
    LAST_WALLS.clear()
    LAST_WALLS.update(n=len(out), s=round(time.monotonic() - t0, 2), truncated=flag[0],
                      budget_s=None if deadline is None else round(deadline - t0, 1))
    return out


def _over(deadline, flag):
    import time
    if deadline is not None and time.monotonic() > deadline:
        flag[0] = True
        return True
    return flag[0]


def _walls(page: dict, deadline=None, flag=None, m_per_pt: float | None = None) -> list:
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
        pairs_f, _ = _pairs(FE, max(0.5, WALL_MIN_M / m_per_pt) if m_per_pt else 0.5,
                            MAX_WALL_PT, min_ov=0.3)
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
        pairs, nb = _pairs(Sc, max(1.0, WALL_MIN_M / m_per_pt) if m_per_pt else 1.0,
                           MAX_WALL_PT)
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
            import shapely as _shp
            # both halves of every strip at once (one Polygon per half cost ~1 s on dense sheets)
            QC = np.array([np.asarray(r[0].exterior.coords)[:4] for r in oq], float).reshape(-1, 4, 2)
            CC0 = np.array([r[1] for r in oq], float).reshape(-1, 2)
            CC1 = np.array([r[2] for r in oq], float).reshape(-1, 2)
            HA = np.stack([QC[:, 0], QC[:, 1], CC1, CC0], 1)
            HB = np.stack([CC0, CC1, QC[:, 2], QC[:, 3]], 1)
            halves = _shp.polygons(np.stack([HA, HB], 1).reshape(-1, 4, 2))
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
            covl = np.zeros(len(oq))
            hits_of = defaultdict(list)
            if ltree is not None and len(oq):
                import shapely as _shp
                QQ = np.empty(len(oq), dtype=object)
                QQ[:] = [r[0] for r in oq]
                LA = np.empty(len(light), dtype=object)
                LA[:] = light
                nh = np.flatnonzero(~np.asarray(hatched, bool))  # only un-hatched strips are tested below
                qi_, li_ = ltree.query(QQ[nh])
                qi_ = nh[qi_]
                if len(qi_):
                    np.add.at(covl, qi_, _shp.area(_shp.intersection(QQ[qi_], LA[li_])))
                    for a_, b_ in zip(qi_.tolist(), li_.tolist()):
                        hits_of[a_].append(b_)
            keep = []
            for k_, (r, h_) in enumerate(zip(oq, hatched)):
                q = r[0]
                if not h_:
                    if ltree is not None:
                        hits = hits_of.get(k_, [])
                        cov = covl[k_]
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
    if any(w["style"] == "parapet" for w in out) and os.environ.get("PDF_PARAPET_SETTLE", "1") != "0":
        # pre-settle walls for pdf_openings' window reading (settle merges strips that carry window gaps); page-only
        # key, never written to the plan map
        page["_walls_unsettled"] = copy.deepcopy(out)
        try:
            out = _settle_parapets(out)
        except Exception:  # noqa: BLE001  the unsettled walls as before
            pass
    return out


def _wall_rect(c0, c1, t):
    (x0, y0), (x1, y1) = c0, c1
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / L * t / 2, (x1 - x0) / L * t / 2
    return [[round(float(x), 3), round(float(y), 3)] for x, y in
            ((x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny))]


PARAPET_PROBES = (0.2, 0.5, 0.8)
PARAPET_REACH = 40.0  # open-side rays reach this many median wall thicknesses (~10 m at 25 cm walls)  # positions along a candidate where the open-side test casts its rays


def _settle_parapets(out: list) -> list:
    """A thin 'parapet' candidate is a parapet only when it lies on the building's outer edge: on at least one side
    most perpendicular rays from it meet no other wall (open terrace / balcony / roof beyond). Enclosed on both sides
    it is an ordinary thin wall (partition): full height. Strips lying face to face along each other (the layers of
    one layered wall: structure, insulation, finish) become ONE wall over their total thickness, full height unless
    every layer is an open-edge parapet."""
    import shapely
    from shapely import STRtree
    if len(out) < 2:
        return out
    lines = np.empty(len(out), dtype=object)
    lines[:] = [shapely.LineString(w["centerline"]) for w in out]
    tree = STRtree(lines)
    allc = np.array([[*w["centerline"][0], *w["centerline"][1]] for w in out], float)
    span = float(max(np.ptp(allc[:, [0, 2]]), np.ptp(allc[:, [1, 3]]))) + 1.0
    tf = [w["thickness_pt"] for w in out if w["style"] != "parapet"]
    if tf:  # a room-sized reach (in units of the page's own wall thickness), not the whole sheet's other drawings
        span = min(span, PARAPET_REACH * float(np.median(tf)))
    para = [i for i, w in enumerate(out) if w["style"] == "parapet"]
    rays, owner = [], []
    for i in para:
        (x0, y0), (x1, y1) = out[i]["centerline"]
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / L, (x1 - x0) / L
        off = out[i]["thickness_pt"] / 2 + 0.5
        for f in PARAPET_PROBES:
            px, py = x0 + f * (x1 - x0), y0 + f * (y1 - y0)
            for sgn in (1, -1):
                rays.append(shapely.LineString([(px + sgn * nx * off, py + sgn * ny * off),
                                                (px + sgn * nx * span, py + sgn * ny * span)]))
                owner.append((i, sgn))
    ri, wi = tree.query(rays, predicate="intersects")
    hit = np.zeros(len(rays), bool)
    for r_, w_ in zip(ri.tolist(), wi.tolist()):
        if w_ != owner[r_][0]:
            hit[r_] = True
    enclosed = {}
    for k, (i, sgn) in enumerate(owner):
        enclosed.setdefault(i, {1: 0, -1: 0})[sgn] += int(hit[k])
    need = len(PARAPET_PROBES) // 2 + 1  # majority of the probes on that side
    infill = {i for i in para if _in_wall_gap(out, i, tree)}
    for i in para:
        if i in infill:
            continue  # window/door infill between two wall ends on the wall's axis: stays low, never a full wall
        if min(enclosed[i].values()) >= need:  # enclosed on both sides: an ordinary thin wall, full height
            out[i].pop("height_m", None)
            out[i]["style"] = "fill"
    # layers: merge each parapet-born strip into a parallel strip/wall it lies flat against (the longer one hosts)
    drop = set()
    tmax = max(w["thickness_pt"] for w in out)  # centreline tree: reach the far face of the thickest wall
    for _ in range(3 if os.environ.get("PDF_LAYER_MERGE", "1") != "0" else 0):
        changed = False
        for i in para:
            if i in drop or i in infill:
                continue
            for j in tree.query(lines[i].buffer(out[i]["thickness_pt"] / 2 + tmax / 2 + 2.0)).tolist():
                if j == i or j in drop:
                    continue
                h, g = (j, i) if _seg_len(out[j]) >= _seg_len(out[i]) else (i, j)  # host, guest
                if _merge_layer(out[h], out[g]):
                    drop.add(g)
                    lines[h] = shapely.LineString(out[h]["centerline"])
                    changed = True
                    if g == i:
                        break
        if not changed:
            break
    return [w for k, w in enumerate(out) if k not in drop]


def _in_wall_gap(out: list, i: int, tree) -> bool:
    """Strip i lies on the axis of a thicker parallel wall (inside its band laterally) and one of its ends meets
    that wall's end: a window frame / sill or door infill in a wall opening, not a wall."""
    w = out[i]
    (a0, a1), t = w["centerline"], w["thickness_pt"]
    u = np.subtract(a1, a0, dtype=float)
    La = float(np.hypot(*u)) or 1.0
    u /= La
    reach = max(v["thickness_pt"] for v in out) + 2.0
    for j in tree.query(shapely_buffer(w["centerline"], t / 2 + reach)).tolist():
        if j == i:
            continue
        v = out[j]
        tb = v["thickness_pt"]
        if v["style"] == "parapet" or tb < 1.5 * t:
            continue
        (b0, b1) = v["centerline"]
        ub = np.subtract(b1, b0, dtype=float)
        Lb = float(np.hypot(*ub)) or 1.0
        ub /= Lb
        if abs(float(u @ ub)) < 0.996:
            continue
        nb = np.array([-ub[1], ub[0]])
        mid = (np.asarray(a0, float) + np.asarray(a1, float)) / 2
        if abs(float((mid - np.asarray(b0, float)) @ nb)) > tb / 2:
            continue  # beside the wall (a layer), not on its axis
        gap_ends = min(math.dist(p, q) for p in (a0, a1) for q in (b0, b1))
        if gap_ends <= max(2.0, tb):
            return True
    return False


def shapely_buffer(line, r):
    import shapely
    return shapely.LineString(line).buffer(r)


def _seg_len(w) -> float:
    return math.dist(w["centerline"][0], w["centerline"][1])


def _merge_layer(v: dict, w: dict) -> bool:
    """Widen wall v (host) over strip w when w is parallel to v (< ~5 deg), touches v's face or lies inside it,
    and runs along it (overlap >= 60% of w, w at least a third of v's length). Host style: full wall unless both
    are parapets. True when merged."""
    (a0, a1), t = w["centerline"], w["thickness_pt"]
    (b0, b1), tb = v["centerline"], v["thickness_pt"]
    u = np.subtract(a1, a0, dtype=float)
    La = float(np.hypot(*u)) or 1.0
    u /= La
    ub = np.subtract(b1, b0, dtype=float)
    Lb = float(np.hypot(*ub)) or 1.0
    ub /= Lb
    if abs(float(u @ ub)) < 0.996 or La < 0.35 * Lb:
        return False
    nb = np.array([-ub[1], ub[0]])
    d = float(((np.asarray(a0, float) + np.asarray(a1, float)) / 2 - np.asarray(b0, float)) @ nb)
    gap = abs(d) - (t + tb) / 2
    if gap > max(1.0, 0.25 * min(t, tb)):
        return False  # apart: two walls
    s0, s1 = sorted(float((np.asarray(p, float) - np.asarray(b0, float)) @ ub) for p in (a0, a1))
    if min(s1, Lb) - max(s0, 0.0) < 0.6 * La:
        return False
    lo, hi = min(-tb / 2, d - t / 2), max(tb / 2, d + t / 2)
    mid = (lo + hi) / 2
    e0, e1 = 0.0, Lb  # along: the host's run (extending it over the guest's ends would bridge door gaps)
    c0 = np.asarray(b0, float) + e0 * ub + mid * nb
    c1 = np.asarray(b0, float) + e1 * ub + mid * nb
    v["centerline"] = [[round(float(c0[0]), 3), round(float(c0[1]), 3)], [round(float(c1[0]), 3), round(float(c1[1]), 3)]]
    v["thickness_pt"] = round(float(hi - lo), 3)
    v["polygon"] = _wall_rect(v["centerline"][0], v["centerline"][1], v["thickness_pt"])
    if v["style"] == "parapet" and w["style"] != "parapet":
        v["style"] = w["style"]
        v.pop("height_m", None)
    return True


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


# ---------------------------------------------------------------- post-detection cleanup (pen evidence + geometry)

# post-detection cleanup steps (env PDF_WALL_CLEAN_STEPS overrides): h hatched fill walls, o heavy-pen outline
# pairs, q thin partition pairs spanning between found walls (or a wall and a door swing), w words inside a pair, d duplicates, j join, m merge overlapping / face-to-face parallel walls, s snap to
# thickness classes, e close end gaps, c close L corners, f free short blocks, b labelled blocks, p short blocks
# lying beside a longer parallel wall (radiator / sill / bulkhead under a facade), v evidence, x on sheets that
# hatch their walls: drop unhatched candidates without two heavy-pen faces.
# Off by default: t thin linework by pen role (slow, drops real partitions), g bridge door gaps (would put a wall
# where no line is drawn: the door opening is left open, DATA RULE)
CLEAN_STEPS = "howdjmsefcbpvx"  # q (thin partitions spanning walls) off: not yet finding its targets
THIN_LINEWORK_FRAC = 0.2   # thinner than this x the page's length-weighted median wall: linework unless wall pen
THICK_CLASSES_MAX = 6      # at most this many wall thickness classes per page
THICK_CLASS_GAP = 1.25     # neighbouring classes differ by at least this ratio
THICK_CLASS_TOL = 1.2      # a wall within this ratio of a class belongs to it (props.thickness_class)
THICK_KNOWN_TOL = 1.08     # a class takes the nearest standard size (KNOWN_WALL_MM) only within this ratio
THICK_SNAP_TOL = 1.1       # ... and its drawn thickness is snapped to the class value only within this ratio
WALLISH_ROLES = ("wall", "wall_fill", "hatch", "column")
NONWALL_ROLES = ("other", "background", "door", "fixture", "furniture", "text", "dimension", "grid", "stair",
                 "window", "mep", "titleblock")


def _rect_of(c0, c1, t):
    (x0, y0), (x1, y1) = c0, c1
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / L * t / 2, (x1 - x0) / L * t / 2
    return [[round(float(x), 3), round(float(y), 3)] for x, y in
            ((x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny))]


def _set_geom(w, c0, c1, t):
    w["centerline"] = [[round(float(c0[0]), 3), round(float(c0[1]), 3)], [round(float(c1[0]), 3), round(float(c1[1]), 3)]]
    w["thickness_pt"] = round(float(t), 3)
    w["polygon"] = _rect_of(c0, c1, t)


def _pen_evidence(page, ws):
    """Per wall: (wall-pen stroke ink, non-wall-pen stroke ink) of the path segments lying inside its rectangle,
    from pdf_layers pen roles. None when the page has no confident wall pens."""
    import shapely
    from pipeline import pdf_layers
    Ls = pdf_layers.layers(page)
    if not Ls or sum(L["ink"] for L in Ls if L["role"] in ("wall", "wall_fill")) < 0.05:
        return None
    n = len(page.get("paths") or [])
    code = np.zeros(n, np.int8)  # 0 unknown / fill-only, 1 wall pen, 2 non-wall pen
    for L in Ls:
        if L["sig"].get("stroke") is None:
            continue
        if L["role"] in WALLISH_ROLES:
            code[L["paths"]] = 1
        elif L["role"] in NONWALL_ROLES:
            code[L["paths"]] = 2
    F = _flat(page)
    seg, sp = F["seg"], F["sp"]
    if not len(seg):
        return None
    mx, my = (seg[:, 0] + seg[:, 2]) / 2, (seg[:, 1] + seg[:, 3]) / 2
    Lg = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1])
    cs = code[sp]
    polys = shapely.buffer(shapely.polygons([w["polygon"] for w in ws]), 0.6)
    tree = shapely.STRtree(polys)
    pi, si = tree.query(shapely.points(np.column_stack([mx, my])), predicate="within")
    # query returns (input idx, tree idx): input = segment midpoints, tree = wall polygons
    ev = np.zeros((len(ws), 3))
    np.add.at(ev, (si, cs[pi]), Lg[pi])
    return ev


def thickness_classes(ws, m_per_pt: float | None = None) -> list:
    """Dominant wall thicknesses (pt, ascending) of a page: peaks of the length-weighted log-thickness density,
    strongest first, kept when at least THICK_CLASS_GAP (ratio) from every stronger one; at most
    THICK_CLASSES_MAX, and only peaks carrying >= 3 % of the wall length. With m_per_pt each peak is replaced by
    the nearest KNOWN_WALL_MM size when that lies within THICK_CLASS_TOL of it (the built size, not the drawn one)."""
    T = np.array([w["thickness_pt"] for w in ws], float)
    Lc = np.array([math.dist(*w["centerline"]) for w in ws], float)
    ok = (T > 0) & (Lc > 0)
    if not ok.any():
        return []
    lt, wt = np.log(T[ok]), Lc[ok]
    grid = np.arange(lt.min() - 0.1, lt.max() + 0.1, 0.01)
    bw = 0.05
    dens = (wt[None, :] * np.exp(-0.5 * ((grid[:, None] - lt[None, :]) / bw) ** 2)).sum(1)
    pk = [i for i in range(len(grid)) if dens[i] > 0 and (i == 0 or dens[i] >= dens[i - 1])
          and (i == len(grid) - 1 or dens[i] > dens[i + 1])]
    pk.sort(key=lambda i: -dens[i])
    tot = float(wt.sum())
    out = []
    for i in pk:
        g = grid[i]
        near = np.abs(lt - g) <= math.log(THICK_CLASS_TOL)
        if wt[near].sum() < 0.03 * tot:
            continue
        if any(abs(g - o) < math.log(THICK_CLASS_GAP) for o in out):
            continue
        out.append(g)
        if len(out) >= THICK_CLASSES_MAX:
            break
    res = []
    for g in sorted(out):  # class value: length-weighted median of its members
        near = np.abs(lt - g) <= math.log(THICK_CLASS_TOL)
        o = np.argsort(lt[near])
        cw = np.cumsum(wt[near][o])
        tc = float(np.exp(lt[near][o][np.searchsorted(cw, cw[-1] / 2)]))
        if m_per_pt:
            kn = min(KNOWN_WALL_MM, key=lambda mm: abs(math.log(mm / 1000 / m_per_pt / tc)))
            if abs(math.log(kn / 1000 / m_per_pt / tc)) <= math.log(THICK_KNOWN_TOL):
                tc = kn / 1000 / m_per_pt
        res.append(tc)
    return sorted(set(res))


def _hatched_fill_walls(page, ws, m_per_pt: float | None = None) -> list:
    """Extra walls the pair search misses: a filled thin rectangle (any fill colour, white poche included) whose
    two long sides are both drawn as stroked lines and whose inside carries hatch strokes (slanted to its axis).
    A text mask has no stroked sides, a window pane / door leaf no hatch. Returns wall dicts (style "double")
    not already covered by ws."""
    import shapely
    paths = page.get("paths") or []
    if not paths:
        return []
    F = _flat(page)
    seg, sp = F["seg"], F["sp"]
    cand = np.flatnonzero(F["fill"] & F["closed"] & ((F["npts"] == 4) | (F["npts"] == 5)) & (F["n_curves"] == 0))
    if not len(cand) or not len(seg):
        return []
    tmin = max(1.5, WALL_MIN_M / m_per_pt) if m_per_pt else 1.5
    tmax = min(MAX_WALL_PT, WALL_MAX_M / m_per_pt) if m_per_pt else MAX_WALL_PT
    bb = F["bbox"][cand]  # cheap pre-filter on the box: thin side in range (rotated rects pass via the diagonal)
    bw, bh = bb[:, 2] - bb[:, 0], bb[:, 3] - bb[:, 1]
    cand = cand[(np.maximum(bw, bh) >= 2.5 * tmin) & (np.minimum(bw, bh) <= np.hypot(tmax, tmax))]
    if not len(cand):
        return []
    P4 = np.array([paths[i]["pts"][:4] for i in cand.tolist()], float)  # (n, 4, 2)
    a, b = P4[:, 1] - P4[:, 0], P4[:, 2] - P4[:, 1]
    la, lb = np.hypot(a[:, 0], a[:, 1]), np.hypot(b[:, 0], b[:, 1])
    lc = np.hypot(*(P4[:, 3] - P4[:, 2]).T)
    tt, LL = np.minimum(la, lb), np.maximum(la, lb)
    with np.errstate(invalid="ignore", divide="ignore"):
        good = ((tt > 0) & (np.abs((a * b).sum(1)) <= 0.03 * la * lb) & (lc >= 0.97 * la)
                & (tt >= tmin) & (tt <= tmax) & (LL >= 2.5 * tt))
    rects = [(int(cand[k]), P4[k], float(tt[k]), float(LL[k]), bool(la[k] >= lb[k])) for k in np.flatnonzero(good)]
    if not rects:
        return []
    st = ~np.isnan(F["grey"][sp]) & (F["grey"][sp] < 0.8) & ~F["arc"][sp] & ~F["fill"][sp]
    st |= ~np.isnan(F["grey"][sp]) & (F["grey"][sp] < 0.8) & ~F["arc"][sp] & ~np.isin(sp, [r[0] for r in rects])
    S, Wd = seg[st], F["width"][sp[st]]
    if not len(S):
        return []
    Ls = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    ok = Ls > 0.2
    S, Ls, Wd = S[ok], Ls[ok], Wd[ok]
    o_ = np.argsort(Wd)
    cw_ = np.cumsum(Ls[o_])
    w_med = float(Wd[o_][np.searchsorted(cw_, cw_[-1] / 2)]) if len(o_) else 0.0
    lines = shapely.linestrings(S.reshape(-1, 2, 2))
    tree = shapely.STRtree(lines)
    have = shapely.STRtree(shapely.polygons([w["polygon"] for w in ws])) if ws else None
    have_p = shapely.polygons([w["polygon"] for w in ws]) if ws else None
    # vectorised hatch pre-check over every (rect, nearby segment) pair: most fills (text masks, cells) carry no
    # dense one-direction slanted strokes and are dropped before the per-rect edge test
    RP = np.array([r[1] for r in rects], float)
    RT = np.array([r[2] for r in rects]); RL = np.array([r[3] for r in rects])
    RU = np.where(np.array([r[4] for r in rects])[:, None], RP[:, 1] - RP[:, 0], RP[:, 2] - RP[:, 1])
    RU = RU / np.hypot(RU[:, 0], RU[:, 1])[:, None]
    RN = np.column_stack([-RU[:, 1], RU[:, 0]])
    RC = RP.mean(1)
    qr, qs = tree.query(shapely.polygons(RP), predicate="intersects")
    if not len(qr):
        return []
    dv = S[qs, 2:4] - S[qs, 0:2]
    cosu = np.abs((dv * RU[qr]).sum(1)) / np.maximum(Ls[qs], 1e-9)
    mid = (S[qs, 0:2] + S[qs, 2:4]) / 2 - RC[qr]
    ins = (np.abs((mid * RN[qr]).sum(1)) < RT[qr] / 2 + 0.2) & (np.abs((mid * RU[qr]).sum(1)) < RL[qr] / 2 + 0.2)
    sl = ins & (cosu > math.cos(math.radians(70))) & (cosu < math.cos(math.radians(20)))
    sg = np.sign((dv * RU[qr]).sum(1) * (dv * RN[qr]).sum(1))
    npos = np.bincount(qr[sl & (sg > 0)], minlength=len(rects))
    nneg = np.bincount(qr[sl & (sg < 0)], minlength=len(rects))
    nsl = npos + nneg
    passing = np.flatnonzero((nsl >= np.maximum(3, (RL / RT).astype(int))) & (np.maximum(npos, nneg) >= 0.8 * nsl))
    out = []
    for i, P, t, L, a_long in (rects[k] for k in passing.tolist()):
        c = P.mean(0)
        u = (P[1] - P[0]) if a_long else (P[2] - P[1])
        u = u / np.hypot(*u)
        n = np.array([-u[1], u[0]])
        poly = shapely.Polygon(P)
        q = tree.query(poly.buffer(0.5))
        if len(q) < 4:
            continue
        Q = S[q]
        d0 = (Q[:, 0:2] - c) @ n
        d1 = (Q[:, 2:4] - c) @ n
        s0 = (Q[:, 0:2] - c) @ u
        s1 = (Q[:, 2:4] - c) @ u
        lq = Ls[q]
        par = np.abs((Q[:, 2:4] - Q[:, 0:2]) @ n) < 0.035 * lq
        cov, ew = [], []
        for side in (1, -1):
            e = par & (np.abs(d0 - side * t / 2) < 0.4) & (np.abs(d1 - side * t / 2) < 0.4)
            ew += Wd[q][e].tolist()
            iv = sorted((max(-L / 2, min(a_, b_)), min(L / 2, max(a_, b_))) for a_, b_ in zip(s0[e], s1[e]))
            tot, hi = 0.0, -L / 2
            for lo_, hi_ in iv:
                if hi_ > hi:
                    tot += hi_ - max(lo_, hi)
                    hi = hi_
            cov.append(tot / L)
        if min(cov) < 0.7 or not ew or float(np.mean(ew)) < 1.25 * w_med:  # wall outlines: a heavier pen than
            continue                                                        # the page's typical (furniture) line
        cosu = np.abs((Q[:, 2:4] - Q[:, 0:2]) @ u) / np.maximum(lq, 1e-9)
        slant = (cosu > math.cos(math.radians(70))) & (cosu < math.cos(math.radians(20)))
        mid = (Q[:, 0:2] + Q[:, 2:4]) / 2
        inside = (np.abs((mid - c) @ n) < t / 2 + 0.2) & (np.abs((mid - c) @ u) < L / 2 + 0.2)
        h = slant & inside
        if int(h.sum()) < max(3, int(L / t)):  # poche hatch: dense parallel slants (one per < thickness)
            continue
        sg = np.sign(((Q[h, 2:4] - Q[h, 0:2]) @ u) * ((Q[h, 2:4] - Q[h, 0:2]) @ n))
        if max((sg > 0).sum(), (sg < 0).sum()) < 0.8 * len(sg):  # one hatch direction; crossed boxes (lockers,
            continue                                               # shafts, furniture) have both diagonals
        if have is not None:
            hq = have.query(poly)
            if len(hq) and shapely.area(shapely.intersection(have_p[hq], poly)).sum() >= 0.6 * poly.area:
                continue
        c0, c1 = c - u * L / 2, c + u * L / 2
        w = {"style": "double"}
        _set_geom(w, c0, c1, t)
        out.append(w)
    return out


def _door_swings(page, m_per_pt=None):
    """Bounding boxes of drawn door swings: arcs / curved paths, or open polylines of >= 5 points (exporters
    flatten arcs) with a roughly square box of door size (0.5-1.3 m with a scale, else 10-45 pt)."""
    F = _flat(page)
    bb = F["bbox"]
    w_, h_ = bb[:, 2] - bb[:, 0], bb[:, 3] - bb[:, 1]
    sz = np.nan_to_num(np.maximum(w_, h_))
    sq = np.nan_to_num(np.minimum(w_, h_)) >= 0.6 * sz
    lo, hi = (0.5 / m_per_pt, 1.3 / m_per_pt) if m_per_pt else (10.0, 45.0)
    k = ((F["arc"] | (F["n_curves"] > 0) | ((F["npts"] >= 5) & ~F["closed"])) & sq & (sz >= lo) & (sz <= hi)
         & ~F["fill"])
    return bb[k]


def _bridging_partitions(page, ws, m_per_pt: float | None = None) -> list:
    """Thin partitions drawn as two parallel lines (any pen, hatched or not) that the main search missed: a pair
    PARTITION_MIN_M..PARTITION_MAX_M apart (with a scale; else 1.5..8 pt) is a wall when BOTH its ends meet a
    found wall, or one end meets a wall and the other a door swing (arc) — a partition spans between walls.
    Benches, blocks and furniture outlines do not connect wall to wall. Skips pairs already covered, pairs with
    text inside, and runs of identical parallel pieces. Both faces are drawn (measured)."""
    import shapely
    if not ws:
        return []
    try:
        box = _frame_and_titleblock(page)
    except Exception:  # noqa: BLE001
        box = (-1e9, -1e9, 1e9, 1e9)
    S = _merge_collinear(_raw_segments(page, box))
    S = S[S[:, 6] >= 6.0] if len(S) else S
    if len(S) < 2:
        return []
    dmin = PARTITION_MIN_M / m_per_pt if m_per_pt else 1.5
    dmax = PARTITION_MAX_M / m_per_pt if m_per_pt else 8.0
    pairs, _ = _pairs(S, dmin, dmax)
    if not pairs:
        return []
    bad = _series(S, pairs)
    pairs = [r for r in pairs if r[0] not in bad and r[1] not in bad]
    if not pairs:
        return []
    Q, C0, C1 = _quads(S, pairs)
    ok = shapely.is_valid(Q) & (shapely.area(Q) > 0)
    have = shapely.polygons([w["polygon"] for w in ws])
    ht = shapely.STRtree(have)
    qa, qb = ht.query(Q, predicate="intersects")
    cov = np.zeros(len(Q))
    if len(qa):
        np.add.at(cov, qa, shapely.area(shapely.intersection(Q[qa], have[qb])))
    ok &= cov < 0.5 * shapely.area(Q)
    words = page.get("words") or []
    if words:
        WB = np.array([w_["bbox"] for w_ in words], float).reshape(-1, 4)
        wt = shapely.STRtree(shapely.box(WB[:, 0], WB[:, 1], WB[:, 2], WB[:, 3]))
        a_, _ = wt.query(Q, predicate="intersects")
        ok[np.unique(a_)] = False
    ab = _door_swings(page, m_per_pt)
    at = shapely.STRtree(shapely.box(ab[:, 0], ab[:, 1], ab[:, 2], ab[:, 3])) if len(ab) else None
    anchors = [w for w in ws if w["style"] != "parapet"]  # roof / terrace edges do not anchor partitions
    if not anchors:
        return []
    ht = shapely.STRtree(shapely.polygons([w["polygon"] for w in anchors]))
    gmax = DOOR_GAP_MAX_M / m_per_pt if m_per_pt else 45.0
    # pieces of one partition line: same axis (angle, offset), similar thickness; ordered along the axis
    groups = defaultdict(list)
    for k in np.flatnonzero(ok).tolist():
        t = pairs[k][2]
        c0, c1 = np.array(C0[k], float), np.array(C1[k], float)
        L = float(np.hypot(*(c1 - c0)))
        if L < 2 * t:
            continue
        u = (c1 - c0) / L
        if u[0] < 0 or (abs(u[0]) < 1e-9 and u[1] < 0):
            u, c0, c1 = -u, c1, c0
        ang = math.atan2(u[1], u[0])
        off = float(-u[1] * c0[0] + u[0] * c0[1])
        s0, s1 = float(u @ c0), float(u @ c1)
        groups[(round(ang / math.radians(1.5)), round(off / 1.0))].append((s0, s1, t, c0, c1, u))

    def meets(pt, u, sg, t):
        probe = shapely.Point(*(pt + sg * u * 0.5)).buffer(t / 2 + 0.6)
        wall = bool(len(ht.query(probe, predicate="intersects")))
        door = at is not None and bool(len(at.query(probe, predicate="intersects")))
        return wall, door

    def touches_wall(c0, c1, t):
        return bool(len(ht.query(shapely.LineString([c0, c1]).buffer(t / 2 + 0.6), predicate="intersects")))
    out = []
    for key in sorted(groups):
        pcs = sorted(groups[key], key=lambda r: r[0])
        runs, cur = [], [pcs[0]]
        cur_doors = set()
        for r in pcs[1:]:
            prev = cur[-1]
            gap = r[0] - prev[1]
            tsim = min(r[2], prev[2]) >= 0.7 * max(r[2], prev[2])
            door_gap = False
            if tsim and 0 < gap <= gmax and at is not None:
                gp = shapely.LineString([prev[4], r[3]]).buffer(max(r[2], prev[2]) / 2 + gap / 2)
                door_gap = bool(len(at.query(gp, predicate="intersects")))
            if tsim and (gap <= 1.0 or door_gap):
                cur.append(r)
                if door_gap:
                    cur_doors.add(id(cur))
            else:
                runs.append(cur)
                cur = [r]
        runs.append(cur)
        for run in runs:
            a0, a1 = run[0], run[-1]
            m0 = meets(a0[3], a0[5], -1.0, a0[2])
            m1 = meets(a1[4], a1[5], 1.0, a1[2])
            # a partition holding doors: a door swing at a run end or inside the run, both run ends at a wall or
            # a door, and the run touching a found wall somewhere (its ends or a T into its side)
            has_door = m0[1] or m1[1] or id(run) in cur_doors
            ends_ok = (m0[0] or m0[1]) and (m1[0] or m1[1])
            walled = m0[0] or m1[0] or any(touches_wall(r[3], r[4], r[2]) for r in run)
            # door swings are often not drawn as one path (flattened into separate strokes): a run whose EVERY
            # piece touches a found wall (end on a wall or a wall T-ing into it, e.g. cubicle dividers) also counts
            every = all(touches_wall(r[3], r[4], r[2]) for r in run) and len(run) >= 2
            if (has_door and ends_ok and walled) or every:
                for s0_, s1_, t, c0, c1, u in run:  # only the drawn stretches; door gaps stay open
                    w = {"style": "double"}
                    _set_geom(w, c0, c1, t)
                    out.append(w)
    return out


def _heavy_outline_walls(page, ws, m_per_pt: float | None = None) -> list:
    """Layered walls the pair search misses: the two outer faces drawn with a heavier pen than the page's typical
    line, with thin layer / stud lines between them (the nearest-partner pairing stops at the first inner line).
    Pairs only the heavy-pen lines, at wall spacing, and keeps pairs not already covered by ws and with no text
    inside. Returns wall dicts (style "double")."""
    import shapely
    try:
        box = _frame_and_titleblock(page)  # the drawing area, as _walls uses it (no title block / legend rows)
    except Exception:  # noqa: BLE001
        box = (-1e9, -1e9, 1e9, 1e9)
    Rw = _raw_segments(page, box)
    if len(Rw) < 2:
        return []
    Lr = np.hypot(Rw[:, 2] - Rw[:, 0], Rw[:, 3] - Rw[:, 1])
    o = np.argsort(Rw[:, 4])
    cw = np.cumsum(Lr[o])
    w_med = float(Rw[o, 4][np.searchsorted(cw, cw[-1] / 2)])
    S = _merge_collinear(Rw[(Rw[:, 4] >= 1.25 * w_med) & (Rw[:, 4] > 0)])  # heavy pens only, then join pieces
    if len(S) < 2:
        return []
    H = S[S[:, 6] >= 6.0]
    if len(H) < 2:
        return []
    dmin = max(1.5, WALL_MIN_M / m_per_pt) if m_per_pt else 1.5
    # layered partitions only (thick outer walls are found by the main search): <= OUTLINE_MAX_M
    dmax = min(MAX_WALL_PT, OUTLINE_MAX_M / m_per_pt) if m_per_pt else 0.25 * MAX_WALL_PT
    pairs, _ = _pairs(H, dmin, dmax)
    if not pairs:
        return []
    bad = _series(H, pairs)  # stair treads / lockers / slats: runs of equally spaced lines
    pairs = [r for r in pairs if r[0] not in bad and r[1] not in bad]
    if not pairs:
        return []
    Q, C0, C1 = _quads(H, pairs)
    ok = shapely.is_valid(Q) & (shapely.area(Q) > 0)
    if ws:
        have = shapely.polygons([w["polygon"] for w in ws])
        ht = shapely.STRtree(have)
        qa, qb = ht.query(Q, predicate="intersects")
        cov = np.zeros(len(Q))
        if len(qa):
            np.add.at(cov, qa, shapely.area(shapely.intersection(Q[qa], have[qb])))
        ok &= cov < 0.5 * shapely.area(Q)
    words = page.get("words") or []
    if words:
        WB = np.array([w_["bbox"] for w_ in words], float).reshape(-1, 4)
        wt = shapely.STRtree(shapely.box(WB[:, 0], WB[:, 1], WB[:, 2], WB[:, 3]))
        qa, _ = wt.query(Q, predicate="intersects")
        ok[np.unique(qa)] = False
    ks = [k for k in np.flatnonzero(ok).tolist() if math.dist(C0[k], C1[k]) >= 2 * pairs[k][2]]
    if not ks:
        return []
    # a run of near-identical parallel pieces side by side is a stair / slatted bench / shelving, not walls
    A = np.array([[*C0[k], *C1[k]] for k in ks], float)
    L = np.hypot(A[:, 2] - A[:, 0], A[:, 3] - A[:, 1])
    U = (A[:, 2:4] - A[:, 0:2]) / L[:, None]
    M = (A[:, 0:2] + A[:, 2:4]) / 2
    sib = np.zeros(len(ks), int)
    for a, b in _near_pairs(M, float(L.max()) * 2):
        if abs(U[a, 0] * U[b, 1] - U[a, 1] * U[b, 0]) > 0.035 or abs(L[a] - L[b]) > 0.1 * max(L[a], L[b]):
            continue
        d = M[b] - M[a]
        along = abs(d @ U[a])
        perp = abs(d[0] * U[a, 1] - d[1] * U[a, 0])
        if along < 0.2 * L[a] and perp < 2 * L[a]:
            sib[a] += 1
            sib[b] += 1
    out = []
    for n_, k in enumerate(ks):
        if sib[n_] >= 3:
            continue
        w = {"style": "double"}
        _set_geom(w, C0[k], C1[k], pairs[k][2])
        out.append(w)
    return out


def _clean_walls(page, out, m_per_pt: float | None = None):
    """General post-detection cleanup of walls() output (env PDF_WALL_CLEAN=0 turns it off):
    (1) drop thin walls whose own edges are drawn only by non-wall pens (furniture, detail, hatch linework);
    (2) drop pieces lying inside another wall (duplicates); (3) join collinear touching / overlapping pieces of
    similar thickness into one run; (4) snap thickness to the page's dominant classes; (5) close small gaps
    between a free end and a crossing wall (corners / T-junctions)."""
    import shapely
    steps = os.environ.get("PDF_WALL_CLEAN_STEPS", CLEAN_STEPS)
    if len(out) < 3:
        return out
    rect = [w for w in out if len(w["polygon"]) == 4 and not w.get("holes")]
    other = [w for w in out if not (len(w["polygon"]) == 4 and not w.get("holes"))]
    ws = [dict(w) for w in rect]
    if not ws:
        return out
    if "h" in steps:
        try:
            ws += _hatched_fill_walls(page, ws, m_per_pt)
        except Exception:  # noqa: BLE001
            pass
    if "o" in steps:
        try:
            ws += _heavy_outline_walls(page, ws, m_per_pt)
        except Exception:  # noqa: BLE001
            pass
    if "q" in steps:
        try:
            ws += _bridging_partitions(page, ws, m_per_pt)
        except Exception:  # noqa: BLE001
            pass
    T = np.array([w["thickness_pt"] for w in ws], float)
    Lc = np.array([math.dist(*w["centerline"]) for w in ws], float)
    o = np.argsort(T)
    cw = np.cumsum(Lc[o])
    t_med = float(T[o][np.searchsorted(cw, cw[-1] / 2)])
    # (1) thin linework walls
    ev = None
    if "t" in steps:
        try:
            ev = _pen_evidence(page, ws)
        except Exception:  # noqa: BLE001
            ev = None
    if ev is not None and "t" in steps:
        keep = []
        for i, w in enumerate(ws):
            wl, nw = ev[i, 1], ev[i, 2]
            strokes = wl + nw
            # very thin (well under the page's typical wall) and drawn by non-wall pens only: hatch / frame /
            # skylight / furniture edge lines, not a wall (real partitions keep wall-pen or fill evidence)
            if T[i] < THIN_LINEWORK_FRAC * t_med and strokes >= 1.0 * Lc[i] and wl < 0.05 * strokes:
                continue
            keep.append(i)
        ws = [ws[i] for i in keep]
    if "w" in steps and page.get("words"):
        # a double-line pair whose gap holds room text (two or more words wholly inside) spans a room, not a wall:
        # a wall face paired with a thin per-room line / furniture edge across the room
        import shapely
        WB = np.array([w_["bbox"] for w_ in page["words"]], float).reshape(-1, 4)
        wt = shapely.STRtree(shapely.box(WB[:, 0], WB[:, 1], WB[:, 2], WB[:, 3]))
        dbl = [i for i, w in enumerate(ws) if w["style"] == "double"]
        if dbl:
            inner = shapely.buffer(shapely.polygons([ws[i]["polygon"] for i in dbl]), -0.5)
            pi_, wi_ = wt.query(inner, predicate="contains")
            nin = np.bincount(pi_, minlength=len(dbl))
            drop = {dbl[k] for k in np.flatnonzero(nin >= 2)}
            ws = [w for i, w in enumerate(ws) if i not in drop]
    if len(ws) < 2:
        return other + ws

    def geo(w):
        (x0, y0), (x1, y1) = w["centerline"]
        L = math.hypot(x1 - x0, y1 - y0) or 1e-9
        return x0, y0, x1, y1, (x1 - x0) / L, (y1 - y0) / L, L, w["thickness_pt"]
    # (2) duplicates: a piece whose centre line lies >= 85 % inside a wider-or-equal / longer wall
    order = sorted(range(len(ws)), key=lambda i: (-ws[i]["thickness_pt"], -math.dist(*ws[i]["centerline"])))
    kept, kpolys = [], []
    tree = None
    lines = [shapely.LineString(ws[i]["centerline"]) for i in order]
    allp = shapely.polygons([ws[i]["polygon"] for i in order])
    allp = shapely.buffer(allp, 0.5)
    tree = shapely.STRtree(allp)
    dead = np.zeros(len(order), bool)
    for k, i in enumerate(order):
        ln = lines[k]
        if ln.length <= 0:
            dead[k] = True
            continue
        if "d" not in steps:
            continue
        for j in tree.query(ln).tolist():
            if j == k or dead[j] or j > k:  # only earlier (wider / longer) survivors can absorb this piece
                continue
            if ln.intersection(allp[j]).length >= 0.85 * ln.length:
                dead[k] = True
                break
    ws = [ws[i] for k, i in enumerate(order) if not dead[k]]
    # (3) join collinear runs: angle < 1.5 deg, lateral offset < half the thinner, thickness within 30 %,
    #     axial gap <= the thinner thickness (a door opening is much wider, so openings stay open)
    changed = "j" in steps
    while changed:
        changed = False
        G = [geo(w) for w in ws]
        rects = shapely.buffer(shapely.polygons([w["polygon"] for w in ws]), [max(0.5, g[7]) for g in G])
        tr = shapely.STRtree(rects)
        qa, qb = tr.query(rects)
        used = np.zeros(len(ws), bool)
        new = []
        for a, b in zip(qa.tolist(), qb.tolist()):
            if a >= b or used[a] or used[b]:
                continue
            A, B = G[a], G[b]
            if ws[a]["style"] != ws[b]["style"] and "parapet" in (ws[a]["style"], ws[b]["style"]):
                continue
            if abs(A[4] * B[5] - A[5] * B[4]) > math.sin(math.radians(1.5)):
                continue
            tmin, tmax = min(A[7], B[7]), max(A[7], B[7])
            if tmin < 0.7 * tmax:
                continue
            ux, uy = (A[4], A[5]) if A[4] * B[4] + A[5] * B[5] >= 0 else (A[4], A[5])
            nx, ny = -uy, ux
            off = abs((B[0] - A[0]) * nx + (B[1] - A[1]) * ny)
            off2 = abs((B[2] - A[0]) * nx + (B[3] - A[1]) * ny)
            if max(off, off2) > 0.5 * tmin:
                continue
            pa = sorted([0.0, A[6]])
            pb = sorted([(B[0] - A[0]) * ux + (B[1] - A[1]) * uy, (B[2] - A[0]) * ux + (B[3] - A[1]) * uy])
            gap = max(pb[0] - pa[1], pa[0] - pb[1])
            if gap > tmin:
                continue
            lo, hi = min(pa[0], pb[0]), max(pa[1], pb[1])
            t = (A[7] * A[6] + B[7] * B[6]) / (A[6] + B[6])
            ob = ((B[0] + B[2]) / 2 - A[0]) * nx + ((B[1] + B[3]) / 2 - A[1]) * ny
            o_ = ob * B[6] / (A[6] + B[6])
            c0 = (A[0] + ux * lo + nx * o_, A[1] + uy * lo + ny * o_)
            c1 = (A[0] + ux * hi + nx * o_, A[1] + uy * hi + ny * o_)
            w = dict(ws[a] if A[6] >= B[6] else ws[b])
            _set_geom(w, c0, c1, t)
            new.append(w)
            used[a] = used[b] = True
            changed = True
        ws = [w for i, w in enumerate(ws) if not used[i]] + new
    if "g" in steps and len(ws) > 1:
        try:
            ws = _bridge_door_gaps(page, ws, m_per_pt)
        except Exception:  # noqa: BLE001
            pass
    if "m" in steps and len(ws) > 1:
        ws = _merge_overlaps(ws)
    # (4) thickness classes: at most THICK_CLASSES_MAX length-weighted peaks at least THICK_CLASS_GAP apart
    #     (ratio); every wall within THICK_CLASS_TOL of a class is snapped to it and tagged
    #     props.thickness_class (0 = thinnest); walls fitting no class keep their own thickness (class None)
    classes = thickness_classes(ws, m_per_pt)
    for w in ws:
        t = w["thickness_pt"]
        k = min(range(len(classes)), key=lambda c: abs(math.log(t / classes[c]))) if classes and t > 0 else None
        if k is not None and abs(math.log(t / classes[k])) <= math.log(THICK_CLASS_TOL) and "s" in steps:
            if abs(t - classes[k]) > 1e-3 and abs(math.log(t / classes[k])) <= math.log(THICK_SNAP_TOL):
                _set_geom(w, w["centerline"][0], w["centerline"][1], classes[k])
            w["props"] = {**(w.get("props") or {}), "thickness_class": k, "thickness_class_pt": round(classes[k], 3)}
        else:
            w["props"] = {**(w.get("props") or {}), "thickness_class": None}
    if m_per_pt:  # a double-line "wall" wider than any built wall: two faces of different walls / a corridor
        ws = [w for w in ws if w["style"] != "double" or w["thickness_pt"] * m_per_pt <= WALL_MAX_M]
    if m_per_pt and "s" in steps:  # fits no class and shorter than 1 m: a fragment, not a wall
        ws = [w for w in ws if w["props"].get("thickness_class") is not None
              or math.dist(*w["centerline"]) * m_per_pt >= 1.0]
    # (5) close small gaps (DATA RULE: measured geometry only): a free end (its centre point touches no other
    #     wall) is extended along its axis to the face of the crossing (>= 30 deg) wall it runs into, when that
    #     face (or the end of a collinear wall) is at most 1.5 x the end's thickness away AND the drawn lines of one of its faces continue over
    #     at least half of that gap (or the gap is < 0.6 pt). The end stops a quarter of the met wall's
    #     thickness inside it: walls touch, no overshoot.
    polys = shapely.polygons([w["polygon"] for w in ws])
    tr = shapely.STRtree(polys)
    G = [geo(w) for w in ws]
    drawn = _Drawn(page) if "e" in steps else None
    for i, w in enumerate(ws if "e" in steps else []):
        x0, y0, x1, y1, ux, uy, L, t = G[i]
        ends = [[x0, y0], [x1, y1]]
        moved = False
        for e, sg in ((0, -1.0), (1, 1.0)):
            ex, ey = ends[e]
            probe = shapely.Point(ex, ey).buffer(0.5)
            if any(j != i and polys[j].intersects(probe) for j in tr.query(probe).tolist()):
                continue
            reach = 1.5 * t + 0.5
            ray = shapely.LineString([(ex, ey), (ex + sg * ux * reach, ey + sg * uy * reach)])
            best = None
            for j in tr.query(ray).tolist():
                if j == i:
                    continue
                hit = ray.intersection(polys[j])
                if hit.is_empty:
                    continue
                d = shapely.Point(ex, ey).distance(hit)
                if best is None or d < best[0]:
                    # crossing wall: stop a quarter of its thickness inside; collinear / parallel end-on: touch
                    par = abs(ux * G[j][5] - uy * G[j][4]) < math.sin(math.radians(30))
                    best = (d, 0.0 if par else G[j][7])
            if best is None:
                continue
            d = best[0]
            if d >= 0.6 and drawn.frac((ex, ey), (sg * ux, sg * uy), t, d) < 0.5:
                continue
            ext = d + 0.25 * best[1]
            ends[e] = [ex + sg * ux * ext, ey + sg * uy * ext]
            moved = True
        if moved:
            _set_geom(w, ends[0], ends[1], t)
    if "c" in steps and len(ws) > 1:
        ws = _close_corners(ws, drawn if drawn is not None else _Drawn(page))
    if "b" in steps and m_per_pt and page.get("words") and ws:
        # a deep, short block with a label inside (room / equipment / detail tag, not a bare dimension) is a
        # bench, plant box or cabinet drawn in wall pens, not a wall
        WB = np.array([w_["bbox"] for w_ in page["words"]], float).reshape(-1, 4)
        named = np.array([bool(re.search(r"[A-Za-z]{2,}|\d+-\d+", w_["text"] or "")) for w_ in page["words"]])
        wt = shapely.STRtree(shapely.box(WB[:, 0], WB[:, 1], WB[:, 2], WB[:, 3]))
        polys = shapely.polygons([w["polygon"] for w in ws])
        pi_, wi_ = wt.query(polys, predicate="intersects")
        lab = np.zeros(len(ws), bool)
        lab[pi_[named[wi_]]] = True
        ws = [w for i, w in enumerate(ws)
              if not (lab[i] and w["style"] != "parapet" and w["thickness_pt"] * m_per_pt >= BLOCK_MIN_M
                      and math.dist(*w["centerline"]) < 5 * w["thickness_pt"])]
    if "f" in steps and len(ws) > 1:
        # a short block (length < 4 x thickness) touching no other wall: bench / AHU / cabinet / symbol, not a wall
        polys = shapely.polygons([w["polygon"] for w in ws])
        tr = shapely.STRtree(shapely.buffer(polys, 0.5))
        qa, qb = tr.query(polys, predicate="intersects")
        touch = np.bincount(qa[qa != qb], minlength=len(ws))
        ws = [w for i, w in enumerate(ws)
              if touch[i] > 0 or math.dist(*w["centerline"]) >= 4 * w["thickness_pt"] or w["style"] == "parapet"]
    if "p" in steps and len(ws) > 1:
        ws = _drop_side_blocks(page, ws, m_per_pt)
    if "v" in steps and ws:
        try:
            _wall_evidence(page, ws)
            if "x" in steps:
                ws = _drop_unhatched(ws, m_per_pt)
        except Exception:  # noqa: BLE001
            pass
    return other + ws


def _drop_side_blocks(page, ws, m_per_pt=None):
    """A short block (length < 6x its thickness) with nothing hatched or filled inside, lying BESIDE a longer
    parallel wall (side by side within one block thickness, overlapping it along >= 80 % of the block's
    length) is a radiator / window sill / bulkhead / cabinet drawn along that wall, not a second wall. Wall
    piers between windows are collinear with the facade, not beside it, and stay. Only deep blocks (>= SIDE_BLOCK_MIN_M,
    or >= 1.5x the page's median wall without a scale): thin pieces beside a wall are its layers / frames."""
    import shapely
    F = _flat(page)
    polys = shapely.polygons([w["polygon"] for w in ws])
    fills = np.flatnonzero(F["fill"])
    fb = F["bbox"][fills]
    fc = np.column_stack([(fb[:, 0] + fb[:, 2]) / 2, (fb[:, 1] + fb[:, 3]) / 2]) if len(fills) else np.zeros((0, 2))
    fc = fc[np.isfinite(fc).all(1)]
    nfill = np.zeros(len(ws), int)
    if len(fc):
        a_, _ = shapely.STRtree(shapely.points(fc)).query(polys, predicate="contains")
        nfill = np.bincount(a_, minlength=len(ws))
    seg, sp = F["seg"], F["sp"]
    tr = shapely.STRtree(polys)
    t_min = SIDE_BLOCK_MIN_M / m_per_pt if m_per_pt else 1.5 * float(np.median([w["thickness_pt"] for w in ws]))
    drop = set()
    for i, w in enumerate(ws):
        (x0, y0), (x1, y1) = w["centerline"]
        L = math.hypot(x1 - x0, y1 - y0)
        t = w["thickness_pt"]
        if L <= 0 or L >= 6 * t or t < t_min or w["style"] == "parapet" or nfill[i] > 0:
            continue
        u = np.array([(x1 - x0) / L, (y1 - y0) / L])
        n = np.array([-u[1], u[0]])
        c = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
        # hatch inside (slanted strokes): a hatched block is poche, keep it
        q = np.flatnonzero((np.minimum(seg[:, 0], seg[:, 2]) < c[0] + L) & (np.maximum(seg[:, 0], seg[:, 2]) > c[0] - L)
                           & (np.minimum(seg[:, 1], seg[:, 3]) < c[1] + L) & (np.maximum(seg[:, 1], seg[:, 3]) > c[1] - L))
        if len(q):
            Q = seg[q]
            dv = Q[:, 2:4] - Q[:, 0:2]
            lq = np.hypot(dv[:, 0], dv[:, 1])
            # hatch strokes end inside the block (a long diagonal crossing it, e.g. a ceiling line, does not)
            e0, e1 = Q[:, 0:2] - c, Q[:, 2:4] - c
            ins = ((np.abs(e0 @ n) <= t / 2 + 0.3) & (np.abs(e0 @ u) <= L / 2 + 0.3) & (np.abs(e1 @ n) <= t / 2 + 0.3)
                   & (np.abs(e1 @ u) <= L / 2 + 0.3) & (lq > 0.3))
            cu = np.abs(dv @ u) / np.maximum(lq, 1e-9)
            h = ins & (cu > 0.34) & (cu < 0.94)
            sg = np.sign((dv[h] @ u) * (dv[h] @ n))
            # poche hatch: >= 3 slanted strokes, one direction (a zigzag radiator / spring symbol has both)
            if int(h.sum()) >= 3 and max((sg > 0).sum(), (sg < 0).sum()) >= 0.8 * len(sg):
                continue
        for j in tr.query(polys[i].buffer(t)).tolist():
            if j == i:
                continue
            (a0, b0), (a1, b1) = ws[j]["centerline"]
            Lj = math.hypot(a1 - a0, b1 - b0)
            if Lj < 2 * L:
                continue
            v = np.array([(a1 - a0) / Lj, (b1 - b0) / Lj])
            if abs(u[0] * v[1] - u[1] * v[0]) > math.sin(math.radians(3)):
                continue
            tj = ws[j]["thickness_pt"]
            off = abs((c - np.array([a0, b0])) @ np.array([-v[1], v[0]]))
            if not ((t + tj) / 2 - 1.0 <= off <= (t + tj) / 2 + t):
                continue
            sj0 = float((c - u * L / 2 - np.array([a0, b0])) @ v)
            sj1 = float((c + u * L / 2 - np.array([a0, b0])) @ v)
            ov = min(Lj, max(sj0, sj1)) - max(0.0, min(sj0, sj1))
            if ov >= 0.8 * L:
                drop.add(i)
                break
    return [w for i, w in enumerate(ws) if i not in drop]


class _Drawn:
    """Stroked straight lines of the page, to test whether drawn linework runs along a wall face over a gap."""

    def __init__(self, page):
        import shapely
        F = _flat(page)
        seg, sp = F["seg"], F["sp"]
        k = ~np.isnan(F["grey"][sp]) & ~F["arc"][sp] if len(seg) else np.zeros(0, bool)
        S = seg[k] if len(seg) else np.zeros((0, 4))
        L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
        self.S, self.L = S[L > 0.2], L[L > 0.2]
        self.tree = shapely.STRtree(shapely.linestrings(self.S.reshape(-1, 2, 2))) if len(self.S) else None

    def frac(self, p, u, t, d):
        """Share of the stretch [p, p + d u] covered by drawn lines parallel to u on either face line (+-t/2)."""
        import shapely
        if self.tree is None or d <= 0:
            return 0.0
        p, u = np.asarray(p, float), np.asarray(u, float)
        n = np.array([-u[1], u[0]])
        box = shapely.Polygon([p + n * (t / 2 + 0.6), p + u * d + n * (t / 2 + 0.6),
                               p + u * d - n * (t / 2 + 0.6), p - n * (t / 2 + 0.6)])
        q = self.tree.query(box)
        if not len(q):
            return 0.0
        Q, Lq = self.S[q], self.L[q]
        par = np.abs((Q[:, 2:4] - Q[:, 0:2]) @ n) < 0.05 * Lq + 0.05
        d0, d1 = (Q[:, 0:2] - p) @ n, (Q[:, 2:4] - p) @ n
        s0, s1 = (Q[:, 0:2] - p) @ u, (Q[:, 2:4] - p) @ u
        best = 0.0
        for off in (t / 2, -t / 2):
            e = par & (np.abs(d0 - off) < 0.6) & (np.abs(d1 - off) < 0.6)
            iv = sorted((max(0.0, min(a, b)), min(d, max(a, b))) for a, b in zip(s0[e], s1[e]))
            tot, hi = 0.0, 0.0
            for lo_, hi_ in iv:
                if hi_ > hi:
                    tot += hi_ - max(lo_, hi)
                    hi = hi_
            best = max(best, tot / d)
        return best


def _wall_evidence(page, ws):
    """props.evidence on every wall, from the page's own drawn paths (DATA RULE): the stroked lines lying along
    each of its two faces (parallel, within 0.6 pt) or along its axis as one thick stroke, and the fill paths
    inside it. {"source": "measured" (both faces drawn over >= half the length, or a fill / thick stroke) |
    "derived" (some drawn support but not both faces: thickness from the pair search / class) | "none",
    "paths": path obj ids (<= 40), "n_paths", "face_cov": [side +, side -], "stroke_cov", "fill_paths"}."""
    import shapely
    paths = page.get("paths") or []
    F = _flat(page)
    seg, sp = F["seg"], F["sp"]
    if not len(seg):
        return
    stroked = ~np.isnan(F["grey"][sp]) & ~F["arc"][sp]
    S, Ssp = seg[stroked], sp[stroked]
    Ls = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    k = Ls > 0.2
    S, Ssp, Ls = S[k], Ssp[k], Ls[k]
    W = F["width"][Ssp]
    tree = shapely.STRtree(shapely.linestrings(S.reshape(-1, 2, 2)))
    fills = np.flatnonzero(F["fill"])
    fb = F["bbox"][fills]
    fc = np.column_stack([(fb[:, 0] + fb[:, 2]) / 2, (fb[:, 1] + fb[:, 3]) / 2]) if len(fills) else np.zeros((0, 2))
    okf = np.isfinite(fc).all(1)
    fills, fc = fills[okf], fc[okf]
    ftree = shapely.STRtree(shapely.points(fc)) if len(fills) else None
    oid = [p.get("obj", i) for i, p in enumerate(paths)]
    o_ = np.argsort(W)
    cw_ = np.cumsum(Ls[o_])
    w_med = float(W[o_][np.searchsorted(cw_, cw_[-1] / 2)]) if len(o_) else 0.0
    heavy = W >= 1.25 * w_med
    fgrey = np.array([np.nan if p.get("fill") is None else 0.299 * p["fill"][0] + 0.587 * p["fill"][1]
                      + 0.114 * p["fill"][2] for p in paths], float) if paths else np.zeros(0)
    for w in ws:
        (x0, y0), (x1, y1) = w["centerline"]
        L = math.hypot(x1 - x0, y1 - y0)
        t = w["thickness_pt"]
        if L <= 0:
            continue
        u = np.array([(x1 - x0) / L, (y1 - y0) / L])
        n = np.array([-u[1], u[0]])
        c0 = np.array([x0, y0])
        poly = shapely.Polygon(w["polygon"])
        q = tree.query(poly.buffer(0.8))
        Q = S[q]
        par = np.abs((Q[:, 2:4] - Q[:, 0:2]) @ n) < 0.05 * Ls[q] + 0.05
        d0, d1 = (Q[:, 0:2] - c0) @ n, (Q[:, 2:4] - c0) @ n
        s0, s1 = (Q[:, 0:2] - c0) @ u, (Q[:, 2:4] - c0) @ u
        cov, hcov, ids = [], [], set()
        for off in (t / 2, -t / 2, 0.0):
            e = par & (np.abs(d0 - off) < 0.6) & (np.abs(d1 - off) < 0.6)
            if off == 0.0:
                e &= W[q] >= 0.5 * t  # the wall drawn as one thick stroke
            else:  # the same face, heavy (wall-outline) pen only
                eh = e & heavy[q]
                ivh = sorted((max(0.0, min(a, b)), min(L, max(a, b))) for a, b in zip(s0[eh], s1[eh]))
                toth, hih = 0.0, 0.0
                for lo_, hi_ in ivh:
                    if hi_ > hih:
                        toth += hi_ - max(lo_, hih)
                        hih = hi_
                hcov.append(toth / L)
            iv = sorted((max(0.0, min(a, b)), min(L, max(a, b))) for a, b in zip(s0[e], s1[e]))
            tot, hi = 0.0, 0.0
            for lo_, hi_ in iv:
                if hi_ > hi:
                    tot += hi_ - max(lo_, hi)
                    hi = hi_
            cov.append(tot / L)
            ids.update(Ssp[q][e].tolist())
        nf = nfg = 0
        if ftree is not None:
            fi = ftree.query(poly, predicate="contains")
            nf = len(fi)
            ids.update(fills[fi].tolist())
            fg = fgrey[fills[fi]] if len(fi) else np.zeros(0)
            nfg = int((fg < 0.97).sum())  # non-white fill (poche); white fills are masks
        # poche hatch: >= 3 slanted strokes (20-70 deg to the axis) ending inside the wall, one direction
        tq = (np.abs(d0) <= t / 2 + 0.3) & (np.abs(d1) <= t / 2 + 0.3) & (np.minimum(s0, s1) >= -0.3) \
            & (np.maximum(s0, s1) <= L + 0.3)
        dvq = Q[:, 2:4] - Q[:, 0:2]
        cu = np.abs(dvq @ u) / np.maximum(Ls[q], 1e-9)
        hs = tq & (cu > 0.34) & (cu < 0.94)
        sg = np.sign((dvq[hs] @ u) * (dvq[hs] @ n))
        nh = int(hs.sum()) if (hs.sum() >= 3 and max((sg > 0).sum(), (sg < 0).sum()) >= 0.8 * len(sg)) else 0
        measured = (cov[0] >= 0.5 and cov[1] >= 0.5) or cov[2] >= 0.5 or nf > 0
        src = "measured" if measured else ("derived" if ids else "none")
        w["props"] = {**(w.get("props") or {}), "evidence": {
            "source": src, "paths": [oid[i] for i in sorted(ids)[:40]], "n_paths": len(ids),
            "face_cov": [round(cov[0], 2), round(cov[1], 2)], "stroke_cov": round(cov[2], 2), "fill_paths": nf,
            "heavy_face_cov": [round(hcov[0], 2), round(hcov[1], 2)], "hatch_strokes": nh, "poche_fills": nfg}}


def _drop_unhatched(ws, m_per_pt=None):
    """Adaptive per sheet (DATA RULE: a wall needs drawn wall evidence). Sheets that draw their walls in a heavy
    pen (>= HEAVY_PAGE_FRAC of all wall face length drawn heavier than the page's typical line): a candidate with no hatch, no poche
    fill and no face drawn in the heavy pen over >= half its length is a pair of thin object lines (bench,
    curtain, equipment front, skylight / terrace edge, pipe-zone line), not a wall. On a hatching sheet an
    unhatched candidate also needs BOTH faces heavy. Only DEEP candidates (>= SIDE_BLOCK_MIN_M with a scale, else
    >= 2x the median wall) are judged: a light-pen partition is a real wall on many sheets (gold molio /
    esplanades lose rooms otherwise). Sheets drawn in one pen width are untouched. Parapets are left to the
    envelope."""
    ev = [(w.get("props") or {}).get("evidence") for w in ws]
    if any(e is None or "heavy_face_cov" not in e for e in ev):
        return ws
    tot = hat = ftot = fheavy = 0.0
    for w, e in zip(ws, ev):
        if w["style"] == "parapet":
            continue
        L = math.dist(*w["centerline"])
        ftot += L * (e["face_cov"][0] + e["face_cov"][1])
        fheavy += L * (e["heavy_face_cov"][0] + e["heavy_face_cov"][1])
        if L >= 3 * w["thickness_pt"]:
            tot += L
            if e["hatch_strokes"] or e["poche_fills"]:
                hat += L
    hatches = tot > 0 and hat >= HATCHED_PAGE_FRAC * tot
    heavy_pen = ftot > 0 and fheavy >= HEAVY_PAGE_FRAC * ftot
    if not heavy_pen:  # no wall pen to judge by (a sheet that only poche-fills its walls keeps its unfilled ones)
        return ws
    t_deep = SIDE_BLOCK_MIN_M / m_per_pt if m_per_pt else 2.0 * float(np.median([w["thickness_pt"] for w in ws]))
    out = []
    for w, e in zip(ws, ev):
        hv = e["heavy_face_cov"]
        e["sheet"] = {"hatches_walls": bool(hatches), "heavy_wall_pen": bool(heavy_pen),
                      "hatched_len_frac": round(hat / tot, 3) if tot else None,
                      "heavy_face_frac": round(fheavy / ftot, 3) if ftot else None}
        if w["style"] == "parapet" or e["hatch_strokes"] or e["poche_fills"] or w["thickness_pt"] < t_deep:
            out.append(w)
        elif hatches and min(hv) >= 0.5:
            out.append(w)
        elif not hatches and max(hv) >= 0.5:
            out.append(w)
    return out

def _bridge_door_gaps(page, ws, m_per_pt=None):
    """A wall line broken at its doors (corridor side of an office row, drawn in thin lines between the doors):
    two collinear pieces of similar thickness (within 30 %) with a gap of up to DOOR_GAP_MAX_M (or 12x the
    thickness without a scale) become one wall when a door swing (arc / curved path) touches the gap. The
    door stays an opening: pdf_openings / pdf_to_ifc cut it out of the joined wall."""
    import shapely
    F = _flat(page)
    arc = np.flatnonzero(F["arc"] | (F["n_curves"] > 0))
    if not len(arc):
        return ws
    bb = F["bbox"][arc]
    bb = bb[np.isfinite(bb).all(1)]
    sz = np.maximum(bb[:, 2] - bb[:, 0], bb[:, 3] - bb[:, 1])
    gmax_pt = DOOR_GAP_MAX_M / m_per_pt if m_per_pt else None
    keep = sz >= (0.5 / m_per_pt if m_per_pt else 6.0)  # a door leaf swing, not a glyph
    if gmax_pt:
        keep &= sz <= 1.2 * gmax_pt
    bb = bb[keep]
    if not len(bb):
        return ws
    atree = shapely.STRtree(shapely.box(bb[:, 0], bb[:, 1], bb[:, 2], bb[:, 3]))
    for _ in range(6):
        G = []
        for w in ws:
            (x0, y0), (x1, y1) = w["centerline"]
            L = math.hypot(x1 - x0, y1 - y0) or 1e-9
            G.append((x0, y0, x1, y1, (x1 - x0) / L, (y1 - y0) / L, L, w["thickness_pt"]))
        reach = [gmax_pt if gmax_pt else 12 * g[7] for g in G]
        lines = shapely.linestrings([[g[0], g[1]], [g[2], g[3]]] for g in G)
        tr = shapely.STRtree(lines)
        qa, qb = tr.query(shapely.buffer(lines, reach, cap_style="flat"), predicate="intersects")
        used = np.zeros(len(ws), bool)
        new = []
        for a, b in zip(qa.tolist(), qb.tolist()):
            if a >= b or used[a] or used[b] or "parapet" in (ws[a]["style"], ws[b]["style"]):
                continue
            A, B = G[a], G[b]
            if abs(A[4] * B[5] - A[5] * B[4]) > math.sin(math.radians(1.5)):
                continue
            tmin, tmax = min(A[7], B[7]), max(A[7], B[7])
            if tmin < 0.7 * tmax:
                continue
            ux, uy = A[4], A[5]
            nx, ny = -uy, ux
            if max(abs((B[0] - A[0]) * nx + (B[1] - A[1]) * ny), abs((B[2] - A[0]) * nx + (B[3] - A[1]) * ny)) > 0.5 * tmin:
                continue
            pa = (0.0, A[6])
            pb = sorted([(B[0] - A[0]) * ux + (B[1] - A[1]) * uy, (B[2] - A[0]) * ux + (B[3] - A[1]) * uy])
            if pb[0] >= pa[1]:
                g0, g1 = pa[1], pb[0]
            elif pa[0] >= pb[1]:
                g0, g1 = pb[1], pa[0]
            else:
                continue  # overlapping: the join / merge steps handle it
            gap = g1 - g0
            if gap <= tmin or gap > min(reach[a], reach[b]):
                continue
            gp = shapely.Polygon([(A[0] + ux * g0 + nx * s_ * (tmax / 2 + gap), A[1] + uy * g0 + ny * s_ * (tmax / 2 + gap))
                                  for s_ in (-1, 1)] + [(A[0] + ux * g1 + nx * s_ * (tmax / 2 + gap), A[1] + uy * g1 + ny * s_ * (tmax / 2 + gap))
                                                        for s_ in (1, -1)])
            if not len(atree.query(gp, predicate="intersects")):
                continue
            lo, hi = min(pa[0], pb[0]), max(pa[1], pb[1])
            t = (A[7] * A[6] + B[7] * B[6]) / (A[6] + B[6])
            w = dict(ws[a] if A[6] >= B[6] else ws[b])
            _set_geom(w, (A[0] + ux * lo, A[1] + uy * lo), (A[0] + ux * hi, A[1] + uy * hi), t)
            new.append(w)
            used[a] = used[b] = True
        if not new:
            break
        ws = [w for i, w in enumerate(ws) if not used[i]] + new
    return ws


def _merge_overlaps(ws):
    """Overlapping parallel walls (same axis within 3 deg, polygons sharing >= 30 % of the smaller one) become one:
    the longer wall's axis over both lengths, widened to cover both when that stays <= 1.5x the thicker wall,
    otherwise the smaller one is dropped when it lies mostly (>= 50 %) inside. Repeats until stable."""
    import shapely
    for _ in range(4):
        polys = shapely.buffer(shapely.polygons([w["polygon"] for w in ws]), 0.3, cap_style="flat", join_style="mitre")
        A = shapely.area(polys)
        tr = shapely.STRtree(polys)
        qa, qb = tr.query(polys, predicate="intersects")
        k = qa < qb
        qa, qb = qa[k], qb[k]
        C = np.array([[*w["centerline"][0], *w["centerline"][1]] for w in ws], float)
        U = C[:, 2:4] - C[:, 0:2]
        U = U / np.maximum(np.hypot(U[:, 0], U[:, 1]), 1e-9)[:, None]
        k = np.abs(U[qa, 0] * U[qb, 1] - U[qa, 1] * U[qb, 0]) <= math.sin(math.radians(3))  # parallel only
        qa, qb = qa[k], qb[k]
        if not len(qa):
            return ws
        inter = shapely.area(shapely.intersection(polys[qa], polys[qb]))
        used = np.zeros(len(ws), bool)
        new, changed = [], False
        for a, b, ia in sorted(zip(qa.tolist(), qb.tolist(), inter.tolist()), key=lambda r: -r[2]):
            if used[a] or used[b]:
                continue
            sm = min(A[a], A[b])
            if sm <= 0 or ia < 0.3 * sm:
                continue
            wa, wb = ws[a], ws[b]
            pa0, pa1 = np.array(wa["centerline"], float)
            pb0, pb1 = np.array(wb["centerline"], float)
            ua, ub = pa1 - pa0, pb1 - pb0
            la, lb = float(np.hypot(*ua)), float(np.hypot(*ub))
            if la <= 0 or lb <= 0 or abs(ua[0] * ub[1] - ua[1] * ub[0]) > math.sin(math.radians(3)) * la * lb:
                continue
            if wa["style"] == "parapet" or wb["style"] == "parapet":
                continue
            big, other_ = (wa, wb) if la * wa["thickness_pt"] >= lb * wb["thickness_pt"] else (wb, wa)
            p0, p1 = np.array(big["centerline"], float)
            u = (p1 - p0) / np.hypot(*(p1 - p0))
            n = np.array([-u[1], u[0]])
            q = np.array(other_["centerline"], float)
            al = [0.0, float((p1 - p0) @ u), float((q[0] - p0) @ u), float((q[1] - p0) @ u)]
            tb, to = big["thickness_pt"], other_["thickness_pt"]
            oo = float(((q[0] + q[1]) / 2 - p0) @ n)
            lo_, hi_ = min(-tb / 2, oo - to / 2), max(tb / 2, oo + to / 2)
            w = dict(big)
            if hi_ - lo_ <= max(1.5 * max(tb, to), tb + to + 0.6):  # overlapping, or layers lying face to face
                mid = (lo_ + hi_) / 2
                _set_geom(w, p0 + u * min(al) + n * mid, p0 + u * max(al) + n * mid, hi_ - lo_)
            elif ia >= 0.5 * (A[a] if other_ is wa else A[b]):
                pass  # drop the smaller, keep the big one as it is
            else:
                continue
            used[a] = used[b] = True
            new.append(w)
            changed = True
        ws = [w for i, w in enumerate(ws) if not used[i]] + new
        if not changed:
            break
    return ws


def _near_pairs(P, r):
    """Sorted index pairs (a < b) of points within r of each other (shapely STRtree; no scipy import)."""
    import shapely
    if len(P) < 2:
        return []
    pts = shapely.points(P)
    a, b = shapely.STRtree(pts).query(pts, predicate="dwithin", distance=r)
    k = a < b
    return sorted(zip(a[k].tolist(), b[k].tolist()))


def _close_corners(ws, drawn=None):
    """L corners: two free ends of non-parallel walls whose centre lines cross within 1.5 x the thicker wall's
    thickness of both ends are extended to the crossing (+ half the other's thickness), closing the corner."""
    import shapely
    polys = shapely.polygons([w["polygon"] for w in ws])
    tr = shapely.STRtree(polys)
    ends = []
    for i, w in enumerate(ws):
        for e in (0, 1):
            pt = shapely.Point(w["centerline"][e])
            probe = pt.buffer(w["thickness_pt"] / 2 + 0.5)
            if not any(j != i and polys[j].intersects(probe) for j in tr.query(probe).tolist()):
                ends.append((i, e))
    if len(ends) < 2:
        return ws
    E = np.array([ws[i]["centerline"][e] for i, e in ends], float)
    tmax = max(w["thickness_pt"] for w in ws)
    done = set()
    for a, b in _near_pairs(E, 3 * tmax + 1.0):
        (i, ei), (j, ej) = ends[a], ends[b]
        if i == j or (i, ei) in done or (j, ej) in done:
            continue
        wi, wj = ws[i], ws[j]
        p0, p1 = np.array(wi["centerline"], float)
        q0, q1 = np.array(wj["centerline"], float)
        u, v = p1 - p0, q1 - q0
        den = u[0] * v[1] - u[1] * v[0]
        if abs(den) < math.sin(math.radians(30)) * np.hypot(*u) * np.hypot(*v):
            continue
        s_ = ((q0 - p0)[0] * v[1] - (q0 - p0)[1] * v[0]) / den
        X = p0 + s_ * u
        ti, tj = wi["thickness_pt"], wj["thickness_pt"]
        lim = 1.5 * max(ti, tj) + 0.5
        if math.dist(X, wi["centerline"][ei]) > lim or math.dist(X, wj["centerline"][ej]) > lim:
            continue
        if drawn is not None:  # DATA RULE: the drawn face lines must continue towards the corner on both walls
            okd = True
            for w, e in ((wi, ei), (wj, ej)):
                pe = np.array(w["centerline"][e], float)
                g = float(np.hypot(*(X - pe)))
                if g >= 0.6 and drawn.frac(pe, (X - pe) / g, w["thickness_pt"], g) < 0.5:
                    okd = False
            if not okd:
                continue
        for w, e, t_other in ((wi, ei, tj), (wj, ej, ti)):
            c = [list(w["centerline"][0]), list(w["centerline"][1])]
            far = np.array(c[1 - e], float)
            d = X - far
            L = float(np.hypot(*d))
            if L <= 0:
                continue
            c[e] = list(X + d / L * t_other / 2)
            _set_geom(w, c[0], c[1], w["thickness_pt"])
        done.add((i, ei)); done.add((j, ej))
    return ws


# ---------------------------------------------------------------- partitions that host otherwise unhosted doors

PARTITION_DOOR_MIN_M = 0.06   # face spacing of a thin partition holding a door
PARTITION_DOOR_MAX_M = 0.22   # (measured on ARK: WC cubicle front 0.085 m, B3xx partitions 0.10-0.20 m)
PARTITION_PIECE_MIN_M = 0.1   # drawn stretches shorter than this (jamb ticks, frame bits) are not walls


def partitions_for_doors(page: dict, doors: list, walls: list, m_per_pt: float | None = None) -> list:
    """Walls for doors that have no wall on their hinge line (DATA RULE: only drawn lines).

    doors: pdf_openings.openings(page, walls) items with kind "door" (page pt coordinates); a door is unhosted
    when props["wall_index"] is None. Uses props["hinge"] (pt) and props["axis_deg"] (the opening's direction
    along its wall line), props["width_pt"].
    For each unhosted door: the stroked lines parallel to its axis (within 2 deg) lying within the partition
    spacing of its hinge line are grouped into face lines; the face pair PARTITION_DOOR_MIN_M..MAX_M apart
    (nearest to the hinge line) gives the partition. Its drawn stretch = the intervals where BOTH faces are
    drawn, chained outwards from the door across gaps that are door openings (another door's box) or <= 1 pt,
    and kept only when both chain ends reach a found wall or a door. Returns wall dicts in the walls() format
    (style "double", thickness = measured face spacing, props.evidence with the face path ids, source
    "measured"), one per drawn stretch; nothing is built across the door gaps."""
    import shapely
    if not doors or not walls:
        return []
    mpt = m_per_pt or None
    dmin = PARTITION_DOOR_MIN_M / mpt if mpt else 1.5
    dmax = PARTITION_DOOR_MAX_M / mpt if mpt else 7.0
    F = _flat(page)
    seg, sp = F["seg"], F["sp"]
    if not len(seg):
        return []
    k = ~np.isnan(F["grey"][sp]) & ~F["arc"][sp] & ~F["dashed"][sp]
    S, Ssp = seg[k], sp[k]
    Ls = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    kk = Ls > 0.5
    S, Ssp, Ls = S[kk], Ssp[kk], Ls[kk]
    if not len(S):
        return []
    stree = shapely.STRtree(shapely.linestrings(S.reshape(-1, 2, 2)))
    wpoly = shapely.polygons([w["polygon"] for w in walls if w.get("style") != "parapet"])
    wtree = shapely.STRtree(wpoly)
    dboxes = [shapely.box(*d["bbox"]).buffer(1.0) for d in doors if d.get("bbox")]
    dcorn = [np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], float)
             for b in (d["bbox"] for d in doors if d.get("bbox"))]
    pmin = PARTITION_PIECE_MIN_M / mpt if mpt else 3.0
    dtree = shapely.STRtree(dboxes) if dboxes else None
    oid = [p.get("obj", i) for i, p in enumerate(page.get("paths") or [])]
    out, seen = [], []
    for d in doors:
        pr = d.get("props") or {}
        if d.get("kind") != "door" or pr.get("wall_index") is not None or not pr.get("hinge"):
            continue
        dbox = shapely.box(*d["bbox"])
        hq = wtree.query(dbox)
        if dbox.area > 0 and len(hq) and float(shapely.area(shapely.intersection(wpoly[hq], dbox)).sum()) >= 0.3 * dbox.area:
            continue  # the door lies in a found wall (a hosting miss in pdf_openings, not a missing partition)
        h = np.asarray(pr["hinge"], float)
        a = math.radians(float(pr.get("axis_deg") or 0.0))
        u = np.array([math.cos(a), math.sin(a)])
        if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
            u = -u
        n = np.array([-u[1], u[0]])
        width = float(pr.get("width_pt") or 30.0)
        reach = max(6.0 * width, 4.0 / mpt if mpt else 120.0)
        db = np.asarray(d["bbox"], float)
        corners = np.array([[db[0], db[1]], [db[2], db[1]], [db[2], db[3]], [db[0], db[3]]])
        dlo, dhi = float((corners @ u).min()), float((corners @ u).max())
        hs = float(h @ u)
        area = shapely.Polygon([h + u * (dlo - hs - reach) + n * (dmax + 1), h + u * (dhi - hs + reach) + n * (dmax + 1),
                                h + u * (dhi - hs + reach) - n * (dmax + 1), h + u * (dlo - hs - reach) - n * (dmax + 1)])
        q = stree.query(area.buffer(reach * math.sin(math.radians(10))))
        if not len(q):
            continue
        Q = S[q]
        dv = Q[:, 2:4] - Q[:, 0:2]
        # the door's axis is measured from its swing (a few degrees off): take the drawn lines' own direction,
        # the length-weighted median of the lines within 10 deg of it near the hinge line
        near = (np.abs(dv @ n) < math.sin(math.radians(10)) * Ls[q]) & \
            (np.abs(((Q[:, 0:2] + Q[:, 2:4]) / 2 - h) @ n) < dmax + 2 + math.sin(math.radians(10)) * reach)
        if near.sum() < 2:
            continue
        ang = np.arctan2(dv[near] @ n, dv[near] @ u)
        ang = np.where(ang > math.pi / 2, ang - math.pi, np.where(ang < -math.pi / 2, ang + math.pi, ang))
        o_ = np.argsort(ang)
        cw_ = np.cumsum(Ls[q][near][o_])
        da = float(ang[o_][np.searchsorted(cw_, cw_[-1] / 2)])
        u = u * math.cos(da) + n * math.sin(da)
        n = np.array([-u[1], u[0]])
        dlo, dhi = float((corners @ u).min()), float((corners @ u).max())
        hs = float(h @ u)
        par = np.abs(dv @ n) < math.sin(math.radians(2)) * Ls[q] + 0.05
        o0, o1 = (Q[:, 0:2] - h) @ n, (Q[:, 2:4] - h) @ n
        par &= np.abs(o0 - o1) < 0.3
        if par.sum() < 2:
            continue
        off = (o0 + o1) / 2
        s0, s1 = np.minimum(Q[:, 0:2] @ u, Q[:, 2:4] @ u), np.maximum(Q[:, 0:2] @ u, Q[:, 2:4] @ u)
        # face lines: offsets clustered at 0.3 pt
        idx = np.flatnonzero(par)
        cl = {}
        for i in idx[np.argsort(off[idx])]:
            key = None
            for c in cl:
                if abs(c - off[i]) <= 0.3:
                    key = c
                    break
            cl.setdefault(key if key is not None else float(off[i]), []).append(i)
        offs = sorted(cl)
        # the door sits in the partition: its box overlaps the face band across the partition
        dn0, dn1 = float(((corners - h) @ n).min()), float(((corners - h) @ n).max())

        def intervals(c):
            iv = sorted((float(s0[i]), float(s1[i])) for i in cl[c])
            m = []
            for lo, hi in iv:
                if m and lo <= m[-1][1] + 0.3:
                    m[-1][1] = max(m[-1][1], hi)
                else:
                    m.append([lo, hi])
            return m

        def both_drawn(ca, cb):
            res = []
            for lo1, hi1 in intervals(ca):
                for lo2, hi2 in intervals(cb):
                    lo, hi = max(lo1, lo2), min(hi1, hi2)
                    if hi - lo > 1.0:
                        res.append([lo, hi])
            return sorted(res)
        def covered(c0, c1, t):
            piece = shapely.LineString([c0, c1]).buffer(t / 2, cap_style="flat")
            hq = wtree.query(piece)
            return bool(len(hq)) and float(shapely.area(shapely.intersection(wpoly[hq], piece)).sum()) >= 0.5 * piece.area

        cands = []
        for ia in range(len(offs)):
            for ib in range(ia + 1, len(offs)):
                sp_ = offs[ib] - offs[ia]
                if not (dmin <= sp_ <= dmax) or offs[ia] > 1.0 or offs[ib] < -1.0:
                    continue
                if min(dn1, offs[ib]) - max(dn0, offs[ia]) < 0.5:
                    continue
                bd = both_drawn(offs[ia], offs[ib])
                tot = sum(hi - lo for lo, hi in bd)
                if tot > 0:
                    cands.append((-tot, offs[ia], offs[ib], bd))
        cands.sort(key=lambda r: (r[0], abs(r[1] + r[2])))
        run = None
        # the face pair (spacing in range, straddling / touching the hinge line) drawn together the longest whose
        # stretch passes the end test
        for _, fa, fb, both in cands:
            t = fb - fa
            mid = (fa + fb) / 2
            base = h + n * mid - u * hs  # point on the centre line at axis coordinate 0

            def at(sv):
                return base + u * sv

            def door_spans(lo, hi):  # axis intervals of the door boxes lying on this centre line within lo..hi
                if dtree is None or hi <= lo:
                    return []
                g = shapely.LineString([at(lo), at(hi)]).buffer(t / 2 + 0.5)
                res = []
                for j in dtree.query(g, predicate="intersects"):
                    pu = dcorn[j] @ u
                    res.append((max(lo, float(pu.min())), min(hi, float(pu.max()))))
                return sorted(r for r in res if r[1] > r[0])

            def gap_ok(lo, hi):  # a gap that is a door opening (door boxes span >= half of it) or a hairline
                if hi - lo <= 1.0:
                    return True
                cov, end = 0.0, lo
                for a_, b_ in door_spans(lo, hi):
                    if b_ > end:
                        cov += b_ - max(a_, end)
                        end = b_
                return cov >= 0.5 * (hi - lo)

            # chain the drawn stretches connected (across door gaps) to this door's opening: they touch the
            # door box (the box can be a little shorter than the opening: tolerance 2 t / 0.15 m)
            tol = max(2.0 * t, 0.15 / mpt if mpt else 4.0)
            chain = [iv for iv in both if iv[1] >= dlo - tol and iv[0] <= dhi + tol]
            if not chain:
                continue
            lo_i = both.index(chain[0])
            hi_i = both.index(chain[-1])
            while lo_i > 0 and gap_ok(both[lo_i - 1][1], both[lo_i][0]):
                lo_i -= 1
            while hi_i < len(both) - 1 and gap_ok(both[hi_i][1], both[hi_i + 1][0]):
                hi_i += 1
            run = both[lo_i:hi_i + 1]

            def end_ok(sv, sg):
                p = shapely.Point(*at(sv + sg * 0.6)).buffer(t / 2 + 0.8)
                if len(wtree.query(p, predicate="intersects")):
                    return True
                return dtree is not None and bool(len(dtree.query(p, predicate="intersects")))
            e0, e1 = end_ok(run[0][0], -1.0), end_ok(run[-1][1], 1.0)
            n_gaps = sum(1 for a_, b_ in zip(run, run[1:]) if b_[0] - a_[1] > 1.0)
            # both ends on a wall / door; or a run spanning door gaps (a door front) with one end on a wall / door
            if not ((e0 and e1) or ((e0 or e1) and n_gaps >= 1)):
                continue
            if all(covered(at(lo), at(hi), t) for lo, hi in run):
                continue  # this pair is an already-found wall: try the next face pair
            break
        else:
            continue
        pieces = []
        for lo, hi in run:  # nothing is built across a door opening drawn with both face lines
            for a_, b_ in door_spans(lo, hi):
                if a_ > lo:
                    pieces.append((lo, a_))
                lo = max(lo, b_)
            if hi > lo:
                pieces.append((lo, hi))
        inner = [c for c in offs if fa + 0.3 < c < fb - 0.3]
        for lo, hi in pieces:
            if hi - lo < pmin:
                continue
            # a line parallel to the faces running between them along most of the stretch = glazing (a window
            # or glazed screen drawn as frame + glass lines), not a partition
            if any(sum(max(0.0, min(hi, b_) - max(lo, a_)) for a_, b_ in intervals(c)) >= 0.5 * (hi - lo)
                   for c in inner):
                continue
            c0, c1 = at(lo), at(hi)
            piece = shapely.LineString([c0, c1]).buffer(t / 2, cap_style="flat")
            if covered(c0, c1, t):
                continue  # already a found wall
            if any(piece.intersection(e_).area >= 0.5 * piece.area for e_ in seen):
                continue  # the same stretch, reached from another door of this partition
            seen.append(piece)
            ids = sorted({int(Ssp[q][i]) for c in (fa, fb) for i in cl[c] if s1[i] > lo and s0[i] < hi})
            w = {"style": "double"}
            _set_geom(w, c0, c1, t)
            w["props"] = {"evidence": {"source": "measured", "paths": [oid[i] for i in ids[:40]], "n_paths": len(ids),
                                       "face_cov": [1.0, 1.0], "rule": "partition_for_unhosted_door",
                                       "door_bbox": [round(float(v), 1) for v in d["bbox"]]}}
            out.append(w)
    return out
