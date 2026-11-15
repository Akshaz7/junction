"""Facade windows from glazing linework (thin parallel line packs across the wall band), pen-aware.

windows(page, walls, mpt) -> [{"kind": "window", "polygon": [[x,y]*4], "bbox", "conf", "props"}]
  page points, top-left origin, y down (the pdf_vector.load_page frame); the pdf_openings window schema.
  props: width_pt, width_m, depth_pt, n_lines, angle_deg, kind "window", sill_m, sill_source, from "pdf_windows",
  pen (layer id), support ("gap" | "run").
merge(ops, wins) -> ops + the windows in wins that do not overlap an existing door / window.

Method (all sizes in metres through mpt; no per-document constants):
  1. straight pieces of every stroked path, plus the long edges of thin filled rectangles (glass panes drawn as
     fills), each tagged with its pen layer (pdf_layers.layers);
  2. packs: 2-5 parallel pieces of equal extent (0.4-6 m long), offsets spread 0.03-0.6 m, i.e. a pack spanning
     a wall band;
  3. support: the pack sits in a wall gap (wall shapes continue the band just past both ends) or lies along a
     wall run (inside the wall polygon, spanning >= half its thickness), and its depth fits the wall thickness;
  4. pen vote: pens whose supported packs carry most of their glazing-length ink are window pens; a pack on a
     window pen needs only one supported end (facade runs whose corner walls were bridged / not read);
  5. one window per drawn pack (MULLION_SPLIT off: a cross line inside a pack is a sash bar of the same window);
     contained / overlapping packs keep the largest. Never raises ([] on error).
"""
from __future__ import annotations

import math
import os

import numpy as np

MIN_W_M, MAX_W_M = 0.3, 6.0       # window width range
MIN_D_M, MAX_D_M = 0.005, 0.12    # glass pane: 2-5 lines 0.5-12 cm apart (pane faces / frame) in the wall band
JAMB = False                      # (experimental) drop short panes next to a longer pane
MULLION_SPLIT = False             # one drawn glazing pack = one window (a sash bar inside it does not make two windows)
SPLIT = False                     # (experimental) replace a found window holding >= 2 panes: esplanades R 1.00 but P 0.69
THIN_D_M = 0.06                   # deeper packs need >= 3 lines (frame + glass), else they are wall faces
END_TOL_M = 0.12                  # equal-extent tolerance of pack lines
PROBE_M = (0.08, 0.2)             # how far past a pack end the wall band is probed
ANG_TOL = math.radians(1.5)
ENVELOPE = os.environ.get("PDF_WINDOWS_ENVELOPE", "1") != "0"   # merge keeps envelope panes only
ENVELOPE_CLOSE_M = 2.5            # building = wall shapes closed over gaps up to this (doors, bays), rooms filled
ENVELOPE_OPEN_MIN_M2 = 50.0       # an unlabelled enclosed hole this big (roof, courtyard) is outside; smaller = void
ENVELOPE_EDGE_M = 1.3             # an envelope pane is this close to the building edge (closed footprint) ...
ENVELOPE_EDGE_ONE_M = 0.25        # ... or this close when only one of its ends meets a wall (support 'one')
ENVELOPE_PROBE_M = (1.5, 3.0)     # probes this far beyond each pane face: one lands outside the building on a facade


def _pieces(page):
    """(segs [N,4], pen [N], page path index [N]) straight pieces of strokes + long edges of thin filled quads."""
    try:
        from pipeline import pdf_layers
        Ls = pdf_layers.layers(page) or []
    except Exception:
        Ls = []
    pen_of = {}
    for L in Ls:
        for i in L.get("paths") or []:
            pen_of[int(i)] = L.get("id")
    segs, pens, pids = [], [], []
    for i, p in enumerate(page.get("paths") or []):
        pts = p.get("pts") or []
        if len(pts) < 2 or p.get("is_arc") or p.get("n_curves", 0) > 0:
            continue
        pen = pen_of.get(i)
        if p.get("stroke") is None:
            if p.get("fill") is None or len(pts) not in (4, 5):
                continue
            q = pts[:4]
            e = [(math.dist(q[k], q[(k + 1) % 4]), k) for k in range(4)]
            e.sort()
            if e[0][0] <= 0 or e[-1][0] < 4 * e[0][0]:
                continue
            for _, k in e[2:]:
                a, b = q[k], q[(k + 1) % 4]
                segs.append((a[0], a[1], b[0], b[1])); pens.append(pen); pids.append(i)
            continue
        if p.get("closed") and len(pts) > 2:
            pts = list(pts) + [pts[0]]
        for a, b in zip(pts, pts[1:]):
            if a[0] != b[0] or a[1] != b[1]:
                segs.append((a[0], a[1], b[0], b[1])); pens.append(pen); pids.append(i)
    return np.asarray(segs, float).reshape(-1, 4), pens, pids


class _Walls:
    def __init__(self, walls):
        from shapely.geometry import Polygon
        from shapely.strtree import STRtree
        self.polys, self.th = [], []
        for w in walls or []:
            try:
                g = Polygon(w["polygon"]).buffer(0)
            except Exception:
                continue
            if g.is_empty or g.area <= 0:
                continue
            self.polys.append(g); self.th.append(float(w.get("thickness_pt") or 0))
        self.tree = STRtree(self.polys) if self.polys else None
        th = sorted(t for t in self.th if t > 0)
        self.t_med = th[len(th) // 2] if th else None
        self.t_max = th[int(0.95 * (len(th) - 1))] if th else None

    def hit(self, x, y, tol):
        """thickness of a wall shape within tol of (x, y), else None."""
        if self.tree is None:
            return None
        from shapely.geometry import Point
        pt = Point(x, y)
        best = None
        for k in self.tree.query(pt.buffer(tol)):
            k = int(k)
            if self.polys[k].distance(pt) <= tol:
                t = self.th[k]
                best = t if best is None else max(best, t)
        return best

    def inside_frac(self, line):
        if self.tree is None:
            return 0.0, None
        inter, th = 0.0, None
        for k in self.tree.query(line):
            k = int(k)
            a = self.polys[k].intersection(line).length
            if a > 0:
                inter += a
                th = self.th[k] if th is None else max(th, self.th[k])
        return inter / max(line.length, 1e-9), th


def _packs(segs, pens, mpt):
    """Packs of parallel equal-extent pieces: list of dict(u, n, t0, t1, offs, idx)."""
    if not len(segs):
        return []
    d = segs[:, 2:] - segs[:, :2]
    L = np.hypot(d[:, 0], d[:, 1])
    lo, hi = MIN_W_M / mpt, MAX_W_M / mpt
    keep = np.nonzero((L >= lo * 0.95) & (L <= hi))[0]
    if not len(keep):
        return []
    d, L, S = d[keep], L[keep], segs[keep]
    ang = np.mod(np.arctan2(d[:, 1], d[:, 0]), math.pi)
    nb = int(math.pi / ANG_TOL)
    b = np.floor(ang / math.pi * nb).astype(int) % nb
    dmax, dmin, etol = MAX_D_M / mpt, MIN_D_M / mpt, END_TOL_M / mpt
    out, used = [], set()
    groups = {}
    for i, bi in enumerate(b):
        groups.setdefault(int(bi), []).append(i)
    for bi in list(groups):
        idx = groups[bi] + groups.get((bi + 1) % nb, [])
        if (bi + 1) % nb == 0:
            idx = groups[bi]
        idx = np.asarray(sorted(set(idx)))
        if len(idx) < 2:
            continue
        a0 = float(np.median(ang[groups[bi]]))
        u = np.array([math.cos(a0), math.sin(a0)]); n = np.array([-u[1], u[0]])
        p0, p1 = S[idx, :2], S[idx, 2:]
        ta, tb = p0 @ u, p1 @ u
        t0, t1 = np.minimum(ta, tb), np.maximum(ta, tb)
        of = (p0 @ n + p1 @ n) / 2
        order = np.argsort(of)
        ofs = of[order]
        for jj, j in enumerate(order):
            gj = int(idx[j])
            if gj in used:
                continue
            k1 = np.searchsorted(ofs, of[j] + dmax, side="right")
            cand = order[jj:k1]
            m = cand[(np.abs(t0[cand] - t0[j]) <= etol) & (np.abs(t1[cand] - t1[j]) <= etol)]
            if len(m) < 2:
                continue
            o = np.sort(of[m])
            distinct = [o[0]]
            for v in o[1:]:
                if v - distinct[-1] > 0.008 / mpt:
                    distinct.append(v)
            if len(distinct) < 2 or len(distinct) > 5:
                continue
            if distinct[-1] - distinct[0] < dmin:
                continue
            gm = [int(idx[q]) for q in m]
            used.update(gm)
            out.append({"u": u, "n": n, "t0": float(np.median(t0[m])), "t1": float(np.median(t1[m])),
                        "o0": float(distinct[0]), "o1": float(distinct[-1]), "nl": len(distinct),
                        "idx": [int(keep[q]) for q in gm], "ang": a0})
    return out


def _corner(p, t, o):
    return (float(p["u"][0] * t + p["n"][0] * o), float(p["u"][1] * t + p["n"][1] * o))


def _support(p, W, mpt):
    """('gap'|'run'|'one'|None, wall thickness)."""
    om = (p["o0"] + p["o1"]) / 2
    tol = 0.03 / mpt
    ends = []
    for t, sg in ((p["t0"], -1), (p["t1"], 1)):
        th = None
        for pr in PROBE_M:
            x, y = _corner(p, t + sg * pr / mpt, om)
            th = W.hit(x, y, tol)
            if th:
                break
        ends.append(th)
    depth = p["o1"] - p["o0"]
    if all(ends):
        th = max(ends)
        if depth <= 1.3 * th + 0.05 / mpt:
            # the gap itself must be open (no wall across the pack's middle)
            from shapely.geometry import LineString
            a = _corner(p, p["t0"] + 0.1 / mpt, om); b = _corner(p, p["t1"] - 0.1 / mpt, om)
            fr, _ = W.inside_frac(LineString([a, b]))
            return ("gap" if fr < 0.5 else "run"), th
        return None, None
    from shapely.geometry import LineString
    a = _corner(p, p["t0"], om); b = _corner(p, p["t1"], om)
    fr, th = W.inside_frac(LineString([a, b]))
    if fr >= 0.8 and th and 0.5 * th <= depth <= 1.3 * th + 0.05 / mpt:
        return "run", th
    th = ends[0] or ends[1]
    if th and depth <= 1.3 * th + 0.05 / mpt:
        return "one", th
    return None, None


def _arc_ends(page):
    pts = []
    for p in page.get("paths") or []:
        q = p.get("pts") or []
        if len(q) < 2:
            continue
        curved = p.get("is_arc") or p.get("n_curves", 0) > 0
        if not curved and len(q) >= 8 and not p.get("closed"):   # a CAD flattening of a swing arc
            curved = _is_arc(q)
        if curved:
            pts.append(q[0]); pts.append(q[-1])
    if not pts:
        return None
    from scipy.spatial import cKDTree
    return cKDTree(np.asarray(pts, float))


def _is_arc(q):
    """open polyline turning steadily one way by small steps (a flattened circular arc)."""
    a = np.asarray(q, float)
    d = np.diff(a, axis=0)
    d = d[np.hypot(d[:, 0], d[:, 1]) > 1e-6]
    if len(d) < 6:
        return False
    h = np.arctan2(d[:, 1], d[:, 0])
    t = (np.diff(h) + math.pi) % (2 * math.pi) - math.pi
    t = t[1:-1] if len(t) > 6 else t        # the swing may carry its leaf / radius line at either end
    return bool((np.all(t > 0) or np.all(t < 0)) and np.abs(t).max() < math.radians(30)
                and abs(t.sum()) > math.radians(45))


def _near_arc(p, tree, r):
    if tree is None:
        return False
    for t in (p["t0"], p["t1"]):
        for o in (p["o0"], p["o1"]):
            if tree.query_ball_point(_corner(p, t, o), r):
                return True
    return False


def _framed(p, segs, mpt):
    """cross pieces (mullion / jamb profile sides) span the pack's depth at both of its ends."""
    u, n = p["u"], p["n"]
    a, b = segs[:, :2], segs[:, 2:]
    ta, tb, oa, ob = a @ u, b @ u, a @ n, b @ n
    d = p["o1"] - p["o0"]
    cross = (np.abs(ta - tb) <= 0.01 / mpt) & (np.minimum(oa, ob) <= p["o0"] + 0.15 * d) & \
        (np.maximum(oa, ob) >= p["o1"] - 0.15 * d) & (np.abs(oa - ob) <= 3 * d)
    tm = (ta + tb)[cross] / 2
    r = 0.06 / mpt
    return bool(np.any(np.abs(tm - p["t0"]) <= r) and np.any(np.abs(tm - p["t1"]) <= r))


def _split_mullions(p, segs, mpt):
    """t-positions where a cross piece spans >= 80 % of the pack depth inside it."""
    if not len(segs):
        return []
    u, n = p["u"], p["n"]
    a, b = segs[:, :2], segs[:, 2:]
    ta, tb, oa, ob = a @ u, b @ u, a @ n, b @ n
    d = p["o1"] - p["o0"]
    cross = (np.abs(ta - tb) <= 0.02 / mpt) & (np.minimum(oa, ob) <= p["o0"] + 0.2 * d) & \
        (np.maximum(oa, ob) >= p["o1"] - 0.2 * d)
    tm = (ta + tb) / 2
    cut = tm[cross & (tm > p["t0"] + MIN_W_M / mpt) & (tm < p["t1"] - MIN_W_M / mpt)]
    cut = np.sort(cut)
    res = []
    for c in cut:
        if not res or c - res[-1] >= MIN_W_M / mpt:
            res.append(float(c))
    return res


def windows(page, walls, mpt) -> list:
    try:
        return _windows(page, walls, mpt)
    except Exception:
        return []


def _windows(page, walls, mpt):
    if not page or not page.get("paths") or not walls:
        return []
    if not mpt:
        try:
            from pipeline.pdf_openings import page_m_per_pt
            mpt = page_m_per_pt(page)[0]
        except Exception:
            mpt = None
    if not mpt:
        return []
    segs, pens, pids = _pieces(page)
    packs = _packs(segs, pens, mpt)
    if not packs:
        return []
    W = _Walls(walls)
    if W.tree is None:
        return []
    arc_end = _arc_ends(page)
    packs = [p for p in packs if p["o1"] - p["o0"] <= THIN_D_M / mpt or p["nl"] >= 3]
    for p in packs:
        p["sup"], p["th"] = _support(p, W, mpt)
        if p["sup"] in (None, "one") and _framed(p, segs, mpt):
            p["sup"], p["th"] = "frame", p["th"] or (p["o1"] - p["o0"])
        p["door"] = _near_arc(p, arc_end, 0.12 / mpt)
        ps = [pens[i] for i in p["idx"] if pens[i] is not None]
        # majority pen; ties go to the smallest id (iterating a set of str follows PYTHONHASHSEED: run-dependent)
        p["pen"] = max(sorted(set(ps)), key=ps.count) if ps else None
    # pen vote: share of each pen's pack ink (length x lines) that is wall-supported
    tot, good = {}, {}
    for p in packs:
        if p["pen"] is None:
            continue
        v = (p["t1"] - p["t0"]) * p["nl"]
        tot[p["pen"]] = tot.get(p["pen"], 0) + v
        if p["sup"] in ("gap", "run", "frame"):
            good[p["pen"]] = good.get(p["pen"], 0) + v
    npk = {}
    for p in packs:
        if p["sup"] in ("gap", "run", "frame") and p["pen"] is not None:
            npk[p["pen"]] = npk.get(p["pen"], 0) + 1
    # a pane that meets a swing arc is a door leaf; pens drawing mostly leaves are door pens
    nd, na = {}, {}
    for p in packs:
        if p["sup"] and p["pen"] is not None:
            na[p["pen"]] = na.get(p["pen"], 0) + 1
            nd[p["pen"]] = nd.get(p["pen"], 0) + bool(p["door"])
    door_pens = {k for k in na if nd.get(k, 0) >= max(2, 0.3 * na[k])}
    packs = [p for p in packs if not p["door"] and p["pen"] not in door_pens]
    win_pens = {k for k in tot if npk.get(k, 0) >= 3 and good.get(k, 0) >= 0.6 * tot[k]}
    acc = [p for p in packs if p["sup"] in ("gap", "run", "frame") or (p["sup"] == "one" and p["pen"] in win_pens)]
    # a short pane right next to a clearly longer pane in the same band is that window's jamb / frame block
    def _jamb(p):
        L = p["t1"] - p["t0"]
        if L * mpt > 0.7:
            return False
        th = p["th"] or (p["o1"] - p["o0"])
        om = (p["o0"] + p["o1"]) / 2
        for q in acc:
            if q is p or abs(float(q["u"] @ p["u"])) < 0.999:
                continue
            if q["t1"] - q["t0"] < 1.5 * L:
                continue
            if abs((q["o0"] + q["o1"]) / 2 - om) > th:
                continue
            gap = max(q["t0"] - p["t1"], p["t0"] - q["t1"])
            if -0.05 / mpt <= gap <= 0.25 / mpt:
                return True
        return False
    acc = [p for p in acc if not (JAMB and _jamb(p))]
    # one window per wall band position: drop packs contained in a larger accepted pack
    from shapely.geometry import Polygon
    items = []
    for p in acc:
        th = p["th"] or (p["o1"] - p["o0"])
        om = (p["o0"] + p["o1"]) / 2
        oa, ob = min(p["o0"], om - th / 2), max(p["o1"], om + th / 2)
        cuts = [p["t0"]] + (_split_mullions(p, segs, mpt) if MULLION_SPLIT else []) + [p["t1"]]
        for ta, tb in zip(cuts, cuts[1:]):
            poly = [_corner(p, ta, oa), _corner(p, tb, oa), _corner(p, tb, ob), _corner(p, ta, ob)]
            items.append((tb - ta, p, Polygon(poly), poly, ta, tb, ob - oa))
    items.sort(key=lambda r: -r[0] * (1 + 0.2 * r[1]["nl"]))
    out, kept = [], []
    for wlen, p, g, poly, ta, tb, dep in items:
        if any(g.intersection(h).area > 0.3 * min(g.area, h.area) for h in kept):
            continue
        kept.append(g)
        conf = 0.55 + 0.1 * (p["sup"] == "gap") + 0.1 * (p["pen"] in win_pens) + 0.05 * (p["nl"] >= 3)
        poly = [[round(x, 2), round(y, 2)] for x, y in poly]
        xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
        out.append({"kind": "window", "polygon": poly, "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "conf": round(min(conf, 0.9), 2),
                    "props": {"width_pt": round(wlen, 2), "width_m": round(wlen * mpt, 2),
                              "depth_pt": round(dep, 2), "depth_m": round(dep * mpt, 2), "n_lines": p["nl"],
                              "angle_deg": round(math.degrees(p["ang"]), 1), "kind": "window",
                              "sill_m": 0.9, "sill_source": "default", "from": "pdf_windows",
                              "pen": p["pen"], "support": p["sup"], "wall_index": None,
                              "evidence": {"Source": "measured",
                                           "Detail": f"{p['nl']} parallel glazing lines, width {wlen * mpt:.2f} m "
                                                     f"measured along them; page paths "
                                                     f"{sorted({int(pids[i]) for i in p['idx']})[:12]}",
                                           "paths": sorted({int(pids[i]) for i in p["idx"]}),
                                           "sill": "default (not printed)"}}})
    try:
        tag_envelope(out, walls, mpt, page=page)
    except Exception:
        pass
    return out


def _filled(polys, close, rooms_at=None, open_min=0.0):
    """Shapes closed over gaps up to `close` (doors, window bays) with the rooms filled: an enclosed hole is a room
    when it holds a point of rooms_at (printed room labels) or is smaller than open_min (shaft, floor void,
    unlabelled store); a larger hole with none (roof, courtyard drawn with outline walls) stays open, so it counts
    as outside. rooms_at None: every hole is filled."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    r = close / 2
    u = unary_union(polys).buffer(r, quad_segs=4).buffer(-r, quad_segs=4)
    parts = []
    for g in getattr(u, "geoms", [u]):
        if g.geom_type != "Polygon" or g.area <= 0:
            continue
        keep = []
        if rooms_at is not None:
            for ring in g.interiors:
                h = Polygon(ring)
                if h.area >= open_min and not any(h.contains(q) for q in rooms_at):
                    keep.append(ring)
        parts.append(Polygon(g.exterior, keep))
    return unary_union(parts) if parts else None


def _room_points(page):
    """Centres of the printed room labels (name / number / area blocks, pdf_rooms.label_blocks); None when the
    sheet prints fewer than 3 (then every enclosed hole counts as a room)."""
    from shapely.geometry import Point
    try:
        from pipeline import pdf_rooms
        bl = pdf_rooms.label_blocks(page.get("words") or [])
    except Exception:
        return None
    pts = [Point((b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2) for b in bl
           if b.get("bbox") and (b.get("area_printed_m2") is not None or b.get("number"))]
    return pts if len(pts) >= 3 else None


def tag_envelope(wins, walls, mpt, extra=(), page=None):
    """props.envelope: True when the pane sits in the building envelope (outer wall). The building is the wall
    shapes (+ known openings `extra`, + the panes themselves, which close glazed bays) closed over ENVELOPE_CLOSE_M
    gaps with the rooms filled (holes holding a printed room label; with no labels every hole); the pane touches
    its edge (ENVELOPE_EDGE_M) and one of the probes ENVELOPE_PROBE_M beyond the pane faces lands outside it.
    Building on both sides = an interior glazed partition (False). No usable footprint -> None (untested)."""
    from shapely.geometry import Point, Polygon
    polys = []
    for o in list(walls or []) + list(extra or []) + list(wins or []):
        try:
            g = Polygon(o["polygon"]).buffer(0)
        except Exception:
            continue
        if not g.is_empty and g.area > 0:
            polys.append(g)
    rooms_at = _room_points(page) if page else None
    foot = _filled(polys, ENVELOPE_CLOSE_M / mpt, rooms_at or None, ENVELOPE_OPEN_MIN_M2 / mpt ** 2) \
        if len(polys) >= 3 else None
    for w in wins or []:
        pr = w.setdefault("props", {})
        if foot is None:
            pr["envelope"] = None
            continue
        p = w["polygon"]
        e = sorted((math.dist(p[i], p[(i + 1) % 4]), i) for i in range(4))
        dep = e[0][0]
        a, b = p[e[-1][1]], p[(e[-1][1] + 1) % 4]
        L = max(math.dist(a, b), 1e-9)
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        cx = sum(q[0] for q in p) / 4; cy = sum(q[1] for q in p) / 4
        inside = [foot.contains(Point(cx + nx * (dep / 2 + m / mpt) * sg, cy + ny * (dep / 2 + m / mpt) * sg))
                  for sg in (1, -1) for m in ENVELOPE_PROBE_M]
        # ... and the pane lies on the building's edge (its outer face), not on a parallel wall just inside it
        # (closing the walls over ENVELOPE_CLOSE_M can move that edge ~1 m out where a parapet / roof outline runs
        # beside the facade; a pane read from one wall end only must sit right on it)
        tol = ENVELOPE_EDGE_M if pr.get("support") != "one" else ENVELOPE_EDGE_ONE_M
        edge = foot.boundary.distance(Polygon(p)) <= tol / mpt
        pr["envelope"] = (not all(inside)) and edge
    return wins


def merge(ops, wins, mpt=None):
    """ops + windows from wins that overlap no existing door / window (by polygon area or 0.5 m centre) and lie
    near the occupied building (pdf_openings._near_doors: within ~7 m of the swing doors' hull)."""
    try:
        from shapely.geometry import Polygon
        try:
            from pipeline.pdf_openings import _near_doors
            wins = _near_doors(list(wins or []), [o for o in ops or [] if o.get("kind") == "door"], mpt)
        except Exception:
            pass
        # windows belong in the envelope: panes with building on both sides are interior glazed partitions
        if ENVELOPE:
            wins = [w for w in wins or [] if w.get("props", {}).get("envelope") is not False]
        hw = [Polygon(o["polygon"]).buffer(0) for o in ops or [] if o.get("polygon") and o.get("kind") == "window"
              and o.get("props", {}).get("kind") != "glass_partition"]
        # window pens learnt from the page: pens whose panes sit inside >= 2 windows already found
        hits = {}
        for w in wins or []:
            g = Polygon(w["polygon"]).buffer(0)
            if any(h.intersection(g).area > 0.3 * g.area for h in hw):
                pen = w["props"].get("pen")
                hits[pen] = hits.get(pen, 0) + 1
        pens = {k for k, v in hits.items() if v >= 2 and k is not None}
        wins = [w for w in wins or [] if w["props"].get("pen") in pens]
        # an existing window holding >= 2 panes is a row of windows split by mullions: the panes replace it
        res, used = [], set()
        for o in ops or []:
            if o.get("kind") == "window" and o.get("polygon"):
                h = Polygon(o["polygon"]).buffer(0)
                inn = [k for k, w in enumerate(wins) if k not in used and
                       h.intersection(Polygon(w["polygon"]).buffer(0)).area > 0.3 * Polygon(w["polygon"]).area]
                if SPLIT and len(inn) >= 2:
                    for k in inn:
                        used.add(k)
                        wp = wins[k]["props"]
                        for key in ("kind", "sill_m", "sill_source", "height_m", "exterior"):
                            if key in o.get("props", {}):
                                wp[key] = o["props"][key]
                        res.append(wins[k])
                    continue
            res.append(o)
        have = [Polygon(o["polygon"]).buffer(0) for o in res if o.get("polygon")]
        for k, w in enumerate(wins):
            if k in used:
                continue
            g = Polygon(w["polygon"]).buffer(0)
            if any(h.intersection(g).area > 0.1 * min(h.area, g.area) or h.distance(g) < 1e-6 and
                   h.centroid.distance(g.centroid) < 0.5 * max(math.sqrt(g.area), 1) for h in have):
                continue
            have.append(g); res.append(w)
        return _dedupe(res)
    except Exception:
        return list(ops or [])


def _dedupe(ops):
    """One window per drawn glazing: of windows overlapping by > 30 % of the smaller (a gap window and a jamb window
    read from the same lines), the larger stays. Doors and everything else pass unchanged."""
    from shapely.geometry import Polygon
    win = [(k, Polygon(o["polygon"]).buffer(0)) for k, o in enumerate(ops)
           if o.get("kind") == "window" and o.get("polygon")]
    drop = set()
    for k, g in sorted(win, key=lambda r: -r[1].area):
        if k in drop:
            continue
        for j, h in win:
            if j != k and j not in drop and h.area <= g.area and g.intersection(h).area > 0.3 * min(g.area, h.area):
                drop.add(j)
    return [o for k, o in enumerate(ops) if k not in drop]
