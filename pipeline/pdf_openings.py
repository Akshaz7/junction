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
import re
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
    key = lambda x, y: (round(x / tol), round(y / tol))
    at = defaultdict(list)
    for i in idx:
        x0, y0, x1, y1 = segs[i]
        at[key(x0, y0)].append((i, 0)); at[key(x1, y1)].append((i, 1))
    cos_max = math.cos(math.radians(MAX_TURN_DEG))
    used = set()

    def nxt(i, end, sign):
        """segment continuing segment i past its endpoint `end` (0/1) smoothly; returns (j, far_end, cross)."""
        x0, y0, x1, y1 = segs[i]
        px, py = (x1, y1) if end == 1 else (x0, y0)
        dx, dy = (x1 - x0, y1 - y0) if end == 1 else (x0 - x1, y0 - y1)
        n = math.hypot(dx, dy); dx /= n; dy /= n
        best = None
        for j, e in at.get(key(px, py), []):
            if j == i or j in used:
                continue
            a0, b0, a1, b1 = segs[j]
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
        x0, y0, x1, y1 = segs[i]
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
                q = segs[j][2:] if fe == 1 else segs[j][:2]
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
        best, ix = None, None
        for (px, py), sg in ((hinge, -1), (closed, 1)):
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
        return (tuple(best) if best else None), ix

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
    if not (70 <= span <= 110):
        return None
    if not np.all(np.diff(a) * np.sign(a[-1] - a[0]) > -1e-6):
        return None
    return {"c": (cx, cy), "r": r, "rms": rms, "ends": (pl[0], pl[-1]), "ccw": bool(a[-1] > a[0]), "pts": pl}


def _leaf_end(arc, segs):
    """Which arc end the door leaf line reaches (the open position), or None when no leaf line is drawn."""
    if not len(segs):
        return None
    cx, cy = arc["c"]; r = arc["r"]
    tol = max(0.6, 0.06 * r)
    best = None
    for k, (ex, ey) in enumerate(arc["ends"]):
        for (p, q) in ((segs[:, :2], segs[:, 2:]), (segs[:, 2:], segs[:, :2])):
            ok = (np.hypot(p[:, 0] - cx, p[:, 1] - cy) < tol) & (np.hypot(q[:, 0] - ex, q[:, 1] - ey) < tol)
            if ok.any():
                return k
            # leaf drawn as a thin rectangle: a side running hinge-ish -> end-ish of length ~r
            L = np.hypot(q[:, 0] - p[:, 0], q[:, 1] - p[:, 1])
            ok2 = (np.abs(L - r) < 0.12 * r) & (np.hypot(q[:, 0] - ex, q[:, 1] - ey) < 0.12 * r) & \
                  (np.hypot(p[:, 0] - cx, p[:, 1] - cy) < 0.12 * r)
            if ok2.any() and best is None:
                best = k
    return best


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
    if band and 0.02 * r <= band[1] - band[0] <= 0.8 * r and band[0] <= 0.15 * r and band[1] >= -0.15 * r:
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
            "near_wall": bool(near), "leaf": leaf_k is not None, "ccw": arc["ccw"]}


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


def _doors(page, segs, arcs, wi: _WallIndex):
    rmin, rmax, _ = _door_range(page)
    mpp = page_m_per_pt(page)[0]
    cands = [_arc_door(pl, wi, rmin, rmax) for pl in arcs + (_chains(segs) if len(segs) else [])]
    cands = [c for c in cands if c]
    # de-duplicate (the same arc drawn twice, or a Bezier + its flattening)
    cands.sort(key=lambda c: c["rms"] / c["r"])
    keep = []
    for c in cands:
        if any(math.dist(c["c"], k["c"]) < 0.1 * c["r"] and abs(c["r"] - k["r"]) < 0.1 * c["r"] for k in keep):
            continue
        keep.append(c)
    doors = []
    for arc in keep:
        leaf = _leaf_end(arc, segs)
        tang = _tangent_ends(arc, segs)
        if tang >= 2 or (tang == 1 and leaf is None):
            continue  # rounded corner / fillet / curved wall
        dd = _door_from_arc(arc, leaf, wi)
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
            if j in used or abs(a["r"] - b["r"]) > 0.15 * a["r"]:
                continue
            if math.dist(a["closed"], b["closed"]) < 0.12 * a["r"]:
                pair = j; break
        if pair is None:
            out.append((a, False))
        else:
            used.add(pair)
            b = doors[pair]
            # one opening across the wall for both leaves: oriented rectangle around both leaves' openings
            from shapely.geometry import MultiPoint
            mr = MultiPoint([tuple(v) for v in a["poly"] + b["poly"]]).minimum_rotated_rectangle
            q = [list(v) for v in list(mr.exterior.coords)[:4]]
            m = dict(a); m["poly"] = q; m["r2"] = b["r"]; m["leaf"] = a["leaf"] or b["leaf"]
            out.append((m, True))
    res = []
    for d, dbl in out:
        width = d["r"] + (d.get("r2", 0) if dbl else 0)
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
                 "wall_index": d.get("wall"), "leaf": bool(d["leaf"]), "double": bool(dbl), "n_leaves": 2 if dbl else 1,
                 "swing_bbox": [round(v, 2) for v in _bbox([d["hinge"], d["closed"], d["opened"]])]}
        if mpp:  # same keys as the DXF plan map's doors
            props["swing_radius_m"] = round(d["r"] * mpp, 2)
            props["leaf_len_m"] = round(d["r"] * mpp, 2)
            props["width_m"] = round(width * mpp, 3)
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
                l0, l1 = float(np.median(lo[inpk])), float(np.median(hi[inpk]))
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
                     "wall_axis_deg": round(math.degrees(math.atan2(uy, ux)) % 180, 2), "from": "wall_gap_sliding"}
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


def _footprint_filter(ops, walls):
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
    out = []
    for o in ops:
        try:
            g = Polygon(o["polygon"])
        except Exception:
            continue
        if hull.intersects(g):
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


def openings(page: dict, walls: list) -> list:
    """Doors and windows on a vector page, in page points (top-left origin, y down)."""
    if not page or not page.get("paths"):
        return []
    segs, arcs = _segments(page)
    wi = _WallIndex(walls)
    doors = _doors(page, segs, arcs, wi)
    mpp = page_m_per_pt(page)[0]
    gap = _gap_windows(segs, walls, wi, doors, mpp)
    doors = doors + [o for o in gap if o["kind"] == "door"]
    wins = [o for o in gap if o["kind"] == "window"]
    door_boxes = [d["bbox"] for d in doors]
    for w in _jamb_windows(segs, wi, mpp) + _windows(segs, wi, doors, mpp):
        b = w["bbox"]
        if any(b[0] < k[2] and k[0] < b[2] and b[1] < k[3] and k[1] < b[3] for k in door_boxes):
            continue
        if not any(b[0] < k["bbox"][2] and k["bbox"][0] < b[2] and b[1] < k["bbox"][3] and k["bbox"][1] < b[3]
                   for k in wins):
            wins.append(w)
    wins = [w for w in (_fit_window(w, wi, mpp) for w in wins) if w]
    return _footprint_filter(doors + wins, walls)


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
        return False, f"too few room labels ({len(labels)} < 2)"
    areas = [r["area_printed_m2"] for r in rooms if r.get("area_printed_m2")]
    if areas:
        # rooms are 2-200 m² typically; closets / halls fall outside, a misread scale or a site plan puts most out
        ok = [a for a in areas if 1 <= a <= 300]
        med = sorted(areas)[len(areas) // 2]
        if not (2 <= med <= 200) or len(ok) < 0.5 * len(areas):
            return False, f"implausible printed areas (median {med:.1f} m², {len(ok)}/{len(areas)} in 1-300 m²)"
    return True, f"plan: {len(walls)} walls, {len(labels)} labelled rooms" + (f", heading words {sorted(set(hits))[:2]} overridden" if hits else "")
