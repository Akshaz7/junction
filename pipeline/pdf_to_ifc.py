"""Vector-PDF plan map -> IFC4 file, so PDF floor plans go down the IFC path (pipeline.ifc_scene + IFC questions).

    build(planmap, out_path, *, storey_name, storey_elevation=0.0, wall_height=2.7) -> Path
    build_many([(planmap, storey_name, storey_elevation), ...], out_path) -> Path      (one storey per plan page)
    link_planmap(planmap_path, doc_id=None)  rewrites the plan map's item_ids to the IFC GlobalIds (old id kept in
                                             props.pdf_item_id) so IFC-mode answers can draw 2D boxes on the PDF page.

Input: a plan map from pipeline.pdf_planmap.process (items in page px, scale.m_per_px). Output (ifcopenshell.api, LGPL):
IfcProject (metres) > IfcSite > IfcBuilding > IfcBuildingStorey; one IfcWall per wall item (IfcExtrudedAreaSolid of
the exact wall polygon); per door/window an IfcOpeningElement voiding its host wall (IfcRelVoidsElement) and an
IfcDoor/IfcWindow filling it (IfcRelFillsElement; door 0-2.1 m, window sill 0.9 m head 2.1 m), so walls get real
openings with sills and lintels; door/window gaps the PDF leaves open are filled into the host wall first. One
IfcSpace per room (Name = number, LongName = label, Qto_SpaceBaseQuantities.NetFloorArea = printed area if present
else measured), one IfcSlab under the building footprint, Pset_*Common.IsExternal from the footprint outline, and a
Hologram_Provenance pset (source pdf_vector, item_id, m_per_pt, scale method) on every element.

Plan coordinates: x_m = x_px * m_per_px, y_m = -y_px * m_per_px (page top-left origin, y flipped to a right-handed plan),
so after ifc_scene's Z-up -> Y-up turn glTF X/Z follow the page's px x/y like the extruded scenes do.
GlobalIds are deterministic: uuid5(doc_id, page, item_id), so the same plan map always gives the same ids.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.style
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.guid
import ifcopenshell.util.element
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

DOOR_HEAD_M = 2.1
WINDOW_SILL_M = 0.9
WINDOW_HEAD_M = 2.1
SLAB_THICK_M = 0.2
PANEL_M = {"door": 0.05, "window": 0.03}           # door leaf / glass pane thickness
# Qto_SpaceBaseQuantities.NetFloorArea: "measured" (the polygon, like a native export computes it) or "printed"
# (the sheet's area wins; tests/test_pdf_to_ifc.py still expects this). The other value is always in Hologram_RoomArea.
NET_AREA_FROM = os.environ.get("PDF_IFC_NET_AREA", "measured")
# a room with no printed number gets a storey-scoped running number as its Name (native exports number every space;
# ifc_native_score spaces_named). Off by default only while tests/test_pdf_to_ifc.py expects Name '' (NEEDS r5-objects).
AUTO_NUMBER_SPACES = os.environ.get("PDF_IFC_SPACE_NUMBERS", "1") == "1"
PARTITION_MAX_MM = 120                             # thickness-class wall types up to this are named 'Partition'
HOST_SEARCH_M = 0.35                               # an opening's host wall is within this distance
FOOTPRINT_CLOSE_M = 0.6                            # closes door/window gaps when tracing the building outline
COLOURS = {  # (rgb, transparency) roughly what authoring tools export
    "wall": ((0.80, 0.80, 0.80), 0.0), "slab": ((0.62, 0.62, 0.62), 0.0), "door": ((0.62, 0.42, 0.24), 0.0),
    "window": ((0.55, 0.75, 0.95), 0.55), "space": ((0.85, 0.80, 0.65), 0.85),
    "glass": ((0.62, 0.80, 0.90), 0.6), "frame": ((0.90, 0.90, 0.88), 0.0), "pane": ((0.62, 0.80, 0.90), 0.6),
}
LINING_W, LINING_D = 0.05, 0.10                    # door lining (jamb/head) thickness along the wall, depth across
LEAF_T = 0.045                                     # door leaf thickness
WIN_FRAME_W, WIN_FRAME_D, PANE_T = 0.05, 0.08, 0.024
DOOR_OPS = {"SINGLE_SWING_LEFT", "SINGLE_SWING_RIGHT", "DOUBLE_DOOR_SINGLE_SWING", "DOUBLE_SWING_LEFT",
            "DOUBLE_SWING_RIGHT", "DOUBLE_DOOR_DOUBLE_SWING", "SLIDING_TO_LEFT", "SLIDING_TO_RIGHT",
            "DOUBLE_DOOR_SLIDING", "FOLDING_TO_LEFT", "FOLDING_TO_RIGHT", "DOUBLE_DOOR_FOLDING", "REVOLVING",
            "ROLLINGUP", "SWING_FIXED_LEFT", "SWING_FIXED_RIGHT"}
DOOR_OPERATION = {("left", 1): "SINGLE_SWING_LEFT", ("right", 1): "SINGLE_SWING_RIGHT", (None, 1): "SINGLE_SWING_LEFT"}
NS = uuid.UUID("6f1c5f0e-3d0a-4c8e-9a51-7d1b1b0c2a10")
# property types the Pset_*Common templates give (others: from the Python type)
_PTYPES = {"IsExternal": "IfcBoolean", "LoadBearing": "IfcBoolean", "Reference": "IfcIdentifier",
           "FireRating": "IfcLabel", "AcousticRating": "IfcLabel", "Status": "IfcLabel"}


def guid_for(doc_id: str, item_id: str, page: int = 1) -> str:
    """Stable IFC GlobalId (22 chars) for a plan-map item."""
    return ifcopenshell.guid.compress(uuid.uuid5(NS, f"{doc_id}:p{page}:{item_id}").hex)


# ---------------------------------------------------------------- geometry helpers (plan metres, y up)

def _poly_m(pts_px, mpp: float):
    if not pts_px or len(pts_px) < 3:
        return None
    p = Polygon([(x * mpp, -y * mpp) for x, y in pts_px]).buffer(0)
    if p.is_empty or p.area <= 1e-6:
        return None
    if isinstance(p, MultiPolygon):
        p = max(p.geoms, key=lambda g: g.area)
    return p


def _wall_poly(it: dict, mpp: float, m_per_pt: float | None):
    p = _poly_m(it.get("polygon_px"), mpp)
    if p is not None:
        return p
    cl = it.get("centerline")  # [[x,y],...] px (pdf_vector may add it with thickness_pt)
    t_pt = it.get("thickness_pt") or (it.get("props") or {}).get("thickness_pt")
    if cl and len(cl) >= 2 and t_pt and m_per_pt:
        ln = LineString([(x * mpp, -y * mpp) for x, y in cl])
        return ln.buffer(t_pt * m_per_pt / 2, cap_style="flat", join_style="mitre")
    return None


def _axis_m(pr: dict, mpp: float):
    cl = pr.get("centerline_px")
    if not cl or len(cl) < 2:
        return None
    ln = LineString([(x * mpp, -y * mpp) for x, y in cl])
    return ln if ln.length > 0.05 else None


def _wall_ev(it: dict) -> dict:
    """pdf_vector's evidence on a wall item: {source measured|derived|none, paths, n_paths, ...} ({} when absent)."""
    ev = (it.get("props") or {}).get("evidence")
    return ev if isinstance(ev, dict) else {}


def _ev_summary(its: list) -> tuple[str, str]:
    """(Source, 'paths ...' detail) over wall items: measured only if every piece is measured; derived when a piece
    is derived; items without recorded evidence count as measured by pdf_vector with no path ids."""
    srcs, paths, n = [], [], 0
    for it in its:
        ev = _wall_ev(it)
        srcs.append(str(ev.get("source") or "measured"))
        for q in ev.get("paths") or []:
            if q not in paths:
                paths.append(q)
        n += int(ev.get("n_paths") or len(ev.get("paths") or []))
    src = "measured" if all(x == "measured" for x in srcs) else "derived"
    det = (f"paths {','.join(str(q) for q in paths[:40])}" + (f" (+{n - 40} more)" if n > 40 else "")) if paths \
        else "no path ids recorded"
    return src, det


def _storey_title(name: str) -> str:
    s = " ".join(name.split()).title()
    return s.replace("1St", "1st").replace("2Nd", "2nd").replace("3Rd", "3rd").replace("Th ", "th ")


def _parts(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon) and p.area > 1e-6]


def _rect_frame(poly: Polygon, width_hint: float | None):
    """Opening rectangle -> (centre, unit axis along the wall, width, depth)."""
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l1, l2 = (e1[0] ** 2 + e1[1] ** 2) ** 0.5, (e2[0] ** 2 + e2[1] ** 2) ** 0.5
    if width_hint and l1 > 1e-6 and l2 > 1e-6:
        along_first = abs(l1 - width_hint) <= abs(l2 - width_hint)
    else:
        along_first = l1 >= l2
    (ax, w), d = ((e1, l1), l2) if along_first else ((e2, l2), l1)
    u = (ax[0] / max(w, 1e-9), ax[1] / max(w, 1e-9))
    ctr = r.centroid
    return (ctr.x, ctr.y), u, w, d


def _rect(c, u, w, d) -> Polygon:
    n = (-u[1], u[0])
    hw, hd = w / 2, d / 2
    return Polygon([(c[0] + s * hw * u[0] + t * hd * n[0], c[1] + s * hw * u[1] + t * hd * n[1])
                    for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


# ---------------------------------------------------------------- wall graph (plan metres, y up)
# Straight wall pieces from the vector reader -> wall runs like an authoring tool exports them: collinear pieces of
# one thickness merged across door/window gaps and small breaks, ends snapped to the other axis at L/T junctions
# (mitre at L corners, butt into the face at T), slivers dropped. Pieces that are not straight stay as they are.

WG_ANGLE_DEG = 3.0          # pieces within this angle are parallel
WG_GAP_M = 0.3              # collinear pieces closer than this are one run
WG_OPEN_GAP_M = 3.5         # longest gap an opening may bridge
WG_REACH_M = 0.5            # an end extends at most this far (beyond the other wall's half thickness) to a junction
WG_FILLER_JOIN_M = 1.0     # openings with no drawn wall this close along one line share one filler wall
# DATA RULE: no wall where nothing is drawn. An opening with no drawn wall on its line is left out of the IFC and
# listed (storey pset Hologram_Unhosted) for the walls/openings readers to fix; PDF_IFC_FILLERS=1 brings back the
# old filler walls (Hologram_Evidence Source 'default').
WG_FILLERS = os.environ.get("PDF_IFC_FILLERS", "0") == "1"
WG_EXTEND_M = 0.3          # a drawn run reaches across an opening only when it ends this close to it (drawing noise)
WG_SLIVER_M = 0.12          # runs shorter than this (and not hosting an opening) are dropped


class _Run:
    __slots__ = ("u", "n", "off", "t", "s0", "s1", "members", "h", "style", "cap0", "cap1", "j0", "j1", "opens",
                 "filler", "poly", "rep")

    def __init__(self, u, off, t, s0, s1, members, h, style, filler=False):
        self.u, self.n = u, (-u[1], u[0])
        self.off, self.t, self.s0, self.s1 = off, t, s0, s1
        self.members, self.h, self.style, self.filler = members, h, style, filler
        self.cap0 = self.cap1 = None   # end cap line (point, direction); None = square end
        self.j0 = self.j1 = None       # (other run index, "ATSTART"|"ATEND"|"ATPATH")
        self.opens = []
        self.poly = None
        self.rep = None

    def pt(self, s, d=0.0):
        return (self.u[0] * s + self.n[0] * (self.off + d), self.u[1] * s + self.n[1] * (self.off + d))

    def proj(self, p):
        return p[0] * self.u[0] + p[1] * self.u[1], p[0] * self.n[0] + p[1] * self.n[1]

    @property
    def length(self):
        return self.s1 - self.s0


def _seg_m(it: dict, mpp: float):
    """Straight wall piece -> (a, b, thickness_m) in plan metres, or None (curved / no axis / glass)."""
    pr = it.get("props") or {}
    cl = pr.get("centerline_px") or it.get("centerline")
    t = pr.get("thickness_m")
    if not cl or len(cl) < 2 or not t or pr.get("glass"):
        return None
    pts = [(x * mpp, -y * mpp) for x, y in cl]
    a, b = pts[0], pts[-1]
    L = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    if L < 1e-3:
        return None
    if len(pts) > 2:
        ab = LineString([a, b])
        if max(ab.distance(Point(p)) for p in pts) > 0.03:
            return None
    return a, b, float(t)


def _line_x(p, d, q, e):
    """Intersection of lines p + s d and q + r e -> (s, r) or None when parallel."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    wx, wy = q[0] - p[0], q[1] - p[1]
    return (wx * e[1] - wy * e[0]) / den, (wx * d[1] - wy * d[0]) / den


def _runs_from_pieces(pieces, opens_m):
    """pieces: [(idx, a, b, t, h, style)], opens_m: [(centre, half width)] -> [_Run] (merged collinear pieces)."""
    import math
    rec = []
    for idx, a, b, t, h, style in pieces:
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
        rec.append((ang, idx, a, b, t, h, style))
    rec.sort()
    # angle groups (0 and 180 deg wrap into one group)
    groups, cur = [], []
    for r in rec:
        if cur and r[0] - cur[-1][0] > WG_ANGLE_DEG / 2:
            groups.append(cur)
            cur = []
        cur.append(r)
    if cur:
        groups.append(cur)
    if len(groups) > 1 and groups[0][0][0] + 180.0 - groups[-1][-1][0] <= WG_ANGLE_DEG / 2:
        groups[0] = [(x[0] + 180.0 if x[0] < 90 else x[0],) + x[1:] for x in groups[0]] + groups.pop()
    runs = []
    for g in groups:
        wsum = sum(((x[3][0] - x[2][0]) ** 2 + (x[3][1] - x[2][1]) ** 2) ** 0.5 for x in g) or 1.0
        ang = sum(x[0] * ((x[3][0] - x[2][0]) ** 2 + (x[3][1] - x[2][1]) ** 2) ** 0.5 for x in g) / wsum
        u = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        n = (-u[1], u[0])
        segs = []
        for x in g:
            _, idx, a, b, t, h, style = x
            sa, sb = a[0] * u[0] + a[1] * u[1], b[0] * u[0] + b[1] * u[1]
            off = ((a[0] + b[0]) * n[0] + (a[1] + b[1]) * n[1]) / 2
            segs.append([min(sa, sb), max(sa, sb), off, t, h, style, [idx]])
        segs = _bands(segs)
        # lines: same offset (within a fraction of the thickness), same thickness class
        segs.sort(key=lambda s: s[2])
        lines = []   # [offset, [segs]]
        for s in segs:
            for ln in lines:
                r = ln[1][0]
                if abs(ln[0] - s[2]) <= max(0.04, 0.35 * min(r[3], s[3])) and \
                        abs(r[3] - s[3]) <= max(0.04, 0.25 * max(r[3], s[3])):
                    ln[1].append(s)
                    break
            else:
                lines.append([s[2], [s]])
        for off_line, ss in lines:
            ss.sort(key=lambda s: s[0])
            merged = [list(ss[0])]
            for s in ss[1:]:
                m = merged[-1]
                gap = s[0] - m[1]
                ok = gap <= WG_GAP_M
                if not ok and gap <= WG_OPEN_GAP_M:
                    t = max(m[3], s[3])
                    for c, hw in opens_m:
                        cs, cn = c[0] * u[0] + c[1] * u[1], c[0] * n[0] + c[1] * n[1]
                        if abs(cn - off_line) <= t / 2 + 0.25 and m[1] - 0.2 <= cs <= s[0] + 0.2 and \
                                gap <= 2 * hw + 0.6:
                            ok = True
                            break
                if ok:
                    L1, L2 = m[1] - m[0], s[1] - s[0]
                    m[2] = (m[2] * L1 + s[2] * L2) / max(L1 + L2, 1e-9)
                    m[3] = (m[3] * L1 + s[3] * L2) / max(L1 + L2, 1e-9)
                    m[1] = max(m[1], s[1])
                    m[6] = m[6] + s[6]
                    m[4] = None if m[4] is None or s[4] is None else max(m[4], s[4])
                    m[5] = m[5] if m[5] == s[5] else None
                else:
                    merged.append(list(s))
            for m in merged:
                runs.append(_Run(u, m[2], m[3], m[0], m[1], m[6], m[4], m[5]))
    return runs


WG_BAND_MAX_M = 0.7         # parallel strips side by side (wall layers drawn as separate lines) up to this width


def _bands(segs):
    """Parallel strips that touch side by side and overlap along the axis (a layered wall drawn line by line:
    structure + insulation + cladding) -> one composite strip spanning their outer faces."""
    n = len(segs)
    if n < 2:
        return segs
    parent = list(range(n))
    lo = [s[2] - s[3] / 2 for s in segs]
    hi = [s[2] + s[3] / 2 for s in segs]
    a0 = [s[0] for s in segs]
    a1 = [s[1] for s in segs]

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    order = sorted(range(n), key=lambda i: lo[i])
    tmax = max(s[3] for s in segs)
    for x, i in enumerate(order):
        for j in order[x + 1:]:
            if lo[j] > hi[i] + 0.04 + tmax:
                break
            if lo[j] > hi[i] + 0.04 or lo[i] > hi[j] + 0.04:
                continue
            # along the axis: overlap of at least half the shorter strip
            ov = min(a1[i], a1[j]) - max(a0[i], a0[j])
            if ov < 0.5 * min(a1[i] - a0[i], a1[j] - a0[j]):
                continue
            ri, rj = find(i), find(j)
            if ri == rj:
                continue
            l2, h2 = min(lo[ri], lo[rj]), max(hi[ri], hi[rj])
            if h2 - l2 > WG_BAND_MAX_M:
                continue
            parent[rj] = ri
            lo[ri], hi[ri] = l2, h2
            a0[ri], a1[ri] = min(a0[ri], a0[rj]), max(a1[ri], a1[rj])
    out = {}
    for i in range(n):
        r = find(i)
        out.setdefault(r, []).append(segs[i])
    res = []
    for r, ms in out.items():
        if len(ms) == 1:
            res.append(ms[0])
            continue
        h = None if any(m[4] is None for m in ms) else max(m[4] for m in ms)
        st = ms[0][5] if all(m[5] == ms[0][5] for m in ms) else None
        res.append([a0[r], a1[r], (lo[r] + hi[r]) / 2, hi[r] - lo[r], h, st, [k for m in ms for k in m[6]]])
    return res


def _join_runs(runs):
    """Snap run ends to the other axes at L/T junctions (end caps: mitre at L, the other wall's face at T)."""
    from shapely.strtree import STRtree
    ends = [(i, e) for i in range(len(runs)) for e in (0, 1)]
    best = {}
    if not runs:
        return []
    tmax = max(r.t for r in runs)
    tree = STRtree([LineString([r.pt(r.s0), r.pt(r.s1)]) for r in runs])
    for i, e in ends:
        a = runs[i]
        s_end = a.s0 if e == 0 else a.s1
        out = -1.0 if e == 0 else 1.0
        p_end = a.pt(s_end)
        cand = None
        near = tree.query(Point(p_end).buffer(tmax / 2 + a.t / 2 + WG_REACH_M + 0.2))
        for j in near:
            j = int(j)
            b = runs[j]
            if j == i:
                continue
            cosang = abs(a.u[0] * b.u[0] + a.u[1] * b.u[1])
            if cosang > 0.87:   # < 30 deg apart: not a junction
                continue
            x = _line_x(a.pt(0.0), a.u, b.pt(0.0), b.u)
            if x is None:
                continue
            sx, rx = x
            # how far the end must move (positive = extend) to reach b's axis
            ext = (sx - s_end) * out
            if ext > b.t / 2 + WG_REACH_M or ext < -(b.t / 2 + 0.1):
                continue
            if not (b.s0 - a.t / 2 - WG_REACH_M <= rx <= b.s1 + a.t / 2 + WG_REACH_M):
                continue
            d = abs(ext)
            if cand is None or d < cand[0]:
                cand = (d, j, sx, rx)
        if cand:
            best[(i, e)] = cand
    done = set()
    conns = []
    for (i, e), (d, j, sx, rx) in sorted(best.items(), key=lambda kv: kv[1][0]):
        if (i, e) in done:
            continue
        a = runs[i]
        b = runs[j]
        # L: b's end is also near the junction and points at a
        be = None
        for e2 in (0, 1):
            if (j, e2) in done or (j, e2) not in best or best[(j, e2)][1] != i:
                continue
            s_b = b.s0 if e2 == 0 else b.s1
            if abs(rx - s_b) <= a.t / 2 + WG_REACH_M:
                be = e2
        if be is not None:
            # mitre: both ends to the axis crossing; cap through the inner and outer face crossings
            sb = best[(j, be)][2]
            pa = [a.pt(0.0, -a.t / 2), a.pt(0.0, a.t / 2)]
            pb = [b.pt(0.0, -b.t / 2), b.pt(0.0, b.t / 2)]
            xs = []
            for qa in pa:
                for qb in pb:
                    r = _line_x(qa, a.u, qb, b.u)
                    if r:
                        xs.append((qa[0] + a.u[0] * r[0], qa[1] + a.u[1] * r[0]))
            # the cap is the diagonal of the face-crossing parallelogram that passes through the axis crossing
            c = a.pt(sx)
            cap = None
            if len(xs) == 4:
                for p, q in ((xs[0], xs[3]), (xs[1], xs[2])):
                    dx, dy = q[0] - p[0], q[1] - p[1]
                    if (dx * dx + dy * dy) ** 0.5 < 1e-6:
                        continue
                    # both diagonals pass through c; the mitre one separates the two walls
                    side_a = (a.pt(sx - (1 if e == 1 else -1) * (a.t + 0.5))[0] - p[0]) * dy - \
                             (a.pt(sx - (1 if e == 1 else -1) * (a.t + 0.5))[1] - p[1]) * dx
                    sbo = sb - (1 if be == 1 else -1) * (b.t + 0.5)
                    side_b = (b.pt(sbo)[0] - p[0]) * dy - (b.pt(sbo)[1] - p[1]) * dx
                    if side_a * side_b < 0:
                        cap = (c, (dx, dy))
                        break
            for r, ee, s in ((a, e, sx), (b, be, sb)):
                if ee == 0:
                    r.s0, r.cap0 = min(s, r.s1 - 0.01), cap
                else:
                    r.s1, r.cap1 = max(s, r.s0 + 0.01), cap
            a_type = "ATSTART" if e == 0 else "ATEND"
            b_type = "ATSTART" if be == 0 else "ATEND"
            if e == 0:
                a.j0 = (j, b_type)
            else:
                a.j1 = (j, b_type)
            if be == 0:
                b.j0 = (i, a_type)
            else:
                b.j1 = (i, a_type)
            conns.append((i, a_type, j, b_type))
            done.add((i, e))
            done.add((j, be))
        else:
            # T: butt the end into b's near face (b must really be there)
            if not (b.s0 - 0.05 <= rx <= b.s1 + 0.05):
                continue
            p_end = a.pt(a.s0 if e == 0 else a.s1)
            side = 1.0 if (p_end[0] * b.n[0] + p_end[1] * b.n[1]) - b.off >= 0 else -1.0
            face_p = b.pt(0.0, side * b.t / 2)
            r = _line_x(a.pt(0.0), a.u, face_p, b.u)
            if r is None:
                continue
            s = r[0]
            if e == 0:
                if s >= a.s1 - 0.05:
                    continue
                a.s0, a.cap0, a.j0 = s, (face_p, b.u), (j, "ATPATH")
            else:
                if s <= a.s0 + 0.05:
                    continue
                a.s1, a.cap1, a.j1 = s, (face_p, b.u), (j, "ATPATH")
            conns.append((i, "ATSTART" if e == 0 else "ATEND", j, "ATPATH"))
            done.add((i, e))
    return conns


def _run_poly(r: _Run):
    """Wall run footprint (plan metres) with its end caps."""
    def corner(s_end, cap, d):
        p = r.pt(0.0, d)
        if cap is not None:
            x = _line_x(p, r.u, cap[0], cap[1])
            if x is not None and abs(x[0] - s_end) <= r.t * 3 + 0.5:
                return r.pt(x[0], d)
        return r.pt(s_end, d)
    h = r.t / 2
    pts = [corner(r.s0, r.cap0, -h), corner(r.s1, r.cap1, -h), corner(r.s1, r.cap1, h), corner(r.s0, r.cap0, h)]
    p = Polygon(pts)
    if not p.is_valid or p.area < 1e-6:
        p = Polygon([r.pt(r.s0, -h), r.pt(r.s1, -h), r.pt(r.s1, h), r.pt(r.s0, h)])
    return p


def _wall_graph(walls, opens, oframe, owidth, mpp, wall_height):
    """-> (runs, connections, {opening index: run index}, free piece indices). Every opening gets a host run:
    the run it sits in, else a collinear run within 1 m extended across it, else a new run across the gap with the
    jamb walls' thickness (the opening's depth when there are none)."""
    pieces = []
    for i, (it, _p) in enumerate(walls):
        sg = _seg_m(it, mpp)
        if sg:
            pr = it.get("props") or {}
            pieces.append((i, sg[0], sg[1], sg[2], pr.get("height_m"), pr.get("style")))
    runs = _runs_from_pieces(pieces, [(fr[0], wd / 2) for fr, wd in zip(oframe, owidth)])
    in_run = {m for r in runs for m in r.members}
    free = [i for i in range(len(walls)) if i not in in_run]

    def aligned(r, fr):
        c, u, wid, dep = fr
        if wid > 1.3 * dep and abs(u[0] * r.u[0] + u[1] * r.u[1]) < 0.9:
            return False
        return True
    host = {}
    for k, ((it, p), fr, wd) in enumerate(zip(opens, oframe, owidth)):
        c = fr[0]
        best = None
        for ri, r in enumerate(runs):
            if not aligned(r, fr):
                continue
            cs, cn = r.proj(c)
            perp = abs(cn - r.off)
            if perp <= r.t / 2 + 0.2 and r.s0 - 0.05 <= cs <= r.s1 + 0.05:
                if best is None or perp < best[0]:
                    best = (perp, ri)
        if best is None:  # extend a collinear run across the opening (a filler too: a band of openings in one
            for ri, r in enumerate(runs):  # undrawn stretch of facade is one wall, not one wall per window)
                if not aligned(r, fr):
                    continue
                cs, cn = r.proj(c)
                perp = abs(cn - r.off)
                lo, hi = cs - wd / 2, cs + wd / 2
                gap = max(r.s0 - hi, lo - r.s1, 0.0)
                if perp <= r.t / 2 + 0.2 and gap <= (WG_FILLER_JOIN_M if r.filler else WG_EXTEND_M) and \
                        (best is None or gap < best[0]):
                    best = (gap, ri)
            if best is not None:
                r = runs[best[1]]
                cs, _ = r.proj(c)
                r.s0, r.s1 = min(r.s0, cs - wd / 2), max(r.s1, cs + wd / 2)
        if best is None:
            if any(walls[i][1].distance(p) <= 0.05 and walls[i][1].intersection(p.buffer(0.1)).area > 0.3 * p.area
                   for i in free):
                continue  # sits in a free (curved / glass) piece: hosted there
            if not WG_FILLERS:
                continue  # no drawn wall on its line: unhosted (left out of the IFC, listed on the storey)
            _, u, _, dep = fr
            if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
                u = (-u[0], -u[1])
            t = None
            for r in runs:  # jamb walls: parallel runs on the opening's line within 1.5 m
                if abs(u[0] * r.u[0] + u[1] * r.u[1]) < 0.97:
                    continue
                cs, cn = r.proj(c)
                if abs(cn - r.off) <= r.t / 2 + 0.2 and max(r.s0 - cs, cs - r.s1, 0.0) <= 1.5 + wd / 2:
                    t = r.t if t is None else max(t, r.t)
            t = t or max(0.08, min(float(dep), 0.5))
            n = (-u[1], u[0])
            cs, cn = c[0] * u[0] + c[1] * u[1], c[0] * n[0] + c[1] * n[1]
            nr = _Run(u, cn, t, cs - wd / 2, cs + wd / 2, [], wall_height, None, filler=True)
            nr.rep = {"item_id": it["item_id"] + "#wall", "conf": it.get("conf"), "props": {}}
            runs.append(nr)
            best = (0.0, len(runs) - 1)
        host[k] = best[1]
        runs[best[1]].opens.append(k)
    _snap_thickness(runs)
    conns = _join_runs(runs)
    for r in runs:
        r.poly = _run_poly(r)
        if r.rep is None:
            m = max(r.members, key=lambda i: walls[i][1].area)
            r.rep = walls[m][0]
    # slivers (short runs with no opening) and duplicates (a run mostly inside other walls, e.g. the same wall drawn
    # twice with another line style): drop, smallest first so the bigger copy stays; openings move to the keeper
    from shapely.strtree import STRtree
    polys = [r.poly for r in runs]
    tree = STRtree(polys)
    drop = set()
    for ri in sorted(range(len(runs)), key=lambda i: polys[i].area):
        r = runs[ri]
        if r.length < WG_SLIVER_M and not r.opens:
            drop.add(ri)
            continue
        near = [j for j in tree.query(r.poly) if j != ri and j not in drop and polys[j].area >= polys[ri].area]
        if not near:
            continue
        cov = unary_union([polys[j] for j in near]).intersection(r.poly).area
        if cov > WG_DUP_FRAC * r.poly.area and not r.filler:
            # an end lies along a parallel bigger run (the same wall drawn twice, or a band overlapping a longer
            # one): trim that end off when what is left still carries its openings, else drop the run
            try:
                tr = _trim_overlap(r, [runs[j] for j in near], oframe)
            except Exception:  # noqa: BLE001
                tr = None
            if tr is not None:
                r.s0, r.s1 = tr
                r.poly = polys[ri] = _run_poly(r)
                cov = unary_union([polys[j] for j in near]).intersection(r.poly).area
        if cov > WG_DUP_FRAC * r.poly.area:
            if r.opens:  # hand the openings to the overlapping parallel run that covers them
                to = {}
                for k in r.opens:
                    c = oframe[k][0]
                    cand = [j for j in near if abs(runs[j].u[0] * r.u[0] + runs[j].u[1] * r.u[1]) > 0.97 and
                            runs[j].s0 - 0.05 <= runs[j].proj(c)[0] <= runs[j].s1 + 0.05 and
                            abs(runs[j].proj(c)[1] - runs[j].off) <= runs[j].t / 2 + 0.2]
                    if not cand:
                        break
                    to[k] = cand[0]
                else:
                    for k, j in to.items():
                        host[k] = j
                        runs[j].opens.append(k)
                    drop.add(ri)
                continue
            drop.add(ri)
    if drop:
        keep = [i for i in range(len(runs)) if i not in drop]
        remap = {o: nidx for nidx, o in enumerate(keep)}
        runs = [runs[i] for i in keep]
        conns = [(remap[a], ta, remap[b], tb) for a, ta, b, tb in conns if a in remap and b in remap]
        host = {k: remap[v] for k, v in host.items()}
    n_touch = 0
    try:
        n_touch = _touch_conns(runs, conns)
    except Exception:  # noqa: BLE001  keep the L/T connections only
        pass
    _wall_graph.last = {"pieces": len(pieces), "runs": len(runs), "slivers_dropped": len(drop),
                        "connections": len(conns), "touch_connections": n_touch,
                        "filler_runs": sum(1 for r in runs if r.filler)}
    return runs, conns, host, free


_wall_graph.last = {}
def _touch_conns(runs, conns) -> int:
    """Run ends the L/T pass left unjoined that butt onto another run (collinear walls of two thicknesses end to
    end, a wall stopping on a face the T search did not reach): IfcRelConnectsPathElements like an authoring tool
    writes them (ATEND-ATSTART end to end, ATPATH onto a face). Geometry is not changed. -> connections added."""
    from shapely.strtree import STRtree
    if len(runs) < 2:
        return 0
    have = {frozenset((a, b)) for a, _, b, _ in conns}
    used = {(a, ta) for a, ta, _, _ in conns} | {(b, tb) for _, _, b, tb in conns if tb != "ATPATH"}
    tree = STRtree([r.poly for r in runs])
    n = 0
    for i, a in enumerate(runs):
        for e, s_end, tag in ((0, a.s0, "ATSTART"), (1, a.s1, "ATEND")):
            if (a.j0 if e == 0 else a.j1) is not None or (i, tag) in used:
                continue
            pe = Point(a.pt(s_end))
            best = None
            for j in tree.query(pe.buffer(a.t / 2 + 0.06)):
                j = int(j)
                if j == i or frozenset((i, j)) in have:
                    continue
                d = runs[j].poly.distance(pe)
                if d <= a.t / 2 + 0.05 and (best is None or d < best[0]):
                    best = (d, j)
            if best is None:
                continue
            j = best[1]
            b = runs[j]
            sb, _ = b.proj(pe.coords[0])
            near_end = None
            for e2, s2, t2 in ((0, b.s0, "ATSTART"), (1, b.s1, "ATEND")):
                if abs(sb - s2) <= max(a.t, b.t) / 2 + 0.1 and (j, t2) not in used:
                    near_end = t2
            tb = near_end or "ATPATH"
            conns.append((i, tag, j, tb))
            have.add(frozenset((i, j)))
            used.add((i, tag))
            if tb != "ATPATH":
                used.add((j, tb))
            if e == 0:
                a.j0 = (j, tb)
            else:
                a.j1 = (j, tb)
            n += 1
    return n


WG_DUP_FRAC = 0.5           # a run with more than this share of its footprint inside bigger runs is a duplicate


def _trim_overlap(r, others, oframe):
    """(s0, s1) of run r with the ends that run inside parallel, overlapping bigger runs cut off, or None (nothing to
    trim, an opening would be cut, or less than 0.3 m would be left)."""
    s0, s1 = r.s0, r.s1
    for b in others:
        if abs(b.u[0] * r.u[0] + b.u[1] * r.u[1]) < 0.97:
            continue
        if abs(b.proj(r.pt((r.s0 + r.s1) / 2))[1] - b.off) > (b.t + r.t) / 2 - 0.02:
            continue  # not overlapping across the thickness
        e = sorted(r.proj(b.pt(x))[0] for x in (b.s0, b.s1))
        if e[0] <= s0 + 0.05 and e[1] < s1:
            s0 = max(s0, e[1])
        elif e[1] >= s1 - 0.05 and e[0] > s0:
            s1 = min(s1, e[0])
    if (s0, s1) == (r.s0, r.s1) or s1 - s0 < 0.3:
        return None
    for k in r.opens:
        cs = r.proj(oframe[k][0])[0]
        if not (s0 - 0.05 <= cs <= s1 + 0.05):
            return None
    return s0, s1


def _free_in_runs(walls, free, runs, opens, oframe, owidth, run_host):
    """-> free piece indices left. Pieces more than half inside runs leave the free list (the run is the wall). A
    glass one is appended to opens as a glazed span of that run (props glass_in_run); _add_storey keeps it as a
    window only in an EXTERIOR run (facade glazing) and records it on an interior run as Hologram_Glazing (an
    interior glazed partition is not a window). Openings hosted by a dropped piece move to the run that holds them."""
    from shapely.strtree import STRtree
    rp = [r.poly for r in runs]
    tree = STRtree(rp)
    keep, gone = [], []
    for i in free:
        it, p = walls[i]
        near = [int(j) for j in tree.query(p)]
        if not near or p.area <= 1e-6:
            keep.append(i)
            continue
        if unary_union([rp[j] for j in near]).intersection(p).area <= WG_DUP_FRAC * p.area:
            keep.append(i)
            continue
        gone.append(i)
        if not (it.get("props") or {}).get("glass"):
            continue
        ri = max(near, key=lambda j: rp[j].intersection(p).area)
        r = runs[ri]
        ss = [r.proj(q)[0] for q in p.exterior.coords]
        s0, s1 = max(min(ss), r.s0), min(max(ss), r.s1)
        if s1 - s0 < 0.2:
            continue
        c = r.pt((s0 + s1) / 2)
        pr = {k: v for k, v in (it.get("props") or {}).items() if k not in ("glass", "thickness_m")}
        pr.update(kind="glass_partition", width_m=round(s1 - s0, 3), glass_in_run=True)
        opens.append(({**it, "kind": "window", "props": pr}, _rect(c, r.u, s1 - s0, r.t)))
        oframe.append((c, r.u, s1 - s0, r.t))
        owidth.append(s1 - s0)
        k = len(opens) - 1
        run_host[k] = ri
        r.opens.append(k)
    if gone:
        gp = [walls[i][1] for i in gone]
        for k, (it, p) in enumerate(opens):
            if k in run_host or not any(g.distance(p) <= HOST_SEARCH_M for g in gp):
                continue
            c = oframe[k][0]
            for ri, r in enumerate(runs):
                cs, cn = r.proj(c)
                if abs(cn - r.off) <= r.t / 2 + 0.2 and r.s0 - 0.05 <= cs <= r.s1 + 0.05:
                    run_host[k] = ri
                    r.opens.append(k)
                    break
    return keep


def _snap_thickness(runs, tol: float = 0.015):
    """Wall thicknesses -> a few types: length-weighted modes, every run within tol of a mode takes it."""
    todo = sorted(runs, key=lambda r: -r.length)
    modes = []
    for r in todo:
        for m in modes:
            if abs(m[0] - r.t) <= max(tol, 0.08 * m[0]):
                m[1].append(r)
                break
        else:
            modes.append([r.t, [r]])
    for m in modes:
        L = sum(r.length for r in m[1]) or 1.0
        t = round(sum(r.t * r.length for r in m[1]) / L, 2)
        t = t if t > 0 else m[0]
        for r in m[1]:
            r.t = t


def _door_operation(pr: dict) -> str:
    """Door props from pdf_openings -> IfcDoorTypeOperationEnum (props.operation wins: it carries the IFC handing)."""
    op = str(pr.get("operation") or "").upper()
    if op in DOOR_OPS:
        return op
    side = pr.get("hinge_side")   # IFC handing (viewed along +Y); swing_side is NOT the IFC hinge side
    two = bool(pr.get("double")) or int(pr.get("n_leaves") or 1) >= 2 or side == "both"
    if pr.get("sliding"):
        return "DOUBLE_DOOR_SLIDING" if two else ("SLIDING_TO_RIGHT" if side == "right" else "SLIDING_TO_LEFT")
    if pr.get("folding"):
        return "DOUBLE_DOOR_FOLDING" if two else ("FOLDING_TO_RIGHT" if side == "right" else "FOLDING_TO_LEFT")
    if pr.get("double_acting") or pr.get("double_swing"):
        return "DOUBLE_DOOR_DOUBLE_SWING" if two else ("DOUBLE_SWING_RIGHT" if side == "right" else "DOUBLE_SWING_LEFT")
    if two:
        return "DOUBLE_DOOR_SINGLE_SWING"
    if side in ("left", "right"):
        return f"SINGLE_SWING_{side.upper()}"
    return "NOTDEFINED"


def _door_parts(wid: float, thick: float, z1: float, op: str):
    """Door body in the door's own frame (X along the opening centred on 0, +Y = the side the leaf opens into):
    lining (two jambs + head) and the closed leaf/leaves. -> [(polygon, z0, h, style)]"""
    ld = max(0.03, min(LINING_D, thick))
    lw = min(LINING_W, wid / 6)
    parts = [(_rect((-wid / 2 + lw / 2, 0.0), (1.0, 0.0), lw, ld), 0.0, z1, "frame"),
             (_rect((wid / 2 - lw / 2, 0.0), (1.0, 0.0), lw, ld), 0.0, z1, "frame"),
             (_rect((0.0, 0.0), (1.0, 0.0), wid, ld), z1 - lw, lw, "frame")]
    clear = wid - 2 * lw
    lt = min(LEAF_T, ld * 0.8)
    hl = z1 - lw - 0.01
    if "SLIDING" in op:  # leaves in two tracks across the lining, overlapping 5 cm
        n = 2 if op.startswith("DOUBLE") else 1
        lwid = clear / n + (0.05 if n == 2 else 0.0)
        for i in range(n):
            x = 0.0 if n == 1 else (-clear / 4 - 0.025 if i == 0 else clear / 4 + 0.025)
            y = (ld / 2 - lt / 2) * (1 if i == 0 else -1) if n == 2 else 0.0
            parts.append((_rect((x, y), (1.0, 0.0), lwid, lt), 0.01, hl, "door"))
        return parts
    y = ld / 2 - lt / 2 if "DOUBLE_SWING" not in op and "DOUBLE_DOOR_DOUBLE" not in op else 0.0
    if op.startswith("DOUBLE_DOOR"):
        for sgn in (-1, 1):
            parts.append((_rect((sgn * (clear / 4 + 0.0025), y), (1.0, 0.0), clear / 2 - 0.005, lt), 0.01, hl, "door"))
    else:
        parts.append((_rect((0.0, y), (1.0, 0.0), clear - 0.006, lt), 0.01, hl, "door"))
    return parts


def _window_parts(wid: float, thick: float, z0: float, z1: float):
    """Window body in its own frame (X along the opening centred on 0, centred in the wall): frame + glass pane."""
    fd = max(0.03, min(WIN_FRAME_D, thick))
    fw = min(WIN_FRAME_W, wid / 6, (z1 - z0) / 6)
    h = z1 - z0
    return [(_rect((-wid / 2 + fw / 2, 0.0), (1.0, 0.0), fw, fd), z0, h, "frame"),
            (_rect((wid / 2 - fw / 2, 0.0), (1.0, 0.0), fw, fd), z0, h, "frame"),
            (_rect((0.0, 0.0), (1.0, 0.0), wid - 2 * fw, fd), z0, fw, "frame"),
            (_rect((0.0, 0.0), (1.0, 0.0), wid - 2 * fw, fd), z1 - fw, fw, "frame"),
            (_rect((0.0, 0.0), (1.0, 0.0), wid - 2 * fw, min(PANE_T, fd / 2)), z0 + fw, h - 2 * fw, "pane")]


def _opening_type_props(f, w, dt, kind: str, op: str, wid: float, thick: float) -> list:
    """IfcDoorLiningProperties + IfcDoorPanelProperties (or the window ones) for a door/window type."""
    gid = lambda tag: w.gid(f"{dt.GlobalId}:{tag}")  # noqa: E731
    if kind == "door":
        ld = max(0.03, min(LINING_D, thick))
        lin = f.create_entity("IfcDoorLiningProperties", GlobalId=gid("lining"), Name="Lining", LiningDepth=ld,
                              LiningThickness=LINING_W)
        po = "SLIDING" if "SLIDING" in op else "FOLDING" if "FOLDING" in op else "REVOLVING" if op == "REVOLVING" \
            else "DOUBLE_ACTING" if "DOUBLE_SWING" in op or "DOUBLE_DOOR_DOUBLE" in op else \
            "SWINGING" if op != "NOTDEFINED" else "NOTDEFINED"
        out = [lin]
        if op.startswith("DOUBLE_DOOR"):
            for pos in ("LEFT", "RIGHT"):
                out.append(f.create_entity("IfcDoorPanelProperties", GlobalId=gid("panel" + pos), Name="Panel",
                                           PanelDepth=LEAF_T, PanelOperation=po, PanelWidth=0.5, PanelPosition=pos))
        else:
            out.append(f.create_entity("IfcDoorPanelProperties", GlobalId=gid("panel"), Name="Panel",
                                       PanelDepth=LEAF_T, PanelOperation=po, PanelWidth=1.0,
                                       PanelPosition="LEFT" if op.endswith("LEFT") else
                                       "RIGHT" if op.endswith("RIGHT") else "MIDDLE"))
        return out
    fd = max(0.03, min(WIN_FRAME_D, thick))
    return [f.create_entity("IfcWindowLiningProperties", GlobalId=gid("lining"), Name="Lining", LiningDepth=fd,
                            LiningThickness=WIN_FRAME_W),
            f.create_entity("IfcWindowPanelProperties", GlobalId=gid("panel"), Name="Panel",
                            OperationType="FIXEDCASEMENT", PanelPosition="MIDDLE", FrameDepth=fd,
                            FrameThickness=WIN_FRAME_W)]


def _window_partitioning(pr: dict) -> str:
    n = int(pr.get("n_panels") or pr.get("n_leaves") or 1)
    if n >= 3:
        return "TRIPLE_PANEL_VERTICAL"
    if n == 2:
        return "DOUBLE_PANEL_VERTICAL"
    return "SINGLE_PANEL"


# ---------------------------------------------------------------- IFC helpers

class _W:
    def __init__(self, f, body, doc_id, page, prov):
        self.f, self.body, self.doc_id, self.page, self.prov = f, body, doc_id, page, prov
        self.styles = {}
        self.sets = {}
        self.axis_ctx = None

    def gid(self, item_id):
        return guid_for(self.doc_id, item_id, self.page)

    def entity(self, cls, item_id, name=None, predefined=None):
        e = ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=name, predefined_type=predefined)
        e.GlobalId = self.gid(item_id)
        return e

    def placement(self, rel=None, z=0.0):
        f = self.f
        ax = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z))), None, None)
        return f.createIfcLocalPlacement(rel, ax)

    def profile(self, poly: Polygon):
        f = self.f

        def curve(ring):
            pts = [(round(x, 5), round(y, 5)) for x, y in list(ring.coords)[:-1]]
            pl = f.createIfcCartesianPointList2D(pts)
            return f.createIfcIndexedPolyCurve(pl, [f.createIfcLineIndex(list(range(1, len(pts) + 1)) + [1])], False)
        poly = poly.simplify(0.003)
        if poly.interiors:
            return f.createIfcArbitraryProfileDefWithVoids("AREA", None, curve(poly.exterior), [curve(r) for r in poly.interiors])
        return f.createIfcArbitraryClosedProfileDef("AREA", None, curve(poly.exterior))

    def solid(self, poly: Polygon, z0: float, h: float):
        f = self.f
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z0))), None, None)
        return f.createIfcExtrudedAreaSolid(self.profile(poly), pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(h))

    def shape_items(self, product, parts):
        """parts: [(polygon, z0, height, style key)] -> one SweptSolid Body with a styled item per part."""
        f = self.f
        items = []
        for poly, z0, h, key in parts:
            if poly is None or poly.area <= 1e-6 or h <= 1e-4:
                continue
            it = self.solid(poly, z0, h)
            if key:
                f.createIfcStyledItem(it, [self.style(key)], None)
            items.append(it)
        if not items:
            return False
        product.Representation = f.createIfcProductDefinitionShape(None, None, [
            f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", items)])
        return True

    def shape(self, product, polys, z0, h, style=None, axis=None):
        f = self.f
        items = [self.solid(p, z0, h) for p in polys if p.area > 1e-6 and len(p.exterior.coords) >= 4]
        if not items:
            return False
        rep = f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", items)
        reps = [rep]
        if axis is not None:
            if self.axis_ctx is None:
                self.axis_ctx = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                                                     target_view="GRAPH_VIEW", parent=self.body.ParentContext)
            pl = f.createIfcPolyline([f.createIfcCartesianPoint((round(x, 5), round(y, 5))) for x, y in axis.coords])
            reps.insert(0, f.createIfcShapeRepresentation(self.axis_ctx, "Axis", "Curve2D", [pl]))
        product.Representation = f.createIfcProductDefinitionShape(None, None, reps)
        if style:
            ifcopenshell.api.style.assign_representation_styles(self.f, shape_representation=rep, styles=[self.style(style)])
        return True

    def style(self, key):
        if key not in self.styles:
            rgb, tr = COLOURS[key]
            s = ifcopenshell.api.style.add_style(self.f, name=f"pdf_{key}")
            ifcopenshell.api.style.add_surface_style(self.f, style=s, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "Transparency": tr})
            self.styles[key] = s
        return self.styles[key]

    def _rel(self, product, name, cls, props):
        """Property set / element quantity written directly (the api's add/edit_pset re-reads the templates per
        call: ~70% of the build on big sheets). Same set name twice on one product -> one set."""
        f = self.f
        key = (product.id(), name)
        have = self.sets.get(key)
        if have is not None:
            attr = "HasProperties" if cls == "IfcPropertySet" else "Quantities"
            setattr(have, attr, list(getattr(have, attr)) + props)
            return have
        gid = guid_for(self.doc_id, f"{product.GlobalId}:{name}", self.page)
        ps = f.create_entity(cls, GlobalId=gid, Name=name, **({"HasProperties": props} if cls == "IfcPropertySet"
                                                               else {"Quantities": props}))
        f.create_entity("IfcRelDefinesByProperties", GlobalId=guid_for(self.doc_id, f"{gid}:rel", self.page),
                        RelatedObjects=[product], RelatingPropertyDefinition=ps)
        self.sets[key] = ps
        return ps

    def pset(self, product, name, props: dict):
        f = self.f
        vals = []
        for k, v in props.items():
            if v is None:
                continue
            if hasattr(v, "item") and not isinstance(v, (str, bytes)):
                v = v.item()   # numpy scalar
            t = _PTYPES.get(k)
            if t is None:
                t = ("IfcBoolean" if isinstance(v, bool) else "IfcInteger" if isinstance(v, int) else
                     "IfcReal" if isinstance(v, float) else "IfcLabel")
            if t == "IfcBoolean":
                v = bool(v)
            elif t in ("IfcLabel", "IfcIdentifier"):
                v = str(v)
                if len(v) > 255:
                    t = "IfcText"
            vals.append(f.create_entity("IfcPropertySingleValue", Name=k, NominalValue=f.create_entity(t, v)))
        if vals:
            self._rel(product, name, "IfcPropertySet", vals)

    def qto(self, product, name, props: dict):
        f = self.f
        qs = []
        for k, v in props.items():
            if v is None:
                continue
            v = round(float(v), 4)
            if k.endswith("Area"):
                qs.append(f.create_entity("IfcQuantityArea", Name=k, AreaValue=v))
            elif k.endswith("Volume"):
                qs.append(f.create_entity("IfcQuantityVolume", Name=k, VolumeValue=v))
            else:
                qs.append(f.create_entity("IfcQuantityLength", Name=k, LengthValue=v))
        if qs:
            self._rel(product, name, "IfcElementQuantity", qs)

    def provenance(self, product, it: dict | None):
        self.pset(product, "Hologram_Provenance", {**self.prov, "item_id": (it or {}).get("item_id"),
                                                   "page": self.page, "conf": (it or {}).get("conf")})


# ---------------------------------------------------------------- main builder

def _new_file(doc_id: str, project_name: str | None):
    f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=project_name or doc_id)
    proj.GlobalId = guid_for(doc_id, "project", 0)
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"})
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    site.GlobalId = guid_for(doc_id, "site", 0)
    bldg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    bldg.GlobalId = guid_for(doc_id, "building", 0)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bldg], relating_object=site)
    org = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
    site.ObjectPlacement = f.createIfcLocalPlacement(None, org)
    bldg.ObjectPlacement = f.createIfcLocalPlacement(site.ObjectPlacement, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
    return f, proj, bldg, body


def _class_mm(tc) -> int | None:
    """props.thickness_class (walls role) -> mm, rounded to 10 mm: 0.2 / 200 / '200' / '200 mm' / 'wall_200'."""
    import re
    if tc is None or isinstance(tc, bool):
        return None
    if isinstance(tc, (int, float)):
        v = float(tc)
    else:
        m = re.search(r"\d+(?:\.\d+)?", str(tc))
        if not m:
            return None
        v = float(m.group(0))
    mm = v * 1000 if v < 2 else v
    mm = int(round(mm / 10) * 10)
    return mm if 10 <= mm <= 2000 else None


ROOM_NUMBER_RE = r"[A-Z]{0,3}[-.]?\d{1,4}[A-Z]?(?:[./]\d{1,3})?"   # A12, 3.12, U-104, 1012A


def _room_texts(items, room_polys, rooms, mpp) -> dict:
    """Free room-label text items (props.role room_label) -> the room whose polygon holds most of the text box:
    {room item_id: {"numbers": [...], "names": [...]}}. A text overlapping several rooms goes to the one with the
    largest share (>= 35 % of the text box, or its centre inside). Texts equal to the room's own label/number skip."""
    import re
    num_re = re.compile(ROOM_NUMBER_RE + r"$")
    out: dict = {}
    cands = [(it, rp) for it in rooms if (rp := room_polys.get(it["item_id"])) is not None and rp.is_valid]
    if not cands:
        return out
    for t in items:
        if t.get("kind") != "text" or (t.get("props") or {}).get("role") not in ("room_label", "room_number"):
            continue
        txt = " ".join(str(t.get("label") or "").split())
        bb = t.get("bbox_px")
        if not txt or not bb:
            continue
        tb = _poly_m([[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]]], mpp)
        if tb is None or tb.area <= 0:
            continue
        c = tb.centroid
        best, best_s = None, 0.0
        for it, rp in cands:
            if not rp.intersects(tb):
                continue
            s_ = rp.intersection(tb).area / tb.area + (0.5 if rp.contains(c) else 0.0)
            if s_ > best_s:
                best, best_s = it, s_
        if best is None or best_s < 0.35:
            continue
        pr = best.get("props") or {}
        d = out.setdefault(best["item_id"], {"numbers": [], "names": []})
        if num_re.match(txt) and any(ch.isdigit() for ch in txt):
            if txt != str(pr.get("number") or "").strip() and txt not in d["numbers"]:
                d["numbers"].append(txt)
        elif txt.upper() != " ".join(str(best.get("label") or "").split()).upper() and txt not in d["names"]:
            d["names"].append(txt)
    return out


def _add_storey(f, bldg, body, planmap: dict, storey_name: str, storey_elevation: float, wall_height: float,
                doc_id: str, level: dict | None = None, place: bool = False) -> dict:
    sc = planmap.get("scale") or {}
    mpp = sc.get("m_per_px")
    if not mpp:
        raise ValueError("plan map has no scale.m_per_px")
    m_per_pt = sc.get("m_per_pt")
    page = int(planmap.get("page", 1))
    prov = {"source": "pdf_vector", "doc_id": doc_id, "m_per_px": float(mpp),
            "m_per_pt": float(m_per_pt) if m_per_pt else None, "scale_method": sc.get("method"),
            "scale_ratio": sc.get("ratio"), "scale_confidence": sc.get("confidence"),
            "coords": "plan x = page px x * m_per_px, plan y = -page px y * m_per_px"}
    w = _W(f, body, doc_id, page, {k: v for k, v in prov.items() if v is not None})
    sem = planmap.get("semantics") or {}
    sst = dict(sem.get("storey") or {})
    pst = (planmap.get("provenance") or {}).get("storey") or {}   # pdf_levels.planmap_provenance (title block)
    lv = level or {}
    if storey_name in (None, "", "Floor 1"):
        for cand in (sst.get("name"), pst.get("name"), lv.get("name")):
            if cand and str(cand).strip():
                storey_name = _storey_title(str(cand))
                break
    storey_name = storey_name or "Floor 1"
    if sst.get("elevation_m") is None:
        sst.pop("elevation_m", None)
        if pst.get("elevation_m") is not None and not storey_elevation:
            sst.update(elevation_m=float(pst["elevation_m"]), elevation_source=pst.get("source"))
    if sem.get("wall_height_m"):
        wall_height = float(sem["wall_height_m"])
    elif lv.get("height_m"):
        wall_height = float(lv["height_m"])
    if sst.get("elevation_m") is None and lv.get("elevation_m") is not None and not storey_elevation:
        sst = {**sst, "elevation_m": float(lv["elevation_m"]), "elevation_source": lv.get("source")}
    # storey height (floor to floor): printed on the sheet (title block / level marks: pdf_levels) else the wall
    # height. With a printed height the walls run from this floor to the underside of the slab above (storey height
    # - slab), never below the highest printed ceiling + 0.1 m, so storey, walls and the next floor agree.
    storey_h, storey_h_src = None, None
    lv_h = None if str(lv.get("height_source") or "").startswith("default") else lv.get("height_m")
    for cand, src in ((pst.get("height_m"), pst.get("source")), (lv_h, lv.get("source")),
                      (sst.get("height_m"), sst.get("elevation_source"))):
        try:
            if cand is not None and 2.2 <= float(cand) <= 8.0:
                storey_h, storey_h_src = float(cand), f"printed: {src}" if src else "printed"
                break
        except (TypeError, ValueError):
            continue
    if storey_h:
        ceil_ = [float(v) for v in (sem.get("ceiling_heights_m") or []) if isinstance(v, (int, float))]
        wall_height = round(min(storey_h, max(storey_h - SLAB_THICK_M, max(ceil_, default=0.0) + 0.1)), 3)
    else:
        storey_h, storey_h_src = float(wall_height), "wall height (no storey height printed)"
    door_head = float(sem.get("door_height_m") or DOOR_HEAD_M)

    st = w.entity("IfcBuildingStorey", "storey", name=storey_name)
    # Elevation carries the printed level (e.g. +9.000 in the height system). Placement z = the storey_elevation the
    # caller passes (ingest: the level read by pdf_levels; 0 by default), like a native export: the 3D walk mode
    # puts the floor at the scene storey's elevation_m, so geometry and Elevation must agree. Sets: z_m from levels.
    st.Elevation = float(sst.get("elevation_m", storey_elevation))
    z_pl = float(storey_elevation)
    if place and not storey_elevation and lv.get("z_m") is not None:
        z_pl = float(lv["z_m"])   # multi-storey set: storey placed at its height above the lowest one
    loc, ref = (0.0, 0.0, z_pl), None
    if place and lv.get("offset_m"):  # multi-sheet set: this page's frame -> the reference page (pdf_levels)
        import math
        dx, dy = (float(v) for v in lv["offset_m"])
        th = math.radians(float(lv.get("rotation_deg") or 0.0))
        loc = (round(dx, 4), round(-dy, 4), z_pl)   # page y down -> plan y up
        if abs(th) > 1e-6:
            ref = f.createIfcDirection((round(math.cos(th), 9), round(-math.sin(th), 9), 0.0))
    st.ObjectPlacement = f.createIfcLocalPlacement(bldg.ObjectPlacement, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint(loc), f.createIfcDirection((0.0, 0.0, 1.0)) if ref else None, ref))
    ifcopenshell.api.aggregate.assign_object(f, products=[st], relating_object=bldg)
    w.provenance(st, None)
    w.pset(st, "Hologram_StoreySource", {"HeightSystem": sst.get("height_system"),
                                         "ElevationSource": sst.get("elevation_source"),
                                         "StoreyNumber": sst.get("number"), "WallHeight": wall_height,
                                         "DoorHeight": door_head, "StoreyHeight": storey_h,
                                         "StoreyHeightSource": storey_h_src})
    w.qto(st, "Qto_BuildingStoreyBaseQuantities", {"GrossHeight": storey_h,
                                                   "NetHeight": round(max(wall_height, storey_h - SLAB_THICK_M), 4)})
    sp = st.ObjectPlacement

    def evidence(prod, src, detail, height_src=None):
        """DATA RULE: where an element / dimension comes from (measured | printed | derived | default)."""
        w.pset(prod, "Hologram_Evidence", {"Source": src, "Detail": str(detail)[:2000],
                                           "HeightSource": height_src})
    ceil_pr = [float(v) for v in (sem.get("ceiling_heights_m") or []) if isinstance(v, (int, float))]
    if storey_h_src and storey_h_src.startswith("printed"):
        sh_src = "derived" if "slab" in storey_h_src else "printed"
        wh_src = "derived"
        wh_detail = (f"wall height {wall_height} m = min(storey height {storey_h} m, max(storey height - "
                     f"{SLAB_THICK_M} m default slab, highest printed ceiling {max(ceil_pr, default=0.0)} m + 0.1 m))")
    else:
        sh_src = wh_src = "derived" if sem.get("wall_height_m") or lv_h else "default"
        wh_detail = (f"wall height {wall_height} m from " + ("printed ceiling heights (semantics.wall_height_m)"
                     if sem.get("wall_height_m") else f"the level table ({lv.get('source')})" if lv_h
                     else f"default {wall_height} m (nothing printed: "
                          f"{lv.get('height_source') or 'no level table'})"))
    _es = str(sst.get("elevation_source") or "").lower()
    el_src = "printed" if sst.get("elevation_m") is not None and any(k in _es for k in (
        "mark", "title", "printed", "table", "level +", "level -")) else "default"   # not "page order" / defaults
    evidence(st, el_src, f"elevation {st.Elevation} m: {sst.get('elevation_source') or 'default (no level printed)'}; "
             f"storey height {storey_h} m: {storey_h_src}; {wh_detail}", sh_src)
    door_src = "printed" if sem.get("door_height_m") else "default"

    items = planmap.get("items") or []
    def _glass(it):  # interior glazing the openings reader tags as a partition: a glass wall, not a window
        return it.get("kind") in ("door", "window") and (it.get("props") or {}).get("kind") == "glass_partition"
    # DATA RULE: a wall item whose drawn linework pdf_vector could not find (props.evidence.source == "none") is
    # not emitted; it is listed on the storey (Hologram_Dropped)
    no_ev = [it for it in items if it.get("kind") == "wall" and _wall_ev(it).get("source") == "none"]
    walls = [(it, _wall_poly(it, mpp, m_per_pt)) for it in items if it.get("kind") == "wall"
             and _wall_ev(it).get("source") != "none"]
    for it in items:
        if _glass(it):
            gp = _poly_m(it.get("polygon_px"), mpp)
            if gp is None and it.get("bbox_px"):
                x0, y0, x1, y1 = it["bbox_px"]
                gp = _poly_m([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], mpp)
            if gp is not None:
                pr = dict(it.get("props") or {}, glass=True)
                pr.setdefault("thickness_m", round(max(0.02, min(_rect_frame(gp, None)[3], 0.12)), 3))
                walls.append(({**it, "kind": "wall", "props": pr}, gp))
    walls = [(it, p) for it, p in walls if p is not None]
    rooms = [it for it in items if it.get("kind") == "room"]
    opens = []
    for it in items:
        if it.get("kind") not in ("door", "window") or _glass(it):
            continue
        p = _poly_m(it.get("polygon_px"), mpp)
        if p is None and it.get("bbox_px"):
            x0, y0, x1, y1 = it["bbox_px"]
            p = _poly_m([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], mpp)
        if p is not None:
            opens.append((it, p))

    # opening frames (centre, unit axis, width, depth) in plan metres
    oframe = [_rect_frame(p, (it.get("props") or {}).get("width_m")) for it, p in opens]
    owidth = [float((it.get("props") or {}).get("width_m") or fr[2]) for (it, _), fr in zip(opens, oframe)]

    # wall graph: straight pieces -> runs (merged, joined); every opening gets a run as host
    runs, conns, run_host, graph_err = [], [], {}, None
    free = list(range(len(walls)))
    try:
        runs, conns, run_host, free = _wall_graph(walls, opens, oframe, owidth, mpp, wall_height)
    except Exception as e:  # noqa: BLE001  any failure: previous behaviour (one wall per piece)
        runs, conns, run_host, free = [], [], {}, list(range(len(walls)))
        graph_err = f"{type(e).__name__}: {e}"[:200]

    # free pieces lying inside wall runs: the same wall drawn twice, dropped; a glass one (glazed partition) is
    # a window in an exterior run (facade glazing), recorded on an interior run (Hologram_Glazing), not a window
    if runs and free:
        try:
            free = _free_in_runs(walls, free, runs, opens, oframe, owidth, run_host)
        except Exception:  # noqa: BLE001
            pass

    # free pieces (not straight / glass / graph off): host by overlap like before
    wall_polys = [p for _, p in walls]
    host = {}
    extra = {i: [] for i in free}
    orphans = []
    for k, (it, p) in enumerate(opens):
        if k in run_host:
            continue
        grown = p.buffer(HOST_SEARCH_M)
        best, best_a = None, 0.0
        for i in free:
            wp = wall_polys[i]
            if wp.distance(p) > HOST_SEARCH_M:
                continue
            a = wp.intersection(grown).area
            if a > best_a:
                best, best_a = i, a
        if best is None:
            orphans.append(k)
        else:
            host[k] = best
            extra[best].append(p)

    # footprint (slab + IsExternal): the closed wall envelope (walls + openings), holes filled; rooms only help when
    # the walls alone do not close
    def _room_poly(it):
        rp_ = _poly_m(it.get("polygon_px"), mpp)
        if rp_ is None and it.get("bbox_px"):
            x0, y0, x1, y1 = it["bbox_px"]
            rp_ = _poly_m([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], mpp)
        return rp_
    room_polys = {it["item_id"]: _room_poly(it) for it in rooms}
    unhosted = set() if WG_FILLERS else set(orphans)
    shell = [r.poly for r in runs] + [wall_polys[i] for i in free] + \
        [p for k, (_, p) in enumerate(opens) if k not in unhosted]

    def _foot(polys):
        if not polys:
            return []
        u_ = unary_union(polys).buffer(FOOTPRINT_CLOSE_M, join_style="mitre").buffer(-FOOTPRINT_CLOSE_M,
                                                                                        join_style="mitre")
        parts_ = sorted(_parts(u_), key=lambda g: -g.area)
        return [Polygon(g.exterior) for g in parts_ if g.area >= 0.15 * parts_[0].area] if parts_ else []
    footprint = _foot(shell)
    rp = [p for p in room_polys.values() if p is not None]
    if rp:
        fr_ = _foot(shell + rp)
        if sum(g.area for g in fr_) > 2.0 * sum(g.area for g in footprint):
            footprint = fr_
    outline = unary_union([g.exterior for g in footprint]) if footprint else None

    def external(poly) -> bool:
        return bool(outline is not None and outline.intersection(poly.buffer(0.1)).length > 0.4)

    out_walls = {}
    products = []
    wtypes, dtypes = {}, {}

    glass_leg = next((e for e in sem.get("legend") or [] if e.get("kind") == "glass_partition"), None)

    def wall_type(pr, ext):
        if pr.get("glass") and not pr.get("wall_type") and glass_leg:
            pr = {**pr, "wall_type": glass_leg["code"], "type_description": glass_leg["description"]}
        t_mm = int(round(float(pr.get("thickness_m") or 0) * 1000 / 10) * 10)
        tc = _class_mm(pr.get("thickness_class"))
        if tc and not pr.get("wall_type") and not pr.get("glass"):
            # walls role snapped this wall to a thickness class: one IfcWallType per class, native-style name
            t_mm = tc
            key = ("class", t_mm)
            name = f"{'Partition' if t_mm <= PARTITION_MAX_MM else 'Wall'} {t_mm} mm"
        elif pr.get("wall_type"):
            key = (pr["wall_type"], t_mm)
            name = f"{pr['wall_type']} {pr.get('type_description') or ''} {t_mm} mm".replace("  ", " ")
        else:
            key = ("ext" if ext else "int", t_mm)
            name = f"{'Exterior' if ext else 'Interior'} wall {t_mm} mm"
        if key not in wtypes:
            wt = w.entity("IfcWallType", f"type:wall:{key[0]}:{t_mm}", name=name,
                          predefined="PARTITIONING" if pr.get("glass") else "STANDARD")
            mat = ifcopenshell.api.material.add_material(f, name="Glass" if pr.get("glass") else
                                                         (pr.get("material") or ("Exterior wall" if ext else "Wall")))
            ls = ifcopenshell.api.material.add_material_set(f, name=name, set_type="IfcMaterialLayerSet")
            lay = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=mat)
            lay.LayerThickness = max(t_mm, 10) / 1000
            ifcopenshell.api.material.assign_material(f, products=[wt], type="IfcMaterialLayerSet", material=ls)
            wtypes[key] = (wt, ls)
        return wtypes[key]

    n_wall = 0

    def next_name():
        nonlocal n_wall
        n_wall += 1
        return f"Wall-{n_wall:03d}"

    # wall runs: IfcWallStandardCase placed at the axis start, X along the axis (like an authoring tool's export)
    run_wall = {}
    by_type = {}
    for ri, r in enumerate(runs):
        rep = r.rep
        pr = dict(rep.get("props") or {})
        pr["thickness_m"] = round(r.t, 4)
        ext = external(r.poly)
        h = float(r.h or wall_height)
        if r.h and r.h < wall_height - 0.3 and (not ext or r.opens):
            h = wall_height   # "low wall" inside the building or with a door/window in it: a full-height wall
        o = r.pt(r.s0)
        L = r.length
        wall = w.entity("IfcWallStandardCase", rep["item_id"], name=next_name())
        wall.ObjectPlacement = f.createIfcLocalPlacement(sp, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((round(o[0], 5), round(o[1], 5), 0.0)), f.createIfcDirection((0.0, 0.0, 1.0)),
            f.createIfcDirection((round(r.u[0], 9), round(r.u[1], 9), 0.0))))

        def loc(q, o=o, r=r):
            dx, dy = q[0] - o[0], q[1] - o[1]
            return dx * r.u[0] + dy * r.u[1], dx * r.n[0] + dy * r.n[1] - r.off + (o[0] * r.n[0] + o[1] * r.n[1])
        lp = Polygon([loc(q) for q in list(r.poly.exterior.coords)[:-1]])
        w.shape(wall, [lp], 0.0, h, "wall", axis=LineString([(0.0, 0.0), (L, 0.0)]))
        wt, ls = wall_type(pr, ext)
        by_type.setdefault(wt.id(), (wt, ls, []))[2].append(wall)
        w.pset(wall, "Pset_WallCommon", {"IsExternal": ext, "LoadBearing": None, "Reference": wt.Name,
                                         "FireRating": pr.get("fire_rating"),
                                         "AcousticRating": pr.get("acoustic_rating")})
        a = r.poly.area
        w.qto(wall, "Qto_WallBaseQuantities", {"Length": L, "Width": r.t, "Height": h, "NetFootprintArea": a,
                                               "GrossFootprintArea": a, "GrossSideArea": L * h,
                                               "GrossVolume": a * h})
        w.provenance(wall, rep)
        ids = [str(walls[m][0]["item_id"]) for m in r.members]
        if r.filler:
            evidence(wall, "default", f"filler wall: no drawn wall on the line of {rep['item_id']}", wh_src)
        else:
            sp_open = [str(opens[k][0]["item_id"]) for k in r.opens]
            esrc, edet = _ev_summary([walls[m][0] for m in r.members])
            evidence(wall, esrc, f"pdf_vector wall items {','.join(ids)} ({edet}): axis, length {L:.3f} m and thickness "
                     f"{r.t:.3f} m from the drawn wall polygons (page px x m_per_px {float(mpp):.6f})"
                     + (f"; wall over openings {','.join(sp_open)} between drawn jambs" if sp_open else "")
                     + f"; {wh_detail}", wh_src)
        if len(r.members) > 1:
            w.pset(wall, "Hologram_WallRun", {"MergedPieces": len(r.members), "PieceItemIds": ",".join(
                str(walls[m][0]["item_id"]) for m in r.members)[:2000]})
        elif r.filler:  # no plan-map wall: made only to host the openings the drawing leaves in an undrawn stretch
            w.pset(wall, "Hologram_WallRun", {"Filler": True, "Reason": "hosts openings with no drawn wall on their line",
                                              "HostedItemIds": ",".join(str(opens[k][0]["item_id"])
                                                                        for k in r.opens)[:2000]})
        run_wall[ri] = wall
        products.append(wall)
    # one assign_type per wall type (the api re-derives materials per call), then the layer set usage per wall
    for wt, ls, ws in by_type.values():
        ifcopenshell.api.type.assign_type(f, related_objects=ws, relating_type=wt)
        for wall in ws:
            usage = ifcopenshell.util.element.get_material(wall, should_inherit=False)
            if usage is None or not usage.is_a("IfcMaterialLayerSetUsage"):
                ifcopenshell.api.material.assign_material(f, products=[wall], type="IfcMaterialLayerSetUsage",
                                                          material=ls)
                usage = ifcopenshell.util.element.get_material(wall, should_inherit=False)
            if usage is not None and usage.is_a("IfcMaterialLayerSetUsage"):  # axis = centre line of the layer set
                usage.LayerSetDirection, usage.DirectionSense = "AXIS2", "POSITIVE"
                usage.OffsetFromReferenceLine = -round(float(ls.MaterialLayers[0].LayerThickness) / 2, 4)
    for ri, ta, rj, tb in conns:
        if ri in run_wall and rj in run_wall:
            a_, b_ = run_wall[ri], run_wall[rj]
            f.create_entity("IfcRelConnectsPathElements", GlobalId=w.gid(f"conn:{a_.GlobalId}:{b_.GlobalId}:{ta}"),
                            RelatingElement=a_, RelatedElement=b_, RelatingPriorities=[], RelatedPriorities=[],
                            RelatingConnectionType=ta, RelatedConnectionType=tb)

    # free pieces (gap openings merged into their host, so the lintel and sill are wall material)
    for i in free:
        it, p = walls[i]
        geom = unary_union([p] + [e.buffer(0.02, join_style="mitre") for e in extra[i]]) if extra[i] else p
        pr = it.get("props") or {}
        h = float(pr.get("height_m") or wall_height)
        ext = external(p)
        wall = w.entity("IfcWall", it["item_id"], name=next_name())
        wall.ObjectPlacement = w.placement(sp)
        w.shape(wall, _parts(geom), 0.0, h, "glass" if pr.get("glass") else "wall")
        wt, ls = wall_type(pr, ext)
        ifcopenshell.api.type.assign_type(f, related_objects=[wall], relating_type=wt)
        ifcopenshell.api.material.assign_material(f, products=[wall], material=ls.MaterialLayers[0].Material)
        w.pset(wall, "Pset_WallCommon", {"IsExternal": ext, "LoadBearing": None, "Reference": wt.Name,
                                         "FireRating": pr.get("fire_rating"),
                                         "AcousticRating": pr.get("acoustic_rating")})
        L = float(pr.get("length_m") or 0) or None
        t = float(pr.get("thickness_m") or 0) or None
        w.qto(wall, "Qto_WallBaseQuantities", {"Length": L, "Width": t, "Height": h, "NetFootprintArea": p.area,
                                               "GrossFootprintArea": p.area,
                                               "GrossSideArea": L * h if L else None,
                                               "GrossVolume": p.area * h})
        w.provenance(wall, it)
        esrc, edet = _ev_summary([it])
        evidence(wall, esrc, f"pdf_vector wall item {it['item_id']} ({edet}): drawn polygon "
                 f"({p.area:.3f} m2) as is; {wh_detail}", "printed" if pr.get("height_m") else wh_src)
        out_walls[i] = wall
        products.append(wall)
    # openings with no wall at all (graph off) get a filler wall of their own
    for k in orphans:
        if k in unhosted:
            continue
        it, p = opens[k]
        wall = w.entity("IfcWall", it["item_id"] + "#wall", name=next_name(), predefined="STANDARD")
        wall.ObjectPlacement = w.placement(sp)
        w.shape(wall, [p], 0.0, wall_height, "wall")
        w.pset(wall, "Pset_WallCommon", {"IsExternal": external(p)})
        w.provenance(wall, {"item_id": it["item_id"] + "#wall", "conf": it.get("conf")})
        evidence(wall, "default", f"filler wall for {it['item_id']}: no drawn wall on its line (PDF_IFC_FILLERS=1)",
                 wh_src)
        out_walls[("o", k)] = wall
        products.append(wall)
        host[k] = ("o", k)

    # openings + fillings: opening placed in the host wall's frame, the door/window placed in the opening's frame
    # (X along the wall; for doors +Y = the side the leaf opens into, so OperationType handing reads like a native one)
    n_void = 0
    n_clipped = 0
    n_kind = {"door": 0, "window": 0}
    fill_by_type = {}
    glazed = {}  # interior run index -> [(item id, s0, s1)]: glazed partitions recorded on the wall, not windows
    for k, (it, p) in enumerate(opens):
        if k in unhosted:
            continue
        kind = it["kind"]
        pr = it.get("props") or {}
        if pr.get("glass_in_run") and k in run_host and not (outline is not None and outline.intersection(
                runs[run_host[k]].poly.buffer(0.1)).length > 0.5 * runs[run_host[k]].length):
            r_ = runs[run_host[k]]   # interior run (it runs along the building outline for less than half its length)
            cs_ = r_.proj(oframe[k][0])[0] - r_.s0
            glazed.setdefault(run_host[k], []).append((str(it["item_id"]), round(cs_ - owidth[k] / 2, 3),
                                                       round(cs_ + owidth[k] / 2, 3)))
            continue
        c, u, wid, dep = oframe[k]
        wid = owidth[k]
        if k in run_host:
            r = runs[run_host[k]]
            wall = run_wall[run_host[k]]
            hh = float(r.h or wall_height)
            cs, _ = r.proj(c)
            # an opening never runs past its host wall's ends (a native opening is cut out of the wall body)
            a_, b_ = max(cs - wid / 2, r.s0), min(cs + wid / 2, r.s1)
            if b_ - a_ < wid - 0.005 and b_ - a_ >= 0.3:
                cs, wid = (a_ + b_) / 2, b_ - a_
                n_clipped += 1
            lc, lu, thick = (cs - r.s0, 0.0), (1.0, 0.0), r.t
            wu, wn = r.u, r.n
            hw = r.poly
        else:
            wall = out_walls[host[k]]
            hw = wall_polys[host[k]] if isinstance(host[k], int) else p
            hh = float(((walls[host[k]][0].get("props") or {}).get("height_m") if isinstance(host[k], int) else 0)
                       or wall_height)
            thick = max(dep, float((walls[host[k]][0].get("props") or {}).get("thickness_m") or 0)
                        if isinstance(host[k], int) else dep)
            lc, lu = c, u
            wu, wn = u, (-u[1], u[0])
        top = max(hh, wall_height) - 0.05
        if kind == "door":
            z0 = 0.0
            z1 = min(float(pr.get("height_m") or door_head), top)
        elif pr.get("kind") in ("curtain_wall", "glass_partition"):
            z0, z1 = 0.0, top
        else:
            z0 = float(pr["sill_m"] if pr.get("sill_m") is not None else pr.get("sill_height_m") or WINDOW_SILL_M)
            head = pr.get("head_m") or (z0 + float(pr["height_m"]) if pr.get("height_m") else None)
            z1 = min(float(head or WINDOW_HEAD_M), top)
            if z1 - z0 < 0.3:
                z0 = max(0.0, z1 - 1.2)
        op = w.entity("IfcOpeningElement", it["item_id"] + "#opening", name=f"opening {it['item_id']}",
                      predefined="OPENING")
        op.ObjectPlacement = w.placement(wall.ObjectPlacement)
        w.shape(op, [_rect(lc, lu, wid, thick + 0.1)], z0, z1 - z0)
        # relations written directly (the api re-derives every placement: ~4x slower on big sheets)
        f.create_entity("IfcRelVoidsElement", GlobalId=w.gid(it["item_id"] + "#voids"), RelatingBuildingElement=wall,
                        RelatedOpeningElement=op)
        n_void += 1
        cls = "IfcDoor" if kind == "door" else "IfcWindow"
        n_kind[kind] += 1
        el = w.entity(cls, it["item_id"], name=f"{'Door' if kind == 'door' else 'Window'}-{n_kind[kind]:03d}",
                      predefined=kind.upper())
        op_type = _door_operation(pr) if kind == "door" else _window_partitioning(pr)
        el.PredefinedType = None   # typed occurrence: PredefinedType / OperationType live on the type
        # door frame: +Y towards the swing side (props.swing_dir, page y down -> plan y up)
        sx = 1.0
        sd = pr.get("swing_dir") if kind == "door" else None
        if sd and len(sd) == 2:
            swm = (float(sd[0]), -float(sd[1]))
            sx = 1.0 if swm[0] * wn[0] + swm[1] * wn[1] >= 0 else -1.0
        el.ObjectPlacement = f.createIfcLocalPlacement(op.ObjectPlacement, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((round(lc[0], 5), round(lc[1], 5), 0.0)), f.createIfcDirection((0.0, 0.0, 1.0)),
            f.createIfcDirection((round(lu[0] * sx, 9), round(lu[1] * sx, 9), 0.0))))
        el.OverallWidth = round(wid, 4)
        el.OverallHeight = round(z1 - z0, 4)
        parts = _door_parts(wid, thick, z1, op_type) if kind == "door" else _window_parts(wid, thick, z0, z1)
        w.shape_items(el, parts)
        tkey = (kind, op_type, int(round(wid * 10)), int(round((z1 - z0) * 10)))
        if tkey not in dtypes:
            tcls = "IfcDoorType" if kind == "door" else "IfcWindowType"
            label = op_type.replace("_", " ").lower()
            tname = (f"Door {label} {tkey[2] * 100} x {tkey[3] * 100} mm" if kind == "door"
                     else f"Window {label} {tkey[2] * 100} x {tkey[3] * 100} mm")
            dt = w.entity(tcls, f"type:{kind}:{op_type}:{tkey[2]}:{tkey[3]}", name=tname, predefined=kind.upper())
            if kind == "door":
                dt.OperationType = op_type
            else:
                dt.PartitioningType = op_type
            try:
                dt.HasPropertySets = _opening_type_props(f, w, dt, kind, op_type, wid, thick)
            except Exception:  # noqa: BLE001
                pass
            dtypes[tkey] = dt
        fill_by_type.setdefault(tkey, []).append(el)
        f.create_entity("IfcRelFillsElement", GlobalId=w.gid(it["item_id"] + "#fills"), RelatingOpeningElement=op,
                        RelatedBuildingElement=el)
        ext = external(p) or bool(hw is not None and external(hw) and kind == "window")
        w.pset(el, "Pset_DoorCommon" if kind == "door" else "Pset_WindowCommon",
               {"IsExternal": ext, "FireRating": pr.get("fire_rating"), "AcousticRating": pr.get("acoustic_rating"),
                "Reference": dtypes[tkey].Name})
        if kind == "window":
            w.pset(el, "Hologram_Opening", {"SillHeight": round(z0, 3), "HeadHeight": round(z1, 3),
                                            "SillSource": pr.get("sill_source"), "GlazingKind": pr.get("kind")})
        else:
            w.pset(el, "Hologram_Opening", {"HeightSource": pr.get("height_source"),
                                            "HingeSide": pr.get("hinge_side")})
        w.qto(el, "Qto_DoorBaseQuantities" if kind == "door" else "Qto_WindowBaseQuantities",
              {"Width": el.OverallWidth, "Height": el.OverallHeight, "Area": el.OverallWidth * el.OverallHeight,
               "Perimeter": 2 * (el.OverallWidth + el.OverallHeight)})
        w.provenance(el, it)
        if kind == "door":
            hs = "printed" if (pr.get("height_m") and str(pr.get("height_source") or "") not in ("", "default")) \
                else door_src
            hd = f"head {z1:.2f} m: " + (f"printed ({pr.get('height_source') or 'door height note'})" if hs == "printed"
                                         else f"default {DOOR_HEAD_M} m")
        else:
            sill_p = pr.get("sill_m") is not None and str(pr.get("sill_source") or "default") != "default"
            head_p = bool(pr.get("head_m") or pr.get("height_m")) and \
                str(pr.get("head_source") or pr.get("height_source") or "default") != "default"
            hs = "printed" if sill_p and head_p else "default"
            hd = (f"sill {z0:.2f} m: {'printed (' + str(pr.get('sill_source')) + ')' if sill_p else 'default'}, "
                  f"head {z1:.2f} m: {'printed' if head_p else 'default'}")
        evidence(el, "measured", f"{kind} {it['item_id']}: width {wid:.3f} m and position measured from the drawn "
                 f"symbol (bbox px {[round(float(v), 1) for v in (it.get('bbox_px') or [])]}); {hd}", hs)
        if kind == "door" and pr.get("det_conf") is not None:  # detector experiment: supporting evidence only
            w.pset(el, "Hologram_Detector", {"Confirmed": True, "Confidence": float(pr["det_conf"]),
                                             "Evidence": str(pr.get("det_evidence") or "derived: detector")[:200]})
        products.append(el)

    for tkey, els in fill_by_type.items():
        ifcopenshell.api.type.assign_type(f, related_objects=els, relating_type=dtypes[tkey])

    # spaces
    n_space = 0
    texts = _room_texts(items, room_polys, rooms, mpp)
    used_nums = {str((it.get("props") or {}).get("number") or "").strip() for it in rooms} | \
        {v for d in texts.values() for v in d.get("numbers", [])}
    seq = 0
    for it in rooms:
        pr = it.get("props") or {}
        q = it.get("q") or {}
        poly = room_polys.get(it["item_id"])
        tx = texts.get(it["item_id"]) or {}
        # like a native export: Name = the printed room number, LongName = the printed room name. A label the rooms
        # reader left as a free text item inside / overlapping the polygon still counts as printed. A room with no
        # printed number gets a storey-scoped running number (an authoring tool numbers every space), flagged in
        # Hologram_RoomArea.NumberSource so it is never mistaken for a printed one.
        num = str(pr.get("number") or "").strip()
        num_src = "printed" if num else None
        if not num and tx.get("numbers"):
            num, num_src = tx["numbers"][0], "printed (free label in the room)"
        label = " ".join(str(it.get("label") or "").split()) or None
        label_src = "printed" if label else None
        if not label and tx.get("names"):
            label, label_src = tx["names"][0], "printed (free label in the room)"
        if not num and AUTO_NUMBER_SPACES:
            while True:
                seq += 1
                sno = next((v for v in (sst.get("number"), pst.get("number"), lv.get("number")) if v is not None), None)
                cand = f"{sno}.{seq:02d}" if sno is not None else f"{seq:03d}"
                if cand not in used_nums:
                    break
            num, num_src = cand, "generated (no number printed)"
            used_nums.add(num)
        rt = str(pr.get("room_type") or "").replace("_", " ").strip()
        sp_el = w.entity("IfcSpace", it["item_id"], name=num, predefined="SPACE")
        sp_el.Name = num
        sp_el.LongName = label or (rt.capitalize() if rt and rt.lower() not in ("other", "unknown", "room") else None) \
            or "Room"
        sp_el.ObjectPlacement = w.placement(sp)
        measured = q.get("area_m2") or pr.get("area_m2_geom") or (round(poly.area, 3) if poly is not None else None)
        printed = q.get("area_m2_printed") or pr.get("area_m2_label")
        sh = float(pr.get("ceiling_height_m") or wall_height)
        if poly is not None:
            w.shape(sp_el, [poly], 0.0, sh, "space")
        # quantities are what the model measures (a native export computes them from the geometry); the area the
        # sheet prints goes next to it as a property, so the two can be compared
        net = (measured or printed) if NET_AREA_FROM == "measured" else (printed or measured)
        w.qto(sp_el, "Qto_SpaceBaseQuantities", {"NetFloorArea": net, "GrossFloorArea": measured,
                                                 "Height": sh if poly is not None else None,
                                                 "NetVolume": net * sh if net and poly is not None else None,
                                                 "GrossPerimeter": poly.exterior.length if poly is not None else None})
        w.pset(sp_el, "Hologram_RoomArea", {"MeasuredArea": measured, "PrintedArea": printed,
                                            "AreaSource": "measured" if net == measured and measured else
                                            ("printed" if printed else None),
                                            "AreaError": round((measured - printed) / printed, 4)
                                            if measured and printed else None,
                                            "NumberSource": num_src, "NameSource": label_src,
                                            "RoomType": pr.get("room_type"),
                                            "CeilingHeight": pr.get("ceiling_height_m"),
                                            "CeilingHeightSource": "h= mark in the room" if pr.get("ceiling_height_m") else None})
        w.provenance(sp_el, it)
        evidence(sp_el, "measured", f"room {it['item_id']}: polygon from pdf_rooms (measured area {measured} m2"
                 + (f", printed area {printed} m2" if printed else ", no printed area") + f"); name {num!r}: {num_src}; "
                 f"label {label!r}: {label_src or 'none printed'}; height {sh} m: "
                 + ("printed h= mark in the room" if pr.get("ceiling_height_m") else wh_detail),
                 "printed" if pr.get("ceiling_height_m") else wh_src)
        n_space += 1
        products.append(sp_el)

    # floor slab under the building footprint
    if footprint:
        slab = w.entity("IfcSlab", "floor", name=f"Floor slab {storey_name}", predefined="FLOOR")
        slab.ObjectPlacement = w.placement(sp)
        w.shape(slab, footprint, -SLAB_THICK_M, SLAB_THICK_M, "slab")
        w.qto(slab, "Qto_SlabBaseQuantities", {"Depth": SLAB_THICK_M, "GrossArea": sum(g.area for g in footprint)})
        w.provenance(slab, {"item_id": "floor"})
        evidence(slab, "derived", f"outline of the drawn walls + hosted openings closed over {FOOTPRINT_CLOSE_M} m gaps "
                 f"({sum(g.area for g in footprint):.1f} m2); thickness {SLAB_THICK_M} m default", "default")
        products.append(slab)

    # fixtures role (stairs, railings, sanitary, furniture): contained in the storey by its own code
    stats_fx = None
    try:
        from pipeline import pdf_fixtures
        stats_fx = pdf_fixtures.to_ifc(f, st, body, planmap.get("fixtures") or [], 0.0, storey_height_m=storey_h,
                                       m_per_pt=m_per_pt, doc_id=doc_id, page=page)
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        stats_fx = {"error": f"{type(e).__name__}: {e}"[:200]}

    spatial = [p for p in products if not p.is_a("IfcSpace")]
    if spatial:  # placements are already relative to the storey: write the relations directly
        f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=w.gid("storey#contains"),
                        RelatedElements=spatial, RelatingStructure=st)
    spaces = [p for p in products if p.is_a("IfcSpace")]
    if spaces:
        f.create_entity("IfcRelAggregates", GlobalId=w.gid("storey#spaces"), RelatingObject=st, RelatedObjects=spaces)
    for ri_, gl in glazed.items():
        w.pset(run_wall[ri_], "Hologram_Glazing", {
            "GlazedSpans": ";".join(f"{i}:{a}-{b} m" for i, a, b in gl)[:2000], "Source": "measured",
            "Detail": "interior glass_partition items lying inside this drawn wall run: kept as the wall they "
                      "duplicate, not exported as IfcWindow (facade glazing stays a window)"})
    if no_ev:
        w.pset(st, "Hologram_Dropped", {"Count": len(no_ev), "ItemIds": ",".join(str(i["item_id"]) for i in no_ev)[:2000],
                                        "Reason": "wall item with no drawn linework found (evidence.source none)"})
    if unhosted:
        evidence_ids = ",".join(str(opens[k][0]["item_id"]) for k in sorted(unhosted))
        w.pset(st, "Hologram_Unhosted", {"Count": len(unhosted), "ItemIds": evidence_ids[:2000],
                                         "Reason": "door/window with no drawn wall on its line: left out of the "
                                                   "IFC (no invented walls); fix the wall or the opening upstream"})
    run_len = [r.length for r in runs]
    return {"unhosted_openings": len(unhosted), "walls_without_evidence_dropped": len(no_ev), "walls": len(out_walls) + len(run_wall), "wall_runs": len(run_wall), "free_walls": len(free),
            "filler_walls": len(set(orphans) - unhosted) + sum(1 for r in runs if r.filler),
            "mean_wall_length_m": round(sum(run_len) / len(run_len), 3) if run_len else None,
            "wall_graph": dict(_wall_graph.last) if runs else None, "wall_graph_error": graph_err,
            "openings": n_void, "openings_in_runs": len(run_host), "openings_clipped_to_wall": n_clipped, "spaces": n_space,
            "doors": sum(1 for it, _ in opens if it["kind"] == "door"),
            "windows": sum(1 for it, _ in opens if it["kind"] == "window"), "slab": bool(footprint),
            "fixtures": stats_fx}


def _add_grid(f, body, planmap: dict, doc_id: str):
    """IfcGrid from the levels role's grid axes (planmap.provenance.grid, page px) on that page's storey."""
    g = ((planmap.get("provenance") or {}).get("grid")) or []
    mpp = (planmap.get("scale") or {}).get("m_per_px")
    if not g or not mpp:
        return None
    page = int(planmap.get("page", 1))
    sgid = guid_for(doc_id, "storey", page)
    st = next((s for s in f.by_type("IfcBuildingStorey") if s.GlobalId == sgid), None)
    if st is None:
        return None

    # split U/V by line direction (tags like U1..U12 / A..H are not reliably letters vs digits)
    import math as _m
    segs = [(a, a.get("p0_px"), a.get("p1_px")) for a in g]
    segs = [(a, p0, p1) for a, p0, p1 in segs if p0 and p1 and (p0[0] != p1[0] or p0[1] != p1[1])]
    if not segs:
        return None
    ang = [_m.atan2(p1[1] - p0[1], p1[0] - p0[0]) % _m.pi for _, p0, p1 in segs]
    ref = ang[0]
    near = [min(abs(t - ref), _m.pi - abs(t - ref)) < _m.pi / 4 for t in ang]
    fam_u = [sg for sg, n in zip(segs, near) if n]
    fam_v = [sg for sg, n in zip(segs, near) if not n]
    if not fam_u or not fam_v:  # one direction only: no IfcGrid, and no orphan IfcGridAxis left in the file
        return None
    if any(str(a.get("tag") or "").isdigit() for a, _, _ in fam_u) and \
            not any(str(a.get("tag") or "").isdigit() for a, _, _ in fam_v):
        fam_u, fam_v = fam_v, fam_u  # keep the old convention: lettered axes = U, numbered = V

    def axis(a, p0, p1):
        pl = f.createIfcPolyline([f.createIfcCartesianPoint((round(x * mpp, 4), round(-y * mpp, 4))) for x, y in (p0, p1)])
        return f.createIfcGridAxis(str(a.get("tag") or ""), pl, True)
    u = [axis(*sg) for sg in fam_u]
    v = [axis(*sg) for sg in fam_v]
    if not u or not v:
        return None
    grid = ifcopenshell.api.root.create_entity(f, ifc_class="IfcGrid", name="Grid")
    grid.GlobalId = guid_for(doc_id, "grid", page)
    grid.UAxes, grid.VAxes = u, v
    grid.ObjectPlacement = f.createIfcLocalPlacement(st.ObjectPlacement, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
    ctx = next((c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "FootPrint"), None)
    if ctx is None:
        ctx = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="FootPrint",
                                                   target_view="PLAN_VIEW", parent=body.ParentContext)
    gcs = f.createIfcGeometricCurveSet([a.AxisCurve for a in u + v])
    grid.Representation = f.createIfcProductDefinitionShape(None, None, [
        f.createIfcShapeRepresentation(ctx, "FootPrint", "GeometricCurveSet", [gcs])])
    ifcopenshell.api.spatial.assign_container(f, products=[grid], relating_structure=st)
    return grid


def _storey_from_text(pm: dict, words: list | None) -> dict:
    """Printed storey name / level / height read straight from the page words (pdf_levels.storey_info, a pure text
    parse, < 0.1 s), for a plan map whose semantics.storey and provenance.storey are missing (their stages were cut
    by the ingest budget). Words: [{"text", "bbox_px"}] (text-<page>.json); level marks inside the plan region only.
    Returns pdf_levels.storey_info's dict ({} when nothing is printed / on any error)."""
    if not words:
        return {}
    try:
        from pipeline import pdf_levels
        from shapely.geometry import Polygon as _P
        reg = ((pm.get("semantics") or {}).get("plan_region") or {}).get("polygon_px")
        region = _P(reg).buffer(0) if reg and len(reg) >= 3 else None
        page = {"words": [{"text": w.get("text") or "", "bbox": w.get("bbox_px") or w.get("bbox")}
                          for w in words if (w.get("bbox_px") or w.get("bbox"))]}
        st = pdf_levels.storey_info(page, region)
        return {k: v for k, v in st.items() if v is not None}
    except Exception:  # noqa: BLE001
        return {}


def _with_text_storey(pm: dict, words: list | None) -> dict:
    """pm, or a copy whose semantics.storey / provenance.storey are filled from the printed text when both are
    missing (so the storey keeps its printed name and level when the analyse / provenance stages were cut)."""
    sem = pm.get("semantics") or {}
    sst = sem.get("storey") or {}
    pst = (pm.get("provenance") or {}).get("storey") or {}
    if (sst.get("name") or pst.get("name")) and (sst.get("elevation_m") is not None or pst.get("elevation_m") is not None):
        return pm
    t = _storey_from_text(pm, words)
    if not t:
        return pm
    tag = " (page text; the analyse stage did not run)"
    nsst = dict(sst)
    if not nsst.get("name") and t.get("name"):
        nsst.update(name=t["name"], number=t.get("number"))
    if nsst.get("elevation_m") is None and t.get("elevation_m") is not None:
        nsst.update(elevation_m=t["elevation_m"], elevation_source=str(t.get("elevation_source")) + tag)
    npst = dict(pst)
    if npst.get("height_m") is None and t.get("height_m") is not None:
        npst.update(height_m=t["height_m"], source=str(t.get("height_source")) + tag)
    if not npst.get("name") and t.get("name"):
        npst.update(name=t["name"], number=t.get("number"))
    return {**pm, "semantics": {**sem, "storey": nsst}, "provenance": {**(pm.get("provenance") or {}), "storey": npst}}


def build_many(pages: list[tuple[dict, str, float]], out_path, *, wall_height: float = 2.7, doc_id: str | None = None,
               project_name: str | None = None, words: list | None = None) -> Path:
    """[(planmap, storey_name, storey_elevation_m), ...] -> one IFC with one storey per plan page. words: the page
    words per plan map (list of lists) for the printed-storey fallback; default: text-<page>.json next to out_path."""
    if not pages:
        raise ValueError("no plan maps")
    fixed = []
    for i, (pm, name, elev) in enumerate(pages):
        ws = words[i] if words and i < len(words) else None
        if ws is None:
            tp = Path(out_path).parent / f"text-{int(pm.get('page', 1))}.json"
            try:
                ws = json.loads(tp.read_text()).get("words") if tp.is_file() else None
            except Exception:  # noqa: BLE001
                ws = None
        fixed.append((_with_text_storey(pm, ws), name, elev))
    pages = fixed
    t0 = time.time()
    doc_id = doc_id or pages[0][0].get("doc_id") or "pdf"
    f, proj, bldg, body = _new_file(doc_id, project_name)
    levels, lv_err = [None] * len(pages), None
    try:  # levels role: storey names / elevations / heights and the sheet-to-sheet alignment
        from pipeline import pdf_levels
        lv = pdf_levels.storeys_from_planmaps([pm for pm, _, _ in pages])
        for pos, e in enumerate(lv or []):
            i = e.get("page_index", pos)
            if isinstance(i, int) and 0 <= i < len(pages):
                levels[i] = e
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        levels, lv_err = [None] * len(pages), f"{type(e).__name__}: {e}"[:200]
    stats = []
    for i, (pm, name, elev) in enumerate(pages):
        try:
            stats.append(_add_storey(f, bldg, body, pm, name, elev, wall_height, doc_id, level=levels[i],
                                     place=len(pages) > 1))
        except ValueError:
            raise
        except Exception:  # noqa: BLE001  level data broke the storey: build it the old way
            if levels[i] is None:
                raise
            stats.append(_add_storey(f, bldg, body, pm, name, elev, wall_height, doc_id))
    for pm, _, _ in pages:
        try:
            _add_grid(f, body, pm, doc_id)
        except Exception as e:  # noqa: BLE001
            lv_err = lv_err or f"grid {type(e).__name__}: {e}"[:200]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:  # what a native export carries: a named header and spatial elements that are whole elements (.ELEMENT.)
        h = f.header.file_name
        h.name, h.author, h.organization = out.name, ("Hologram",), ("Hologram",)
        h.originating_system, h.authorization = "Hologram PDF-to-IFC 1.0", "Hologram"
        for s in f.by_type("IfcSite") + f.by_type("IfcBuilding") + f.by_type("IfcBuildingStorey"):
            if s.CompositionType is None:
                s.CompositionType = "ELEMENT"
    except Exception:  # noqa: BLE001
        pass
    f.write(str(out))
    build.last_stats = {"storeys": stats, "s": round(time.time() - t0, 2), "levels_error": lv_err,
                        "levels": [bool(x) for x in levels]}
    try:  # ifc-native role's enrichment (psets, qtos, material layer sets, types, space boundaries) when present
        from pipeline import ifc_enrich
        ifc_enrich.enrich(out)
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        build.last_stats["enrich_error"] = f"{type(e).__name__}: {e}"[:200]
    return out


def build(planmap: dict, out_path, *, storey_name: str = "Floor 1", storey_elevation: float = 0.0,
          wall_height: float = 2.7, doc_id: str | None = None, project_name: str | None = None,
          words: list | None = None) -> Path:
    """One plan map -> IFC4 file with one storey. Raises ValueError when the plan map has no scale. words: the page
    words ({"text", "bbox_px"}) for the printed-storey fallback (default: text-<page>.json next to out_path)."""
    return build_many([(planmap, storey_name, storey_elevation)], out_path, wall_height=wall_height, doc_id=doc_id,
                      project_name=project_name, words=[words] if words is not None else None)


build.last_stats = {}


def link_planmap(planmap_path, doc_id: str | None = None) -> int:
    """Rewrite plan-map item_ids to the IFC GlobalIds build() gave them (walls, doors, windows, rooms), keeping the
    PDF id in props.pdf_item_id, so engine IFC mode (engine.solvers.data.load_doc) finds each element's page and
    bbox_px on the real PDF page. Idempotent. Returns the number of items relinked."""
    p = Path(planmap_path)
    pm = json.loads(p.read_text())
    doc_id = doc_id or pm.get("doc_id") or "pdf"
    page = int(pm.get("page", 1))
    n = 0
    for it in pm.get("items") or []:
        if it.get("kind") not in ("wall", "door", "window", "room"):
            continue
        pr = it.setdefault("props", {})
        src = pr.get("pdf_item_id") or it["item_id"]
        pr["pdf_item_id"] = src
        it["item_id"] = guid_for(doc_id, src, page)
        if it["kind"] == "room" and "ifc_class" not in pr:
            pr["ifc_class"] = "IfcSpace"
        n += 1
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(pm))
    tmp.replace(p)
    return n


def validate(ifc_path) -> dict:
    """Counts + structural checks: every opening voids a wall, every door/window fills an opening."""
    f = ifcopenshell.open(str(ifc_path))
    c = {k: len(f.by_type(k)) for k in ("IfcBuildingStorey", "IfcWall", "IfcOpeningElement", "IfcDoor", "IfcWindow",
                                         "IfcSpace", "IfcSlab", "IfcRelVoidsElement", "IfcRelFillsElement")}
    bad_void = [o.GlobalId for o in f.by_type("IfcOpeningElement")
                if not o.VoidsElements or not o.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")]
    bad_fill = [e.GlobalId for e in f.by_type("IfcDoor") + f.by_type("IfcWindow") if not e.FillsVoids]
    gids = [e.GlobalId for e in f.by_type("IfcRoot")]
    c.update(schema=f.schema, openings_not_voiding_wall=len(bad_void), fillings_without_opening=len(bad_fill),
             duplicate_guids=len(gids) - len(set(gids)))
    return c


if __name__ == "__main__":
    import sys
    pm = json.loads(Path(sys.argv[1]).read_text())
    out = build(pm, sys.argv[2], storey_name=sys.argv[3] if len(sys.argv) > 3 else "Floor 1")
    print(json.dumps({"ifc": str(out), **build.last_stats, "validate": validate(out)}))
