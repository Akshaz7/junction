"""Walls and floor outline read from the drawing's own pixels (raster plans), for the 3D scene.

Thick dark fills are walls; a morphological open drops text, dimension lines and furniture strokes. The floor is
everything the walls enclose (a big closing bridges door gaps, then outside is flood-filled away).
Returns shapely polygons in page pixels, or None when the page does not look like a wall-fill drawing.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union


def _polys(mask, simplify=1.2, min_area=30):
    import cv2
    cs, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return []
    hier = hier[0]
    out = []
    for i, c in enumerate(cs):
        if hier[i][3] != -1 or len(c) < 3:
            continue
        holes = [cs[j].reshape(-1, 2) for j in range(len(cs)) if hier[j][3] == i and len(cs[j]) >= 3]
        p = Polygon(c.reshape(-1, 2), [h for h in holes])
        if not p.is_valid:
            p = p.buffer(0)
        p = p.simplify(simplify)
        for g in (p.geoms if p.geom_type == "MultiPolygon" else [p]):
            if g.geom_type == "Polygon" and g.area >= min_area:
                out.append(g)
    return out


def read(gray: np.ndarray, mpp: float):
    import cv2
    H, W = gray.shape
    paper = float(np.percentile(gray, 70))
    dark = (gray < min(110, 0.45 * paper)).astype(np.uint8)
    k = max(3, int(round(0.11 / mpp)))
    k += (k + 1) % 2 * 0  # keep as is
    walls = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    frac = walls.mean()
    if not (0.004 < frac < 0.30):
        return None
    n, lab, stats, _ = cv2.connectedComponentsWithStats(walls, connectivity=8)
    keep = np.zeros_like(walls)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= max(60, 0.0004 * W * H):
            keep[lab == i] = 1
    if keep.sum() < 0.003 * W * H:
        return None
    wall_polys = _polys(keep)
    # floor: close door gaps, then everything not reachable from the border is inside. Wider closings are tried
    # until the result covers most of the walls' hull (an open doorway otherwise lets "outside" flood the rooms).
    hull_px = unary_union(wall_polys).convex_hull
    floor = None
    for metres in (1.0, 1.8, 2.8, 4.0):
        kc = max(5, int(round(metres / mpp)) | 1)
        closed = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc)))
        pad = cv2.copyMakeBorder(closed, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        ff = pad.copy()
        cv2.floodFill(ff, np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8), (0, 0), 2)
        inside = ((ff != 2).astype(np.uint8))[1:-1, 1:-1]
        inside = cv2.morphologyEx(inside, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        fp = _polys(inside, simplify=2.0, min_area=0.01 * W * H)
        if fp:
            floor = unary_union([Polygon(g.exterior) for g in fp])  # fill holes: wall rings are solid floor too
            if floor.area >= 0.55 * hull_px.area:
                break
    if floor is None or floor.area < 0.55 * hull_px.area:
        floor = hull_px
    # a wide closing bulges out through doorways: keep the floor inside the walls' own footprint hull
    g = 4.0 / mpp
    floor = floor.buffer(g).buffer(-g).union(floor).intersection(hull_px.buffer(2))
    if floor.geom_type != "Polygon":
        floor = unary_union([g for g in floor.geoms if g.geom_type == "Polygon"]) if hasattr(floor, "geoms") else hull_px
    return {"walls": wall_polys, "floor": floor, "wall_frac": float(frac)}
