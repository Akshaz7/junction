"""Ingest-time accuracy score for a PDF -> plan map conversion, with no ground truth.

assess(page, planmap) compares the plan map against the PDF's own evidence:
  walls     rasterise the wall evidence the vector reader saw (pdf_vector.walls before the plan-map filters, plus
            the page's dark fills) and the final wall polygons at 5 cm/px; precision / recall / IoU (1-px tolerance)
            and a back-projection check of the final envelope (walls + openings) against the drawing's outer outline.
            score = 0.6 * F1 + 0.4 * outline coverage.
  rooms     fraction of rooms that got a polygon; measured vs printed area relative error (median, p90).
            per-room area score = max(0, 1 - err / 0.30); score = 0.4 * polygon fraction + 0.6 * mean area score
            (polygon fraction alone, capped at 0.85, when nothing is printed).
  scale     rung base (printed 1:N 0.95, scale bar / printed-areas fit 0.85, dimensions 0.7, door guess 0.4, none 0),
            times an agreement factor between printed 1:N and the printed-areas fit when both exist
            (1.0 within 2%, falling linearly to 0.5 at 10%); +0.05 when they agree within 2%.
  openings  fraction of door-swing arcs on the page (quarter arcs, Bezier or flattened polylines, r 0.45-1.35 m)
            whose hinge is at a door item; fraction of windows on a wall.
  overall   weights walls 0.40, rooms 0.30, scale 0.15, openings 0.15 (renormalised over available components);
            95% CI from a bootstrap over 2 m wall tiles, rooms, arcs and windows (scale held fixed).
All geometry in page points, top-left origin, y down (plan-map px are divided by provenance.px_per_pt).
"""
from __future__ import annotations

import math

import numpy as np

CELL_M = 0.05
TILE_M = 2.0
WEIGHTS = {"walls": 0.40, "rooms": 0.30, "scale": 0.15, "openings": 0.15}
AREA_ERR_ZERO = 0.30
MAX_FILL_THICK_M = 1.2


def _grey(c):
    return None if c is None else (sum(c[:3]) / 3.0 if max(c[:3]) <= 1.0 else sum(c[:3]) / 765.0)


def _shoelace(p):
    return abs(sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1] for i in range(len(p)))) / 2


def _perim(p):
    return sum(math.dist(p[i][:2], p[i - 1][:2]) for i in range(len(p)))


def _rect_thick(p):
    a, per = _shoelace(p), _perim(p)
    d = max(per * per / 4 - 4 * a, 0.0)
    L = (per / 2 + math.sqrt(d)) / 2
    return a / L if L > 0 else 0.0


def _label(x):
    return "high" if x >= 0.85 else "medium" if x >= 0.65 else "low"


class _Grid:
    def __init__(self, box, mpt, cell_m=CELL_M):
        self.x0, self.y0 = box[0], box[1]
        self.k = mpt / cell_m  # cells per pt
        self.w = max(1, int(math.ceil((box[2] - box[0]) * self.k)))
        self.h = max(1, int(math.ceil((box[3] - box[1]) * self.k)))

    def cell(self, xy):
        return ((xy[0] - self.x0) * self.k, (xy[1] - self.y0) * self.k)

    def raster(self, polys):
        from PIL import Image, ImageDraw
        im = Image.new("1", (self.w, self.h), 0)
        d = ImageDraw.Draw(im)
        for p in polys:
            if p and len(p) >= 3:
                d.polygon([self.cell(q) for q in p], fill=1, outline=1)
        return np.array(im, dtype=bool)


EDT_MIN_R = 4  # disk radius (cells) from which the distance-transform form beats scipy's structured morphology


def _dil(m, r):
    """Binary dilation by a disk of radius r cells (x^2 + y^2 <= r^2), outside the array = False.
    r >= EDT_MIN_R: the same mask from one Euclidean distance transform (O(n), vs O(n r^2) for the structure)."""
    from scipy import ndimage
    if r <= 0:
        return m
    if r >= EDT_MIN_R:
        if not m.any():
            return np.zeros(m.shape, bool)
        return ndimage.distance_transform_edt(~m) <= r
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return ndimage.binary_dilation(m, structure=(x * x + y * y) <= r * r)


def _ero(m, r):
    """Binary erosion by the same disk, outside the array = False (scipy border_value=0)."""
    from scipy import ndimage
    if r >= EDT_MIN_R:
        return (ndimage.distance_transform_edt(np.pad(m, 1)) > r)[1:-1, 1:-1]
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return ndimage.binary_erosion(m, structure=(x * x + y * y) <= r * r)


def _close_fill(m, r):
    from scipy import ndimage
    pad = np.pad(m, r + 1)
    c = _ero(_dil(pad, r), r)[r + 1:-r - 1, r + 1:-r - 1]
    return ndimage.binary_fill_holes(c)


def _items(pm, kind):
    return [i for i in pm.get("items", []) if i.get("kind") == kind]


def _to_pt(pm, page):
    s = float((pm.get("provenance") or {}).get("px_per_pt") or (pm["image"]["w"] / page["W_pt"]))
    return lambda poly: [[q[0] / s, q[1] / s] for q in poly], s


def _bbox_poly(b):
    return [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]


def wall_evidence(page, raw_walls, roi, mpt):
    """Polygons (pt) the PDF itself offers as walls: the vector reader's raw walls + dark closed fills in the ROI."""
    ev = [w["polygon"] for w in raw_walls or [] if w.get("polygon") and len(w["polygon"]) >= 3]
    for p in page.get("paths", []):
        g = _grey(p.get("fill"))
        pts = p.get("pts") or []
        if g is None or g > 0.35 or len(pts) < 3:
            continue
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        if max(xs) < roi[0] or min(xs) > roi[2] or max(ys) < roi[1] or min(ys) > roi[3]:
            continue
        if _shoelace(pts) <= 0 or _rect_thick(pts) * mpt > MAX_FILL_THICK_M:
            continue  # floor/site/slab fills are not walls
        ev.append(pts)
    return ev


INK_GREY = 160          # 0..255: darker counts as ink (anti-aliased thin lines and hatch included)
INK_CELL_M = CELL_M / 2  # render at 2.5 cm/px, reduce to the 5 cm grid after the morphology
HATCH_CLOSE_M = 0.05     # merges hatch strokes / fill seams into solid
OUTLINE_WALL_MAX_M = 0.40  # a closed outline narrower than this is a drawn (unfilled) wall: fill it
OPEN_M = 0.06            # opening at ~half the minimum wall thickness (~0.12 m): removes lines, text strokes, dims


def ink_walls(pdf_path, page, g, mpt):
    """Wall evidence straight from the rendered page, independent of the vector reader: dark ink at 2.5 cm/px,
    text boxes blanked, hatch merged, thin closed outlines (< 0.4 m) filled, thin lines removed by an opening.
    Returns a bool mask on grid g (5 cm cells), or None."""
    import pypdfium2 as pdfium
    from scipy import ndimage
    kr = mpt / INK_CELL_M  # px per pt
    big = max(page["W_pt"], page["H_pt"]) * kr
    if big > 12000:
        return None
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        pg = doc[int(page.get("page_index", 0))]
        bm = pg.render(scale=kr, grayscale=True)
        a = bm.to_numpy()
    finally:
        doc.close()
    a = a[..., 0] if a.ndim == 3 else a
    a = a.copy()
    for w in page.get("words", []):  # blank text (room names, dimensions, areas)
        b = w["bbox"]
        m = int(round(0.25 * (b[3] - b[1]) * kr)) + 1  # glyph overshoot, underlines, superscripts (m², ft²)
        a[max(0, int(b[1] * kr) - m):int(b[3] * kr) + m + 1, max(0, int(b[0] * kr) - m):int(b[2] * kr) + m + 1] = 255
    x0, y0 = int(round(g.x0 * kr)), int(round(g.y0 * kr))
    h, w = 2 * g.h, 2 * g.w
    crop = np.full((h, w), 255, a.dtype)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(a.shape[1], x0 + w), min(a.shape[0], y0 + h)
    if sx1 > sx0 and sy1 > sy0:
        crop[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = a[sy0:sy1, sx0:sx1]
    dark = crop < INK_GREY
    r = max(1, int(round(HATCH_CLOSE_M / INK_CELL_M)))
    dark = ndimage.binary_closing(np.pad(dark, r), structure=np.ones((2 * r + 1,) * 2))[r:-r, r:-r] | dark
    holes = ndimage.binary_fill_holes(dark) & ~dark
    if holes.any():
        lab, n = ndimage.label(holes)
        width = ndimage.maximum(ndimage.distance_transform_edt(holes), lab, index=np.arange(1, n + 1))
        thin = np.zeros(n + 1, bool)
        thin[1:] = np.asarray(width) * 2 * INK_CELL_M <= OUTLINE_WALL_MAX_M
        dark |= thin[lab]
    k = max(2, int(round(OPEN_M / INK_CELL_M)) + 1)
    dark = ndimage.binary_opening(dark, structure=np.ones((k, k)))
    return dark.reshape(g.h, 2, g.w, 2).any(axis=(1, 3))


def _wall_part(page, pm, raw_walls, mpt, to_pt, pdf_path=None):
    wall_pt = [to_pt(i["polygon_px"]) for i in _items(pm, "wall") if i.get("polygon_px")]
    if not wall_pt:
        return None
    open_pt = [to_pt(i["polygon_px"]) if i.get("polygon_px") else _bbox_poly([c for xy in to_pt([i["bbox_px"][:2], i["bbox_px"][2:]]) for c in xy])
               for i in _items(pm, "door") + _items(pm, "window")]
    xs = [q[0] for p in wall_pt for q in p]
    ys = [q[1] for p in wall_pt for q in p]
    pad = 3.0 / mpt
    roi = [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]
    g = _Grid(roi, mpt)
    if g.w * g.h > 6e7:
        return None
    E, src, ev = None, "pdf ink (rendered page)", []
    if pdf_path:
        try:
            E = ink_walls(pdf_path, page, g, mpt)
        except Exception:
            E = None
    if E is None:  # no PDF at hand (tests): the vector reader's raw walls + dark fills
        ev = wall_evidence(page, raw_walls, roi, mpt)
        E, src = g.raster(ev), "vector paths (raw walls + dark fills)"
    F = g.raster(wall_pt)
    O = g.raster(open_pt)
    dE, dF = _dil(E, 1), _dil(F | O, 1)
    fm, em = F & dE, E & dF  # final wall px on ink / ink px reproduced by the 3D envelope (walls + doors/windows)
    r_gap = max(2, int(round(1.0 / CELL_M)))  # closes gaps < 2 m (doors, windows drawn as thin lines)
    outer_E = _close_fill(E, r_gap)
    outline = outer_E & _dil(~outer_E, 1)
    envelope = F | O
    cov = outline & _dil(envelope, int(round(0.3 / CELL_M)))
    outer_F = _close_fill(envelope, r_gap)
    closed_ratio = float(outer_F.sum() / outer_E.sum()) if outer_E.sum() else 0.0
    t = max(1, int(round(TILE_M / CELL_M)))
    ty, tx = (g.h + t - 1) // t, (g.w + t - 1) // t

    def tiles(m):
        pad_ = np.zeros((ty * t, tx * t), dtype=np.int64)
        pad_[:g.h, :g.w] = m
        return pad_.reshape(ty, t, tx, t).sum(axis=(1, 3)).ravel()

    T = np.stack([tiles(F), tiles(fm), tiles(E), tiles(em), tiles(outline), tiles(cov),
                  tiles(F & E), tiles(F | E)], axis=1)
    T = T[T[:, [0, 2, 4]].sum(axis=1) > 0]
    stats = _wall_stats(T.sum(axis=0))
    stats.update({"closed_exterior": bool(closed_ratio >= 0.9), "enclosed_vs_outline": round(closed_ratio, 3),
                  "evidence": src, "evidence_polys": len(ev), "final_walls": len(wall_pt), "cell_m": CELL_M})
    return {"stats": stats, "tiles": T, "masks": (E, F, O, outline), "grid": g, "outer": outer_E}


def _wall_stats(c):
    F, fm, E, em, ol, cov, inter, uni = [float(v) for v in c]
    p = fm / F if F else 0.0
    r = em / E if E else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    oc = cov / ol if ol else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            "iou": round(inter / uni, 4) if uni else 0.0, "outline_covered": round(oc, 4),
            "score": round(0.6 * f1 + 0.4 * oc, 4)}


ROOM_NO_PRINTED_U = 0.10  # +/- uniform term added to the room score per bootstrap draw when nothing is printed:
                          # printed areas are the only independent area check, without them area accuracy is unknown


def _room_part(pm, to_pt=None, W=None):
    rooms = _items(pm, "room")
    if not rooms:
        return None
    has = np.array([1.0 if r.get("polygon_px") else 0.0 for r in rooms])
    errs = []
    for r in rooms:
        q = r.get("q") or {}
        a, pr = q.get("area_m2"), q.get("area_m2_printed")
        errs.append(abs(a / pr - 1) if a and pr else np.nan)
    px = np.zeros(len(rooms))
    leak = np.zeros(len(rooms))
    interior = 0.0
    if W is not None and to_pt is not None:
        from scipy import ndimage
        E, F, O, _ = W["masks"]
        outer = W["outer"]
        core = ndimage.binary_erosion(E | F, iterations=2)  # inside a wall, past a 10 cm tolerance
        bad = ~outer | core
        interior = float((outer & ~(E | F)).sum())
        for k, r in enumerate(rooms):
            if r.get("polygon_px"):
                m = W["grid"].raster([to_pt(r["polygon_px"])])
                px[k], leak[k] = m.sum(), (m & bad).sum()
    return {"has": has, "errs": np.array(errs), "px": px, "leak": leak, "interior": interior}


def _room_terms(R, ix=None):
    ix = np.arange(len(R["has"])) if ix is None else ix
    has, errs, px, leak = R["has"][ix], R["errs"][ix], R["px"][ix], R["leak"][ix]
    cov = float(has.mean()) if len(has) else 0.0
    t = {"coverage": cov}
    if R["interior"] > 0:
        rc = float(px.sum()) / R["interior"]
        t["closure"] = min(rc, 1 / rc) if rc > 0 else 0.0
        t["leak_fraction"] = float(leak.sum() / px.sum()) if px.sum() else 1.0
        t["leak_score"] = max(0.0, 1 - 3 * t["leak_fraction"])
    e = errs[~np.isnan(errs)]
    if len(e):
        t["area"] = float(np.clip(1 - e / AREA_ERR_ZERO, 0, 1).mean())
    return t


def _room_score_t(t):
    geo = [t[k] for k in ("closure", "leak_score") if k in t]
    if "area" in t:
        return 0.3 * t["coverage"] + 0.4 * t["area"] + (0.15 * sum(geo) if len(geo) == 2 else 0.3 * t["area"])
    if len(geo) == 2:
        return 0.4 * t["coverage"] + 0.3 * geo[0] + 0.3 * geo[1]
    return 0.5 * t["coverage"]  # nothing to check the rooms against


def _scale_part(pm):
    sc = pm.get("scale") or {}
    m = (sc.get("method") or "none").lower()
    base = (0.95 if m.startswith("printed 1:") else 0.85 if m in ("scale bar", "printed areas fit")
            else 0.7 if m.startswith("dimension") else 0.4 if "door" in m else 0.0)
    ck = sc.get("check") or {}
    agree = ck.get("fit_vs_printed_rel")
    f = 1.0
    if agree is not None and ck.get("fit_n", 0) >= 2:
        a = abs(agree)
        f = 1.0 if a <= 0.02 else max(0.5, 1 - 0.5 * (a - 0.02) / 0.08)
        if a <= 0.02:
            base += 0.05
    return {"method": sc.get("method") or "none", "ratio": sc.get("ratio"), "confidence": sc.get("confidence"),
            "fit_vs_printed_rel": agree, "agree_2pct": None if agree is None else abs(agree) <= 0.02,
            "score": round(min(1.0, base * f), 4)}


ARC_R_M = (0.45, 1.35)      # door-leaf radius range (same as pdf_openings._door_range)
ARC_SPAN_DEG = (60.0, 115.0)  # a full quarter swing; partial swings are not counted as evidence
ARC_MATCH_M = 0.3
ARC_PIECE_M = 0.3          # longest straight piece of a flattened door arc


def _arc_chains(segs, max_turn_deg, tol=0.15):
    """Smooth one-way-turning chains of short segments (a flattened arc split into 2-point paths) -> point arrays.
    Same rule as pdf_openings._chains (each joint turns 0 < angle < max_turn, all the same way), with integer
    endpoint keys built in numpy: 10x faster on 50k+ segment sheets, where the quality pass must stay cheap."""
    from collections import defaultdict
    n = len(segs)
    if n == 0:
        return []
    d = segs[:, 2:] - segs[:, :2]
    u = d / np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]
    keys = np.round(np.r_[segs[:, :2], segs[:, 2:]] / tol).astype(np.int64)
    kk = (keys[:, 0] * 1_000_003 + keys[:, 1]).tolist()
    at = defaultdict(list)
    for i in range(n):
        at[kk[i]].append((i, 0))
        at[kk[n + i]].append((i, 1))
    ux, uy = u[:, 0].tolist(), u[:, 1].tolist()
    P = segs.tolist()
    cmin = math.cos(math.radians(max_turn_deg))
    used = bytearray(n)

    def step(i, end, sign):
        dx, dy = (ux[i], uy[i]) if end == 1 else (-ux[i], -uy[i])
        best = None
        for j, e in at[kk[n * end + i]]:
            if j == i or used[j]:
                continue
            ex, ey = (ux[j], uy[j]) if e == 0 else (-ux[j], -uy[j])
            c = dx * ex + dy * ey
            if c < cmin or c > 0.99995:
                continue
            cr = dx * ey - dy * ex
            if sign and cr * sign < 0:
                continue
            if best is None or c > best[3]:
                best = (j, 1 - e, cr, c)
        return best

    out = []
    for i0 in range(n):
        if used[i0]:
            continue
        used[i0] = 1
        pts = [P[i0][:2], P[i0][2:]]
        for end in (1, 0):
            i, e, sign = i0, end, 0.0
            while True:
                nx = step(i, e, sign)
                if nx is None:
                    break
                j, fe, cr, _ = nx
                used[j] = 1
                sign = sign or (1.0 if cr > 0 else -1.0)
                q = P[j][2:] if fe == 1 else P[j][:2]
                if end == 1:
                    pts.append(q)
                else:
                    pts.insert(0, q)
                i, e = j, fe
        if len(pts) >= 4:
            out.append(np.asarray(pts, float))
    return out


def _arc_of(pts, rmin, rmax):
    """(cx, cy, r) when the points lie on a circle of radius rmin..rmax spanning ARC_SPAN_DEG, else None."""
    from pipeline import pdf_openings as po
    c = po._fit_circle(pts)
    if c is None:
        return None
    cx, cy, r, rms = c
    if not (rmin <= r <= rmax) or rms > 0.05 * r:
        return None
    a = np.sort(np.degrees(np.arctan2(np.asarray(pts)[:, 1] - cy, np.asarray(pts)[:, 0] - cx)) % 360)
    gaps = np.diff(np.r_[a, a[0] + 360])
    span = 360 - gaps.max()  # angular extent, order-free
    return (cx, cy, r) if ARC_SPAN_DEG[0] <= span <= ARC_SPAN_DEG[1] else None


def door_arcs(page, mpt, roi):
    """Door-swing evidence on the page (pt): quarter arcs drawn as Bezier curves, as one flattened polyline path,
    or as runs of separate short segments (CAD exports usually flatten arcs; is_arc only marks the Bezier ones,
    which is why the old is_arc-only scan saw a handful of symbol arcs and matched none). Circle-fit radius
    0.45-1.35 m, span 60-115 deg, hinge inside the wall ROI, de-duplicated. Returns [{"c", "r", "bbox"}]."""
    from pipeline import pdf_openings as po
    rmin, rmax = ARC_R_M[0] / mpt, ARC_R_M[1] / mpt
    if page.get("_arc_polylines") is not None:  # the door reader's own arcs + chains, when it left them on the page
        segs, cands = np.zeros((0, 4)), [np.asarray(a, float) for a in page["_arc_polylines"] if len(a) >= 3]
    else:
        segs, arcs = po._segments(page)
        cands = [np.asarray(a, float) for a in arcs]
    cands += [np.asarray(p["pts"], float) for p in page.get("paths", [])
              if not p.get("closed") and not p.get("n_curves") and len(p.get("pts") or []) >= 4]
    if len(segs):
        # flattened arcs drawn as separate short segments: chain the short pieces inside the ROI only
        # (arc pieces are < ~0.3 m; this keeps the chaining a few % of the page's segments)
        L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
        mx, my = (segs[:, 0] + segs[:, 2]) / 2, (segs[:, 1] + segs[:, 3]) / 2
        k = (L < min(po.SHORT_SEG_PT, ARC_PIECE_M / mpt)) & (mx >= roi[0]) & (mx <= roi[2]) & (my >= roi[1]) & (my <= roi[3])
        if k.any():
            cands += _arc_chains(segs[k], po.MAX_TURN_DEG)
    out = []
    for pl in cands:
        if len(pl) < 3:
            continue
        xs, ys = pl[:, 0], pl[:, 1]
        if xs.max() < roi[0] or xs.min() > roi[2] or ys.max() < roi[1] or ys.min() > roi[3]:
            continue
        ext = max(xs.max() - xs.min(), ys.max() - ys.min())
        if ext > 2.2 * rmax or ext < 0.45 * rmin:  # a >= 60 deg arc of radius r spans >= r / 2
            continue
        c = _arc_of(pl, rmin, rmax)
        if c is None:
            continue
        cx, cy, r = c
        if not (roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]):
            continue
        if any(math.dist((cx, cy), k["c"]) < 0.1 * r and abs(r - k["r"]) < 0.1 * r for k in out):
            continue
        out.append({"c": (cx, cy), "r": r, "bbox": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]})
    return out


def _arc_hits(arcs, doors_pt, tol):
    """1.0 per arc whose hinge (circle centre) lies within tol of a door item (its polygon, bbox or hinge points,
    all page pt), or whose bbox overlaps a door bbox grown by tol."""
    out = []
    for a in arcs:
        (cx, cy), b = a["c"], a["bbox"]
        ok = False
        for d in doors_pt:
            x0, y0, x1, y1 = d["bbox"]
            if (x0 - tol <= cx <= x1 + tol and y0 - tol <= cy <= y1 + tol) or \
                    (b[0] <= x1 + tol and x0 - tol <= b[2] and b[1] <= y1 + tol and y0 - tol <= b[3]) or \
                    any(h and math.dist((cx, cy), h) <= tol for h in d["hinges"]):
                ok = True
                break
        out.append(1.0 if ok else 0.0)
    return np.array(out)


def _opening_part(page, pm, mpt, to_pt, wall_masks, grid):
    doors = []
    for i in _items(pm, "door"):
        b = [v for xy in to_pt([i["bbox_px"][:2], i["bbox_px"][2:]]) for v in xy]
        pr = i.get("props") or {}
        doors.append({"bbox": [min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])],
                      "hinges": [pr.get("hinge"), pr.get("hinge2")]})  # props hinge are page pt already
    walls = [to_pt(i["polygon_px"]) for i in _items(pm, "wall") if i.get("polygon_px")]
    if not walls:
        return None
    xs = [q[0] for p in walls for q in p]
    ys = [q[1] for p in walls for q in p]
    m = 0.5 / mpt
    roi = [min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m]
    try:
        arcs = door_arcs(page, mpt, roi)
    except Exception:
        arcs = []
    hit = _arc_hits(arcs, doors, ARC_MATCH_M / mpt)
    on = []
    if wall_masks is not None:
        Fd = _dil(wall_masks[1], int(round(0.3 / CELL_M)))
        for i in _items(pm, "window"):
            b = [v for xy in to_pt([i["bbox_px"][:2], i["bbox_px"][2:]]) for v in xy]
            (x0, y0), (x1, y1) = grid.cell(b[:2]), grid.cell(b[2:4])
            x0, y0 = max(0, int(min(x0, x1))), max(0, int(min(y0, y1)))
            x1, y1 = min(Fd.shape[1], int(max(x0, x1)) + 2), min(Fd.shape[0], int(max(y0, y1)) + 2)
            on.append(1.0 if x1 > x0 and y1 > y0 and Fd[y0:y1, x0:x1].any() else 0.0)  # window box touches a wall
    return {"arcs": hit, "win": np.array(on)}


def _open_score(arcs, win):
    parts = [float(a.mean()) for a in (arcs, win) if len(a)]
    return sum(parts) / len(parts) if parts else None


def assess(page: dict, planmap: dict, *, n_boot: int = 200, seed: int = 0, raw_walls: list | None = None,
           pdf_path=None, page_index: int = 0) -> dict:
    """Accuracy score (0..1) with a 95% bootstrap CI for planmap vs the PDF page it came from.
    raw_walls: pdf_vector.walls(page) if the caller already has it (computed here otherwise)."""
    mpt = float((planmap.get("scale") or {}).get("m_per_pt") or 0)
    to_pt, s = _to_pt(planmap, page)
    if raw_walls is None:
        try:
            from pipeline import pdf_vector
            raw_walls = pdf_vector.walls(page)
        except Exception:
            raw_walls = []
    if pdf_path is not None:
        page = {**page, "page_index": page_index}
    W = _wall_part(page, planmap, raw_walls, mpt, to_pt, pdf_path) if mpt > 0 else None
    R = _room_part(planmap, to_pt, W)
    S = _scale_part(planmap)
    O = _opening_part(page, planmap, mpt, to_pt, W["masks"] if W else None, W["grid"] if W else None) if mpt > 0 else None

    def overall(ws, rs, os_):
        comp = {"walls": ws, "rooms": rs, "scale": S["score"], "openings": os_}
        avail = {k: v for k, v in comp.items() if v is not None}
        tot = sum(WEIGHTS[k] for k in avail)
        return sum(WEIGHTS[k] * v for k, v in avail.items()) / tot if tot else 0.0

    ws = W["stats"]["score"] if W else 0.0
    RT = _room_terms(R) if R else {}
    rs = _room_score_t(RT) if R else 0.0
    no_printed = not R or not (~np.isnan(R["errs"])).any()
    os_ = _open_score(O["arcs"], O["win"]) if O else None
    score = overall(ws, rs, os_)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        bw = _wall_stats(W["tiles"][rng.integers(0, len(W["tiles"]), len(W["tiles"]))].sum(axis=0))["score"] \
            if W and len(W["tiles"]) else ws
        if R:
            ix = rng.integers(0, len(R["has"]), len(R["has"]))
            br = _room_score_t(_room_terms(R, ix))
            if no_printed:
                br = float(np.clip(br + rng.uniform(-ROOM_NO_PRINTED_U, ROOM_NO_PRINTED_U), 0, 1))
        else:
            br = rs
        bo = os_
        if O and os_ is not None:
            a, w = O["arcs"], O["win"]
            bo = _open_score(a[rng.integers(0, len(a), len(a))] if len(a) else a,
                             w[rng.integers(0, len(w), len(w))] if len(w) else w)
        boots.append(overall(bw, br, bo))
    lo, hi = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (score, score)

    rooms_out = None
    if R:
        e = R["errs"][~np.isnan(R["errs"])]
        rooms_out = {"n": int(len(R["has"])), "with_polygon": int(R["has"].sum()),
                     "polygon_fraction": round(float(R["has"].mean()), 4), "n_printed": int(len(e)),
                     "area_rel_err_median": round(float(np.median(e)), 4) if len(e) else None,
                     "area_rel_err_p90": round(float(np.percentile(e, 90)), 4) if len(e) else None,
                     **{k: round(v, 4) for k, v in RT.items() if k != "area"}, "score": round(rs, 4),
                     "no_printed_areas_uncertainty": ROOM_NO_PRINTED_U if no_printed else 0.0}
        if len(e) >= 2:
            meds = [float(np.median(e[rng.integers(0, len(e), len(e))])) for _ in range(n_boot)]
            rooms_out["area_rel_err_median_ci95"] = [round(float(np.percentile(meds, 2.5)), 4),
                                                     round(float(np.percentile(meds, 97.5)), 4)]
    open_out = None
    if O:
        open_out = {"door_arcs": int(len(O["arcs"])), "door_arcs_matched": int(O["arcs"].sum()),
                    "arc_match_fraction": round(float(O["arcs"].mean()), 4) if len(O["arcs"]) else None,
                    "windows": int(len(O["win"])), "windows_on_wall": int(O["win"].sum()),
                    "window_on_wall_fraction": round(float(O["win"].mean()), 4) if len(O["win"]) else None,
                    "score": None if os_ is None else round(os_, 4)}
    label, cap = _label(score), []
    if no_printed:
        cap.append("no printed room areas")
    if not O or (len(O["arcs"]) + len(O["win"])) < 3:
        cap.append("fewer than 3 openings to check")
    if cap and label == "high":
        label = "medium"
    out = {"score": round(score, 4), "ci95": [round(lo, 4), round(hi, 4)], "label": label, "label_capped_by": cap,
           "weights": dict(WEIGHTS), "n_boot": n_boot,
           "components": {"walls": W["stats"] if W else None, "rooms": rooms_out, "scale": S, "openings": open_out},
           "method": "no ground truth: plan map vs the PDF's own evidence (wall fills/outlines raster at 5 cm/px, "
                     "printed room areas, printed scale, door arcs); see pipeline/pdf_quality.py"}
    out["summary"] = summary(out)
    return out


def summary(q: dict) -> str:
    c = q["components"]
    bits = []
    if c["walls"]:
        bits.append(f"walls {c['walls']['score'] * 100:.0f}%")
    r = c["rooms"]
    if r:
        t = f"rooms {r['score'] * 100:.0f}% ({r['with_polygon']}/{r['n']} labelled rooms"
        if r["area_rel_err_median"] is not None:
            t += f", area within {r['area_rel_err_median'] * 100:.0f}% of printed"
        bits.append(t + ")")
    sc = c["scale"]
    bits.append(f"scale {sc['method']}" + (" (areas agree)" if sc.get("agree_2pct") else ""))
    lo, hi = q["ci95"]
    return (f"3D matches the drawing: {q['score'] * 100:.0f}% (95% CI {lo * 100:.0f}-{hi * 100:.0f}%), {q['label']}. "
            + ", ".join(bits).capitalize() + ".")


def overlay(q_masks, score_text: str, out_png: str):
    """Evidence vs final walls: green = matched, red = missed evidence, blue = extra, score in the corner."""
    from PIL import Image, ImageDraw
    E, F, O, outline = q_masks
    dE, dF = _dil(E, 1), _dil(F, 1)
    img = np.full(E.shape + (3,), 255, np.uint8)
    img[outline] = (200, 200, 200)
    img[O] = (255, 200, 80)
    img[E & ~dF] = (220, 30, 30)
    img[F & ~dE] = (40, 80, 230)
    img[(F & dE) | (E & dF)] = (30, 160, 60)
    im = Image.fromarray(img)
    if max(im.size) > 2400:
        k = 2400 / max(im.size)
        im = im.resize((max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))), Image.NEAREST)
    d = ImageDraw.Draw(im)
    lines = [score_text[i:i + 90] for i in range(0, len(score_text), 90)]
    d.rectangle([0, 0, 8 + 6 * 92, 6 + 12 * len(lines) + 14], fill=(255, 255, 255))
    for k, ln in enumerate(lines):
        d.text((4, 4 + 12 * k), ln, fill=(0, 0, 0))
    d.text((4, 4 + 12 * len(lines)), "green=matched red=missed evidence blue=extra orange=openings grey=outline",
           fill=(90, 90, 90))
    im.save(out_png)


def assess_with_overlay(page, planmap, out_png, **kw):
    """assess() plus the overlay PNG (recomputes the wall masks)."""
    q = assess(page, planmap, **kw)
    mpt = float(planmap["scale"]["m_per_pt"])
    to_pt, _ = _to_pt(planmap, page)
    raw = kw.get("raw_walls")
    if raw is None:
        from pipeline import pdf_vector
        raw = pdf_vector.walls(page)
    pg = {**page, "page_index": kw.get("page_index", 0)}
    W = _wall_part(pg, planmap, raw, mpt, to_pt, kw.get("pdf_path"))
    if W:
        overlay(W["masks"], q["summary"], out_png)
    return q
