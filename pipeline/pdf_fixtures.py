"""Stairs, railings, sanitary fixtures, kitchens, lifts and furniture from a vector PDF plan page, and their IFC.

    detect(page, walls, rooms, openings, m_per_pt) -> [{"kind", "polygon": [[x,y],...] page pt, "props": {...}, "conf"}]
    to_ifc(model, storey, body_ctx, fixtures, z0, storey_height_m=None, m_per_pt=None, to_model_xy=None,
           *, doc_id=None, page=1) -> {ifc_class: count}

Kinds: stair | railing | wc | basin | shower | bath | sink | counter | lift | shaft | furniture.
Page coordinates are pdf_vector's: page points, top-left origin, y down. Every symbol is read from its geometry
(sizes in metres through m_per_pt); a printed label (WC, DU, Hissi, ...) only raises confidence, it never creates
a fixture on its own. Precision first: anything ambiguous, overlapping a wall or a door swing is dropped.

IFC: IfcStair (aggregating an IfcStairFlight with stepped solids, risers from the storey height), IfcRailing
(HANDRAIL), IfcSanitaryTerminal (TOILETPAN / WASHHANDBASIN / SHOWER / BATH / SINK), IfcFurniture (kitchen counter,
bed, table), IfcTransportElement (ELEVATOR); each with a type object, a material, a simple extruded body, a
Hologram_Provenance pset and containment in the storey. Plan coordinates follow pdf_to_ifc: x_m = x_pt * m_per_pt,
y_m = -y_pt * m_per_pt (unless a to_model_xy callable is given).
"""
from __future__ import annotations

import math
import re
import uuid

import numpy as np

KINDS = ("stair", "railing", "wc", "basin", "shower", "bath", "sink", "counter", "lift", "shaft", "furniture",
         "equipment")
# printed labels that support (never create) a kind; EN / DE / FI / SV abbreviations seen on plan sheets
LABELS = {
    "stair": re.compile(r"^(?:stairs?|stair\w*|treppe\w*|trh|trp|porras\w*|porrashuone\w*|trapp\w*|upp?|dn|down)$", re.I),
    "lift": re.compile(r"^(?:lift|elev\.?|elevator|aufzug|hissi|hiss|ascenseur)$", re.I),
    "wc": re.compile(r"^(?:wc|w\.c\.|toilet|toilette|wc/?\w*)$", re.I),
    "bath": re.compile(r"^(?:ba|bath|bad|kh|kph|bathroom|badewanne)$", re.I),
    "shower": re.compile(r"^(?:du|sh|shower|dusche|suihku|ph|psh)$", re.I),
    "basin": re.compile(r"^(?:wt|lav|lav\.|basin|waschtisch|pesuallas)$", re.I),
    "sink": re.compile(r"^(?:sink|spüle|tiski\w*|kitchen|kit\.?|kt|keittiö|k)$", re.I),
}
SYMBOLS_BUDGET_S = 20.0  # after the shared layer pass; ARK (60k paths) needs ~12 s under load
FURNITURE_H = {"bed": 0.5, "sofa": 0.8, "chair": 0.45, "armchair": 0.8, "table": 0.75, "desk": 0.75,
               "wardrobe": 2.0, "locker": 1.8, "shelf": 1.8, "cabinet": 0.9}
IFC_MAP = {  # kind -> (class, predefined type, type class, height m, z offset m, material, colour)
    "wc": ("IfcSanitaryTerminal", "TOILETPAN", "IfcSanitaryTerminalType", 0.42, 0.0, "Ceramic", (0.97, 0.97, 0.97)),
    "basin": ("IfcSanitaryTerminal", "WASHHANDBASIN", "IfcSanitaryTerminalType", 0.18, 0.67, "Ceramic", (0.97, 0.97, 0.97)),
    "shower": ("IfcSanitaryTerminal", "SHOWER", "IfcSanitaryTerminalType", 0.05, 0.0, "Ceramic", (0.92, 0.94, 0.96)),
    "bath": ("IfcSanitaryTerminal", "BATH", "IfcSanitaryTerminalType", 0.55, 0.0, "Acrylic", (0.97, 0.97, 0.97)),
    "sink": ("IfcSanitaryTerminal", "SINK", "IfcSanitaryTerminalType", 0.04, 0.88, "Stainless steel", (0.75, 0.76, 0.78)),
    "counter": ("IfcFurniture", "USERDEFINED", "IfcFurnitureType", 0.9, 0.0, "Laminate", (0.83, 0.80, 0.74)),
    "furniture": ("IfcFurniture", "NOTDEFINED", "IfcFurnitureType", 0.75, 0.0, "Wood", (0.70, 0.55, 0.38)),
    "lift": ("IfcTransportElement", "ELEVATOR", "IfcTransportElementType", 2.2, 0.0, "Steel", (0.60, 0.62, 0.66)),
    "railing": ("IfcRailing", "GUARDRAIL", "IfcRailingType", 1.0, 0.0, "Steel", (0.35, 0.36, 0.38)),
    "equipment": ("IfcUnitaryEquipment", "AIRHANDLER", "IfcUnitaryEquipmentType", 2.0, 0.0, "Galvanised steel",
                  (0.72, 0.74, 0.76)),
}
STAIR_COLOUR = (0.78, 0.76, 0.72)
NAMES = {"wc": "WC", "basin": "Wash basin", "shower": "Shower", "bath": "Bath", "sink": "Kitchen sink",
         "counter": "Kitchen counter", "furniture": "Furniture", "lift": "Lift", "railing": "Railing",
         "stair": "Stair", "shaft": "Shaft", "equipment": "Air handling unit"}
NS = uuid.UUID("0b5e1f3a-7c2d-4e8b-a9f6-3d4c5b6a7e81")


# ================================================================ detection
# (filled below)

def detect(page: dict, walls: list, rooms: list, openings: list, m_per_pt: float | None, budget_s: float = 30.0) -> list:
    """Fixtures on a vector plan page (see module doc). Never raises: [] on any error or without a scale.
    Stages run cheapest-first; once budget_s is spent the remaining stages are skipped."""
    try:
        return _detect(page, walls or [], rooms or [], openings or [], float(m_per_pt or 0), budget_s)
    except Exception:  # noqa: BLE001 - detection must never break ingest
        return []


# words printed inside a fixture symbol that name it (a callout bubble or tag carries other text)
FIXTURE_WORD = re.compile(r"^(?:ada|sink|lav|lavatory|basin|vanity|wc|w\.c|toilet|du|sh|shower|bath|tub|bathtub|dw|d/w|"
                          r"range|oven|&oven|cooktop|hob|ref|refrig|fridge|spüle|wt|ba|kh|ph|hissi|lift|elev|elevator)$", re.I)
SINK_WORD = re.compile(r"^(?:sink|lav|lavatory|basin|vanity|spüle|wt|tiskiallas|pesuallas)$", re.I)
BIG_CHAIN_S = 3.0  # time for faces of large connected linework clusters (symbols drawn into counters, walls)
FOOTPRINT_CLOSE_M = 1.6  # wall gaps up to ~3 m (doorways, unlabelled rooms) close into the building footprint
KITCHEN_ROOM = re.compile(r"kitchen|kitch|\bkit\b|keitti|k[üu]che|\bkt\b|\bkk\b|kök|pantry|break ?room|tupak", re.I)
BATH_ROOM = re.compile(r"bath|\bwc\b|toilet|restroom|lav\b|\bkh\b|\bph\b|\bpkh\b|\bkph\b|bad\b|suihku|wash|shower", re.I)


class _Ctx:
    """Page primitives in page pt plus the masks every rule shares (walls, footprint, door swings)."""

    def __init__(self, page, walls, rooms, openings, mpt):
        from shapely.geometry import Polygon, box
        from shapely.ops import unary_union
        from shapely.strtree import STRtree
        self.page, self.mpt = page, mpt
        self.m = lambda v: v * mpt        # pt -> m
        self.pt = lambda v: v / mpt       # m -> pt
        wp = []
        for w in walls:
            try:
                g = Polygon(w["polygon"]).buffer(0)
                if not g.is_empty:
                    wp.append(g)
            except Exception:  # noqa: BLE001
                pass
        self.walls = wp
        self.wall_u = unary_union(wp) if wp else None
        self.wall_tree = STRtree(wp) if wp else None
        rp = []
        self.room_polys = []
        for r in rooms:
            try:
                g = Polygon(r["polygon"]).buffer(0)
                if not g.is_empty and g.area > 0:
                    rp.append(g)
                    self.room_polys.append((g, " ".join(str(r.get(k) or "") for k in ("label", "number"))))
            except Exception:  # noqa: BLE001
                pass
        self.footprint = None
        every = wp + rp
        if every:
            c = self.pt(0.6)
            u = unary_union(every).buffer(c, join_style="mitre").buffer(-c, join_style="mitre")
            if wp:  # rooms without a polygon leave holes: walls closed over a room-sized gap fill them
                try:
                    cw = self.pt(FOOTPRINT_CLOSE_M)
                    uw = unary_union(wp).simplify(self.pt(0.02)).buffer(cw, 2, join_style="mitre").buffer(-cw, 2, join_style="mitre")
                    gs = [g for g in getattr(uw, "geoms", [uw]) if g.geom_type == "Polygon" and not g.is_empty]
                    big_w = max((g.area for g in gs), default=0)
                    # each wall cluster's convex hull: exterior walls broken by wide window bands still enclose
                    u = unary_union([u] + [g.convex_hull for g in gs if g.area >= 0.05 * big_w])
                except Exception:  # noqa: BLE001
                    pass
            parts = [g for g in getattr(u, "geoms", [u]) if g.geom_type == "Polygon" and not g.is_empty]
            if parts:
                big = max(g.area for g in parts)
                self.footprint = unary_union([Polygon(g.exterior) for g in parts if g.area >= 0.05 * big])
                import shapely
                shapely.prepare(self.footprint)
        dz = []
        for o in openings:
            if o.get("kind") != "door":
                continue
            b = (o.get("props") or {}).get("swing_bbox") or o.get("bbox")
            if b:
                dz.append(box(*b))
        self.doors = unary_union(dz) if dz else None
        self.area = None  # the building footprint already keeps title block and legend symbols out
        self.words = [w for w in page.get("words") or [] if w.get("bbox") and w.get("text")]
        self.wc = np.array([[(w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2]
                            for w in self.words if w["text"].strip()]).reshape(-1, 2)
        self._paths()

    def _paths(self):
        """Segments (N,4) with owner path ids; closed shapes with their oriented-rectangle measures."""
        from shapely.geometry import Polygon
        paths = self.page.get("paths") or []
        use = [i for i, p in enumerate(paths) if len(p.get("pts") or ()) >= 2 and not (
            p.get("fill") is not None and p.get("stroke") is None and sum(p["fill"]) / 3 < 0.5)]  # dark poché
        # vectorised segments: consecutive points of each path (+ the closing edge of closed paths)
        pts, pid, nxt_ok = [], [], []
        for i in use:
            p = paths[i]
            q = p["pts"]
            if p.get("closed") and (q[0][0] != q[-1][0] or q[0][1] != q[-1][1]):
                q = list(q) + [q[0]]
            pts.extend(q)
            pid.extend([i] * len(q))
            nxt_ok.extend([not p.get("is_arc")] * (len(q) - 1) + [False])
        shapes = []
        if pts:
            A = np.asarray(pts, float)
            I = np.asarray(pid)
            ok = np.asarray(nxt_ok, bool)
            ok[:-1] &= I[:-1] == I[1:]
            k = np.flatnonzero(ok[:-1])
            S = np.hstack([A[k], A[k + 1]])
            good = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) > 1e-3
            self.seg, self.seg_owner = S[good], I[k][good]
            # per-path bbox for the closed-shape candidates
            starts = np.flatnonzero(np.r_[True, I[1:] != I[:-1]])
            mn_x = np.minimum.reduceat(A[:, 0], starts); mx_x = np.maximum.reduceat(A[:, 0], starts)
            mn_y = np.minimum.reduceat(A[:, 1], starts); mx_y = np.maximum.reduceat(A[:, 1], starts)
            cnt = np.diff(np.r_[starts, len(A)])
            ext = np.maximum(mx_x - mn_x, mx_y - mn_y) * self.mpt
            cand = np.flatnonzero((cnt >= 4) & (ext >= 0.015) & (ext <= 2.6))
            for c in cand:
                i = int(I[starts[c]])
                p = paths[i]
                a = A[starts[c]:starts[c] + cnt[c]]
                closed = bool(p.get("closed"))
                gap = np.hypot(*(a[0] - a[-1]))
                if not closed and gap > 0.5 * min(mx_x[c] - mn_x[c], mx_y[c] - mn_y[c]) + 1e-6:
                    continue
                try:
                    g = Polygon(a).buffer(0)
                except Exception:  # noqa: BLE001
                    continue
                if g.is_empty or g.area <= 0 or g.geom_type != "Polygon":
                    continue
                sh = self._shape(g, i, int(p.get("n_curves") or 0) >= 2, closed)
                if sh:
                    shapes.append(sh)
        else:
            self.seg, self.seg_owner = np.zeros((0, 4)), np.zeros(0, int)
        self._base_shapes = shapes
        self.shapes, self.shape_tree = None, None

    def ensure_shapes(self):
        """Closed shapes (closed paths + faces rebuilt from loose segments), built on first use."""
        if self.shapes is not None:
            return self.shapes
        shapes = list(self._base_shapes)
        try:  # CAD exports often explode symbols into loose 2-point lines: rebuild their closed faces
            shapes += self._chain_shapes(seen={s["i"] for s in shapes})
        except Exception:  # noqa: BLE001
            pass
        self.shapes = shapes
        from shapely.strtree import STRtree
        self.shape_tree = STRtree([s["g"] for s in shapes]) if shapes else None
        return shapes

    def _shape(self, g, sid, n_curved, closed=True):
        r = g.minimum_rotated_rectangle
        c = np.asarray(r.exterior.coords)[:4]
        e1, e2 = c[1] - c[0], c[2] - c[1]
        l1, l2 = float(np.hypot(*e1)), float(np.hypot(*e2))
        if min(l1, l2) <= 0:
            return None
        major = e1 / l1 if l1 >= l2 else e2 / l2
        return {"i": sid, "g": g, "rect": c, "l": max(l1, l2) * self.mpt, "w": min(l1, l2) * self.mpt,
                "fill": g.area / (l1 * l2), "curved": n_curved, "c": np.array(g.centroid.coords[0]),
                "major": major, "closed": closed}

    def _chain_shapes(self, seen=()):
        """Closed faces of clusters of short loose segments (endpoint graph, snapped to 0.25 pt)."""
        import shapely
        from shapely.geometry import LineString, Polygon
        from shapely.ops import polygonize, unary_union
        S, own = self.seg, self.seg_owner
        if not len(S):
            return []
        L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * self.mpt
        dashed = np.array([bool(self.page["paths"][int(o)].get("dashed")) for o in own]) if len(own) else np.zeros(0, bool)
        k = (L <= 2.2) & (L >= 0.002) & ~dashed
        if seen and len(own):  # paths already read as closed shapes are not re-chained
            k &= ~np.isin(own, np.fromiter((i for i in seen if isinstance(i, (int, np.integer))), np.int64))
        if self.wall_u is not None and k.any():
            mid = (S[:, :2] + S[:, 2:]) / 2
            inw = shapely.contains_xy(self.wall_buf(0.01), mid[:, 0], mid[:, 1])
            k &= ~inw
        if self.footprint is not None and k.any():
            mid = (S[:, :2] + S[:, 2:]) / 2
            k &= shapely.contains_xy(self.footprint, mid[:, 0], mid[:, 1])
        ids = np.flatnonzero(k)
        if not len(ids) or len(ids) > 400000:
            return []
        q = 0.25
        a = np.round(S[ids, :2] / q).astype(np.int64)
        b = np.round(S[ids, 2:] / q).astype(np.int64)
        keys = np.vstack([a, b])
        keys = keys[:, 0] * np.int64(1 << 31) + keys[:, 1]
        _, inv = np.unique(keys, return_inverse=True)
        inv = inv.reshape(-1)
        na, nb = inv[:len(ids)], inv[len(ids):]
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        n = int(inv.max()) + 1
        g = coo_matrix((np.ones(len(ids)), (na, nb)), shape=(n, n))
        _, lab = connected_components(g, directed=False)
        try:  # a line ending ON another line (T-junction, e.g. a basin rim closed by the tap stem) joins the two
            lab = self._join_t(S[ids], na, nb, lab, n, q)
        except Exception:  # noqa: BLE001
            pass
        comp = lab[na]
        order = np.argsort(comp, kind="stable")
        bounds = np.flatnonzero(np.diff(comp[order])) + 1
        out = []
        import time
        big_budget = time.time() + BIG_CHAIN_S
        groups = np.split(order, bounds)
        groups.sort(key=len)  # symbol-sized clusters first; big linework clusters only while time allows
        for grp in groups:
            if len(grp) < 4:
                continue
            sg = S[ids[grp]]
            ext = (np.maximum(sg[:, [0, 2]].max(), 0) - sg[:, [0, 2]].min(), sg[:, [1, 3]].max() - sg[:, [1, 3]].min())
            big = len(grp) > 600 or max(ext) * self.mpt > 2.2
            if big:  # a symbol whose outline shares end points with long linework (a sink cut into a counter line)
                if len(grp) > 3000 or max(ext) * self.mpt > 15 or time.time() > big_budget:
                    continue
            elif max(ext) * self.mpt < 0.1:
                continue
            snapped = np.round(sg / q) * q
            lines = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in snapped if s[0] != s[2] or s[1] != s[3]]
            faces = [f for f in polygonize(unary_union(lines)) if f.area * self.mpt ** 2 >= 0.002]
            if big:
                faces = [f for f in faces if 0.1 <= max(f.bounds[2] - f.bounds[0], f.bounds[3] - f.bounds[1]) * self.mpt <= 2.2]
                for j, f in enumerate(faces):
                    nv = len(f.exterior.coords) - 1
                    sh = self._shape(Polygon(f.exterior).simplify(0.05), ("b", int(ids[grp[0]]), j), nv >= 10)
                    if sh:
                        out.append(sh)
                continue
            if not faces:
                continue
            cid = int(ids[grp[0]])
            for j, f in enumerate(faces):
                nv = len(f.exterior.coords) - 1
                sh = self._shape(Polygon(f.exterior).simplify(0.05), ("c", cid, j), nv >= 10)
                if sh:
                    out.append(sh)
            if len(faces) > 1:
                u = unary_union(faces)
                if u.geom_type == "Polygon":
                    sh = self._shape(Polygon(u.exterior), ("c", cid, "u"), len(u.exterior.coords) > 11)
                    if sh:
                        out.append(sh)
        return out

    def _join_t(self, SG, na, nb, lab, n, q, max_ext_m=2.2):
        """Merge endpoint-graph components where a dangling end lies on another component's segment, as long as
        the merged cluster stays symbol-sized (max_ext_m); returns new per-node labels."""
        import shapely
        deg = np.bincount(np.r_[na, nb], minlength=n)
        node_xy = np.zeros((n, 2))
        node_xy[na] = SG[:, :2]
        node_xy[nb] = SG[:, 2:]
        dang = np.flatnonzero(deg == 1)
        if not len(dang) or len(dang) > 200000:
            return lab
        lines = shapely.linestrings(SG.reshape(-1, 2, 2))
        tree = shapely.STRtree(lines)
        pi, si = tree.query(shapely.points(node_xy[dang]), predicate="dwithin", distance=0.6 * q)
        ca, cb = lab[dang[pi]], lab[na[si]]
        k = ca != cb
        ca, cb = ca[k], cb[k]
        if not len(ca):
            return lab
        m = int(lab.max()) + 1
        lo = np.full((m, 2), np.inf); hi = np.full((m, 2), -np.inf)
        np.minimum.at(lo, lab, node_xy); np.maximum.at(hi, lab, node_xy)
        parent = list(range(m))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        lim = self.pt(max_ext_m)
        for a, b in zip(ca.tolist(), cb.tolist()):
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            l2, h2 = np.minimum(lo[ra], lo[rb]), np.maximum(hi[ra], hi[rb])
            if (h2 - l2).max() > lim:
                continue
            parent[rb] = ra
            lo[ra], hi[ra] = l2, h2
        root = np.array([find(x) for x in range(m)])
        return root[lab]

    # ------------------------------------------------------------ masks
    def in_plan(self, g) -> bool:
        if self.footprint is None or not self.footprint.contains(g.centroid):
            return False
        return self.area is None or self.area.contains(g.centroid)

    def wall_buf(self, m):
        """Wall union grown by m metres (cached, prepared)."""
        import shapely
        if self.wall_u is None:
            return None
        if not hasattr(self, "_wb"):
            self._wb = {}
        if m not in self._wb:
            g = self.wall_u.buffer(self.pt(m))
            shapely.prepare(g)
            self._wb[m] = g
        return self._wb[m]

    def wall_overlap(self, g) -> float:
        if self.wall_tree is None or g.area <= 0:
            return 0.0
        a = sum(self.walls[int(k)].intersection(g).area for k in self.wall_tree.query(g))
        return min(1.0, a / g.area)

    def wall_dist(self, g) -> float:
        """Distance in m from g to the nearest wall polygon (inf without walls)."""
        if self.wall_tree is None:
            return math.inf
        k = self.wall_tree.nearest(g)
        return self.walls[int(k)].distance(g) * self.mpt

    def back_normal(self, g, d_m, min_len_m=0.6):
        """Unit vector from g's centre towards the nearest wall or long drawn line within d_m (None if none)."""
        from shapely.geometry import LineString
        from shapely.ops import nearest_points
        c = g.centroid
        best = None
        if self.wall_tree is not None:
            w = self.walls[int(self.wall_tree.nearest(g))]
            if w.distance(g) * self.mpt <= d_m:
                best = (w.distance(g), np.array(nearest_points(w, c)[0].coords[0]))
        if best is not None:  # a wall wins over drawn lines (dimension and grid lines run everywhere)
            v = best[1] - np.array(c.coords[0])
            n = float(np.hypot(*v))
            return v / n if n > 0 else None
        x0, y0, x1, y1 = g.bounds
        d = self.pt(d_m)
        S = self.seg
        L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * self.mpt
        k = np.flatnonzero((L >= min_len_m) & (np.maximum(S[:, 0], S[:, 2]) >= x0 - d) & (np.minimum(S[:, 0], S[:, 2]) <= x1 + d)
                           & (np.maximum(S[:, 1], S[:, 3]) >= y0 - d) & (np.minimum(S[:, 1], S[:, 3]) <= y1 + d))
        inner = g.buffer(-self.pt(0.01))
        for i in k[:300]:
            ln = LineString([(S[i, 0], S[i, 1]), (S[i, 2], S[i, 3])])
            dist = ln.distance(g)
            if dist <= d and not inner.intersects(ln) and (best is None or dist < best[0]):
                best = (dist, np.array(nearest_points(ln, c)[0].coords[0]))
        if best is None:
            return None
        v = best[1] - np.array(c.coords[0])
        n = float(np.hypot(*v))
        return v / n if n > 0 else None

    def near_line(self, g, d_m, min_len_m=0.8) -> bool:
        """A wall, or a drawn line of at least min_len_m, within d_m of g (what a fixture backs onto)."""
        if self.wall_dist(g) <= d_m:
            return True
        x0, y0, x1, y1 = g.bounds
        d = self.pt(d_m)
        S = self.seg
        L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * self.mpt
        k = (L >= min_len_m) & (np.maximum(S[:, 0], S[:, 2]) >= x0 - d) & (np.minimum(S[:, 0], S[:, 2]) <= x1 + d) \
            & (np.maximum(S[:, 1], S[:, 3]) >= y0 - d) & (np.minimum(S[:, 1], S[:, 3]) <= y1 + d)
        if not k.any():
            return False
        from shapely.geometry import LineString
        return any(LineString([(s[0], s[1]), (s[2], s[3])]).distance(g) <= d and
                   not g.buffer(-self.pt(0.01)).intersects(LineString([(s[0], s[1]), (s[2], s[3])]))
                   for s in S[k][:200])

    def spokes(self, g, min_len_m=0.8, tol_m=0.06) -> int:
        """Long lines that end on g's outline and run away from it (roof drain valleys, leader lines, grids)."""
        import shapely
        if not hasattr(self, "_long"):
            S = self.seg
            L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * self.mpt
            paths = self.page.get("paths") or []

            def light(o):  # pale grey floor/tile hatch stopping at a counter edge is no drain valley
                st = paths[int(o)].get("stroke")
                return bool(st) and sum(st[:3]) / 3 > 0.75
            lt = np.array([light(o) for o in self.seg_owner[L >= min_len_m]], bool).reshape(-1)
            self._long = S[L >= min_len_m][~lt] if len(lt) else S[L >= min_len_m]
        S = self._long
        if not len(S):
            return 0
        t = self.pt(tol_m)
        x0, y0, x1, y1 = g.bounds
        n = 0
        b = g.boundary
        grown = g.buffer(t)
        for a, z in ((S[:, :2], S[:, 2:]), (S[:, 2:], S[:, :2])):
            k = np.flatnonzero((a[:, 0] >= x0 - t) & (a[:, 0] <= x1 + t) & (a[:, 1] >= y0 - t) & (a[:, 1] <= y1 + t))
            if not len(k):
                continue
            near = shapely.distance(b, shapely.points(a[k])) <= t
            away = ~shapely.contains_xy(grown, z[k, 0], z[k, 1])
            hit = k[near & away]
            if len(hit):  # a line continuing one of the outline's straight edges (a counter edge cut by a sink) is no spoke
                r = np.asarray(g.minimum_rotated_rectangle.exterior.coords)[:4]
                cont = np.zeros(len(hit), bool)
                for q in range(4):
                    p0, p1 = r[q], r[(q + 1) % 4]
                    e = p1 - p0
                    le = float(np.hypot(*e))
                    if le <= 0:
                        continue
                    nn = np.array([-e[1], e[0]]) / le
                    cont |= (np.abs((a[hit] - p0) @ nn) <= t) & (np.abs((z[hit] - p0) @ nn) <= t)
                n += int((~cont).sum())
        return n

    def has_text(self, g) -> bool:
        """Printed text inside: a callout bubble, tag or legend box, never a fixture symbol."""
        import shapely
        if not len(self.wc):
            return False
        hit = shapely.contains_xy(g, self.wc[:, 0], self.wc[:, 1])
        if hit.any() and not hasattr(self, "_wfix"):
            self._wfix = np.array([bool(FIXTURE_WORD.match(w["text"].strip(" .:,()"))) for w in self.words if w["text"].strip()])
        return bool((hit & ~self._wfix).any()) if hit.any() else False

    def in_door(self, g) -> bool:
        return self.doors is not None and self.doors.contains(g.centroid)

    def labels(self, g, rx, reach_m=0.6) -> list:
        gg = g.buffer(self.pt(reach_m))
        out = []
        for w in self.words:
            b = w["bbox"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if gg.bounds[0] <= cx <= gg.bounds[2] and gg.bounds[1] <= cy <= gg.bounds[3]:
                from shapely.geometry import Point
                if gg.contains(Point(cx, cy)) and rx.match(w["text"].strip(" .:,()")):
                    out.append(w["text"])
        return out

    def room_of(self, g) -> str:
        c = g.centroid
        best = None
        for poly, lab in self.room_polys:
            if poly.contains(c) and (best is None or poly.area < best[0]):
                best = (poly.area, lab)
        return best[1] if best else ""

    def inside(self, outer, fn=None) -> list:
        """Shapes strictly inside outer (shapely polygon), excluding the outer shape itself."""
        if self.shape_tree is None:
            return []
        out = []
        for k in self.shape_tree.query(outer):
            s = self.shapes[int(k)]
            if s["g"].area < outer.area * 0.98 and outer.buffer(self.pt(0.01)).contains(s["g"]) and (fn is None or fn(s)):
                out.append(s)
        return out


def _rect_poly(c, u, n, t0, t1, d0, d1):
    """Rectangle spanned by t in [t0,t1] along u and d in [d0,d1] along n (page pt)."""
    return [[float(u[0] * t + n[0] * d), float(u[1] * t + n[1] * d)] for t, d in ((t0, d0), (t1, d0), (t1, d1), (t0, d1))]


def _poly_list(g):
    return [[round(float(x), 2), round(float(y), 2)] for x, y in list(g.exterior.coords)[:-1]]


# ------------------------------------------------------------ stairs

def _stairs(C, t_end=None):
    """Runs of >= 4 equally spaced, equally long parallel lines, both ends closed by a stringer line or a wall."""
    from shapely.geometry import LineString, Polygon
    S = C.seg
    if not len(S):
        return []
    dx, dy = S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
    L = np.hypot(dx, dy)
    Lm = L * C.mpt
    keep = (Lm >= 0.6) & (Lm <= 3.2)
    idx = np.flatnonzero(keep)
    if not len(idx):
        return []
    th = np.mod(np.arctan2(dy[idx], dx[idx]), math.pi)
    out = []
    used = set()
    q = np.round(np.degrees(th)).astype(int) % 180
    for b in np.unique(q):
        sel = idx[(np.abs(((q - b + 90) % 180) - 90) <= 1)]
        if len(sel) < 4:
            continue
        ang = math.radians(b)
        u = np.array([math.cos(ang), math.sin(ang)])
        n = np.array([-u[1], u[0]])
        P0, P1 = S[sel, :2], S[sel, 2:]
        t0 = np.minimum(P0 @ u, P1 @ u)
        t1 = np.maximum(P0 @ u, P1 @ u)
        d = ((P0 + P1) / 2) @ n
        tol = C.pt(0.06)
        # group by matching extent along u (both ends on a 2*tol grid, offset grids so neighbours meet once)
        groups = {}
        for off in (0.0, 0.5):
            ka = np.floor(t0 / (2 * tol) + off).astype(np.int64)
            kb = np.floor(t1 / (2 * tol) + off).astype(np.int64)
            for k in range(len(sel)):
                groups.setdefault((off, ka[k], kb[k]), []).append(k)
        if t_end is not None and __import__("time").time() > t_end:
            break
        for key, ks in groups.items():
            if len(ks) < 4:
                continue
            ks = sorted(ks, key=lambda k: d[k])
            dd = []
            for k in ks:  # drop duplicates (a line drawn twice)
                if not dd or d[k] - d[dd[-1]] > C.pt(0.02):
                    dd.append(k)
            ds = np.array([d[k] for k in dd])
            gaps = np.diff(ds) * C.mpt
            i = 0
            while i < len(gaps):
                g0 = gaps[i]
                if not 0.2 <= g0 <= 0.36:
                    i += 1
                    continue
                j = i
                while j + 1 < len(gaps) and abs(gaps[j + 1] - g0) <= 0.1 * g0 + 0.01:
                    j += 1
                n_lines = j - i + 2
                if n_lines >= 4:
                    run = dd[i:j + 2]
                    st = _stair_check(C, S, sel, run, u, n, t0, t1, d, float(np.median(gaps[i:j + 1])))
                    if st and not any(Polygon(st["polygon"]).intersects(Polygon(o["polygon"]).buffer(-0.5)) for o in out):
                        out.append(st)
                        used.update(int(sel[k]) for k in run)
                i = j + 1
    return out


_WHY = []


def _why(code):
    """Rejection reason for debugging (kept short; never grows past 200 entries)."""
    if len(_WHY) < 200:
        _WHY.append(code)
    return None


def _stair_check(C, S, sel, run, u, n, t0, t1, d, gap):
    from shapely.geometry import LineString, Polygon
    n_lines = len(run)
    if n_lines > 22:
        return _why(495)
    a, b = float(np.median([t0[k] for k in run])), float(np.median([t1[k] for k in run]))
    d0, d1 = float(d[run[0]]), float(d[run[-1]])
    width = (b - a) * C.mpt
    poly = Polygon(_rect_poly(None, u, n, a, b, d0, d1))
    if not poly.is_valid or poly.area <= 0 or not C.in_plan(poly) or C.wall_overlap(poly) > 0.08 or C.in_door(poly):
        return _why(501)
    # both ends closed: a line along the run (stringer, wall face) or a wall polygon at each end
    span = d1 - d0
    Sx = C.seg
    dx, dy = Sx[:, 2] - Sx[:, 0], Sx[:, 3] - Sx[:, 1]
    Ls = np.hypot(dx, dy) + 1e-9
    par_n = np.abs((dx * n[0] + dy * n[1]) / Ls) > 0.995       # along the run
    tm = ((Sx[:, :2] + Sx[:, 2:]) / 2) @ u
    s0 = np.minimum(Sx[:, :2] @ n, Sx[:, 2:] @ n)
    s1 = np.maximum(Sx[:, :2] @ n, Sx[:, 2:] @ n)
    cover = np.clip(np.minimum(s1, d1) - np.maximum(s0, d0), 0, None)
    ends = []
    tol = C.pt(0.05)
    for t_end in (a, b):
        k = par_n & (np.abs(tm - t_end) <= tol)
        line_ok = bool(k.any() and cover[k].max() >= 0.7 * span)
        if not line_ok:  # sum of pieces (a stringer drawn in parts)
            line_ok = bool(k.any() and cover[k].sum() >= 0.8 * span)
        edge = LineString([tuple(u * t_end + n * d0), tuple(u * t_end + n * d1)])
        wall_ok = C.wall_u is not None and C.wall_buf(0.06).intersection(edge).length >= 0.7 * edge.length
        if not (line_ok or wall_ok):
            return _why(522)
        ends.append("wall" if wall_ok else "line")
    # not a tile grid / hatch: few lines cross the run, none of its other lines sit between the treads
    inner = poly.buffer(-C.pt(0.04))
    if inner.is_empty:
        return _why(527)
    ix0, iy0, ix1, iy1 = inner.bounds
    bb = (np.maximum(Sx[:, 0], Sx[:, 2]) >= ix0) & (np.minimum(Sx[:, 0], Sx[:, 2]) <= ix1) & \
         (np.maximum(Sx[:, 1], Sx[:, 3]) >= iy0) & (np.minimum(Sx[:, 1], Sx[:, 3]) <= iy1)
    run_ids = {int(sel[k]) for k in run}
    cross, stray, cross_t = 0, 0, []
    run_d = np.array([d[k] for k in run])
    for k in np.flatnonzero(bb)[:3000]:
        if int(k) in run_ids:
            continue
        ln = LineString([tuple(Sx[k, :2]), tuple(Sx[k, 2:])])
        if not ln.intersects(inner):
            continue
        cl = ln.intersection(inner).length
        if cl < C.pt(0.1):
            continue
        if par_n[k]:
            cross += 1
            cross_t.append(float(tm[k]))
        elif abs((dx[k] * u[0] + dy[k] * u[1]) / Ls[k]) > 0.995 and cl > 0.5 * (b - a):
            dk = float(((Sx[k, :2] + Sx[k, 2:]) / 2) @ n)
            if np.min(np.abs(run_d - dk)) > C.pt(0.03):  # a tread line drawn twice is not a stray line
                stray += 1
    # a tile/paving grid crosses the run with evenly spaced lines; handrails, a walk line, a flight divider and
    # dimension lines do not
    ct = np.unique(np.round(np.array(cross_t) / C.pt(0.02)))
    grid = False
    if len(ct) >= 4:
        dg = np.diff(np.sort(ct)) * 0.02
        grid = bool(np.median(dg) <= 2.5 * gap and np.std(dg) <= 0.25 * np.median(dg))
    if grid or len(ct) > 10 or stray > 1:
        return _why(547)
    # walk line + arrow (optional): a line along the run near the middle, arrowhead at the "up" end
    tmid = (a + b) / 2
    walk = par_n & (np.abs(tm - tmid) <= 0.3 * (b - a)) & (cover >= 0.5 * span)
    direction, dlabel, evid = None, None, [f"{n_lines} treads lines", f"ends: {'/'.join(ends)}"]
    if walk.any():
        evid.append("walk line")
        kk = np.flatnonzero(walk)
        lo = min(s0[k] for k in kk)
        hi = max(s1[k] for k in kk)
        heads = {"lo": 0, "hi": 0}
        short = (Ls * C.mpt >= 0.04) & (Ls * C.mpt <= 0.45) & ~par_n
        for end_d, key in ((lo, "lo"), (hi, "hi")):
            tip = u * tmid + n * end_d
            e0 = np.hypot(Sx[:, 0] - tip[0], Sx[:, 1] - tip[1]) <= C.pt(0.03)
            e1 = np.hypot(Sx[:, 2] - tip[0], Sx[:, 3] - tip[1]) <= C.pt(0.03)
            heads[key] = int((short & (e0 | e1)).sum())
        up_words = C.labels(poly, re.compile(r"^(?:up|ylös|upp|auf|hoch)$", re.I), 0.4)
        dn_words = C.labels(poly, re.compile(r"^(?:dn|down|alas|ned|ab)$", re.I), 0.4)
        if heads["hi"] >= 2 > heads["lo"]:
            sgn = 1
        elif heads["lo"] >= 2 > heads["hi"]:
            sgn = -1
        else:
            sgn = 0
        if sgn and dn_words and not up_words:
            sgn = -sgn
        if sgn:
            direction = [round(float(n[0] * sgn), 4), round(float(n[1] * sgn), 4)]
            dlabel = "up" if not dn_words else "down-arrow"
            evid.append("arrow")
    lab = C.labels(poly, LABELS["stair"], 1.5)
    if lab:
        evid.append("label " + lab[0])
    conf = 0.55 + 0.05 * min(n_lines - 4, 4) + (0.1 if walk.any() else 0) + (0.1 if lab else 0) + \
        (0.05 if "wall" in ends else 0)
    printed = _printed_rise_going(C, poly)
    return {"kind": "stair", "polygon": _poly_list(poly), "conf": round(min(conf, 0.95), 2),
            "props": {**printed, "treads": n_lines - 1, "nosing_lines": n_lines, "tread_depth_m": round(gap, 3),
                      "width_m": round(width, 3), "run_m": round((d1 - d0) * C.mpt, 3), "direction": direction,
                      "direction_label": dlabel, "ends": ends, "axis_u": [round(float(u[0]), 4), round(float(u[1]), 4)],
                      "evidence": ", ".join(evid)}}


RISE_KEY = re.compile(r"^(?:N|R|nousu|riser?|steigung|stigning|h)$", re.I)     # FI nousu / EN riser / DE Steigung
GOING_KEY = re.compile(r"^(?:E|G|T|etenemä|going|tread|auftritt|steg)$", re.I)  # FI etenemä / EN going / DE Auftritt


def _printed_rise_going(C, poly, reach_m=2.0):
    """Riser and going printed beside a stair run ("N 170 E 280": Finnish nousu / etenemä, mm; also R/G, T),
    nearest pair to the run. {} when none is printed."""
    import math
    from shapely.geometry import Point
    g = poly.buffer(C.pt(reach_m))
    ws = C.words
    c = poly.centroid
    best = {}
    for k in range(len(ws) - 1):
        key, val = ws[k]["text"].strip(" .:=,"), ws[k + 1]["text"].strip(" .:=,").replace(",", ".")
        if not re.fullmatch(r"\d{2,3}(?:\.\d+)?", val):
            continue
        b0, b1 = ws[k]["bbox"], ws[k + 1]["bbox"]
        cx, cy = (b1[0] + b1[2]) / 2, (b1[1] + b1[3]) / 2
        if not g.contains(Point(cx, cy)) or math.hypot((b0[0] + b0[2]) / 2 - cx, (b0[1] + b0[3]) / 2 - cy) > C.pt(0.8):
            continue
        v = float(val) / 1000.0
        d = c.distance(Point(cx, cy))
        if RISE_KEY.match(key) and 0.1 <= v <= 0.22 and d < best.get("_dr", 1e18):
            best["riser_printed_m"], best["_dr"] = round(v, 4), d
            best["riser_text"] = f"{ws[k]['text']} {ws[k + 1]['text']}"
        elif GOING_KEY.match(key) and 0.2 <= v <= 0.4 and d < best.get("_dg", 1e18):
            best["going_printed_m"], best["_dg"] = round(v, 4), d
            best["going_text"] = f"{ws[k]['text']} {ws[k + 1]['text']}"
    return {k: v for k, v in best.items() if not k.startswith("_")}


def _railings(C, stairs):
    """A guard rail on each stair side that is not against a wall."""
    from shapely.geometry import LineString
    out = []
    for si, st in enumerate(stairs):
        p = st["polygon"]
        u = st["props"]["axis_u"]
        # the two sides along the run are the edges perpendicular to u (tread direction)
        for e0, e1 in ((p[1], p[2]), (p[3], p[0])):
            ln = LineString([e0, e1])
            if ln.length * C.mpt < 0.6:
                continue
            if C.wall_u is not None and C.wall_buf(0.12).intersection(ln).length > 0.5 * ln.length:
                continue
            g = ln.buffer(C.pt(0.025), cap_style="flat")
            out.append({"kind": "railing", "polygon": _poly_list(g), "conf": round(st["conf"] - 0.1, 2),
                        "props": {"stair": si, "height_m": 1.0, "length_m": round(ln.length * C.mpt, 3),
                                  "evidence": "open side of a detected stair"}})
    return out


# ------------------------------------------------------------ X rectangles: lifts, shafts

def _x_rects(C):
    """Two equal diagonals bisecting each other span a rectangle; its sides must be drawn or walls."""
    from shapely.geometry import LineString, Polygon
    S = C.seg
    if not len(S):
        return []
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * C.mpt
    k = np.flatnonzero((L >= 0.8) & (L <= 5.0))
    if len(k) < 2:
        return []
    mid = (S[k, :2] + S[k, 2:]) / 2
    from scipy.spatial import cKDTree
    tree = cKDTree(mid)
    out = []
    seen = []
    for a, b in tree.query_pairs(C.pt(0.05)):
        i, j = k[a], k[b]
        if abs(L[i] - L[j]) > 0.04 * L[i]:
            continue
        v1 = S[i, 2:] - S[i, :2]
        v2 = S[j, 2:] - S[j, :2]
        cosang = abs(v1 @ v2) / (np.hypot(*v1) * np.hypot(*v2))
        if cosang > 0.94:  # nearly parallel: not an X
            continue
        corners = [S[i, :2], S[j, :2], S[i, 2:], S[j, 2:]]
        g = Polygon(corners)
        if not g.is_valid or g.area <= 0:
            continue
        sides = [np.hypot(*(corners[(q + 1) % 4] - corners[q])) * C.mpt for q in range(4)]
        w, l = min(sides), max(sides)
        if w < 0.6 or l > 3.5:
            continue
        if any(g.intersection(s).area > 0.5 * g.area for s in seen):
            continue
        # each side drawn (a line along it) or a wall face
        ok = 0
        for q in range(4):
            e = LineString([tuple(corners[q]), tuple(corners[(q + 1) % 4])])
            if C.wall_u is not None and C.wall_buf(0.05).intersection(e).length >= 0.7 * e.length:
                ok += 1
                continue
            ex0, ey0, ex1, ey1 = e.buffer(C.pt(0.03)).bounds
            cand = np.flatnonzero((np.minimum(S[:, 0], S[:, 2]) >= ex0) & (np.maximum(S[:, 0], S[:, 2]) <= ex1) &
                                  (np.minimum(S[:, 1], S[:, 3]) >= ey0) & (np.maximum(S[:, 1], S[:, 3]) <= ey1))
            if sum(LineString([tuple(S[c, :2]), tuple(S[c, 2:])]).length for c in cand) >= 0.7 * e.length:
                ok += 1
        if ok < 4:
            continue
        if not C.in_plan(g) or C.wall_overlap(g) > 0.15 or C.in_door(g):
            continue
        walls_around = sum(1 for q in range(4) if C.wall_u is not None and C.wall_buf(0.08).intersection(
            LineString([tuple(corners[q]), tuple(corners[(q + 1) % 4])])).length >= 0.5 * sides[q] / C.mpt)
        lab = C.labels(g, LABELS["lift"], 1.0)
        kind = "lift" if (lab and w >= 0.9) else "shaft"
        if kind == "shaft" and walls_around < 2:
            continue  # a free-standing X box (column, crate, "not in contract") is not a shaft
        seen.append(g)
        out.append({"kind": kind, "polygon": _poly_list(g), "conf": 0.8 if lab else 0.6,
                    "props": {"size_m": [round(l, 2), round(w, 2)], "walls_around": walls_around,
                              "evidence": "rectangle with an X" + (f", label {lab[0]}" if lab else "")}})
    return out


# ------------------------------------------------------------ sanitary, kitchen, beds

def _ok_symbol(C, s, max_wall=0.1):
    g = s["g"]
    return C.in_plan(g) and C.wall_overlap(g) <= max_wall and not C.in_door(g) and not C.has_text(g)


def _sanitary(C):
    from shapely.geometry import Polygon
    out = []
    taken = set()
    shapes = C.ensure_shapes()
    drains = [s for s in shapes if s["curved"] and 0.02 <= s["l"] <= 0.12 and s["l"] / s["w"] < 1.2 and s["fill"] > 0.7]
    from shapely.geometry import Point

    def drain_in(g, near=None):
        for s in drains:
            if g.contains(Point(s["c"])) and (near is None or np.hypot(*(s["c"] - near)) * C.mpt <= 0.25):
                return True
        return False

    def diagonals(rect):
        """Both diagonals of a rectangle drawn (a shower tray cross)."""
        Sx = C.seg
        tol = C.pt(0.04)
        hit = 0
        for p, q in ((rect[0], rect[2]), (rect[1], rect[3])):
            m1 = (np.hypot(Sx[:, 0] - p[0], Sx[:, 1] - p[1]) <= tol) & (np.hypot(Sx[:, 2] - q[0], Sx[:, 3] - q[1]) <= tol)
            m2 = (np.hypot(Sx[:, 0] - q[0], Sx[:, 1] - q[1]) <= tol) & (np.hypot(Sx[:, 2] - p[0], Sx[:, 3] - p[1]) <= tol)
            hit += bool((m1 | m2).any())
        return hit == 2

    # WC: oval bowl + cistern rectangle behind it, on the bowl's axis
    tanks = [s for s in shapes if 0.1 <= s["w"] <= 0.3 and 0.3 <= s["l"] <= 0.62 and s["fill"] >= 0.85]
    for s in shapes:
        if not (s["curved"] and 0.28 <= s["w"] <= 0.5 and 0.35 <= s["l"] <= 0.68 and 1.05 <= s["l"] / s["w"] <= 1.9
                and 0.68 <= s["fill"] <= 0.95):
            continue
        if not _ok_symbol(C, s):
            continue
        ax = s["major"]
        for t in tanks:
            if t["i"] == s["i"]:
                continue
            v = (t["c"] - s["c"]) * C.mpt
            along, perp = abs(v @ ax), abs(v @ np.array([-ax[1], ax[0]]))
            if perp > 0.3 * s["w"] or not (0.35 * s["l"] <= along <= 0.5 * s["l"] + 0.35):
                continue
            if abs(t["major"] @ ax) > 0.3:
                continue
            g = s["g"].union(t["g"]).convex_hull
            ext = max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) * C.mpt
            if not 0.5 <= ext <= 0.95 or C.wall_overlap(g) > 0.1:
                continue
            # the cistern is the part against the wall; a bar or a box on the open side is not one
            dt, ds = C.wall_dist(t["g"]), C.wall_dist(s["g"])
            if not (dt <= 0.3 and dt < ds - 0.05):
                continue
            back = True
            lab = C.labels(g, LABELS["wc"], 1.2)
            out.append({"kind": "wc", "polygon": _poly_list(g), "conf": round(0.65 + 0.15 * back + 0.1 * bool(lab), 2),
                        "props": {"size_m": [round(s["w"], 2), round(float(along + t["w"] / 2 + s["l"] / 2), 2)],
                                  "evidence": "oval bowl + cistern" + (", against wall" if back else "") +
                                  (f", label {lab[0]}" if lab else "")}})
            taken.update((s["i"], t["i"]))
            break

    for s in shapes:
        if s["i"] in taken or not _ok_symbol(C, s):
            continue
        w, l, g = s["w"], s["l"], s["g"]
        # bath: ~0.7 x 1.7 rectangle with a rounded inner outline
        if 0.6 <= w <= 0.95 and 1.35 <= l <= 2.05 and s["fill"] >= 0.92:
            inner = C.inside(g, lambda q: q["curved"] and 0.4 <= q["g"].area / g.area <= 0.92)
            if inner:
                lab = C.labels(g, LABELS["bath"], 1.2)
                out.append({"kind": "bath", "polygon": _poly_list(g), "conf": round(0.75 + 0.1 * bool(lab), 2),
                            "props": {"size_m": [round(l, 2), round(w, 2)],
                                      "evidence": "rectangle + rounded inner outline" + (f", label {lab[0]}" if lab else "")}})
                taken.add(s["i"])
                taken.update(q["i"] for q in inner)
                continue
        # shower: ~0.9 m square tray with a diagonal cross or a drain
        if 0.7 <= w <= 1.25 and 0.7 <= l <= 1.6 and s["fill"] >= 0.95 and not s["curved"]:
            cross = diagonals(s["rect"])
            drain = drain_in(g, s["c"])
            if cross or drain:
                lab = C.labels(g, LABELS["shower"], 1.0)
                out.append({"kind": "shower", "polygon": _poly_list(g), "conf": round(0.7 + 0.1 * (cross and drain) + 0.1 * bool(lab), 2),
                            "props": {"size_m": [round(l, 2), round(w, 2)],
                                      "evidence": ("diagonal cross" if cross else "drain") + (f", label {lab[0]}" if lab else "")}})
                taken.add(s["i"])
                continue
    # oval with a seat / bowl opening inside it, backed by a wall: WC when the oval points away from the wall,
    # wash basin when it runs along the wall
    for s in shapes:
        if s["i"] in taken or not s["curved"] or not 0.68 <= s["fill"] <= 0.95 or not _ok_symbol(C, s):
            continue
        w, l, g = s["w"], s["l"], s["g"]
        if not (0.28 <= w <= 0.6 and 0.33 <= l <= 0.72):
            continue
        inner = C.inside(g, lambda q: q["curved"] and 0.15 <= q["g"].area / g.area <= 0.75 and q["i"] not in taken)
        if not inner:
            continue
        nb = C.back_normal(g, 0.35)
        if nb is None:
            continue
        along = abs(float(nb @ s["major"]))
        if along >= 0.8 and l / w >= 1.15 and 0.4 <= l <= 0.72:
            kind = "wc"
        elif along <= 0.5 and l / w >= 1.15 and l <= 0.7:
            kind = "basin"  # wider than deep, along the wall (a round/square symbol is as often a drain)
        else:
            continue
        room = C.room_of(g)
        if kind == "basin" and KITCHEN_ROOM.search(room) and not BATH_ROOM.search(room):
            kind = "sink"
        lab = C.labels(g, LABELS[kind], 1.2)
        out.append({"kind": kind, "polygon": _poly_list(g), "conf": round(0.7 + 0.1 * bool(lab), 2),
                    "props": {"size_m": [round(l, 2), round(w, 2)], "room": room or None,
                              "evidence": ("oval bowl + seat, pointing away from the wall" if kind == "wc" else
                                           "oval + inner bowl along a wall") + (f", label {lab[0]}" if lab else "")}})
        taken.add(s["i"])
        taken.update(q["i"] for q in inner)
    # basins and sinks: an outer outline holding one or two bowls (or a drain), backed by a wall
    for s in shapes:
        if s["i"] in taken or not _ok_symbol(C, s):
            continue
        w, l, g = s["w"], s["l"], s["g"]
        if not (0.3 <= w <= 0.65 and 0.35 <= l <= 1.05 and s["fill"] >= 0.72):
            continue
        room = C.room_of(g)
        # a square-cornered bowl only where the room or a printed word says sink / wash basin (cabinets, boxes and
        # window frames are rectangles in rectangles too)
        sq_ok = bool((KITCHEN_ROOM.search(room) or BATH_ROOM.search(room)
                      or C.labels(g, SINK_WORD, 0.3)) and s["fill"] >= 0.95)

        def bowl_ok(q):
            if not (0.12 <= q["g"].area / g.area <= 0.93 and q["l"] >= 0.2):
                return False
            if q["curved"]:
                return True
            return sq_ok and q["fill"] >= 0.95 and q["w"] >= 0.2 and np.hypot(*(q["c"] - s["c"])) * C.mpt <= 0.15
        bowls = C.inside(g, bowl_ok)
        bowls = [q for q in bowls if q["i"] not in taken]
        top = [q for q in bowls if not any(o is not q and o["g"].contains(q["g"]) for o in bowls)]
        drain = drain_in(g)
        sq_bowl = bool(top) and not any(q["curved"] for q in top)
        if not top or not (drain or len(top) >= 1 and s["curved"] or len(top) == 2 or sq_bowl):
            continue
        if len(top) != 2 and l / w < 1.1:
            continue  # square/round with a ring inside: a floor or roof drain as often as a basin
        if not C.near_line(g, 0.25):
            continue
        if C.wall_dist(g) > 0.35 and not (KITCHEN_ROOM.search(room) or BATH_ROOM.search(room)
                                          or C.labels(g, SINK_WORD, 0.6)):
            continue  # away from walls (island, counter run) only where the room or a word says kitchen / bath
        if len(top) == 2 or (KITCHEN_ROOM.search(room) and not BATH_ROOM.search(room)):
            kind = "sink"
        elif BATH_ROOM.search(room) or s["curved"]:
            kind = "basin"
        elif l >= 0.5 and s["fill"] >= 0.95:
            kind = "sink"
        else:
            kind = "basin"
        if kind == "basin" and l > 0.8:
            continue
        lab = C.labels(g, LABELS[kind], 1.0)
        out.append({"kind": kind, "polygon": _poly_list(g), "conf": round(0.65 + 0.1 * drain + 0.1 * bool(lab), 2),
                    "props": {"size_m": [round(l, 2), round(w, 2)], "bowls": len(top), "room": room or None,
                              "evidence": f"outline + {len(top)} bowl(s)" + (", drain" if drain else "") +
                              (f", label {lab[0]}" if lab else "")}})
        taken.add(s["i"])
        taken.update(q["i"] for q in bowls)
    out += _hand_basins(C, shapes, out, taken)
    return out


def _hand_basins(C, shapes, found, taken):
    """Small hand-rinse basin (0.3-0.5 x 0.2-0.35 m box holding a bowl) on a wall, in a bath-labelled room or
    within 2 m of a WC already found (WC cubicles at 1:100 rarely carry a room polygon)."""
    from shapely.geometry import Polygon
    wcs = [np.array(Polygon(f["polygon"]).centroid.coords[0]) for f in found if f["kind"] == "wc"]
    out = []
    for s in shapes:
        if s["i"] in taken or not (0.2 <= s["w"] <= 0.35 and 0.3 <= s["l"] <= 0.5 and s["fill"] >= 0.9):
            continue
        g = s["g"]
        if not _ok_symbol(C, s) or C.wall_dist(g) > 0.1:
            continue
        room = C.room_of(g)
        near_wc = any(np.hypot(*(c - s["c"])) * C.mpt <= 2.0 for c in wcs)
        if not (near_wc or BATH_ROOM.search(room)):
            continue
        nb = C.back_normal(g, 0.1)
        if nb is None or abs(float(nb @ s["major"])) > 0.3:
            continue  # the long side runs along the wall
        bowls = C.inside(g, lambda q: 0.05 <= q["g"].area / g.area <= 0.65 and q["l"] >= 0.06)
        if not bowls:
            continue
        lab = C.labels(g, LABELS["basin"], 0.8)
        out.append({"kind": "basin", "polygon": _poly_list(g), "conf": round(0.6 + 0.1 * bool(lab), 2),
                    "props": {"size_m": [round(s["l"], 2), round(s["w"], 2)], "room": room or None,
                              "evidence": "small box + bowl on a wall, " + ("next to a WC" if near_wc else "wet room") +
                              (f", label {lab[0]}" if lab else "")}})
        taken.add(s["i"])
        taken.update(q["i"] for q in bowls)
    return out


def _cooktops(C):
    """Hob: 3-4 round burner rings (0.1-0.3 m) packed in a <= 0.8 m square, near a wall. Internal anchor only."""
    from shapely.geometry import MultiPoint
    rings = [s for s in C.ensure_shapes() if s["curved"] and 0.1 <= s["l"] <= 0.32 and s["l"] / s["w"] <= 1.15
             and s["fill"] >= 0.7 and C.in_plan(s["g"]) and not C.in_door(s["g"])]
    if len(rings) < 3:
        return []
    from scipy.spatial import cKDTree
    P = np.array([s["c"] for s in rings])
    tree = cKDTree(P)
    out, used = [], set()
    for i in range(len(rings)):
        if i in used:
            continue
        nb = [j for j in tree.query_ball_point(P[i], C.pt(0.6)) if j not in used]
        if not 3 <= len(nb) <= 6:
            continue
        ext = (P[nb].max(0) - P[nb].min(0)) * C.mpt
        if ext.max() > 0.6 or ext.min() < 0.12:
            continue  # burners sit in a 2 x 2 (or 2 + 1) grid, never in a row
        g = MultiPoint([tuple(p) for p in P[nb]]).convex_hull.buffer(C.pt(0.12), join_style="mitre")
        if C.wall_dist(g) > 0.5 or C.has_text(g):
            continue
        used.update(nb)
        out.append({"kind": "cooktop", "polygon": _poly_list(g), "conf": 0.6, "props": {"rings": len(nb)}})
    return out


def _counters(C, fixtures):
    """Kitchen counter: the strip between the wall a sink or hob backs onto and the counter edge line ~0.6 m out."""
    from shapely.geometry import LineString, Polygon
    out = []
    S = C.seg
    if not len(S) or C.wall_u is None:
        return out
    for fx in fixtures:
        if fx["kind"] not in ("sink", "cooktop"):
            continue
        g = Polygon(fx["polygon"])
        c = np.array(g.centroid.coords[0])
        k = C.wall_tree.nearest(g)
        wall = C.walls[int(k)]
        if wall.distance(g) * C.mpt > 0.3:
            continue
        # wall face direction: the wall outline edge nearest the anchor (walls are often long L/U polygons)
        from shapely.ops import nearest_points
        face = np.array(nearest_points(wall.exterior, g.centroid)[0].coords[0])
        ring = np.asarray(wall.exterior.coords)
        ev = ring[1:] - ring[:-1]
        el = np.hypot(ev[:, 0], ev[:, 1]) + 1e-9
        tt = np.clip(np.einsum("ij,ij->i", face - ring[:-1], ev) / el ** 2, 0, 1)
        dd = np.hypot(*(ring[:-1] + ev * tt[:, None] - face).T)
        cand_e = np.flatnonzero(dd <= dd.min() + 0.5)
        ke = cand_e[np.argmax(el[cand_e])]
        u = ev[ke] / el[ke]
        n = np.array([-u[1], u[0]])
        if (c - face) @ n < 0:
            n = -n
        dx, dy = S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
        Ls = np.hypot(dx, dy) + 1e-9
        par = np.abs((dx * u[0] + dy * u[1]) / Ls) > 0.995
        off = (((S[:, :2] + S[:, 2:]) / 2) - face) @ n * C.mpt
        t0 = np.minimum((S[:, :2] - face) @ u, (S[:, 2:] - face) @ u)
        t1 = np.maximum((S[:, :2] - face) @ u, (S[:, 2:] - face) @ u)
        tc = (c - face) @ u
        cand = np.flatnonzero(par & (off >= 0.5) & (off <= 0.75) & (t0 <= tc) & (t1 >= tc) & (Ls * C.mpt >= 0.9))
        if len(cand):
            best = cand[np.argmin(np.abs(off[cand] - 0.6))]
            a, b, ob = max(t0[best], tc - C.pt(4.0)), min(t1[best], tc + C.pt(4.0)), off[best]
        else:  # the edge line broken by the symbol drawn over it: collinear pieces on both sides of the anchor
            near = np.flatnonzero(par & (off >= 0.5) & (off <= 0.75) & (Ls * C.mpt >= 0.25)
                                  & (t1 >= tc - C.pt(1.2)) & (t0 <= tc + C.pt(1.2)))
            if not len(near):
                continue
            ob = float(np.median(off[near]))
            near = near[np.abs(off[near] - ob) <= 0.02]
            left, right = near[t1[near] <= tc + C.pt(0.05)], near[t0[near] >= tc - C.pt(0.05)]
            if not len(left) or not len(right):
                continue
            a, b = max(t0[near].min(), tc - C.pt(4.0)), min(t1[near].max(), tc + C.pt(4.0))
            if (b - a) * C.mpt < 0.9:
                continue
        off_b = ob
        dd = off_b / C.mpt
        poly = Polygon([tuple(face + u * a), tuple(face + u * b), tuple(face + u * b + n * dd), tuple(face + u * a + n * dd)])
        if not poly.is_valid or C.wall_overlap(poly) > 0.1 or not C.in_plan(poly):
            continue
        if any(Polygon(o["polygon"]).intersection(poly).area > 0.5 * poly.area for o in out):
            continue
        out.append({"kind": "counter", "polygon": _poly_list(poly), "conf": 0.6,
                    "props": {"size_m": [round((b - a) * C.mpt, 2), round(float(off_b), 2)],
                              "evidence": f"counter edge line ~0.6 m off the wall behind a {'hob' if fx['kind'] == 'cooktop' else 'sink'}"}})
    return out


def _beds(C):
    out = []
    for s in C.ensure_shapes():
        if not (0.85 <= s["w"] <= 2.05 and 1.85 <= s["l"] <= 2.3 and s["fill"] >= 0.93) or not _ok_symbol(C, s):
            continue
        g = s["g"]
        pillows = C.inside(g, lambda q: 0.25 <= q["w"] <= 0.55 and 0.4 <= q["l"] <= 0.85 and q["g"].area < 0.2 * g.area)
        if not 1 <= len(pillows) <= 2:
            continue
        ax = s["major"]
        ends = [((q["c"] - s["c"]) @ ax) * C.mpt for q in pillows]
        if not all(abs(e) >= 0.5 * s["l"] - 0.45 for e in ends) or len({e > 0 for e in ends}) != 1:
            continue
        head_pt = s["c"] + ax * (np.sign(ends[0]) * s["l"] / 2 / C.mpt)
        from shapely.geometry import Point
        if not C.near_line(Point(head_pt).buffer(C.pt(0.1)), 0.3):
            continue
        out.append({"kind": "furniture", "polygon": _poly_list(g), "conf": 0.7,
                    "props": {"type": "bed", "size_m": [round(s["l"], 2), round(s["w"], 2)],
                              "evidence": f"bed outline + {len(pillows)} pillow(s), head against a wall"}})
    return out


LOCKER = re.compile(r"locker|kaapi|kaappi|skåp|spind|garderob", re.I)


def _lockers(C, reach_m=3.0, same_m=6.0):
    """Locker banks: plain closed rectangles 0.3-0.8 m deep, 0.8-6 m long, near a printed LOCKER(S) word (EN/FI/SV/DE);
    rectangles of the same size within same_m of a seed count too (the word is printed once per group of banks)."""
    words = [w for w in C.words if LOCKER.search(w["text"])]
    if not words:
        return []
    wc = np.array([[(w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2] for w in words])
    cand = [s for s in C.ensure_shapes() if 0.3 <= s["w"] <= 0.8 and 0.8 <= s["l"] <= 6.0 and s["fill"] >= 0.9
            and not s["curved"] and C.in_plan(s["g"]) and C.wall_overlap(s["g"]) <= 0.1 and not C.in_door(s["g"])]
    # (the LOCKERS label is often printed inside the bank, so no has_text test here)
    if not cand:
        return []
    dist = lambda s: float(np.min(np.linalg.norm(wc - s["c"], axis=1))) * C.mpt  # noqa: E731
    seeds = [s for s in cand if dist(s) <= reach_m]
    keep = list(seeds)
    for s in cand:
        if s in keep or dist(s) > same_m:
            continue
        if any(abs(s["w"] - q["w"]) <= 0.05 and abs(s["l"] - q["l"]) <= 0.1 for q in seeds):
            keep.append(s)
    return [{"kind": "furniture", "polygon": _poly_list(s["g"]), "conf": 0.6,
             "props": {"type": "locker", "size_m": [round(s["l"], 2), round(s["w"], 2)],
                       "evidence": "bank outline near a printed LOCKERS label"}} for s in keep]


# printed equipment tags (any language): air handling units, heat recovery, fans, make-up air, rooftop / fan coil
EQUIP = re.compile(r"^(?:AHU|AHK|IV-?kone\w*|ilmanvaihtokone\w*|LTO|FAN|PUHALLIN\w*|MUA?|RTU|FCU|RLT\w*|"
                   r"L[üu]ftungsger[äa]t\w*|aggregat\w*|ventilationsaggregat\w*|TK\d*|IV\d+)$", re.I)
HEIGHT_TXT = re.compile(r"^h\s*=\s*(\d{3,4})$", re.I)


def _equipment(C, page, reach_m=12.5):
    """Plant: the smallest closed rectangle (0.6-12 m long, at least 0.4 m wide, drawn as one closed path or as
    loose lines) around a printed equipment tag (AHU / AHK / IV-kone / LTO / FAN ...). Height: a printed 'h=NNNN'
    inside the outline, else none (to_ifc then uses a default and marks it so)."""
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    ws = C.words
    room_word = re.compile(r"^(?:room|huone\w*|rum|raum|space|tila)$", re.I)
    # a tag, not a room name: "AHU ROOM" / "IV-konehuone" name the room the plant stands in
    tags = [w for k, w in enumerate(ws) if EQUIP.match(w["text"].strip(" .:,()"))
            and not (k + 1 < len(ws) and room_word.match(ws[k + 1]["text"].strip(" .:,()")))]
    if not tags:
        return []
    paths = page.get("paths") or []
    min_seg = C.pt(0.25)  # dash / dash-dot fragments (grid lines exploded by the exporter) would cut the outline
    r = C.pt(reach_m)
    out = []
    for w in tags:
        cx, cy = (w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2
        win = box(cx - r, cy - r, cx + r, cy + r)
        lines = []
        for p in paths:
            q = p.get("pts") or ()
            if len(q) < 2 or p.get("dashed") or p.get("stroke") is None:
                continue
            xs = [v[0] for v in q]; ys = [v[1] for v in q]
            if max(xs) < win.bounds[0] or min(xs) > win.bounds[2] or max(ys) < win.bounds[1] or min(ys) > win.bounds[3]:
                continue
            pts = [tuple(v[:2]) for v in q] + ([tuple(q[0][:2])] if p.get("closed") else [])
            lines += [LineString([a, b]) for a, b in zip(pts[:-1], pts[1:])
                      if a != b and math.hypot(b[0] - a[0], b[1] - a[1]) >= min_seg]
        if not lines or len(lines) > 20000:
            continue
        pt = Point(cx, cy)
        best = None
        # faces of the line work, with end gaps up to 2 x tol closed (exporters leave corners a hair open)
        tol = C.pt(0.02)
        ink = unary_union(lines).buffer(tol, cap_style=2, join_style=2)
        faces = []
        for comp in (ink.geoms if hasattr(ink, "geoms") else [ink]):
            faces += [Polygon(h).buffer(tol, join_style=2) for h in getattr(comp, "interiors", [])]
        for g in faces:
            if not g.contains(pt):
                continue
            sh = C._shape(g, -1, 0)
            if sh is None or not (0.6 <= sh["l"] <= 12.0 and 0.4 <= sh["w"] <= 6.0) or sh["fill"] < 0.9:
                continue
            if best is None or g.area < best[0].area:
                best = (g, sh)
        if best is None:
            continue
        g, sh = best
        if not C.in_plan(g) or C.wall_overlap(g) > 0.1:
            continue
        hs = [x for x in C.words if HEIGHT_TXT.match(x["text"].replace(" ", ""))
              and g.contains(Point((x["bbox"][0] + x["bbox"][2]) / 2, (x["bbox"][1] + x["bbox"][3]) / 2))]
        props = {"type": "air_handler", "size_m": [round(sh["l"], 2), round(sh["w"], 2)], "tag": w["text"],
                 "evidence": f"closed outline around the printed tag '{w['text']}'"}
        if hs:
            props["height_m"] = int(HEIGHT_TXT.match(hs[0]["text"].replace(" ", "")).group(1)) / 1000.0
            props["height_printed"] = hs[0]["text"]
        out.append((g, {"kind": "equipment", "polygon": _poly_list(g), "conf": 0.7, "props": props}))
    keep = []  # one element per outline (two tags in one box)
    for g, f in out:
        if not any(g.symmetric_difference(k).area < 0.05 * g.area for k, _ in keep):
            keep.append((g, f))
    return [f for _, f in keep]


def _spirals(C, page):
    """Spiral stairs: a drawn circle 1.0-3.0 m across with >= 8 radial tread lines (centre post to rim). Treads =
    the radial lines counted; riser / going printed beside it when present (else none: to_ifc marks defaults)."""
    import math
    from shapely.geometry import Point
    out = []
    paths = page.get("paths") or []
    for s in C.ensure_shapes():
        if not (s["curved"] and 1.0 <= s["l"] <= 3.0 and s["w"] >= 0.92 * s["l"] and 0.74 <= s["fill"] <= 0.82):
            continue
        g = s["g"]
        if not C.in_plan(g):
            continue
        cx, cy = g.centroid.x, g.centroid.y
        R = math.sqrt(g.area / math.pi)
        x0, y0, x1, y1 = g.bounds
        angs = set()
        for p in paths:
            q = p.get("pts") or ()
            if len(q) < 2 or p.get("stroke") is None:
                continue
            if max(v[0] for v in q) < x0 or min(v[0] for v in q) > x1 or max(v[1] for v in q) < y0 or min(v[1] for v in q) > y1:
                continue
            for a, b in zip(q[:-1], q[1:]):
                da, db = math.hypot(a[0] - cx, a[1] - cy), math.hypot(b[0] - cx, b[1] - cy)
                inner, outer = (a, b) if da < db else (b, a)
                di, do = min(da, db), max(da, db)
                if di <= 0.4 * R and abs(do - R) <= 0.12 * R:
                    ang = math.atan2(outer[1] - cy, outer[0] - cx)
                    angs.add(round(ang / (math.pi / 90)))  # 2-degree bins: one line per tread edge
        angs = sorted(angs)
        n = len(angs)
        if n < 8:
            continue
        printed = _printed_rise_going(C, g)
        lab = C.labels(g, LABELS["stair"], 1.5)
        out.append({"kind": "stair", "polygon": _poly_list(g), "conf": 0.7 + 0.1 * bool(lab),
                    "props": {**printed, "spiral": True, "treads": n, "diameter_m": round(2 * R * C.mpt, 3),
                              "centre_pt": [round(cx, 2), round(cy, 2)], "radius_pt": round(R, 2),
                              "tread_angles_deg": [a * 2 for a in angs],
                              "evidence": f"circle {2 * R * C.mpt:.2f} m with {n} radial tread lines"
                                          + (", label " + lab[0] if lab else "")}})
    return out


def _detect(page, walls, rooms, openings, mpt, budget_s=25.0):
    import time
    if not mpt or not page or not page.get("paths"):
        return []
    t_end = time.time() + float(budget_s)
    C = _Ctx(page, walls, rooms, openings, mpt)
    if C.footprint is None:
        return []
    out = []
    stairs = _stairs(C, t_end)
    out += stairs + _railings(C, stairs)
    if time.time() < t_end:
        san = _sanitary(C)
        out += san
        if time.time() < t_end:
            try:
                hobs = _cooktops(C)
            except Exception:  # noqa: BLE001
                hobs = []
            out += _counters(C, san + hobs)
    if time.time() < t_end:
        out += _x_rects(C)
    if time.time() < t_end:
        out += _beds(C)
    try:
        out += _lockers(C)
    except Exception:  # noqa: BLE001
        pass
    try:
        out += _equipment(C, page)
    except Exception:  # noqa: BLE001
        pass
    try:
        out += _spirals(C, page)
    except Exception:  # noqa: BLE001
        pass
    try:  # repeated / room-backed drawn symbols (furniture, WCs, showers); lower conf, so _final prefers the above.
        # Its own bounded budget (SYMBOLS_BUDGET_S): it must not starve when the geometric passes ran long.
        from pipeline import pdf_symbols
        out += pdf_symbols.find(page, mpt, wall_u=C.wall_u, footprint=C.footprint, doors=C.doors,
                                rooms=C.room_polys, words=C.words, budget_s=SYMBOLS_BUDGET_S)
    except Exception:  # noqa: BLE001
        pass
    try:  # labelled wet rooms: WC / basin / shower symbols the passes above missed; _final arbitrates overlaps
        from pipeline import pdf_sanitary
        from shapely.geometry import Polygon
        for f in pdf_sanitary.find(page, mpt, rooms, walls, out):
            g = Polygon(f["polygon"]).buffer(0)
            if "no tray" in str((f.get("props") or {}).get("evidence") or ""):
                continue  # DATA RULE: a fixed 0.9 x 0.9 m zone around a shower head is not a measured shape
            if not g.is_empty and not (f.get("kind") == "basin" and C.has_text(g)):  # a callout bubble is no basin
                out.append(f)
    except Exception:  # noqa: BLE001
        pass
    return _final(C, out)


def _final(C, fx):
    """Precision pass: no fixture inside walls, no overlaps between incompatible symbols."""
    from shapely.geometry import Polygon
    keep = []
    polys = []
    nested_ok = {("counter", "sink"), ("sink", "counter"), ("stair", "railing"), ("railing", "stair")}
    for f in sorted(fx, key=lambda f: -(f.get("conf") or 0)):
        g = Polygon(f["polygon"]).buffer(0)
        if g.is_empty or (f["kind"] != "railing" and C.wall_overlap(g) > 0.15):
            continue
        if f["kind"] in ("basin", "sink", "shower", "bath", "furniture") and C.spokes(g) >= 2:
            continue  # tied into long linework (roof drain valleys, leaders): a free symbol is not
        clash = False
        for k, h in zip(keep, polys):
            if (f["kind"], k["kind"]) in nested_ok:
                continue
            inter = g.intersection(h).area
            if inter > 0.2 * min(g.area, h.area):
                clash = True
                break
        if clash:
            continue
        keep.append(f)
        polys.append(g)
    order = {k: i for i, k in enumerate(KINDS)}
    keep.sort(key=lambda f: (order.get(f["kind"], 99), f["polygon"][0][1], f["polygon"][0][0]))
    # a railing lives only beside a kept stair; point it at that stair's index in the final list
    st = [(i, Polygon(f["polygon"])) for i, f in enumerate(keep) if f["kind"] == "stair"]
    out = []
    for f in keep:
        if f["kind"] == "railing":
            g = Polygon(f["polygon"])
            near = [i for i, sg in st if sg.distance(g) <= C.pt(0.1)]
            if not near:
                continue
            f["props"]["stair"] = near[0]
        out.append(f)
    keep = out
    import json  # plain JSON types only (numpy scalars break the plan map writer)
    return json.loads(json.dumps(keep, default=lambda v: v.item() if hasattr(v, "item") else str(v)))


# ================================================================ IFC authoring

def _gid(doc_id, page, key):
    import ifcopenshell.guid
    if doc_id:
        try:
            from pipeline.pdf_to_ifc import guid_for
            return guid_for(doc_id, key, page)
        except Exception:  # noqa: BLE001
            return ifcopenshell.guid.compress(uuid.uuid5(NS, f"{doc_id}:p{page}:{key}").hex)
    return ifcopenshell.guid.new()


class _Author:
    def __init__(self, f, storey, body, doc_id, page, xy, prov):
        self.f, self.storey, self.body, self.doc_id, self.page, self.xy, self.prov = f, storey, body, doc_id, page, xy, prov
        self.types, self.mats, self.styles = {}, {}, {}

    def entity(self, cls, key, name=None, predefined=None):
        import ifcopenshell.api.root
        e = ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=name, predefined_type=predefined)
        e.GlobalId = _gid(self.doc_id, self.page, key)
        if predefined and hasattr(e, "PredefinedType") and e.PredefinedType != predefined:
            e.PredefinedType = predefined
        return e

    def placement(self, rel):
        f = self.f
        return f.createIfcLocalPlacement(rel, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))

    def solid(self, ring, z0, h):
        f = self.f
        pts = [(round(float(x), 5), round(float(y), 5)) for x, y in ring]
        pl = f.createIfcCartesianPointList2D(pts)
        curve = f.createIfcIndexedPolyCurve(pl, [f.createIfcLineIndex(list(range(1, len(pts) + 1)) + [1])], False)
        prof = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z0))), None, None)
        return f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(max(h, 0.005)))

    def shape(self, product, solids, colour):
        import ifcopenshell.api.style
        f = self.f
        if not solids:
            return False
        rep = f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", solids)
        product.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        if colour not in self.styles:
            s = ifcopenshell.api.style.add_style(f, name=f"pdf_fixture_{len(self.styles)}")
            ifcopenshell.api.style.add_surface_style(f, style=s, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": colour[0], "Green": colour[1], "Blue": colour[2]}, "Transparency": 0.0})
            self.styles[colour] = s
        ifcopenshell.api.style.assign_representation_styles(f, shape_representation=rep, styles=[self.styles[colour]])
        return True

    def material(self, name):
        import ifcopenshell.api.material
        if name not in self.mats:
            self.mats[name] = ifcopenshell.api.material.add_material(self.f, name=name)
        return self.mats[name]

    def typed(self, el, tcls, predefined, name, mat, extra=None):
        import ifcopenshell.api.material
        import ifcopenshell.api.type
        key = (tcls, predefined, name)
        if key not in self.types:
            t = self.entity(tcls, f"type:fixture:{tcls}:{predefined}:{name}", name=name, predefined=predefined)
            if predefined == "USERDEFINED":
                t.ElementType = name
            for k, v in (extra or {}).items():
                setattr(t, k, v)
            ifcopenshell.api.material.assign_material(self.f, products=[t], material=self.material(mat))
            self.types[key] = t
        ifcopenshell.api.type.assign_type(self.f, related_objects=[el], relating_type=self.types[key])

    def pset(self, product, name, props):
        import ifcopenshell.api.pset
        props = {k: v for k, v in props.items() if v is not None}
        if props:
            ps = ifcopenshell.api.pset.add_pset(self.f, product=product, name=name)
            ifcopenshell.api.pset.edit_pset(self.f, pset=ps, properties=props)

    def qto(self, product, name, props):
        import ifcopenshell.api.pset
        props = {k: round(float(v), 4) for k, v in props.items() if v is not None}
        if props:
            q = ifcopenshell.api.pset.add_qto(self.f, product=product, name=name)
            ifcopenshell.api.pset.edit_qto(self.f, qto=q, properties=props)

    def provenance(self, product, fx, i):
        self.pset(product, "Hologram_Provenance", {**self.prov, "item_id": f"fixture-{i + 1}", "page": self.page,
                                                   "conf": fx.get("conf"), "fixture_kind": fx.get("kind"),
                                                   "evidence": (fx.get("props") or {}).get("evidence")})


def _ring_m(poly_pt, xy):
    from shapely.geometry import Polygon
    ring = [xy(float(x), float(y)) for x, y in poly_pt]
    p = Polygon(ring).buffer(0)
    if p.is_empty or p.area < 1e-4:
        return None
    if p.geom_type != "Polygon":
        p = max(p.geoms, key=lambda g: g.area)
    p = p.simplify(0.003)
    c = list(p.exterior.coords)[:-1]
    return c if len(c) >= 3 else None


def _risers(h, drawn_treads):
    """(risers, riser height): the drawn tread count when it gives a buildable riser, else ~175 mm risers."""
    if drawn_treads and 0.14 <= h / (drawn_treads + 1) <= 0.21:
        n = drawn_treads + 1
    else:
        n = max(2, int(round(h / 0.175)))
    return n, h / n


def _stair_steps(fx, xy, h, z0):
    """Stepped plan slices of the run rectangle, in model metres: [(ring, z_top)], plus flight numbers."""
    from shapely.geometry import Polygon
    pr = fx.get("props") or {}
    poly = [xy(float(x), float(y)) for x, y in fx["polygon"]]
    P = Polygon(poly).buffer(0)
    if P.is_empty or P.area < 0.2:
        return None
    r = P.minimum_rotated_rectangle
    c = np.array(list(r.exterior.coords)[:4])
    e1, e2 = c[1] - c[0], c[3] - c[0]
    d = pr.get("direction")  # page-pt unit vector of "up" along the run
    if d:
        a = np.array(xy(float(d[0]), float(d[1]))) - np.array(xy(0.0, 0.0))
        a = a / (np.linalg.norm(a) or 1)
        run = e1 if abs(np.dot(e1, a)) >= abs(np.dot(e2, a)) else e2
        side = e2 if run is e1 else e1
        if np.dot(run, a) < 0:  # start at the far corner so the slices climb along `a`
            origin = c[0] + run
            run = -run
        else:
            origin = c[0]
    else:
        n_drawn = pr.get("treads") or 0
        td = pr.get("tread_depth_m")
        # the run is the side the treads stack along: closer to treads * depth
        if td and n_drawn:
            L = n_drawn * td
            run, side = (e1, e2) if abs(np.linalg.norm(e1) - L) <= abs(np.linalg.norm(e2) - L) else (e2, e1)
        else:
            run, side = (e1, e2) if np.linalg.norm(e1) >= np.linalg.norm(e2) else (e2, e1)
        origin = c[0]
    n_drawn = int(pr.get("treads") or 0)
    risers, rh = _risers(h, n_drawn)
    n_slices = n_drawn if n_drawn >= 2 else risers - 1
    steps = []
    for k in range(n_slices):
        a0, a1 = origin + run * (k / n_slices), origin + run * ((k + 1) / n_slices)
        ring = [tuple(a0), tuple(a1), tuple(a1 + side), tuple(a0 + side)]
        steps.append((ring, z0 + min(h, (k + 1) * rh)))
    tread_len = float(np.linalg.norm(run)) / max(n_slices, 1)
    # the flight is what is drawn (a U stair draws two half flights); the storey total stays on the IfcStair
    return {"steps": steps, "risers": min(risers, n_slices + 1), "riser_h": rh, "treads": min(max(risers - 1, 1), n_slices),
            "storey_risers": risers,
            "tread_len": float(pr.get("tread_depth_m") or tread_len), "width": float(np.linalg.norm(side)),
            "run_len": float(np.linalg.norm(run)), "area": P.area}


def _spiral_steps(fx, xy, z0, default_riser=0.175):
    """Wedge treads of a drawn spiral stair in model metres: one sector between consecutive radial tread lines,
    starting after the widest gap (the entry), each a block from the floor to its tread level (riser printed or
    default). Climb sense follows increasing page angle (not printed: derived)."""
    import math
    pr = fx.get("props") or {}
    angs = sorted(pr.get("tread_angles_deg") or [])
    c, R = pr.get("centre_pt"), pr.get("radius_pt")
    if len(angs) < 3 or not c or not R:
        return None
    gaps = [((angs[(k + 1) % len(angs)] - angs[k]) % 360, k) for k in range(len(angs))]
    k0 = (max(gaps)[1] + 1) % len(angs)
    seq = angs[k0:] + angs[:k0]
    rh = float(pr.get("riser_printed_m") or default_riser)
    n = len(seq)  # tread lines = risers; the last one arrives at the upper level
    steps = []
    for k in range(n - 1):
        a0, a1 = math.radians(seq[k]), math.radians(seq[k + 1])
        if a1 <= a0:
            a1 += 2 * math.pi
        arc = [(c[0] + R * math.cos(a0 + (a1 - a0) * j / 6), c[1] + R * math.sin(a0 + (a1 - a0) * j / 6)) for j in range(7)]
        ring = [xy(c[0], c[1])] + [xy(x, y) for x, y in arc]
        steps.append((ring, z0 + (k + 1) * rh))
    src = "printed" if pr.get("riser_printed_m") else "default"
    detail = (f"{n} radial tread lines on a {pr.get('diameter_m')} m drawn circle (measured); riser "
              + (f"printed '{pr.get('riser_text')}'" if pr.get("riser_printed_m") else f"default {default_riser} m")
              + f"; rise {n * rh:.3f} m; climb sense derived (increasing page angle)")
    return {"steps": steps, "risers": n, "riser_h": rh, "src": src, "detail": detail}


def to_ifc(model, storey, body_ctx, fixtures, z0, storey_height_m=None, m_per_pt=None, to_model_xy=None, *,
           doc_id=None, page=1) -> dict:
    """Author the detected fixtures in `model` (an ifcopenshell file) on `storey`. Returns counts by IFC class.
    Geometry is placed relative to the storey's placement; z0 is the floor level in that placement (0.0)."""
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.material
    import ifcopenshell.api.spatial
    counts: dict = {}
    if not fixtures:
        return counts
    if to_model_xy is None:
        if not m_per_pt:
            raise ValueError("to_ifc needs m_per_pt or to_model_xy")
        mpt = float(m_per_pt)
        to_model_xy = lambda x, y: (x * mpt, -y * mpt)  # noqa: E731 - pdf_to_ifc's page -> plan convention
    h = float(storey_height_m or 2.7)
    z0 = float(z0 or 0.0)
    prov = {"source": "pdf_fixtures", "doc_id": doc_id, "m_per_pt": float(m_per_pt) if m_per_pt else None}
    A = _Author(model, storey, body_ctx, doc_id, page, to_model_xy, {k: v for k, v in prov.items() if v is not None})
    sp = storey.ObjectPlacement
    contained, n_by = [], {}
    for i, fx in enumerate(fixtures):
        kind = fx.get("kind")
        if kind not in KINDS or not fx.get("polygon"):
            continue
        n_by[kind] = n_by.get(kind, 0) + 1
        name = f"{NAMES.get(kind, kind)}-{n_by[kind]:03d}"
        pr = fx.get("props") or {}
        try:
            if kind == "stair" and pr.get("spiral"):
                sp_ = _spiral_steps(fx, to_model_xy, z0)
                if not sp_:
                    continue
                stair = A.entity("IfcStair", f"fixture-{i + 1}", name=name, predefined="SPIRAL_STAIR")
                stair.ObjectPlacement = A.placement(sp)
                fl = A.entity("IfcStairFlight", f"fixture-{i + 1}#flight", name=f"{name} flight 1", predefined="SPIRAL")
                fl.ObjectPlacement = A.placement(stair.ObjectPlacement)
                fl.NumberOfRisers, fl.NumberOfTreads = sp_["risers"], sp_["risers"] - 1
                fl.RiserHeight = round(sp_["riser_h"], 4)
                A.shape(fl, [A.solid(r, z0, zt - z0) for r, zt in sp_["steps"]], STAIR_COLOUR)
                ifcopenshell.api.aggregate.assign_object(model, products=[fl], relating_object=stair)
                A.typed(stair, "IfcStairType", "SPIRAL_STAIR", "Spiral stair", "Steel")
                A.pset(stair, "Pset_StairCommon", {"NumberOfRiser": sp_["risers"], "NumberOfTreads": sp_["risers"] - 1,
                                                   "RiserHeight": round(sp_["riser_h"], 4), "IsExternal": False,
                                                   "Reference": "Spiral stair"})
                A.pset(stair, "Hologram_Stair", {"Spiral": True, "Diameter": pr.get("diameter_m"),
                                                 "DrawnTreads": pr.get("treads"), "RebuiltBy": "pdf_fixtures spiral"})
                A.pset(stair, "Hologram_Evidence", {"Source": sp_["src"], "Detail": sp_["detail"]})
                A.pset(fl, "Hologram_Evidence", {"Source": sp_["src"], "Detail": sp_["detail"]})
                A.provenance(stair, fx, i)
                contained.append(stair)
                counts["IfcStair"] = counts.get("IfcStair", 0) + 1
                counts["IfcStairFlight"] = counts.get("IfcStairFlight", 0) + 1
                continue
            if kind == "stair":
                st = _stair_steps(fx, to_model_xy, h, z0)
                if not st:
                    continue
                stair = A.entity("IfcStair", f"fixture-{i + 1}", name=name, predefined="STRAIGHT_RUN_STAIR")
                stair.ObjectPlacement = A.placement(sp)
                fl = A.entity("IfcStairFlight", f"fixture-{i + 1}#flight", name=f"{name} flight 1", predefined="STRAIGHT")
                fl.ObjectPlacement = A.placement(stair.ObjectPlacement)
                fl.NumberOfRisers, fl.NumberOfTreads = st["risers"], st["treads"]
                fl.RiserHeight, fl.TreadLength = round(st["riser_h"], 4), round(st["tread_len"], 4)
                # each step: a block from the floor (solid stair) to its tread level
                A.shape(fl, [A.solid(r, z0, zt - z0) for r, zt in st["steps"]], STAIR_COLOUR)
                ifcopenshell.api.aggregate.assign_object(model, products=[fl], relating_object=stair)
                A.typed(stair, "IfcStairType", "STRAIGHT_RUN_STAIR", "Straight run stair", "Concrete")
                A.typed(fl, "IfcStairFlightType", "STRAIGHT", f"Stair flight {st['risers']} risers", "Concrete")
                common = {"NumberOfRiser": st["risers"], "NumberOfTreads": st["treads"],
                          "RiserHeight": round(st["riser_h"], 4), "TreadLength": round(st["tread_len"], 4)}
                A.pset(stair, "Pset_StairCommon", {**common, "NumberOfRiser": st["storey_risers"],
                                                   "NumberOfTreads": max(st["storey_risers"] - 1, 1),
                                                   "IsExternal": False, "Reference": "Straight run stair"})
                A.pset(fl, "Pset_StairFlightCommon", {**common, "Reference": f"Stair flight {st['risers']} risers"})
                A.qto(fl, "Qto_StairFlightBaseQuantities", {"Length": st["run_len"], "GrossVolume": None})
                A.qto(stair, "Qto_StairBaseQuantities", {"Length": st["run_len"]})
                A.pset(stair, "Hologram_Stair", {"DrawnTreads": pr.get("treads"), "Width": round(st["width"], 3),
                                                 "Direction": pr.get("direction_label"),
                                                 "RisersFrom": "drawn treads" if pr.get("treads") and
                                                 st["risers"] == pr.get("treads") + 1 else "storey height / 175 mm"})
                A.provenance(stair, fx, i)
                A.pset(stair, "Hologram_Evidence", {"Source": "measured", "Detail": f"{pr.get('treads')} drawn tread "
                                                    f"lines; plan outline measured (rebuilt by pdf_stairs)"})
                contained.append(stair)
                counts["IfcStair"] = counts.get("IfcStair", 0) + 1
                counts["IfcStairFlight"] = counts.get("IfcStairFlight", 0) + 1
                continue
            if kind == "shaft":
                continue  # a shaft is a void, not an element; it stays in the plan map only
            cls, pdt, tcls, eh, ez, mat, col = IFC_MAP[kind]
            ring = _ring_m(fx["polygon"], to_model_xy)
            if not ring:
                continue
            if kind == "lift":
                eh = min(eh, h - 0.1)
            if kind in ("railing", "equipment") and pr.get("height_printed"):
                eh = float(pr.get("height_m") or eh)
            if kind == "furniture":
                eh = FURNITURE_H.get(pr.get("type"), eh)
                if pr.get("type") == "chair" and max(pr.get("size_m") or [0]) >= 0.8:
                    eh = FURNITURE_H["armchair"]  # upholstered armchair footprint, not a dining chair
            el = A.entity(cls, f"fixture-{i + 1}", name=name, predefined=pdt)
            if pdt == "USERDEFINED":
                el.ObjectType = "KITCHEN_COUNTER" if kind == "counter" else kind.upper()
            if kind == "furniture" and pr.get("type"):
                ft = {"bed": "BED", "table": "TABLE", "chair": "CHAIR", "sofa": "SOFA", "desk": "DESK"}.get(pr["type"])
                if ft:
                    el.PredefinedType, pdt = ft, ft
            el.ObjectPlacement = A.placement(sp)
            solids = [A.solid(ring, z0 + ez, eh)]
            if kind in ("basin", "sink") and pr.get("on_counter") is not True and kind == "basin":
                pass
            A.shape(el, solids, col)
            tname = {"wc": "WC pan", "basin": "Wash hand basin", "shower": "Shower tray", "bath": "Bath",
                     "sink": "Kitchen sink", "counter": "Kitchen counter", "lift": "Passenger lift",
                     "railing": "Guard rail", "equipment": "Air handling unit"}.get(kind) or (pr.get("type") or "Furniture").title()
            A.typed(el, tcls, pdt, tname, mat)
            sx, sy = pr.get("size_m") or (None, None)
            if cls == "IfcSanitaryTerminal":
                A.pset(el, "Pset_SanitaryTerminalTypeCommon", {"Reference": tname, "NominalLength": sx,
                                                               "NominalWidth": sy, "NominalDepth": eh})
                # (the material is the type's IfcRelAssociatesMaterial: 'Material' is not in the IFC4 template)
            elif cls == "IfcRailing":
                A.pset(el, "Pset_RailingCommon", {"Reference": tname, "Height": eh, "IsExternal": False})
            elif cls == "IfcTransportElement":
                A.pset(el, "Pset_TransportElementCommon", {"Reference": tname})
            elif cls == "IfcFurniture":
                A.pset(el, "Pset_FurnitureTypeCommon", {"Reference": tname, "NominalLength": sx, "NominalDepth": sy,
                                                        "NominalHeight": eh})
            A.provenance(el, fx, i)
            hsrc = "printed" if pr.get("height_printed") else "default"
            A.pset(el, "Hologram_Evidence", {
                "Source": "measured", "HeightSource": hsrc,
                "Detail": f"plan outline measured from the drawn {pr.get('type') or kind} symbol "
                          f"({pr.get('evidence') or 'pdf_fixtures'}; size {pr.get('size_m') or 'see outline'} m); "
                          f"height {eh:.2f} m and base {ez:.2f} m are {hsrc} values"})
            contained.append(el)
            counts[cls] = counts.get(cls, 0) + 1
            counts["evidence_" + hsrc + "_height"] = counts.get("evidence_" + hsrc + "_height", 0) + 1
        except Exception:  # noqa: BLE001 - one odd fixture never stops the rest
            counts["errors"] = counts.get("errors", 0) + 1
    if contained:
        ifcopenshell.api.spatial.assign_container(model, products=contained, relating_structure=storey)
    return counts
