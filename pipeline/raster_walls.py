"""Read filled walls from a bounded uint8 copy; return polygons in original page pixels."""
from __future__ import annotations

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Polygon
from shapely.ops import unary_union

MAX_SIDE = 1600


def _polys(mask, simplify=1.2, min_area=30):
    import cv2
    cs, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return []
    hier = hier[0]
    children = {}
    for i, entry in enumerate(hier):
        if entry[3] >= 0 and len(cs[i]) >= 3:
            children.setdefault(entry[3], []).append(cs[i].reshape(-1, 2))
    out = []
    for i, c in enumerate(cs):
        if hier[i][3] != -1 or len(c) < 3:
            continue
        p = Polygon(c.reshape(-1, 2), children.get(i, []))
        if not p.is_valid:
            p = p.buffer(0)
        p = p.simplify(simplify)
        for g in (p.geoms if p.geom_type == "MultiPolygon" else [p]):
            if g.geom_type == "Polygon" and g.area >= min_area:
                out.append(g)
    return out


def _content_crop(gray):
    """Trim a ruled title strip only when a blank gutter separates it from the drawing.

    Search the outer quarter: central empty bands can separate two real floor plans.
    A thin long border by itself is not enough evidence to discard drawing content.
    """
    import cv2
    h, w = gray.shape
    ink = (gray < 180).astype(np.uint8)
    # Ignore isolated text strokes, but retain title-block grid lines as evidence.
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(15, h // 30), 1), np.uint8))
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(15, w // 30)), np.uint8))
    x1, y1 = w, h
    for axis, size in ((0, w), (1, h)):
        density = ink.mean(axis=axis)
        quiet = density < 0.008
        runs = np.flatnonzero(np.diff(np.r_[False, quiet, False]))
        for a, b in zip(runs[::2], runs[1::2]):
            if a < 0.70 * size or b > 0.95 * size or b - a < max(3, size * 0.006):
                continue
            tail_v = vertical[:, b:] if axis == 0 else vertical[b:, :]
            tail_h = horizontal[:, b:] if axis == 0 else horizontal[b:, :]
            # A title strip contains both grid directions, including several ruled rows.
            ruled = tail_h.sum(axis=1) > max(10, tail_h.shape[1] * 0.35)
            rows = np.count_nonzero(np.diff(np.r_[False, ruled].astype(np.int8)) == 1)
            if tail_v.sum() > 0.3 * h and rows >= 4:
                if axis == 0:
                    x1 = a
                else:
                    y1 = a
                break
    return gray[:y1, :x1], (0, 0)


def read(gray: np.ndarray, mpp: float):
    import cv2
    if gray.ndim != 2 or not np.isfinite(mpp) or mpp <= 0:
        return None
    H, W = gray.shape
    if min(H, W) < 8:
        return None
    # Resize before converting legacy float callers: never allocate a full-sheet float copy.
    factor = min(1.0, MAX_SIDE / max(H, W))
    work = cv2.resize(gray, (max(1, round(W * factor)), max(1, round(H * factor))), interpolation=cv2.INTER_AREA) if factor < 1 else gray
    work = np.clip(work, 0, 255).astype(np.uint8) if work.dtype != np.uint8 else work.copy()
    sy, sx = H / work.shape[0], W / work.shape[1]
    work, (ox, oy) = _content_crop(work)
    h, w = work.shape
    local_mpp = mpp * (sx + sy) / 2
    paper = float(np.percentile(work, 70))
    dark = (work < min(110, 0.45 * paper)).astype(np.uint8)
    k = min(min(h, w), max(3, int(round(0.11 / local_mpp))))
    walls = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    frac = walls.mean()
    if not (0.004 < frac < 0.30):
        return None
    _, lab, stats, _ = cv2.connectedComponentsWithStats(walls, connectivity=8)
    accepted = stats[:, cv2.CC_STAT_AREA] >= max(60, 0.0004 * w * h)
    accepted[0] = False
    keep = accepted[lab].astype(np.uint8)
    if keep.sum() < 0.003 * w * h:
        return None
    wall_polys = _polys(keep)
    if not wall_polys:
        return None
    hull_px = unary_union(wall_polys).convex_hull
    floor = None
    for metres in (1.0, 1.8, 2.8, 4.0):
        kc = min(min(h, w), max(5, int(round(metres / local_mpp)) | 1))
        # Rectangular kernels are separable, unlike a full ellipse at sheet resolution.
        closed = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kc, kc)))
        pad = cv2.copyMakeBorder(closed, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        ff = pad.copy()
        cv2.floodFill(ff, None, (0, 0), 2)
        inside = ((ff != 2).astype(np.uint8))[1:-1, 1:-1]
        inside = cv2.morphologyEx(inside, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        fp = _polys(inside, simplify=2.0, min_area=0.01 * w * h)
        if fp:
            floor = unary_union([Polygon(g.exterior) for g in fp])
            if floor.area >= 0.55 * hull_px.area:
                break
    if floor is None or floor.area < 0.55 * hull_px.area:
        floor = hull_px
    g = 4.0 / local_mpp
    floor = floor.buffer(g).buffer(-g).union(floor).intersection(hull_px.buffer(2))
    if floor.geom_type != "Polygon":
        floor = unary_union([g for g in floor.geoms if g.geom_type == "Polygon"]) if hasattr(floor, "geoms") else hull_px
    restore = lambda p: affine_transform(p, [sx, 0, 0, sy, ox * sx, oy * sy])
    return {"walls": [restore(p) for p in wall_polys], "floor": restore(floor), "wall_frac": float(frac),
            "working_shape": [h, w], "crop_px": [ox * sx, oy * sy, (ox + w) * sx, (oy + h) * sy]}
