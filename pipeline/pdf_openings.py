"""Doors, windows and the plan / non-plan gate for vector (CAD-exported) PDF pages.

Coordinates: page points, top-left origin, y down (the `pipeline.pdf_vector.load_page` frame).

openings(page, walls) -> [{"kind": "door"|"window", "polygon": [[x,y],...], "bbox": [x0,y0,x1,y1], "conf", "props"}]
  Doors: a quarter-circle swing (a Bezier arc, or CAD's flattening of it into many short lines) with radius in the
  door range, optionally a leaf line from the hinge; the polygon is the door gap across the wall (hinge -> closed
  end, wall thickness deep). props: width_pt, swing ("cw"|"ccw"), hinge, leaf (bool), double (bool), radius_pt.
  Windows: 2-4 short parallel lines (glazing / sill) of equal extent packed into wall thickness, inside a wall run
  (ends touch wall shapes) or, with no walls known, 3-4 lines. props: width_pt, n_lines, depth_pt, angle_deg.
gate(page, walls, rooms) -> (is_plan: bool, reason: str)
No per-document constants; sizes are in points with a scale-free range, tightened by wall thickness when known.
"""
from __future__ import annotations

import math
import os
import re
import statistics
from collections import defaultdict

import numpy as np

# door swing radius range in points, scale-free first pass (0.6-1.2 m spans ~15-60 pt at 1:50..1:100,
# ~60-130 pt at 1/4"=1'..3/8"=1'); tightened below by the wall thickness when walls are known
R_MIN_PT, R_MAX_PT = 10.0, 140.0
SHORT_SEG_PT = 35.0          # flattened-arc segments are shorter than this
MAX_TURN_DEG = 32.0          # turn between consecutive segments of a flattened arc
HEADING = re.compile(r"\b(elevations?|sections?|schedules?|details?|ansicht(?:en)?|schnitt(?:e)?|"
                     r"julkisivu(?:t)?|leikkau(?:s|kset))\b", re.I)
AREA_WORD = re.compile(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:m²|m2|㎡)", re.I)


# ---------------------------------------------------------------- geometry helpers
def _bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _poly_area(p):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]))) / 2


def _fit_circle(pts):
    """Algebraic (Kasa) circle fit -> (cx, cy, r, rms) or None."""
    a = np.asarray(pts, float)
    if len(a) < 3:
        return None
    A = np.c_[2 * a[:, 0], 2 * a[:, 1], np.ones(len(a))]
    b = (a ** 2).sum(1)
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = sol
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    d = np.hypot(a[:, 0] - cx, a[:, 1] - cy)
    return float(cx), float(cy), r, float(np.sqrt(((d - r) ** 2).mean()))


def _bezier(p0, p1, p2, p3, n=8):
    t = np.linspace(0, 1, n + 1)[:, None]
    p0, p1, p2, p3 = (np.asarray(p, float) for p in (p0, p1, p2, p3))
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3).tolist()


def _path_polyline(p):
    """Sampled polyline of a path: evaluates Bezier segments when the raw segments are present."""
    segs = p.get("segs")
    if segs:
        out, cur = [], None
        for op, q in segs:
            if op == "m" and q:
                cur = q[0]; out.append(cur)
            elif op == "l" and q and cur is not None:
                cur = q[0]; out.append(cur)
            elif op == "c" and len(q) == 3 and cur is not None:
                out.extend(_bezier(cur, q[0], q[1], q[2])[1:]); cur = q[2]
            elif op in ("v", "y") and len(q) == 2 and cur is not None:
                c1, c2 = (cur, q[0]) if op == "v" else (q[0], q[1])
                out.extend(_bezier(cur, c1, c2, q[1])[1:]); cur = q[1]
        if len(out) >= 2:
            return out
    return [list(map(float, q)) for q in p["pts"]]


def _segments(page):
    """All straight pieces of open strokes: (x0, y0, x1, y1) array, plus Bezier-arc polylines."""
    segs, arcs = [], []
    for p in page.get("paths", []):
        if p.get("fill") is not None and p.get("stroke") is None:
            continue  # pure fills (wall poche, hatch blocks) are not door / window linework
        if p.get("is_arc") or p.get("n_curves", 0) > 0:
            pl = _path_polyline(p)
            if len(pl) >= 3:
                arcs.append(pl)
            continue
        pts = p["pts"]
        if p.get("closed") and len(pts) > 2:
            pts = list(pts) + [pts[0]]
        for a, b in zip(pts, pts[1:]):
            if a[0] != b[0] or a[1] != b[1]:
                segs.append((a[0], a[1], b[0], b[1]))
    return np.asarray(segs, float).reshape(-1, 4), arcs


def _chains(segs, tol=0.15):
    """Smooth chains of short segments (flattened arcs): polylines whose joints turn < MAX_TURN_DEG, one way."""
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    idx = np.nonzero((L > 0.05) & (L < SHORT_SEG_PT))[0]
    S = {}                                        # python floats: per-element numpy indexing is the slow part
    K = np.round(segs[idx] / tol).astype(np.int64).tolist()
    at = defaultdict(list)
    keys = {}
    for i, k4, row in zip(idx.tolist(), K, segs[idx].tolist()):
        S[i] = row
        a, b = (k4[0], k4[1]), (k4[2], k4[3])
        keys[(i, 0)], keys[(i, 1)] = a, b
        at[a].append((i, 0)); at[b].append((i, 1))
    idx = idx.tolist()
    cos_max = math.cos(math.radians(MAX_TURN_DEG))
    used = set()

    def nxt(i, end, sign):
        """segment continuing segment i past its endpoint `end` (0/1) smoothly; returns (j, far_end, cross)."""
        x0, y0, x1, y1 = S[i]
        px, py = (x1, y1) if end == 1 else (x0, y0)
        dx, dy = (x1 - x0, y1 - y0) if end == 1 else (x0 - x1, y0 - y1)
        n = math.hypot(dx, dy); dx /= n; dy /= n
        best = None
        for j, e in at.get(keys[(i, end)], []):
            if j == i or j in used:
                continue
            a0, b0, a1, b1 = S[j]
            ex, ey = (a1 - a0, b1 - b0) if e == 0 else (a0 - a1, b0 - b1)
            m = math.hypot(ex, ey); ex /= m; ey /= m
            c = dx * ex + dy * ey
            cr = dx * ey - dy * ex
            if c < cos_max or c > 0.99995:   # straight continuation is a line, not an arc
                continue
            if sign and cr * sign < 0:
                continue
            if best is None or c > best[3]:
                best = (j, 1 - e, cr, c)
        return best

    out = []
    for i in idx:
        if i in used:
            continue
        used.add(i)
        x0, y0, x1, y1 = S[i]
        pts = [[x0, y0], [x1, y1]]
        for end, front in ((1, False), (0, True)):
            cur, ce, sign = i, end, 0.0
            while True:
                r = nxt(cur, ce, sign)
                if r is None:
                    break
                j, fe, cr, _ = r
                used.add(j)
                sign = sign or (1.0 if cr > 0 else -1.0)
                q = S[j][2:] if fe == 1 else S[j][:2]
                if front:
                    pts.insert(0, [float(q[0]), float(q[1])])
                else:
                    pts.append([float(q[0]), float(q[1])])
                cur, ce = j, fe
            if front is False:
                first_sign = sign
        if len(pts) >= 4:
            out.append(pts)
    return out


class _WallIndex:
    def __init__(self, walls):
        self.walls = walls or []
        self.tree = None
        self.polys = []
        self.ids = []
        if self.walls:
            from shapely.geometry import Polygon
            from shapely.strtree import STRtree
            for wi_, w in enumerate(self.walls):
                try:
                    g = Polygon(w["polygon"])
                    if not g.is_valid:
                        g = g.buffer(0)
                except Exception:
                    continue
                if not g.is_empty:
                    self.polys.append((g, float(w.get("thickness_pt") or 0)))
                    self.ids.append(wi_)
            if self.polys:
                self.tree = STRtree([g for g, _ in self.polys])
        th = [t for _, t in self.polys if t > 0]
        self.t_med = float(np.median(th)) if th else None

    def run_end(self, e, out_dir, n, o0, o1, rr):
        """A wall shape continues the run beyond end point e: it lies outward along out_dir and spans the
        pack's offset range [o0, o1] across the wall (so the glazing sits in a gap of that wall)."""
        if self.tree is None:
            return False
        from shapely.geometry import Point
        pt = Point(*e)
        depth = max(o1 - o0, 0.5)
        for k in self.tree.query(pt.buffer(rr)):
            g, t = self.polys[int(k)]
            if g.distance(pt) > rr:
                continue
            xy = np.asarray(g.exterior.coords) if hasattr(g, "exterior") else None
            if xy is None or not len(xy):
                continue
            al = (xy[:, 0] - e[0]) * out_dir[0] + (xy[:, 1] - e[1]) * out_dir[1]
            of = xy[:, 0] * n[0] + xy[:, 1] * n[1]
            if al.max() < 0.8 * depth:          # not extending outward
                continue
            lo, hi = of.min(), of.max()
            ov = min(hi, o1) - max(lo, o0)
            if ov >= 0.6 * depth and (hi - lo) <= 2.5 * depth + 1.0:
                return True
        return False

    def band(self, hinge, closed, u, n, r):
        """Wall band across a door gap: probe lines along n just outside each end of the gap (inside the jamb
        walls); returns ((lo, hi) offsets along n from the hinge line, wall index) or (None, None)."""
        if self.tree is None:
            return None, None
        from shapely.geometry import LineString
        per = []   # (interval, wall index) found beyond each end of the gap
        for (px, py), sg in ((hinge, -1), (closed, 1)):
            best, ix = None, None
            ox, oy = px + u[0] * sg * 0.06 * r, py + u[1] * sg * 0.06 * r
            ln = LineString([(ox - n[0] * r, oy - n[1] * r), (ox + n[0] * r, oy + n[1] * r)])
            for k in self.tree.query(ln):
                g = self.polys[int(k)][0]
                xs = g.intersection(ln)
                for part in getattr(xs, "geoms", [xs]):
                    if part.is_empty or part.geom_type != "LineString":
                        continue
                    offs = [(x - hinge[0]) * n[0] + (y - hinge[1]) * n[1] for x, y in part.coords]
                    lo, hi = min(offs), max(offs)
                    if lo - 0.15 * r <= 0 <= hi + 0.15 * r or abs(lo) < 0.15 * r or abs(hi) < 0.15 * r:
                        if best is None:
                            best, ix = [lo, hi], self.ids[int(k)]
                        else:
                            best = [min(best[0], lo), max(best[1], hi)]
            if best:
                per.append((best, ix))
        if not per:
            return None, None
        if len(per) == 2:
            (a, ia), (b, ib) = per
            la, lb = a[1] - a[0], b[1] - b[0]
            # one end reads a partition meeting the wall at the jamb (its length along n): trust the thinner end
            if max(la, lb) > 1.6 * min(la, lb) + 0.05 * r:
                return tuple(a if la < lb else b), (ia if la < lb else ib)
            return (min(a[0], b[0]), max(a[1], b[1])), ia
        return tuple(per[0][0]), per[0][1]

    def near(self, x, y, d):
        """[(dist, thickness)] of wall shapes within d of (x, y)."""
        if self.tree is None:
            return []
        from shapely.geometry import Point
        pt = Point(x, y)
        res = []
        for k in self.tree.query(pt.buffer(d)):
            g, t = self.polys[int(k)]
            dd = g.distance(pt)
            if dd <= d:
                res.append((dd, t))
        return sorted(res)


# ---------------------------------------------------------------- doors
def _arc_door(pl, wi: _WallIndex, rmin, rmax):
    c = _fit_circle(pl)
    if c is None:
        return None
    cx, cy, r, rms = c
    if not (rmin <= r <= rmax) or rms > 0.04 * r:
        return None
    ang = [math.atan2(p[1] - cy, p[0] - cx) for p in pl]
    a = np.unwrap(np.asarray(ang))
    span = abs(math.degrees(a[-1] - a[0]))
    if not (25 <= span <= 110):
        return None  # partial swings (25-70 deg, e.g. a leaf drawn at 45 deg) need their leaf line (checked later)
    if not np.all(np.diff(a) * np.sign(a[-1] - a[0]) > -1e-6):
        return None
    return {"c": (cx, cy), "r": r, "rms": rms, "ends": (pl[0], pl[-1]), "ccw": bool(a[-1] > a[0]), "pts": pl,
            "span": span}





def _wall_line_hits(wi, h, e, r):
    """Wall shapes met on the line hinge h -> arc end e beyond the end (1.1-1.6 r) and behind the hinge
    (0.3-0.7 r): the line a closed door leaf lies on continues as wall on both sides of the opening."""
    ux, uy = (e[0] - h[0]) / r, (e[1] - h[1]) / r
    n = 0
    for t in (1.1, 1.25, 1.4, 1.55, -0.3, -0.5, -0.7):
        if wi.near(h[0] + ux * t * r, h[1] + uy * t * r, 0.05 * r):
            n += 1
    return n

def _leaf_end(arc, segs, wi=None):
    """Which arc end the door leaf line reaches (the open position), or None when no leaf line is drawn.
    When both ends have a line from the hinge (a threshold / wall-face line runs hinge -> closed end), the open end
    is the one whose hinge line lies farther from the wall shapes (the closed position lies in the wall gap)."""
    if not len(segs):
        return None
    cx, cy = arc["c"]; r = arc["r"]
    tol = max(0.6, 0.06 * r)
    best = None
    exact = []
    for k, (ex, ey) in enumerate(arc["ends"]):
        for (p, q) in ((segs[:, :2], segs[:, 2:]), (segs[:, 2:], segs[:, :2])):
            ok = (np.hypot(p[:, 0] - cx, p[:, 1] - cy) < tol) & (np.hypot(q[:, 0] - ex, q[:, 1] - ey) < tol)
            if ok.any():
                exact.append(k)
                break
    if len(exact) == 1:
        return exact[0]
    if len(exact) == 2:
        if wi is None or wi.tree is None:
            return exact[0]
        # the closed end meets the far jamb: a wall shape continues just beyond it, along hinge -> end;
        # beyond the open leaf's tip lies the room
        jamb = []
        for ex, ey in arc["ends"]:
            bx, by = ex + (ex - cx) * 0.15, ey + (ey - cy) * 0.15
            jamb.append(bool(wi.near(bx, by, 0.1 * r)))
        if jamb[0] != jamb[1]:
            return 1 if jamb[0] else 0
        # no jamb right at either end (a door in a glazed facade bay): the closed line lies on the wall's own line,
        # so walls continue on that line further on and behind the hinge; the open leaf points off it
        sc = [_wall_line_hits(wi, (cx, cy), e, r) for e in arc["ends"]]
        if sc[0] != sc[1]:
            return 1 if sc[0] > sc[1] else 0
        return exact[0]
    for k, (ex, ey) in enumerate(arc["ends"]):
        for (p, q) in ((segs[:, :2], segs[:, 2:]), (segs[:, 2:], segs[:, :2])):
            # leaf drawn as a thin rectangle: a side running hinge-ish -> end-ish of length ~r
            L = np.hypot(q[:, 0] - p[:, 0], q[:, 1] - p[:, 1])
            ok2 = (np.abs(L - r) < 0.12 * r) & (np.hypot(q[:, 0] - ex, q[:, 1] - ey) < 0.12 * r) & \
                  (np.hypot(p[:, 0] - cx, p[:, 1] - cy) < 0.12 * r)
            if ok2.any() and best is None:
                best = k
    return best


def _radial_lines(arc, segs):
    """Lines (longer than 0.3 r) that point at the arc centre from inside the circle (ends within 0.06 r of the
    centre or the line passes through it)."""
    if not len(segs):
        return 0
    cx, cy = arc["c"]; r = arc["r"]
    x0, y0, x1, y1 = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    L = np.hypot(x1 - x0, y1 - y0)
    near = (np.hypot(x0 - cx, y0 - cy) < 1.05 * r) & (np.hypot(x1 - cx, y1 - cy) < 1.05 * r) & (L > 0.3 * r)
    if not near.any():
        return 0
    k = np.nonzero(near)[0]
    # distance from the centre to the infinite line through the segment
    d = np.abs((x1[k] - x0[k]) * (y0[k] - cy) - (x0[k] - cx) * (y1[k] - y0[k])) / L[k]
    ang = np.round(np.degrees(np.arctan2(y1[k] - y0[k], x1[k] - x0[k])) % 180 / 5)
    return len(set(ang[d < 0.06 * r].tolist()))


def _tangent_ends(arc, segs):
    """Number of arc ends that run on tangentially into a straight line (a rounded corner / fillet / curved wall,
    not a door swing, whose ends meet the leaf radially and the jamb end-on)."""
    if not len(segs):
        return 0
    cx, cy = arc["c"]; r = arc["r"]
    tol = max(0.6, 0.04 * r)
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    dx = (segs[:, 2] - segs[:, 0]) / np.maximum(L, 1e-9); dy = (segs[:, 3] - segs[:, 1]) / np.maximum(L, 1e-9)
    n = 0
    for ex, ey in arc["ends"]:
        rx, ry = (ex - cx) / r, (ey - cy) / r          # radial unit; the tangent is (-ry, rx)
        touch = (np.hypot(segs[:, 0] - ex, segs[:, 1] - ey) < tol) | (np.hypot(segs[:, 2] - ex, segs[:, 3] - ey) < tol)
        par = np.abs(dx * -ry + dy * rx) > 0.985
        if np.any(touch & par & (L > 0.25 * r)):
            n += 1
    return n


def _door_from_arc(arc, leaf_k, wi: _WallIndex):
    cx, cy = arc["c"]; r = arc["r"]
    k_open = leaf_k if leaf_k is not None else None
    if arc.get("double_acting"):
        k_open = 1 - arc["closed_k"]
    # the closed end lies along the wall; with no leaf line, pick the end closer to a wall shape
    if k_open is None:
        d = [wi.near(e[0], e[1], 0.5 * r) for e in arc["ends"]]
        d = [x[0][0] if x else 1e9 for x in d]
        k_open = 0 if d[1] < d[0] else 1
    closed = arc["ends"][1 - k_open]
    opened = arc["ends"][k_open]
    ux, uy = (closed[0] - cx) / r, (closed[1] - cy) / r
    nx, ny = -uy, ux
    # wall lies on the side opposite the open leaf
    side = -1.0 if (opened[0] - cx) * nx + (opened[1] - cy) * ny > 0 else 1.0
    near = sorted(wi.near((cx + closed[0]) / 2, (cy + closed[1]) / 2, 0.6 * r) + wi.near(cx, cy, 0.3 * r)
                  + wi.near(closed[0], closed[1], 0.3 * r))
    t = near[0][1] if near and near[0][1] > 0 else (wi.t_med or 0.12 * r)
    t = min(max(t, 0.04 * r), 0.6 * r)
    # snap across the wall: the jamb walls just beyond the hinge and the closed end give the wall band [lo, hi]
    # (offsets along n from the hinge line), so the opening spans exactly the wall thickness
    band, wall_ix = wi.band((cx, cy), (closed[0], closed[1]), (ux, uy), (nx, ny), r)
    t_host = near[0][1] if near and near[0][1] > 0 else None
    # a band far thicker than the wall the door sits in comes from a partition meeting the wall at the jamb
    # (its length along n read as wall depth): the opening then spans the host wall only
    thick = t_host is not None and band and band[1] - band[0] > 1.6 * t_host + 0.05 * r
    if band and not thick and 0.02 * r <= band[1] - band[0] <= 0.8 * r and band[0] <= 0.15 * r and band[1] >= -0.15 * r:
        lo, hi = band
        t = hi - lo
    else:
        lo, hi = (0.0, t) if side > 0 else (-t, 0.0)
        wall_ix = None
    q = [[cx + nx * lo, cy + ny * lo], [closed[0] + nx * lo, closed[1] + ny * lo],
         [closed[0] + nx * hi, closed[1] + ny * hi], [cx + nx * hi, cy + ny * hi]]
    # leaf swings to the side of the opened end: +n or -n relative to the hinge -> closed axis
    swing_side = 1 if (opened[0] - cx) * nx + (opened[1] - cy) * ny > 0 else -1
    return {"hinge": [cx, cy], "closed": list(closed), "opened": list(opened), "r": r, "t": t, "poly": q,
            "axis": (ux, uy), "swing_side": swing_side, "wall": wall_ix, "band": (lo, hi),
            "near_wall": bool(near), "leaf": leaf_k is not None, "ccw": arc["ccw"],
            "double_acting": bool(arc.get("double_acting"))}


def page_m_per_pt(page):
    """Metres per point: from the caller (page['m_per_pt'] / page['scale']) or the printed 1:N / 3/8"=1'-0"."""
    v = page.get("m_per_pt") or (page.get("scale") or {}).get("m_per_pt")
    if v:
        return float(v), "given"
    try:
        from engine.scale_text import ratio_and_sheet
        ratio, _ = ratio_and_sheet(page.get("words", []))
    except Exception:
        ratio = None
    if ratio:
        return 0.0254 / 72 * ratio, f"printed 1:{ratio}"
    return None, None


def _door_range(page):
    mpp, src = page_m_per_pt(page)
    if mpp:  # a door leaf is 0.6-1.2 m; allow 0.45 (double-door leaves) .. 1.35
        return 0.45 / mpp, 1.35 / mpp, src
    return R_MIN_PT, R_MAX_PT, "scale-free"


def _left_of(d):
    """Left-hand unit vector of a page-frame direction d (y down), as seen by someone facing d on the floor."""
    return (d[1], -d[0])


def _swing_operation(d, dbl):
    """IFC door operation from the swing geometry (page frame, y down).
    swing_dir = unit normal to the wall toward the side the leaf opens into (IFC local +y of the door);
    hinge_side = side of the hinge as seen facing swing_dir (IFC: 'as viewed in the direction of the positive y-axis');
    x_dir = unit vector along the wall from the opening's left jamb to its right jamb (seen facing swing_dir)."""
    hx, hy = d["hinge"]
    ux, uy = d["axis"]                        # hinge -> closed end, along the wall
    sd = d["swing_side"]
    nx, ny = -uy * sd, ux * sd                # toward the opened leaf
    L = _left_of((nx, ny))
    hinge_left = (-ux) * L[0] + (-uy) * L[1] > 0
    out = {"swing_dir": [round(nx, 4), round(ny, 4)], "x_dir": [round(-L[0], 4), round(-L[1], 4)]}
    if dbl:
        out.update(operation="DOUBLE_DOOR_SINGLE_SWING", hinge_side="both")
    elif d.get("double_acting"):
        out.update(operation="DOUBLE_SWING_LEFT" if hinge_left else "DOUBLE_SWING_RIGHT",
                   hinge_side="left" if hinge_left else "right", double_acting=True)
    else:
        out.update(operation="SINGLE_SWING_LEFT" if hinge_left else "SINGLE_SWING_RIGHT",
                   hinge_side="left" if hinge_left else "right")
    out["operation_source"] = "swing arc"
    return out



def _wall_dirs(wi: _WallIndex, min_len_ratio=3.0):
    """Axis directions (deg mod 180) of the wall shapes (long side of each elongated wall polygon)."""
    out = []
    for g, _ in wi.polys:
        try:
            cs = list(g.minimum_rotated_rectangle.exterior.coords)
        except Exception:  # noqa: BLE001
            continue
        if len(cs) < 4:
            continue
        a = math.dist(cs[0], cs[1]); b = math.dist(cs[1], cs[2])
        if min(a, b) <= 0 or max(a, b) < min_len_ratio * min(a, b):
            continue
        p, q = (cs[0], cs[1]) if a >= b else (cs[1], cs[2])
        out.append(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180.0)
    return out


def _snap_door(d, wall_deg):
    """Door d re-laid along wall direction `wall_deg`: same hinge, same leaf radius (both measured), closed end
    on the wall line on the side the drawn closed end lies, opening band of the same depth on the wall side."""
    d = dict(d)
    a = math.radians(wall_deg)
    ux, uy = math.cos(a), math.sin(a)
    h, c0, op = d["hinge"], d["closed"], d["opened"]
    if (c0[0] - h[0]) * ux + (c0[1] - h[1]) * uy < 0:
        ux, uy = -ux, -uy
    r, t = d["r"], d["t"]
    nx, ny = -uy, ux
    lo, hi = (-t, 0.0) if (op[0] - h[0]) * nx + (op[1] - h[1]) * ny > 0 else (0.0, t)
    c = [h[0] + ux * r, h[1] + uy * r]
    d["poly"] = [[h[0] + nx * lo, h[1] + ny * lo], [c[0] + nx * lo, c[1] + ny * lo],
                 [c[0] + nx * hi, c[1] + ny * hi], [h[0] + nx * hi, h[1] + ny * hi]]
    d["axis"], d["closed"], d["band"], d["snapped"] = (ux, uy), c, (lo, hi), True
    return d


def _on_wall_dir(poly, wdirs, tol_deg=10.0):
    """The long side of an opening polygon runs along one of the wall directions (or the polygon is ~square)."""
    from shapely.geometry import Polygon
    cs = list(Polygon(poly).minimum_rotated_rectangle.exterior.coords)
    if len(cs) < 4:
        return True
    a = math.dist(cs[0], cs[1]); b = math.dist(cs[1], cs[2])
    if max(a, b) < 1.5 * min(a, b):
        return True
    p, q = (cs[0], cs[1]) if a >= b else (cs[1], cs[2])
    da = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180.0
    return min(min(abs(da - w), 180.0 - abs(da - w)) for w in wdirs) <= tol_deg

BIG_LEAF = 1.22 if os.environ.get("PDF_DOORS_WIDE", "1") != "0" else 1.0   # 1.35 m -> 1.65 m leaves, double doors only


def _doors(page, segs, arcs, wi: _WallIndex):
    rmin, rmax, _ = _door_range(page)
    mpp = page_m_per_pt(page)[0]
    polys = arcs + (_chains(segs) if len(segs) else [])
    try:  # pdf_quality.door_arcs reuses these instead of re-chaining the page (~12 s on big sheets)
        page["_arc_polylines"] = polys
    except Exception:
        pass
    # leaves up to BIG_LEAF x the single-door limit are read too, but kept only as one leaf of a double door
    # (wide double doors into halls / conference rooms: 2 x 1.5 m leaves); a lone big arc is not a door
    cands = [_arc_door(pl, wi, rmin, rmax * BIG_LEAF) for pl in polys]
    cands = [c for c in cands if c]
    # de-duplicate (the same arc drawn twice, or a Bezier + its flattening)
    cands.sort(key=lambda c: c["rms"] / c["r"])
    keep = []
    for c in cands:
        dup = [k for k in keep if math.dist(c["c"], k["c"]) < 0.1 * c["r"] and abs(c["r"] - k["r"]) < 0.1 * c["r"]]
        if dup:
            # double-acting door: a second swing from the same hinge, mirrored across the wall (the two arcs share
            # the closed end and open to opposite sides); the same arc drawn twice shares both ends
            k = dup[0]
            shared = [(i, j) for i in range(2) for j in range(2) if math.dist(c["ends"][i], k["ends"][j]) < 0.12 * c["r"]]
            if len(shared) == 1:
                i, j = shared[0]
                oc, ok_ = c["ends"][1 - i], k["ends"][1 - j]
                if math.dist(oc, ok_) > 1.6 * c["r"]:
                    k["double_acting"] = True
                    k["closed_k"] = j
            continue
        keep.append(c)
    doors = []
    if len(segs):
        seg_x0 = np.minimum(segs[:, 0], segs[:, 2]); seg_x1 = np.maximum(segs[:, 0], segs[:, 2])
        seg_y0 = np.minimum(segs[:, 1], segs[:, 3]); seg_y1 = np.maximum(segs[:, 1], segs[:, 3])
    for arc in keep:
        # only segments near this arc matter to the leaf / radial / tangent tests (all within ~1.1 r of the centre)
        cx_, cy_ = arc["c"]; R_ = 1.3 * arc["r"] + 1.0
        sub = segs[(seg_x0 <= cx_ + R_) & (seg_x1 >= cx_ - R_) & (seg_y0 <= cy_ + R_) & (seg_y1 >= cy_ - R_)] \
            if len(segs) else segs
        if _radial_lines(arc, sub) >= 5:
            continue  # spiral stair / fan symbol: many lines radiate from the centre, a hinge has 1-2
        leaf = _leaf_end(arc, sub, wi)
        if arc.get("span", 90) < 70 and (leaf is None or wi.tree is None):
            continue  # a partial swing counts only with its leaf line, at a wall
        tang = _tangent_ends(arc, sub)
        if tang >= 2 or (tang == 1 and leaf is None):
            continue  # rounded corner / fillet / curved wall
        dd = _door_from_arc(arc, leaf, wi)
        if arc["r"] > rmax and dd["t"] > 0.3 * rmax:   # wide leaf: its r-relative wall band can reach into the room
            t = min(wi.t_med or 0.12 * rmax, 0.3 * rmax)
            lo = dd["band"][0] if dd["band"][0] > -0.15 * arc["r"] else -t
            lo = max(lo, -t)
            h, c_, (ux, uy) = dd["hinge"], dd["closed"], dd["axis"]
            nx, ny = -uy, ux
            dd["poly"] = [[h[0] + nx * lo, h[1] + ny * lo], [c_[0] + nx * lo, c_[1] + ny * lo],
                          [c_[0] + nx * (lo + t), c_[1] + ny * (lo + t)], [h[0] + nx * (lo + t), h[1] + ny * (lo + t)]]
            dd["t"], dd["band"] = t, (lo, lo + t)
        if wi.tree is not None and not dd["near_wall"] and not dd["leaf"]:
            continue  # with walls known, a swing that touches no wall is furniture / a symbol
        doors.append(dd)
    # double doors: two leaves whose closed ends meet
    used, out = set(), []
    for i, a in enumerate(doors):
        if i in used:
            continue
        pair = None
        for j in range(i + 1, len(doors)):
            b = doors[j]
            if j in used:
                continue
            # two leaves in one wall gap closing toward each other: hinges 0.6-2.4 m apart on the wall axis,
            # the leaves (possibly unequal) together spanning the hinge distance
            D = math.dist(a["hinge"], b["hinge"])
            big = BIG_LEAF > 1.0 and min(a["r"], b["r"]) > 0.9 * rmax   # two wide leaves: the pair may span more than 2.4 m
            lo_d, hi_d = (0.6 / mpp, 2.2 * max(a["r"], b["r"]) if big else 2.4 / mpp) if mpp else \
                (1.2 * min(a["r"], b["r"]), 3.2 * max(a["r"], b["r"]))
            if not (lo_d <= D <= hi_d):
                continue
            hx, hy = (b["hinge"][0] - a["hinge"][0]) / D, (b["hinge"][1] - a["hinge"][1]) / D
            if a["axis"][0] * hx + a["axis"][1] * hy < 0.97 or -(b["axis"][0] * hx + b["axis"][1] * hy) < 0.97:
                continue
            if abs(a["r"] + b["r"] - D) > 0.2 * D:
                continue
            pair = j; break
        if pair is None:
            if a["r"] <= rmax * 1.001:
                out.append((a, False))
        else:
            used.add(pair)
            b = doors[pair]
            # one opening across the wall for both leaves: oriented rectangle around both leaves' openings
            from shapely.geometry import MultiPoint
            mr = MultiPoint([tuple(v) for v in a["poly"] + b["poly"]]).minimum_rotated_rectangle
            q = [list(v) for v in list(mr.exterior.coords)[:4]]
            m = dict(a); m["poly"] = q; m["r2"] = b["r"]; m["leaf"] = a["leaf"] or b["leaf"]
            m["D"] = math.dist(a["hinge"], b["hinge"]); m["hinge2"] = b["hinge"]
            out.append((m, True))
    res = []
    wdirs = _wall_dirs(wi)
    for d, dbl in out:
        if wdirs:   # a door lies in a wall: its axis runs along some wall direction of the sheet (10 deg)
            da = math.degrees(math.atan2(d["axis"][1], d["axis"][0])) % 180.0
            off = [(min(abs(da - w), 180.0 - abs(da - w)), w) for w in wdirs]
            dev, wd = min(off)
            if dev > 10.0:
                if not d["leaf"] or dbl:
                    continue   # no leaf line drawn: a curve off every wall direction is no door
                d = _snap_door(d, wd)   # partial swing drawn short of the wall: measured hinge + leaf radius
                                        # laid along the nearest wall direction
        width = d.get("D", d["r"] + d.get("r2", 0)) if dbl else d["r"]
        conf = 0.55 + 0.2 * d["leaf"] + 0.2 * d["near_wall"]
        poly = [[round(x, 2), round(y, 2)] for x, y in d["poly"]]
        ax = d["axis"]
        props = {"width_pt": round(width, 2), "radius_pt": round(d["r"], 2), "leaf_width_pt": round(d["r"], 2),
                 "depth_pt": round(d["t"], 2), "swing": "ccw" if d["ccw"] else "cw",
                 "swing_side": "left" if d["swing_side"] > 0 else "right",   # of the hinge->closed axis (y down)
                 "hinge": [round(v, 2) for v in d["hinge"]], "closed_end": [round(v, 2) for v in d["closed"]],
                 "open_end": [round(v, 2) for v in d["opened"]],
                 "axis_deg": round(math.degrees(math.atan2(ax[1], ax[0])) % 360, 2),
                 "wall_axis_deg": round(math.degrees(math.atan2(ax[1], ax[0])) % 180, 2),
                 "wall_index": d.get("wall"), "leaf": bool(d["leaf"]), "snapped_to_wall": bool(d.get("snapped")), "double": bool(dbl), "n_leaves": 2 if dbl else 1,
                 "hinge2": [round(v, 2) for v in d["hinge2"]] if dbl and d.get("hinge2") else None,
                 "leaf2_width_pt": round(d["r2"], 2) if dbl and d.get("r2") else None,
                 "swing_bbox": [round(v, 2) for v in _bbox([d["hinge"], d["closed"], d["opened"]])]}
        if mpp:  # same keys as the DXF plan map's doors
            props["swing_radius_m"] = round(d["r"] * mpp, 2)
            props["leaf_len_m"] = round(d["r"] * mpp, 2)
            props["width_m"] = round(width * mpp, 3)
        try:
            props.update(_swing_operation(d, dbl))
        except Exception:
            pass
        res.append({"kind": "door", "polygon": poly, "bbox": [round(v, 2) for v in _bbox(poly)], "conf": round(conf, 2),
                    "props": props})
    return res


# ---------------------------------------------------------------- windows
def _windows(segs, wi: _WallIndex, doors, mpp=None):
    if not len(segs):
        return []
    t_ref = wi.t_med
    dx = segs[:, 2] - segs[:, 0]; dy = segs[:, 3] - segs[:, 1]
    L = np.hypot(dx, dy)
    lmin = max(8.0, 2.5 * t_ref) if t_ref else 12.0
    lmax = max(60.0, 40 * t_ref) if t_ref else 260.0
    gap_max = 1.4 * t_ref if t_ref else 14.0
    if mpp:  # window 0.4-4 m wide, glazing lines < 0.3 m apart
        lmin, lmax, gap_max = 0.4 / mpp, 4.0 / mpp, 0.3 / mpp
    sel = np.nonzero((L >= lmin) & (L <= lmax))[0]
    if not len(sel):
        return []
    ang = np.degrees(np.arctan2(dy[sel], dx[sel])) % 180
    groups = defaultdict(list)
    for k, i in enumerate(sel):
        groups[int(round(ang[k])) % 180].append(i)
    door_boxes = [d["bbox"] for d in doors]
    out = []
    for a_deg, ids in groups.items():
        ids = ids + groups.get((a_deg + 1) % 180, [])  # neighbouring bin, for rounding
        if len(ids) < 2:
            continue
        th = math.radians(a_deg)
        ux, uy = math.cos(th), math.sin(th)
        nx, ny = -uy, ux
        S = segs[ids]
        s0 = S[:, 0] * ux + S[:, 1] * uy; s1 = S[:, 2] * ux + S[:, 3] * uy
        lo, hi = np.minimum(s0, s1), np.maximum(s0, s1)
        off = ((S[:, 0] + S[:, 2]) / 2) * nx + ((S[:, 1] + S[:, 3]) / 2) * ny
        # cluster by (along-extent, offset): same lo/hi within tol, offsets within gap_max of each other
        order = np.lexsort((off, np.round(hi, 0), np.round(lo, 0)))
        taken = np.zeros(len(ids), bool)
        for oi in order:
            if taken[oi]:
                continue
            ln = hi[oi] - lo[oi]
            tol = max(0.8, 0.04 * ln)
            m = (~taken) & (np.abs(lo - lo[oi]) < tol) & (np.abs(hi - hi[oi]) < tol) & \
                (np.abs(off - off[oi]) <= 2.2 * gap_max)
            cand = np.nonzero(m)[0]
            if len(cand) < 2:
                continue
            o = np.sort(np.unique(np.round(off[cand], 2)))
            # split into packs whose consecutive spacing < gap_max
            packs, curp = [], [o[0]]
            for v in o[1:]:
                if v - curp[-1] <= gap_max:
                    curp.append(v)
                else:
                    packs.append(curp); curp = [v]
            packs.append(curp)
            for pk in packs:
                n = len(pk)
                depth = pk[-1] - pk[0]
                if n < 2 or n > 4 or depth < 0.5 or (depth > (0.6 / mpp if mpp else 1.6 * (t_ref or 1e9))) or depth > ln / 2:
                    continue
                inpk = cand[(off[cand] >= pk[0] - 1e-3) & (off[cand] <= pk[-1] + 1e-3)]
                taken[inpk] = True
                if not len(inpk):
                    continue   # (np.median of nothing was nan: such a pack never became a window)
                l0, l1 = float(statistics.median(lo[inpk].tolist())), float(statistics.median(hi[inpk].tolist()))
                o0, o1 = float(pk[0]), float(pk[-1])
                corners = [(l0, o0), (l1, o0), (l1, o1), (l0, o1)]
                poly = [[s * ux + q * nx, s * uy + q * ny] for s, q in corners]
                # both short ends should butt into wall shapes (a gap in a wall run)
                ends_ok = None
                if wi.tree is not None:
                    mid = (o0 + o1) / 2
                    e0 = (l0 * ux + mid * nx, l0 * uy + mid * ny); e1 = (l1 * ux + mid * nx, l1 * uy + mid * ny)
                    rr = max(1.0, 0.6 * depth)
                    ends_ok = wi.run_end(e0, (-ux, -uy), (nx, ny), o0, o1, rr) and \
                        wi.run_end(e1, (ux, uy), (nx, ny), o0, o1, rr)
                if wi.tree is not None and not ends_ok:
                    continue
                if wi.tree is None and n < 3:
                    continue
                bb = _bbox(poly)
                if any(bb[0] < d[2] and d[0] < bb[2] and bb[1] < d[3] and d[1] < bb[3] for d in door_boxes):
                    continue  # door leaf / jamb lines
                conf = 0.5 + 0.15 * (n >= 3) + 0.25 * bool(ends_ok)
                poly = [[round(x, 2), round(y, 2)] for x, y in poly]
                out.append({"kind": "window", "polygon": poly, "bbox": [round(v, 2) for v in _bbox(poly)],
                            "conf": round(conf, 2),
                            "props": {"width_pt": round(l1 - l0, 2), "depth_pt": round(depth, 2), "n_lines": n,
                                      "angle_deg": a_deg}})
    # drop windows contained in a larger window (overlapping packs)
    out.sort(key=lambda w: -w["props"]["width_pt"] * max(w["props"]["depth_pt"], 0.1))
    keep = []
    for w in out:
        b = w["bbox"]
        if any(b[0] >= k["bbox"][0] - 0.5 and b[1] >= k["bbox"][1] - 0.5 and b[2] <= k["bbox"][2] + 0.5
               and b[3] <= k["bbox"][3] + 0.5 for k in keep):
            continue
        keep.append(w)
    return keep


def _end_faces(walls):
    """Short end faces of wall shapes: [(mid xy, outward unit normal, face length, wall index)]. An end face is an
    edge no longer than the wall is thick whose two neighbouring edges run (anti)parallel to its normal."""
    from shapely.geometry import Point, Polygon
    out = []
    for wi_, w in enumerate(walls or []):
        p = [tuple(map(float, q)) for q in w.get("polygon") or []]
        if len(p) > 3 and p[0] == p[-1]:
            p = p[:-1]
        if len(p) < 4:
            continue
        try:
            g = Polygon(p)
            if not g.is_valid:
                g = g.buffer(0)
        except Exception:
            continue
        n = len(p)
        for i in range(n):
            a, b = p[i], p[(i + 1) % n]
            L = math.dist(a, b)
            if L < 0.3:
                continue
            ex, ey = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = -ey, ex
            prv, nxt = p[i - 1], p[(i + 2) % n]
            la, lb = math.dist(prv, a), math.dist(b, nxt)
            if min(la, lb) < 1.2 * L:          # the side edges must be longer than the face (a wall, not a block)
                continue
            # neighbours run along the normal
            ca = abs(((a[0] - prv[0]) * nx + (a[1] - prv[1]) * ny) / la)
            cb = abs(((nxt[0] - b[0]) * nx + (nxt[1] - b[1]) * ny) / lb)
            if ca < 0.95 or cb < 0.95:
                continue
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            eps = 0.25 * L
            if g.contains(Point(mx + nx * eps, my + ny * eps)):
                nx, ny = -nx, -ny
            if g.contains(Point(mx + nx * eps, my + ny * eps)):
                continue
            out.append(((mx, my), (nx, ny), L, wi_))
    return out


def _gap_windows(segs, walls, wi: _WallIndex, doors, mpp=None):
    """Windows as gaps in a wall run: two collinear wall ends facing each other across 0.4-4 m (scale-free:
    1.5-40 wall thicknesses), bridged by thin lines along the wall axis (glazing / sill), no swing arc."""
    faces = _end_faces(walls)
    if len(faces) < 2 or not len(segs):
        return []
    from shapely.geometry import Polygon, box as sbox
    P = np.array([f[0] for f in faces]); N = np.array([f[1] for f in faces]); T = np.array([f[2] for f in faces])
    door_polys = []
    for d in doors:
        try:
            door_polys.append(Polygon(d["polygon"]).buffer(0.1 * d["props"].get("width_pt", 10)))
        except Exception:
            pass
    sdx = segs[:, 2] - segs[:, 0]; sdy = segs[:, 3] - segs[:, 1]
    sL = np.hypot(sdx, sdy)
    out, used = [], set()
    foot = None
    order = np.argsort(-T)
    for i in order:
        if i in used:
            continue
        (mx, my), (nx, ny), t, wa = faces[i]
        if (mpp and t * mpp > 0.6) or (not mpp and wi.t_med and t > 3 * wi.t_med):
            continue  # an end face thicker than any wall (casework, furniture blocks)
        gmin, gmax = (0.4 / mpp, 4.0 / mpp) if mpp else (1.5 * t, 40 * t)
        gmin = max(gmin, 1.2 * t)
        d = P - np.array([mx, my])
        along = d[:, 0] * nx + d[:, 1] * ny
        lat = np.abs(d[:, 0] * -ny + d[:, 1] * nx)
        facing = (N[:, 0] * nx + N[:, 1] * ny) < -0.97
        ok = facing & (along >= gmin) & (along <= gmax) & (lat < 0.3 * t) & (np.abs(T - t) < 0.4 * t)
        ok[i] = False
        cand = np.nonzero(ok)[0]
        if not len(cand):
            continue
        j = int(cand[np.argmin(along[cand])])
        if j in used or faces[j][3] == wa and False:
            continue
        g = float(along[j])
        hw = 0.5 * t
        # gap rectangle: from face i along n for g, +-t/2 across
        ux, uy = nx, ny; vx, vy = -ny, nx
        poly = [[mx + vx * hw, my + vy * hw], [mx + ux * g + vx * hw, my + uy * g + vy * hw],
                [mx + ux * g - vx * hw, my + uy * g - vy * hw], [mx - vx * hw, my - vy * hw]]
        gp = Polygon(poly)
        # nothing solid in between (no wall shape filling the gap)
        if wi.tree is not None:
            inter = sum(wi.polys[int(k)][0].intersection(gp).area for k in wi.tree.query(gp))
            if inter > 0.15 * gp.area:
                continue
        if any(dp.intersects(gp) for dp in door_polys):
            continue
        # glazing: thin lines inside the gap running along the axis, most of the gap long
        x0, y0 = mx, my
        a0 = (segs[:, 0] - x0) * ux + (segs[:, 1] - y0) * uy; a1 = (segs[:, 2] - x0) * ux + (segs[:, 3] - y0) * uy
        b0 = (segs[:, 0] - x0) * vx + (segs[:, 1] - y0) * vy; b1 = (segs[:, 2] - x0) * vx + (segs[:, 3] - y0) * vy
        par = np.abs(sdx * ux + sdy * uy) > 0.985 * np.maximum(sL, 1e-9)
        inside = (np.minimum(a0, a1) > -0.1 * g) & (np.maximum(a0, a1) < 1.1 * g) & \
                 (np.abs(b0) <= hw * 1.15) & (np.abs(b1) <= hw * 1.15)
        span = np.abs(a1 - a0)
        glz = np.nonzero(par & inside & (span >= 0.6 * g))[0]
        offs = sorted({round(float((b0[k] + b1[k]) / 2), 1) for k in glz})
        exterior = False
        # sliding / balcony door: >= 2 leaves along the axis, each 0.35-0.8 of the gap, one anchored at each jamb,
        # at different offsets across the wall, overlapping in the middle; no swing arc; gap >= 1.2 m
        part = np.nonzero(par & inside & (span >= 0.35 * g) & (span <= 0.8 * g))[0]
        lo_a = np.minimum(a0, a1); hi_a = np.maximum(a0, a1)
        left = [k for k in part if lo_a[k] < 0.12 * g]
        right = [k for k in part if hi_a[k] > 0.88 * g]
        sliding = (g * (mpp or 0) >= 1.2 or (not mpp and g >= 4 * t)) and any(
            abs((b0[a_] + b1[a_]) / 2 - (b0[b_] + b1[b_]) / 2) > 0.05 * t and hi_a[a_] > lo_a[b_]
            for a_ in left for b_ in right if a_ != b_)
        if sliding:
            used.add(i); used.add(j)
            poly = [[round(x, 2), round(y, 2)] for x, y in poly]
            props = {"width_pt": round(g, 2), "depth_pt": round(t, 2), "leaf_width_pt": round(g / 2, 2),
                     "sliding": True, "n_leaves": 2, "double": True, "leaf": True,
                     "hinge": None, "swing": None, "wall_index": wa,
                     "axis_deg": round(math.degrees(math.atan2(uy, ux)) % 360, 2),
                     "wall_axis_deg": round(math.degrees(math.atan2(uy, ux)) % 180, 2), "from": "wall_gap_sliding",
                     "operation": "DOUBLE_DOOR_SLIDING", "operation_source": "two sliding leaves"}
            if mpp:
                props["width_m"] = round(g * mpp, 3)
                props["leaf_len_m"] = round(g * mpp / 2, 2)
                props["swing_radius_m"] = None
            out.append({"kind": "door", "polygon": poly, "bbox": [round(v, 2) for v in _bbox(poly)], "conf": 0.6,
                        "props": props})
            continue
        if not offs:
            # an unglazed gap in an EXTERIOR wall run (one side outside the building) that is no door is a window
            # opening too (facade bays drawn as plain gaps); interior gaps without glazing are passages
            if foot is None:
                foot = _filled_footprint(walls, (4.0 / mpp) if mpp else 40 * t) or False
            if not foot:
                continue
            from shapely.geometry import Point
            cxm, cym = mx + ux * g / 2, my + uy * g / 2
            o = hw + max(1.0, 0.5 * t)
            sides = [foot.contains(Point(cxm + vx * o * sg, cym + vy * o * sg)) for sg in (1, -1)]
            if sides[0] == sides[1]:
                continue
            exterior = True
        used.add(i); used.add(j)
        poly = [[round(x, 2), round(y, 2)] for x, y in poly]
        out.append({"kind": "window", "polygon": poly, "bbox": [round(v, 2) for v in _bbox(poly)],
                    "conf": round(0.6 + 0.1 * min(len(offs), 3), 2) if offs else 0.5,
                    "props": {"width_pt": round(g, 2), "depth_pt": round(t, 2), "n_lines": len(offs),
                              "exterior": exterior or None, "wall_index": wa,
                              "angle_deg": int(round(math.degrees(math.atan2(uy, ux)))) % 180, "from": "wall_gap"}})
    return out


def _filled_footprint(walls, close_pt):
    """Building footprint: wall shapes closed over gaps up to close_pt, holes (rooms) filled. Largest part."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = []
    for w in walls or []:
        try:
            g = Polygon(w["polygon"])
            g = g if g.is_valid else g.buffer(0)
            if not g.is_empty:
                polys.append(g)
        except Exception:
            continue
    if len(polys) < 3:
        return None
    r = close_pt / 2 + 0.5
    u = unary_union(polys).buffer(r, resolution=4).buffer(-r, resolution=4)
    parts = [p for p in getattr(u, "geoms", [u]) if p.geom_type == "Polygon"]
    if not parts:
        return None
    big = max(parts, key=lambda p: p.area)
    return Polygon(big.exterior)


def _footprint_filter(ops, walls, mpp=None):
    """Drop openings away from the building: wall shapes are grouped into clusters (touching within ~1 wall
    thickness x 4); only clusters holding >= 15% of the largest cluster's wall area count as building. An opening
    must touch one (legend / title-block symbols and stray sheet furniture sit in tiny clusters or none)."""
    if not walls or not ops:
        return ops
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = []
    for w in walls:
        try:
            g = Polygon(w["polygon"])
            g = g if g.is_valid else g.buffer(0)
            if not g.is_empty:
                polys.append(g)
        except Exception:
            continue
    if len(polys) < 3:
        return ops
    th = sorted(float(w.get("thickness_pt") or 0) for w in walls if w.get("thickness_pt"))
    t = th[len(th) // 2] if th else 3.0
    reach = max(2.0, 4 * t)
    u = unary_union([g.buffer(reach) for g in polys])
    comps = list(getattr(u, "geoms", [u]))
    areas = [sum(g.area for g in polys if c.intersects(g)) for c in comps]
    big = max(areas)
    keep = [c for c, a in zip(comps, areas) if a >= 0.15 * big]
    # the building region: convex hull of the main wall clusters (robust to sparse / broken wall shapes)
    hull = unary_union(keep).convex_hull
    # a door in a thin exterior wall the wall reader missed sits just outside the hull: allow ~1.5 m when the
    # opening is snapped to a wall band (a legend symbol has no wall)
    near = hull.buffer((1.5 / mpp) if mpp else 6 * t)
    out = []
    for o in ops:
        try:
            g = Polygon(o["polygon"])
        except Exception:
            continue
        if hull.intersects(g) or (o["props"].get("wall_index") is not None and near.intersects(g)):
            out.append(o)
    return out


def _jamb_windows(segs, wi: _WallIndex, mpp=None):
    """Windows drawn over a continuous wall shape: two thin jamb lines spanning the wall's full thickness,
    0.4-4 m apart along the wall, with >= 1 glazing line along the wall axis between them."""
    if wi.tree is None or not len(segs):
        return []
    from shapely.geometry import Point
    tmin, tmax = (0.08 / mpp, 0.7 / mpp) if mpp else (2.0, 25.0)
    dx = segs[:, 2] - segs[:, 0]; dy = segs[:, 3] - segs[:, 1]
    L = np.hypot(dx, dy)
    idx = np.nonzero((L >= tmin) & (L <= tmax))[0]
    import shapely
    if not len(idx):
        return []
    A = shapely.points(segs[idx, 0], segs[idx, 1]); B = shapely.points(segs[idx, 2], segs[idx, 3])
    M = shapely.points((segs[idx, 0] + segs[idx, 2]) / 2, (segs[idx, 1] + segs[idx, 3]) / 2)
    geoms = np.array([g for g, _ in wi.polys], dtype=object)
    pi, wi_ = wi.tree.query(M, predicate="dwithin", distance=0.3)
    jambs = []
    if len(pi):
        bd = shapely.boundary(geoms[wi_])
        ok = (shapely.distance(bd, A[pi]) < 0.6) & (shapely.distance(bd, B[pi]) < 0.6)
        jambs = sorted({int(idx[k]) for k in pi[ok]})
    if len(jambs) < 2:
        return []
    # glazing candidates: only lines long enough to span 0.6 of the smallest window
    gl_min = 0.6 * ((0.4 / mpp) if mpp else 6.0)
    G = segs[L >= gl_min]
    GL = np.hypot(G[:, 2] - G[:, 0], G[:, 3] - G[:, 1])
    J = segs[jambs]
    jl = L[jambs]
    jx = dx[jambs] / jl; jy = dy[jambs] / jl
    cx = (J[:, 0] + J[:, 2]) / 2; cy = (J[:, 1] + J[:, 3]) / 2
    sL = L
    out, used = [], set()
    for a in range(len(jambs)):
        if a in used:
            continue
        vx, vy = jx[a], jy[a]            # across the wall
        ux, uy = -vy, vx                 # along the wall
        gmin, gmax = (0.4 / mpp, 4.0 / mpp) if mpp else (3 * jl[a], 40 * jl[a])
        par = np.abs(jx * vx + jy * vy) > 0.985
        dxa = cx - cx[a]; dya = cy - cy[a]
        along = dxa * ux + dya * uy
        lat = np.abs(dxa * vx + dya * vy)
        ok = par & (np.abs(along) >= gmin) & (np.abs(along) <= gmax) & (lat < 0.25 * jl[a]) & \
            (np.abs(jl - jl[a]) < 0.2 * jl[a])
        ok[a] = False
        for b in sorted(np.nonzero(ok)[0], key=lambda b: abs(along[b])):
            if b in used:
                continue
            g = abs(along[b]); sgn = 1 if along[b] > 0 else -1
            ex, ey = ux * sgn, uy * sgn
            # glazing between the jambs, along the wall
            a0 = (G[:, 0] - cx[a]) * ex + (G[:, 1] - cy[a]) * ey
            a1 = (G[:, 2] - cx[a]) * ex + (G[:, 3] - cy[a]) * ey
            b0 = (G[:, 0] - cx[a]) * vx + (G[:, 1] - cy[a]) * vy
            b1 = (G[:, 2] - cx[a]) * vx + (G[:, 3] - cy[a]) * vy
            hw = jl[a] / 2
            along_ok = np.abs((G[:, 2] - G[:, 0]) * ex + (G[:, 3] - G[:, 1]) * ey) > 0.985 * np.maximum(GL, 1e-9)
            inside = (np.minimum(a0, a1) > -0.1 * g) & (np.maximum(a0, a1) < 1.1 * g) & \
                     (np.abs(b0) < 0.9 * hw) & (np.abs(b1) < 0.9 * hw)
            glz = np.nonzero(along_ok & inside & (np.abs(a1 - a0) >= 0.6 * g))[0]
            if not len(glz):
                continue
            # the band between the jambs must be in a wall (not two parallel ticks in a room)
            mid = Point(cx[a] + ex * g / 2, cy[a] + ey * g / 2)
            if not wi.near(mid.x, mid.y, 0.5 * hw):
                continue
            used.add(a); used.add(b)
            p0x, p0y = cx[a], cy[a]
            poly = [[p0x + vx * hw, p0y + vy * hw], [p0x + ex * g + vx * hw, p0y + ey * g + vy * hw],
                    [p0x + ex * g - vx * hw, p0y + ey * g - vy * hw], [p0x - vx * hw, p0y - vy * hw]]
            poly = [[round(float(x), 2), round(float(y), 2)] for x, y in poly]
            nl = len({round(float((b0[k] + b1[k]) / 2), 1) for k in glz})
            out.append({"kind": "window", "polygon": poly, "bbox": [round(v, 2) for v in _bbox(poly)],
                        "conf": round(0.6 + 0.1 * min(nl, 3), 2),
                        "props": {"width_pt": round(float(g), 2), "depth_pt": round(float(jl[a]), 2), "n_lines": nl,
                                  "angle_deg": int(round(math.degrees(math.atan2(ey, ex)))) % 180, "from": "jambs"}})
            break
    return out


def _wall_frames(wi: _WallIndex):
    """Per wall shape: (unit axis, centre offset along the normal, half thickness, along-axis extent [lo, hi])."""
    out = []
    for g, t in wi.polys:
        try:
            mr = g.minimum_rotated_rectangle
            c = list(mr.exterior.coords)[:4]
        except Exception:
            out.append(None); continue
        e = [(math.dist(c[i], c[(i + 1) % 4]), i) for i in range(4)]
        (L, i), (S, _) = max(e), min(e)
        if L <= 0:
            out.append(None); continue
        a, b = c[i], c[(i + 1) % 4]
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = -uy, ux
        xy = np.asarray(g.exterior.coords) if hasattr(g, "exterior") else np.asarray(c)
        s = xy[:, 0] * ux + xy[:, 1] * uy
        o = xy[:, 0] * nx + xy[:, 1] * ny
        out.append(((ux, uy), float((o.min() + o.max()) / 2), float((o.max() - o.min()) / 2), (float(s.min()), float(s.max()))))
    return out


_DBG = None


def _bridge_windows(segs, wi: _WallIndex, doors, mpp=None, page=None):
    """Windows drawn as thin glazing (lines or thin pane outlines, frames between panes) that bridge a gap between
    two collinear wall pieces: collinear thin lines are merged into runs (gaps < 0.3 m); a run 0.4-6 m long whose
    two ends enter wall shapes running along it, lies inside those walls' band, and whose middle is in no filled
    wall is a window across that gap. Facade glazing exported from BIM tools is often drawn this way (no sill
    lines, no jamb ticks). Needs >= 2 such lines (pane outline / double glazing) so a lone threshold line is not
    a window."""
    if wi.tree is None or not len(segs):
        return []
    import shapely
    from shapely.geometry import Point, Polygon
    unit = (1 / mpp) if mpp else None
    lmin = 0.15 * unit if unit else 3.0
    rmin, rmax = (0.4 * unit, 12.0 * unit) if unit else (12.0, 360.0)   # > 4.5 m becomes a curtain wall
    gmerge = 0.3 * unit if unit else 8.0
    gchain = 0.7 * unit if unit else 20.0
    delta = max(1.0, 0.08 * unit) if unit else 2.0
    deltas = (max(1.0, 0.05 * unit), 0.12 * unit, 0.22 * unit) if unit else (1.0, 3.0, 6.0)
    dx = segs[:, 2] - segs[:, 0]; dy = segs[:, 3] - segs[:, 1]
    L = np.hypot(dx, dy)
    sel = np.nonzero(L >= lmin)[0]
    if not len(sel):
        return []
    frames = _wall_frames(wi)
    fill_ids = {k for k, wid in enumerate(wi.ids) if (wi.walls[wid].get("style") == "fill")}
    # solids a glazing run may end in: wall shapes, plus small dark filled blocks (columns, frame / jamb profiles)
    from shapely.strtree import STRtree
    geoms = [g for g, _ in wi.polys]
    wall_of = list(wi.ids)
    fr = list(frames)
    cmin, cmax = (0.08 * unit, 1.0 * unit) if unit else (2.0, 28.0)
    for p in (page or {}).get("paths", []):
        f_ = p.get("fill")
        pts = p.get("pts") or []
        if f_ is None or not p.get("closed") or len(pts) < 4 or max(f_[:3]) > 0.55:
            continue
        xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
        if not (cmin <= max(xs) - min(xs) <= cmax and cmin <= max(ys) - min(ys) <= cmax):
            continue
        try:
            g = Polygon(pts).buffer(0)
        except Exception:
            continue
        if g.is_empty or g.geom_type != "Polygon" or g.area < 0.5 * cmin * cmin:
            continue
        geoms.append(g); wall_of.append(None); fr.append("col")
    stree = STRtree(geoms)
    ang = np.degrees(np.arctan2(dy[sel], dx[sel])) % 180
    groups = defaultdict(list)
    for k, i in enumerate(sel):
        groups[int(round(ang[k])) % 180].append(i)
    door_polys = []
    for d in doors:
        try:
            door_polys.append(Polygon(d["polygon"]))
        except Exception:
            pass
    cands = []
    for a_deg, ids in groups.items():
        ids = sorted(set(ids + groups.get((a_deg + 1) % 180, [])))
        if not ids:
            continue
        th = math.radians(a_deg); ux, uy = math.cos(th), math.sin(th); nx, ny = -uy, ux
        S = segs[ids]
        s0 = S[:, 0] * ux + S[:, 1] * uy; s1 = S[:, 2] * ux + S[:, 3] * uy
        lo, hi = np.minimum(s0, s1), np.maximum(s0, s1)
        off = ((S[:, 0] + S[:, 2]) / 2) * nx + ((S[:, 1] + S[:, 3]) / 2) * ny
        # straightness: both ends on the same offset (skip lines off this angle bin)
        o0 = S[:, 0] * nx + S[:, 1] * ny; o1 = S[:, 2] * nx + S[:, 3] * ny
        okk = np.abs(o0 - o1) < 0.6
        # 1-D clusters of offsets (chained within 0.3 pt), then collinear pieces merged along the axis
        ko = [k for k in np.argsort(off) if okk[k]]
        clusters, cur = [], []
        for k in ko:
            if cur and off[k] - off[cur[-1]] > 0.3:
                clusters.append(cur); cur = []
            cur.append(k)
        if cur:
            clusters.append(cur)
        runs = []
        for cl in clusters:
            o_c = float(statistics.median(off[cl].tolist()))
            r = None
            for k in sorted(cl, key=lambda k: lo[k]):
                if r is not None and lo[k] <= r[1] + gmerge:
                    r[1] = max(r[1], hi[k]); r[3].add(round(float(off[k]) * 2) / 2)
                else:
                    if r is not None:
                        runs.append(r)
                    r = [lo[k], hi[k], o_c, {round(float(off[k]) * 2) / 2}]
            if r is not None:
                runs.append(r)
        # chains: windows in a row separated by mullion / frame blocks (gaps up to 0.7 m) share the end walls
        chains = []
        for r in sorted(runs, key=lambda r: (round(r[2], 1), r[0])):
            c = chains[-1] if chains else None
            if c and abs(c[-1][2] - r[2]) < 0.05 and r[0] - c[-1][1] <= gchain:
                c.append(r)
            else:
                chains.append([r])
        chains = [c for c in chains if rmin <= c[-1][1] - c[0][0] <= rmax]
        if not chains:
            continue
        # end probes for all chains of this direction at once: the nearest of `deltas` past each glass end that
        # lands in a solid (a frame / jamb profile may sit between the glass end and the wall piece)
        C0 = np.array([c[0][0] for c in chains]); C1 = np.array([c[-1][1] for c in chains])
        CO = np.array([c[0][2] for c in chains])
        end_hits = [[[], []] for _ in chains]
        for side, (sg, SV) in enumerate(((-1, C0), (1, C1))):
            todo = np.arange(len(chains))
            for dl in deltas:
                if not len(todo):
                    break
                sv = SV[todo] + sg * dl
                P = shapely.points(sv * ux + CO[todo] * nx, sv * uy + CO[todo] * ny)
                pi_, gi_ = stree.query(P, predicate="intersects")
                found = set()
                for a_, g_ in zip(pi_.tolist(), gi_.tolist()):
                    if fr[g_] is not None:
                        end_hits[int(todo[a_])][side].append(g_); found.add(a_)
                todo = np.array([t_ for k_, t_ in enumerate(todo.tolist()) if k_ not in found], int)
        for ci_, chain in enumerate(chains):
            l0, l1, o = chain[0][0], chain[-1][1], chain[0][2]
            n = set().union(*[r[3] for r in chain])
            if _DBG is not None:
                _DBG.append(("run", a_deg, round(l0, 1), round(l1, 1), round(o, 2), sorted(n)))
            ends = end_hits[ci_]
            if not ends[0] or not ends[1]:
                continue
            pm = Point(((l0 + l1) / 2) * ux + o * nx, ((l0 + l1) / 2) * uy + o * ny)
            if _DBG is not None:
                _DBG.append(("ends", ends))
            ok_pair = None
            for ka in ends[0]:
                for kb in ends[1]:
                    fa, fb = fr[ka], fr[kb]
                    if any(f_ != "col" and abs(f_[0][0] * ux + f_[0][1] * uy) < 0.985 for f_ in (fa, fb)):
                        continue
                    if geoms[ka].contains(pm) or geoms[kb].contains(pm):
                        continue
                    # inside both walls' band (offsets along this run's normal)
                    inside = True
                    for k_ in (ka, kb):
                        xy = np.asarray(geoms[k_].exterior.coords)
                        of = xy[:, 0] * nx + xy[:, 1] * ny
                        if not (of.min() - 0.5 <= o <= of.max() + 0.5):
                            inside = False
                    if inside:
                        ok_pair = (ka, kb); break
                if ok_pair:
                    break
            if not ok_pair:
                continue
            if any(wi.polys[int(k)][0].contains(pm) for k in wi.tree.query(pm) if int(k) in fill_ids):
                continue
            ka, kb = ok_pair
            # gap = jamb face to jamb face; band = the walls' common offsets
            bands = []
            jam = []
            for k_, side in ((ka, -1), (kb, 1)):
                xy = np.asarray(geoms[k_].exterior.coords)
                s_ = xy[:, 0] * ux + xy[:, 1] * uy; of = xy[:, 0] * nx + xy[:, 1] * ny
                if fr[k_] != "col" or (fr[ka] == "col" and fr[kb] == "col"):
                    bands.append((of.min(), of.max()))
                jam.append(s_.max() if side < 0 else s_.min())
            g0, g1 = min(jam[0], l0 + delta), max(jam[1], l1 - delta)
            b0, b1 = max(b[0] for b in bands), min(b[1] for b in bands)
            if b1 - b0 < 0.5:
                b0, b1 = min(b[0] for b in bands), max(b[1] for b in bands)
            # one window per run of the chain: jamb .. mid-mullion .. jamb
            cuts = [g0] + [(a[1] + b[0]) / 2 for a, b in zip(chain, chain[1:])] + [g1]
            for i_, r in enumerate(chain):
                p0, p1 = cuts[i_], cuts[i_ + 1]
                if not (rmin <= p1 - p0 <= rmax):
                    continue
                cands.append((p0, p1, b0, b1, ux, uy, nx, ny, o, r[3], a_deg,
                              wall_of[ka] if wall_of[ka] is not None else wall_of[kb]))   # r[3]: line offsets
    # >= 2 glazing lines per gap (or one inside an exterior wall); one window per gap
    out = []
    foot = None
    used = [False] * len(cands)
    for i, c in enumerate(cands):
        if used[i]:
            continue
        g0, g1, b0, b1, ux, uy, nx, ny = c[:8]
        same = [j for j, d in enumerate(cands) if not used[j] and abs(d[10] - c[10]) <= 1 and
                abs(d[0] - g0) < 1.0 and abs(d[1] - g1) < 1.0 and abs(d[2] - b0) < 1.0 and abs(d[3] - b1) < 1.0]
        # glazing / face lines that span this window (e.g. one outer line over a row of windows) count too
        span = [j for j, d in enumerate(cands) if abs(d[10] - c[10]) <= 1 and d[0] <= g0 + 1.0 and
                d[1] >= g1 - 1.0 and abs(d[2] - b0) < 1.0 and abs(d[3] - b1) < 1.0]
        offs = set().union(*[cands[j][9] for j in same + span])
        for j in same:
            used[j] = True
        if len(offs) < 2:
            # one glazing line: only strictly inside the band of an EXTERIOR wall (a centred threshold line in an
            # interior passage must not become glazing)
            o1_ = next(iter(offs))
            if not (b0 + 0.15 * (b1 - b0) <= o1_ <= b1 - 0.15 * (b1 - b0)):
                continue
            if foot is None:
                foot = _filled_footprint(wi.walls, (4.0 * unit) if unit else 100.0) or False
            if not foot:
                continue
            cs, co = (g0 + g1) / 2, (b0 + b1) / 2
            pr_ = max(1.0, 0.5 * (b1 - b0)) + (b1 - b0) / 2
            sides = [foot.contains(Point(cs * ux + (co + sg * pr_) * nx, cs * uy + (co + sg * pr_) * ny))
                     for sg in (1, -1)]
            if sides[0] == sides[1]:
                continue
        if max(offs) - min(offs) > 0.6 * (b1 - b0):
            continue   # lines on both faces of the band: a thin wall / partition, not glazing inside a wall
        poly = [[g0 * ux + b0 * nx, g0 * uy + b0 * ny], [g1 * ux + b0 * nx, g1 * uy + b0 * ny],
                [g1 * ux + b1 * nx, g1 * uy + b1 * ny], [g0 * ux + b1 * nx, g0 * uy + b1 * ny]]
        gp = Polygon(poly)
        if any(dp.intersects(gp) for dp in door_polys):
            continue
        poly = [[round(float(x), 2), round(float(y), 2)] for x, y in poly]
        out.append({"kind": "window", "polygon": poly, "bbox": [round(v, 2) for v in _bbox(poly)],
                    "conf": round(0.6 + 0.1 * min(len(offs), 3), 2),
                    "props": {"width_pt": round(float(g1 - g0), 2), "depth_pt": round(float(b1 - b0), 2),
                              "n_lines": len(offs), "angle_deg": c[10], "wall_index": c[11], "from": "glazing_bridge",
                              "glazing_spread_pt": round(max(offs) - min(offs), 2),
                              "wall_axis_deg": round(math.degrees(math.atan2(uy, ux)) % 180, 2)}})
        if mpp:
            out[-1]["props"]["width_m"] = round(float(g1 - g0) * mpp, 3)
            out[-1]["props"]["depth_m"] = round(float(b1 - b0) * mpp, 3)
    return out


def _fit_window(w, wi: _WallIndex, mpp):
    """A window lies on a wall line: depth = that wall's thickness, length = the gap. Thin glazing packs are widened
    to the wall band; candidates thicker than 0.6 m (or 3 wall thicknesses) or not on a wall are dropped."""
    from shapely.geometry import Polygon
    p = w["polygon"]
    e = [(math.dist(p[i], p[(i + 1) % 4]), i) for i in range(4)]
    (Ll, il), (Ls, is_) = max(e), min(e)
    a, b = p[il], p[(il + 1) % 4]
    ux, uy = (b[0] - a[0]) / max(Ll, 1e-9), (b[1] - a[1]) / max(Ll, 1e-9)
    nx, ny = -uy, ux
    cx = sum(q[0] for q in p) / 4; cy = sum(q[1] for q in p) / 4
    depth = Ls
    if wi.tree is not None:
        # wall band at both ends of the window (just outside its long extent)
        bands = []
        from shapely.geometry import LineString
        for sg in (-1, 1):
            ox, oy = cx + ux * sg * (Ll / 2 + max(0.5, 0.05 * Ll)), cy + uy * sg * (Ll / 2 + max(0.5, 0.05 * Ll))
            R = max(3 * Ls, 0.8 / mpp if mpp else 20.0)
            ln = LineString([(ox - nx * R, oy - ny * R), (ox + nx * R, oy + ny * R)])
            for k in wi.tree.query(ln):
                xs = wi.polys[int(k)][0].intersection(ln)
                for part in getattr(xs, "geoms", [xs]):
                    if part.is_empty or part.geom_type != "LineString":
                        continue
                    offs = [(x - cx) * nx + (y - cy) * ny for x, y in part.coords]
                    lo, hi = min(offs), max(offs)
                    if lo - 0.5 <= 0 <= hi + 0.5 or min(abs(lo), abs(hi)) < Ls / 2 + 0.5:
                        bands.append((lo, hi))
        on_wall = bool(bands) or any(wi.polys[int(k)][0].contains(Polygon(p).centroid) for k in wi.tree.query(Polygon(p)))
        if not on_wall:
            return None
        if bands:
            lo = min(bb[0] for bb in bands); hi = max(bb[1] for bb in bands)
            if hi - lo >= 0.5 * Ls:
                depth = hi - lo
                cx, cy = cx + nx * (lo + hi) / 2, cy + ny * (lo + hi) / 2
    limit = 0.6 / mpp if mpp else (3 * wi.t_med if wi.t_med else None)
    if limit and depth > limit:
        return None
    if Ll < depth:
        return None
    hw, hl = depth / 2, Ll / 2
    poly = [[round(cx - ux * hl + nx * s1 * hw, 2), round(cy - uy * hl + ny * s1 * hw, 2)] for s1 in (-1, 1)] + \
           [[round(cx + ux * hl + nx * s1 * hw, 2), round(cy + uy * hl + ny * s1 * hw, 2)] for s1 in (1, -1)]
    out = dict(w)
    out["polygon"] = poly
    out["bbox"] = [round(v, 2) for v in _bbox(poly)]
    pr = dict(w["props"])
    pr.update({"width_pt": round(Ll, 2), "depth_pt": round(depth, 2),
               "wall_axis_deg": round(math.degrees(math.atan2(uy, ux)) % 180, 2)})
    if mpp:
        pr["width_m"] = round(Ll * mpp, 3)
        pr["depth_m"] = round(depth * mpp, 3)
    out["props"] = pr
    return out


TAG_RX = [re.compile(r"^[A-Z]{2,4}\d{1,3}[a-z]{1,3}$"),            # door-type codes such as ABC12xy, DEF3z
          re.compile(r"^(?:D|T|O|DR|OV)[-.]?\d{1,4}[A-Z]?$"),       # door marks such as D34, T12, O1
          re.compile(r"^\d{2,4}\.?[A-Z]$")]                          # door numbers such as 127A, 127.A
HEIGHT_RX = re.compile(r"^h\s*=\s*(\d{4})(?:\s*mm)?[;,.:]?$", re.I)


def _door_height_note(words):
    """Page-level 'DOOR HEIGHT h=2100' (mm) -> metres, from the text layer, or None."""
    for i, w in enumerate(words or []):
        if w.get("text", "").strip().upper() not in ("HEIGHT", "HEIGHT:", "HEIGHTS"):
            continue
        b = w["bbox"]; h = max(b[3] - b[1], 1.0)
        same = [v for v in words if abs((v["bbox"][1] + v["bbox"][3]) / 2 - (b[1] + b[3]) / 2) < 0.6 * h]
        if not any(v["text"].strip().upper().startswith("DOOR") and v["bbox"][2] <= b[0] + 1 and
                   b[0] - v["bbox"][2] < 4 * h for v in same):
            continue
        right = sorted((v for v in same if v["bbox"][0] >= b[2] - 1 and v["bbox"][0] - b[2] < 6 * h),
                       key=lambda v: v["bbox"][0])
        for v in right[:3]:
            m = HEIGHT_RX.match(v["text"].strip())
            if m and 1800 <= int(m.group(1)) <= 3500:
                return int(m.group(1)) / 1000
    return None


def _door_height_tags(doors, words):
    """A deviating door height printed beside the door ('h=2400') -> props.height_m for that door."""
    # an 'h=' is a door height only when it belongs to a door tag: within 1.5 text heights of a door-type code and
    # nearer to it than to any room label (an 'h=' printed with a room's label is that room's ceiling height)
    tags = [w["bbox"] for w in words or [] if any(rx.match(w.get("text", "").strip()) for rx in TAG_RX)]
    try:
        from pipeline import pdf_rooms
        labs = [b["bbox"] for b in pdf_rooms.label_blocks(words)]
    except Exception:  # noqa: BLE001
        labs = []

    def rdist(p, b):
        return math.hypot(max(b[0] - p[0], 0, p[0] - b[2]), max(b[1] - p[1], 0, p[1] - b[3]))
    cand = []
    for w in words or []:
        m = HEIGHT_RX.match(w.get("text", "").strip())
        if m and 1800 <= int(m.group(1)) <= 3500:
            b = w["bbox"]
            p = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            th = max(min(b[2] - b[0], b[3] - b[1]), 0.5)
            dt = min((rdist(p, t) for t in tags), default=math.inf)
            dl = min((rdist(p, q) for q in labs), default=math.inf)
            if dt > 1.5 * th or dt >= dl:
                continue
            # paired with another code (a ceiling type such as 'XY1 h=2700' is a ceiling height): its nearest word
            # must be the door tag itself
            dn = min((rdist(p, v["bbox"]) for v in words if v is not w and v.get("bbox") and
                      not any(rx.match(v.get("text", "").strip()) for rx in TAG_RX)), default=math.inf)
            if dn <= dt:
                continue
            cand.append((p[0], p[1], int(m.group(1)) / 1000))
    if not cand or not doors:
        return
    taken = set()
    for d in doors:
        b = d["bbox"]; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        R = 1.2 * d["props"].get("width_pt", 30)
        best = min(((math.hypot(x - cx, y - cy), k) for k, (x, y, _) in enumerate(cand) if k not in taken),
                   default=None)
        if best and best[0] < R:
            taken.add(best[1])
            d["props"]["height_m"] = cand[best[1]][2]
            d["props"]["height_source"] = "printed on the door tag"


def _tag_doors(doors, words):
    """props.tag: the nearest door code printed within ~one door width of the opening."""
    if not words or not doors:
        return
    cand = []
    for w in words:
        t = w.get("text", "").strip()
        for rank, rx in enumerate(TAG_RX):
            if rx.match(t):
                b = w["bbox"]
                cand.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, t, rank))
                break
    if not cand:
        return
    C = np.array([(c[0], c[1]) for c in cand])
    taken = set()
    for d in sorted(doors, key=lambda d: -d["conf"]):
        b = d["bbox"]; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        R = 1.2 * d["props"].get("width_pt", 30)
        dist = np.hypot(C[:, 0] - cx, C[:, 1] - cy)
        ok = [k for k in np.nonzero(dist < R)[0] if k not in taken]
        if ok:
            k = min(ok, key=lambda k: (cand[k][3], dist[k]))
            taken.add(k)
            d["props"]["tag"] = cand[k][2]


def _mark_partitions(wins, walls, mpp):
    """Glazing with building on both sides (both probes inside the filled footprint) is an interior glass
    partition: props.kind = 'glass_partition' (IFC: glazed wall), else props.kind = 'window'."""
    if not wins:
        return
    foot = _filled_footprint(walls, (2.5 / mpp) if mpp else 50.0)
    th = sorted(float(w.get("thickness_pt") or 0) for w in walls or [] if w.get("thickness_pt"))
    wt_med = th[len(th) // 2] if th else None
    from shapely.geometry import Point
    for w in wins:
        pr = w["props"]
        pr.setdefault("kind", "window")
        if not foot:
            continue
        p = w["polygon"]
        e = sorted(((math.dist(p[i], p[(i + 1) % 4]), i) for i in range(4)))
        Ls, i = e[0]
        a, b = p[e[-1][1]], p[(e[-1][1] + 1) % 4]
        L = max(math.dist(a, b), 1e-9)
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        cx = sum(q[0] for q in p) / 4; cy = sum(q[1] for q in p) / 4
        o = Ls / 2 + ((1.5 / mpp) if mpp else 4 * max(Ls, 1.0))
        inside = [foot.contains(Point(cx + nx * o * sg, cy + ny * o * sg)) for sg in (1, -1)]
        # a glazed partition is a thin wall; glazing in a thick (>= 0.25 m) wall is a window in a facade that
        # borders a roof / terrace / courtyard drawn with walls (both probes then land inside the footprint)
        thick = (Ls * mpp >= 0.25) if mpp else (wt_med and Ls >= 1.8 * wt_med)
        if all(inside) and not pr.get("exterior") and not thick:
            pr["kind"] = "glass_partition"


SILL_RX = re.compile(r"\b(?:sill|parapet|brh|bröstning|alareuna|ikkunan\s+alareuna)\b", re.I)
MM_RX = re.compile(r"(?:^|[=\s+])\+?(\d{3,4})(?:\s*mm)?\b")


def _note_value_mm(words, key_rx, lo, hi):
    """A page note '<key> ... 900' (mm) on one text line -> metres, or None (e.g. 'WINDOW SILL h=900')."""
    lines = defaultdict(list)
    for w in words or []:
        b = w.get("bbox")
        if not b:
            continue
        h = max(b[3] - b[1], 1.0)
        lines[(round((b[1] + b[3]) / 2 / h), round(h))].append(w)
    for ws in lines.values():
        ws = sorted(ws, key=lambda w: w["bbox"][0])
        txt = " ".join(w.get("text", "") for w in ws)
        m = key_rx.search(txt)
        if not m:
            continue
        for v in MM_RX.finditer(txt[m.end():m.end() + 40]):
            if lo <= int(v.group(1)) <= hi:
                return int(v.group(1)) / 1000
    return None


def _window_props(wins, words):
    """props.kind (window | glass_partition | curtain_wall), props.sill_m and props.height_m for native IFC windows.
    curtain_wall: exterior glazing longer than 4.5 m (facade / storefront band, floor to ceiling, sill 0)."""
    sill_note = _note_value_mm(words, SILL_RX, 0, 1800)
    for w in wins:
        pr = w["props"]
        k = pr.get("kind") or "window"
        wm = pr.get("width_m")
        if k == "window" and wm and wm > 4.5:
            k = "curtain_wall"
        pr["kind"] = k
        if k == "window":
            if sill_note is not None:
                pr.setdefault("sill_m", sill_note); pr.setdefault("sill_source", "page note")
            else:
                pr.setdefault("sill_m", 0.9); pr.setdefault("sill_source", "default")
        else:  # glazed walls run floor to ceiling
            pr.setdefault("sill_m", 0.0); pr.setdefault("sill_source", "glazed wall")


NEAR_DOORS_M = 7.0   # windows within this distance of the swing doors hull (doors sit on corridors, ~6 m from facades)


def _near_doors(wins, doors, mpp):
    """Windows belong to the occupied building: with >= 4 doors, keep windows within ~4 m of the doors' convex
    hull (roof planes, skylight hatches and neighbouring roofs drawn around the floor carry no doors)."""
    swing = [d for d in doors if d["props"].get("radius_pt") or d["props"].get("sliding")]
    if len(swing) < 4 or not wins:
        return wins
    from shapely.geometry import MultiPoint, Polygon
    hull = MultiPoint([tuple(q) for d in swing for q in d["polygon"]]).convex_hull
    wd = sorted(d["props"]["width_pt"] for d in swing)
    m = (NEAR_DOORS_M / mpp) if mpp else NEAR_DOORS_M * wd[len(wd) // 2]
    zone = hull.buffer(m)
    return [w for w in wins if zone.intersects(Polygon(w["polygon"]))]


def openings(page: dict, walls: list) -> list:
    """Doors and windows on a vector page, in page points (top-left origin, y down)."""
    if not page or not page.get("paths"):
        return []
    segs, arcs = _segments(page)
    wi = _WallIndex(walls)
    doors = _doors(page, segs, arcs, wi)
    mpp = page_m_per_pt(page)[0]
    # windows sit in the gaps between wall pieces: when the wall reader merged layered strips / settled parapets
    # (which can close those gaps), it leaves the pieces as found on walls.unsettled; windows are read from them
    ww, wwi = walls, wi
    try:
        un = getattr(walls, "unsettled", None) or page.get("_walls_unsettled")
        if un and len(un) != len(walls) or (un and any(a is not b for a, b in zip(un, walls))):
            ww, wwi = un, _WallIndex(un)
    except Exception:
        ww, wwi = walls, wi
    gap = _gap_windows(segs, ww, wwi, doors, mpp)
    doors = doors + [o for o in gap if o["kind"] == "door"]
    wins = [o for o in gap if o["kind"] == "window"]
    door_boxes = [d["bbox"] for d in doors]
    try:
        bridge = _bridge_windows(segs, wwi, doors, mpp, page)
    except Exception:
        bridge = []
    for w in _jamb_windows(segs, wwi, mpp) + _windows(segs, wwi, doors, mpp):
        b = w["bbox"]
        if any(b[0] < k[2] and k[0] < b[2] and b[1] < k[3] and k[1] < b[3] for k in door_boxes):
            continue
        if not any(b[0] < k["bbox"][2] and k["bbox"][0] < b[2] and b[1] < k["bbox"][3] and k["bbox"][1] < b[3]
                   for k in wins):
            wins.append(w)
    wins = [w for w in (_fit_window(w, wwi, mpp) for w in wins) if w]
    if bridge:   # oblique facades: overlap by polygon, not by axis-aligned box
        try:
            from shapely.geometry import Polygon
            dpoly = [Polygon(o["polygon"]).buffer(0) for o in doors]
            for w in bridge:
                g = Polygon(w["polygon"]).buffer(0)
                if any(h.intersection(g).area > 0.2 * min(h.area, g.area) for h in dpoly):
                    continue
                # the bridge spans jamb to jamb with its glazing: it replaces partial windows found inside the gap
                keep, clash = [], False
                for o in wins:
                    h = Polygon(o["polygon"]).buffer(0)
                    a = h.intersection(g).area
                    if a > 0.5 * h.area:
                        continue
                    if a > 0.2 * min(h.area, g.area):
                        clash = True
                    keep.append(o)
                if _DBG is not None:
                    _DBG.append(("merge", [round(v) for v in w["bbox"]], clash))
                if not clash:
                    wins = keep + [w]
        except Exception:
            pass
    wins = _near_doors(wins, doors, mpp)
    _mark_partitions(wins, ww, mpp)
    try:  # r6-windows: a 'glass_partition' that pdf_windows finds in the envelope (outer wall; neighbour roofs drawn
        # with outline walls and no printed room label count as outside) is a facade window
        from pipeline import pdf_windows
        env = pdf_windows.tag_envelope([{"polygon": w["polygon"], "props": {}} for w in wins], ww, mpp,
                                       extra=doors, page=page)
        for w, e in zip(wins, env):
            if w["props"].get("kind") == "glass_partition" and e["props"].get("envelope"):
                w["props"]["kind"] = "window"
    except Exception:  # noqa: BLE001
        pass
    if ww is not walls:  # indices of the unsettled pieces do not address the returned walls
        for w in wins + [d for d in doors if d["props"].get("from") == "wall_gap_sliding"]:
            w["props"]["wall_index"] = None
    try:
        _window_props(wins, page.get("words"))
    except Exception:
        pass
    out = _footprint_filter(doors + wins, walls, mpp)
    try:   # HOOK r5-windows: facade glazing from the window pen (pdf_windows), merged with the windows above
        if os.environ.get("PDF_WINDOWS_PEN", "1") == "0":
            raise ImportError("pdf_windows switched off")
        from pipeline import pdf_windows
        out = pdf_windows.merge(out, pdf_windows.windows(page, ww, mpp), mpp)
    except Exception:  # noqa: BLE001
        pass
    try:   # a window lies in a wall too: drop windows whose long side runs off every wall direction (> 10 deg)
        wd = _wall_dirs(wi)
        if wd:
            out = [o for o in out if o["kind"] != "window" or _on_wall_dir(o["polygon"], wd)]
    except Exception:  # noqa: BLE001
        pass
    dr = [o for o in out if o["kind"] == "door"]
    _tag_doors(dr, page.get("words"))
    try:
        _door_height_tags(dr, page.get("words"))
    except Exception:
        pass
    hm = _door_height_note(page.get("words"))
    if hm:
        for o in dr:
            o["props"].setdefault("height_m", hm)
            o["props"].setdefault("height_source", "page note 'DOOR HEIGHT'")
    for o in dr:   # nothing printed: the consumer's default height applies, and it is marked as such
        o["props"].setdefault("height_source", "default (no height printed)")
        o["props"].setdefault("width_source", "measured (swing radius / leaf)")
    return out


# ---------------------------------------------------------------- gate
def _title_words(words, W, H, rx):
    """Words that read as titles: text >= 1.25x the page's median text height, or text in the title-block corner
    (right 22% / bottom 25% of the sheet). Callouts and notes ('SEE SECTION 3/A301') are body-size and skipped."""
    hs = sorted((w["bbox"][3] - w["bbox"][1]) for w in words if w.get("bbox"))
    med = hs[len(hs) // 2] if hs else 0
    out = []
    for w in words:
        t = w.get("text", "")
        if not rx.search(t) or len(t) > 80:
            continue
        b = w["bbox"]
        big = (b[3] - b[1]) >= 1.25 * med
        corner = W and H and ((b[0] > 0.78 * W and b[1] > 0.45 * H) or (b[1] > 0.75 * H and b[0] > 0.5 * W))
        if big or corner:
            out.append((t, big))
    return out


NOT_FLOOR = re.compile(r"\b(site|roof|ceiling|rcp|demolition|demo|lageplan|dachaufsicht|dachdraufsicht|"
                       r"asemapiirros|vesikatto)\b", re.I)
PLAN_WORD = re.compile(r"\b(plans?|floor\s*plan|grundriss|pohja(?:piirustus)?|kerros|geschoss|layout)\b", re.I)


def gate(page: dict, walls: list, rooms: list) -> tuple[bool, str]:
    """Is this page a floor plan the vector path can read? -> (ok, reason)."""
    if not page or not page.get("W_pt"):
        return False, "no page"
    n_paths = len(page.get("paths", []))
    cover = float(page.get("image_cover") or 0)
    if cover > 0.5 and n_paths < 200:
        return False, f"scanned (image cover {cover:.2f}, {n_paths} vector paths)"
    if n_paths < 20:
        return False, f"too few vector paths ({n_paths})"
    words = page.get("words", [])
    hit_w = _title_words(words, page["W_pt"], page["H_pt"], HEADING)
    hits = [HEADING.search(t).group(1).lower() for t, _ in hit_w]
    plan_w = _title_words(words, page["W_pt"], page["H_pt"], PLAN_WORD)
    labels = [r for r in (rooms or []) if r.get("label") or r.get("number") or r.get("area_printed_m2")]
    if hits:
        # a sheet titled "... PLAN" that also names a schedule / detail keeps going when it has real rooms and
        # its plan title is at least as prominent; otherwise a titled elevation / section / schedule / detail sheet
        big_hits = sum(1 for _, big in hit_w if big)
        big_plan = sum(1 for _, big in plan_w if big)
        if not plan_w or len(labels) < 2 or big_hits > big_plan:
            return False, f"heading keyword: {', '.join(sorted(set(hits))[:3])}"
    if len(walls or []) < 6:
        return False, f"too few wall shapes ({len(walls or [])} < 6)"
    if len(labels) < 2:
        # a small floor (attic, gallery) can hold a single labelled room: accept it when the sheet is titled as a
        # plan ('Grundriss', 'Floor plan') and carries no elevation / section / schedule heading
        not_floor = any(NOT_FLOOR.search(w.get("text", "")) for w in words)
        printed = False
        if len(labels) == 1 and plan_w and not hits and not not_floor:
            try:
                printed = str(page_m_per_pt(page)[1] or "").startswith("printed")
            except Exception:
                printed = False
        if not printed:
            return False, f"too few room labels ({len(labels)} < 2)"
    areas = [r["area_printed_m2"] for r in rooms if r.get("area_printed_m2")]
    if areas:
        # rooms are 2-200 m² typically; closets / halls fall outside, a misread scale or a site plan puts most out
        ok = [a for a in areas if 1 <= a <= 300]
        med = sorted(areas)[len(areas) // 2]
        if not (2 <= med <= 200) or len(ok) < 0.5 * len(areas):
            return False, f"implausible printed areas (median {med:.1f} m², {len(ok)}/{len(areas)} in 1-300 m²)"
    return True, f"plan: {len(walls)} walls, {len(labels)} labelled rooms" + (f", heading words {sorted(set(hits))[:2]} overridden" if hits else "")
