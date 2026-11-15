"""Sanitary terminals (WC / basin / shower / bath) inside rooms whose printed label names a wet room.

    find(page, mpt, rooms, walls, existing) -> [{"kind", "polygon": [[x,y],...] page pt, "props": {...}, "conf"}]

Item format is pdf_fixtures' (kinds wc | basin | shower | bath | urinal). Page coordinates are pdf_vector's (page
points, top-left origin, y down); sizes are read through mpt (metres per point). The search runs ONLY around rooms
whose label says WC / toilet / shower / bath / washroom / accessible (EN / DE / FI / SV / DA / NO words), so the
rest of the sheet can never gain a fixture. CAD symbols are usually exploded into many 2-point segments: the stroked
linework of each wet zone is noded and polygonized into faces first, and every face is then measured:

  WC      a bowl face 0.30-0.48 m wide, 0.35-0.80 m long, ONE short end rounded (two sharp corners at the cistern /
          wall end, two rounded corners at the front); a cistern face against that flat end is merged in.
  basin   a face 0.25-0.65 x 0.30-0.75 m with all four corners rounded (or an outline holding a round bowl face).
  shower  a square-ish tray face 0.75-1.25 m holding a drain circle or crossing diagonals; or, in a room labelled
          shower with no tray, each wall-mounted shower head (small circle at the end of a hose zig-zag) gets a
          0.9 x 0.9 m floor zone against the wall.
  bath    a face 0.65-0.85 x 1.5-1.9 m with an inner rounded tub face.

Anything already covered by `existing` (any fixture item) is skipped. Never raises: [] on any error.
"""
from __future__ import annotations

import math
import re

import numpy as np

KINDS = ("wc", "basin", "shower", "bath", "urinal")
# wet-room words: EN / DE / FI / SV / DA / NO (lower-cased label + number text)
WET_ROOM = re.compile(
    r"\bw\.?c\b|toilet|lavatory|restroom|washroom|wash ?room|bath|shower|accessible|disabled|\bada\b|"
    r"dusch|\bbad\b|badez|waschr|\babort|toalett|\btoa\b|\bdusj|\bbade|badev|\bvask|"
    r"suihku|\bpesuh|pesuhuone|\bkph\b|\bkh\b|\bph\b|\bwc\d|\bhwc|\binva",
    re.I)
HEAD_ROOM = re.compile(r"shower|dusch|\bdusj|suihku|\bpesuh|pesuhuone|\bph\b", re.I)  # open wall showers only here
KITCHEN = re.compile(r"kitchen|kitch|\bkit\b|keitti|k[üu]che|\bkök|pantry", re.I)
SHOWER_ROOM = re.compile(r"shower|dusch|\bdusj|suihku|\bpesuh|pesuhuone|\bph\b|\bkph\b|bath|\bbad\b|\bbade", re.I)


def find(page: dict, mpt: float | None, rooms: list, walls: list, existing: list | None = None) -> list:
    """Sanitary terminals in labelled wet rooms (see module doc). Never raises."""
    try:
        if not mpt or mpt <= 0 or not page or not rooms:
            return []
        return _find(page, float(mpt), rooms or [], walls or [], existing or [])
    except Exception:  # noqa: BLE001 - detection must never break ingest
        return []


def _label(r) -> str:
    return " ".join(str(r.get(k) or "") for k in ("label", "name", "number")).strip()


def _poly(g):
    c = np.asarray(g.exterior.coords)[:-1]
    return [[round(float(x), 2), round(float(y), 2)] for x, y in c]


def _rect(g):
    """Oriented rectangle of g: (corners (4,2), length pt, width pt, unit major axis)."""
    r = g.minimum_rotated_rectangle
    c = np.asarray(r.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    l1, l2 = float(np.hypot(*e1)), float(np.hypot(*e2))
    if min(l1, l2) <= 0:
        return None
    major = e1 / l1 if l1 >= l2 else e2 / l2
    return c, max(l1, l2), min(l1, l2), major


def _find(page, mpt, rooms, walls, existing):
    import shapely
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import polygonize, unary_union

    pt = lambda m: m / mpt  # noqa: E731
    wet, dry = [], []
    for r in rooms:
        try:
            g = Polygon(r["polygon"]).buffer(0)
        except Exception:  # noqa: BLE001
            continue
        if g.is_empty or g.area <= 0:
            continue
        lab = _label(r)
        if WET_ROOM.search(lab):
            wet.append((g, lab, r))
        elif re.search(r"[a-z]{3,}", lab, re.I):  # a named dry room (office, corridor); unnamed rooms stay open
            dry.append((g, lab, r))
    if not wet:
        return []
    wall_u = None
    wp = []
    for w in walls:
        try:
            g = Polygon(w["polygon"]).buffer(0)
            if not g.is_empty:
                wp.append(g)
        except Exception:  # noqa: BLE001
            pass
    if wp:
        wall_u = unary_union(wp)
        shapely.prepare(wall_u)
    dry_u = unary_union([g.buffer(-pt(0.15)) for g, _, _ in dry if g.area > pt(1.0) ** 2]) if dry else None
    if dry_u is not None and dry_u.is_empty:
        dry_u = None
    have = []
    for f in existing or []:
        try:
            have.append(Polygon(f["polygon"]).buffer(pt(0.05)))
        except Exception:  # noqa: BLE001
            pass
    have_u = unary_union(have) if have else None

    # ---- stroked segments of the page, vectorised (fill-only masks and dashed lines excluded)
    paths = page.get("paths") or []
    A, I = [], []
    for i, p in enumerate(paths):
        q = p.get("pts")
        if not q or len(q) < 2 or p.get("stroke") is None or p.get("dashed") or p.get("pattern"):
            continue
        if p.get("closed") and (q[0][0] != q[-1][0] or q[0][1] != q[-1][1]):
            q = list(q) + [q[0]]
        A.extend(q)
        I.extend([i] * len(q))
    if not A:
        return []
    A = np.asarray(A, float)
    I = np.asarray(I)
    k = np.flatnonzero(I[:-1] == I[1:])
    S = np.hstack([A[k], A[k + 1]])
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    ok = (L > 1e-3) & (L * mpt <= 2.0)
    S = S[ok]
    mid = (S[:, :2] + S[:, 2:]) / 2
    # no wall mask here: a cistern often sits inside a (slightly too thick) wall polygon

    out = []
    done = []  # union of accepted polygons
    for g, lab, r in wet:
        zone = g.buffer(pt(0.9))
        if dry_u is not None:
            zone = zone.difference(dry_u)
        if zone.is_empty:
            continue
        x0, y0, x1, y1 = zone.bounds
        kk = (mid[:, 0] >= x0) & (mid[:, 0] <= x1) & (mid[:, 1] >= y0) & (mid[:, 1] <= y1)
        kk[kk] = shapely.contains_xy(zone, mid[kk, 0], mid[kk, 1])
        sg = S[kk]
        if len(sg) < 4 or len(sg) > 60000:
            continue
        sg = _snap(sg, 0.2)
        # exploded dash patterns (dash-dot axes, turning circles) are lone strokes touching nothing at either end;
        # they would cut symbol faces apart, so drop every segment whose two ends are both free
        key = np.round(np.vstack([sg[:, :2], sg[:, 2:]]) * 100).astype(np.int64)
        key = key[:, 0] * np.int64(1 << 31) + key[:, 1]
        _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        c = cnt[inv.reshape(-1)]
        sg = sg[(c[:len(sg)] > 1) | (c[len(sg):] > 1)]
        if len(sg) < 4:
            continue
        lines = shapely.linestrings(sg.reshape(-1, 2, 2))
        try:
            faces = [Polygon(f.exterior) for f in polygonize(unary_union(lines))]
        except Exception:  # noqa: BLE001
            continue
        tiny = [f for f in faces if 0.0008 <= f.area * mpt * mpt < 0.004 and f.is_valid]  # shower-head roses
        faces = [f.simplify(0.05) for f in faces if f.area * mpt * mpt >= 0.004 and f.is_valid]
        faces += _groups(faces, mpt)
        shower_room = bool(SHOWER_ROOM.search(lab))
        cands = _classify(faces, mpt, pt, lines, shower_room)
        if HEAD_ROOM.search(lab) and not KITCHEN.search(lab) and not any(c[0] in ("shower", "bath") for c in cands):
            cands += _shower_heads(faces + tiny, sg, mpt, pt, wall_u, g)
        for kind, poly, props, conf in cands:
            c = poly.centroid
            if not g.buffer(pt(0.9)).contains(c):
                continue
            if dry_u is not None and dry_u.contains(c):
                continue
            if have_u is not None and have_u.intersects(poly.buffer(-pt(0.02))):
                continue
            if any(d.intersection(poly).area > 0.3 * min(d.area, poly.area) for d in done):
                continue
            if wall_u is not None and wall_u.intersection(poly).area > 0.02 * poly.area:
                # a cistern drawn into a (too thick) wall polygon: keep the part standing in the room
                rest = poly.difference(wall_u)
                parts = sorted(getattr(rest, "geoms", [rest]), key=lambda q: -q.area)
                if not parts or parts[0].is_empty or parts[0].area < 0.6 * poly.area:
                    continue
                poly = parts[0].minimum_rotated_rectangle.buffer(-pt(0.005), join_style="mitre")
                if poly.is_empty or poly.geom_type != "Polygon":
                    continue
                props = dict(props, trimmed_at_wall=True)
            done.append(poly)
            near = min(wet, key=lambda w: w[0].distance(c))  # the wet room the symbol actually stands in
            props = dict(props, room=near[1] or None, source="pdf_sanitary")
            out.append({"kind": kind, "polygon": _poly(poly), "conf": round(conf, 2), "props": props})
    return out


def _groups(faces, mpt, max_m=0.8):
    """Outer outline of each group of touching small faces (a basin rim cut in two by its tap and bowl)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    small = [f for f in faces if max(f.bounds[2] - f.bounds[0], f.bounds[3] - f.bounds[1]) * mpt <= max_m]
    if len(small) < 2:
        return []
    t = STRtree(small)
    parent = list(range(len(small)))

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    a, b = t.query(small, predicate="touches")
    for i, j in zip(a.tolist(), b.tolist()):
        ri, rj = root(i), root(j)
        if ri != rj:
            parent[rj] = ri
    grp = {}
    for i in range(len(small)):
        grp.setdefault(root(i), []).append(small[i])
    out = []
    for g in grp.values():
        if len(g) < 2:
            continue
        u = unary_union(g)
        if u.geom_type == "Polygon" and max(u.bounds[2] - u.bounds[0], u.bounds[3] - u.bounds[1]) * mpt <= max_m:
            out.append(Polygon(u.exterior).simplify(0.05))
    return out


def _snap(sg, tol):
    """Merge segment end points closer than tol (pt): exploded CAD arcs leave 0.01-0.03 pt gaps between pieces.
    Leader clustering (each point joins the first leader within tol), so dense strokes never chain-collapse."""
    from scipy.spatial import cKDTree
    P = np.vstack([sg[:, :2], sg[:, 2:]])
    n = len(P)
    lead = np.full(n, -1)
    nb = cKDTree(P).query_ball_point(P, tol)
    for i in range(n):
        if lead[i] >= 0:
            continue
        for j in nb[i]:
            if lead[j] < 0:
                lead[j] = i
    P = P[lead]
    out = np.hstack([P[:len(sg)], P[len(sg):]])
    return out[np.hypot(out[:, 2] - out[:, 0], out[:, 3] - out[:, 1]) > 1e-6]


def _corner_gaps(f, rect):
    """Distance (pt) from each oriented-rect corner to the face outline: ~0 for a sharp corner."""
    from shapely.geometry import Point
    ext = f.exterior
    return np.array([ext.distance(Point(*c)) for c in rect[0]])


def _classify(faces, mpt, pt, lines, shower_room):
    from shapely.geometry import Polygon
    from shapely.strtree import STRtree
    out = []
    if not faces:
        return out
    tree = STRtree(faces)
    info = []
    for f in faces:
        rc = _rect(f)
        info.append(rc)
    used = set()
    order = sorted(range(len(faces)), key=lambda i: -faces[i].area)
    for i in order:
        f, rc = faces[i], info[i]
        if rc is None or i in used:
            continue
        corners, l, w, major = rc
        lm, wm = l * mpt, w * mpt
        fill = f.area / (l * w)
        nv = len(f.exterior.coords) - 1
        gaps = _corner_gaps(f, rc) * mpt
        sharp = gaps < 0.012
        inner = [j for j in tree.query(f) if j != i and faces[j].area < 0.6 * f.area and
                 f.contains(faces[j].representative_point())]
        # ---- shower tray / bath: big face with a drain circle or diagonals inside
        if 0.72 <= wm and lm <= 1.3 and lm / wm <= 1.4 and fill > 0.85 and shower_room:
            circ = [j for j in inner if info[j] and 0.04 <= info[j][1] * mpt <= 0.2 and
                    len(faces[j].exterior.coords) > 8 and faces[j].area / (info[j][1] * info[j][2]) > 0.65]
            nlines = len(lines[_crossing(lines, f)]) if not circ else 0
            if circ or nlines >= 2:
                out.append(("shower", _rect_poly(corners), {"size_m": [round(lm, 2), round(wm, 2)],
                            "evidence": "tray with drain" if circ else "tray with diagonals"}, 0.75))
                used.update(inner)
                continue
        if 1.45 <= lm <= 2.0 and 0.6 <= wm <= 0.9 and fill > 0.85:
            tub = [j for j in inner if info[j] and info[j][1] * mpt >= 1.0 and info[j][2] * mpt >= 0.4]
            if tub:
                out.append(("bath", _rect_poly(corners), {"size_m": [round(lm, 2), round(wm, 2)],
                            "evidence": "rim with inner tub"}, 0.75))
                used.update(inner)
                continue
        if not (0.15 <= wm <= 0.65 and 0.25 <= lm <= 0.85) or fill < 0.62:
            continue
        # ---- WC: one short end rounded, the other square (cistern / wall side)
        ends = _ends(corners, major)
        if ends is not None and nv >= 6 and 0.28 <= wm <= 0.5 and 0.3 <= lm <= 0.8:
            (a0, a1), (b0, b1) = ends
            sq_a, sq_b = sharp[a0] and sharp[a1], sharp[b0] and sharp[b1]
            rd_a, rd_b = gaps[a0] > 0.04 and gaps[a1] > 0.04, gaps[b0] > 0.04 and gaps[b1] > 0.04
            if (sq_a and rd_b) or (sq_b and rd_a):
                back = (a0, a1) if sq_a else (b0, b1)
                poly = _rect_poly(corners)
                # cistern: a slim rectangle face sharing the square end
                bc = (corners[back[0]] + corners[back[1]]) / 2
                from shapely.geometry import Point
                cis = None
                for j in tree.query(Point(*bc).buffer(pt(0.03))):
                    if j == i or info[j] is None:
                        continue
                    cj = info[j]
                    if 0.08 <= cj[2] * mpt <= 0.3 and 0.25 <= cj[1] * mpt <= 0.6 and \
                            faces[j].area / (cj[1] * cj[2]) > 0.85 and not faces[j].intersection(f).area > 0.1 * f.area:
                        cis = j
                        break
                if cis is not None:
                    u = f.union(faces[cis])
                    rcu = _rect(u)
                    if rcu and rcu[1] * mpt <= 0.85:
                        poly = _rect_poly(rcu[0])
                        lm, wm = rcu[1] * mpt, rcu[2] * mpt
                        used.add(cis)
                if lm >= 0.42:
                    out.append(("wc", poly, {"size_m": [round(wm, 2), round(lm, 2)],
                                "evidence": "bowl rounded at one end" + (" + cistern" if cis is not None else "")},
                                0.7 + 0.1 * (cis is not None)))
                    used.update(inner)
                    continue
        # ---- basin: a rounded BOX (fill >= 0.86: a plain circle is a tag / callout), all corners rounded or holding a bowl
        bowl = [j for j in inner if info[j] and 0.06 <= info[j][1] * mpt <= 0.4 and info[j][2] / info[j][1] > 0.6 and
                faces[j].area / (info[j][1] * info[j][2]) > 0.6 and len(faces[j].exterior.coords) > 8]
        allround = bool((gaps > 0.006).all()) and (gaps < 0.12).all()
        if 0.18 <= wm <= 0.65 and 0.28 <= lm <= 0.75 and (allround or bowl) and nv >= 8 and lm / wm <= 2.2 and fill >= 0.86:
            out.append(("basin", _rect_poly(corners), {"size_m": [round(lm, 2), round(wm, 2)],
                        "evidence": "rounded box" + (" + bowl" if bowl else "")}, 0.65 + 0.1 * bool(bowl)))
            used.update(inner)
    return out


def _ends(corners, major):
    """Corner index pairs of the two short ends of an oriented rectangle."""
    for s in range(4):
        e = corners[(s + 1) % 4] - corners[s]
        n = np.hypot(*e)
        if n > 0 and abs(np.dot(e / n, major)) < 0.3:  # edge across the major axis = a short end
            a = (s, (s + 1) % 4)
            b = ((s + 2) % 4, (s + 3) % 4)
            return a, b
    return None


def _rect_poly(c):
    from shapely.geometry import Polygon
    return Polygon(c)


def _crossing(lines, f):
    """Indices of lines that run diagonally through face f (end points near the face boundary)."""
    import shapely
    from shapely.strtree import STRtree
    t = STRtree(lines)
    idx = t.query(f, predicate="within")
    keep = []
    rc = _rect(f)
    if rc is None:
        return np.zeros(0, int)
    major = rc[3]
    for j in idx:
        c = np.asarray(lines[j].coords)
        e = c[-1] - c[0]
        n = np.hypot(*e)
        if n < 0.5 * rc[2]:
            continue
        cos = abs(np.dot(e / n, major))
        if 0.35 < cos < 0.94:
            keep.append(j)
    return np.asarray(keep, int)


def _shower_heads(faces, sg, mpt, pt, wall_u, room):
    """Wall-mounted shower heads in a shower room without a tray: a small round face (0.06-0.2 m) within 0.6 m of
    a wall, fed by a zig-zag hose (>= 4 short segments alternating direction) -> 0.9 x 0.9 m zone on the wall."""
    from shapely.geometry import Point, Polygon, box
    if wall_u is None:
        return []
    out = []
    S = sg
    mids = (S[:, :2] + S[:, 2:]) / 2
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * mpt
    ang = np.arctan2(S[:, 3] - S[:, 1], S[:, 2] - S[:, 0])
    for f in faces:
        rc = _rect(f)
        if rc is None:
            continue
        d = rc[1] * mpt
        if not (0.04 <= d <= 0.2) or rc[2] / rc[1] < 0.75 or len(f.exterior.coords) < 7:
            continue
        if f.area / (rc[1] * rc[2]) < 0.65:
            continue
        c = np.array(f.centroid.coords[0])
        if not room.buffer(pt(0.3)).contains(Point(*c)):
            continue
        dw = wall_u.distance(Point(*c)) * mpt
        if dw > 0.7:
            continue
        near = (np.hypot(*(mids - c).T) * mpt < 0.45) & (L < 0.12) & (L > 0.01)
        if near.sum() < 4:
            continue
        a = np.mod(ang[near], math.pi)
        if a.max() - a.min() < 0.6:  # zig-zag: short strokes in at least two directions
            continue
        # floor zone 0.9 x 0.9 m against the nearest wall face, centred on the head
        from shapely.ops import nearest_points
        p_w = np.array(nearest_points(wall_u, Point(*c))[0].coords[0])
        n = c - p_w
        nn = np.hypot(*n)
        if nn <= 0:
            continue
        n = n / nn
        t = np.array([-n[1], n[0]])
        h = pt(0.45)
        q = [p_w + t * h, p_w - t * h, p_w - t * h + n * 2 * h, p_w + t * h + n * 2 * h]
        g = Polygon(q)
        if g.intersection(room.buffer(pt(0.1))).area < 0.6 * g.area:
            continue
        out.append(("shower", g, {"size_m": [0.9, 0.9], "evidence": "wall shower head + hose, no tray"}, 0.6))
    return out
