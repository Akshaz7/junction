"""Swiss Dwellings v3 floor geometry -> labelled vector PDF in a random drafting style (generated training data).

render_floor(rows, rng) -> (pdf_bytes, labels)  labels[k] = class of the k-th painted path object (CLASSES index),
    which is the "obj" id pdf_vector.load_page gives every subpath of that object.
Own minimal PDF writer (no reportlab). Geometry is metres; the page is points (1:50 / 1:100 / 1:200).
Classes: wall / window / door / textdim / hatch / grid / other (see pipeline/pdf_roles.CLASSES).
"""
from __future__ import annotations

import math
import zlib

import numpy as np
from shapely import wkt
from shapely.affinity import rotate as srotate
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

CLASSES = ("wall", "window", "door", "textdim", "hatch", "grid", "other")
C = {c: i for i, c in enumerate(CLASSES)}
ROOM_NAMES = {
    "BATHROOM": ["BATH", "Bad", "WC", "KPH", "Bathroom", "SDB"], "BEDROOM": ["BEDROOM", "Zimmer", "MH", "Chambre", "SOV"],
    "ROOM": ["ROOM", "Zimmer", "Office", "HUONE", "Raum"], "KITCHEN": ["KITCHEN", "Küche", "K", "KEITTIÖ"],
    "LIVING_ROOM": ["LIVING", "Wohnen", "OH", "Séjour"], "LIVING_DINING": ["LIVING/DINING", "Wohnen/Essen", "OH+RT"],
    "CORRIDOR": ["CORRIDOR", "Gang", "ET", "Flur", "HALL"], "BALCONY": ["BALCONY", "Balkon", "PARVEKE"],
    "STOREROOM": ["STORE", "Reduit", "VAR", "Abst."], "STAIRCASE": ["STAIR", "Treppenhaus", "PORRAS"],
    "SHAFT": ["SHAFT", "Schacht", "HK"], "ELEVATOR": ["LIFT", "Aufzug", "HISSI"],
}


class Pdf:
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.ops = []
        self.labels = []
        self.use_pattern = False
        self.pts, self.inst = [], []
        self.split_fs = False  # SVG/BIM exporters: fill and outline of one shape as two painted objects

    @staticmethod
    def _c(c):
        return "%.3f %.3f %.3f" % tuple(c)

    def path(self, subs, label, stroke=None, width=0.25, fill=None, dash=None, closed=False, curves=None,
             pattern=False):
        """subs: list of point lists (page pt, y up). curves: list of bool per sub (points given as Bezier triples
        after the first point). One painted object, one label."""
        if stroke is None and fill is None and not pattern:
            return
        if self.split_fs and stroke is not None and (fill is not None or pattern):
            self.path(subs, label, None, width, fill, None, closed, curves, pattern)
            self.path(subs, label, stroke, width, None, dash, closed, curves, False)
            return
        o = ["q"]
        if stroke is not None:
            o.append(f"{self._c(stroke)} RG {width:.3f} w")
            o.append(("[%s] 0 d" % " ".join("%.2f" % v for v in dash)) if dash else "[] 0 d")
        if pattern:
            o.append("/Pattern cs /P1 scn")
            self.use_pattern = True
        elif fill is not None:
            o.append(f"{self._c(fill)} rg")
        for k, pts in enumerate(subs):
            if len(pts) < 2:
                continue
            o.append("%.3f %.3f m" % pts[0])
            if curves and curves[k]:
                rest = pts[1:]
                for j in range(0, len(rest) - 2, 3):
                    o.append("%.3f %.3f %.3f %.3f %.3f %.3f c" % (*rest[j], *rest[j + 1], *rest[j + 2]))
            else:
                o.extend("%.3f %.3f l" % p for p in pts[1:])
            if closed:
                o.append("h")
        if (fill is not None or pattern) and stroke is not None:
            o.append("B")
        elif fill is not None or pattern:
            o.append("f")
        else:
            o.append("S")
        o.append("Q")
        self.ops.append("\n".join(o))
        self.labels.append(C[label])
        for pts in subs:  # detector boxes: every drawn point (Bezier control points over-approximate slightly)
            self.pts.extend(pts)

    pts: list = None
    inst: list = None

    def begin(self):
        if self.pts is None:
            self.pts, self.inst = [], []
        return len(self.pts)

    def end(self, cls, k0, pad_pt=0.0):
        """Close one object instance (cls 0 door, 1 window, 2 fixture) drawn since begin()."""
        P_ = self.pts[k0:]
        if P_:
            xs = [p[0] for p in P_]; ys = [p[1] for p in P_]
            self.inst.append((cls, min(xs) - pad_pt, min(ys) - pad_pt, max(xs) + pad_pt, max(ys) + pad_pt))

    def text(self, s, x, y, size, ang=0.0, colour=(0, 0, 0)):
        s = s.replace("\\", "").replace("(", "").replace(")", "")
        s = s.encode("latin-1", "replace").decode("latin-1")
        ca, sa = math.cos(ang), math.sin(ang)
        self.ops.append(f"BT {self._c(colour)} rg /F1 {size:.2f} Tf {ca:.4f} {sa:.4f} {-sa:.4f} {ca:.4f} {x:.2f} {y:.2f} Tm ({s}) Tj ET")

    def bytes(self):
        content = zlib.compress("\n".join(self.ops).encode("latin-1"))
        objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.W:.2f} {self.H:.2f}] /Contents 4 0 R "
                f"/Resources << /Font << /F1 5 0 R >> /Pattern << /P1 6 0 R >> >> >>",
                None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>", None]
        pat = b"0 0 0 RG 0.3 w 0 0 m 6 6 l S"
        out = bytearray(b"%PDF-1.5\n")
        offs = []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            if i == 4:
                out += b"4 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream\nendobj\n"
            elif i == 6:
                out += (b"6 0 obj\n<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 6 6] "
                        b"/XStep 6 /YStep 6 /Resources << >> /Length %d >>\nstream\n" % len(pat) + pat + b"\nendstream\nendobj\n")
            else:
                out += f"{i} 0 obj\n{o}\nendobj\n".encode()
        x = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for o in offs:
            out += f"{o:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
        return bytes(out)


def _polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def _lines(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type == "MultiLineString":
        return list(g.geoms)
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]


def _rect_axes(poly):
    """(centre, unit long axis, long length, short length) of the minimum rotated rectangle."""
    r = poly.minimum_rotated_rectangle
    c = np.asarray(r.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    l1, l2 = np.linalg.norm(e1), np.linalg.norm(e2)
    if l1 >= l2:
        u, L, T = e1 / max(l1, 1e-9), l1, l2
    else:
        u, L, T = e2 / max(l2, 1e-9), l2, l1
    return c.mean(0), u, L, T


def _circle(cx, cy, r, a0=0.0, a1=2 * math.pi, curve=True, n=16):
    """Bezier (curve=True: first point + triples) or polyline approximation of an arc."""
    if not curve:
        return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
    segs = max(1, int(math.ceil(abs(a1 - a0) / (math.pi / 2) - 1e-9)))
    da = (a1 - a0) / segs
    kq = 4 / 3 * math.tan(da / 4)
    pts = [(cx + r * math.cos(a0), cy + r * math.sin(a0))]
    for s in range(segs):
        t0, t1 = a0 + s * da, a0 + (s + 1) * da
        p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
        p3 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
        pts += [(p0[0] - kq * r * math.sin(t0), p0[1] + kq * r * math.cos(t0)),
                (p3[0] + kq * r * math.sin(t1), p3[1] - kq * r * math.cos(t1)), p3]
    return pts


def _style(rng):
    blk = (0, 0, 0)
    def pen(w_lo, w_hi, colour_p=0.15):
        c = blk
        u = rng.random()
        if u < colour_p:
            c = tuple(rng.uniform(0, 0.8, 3))
        elif u < colour_p + 0.2:
            g = rng.uniform(0.1, 0.55)
            c = (g, g, g)
        return {"c": c, "w": float(np.exp(rng.uniform(np.log(w_lo), np.log(w_hi))))}
    s = {
        "scale": float(rng.choice([1 / 50, 1 / 100, 1 / 100, 1 / 100, 1 / 200])),
        "wall_mode": str(rng.choice(["outline", "segments", "fill", "fill_outline", "hatch", "pattern", "white_outline",
                                     "per_wall", "per_wall_fill"],
                                    p=[0.12, 0.15, 0.08, 0.12, 0.1, 0.05, 0.08, 0.15, 0.15])),
        "wall_pen": pen(0.25, 1.0), "win_pen": pen(0.08, 0.45), "door_pen": pen(0.08, 0.45), "thin_pen": pen(0.06, 0.3),
        "text_pen": pen(0.08, 0.3), "dim_pen": pen(0.06, 0.3), "hatch_pen": pen(0.05, 0.25, 0.3),
        "grid_pen": pen(0.1, 0.4, 0.4), "furn_pen": pen(0.06, 0.4),
        "wall_fill": tuple([float(rng.choice([0.0, 0.0, 0.25, 0.4, 0.55, 0.7, 0.85]))] * 3),
        "split_edges": rng.random() < 0.35,
        "door_curve": rng.random() < 0.6, "door_leaf_rect": rng.random() < 0.4, "door_dashed_arc": rng.random() < 0.1,
        "glazing": int(rng.integers(1, 4)), "win_bim": rng.random() < 0.35, "win_frame": rng.random() < 0.7, "win_sill": rng.random() < 0.35,
        "dims": rng.random() < 0.75, "grid": rng.random() < 0.4, "floor_hatch": rng.random() < 0.55,
        "wall_hatch_step": float(rng.uniform(0.06, 0.2)), "room_text": rng.random() < 0.9,
        "stroked_text": rng.random() < 0.3, "furniture": rng.random() < 0.7, "fixtures": rng.random() < 0.95,
        "room_outline": rng.random() < 0.2, "white_rooms": rng.random() < 0.3, "background": rng.random() < 0.35,
        "frame": rng.random() < 0.8, "rot": float(rng.choice([0, 0, 0, rng.uniform(-math.pi, math.pi), math.pi / 2])),
        "same_pen": rng.random() < 0.2,  # window/door drawn with the wall pen
        "railing_double": rng.random() < 0.6,
    }
    if rng.random() < 0.35:  # monochrome CAD plot: few shared pens, so classes overlap in pen and geometry decides
        widths = [float(x) for x in rng.choice([0.13, 0.18, 0.25, 0.35, 0.5, 0.7], int(rng.integers(2, 4)), replace=False)]
        g = float(rng.choice([0.0, 0.0, 0.3]))
        for k in ("wall_pen", "win_pen", "door_pen", "thin_pen", "text_pen", "dim_pen", "hatch_pen", "grid_pen", "furn_pen"):
            s[k] = {"c": (g, g, g), "w": float(rng.choice(widths))}
    if s["same_pen"]:
        s["win_pen"] = dict(s["wall_pen"])
        s["door_pen"] = dict(s["wall_pen"]) if rng.random() < 0.5 else s["door_pen"]
    if s["wall_mode"] in ("fill",) and rng.random() < 0.5:
        s["wall_fill"] = (0.0, 0.0, 0.0)
    return s


def render_floor(rows, rng):
    st = _style(rng)
    walls, cols, rails, doors, wins, areas, feats = [], [], [], [], [], [], []
    for r in rows:
        try:
            g = wkt.loads(r["geometry"])
        except Exception:  # noqa: BLE001
            continue
        if g.is_empty:
            continue
        t, sub = r["entity_type"], r["entity_subtype"]
        if not g.is_valid:
            g = g.buffer(0)
        if sub == "WALL":
            walls.append(g)
        elif sub == "COLUMN":
            cols.append(g)
        elif sub == "RAILING":
            rails.append(g)
        elif sub in ("DOOR", "ENTRANCE_DOOR"):
            doors.append(g)
        elif sub == "WINDOW":
            wins.append(g)
        elif t == "area":
            areas.append((sub, g))
        elif t == "feature":
            feats.append((sub, g))
    if len(walls) < 4:
        return None
    base = _dominant(walls)
    u = rng.random()
    rot = -base if u < 0.6 else (0.0 if u < 0.85 else float(rng.uniform(-math.pi, math.pi)))
    st["rot"] = rot
    fa = rot + base  # plan axes angle on the page
    O = (0, 0)
    def R(g):
        return srotate(g, rot, origin=O, use_radians=True) if rot else g
    wall_u = R(unary_union(walls + cols).buffer(0.002).buffer(-0.002))
    door_g = [R(g) for g in doors]
    win_g = [R(g) for g in wins]
    open_u = unary_union(door_g + win_g) if (door_g or win_g) else None
    wall_draw = wall_u.difference(open_u.buffer(0.005)) if open_u is not None else wall_u
    areas = [(s, R(g)) for s, g in areas]
    feats = [(s, R(g)) for s, g in feats]
    rails = [R(g) for g in rails]

    x0, y0, x1, y1 = wall_u.bounds
    sc = st["scale"] * 72 / 0.0254  # pt per metre
    margin = 4.0 + (3.0 if st["dims"] else 0) + (3.0 if st["grid"] else 0)
    W = (x1 - x0 + 2 * margin) * sc
    H = (y1 - y0 + 2 * margin) * sc
    tb = 0.0
    if st["frame"]:
        tb = float(rng.uniform(60, 160))
        W += tb
    W, H = max(W, 300), max(H, 300)
    if W > 5000 or H > 5000:
        return None
    ox = -x0 * sc + margin * sc
    oy = -y0 * sc + margin * sc
    def P(x, y):
        return (ox + x * sc, oy + y * sc)
    def ring(c):
        return [P(x, y) for x, y in c]
    pdf = Pdf(W, H)
    pdf.split_fs = rng.random() < 0.5
    sp = st

    # frame + title block
    if st["frame"]:
        pen = sp["thin_pen"]
        pdf.path([[(10, 10), (W - 10, 10), (W - 10, H - 10), (10, H - 10)]], "other", pen["c"], pen["w"] * 2, closed=True)
        bx = W - 10 - tb
        pdf.path([[(bx, 10), (bx, H - 10)]], "other", pen["c"], pen["w"])
        for k in range(int(rng.integers(3, 9))):
            yy = 10 + (k + 1) * float(rng.uniform(15, 40))
            if yy < H - 20:
                pdf.path([[(bx, yy), (W - 10, yy)]], "other", pen["c"], pen["w"])
                pdf.text(str(rng.choice(["PROJECT", "DRAWING", "SCALE 1:%d" % round(1 / st["scale"]), "DATE", "REV", "A-1%02d" % rng.integers(100)])),
                         bx + 4, yy - 10, float(rng.uniform(5, 9)))
    # background linework (neighbour outline, light grey)
    if st["background"]:
        g = float(rng.uniform(0.55, 0.85))
        off = float(rng.uniform(5, 15))
        nb = srotate(wall_u.envelope, float(rng.uniform(-0.3, 0.3)), use_radians=True).buffer(1.0)
        from shapely.affinity import translate
        nb = translate(nb, off * float(rng.choice([-1, 1])), 0)
        for p in _polys(nb):
            pdf.path([ring(p.exterior.coords)], "other", (g, g, g), 0.2, closed=True)
    # white room masks
    if st["white_rooms"]:
        for s, g in areas:
            for p in _polys(g):
                pdf.path([ring(p.exterior.coords)], "other", None, fill=(1, 1, 1), closed=True)
    # floor hatch (wet rooms tiles, balconies diagonal)
    if st["floor_hatch"]:
        hp = sp["hatch_pen"]
        one_obj = rng.random() < 0.4
        for s, g in areas:
            if s not in ("BATHROOM", "BALCONY", "KITCHEN", "LOGGIA", "TERRACE", "SHAFT", "STOREROOM") or rng.random() < 0.3:
                continue
            region = g.difference(wall_u)
            if region.is_empty:
                continue
            step = float(rng.uniform(0.1, 0.4))
            a = fa + (math.pi / 4 if s in ("BALCONY", "SHAFT", "LOGGIA") else 0.0)
            dirs = [a] if s in ("BALCONY", "SHAFT", "LOGGIA", "STOREROOM") else [a, a + math.pi / 2]
            cx, cy = region.centroid.x, region.centroid.y
            rr = math.hypot(*(np.array(region.bounds[2:]) - np.array(region.bounds[:2]))) / 2 + step
            subs = []
            for d in dirs:
                ux, uy = math.cos(d), math.sin(d)
                for k in np.arange(-rr, rr, step):
                    ln = LineString([(cx - ux * rr - uy * k, cy - uy * rr + ux * k), (cx + ux * rr - uy * k, cy + uy * rr + ux * k)])
                    for piece in _lines(ln.intersection(region)):
                        subs.append(ring(piece.coords))
            if not subs:
                continue
            if one_obj:
                pdf.path(subs, "hatch", hp["c"], hp["w"])
            else:
                for s_ in subs[:400]:
                    pdf.path([s_], "hatch", hp["c"], hp["w"])
    # room outlines
    if st["room_outline"]:
        tp = sp["thin_pen"]
        for s, g in areas:
            for p in _polys(g):
                pdf.path([ring(p.exterior.coords)], "other", tp["c"], tp["w"], dash=[3, 2], closed=True)
    # walls
    wp = sp["wall_pen"]
    mode = st["wall_mode"]
    if mode in ("per_wall", "per_wall_fill"):
        # BIM-export style: every wall element its own closed outline (overlapping at junctions), cut at openings
        cut = open_u.buffer(0.005) if open_u is not None else None
        for g in walls + cols:
            gg = R(g)
            if cut is not None:
                gg = gg.difference(cut)
            for p in _polys(gg):
                rings = [p.exterior.coords] + [i.coords for i in p.interiors]
                if mode == "per_wall_fill":
                    pdf.path([ring(r_) for r_ in rings], "wall", None, fill=st["wall_fill"], closed=True)
                pdf.path([ring(r_) for r_ in rings], "wall", wp["c"], wp["w"], closed=True)
    wpolys = _polys(wall_draw) if mode not in ("per_wall", "per_wall_fill") else []
    for p in wpolys:
        rings = [p.exterior.coords] + [i.coords for i in p.interiors]
        if mode in ("fill", "fill_outline"):
            pdf.path([ring(r_) for r_ in rings], "wall", None, fill=st["wall_fill"], closed=True)
        if mode == "pattern":
            pdf.path([ring(r_) for r_ in rings], "wall", None, closed=True, pattern=True)
        if mode == "white_outline":
            pdf.path([ring(r_) for r_ in rings], "wall", wp["c"], wp["w"], fill=(1, 1, 1), closed=True)
        elif mode in ("outline", "fill_outline", "hatch", "pattern"):
            if mode == "fill_outline" and rng.random() < 0.5:
                continue
            pdf.path([ring(r_) for r_ in rings], "wall", wp["c"], wp["w"], closed=True)
        elif mode == "segments":
            for r_ in rings:
                c = list(r_)
                for a, b in zip(c[:-1], c[1:]):
                    if math.dist(a, b) < 1e-4:
                        continue
                    if st["split_edges"] and math.dist(a, b) > 1.5 and rng.random() < 0.5:
                        t = float(rng.uniform(0.3, 0.7))
                        m = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                        pdf.path([[P(*a), P(*m)]], "wall", wp["c"], wp["w"])
                        pdf.path([[P(*m), P(*b)]], "wall", wp["c"], wp["w"])
                    else:
                        pdf.path([[P(*a), P(*b)]], "wall", wp["c"], wp["w"])
        if mode == "hatch":
            step = st["wall_hatch_step"]
            d = fa + math.pi / 4
            ux, uy = math.cos(d), math.sin(d)
            cx, cy = p.centroid.x, p.centroid.y
            bxs = p.bounds
            rr = math.hypot(bxs[2] - bxs[0], bxs[3] - bxs[1]) / 2 + step
            subs = []
            for k in np.arange(-rr, rr, step):
                ln = LineString([(cx - ux * rr - uy * k, cy - uy * rr + ux * k), (cx + ux * rr - uy * k, cy + uy * rr + ux * k)])
                for piece in _lines(ln.intersection(p)):
                    subs.append(ring(piece.coords))
            if subs:
                hp = sp["hatch_pen"]
                if rng.random() < 0.5:
                    pdf.path(subs, "wall", hp["c"], hp["w"])
                else:
                    for s_ in subs[:600]:
                        pdf.path([s_], "wall", hp["c"], hp["w"])
    # windows
    wn = sp["win_pen"]
    for g in win_g:
        for p in _polys(g):
            c, u, L, T = _rect_axes(p)
            if L < 0.2:
                continue
            _k0 = pdf.begin()
            v = np.array([-u[1], u[0]])
            def pt(a, b):
                q = c + u * a + v * b
                return P(q[0], q[1])
            if st["win_bim"]:  # BIM export: jamb frame boxes + thin pane box (+ sill), all closed shapes
                f = min(0.07, L / 6)
                wfill = (1, 1, 1) if rng.random() < 0.5 else None
                for a in (-L / 2, L / 2 - f):
                    pdf.path([[pt(a, -T / 2), pt(a + f, -T / 2), pt(a + f, T / 2), pt(a, T / 2)]], "window", wn["c"], wn["w"], closed=True, fill=wfill)
                if wfill is not None and rng.random() < 0.5:  # opening box masked white under the frame
                    pdf.path([[pt(-L / 2, -T / 2), pt(L / 2, -T / 2), pt(L / 2, T / 2), pt(-L / 2, T / 2)]], "window", wn["c"], wn["w"] * 0.8, closed=True, fill=wfill)
                pw_ = min(0.03, T / 4)
                pdf.path([[pt(-L / 2 + f, -pw_ / 2), pt(L / 2 - f, -pw_ / 2), pt(L / 2 - f, pw_ / 2), pt(-L / 2 + f, pw_ / 2)]],
                         "window", wn["c"], wn["w"], closed=True, fill=(0.85, 0.92, 0.95) if rng.random() < 0.3 else None)
                if st["win_sill"]:
                    pdf.path([[pt(-L / 2, T / 2), pt(L / 2, T / 2), pt(L / 2, T / 2 + 0.05), pt(-L / 2, T / 2 + 0.05)]], "window", wn["c"], wn["w"], closed=True)
                pdf.end(1, _k0)
                continue
            if st["win_frame"]:
                pdf.path([[pt(-L / 2, -T / 2), pt(L / 2, -T / 2), pt(L / 2, T / 2), pt(-L / 2, T / 2)]], "window", wn["c"], wn["w"], closed=True)
            else:
                pdf.path([[pt(-L / 2, -T / 2), pt(-L / 2, T / 2)]], "window", wn["c"], wn["w"])
                pdf.path([[pt(L / 2, -T / 2), pt(L / 2, T / 2)]], "window", wn["c"], wn["w"])
            ng = st["glazing"]
            for k in range(ng):
                b = (-T / 2 + T * (k + 1) / (ng + 1)) if ng > 1 else 0.0
                pdf.path([[pt(-L / 2, b), pt(L / 2, b)]], "window", wn["c"], wn["w"] * float(rng.uniform(0.6, 1.0)))
            if st["win_sill"]:
                sgn = float(rng.choice([-1, 1]))
                pdf.path([[pt(-L / 2 - 0.05, sgn * (T / 2 + 0.08)), pt(L / 2 + 0.05, sgn * (T / 2 + 0.08))]], "window", wn["c"], wn["w"])
            pdf.end(1, _k0)
    # doors
    dp = sp["door_pen"]
    for g in door_g:
        for p in _polys(g):
            c, u, L, T = _rect_axes(p)
            if L < 0.4:
                continue
            v = np.array([-u[1], u[0]])
            _k0 = pdf.begin()
            side = float(rng.choice([-1, 1]))
            leaves = [(-1, L)] if L < 1.35 else [(-1, L / 2), (1, L / 2)]
            for hs, wl in leaves:
                hinge = c + u * (hs * L / 2) + v * side * T / 2
                tip = hinge + v * side * wl
                jamb = hinge - u * hs * wl
                if st["door_leaf_rect"]:
                    lt = 0.04
                    q = [hinge, tip, tip - u * hs * lt, hinge - u * hs * lt]
                    pdf.path([[P(*x) for x in q]], "door", dp["c"], dp["w"], closed=True)
                else:
                    pdf.path([[P(*hinge), P(*tip)]], "door", dp["c"], dp["w"] * 1.5)
                a0 = math.atan2(*(tip - hinge)[::-1])
                a1 = math.atan2(*(jamb - hinge)[::-1])
                da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
                arc = _circle(0, 0, wl * sc, a0, a0 + da, curve=st["door_curve"], n=int(rng.integers(6, 16)))
                hp_ = P(*hinge)
                arc = [(hp_[0] + x, hp_[1] + y) for x, y in arc]
                pdf.path([arc], "door", dp["c"], dp["w"] * 0.7, dash=[2, 1.5] if st["door_dashed_arc"] else None,
                         curves=[st["door_curve"]])
            if rng.random() < 0.3:  # threshold line
                pdf.path([[P(*(c - u * L / 2)), P(*(c + u * L / 2))]], "door", dp["c"], dp["w"] * 0.6)
            pdf.end(0, _k0)
    # railings
    tp = sp["thin_pen"]
    for g in rails:
        for p in _polys(g):
            if st["railing_double"]:
                pdf.path([ring(p.exterior.coords)], "other", tp["c"], tp["w"], closed=True)
            else:
                c, u, L, T = _rect_axes(p)
                pdf.path([[P(*(c - u * L / 2)), P(*(c + u * L / 2))]], "other", tp["c"], tp["w"])
    # fixtures and stairs
    fp = sp["furn_pen"]
    if st["fixtures"]:
        for s, g in feats:
            for p in _polys(g):
                _k0 = pdf.begin()
                pdf.path([ring(p.exterior.coords)], "other", fp["c"], fp["w"], closed=True)
                c, u, L, T = _rect_axes(p)
                v = np.array([-u[1], u[0]])
                if s == "STAIRS":
                    n = max(2, int(L / 0.27))
                    for k in range(1, n):
                        a = -L / 2 + L * k / n
                        pdf.path([[P(*(c + u * a - v * T / 2)), P(*(c + u * a + v * T / 2))]], "other", fp["c"], fp["w"])
                elif s in ("TOILET", "SINK", "BATHTUB"):
                    r = min(L, T) * 0.35
                    q = P(*c)
                    e = _circle(q[0], q[1], r * sc, curve=True)
                    pdf.path([e], "other", fp["c"], fp["w"], closed=True, curves=[True])
                elif s == "SHOWER":
                    pdf.path([[P(*(c - u * L / 2 - v * T / 2)), P(*(c + u * L / 2 + v * T / 2))]], "other", fp["c"], fp["w"])
                    pdf.path([[P(*(c - u * L / 2 + v * T / 2)), P(*(c + u * L / 2 - v * T / 2))]], "other", fp["c"], fp["w"])
                elif s == "KITCHEN":
                    for k in range(int(rng.integers(0, 4))):
                        q = P(*(c + u * float(rng.uniform(-L / 3, L / 3))))
                        pdf.path([_circle(q[0], q[1], 0.1 * sc)], "other", fp["c"], fp["w"], closed=True, curves=[True])
                pdf.end(2, _k0)
    # furniture
    if st["furniture"]:
        for s, g in areas:
            if s not in ("BEDROOM", "ROOM", "LIVING_ROOM", "LIVING_DINING", "DINING", "OFFICE"):
                continue
            inner = g.buffer(-0.15)
            if inner.is_empty:
                continue
            for _ in range(int(rng.integers(1, 5))):
                w_, h_ = float(rng.uniform(0.4, 2.0)), float(rng.uniform(0.4, 2.0))
                bx0, by0, bx1, by1 = inner.bounds
                if bx1 - bx0 < w_ or by1 - by0 < h_:
                    continue
                px = float(rng.uniform(bx0, bx1 - w_)); py = float(rng.uniform(by0, by1 - h_))
                rect = srotate(box(px, py, px + w_, py + h_), fa, origin=(px, py), use_radians=True)
                if not inner.contains(rect):
                    continue
                pdf.path([ring(rect.exterior.coords)], "other", fp["c"], fp["w"], closed=True)
                if rng.random() < 0.5:
                    pdf.path([ring(rect.buffer(-0.05).exterior.coords)], "other", fp["c"], fp["w"] * 0.7, closed=True)
    # room text
    tpen = sp["text_pen"]
    if st["room_text"]:
        fs = float(rng.uniform(5, 10)) * (sc / 28.35) ** 0.3
        for s, g in areas:
            if g.area < 1.0:
                continue
            q = g.representative_point()
            x, y = P(q.x, q.y)
            name = str(rng.choice(ROOM_NAMES.get(s, [s.title()[:10]])))
            lines = [name, "%.1f m2" % g.area] + (["%d.%02d" % (rng.integers(1, 9), rng.integers(1, 40))] if rng.random() < 0.5 else [])
            for k, t in enumerate(lines):
                yy = y - k * fs * 1.2
                if st["stroked_text"]:
                    _stroke_text(pdf, t, x, yy, fs, tpen, rng)
                else:
                    pdf.text(t, x, yy, fs)
    # dimensions
    if st["dims"]:
        _dims(pdf, wall_u, fa, P, sc, sp["dim_pen"], rng, st)
    # grid
    if st["grid"]:
        _grid(pdf, wall_u, fa, P, sc, sp["grid_pen"], rng, st)
    if len(pdf.labels) < 20:
        return None
    return (pdf.bytes(), list(pdf.labels), {k: (v if not isinstance(v, dict) else {"w": v["w"]}) for k, v in st.items()},
            {"W": W, "H": H, "inst": list(pdf.inst), "pt_per_m": sc})


def _dominant(walls):
    """Length-weighted dominant edge direction (mod 90 deg) of the wall polygons, radians."""
    h = np.zeros(90)
    for g in walls:
        for p in _polys(g):
            c = np.asarray(p.exterior.coords)
            d = np.diff(c, axis=0)
            L = np.hypot(d[:, 0], d[:, 1])
            a = np.mod(np.degrees(np.arctan2(d[:, 1], d[:, 0])), 90.0)
            np.add.at(h, np.minimum(a.astype(int), 89), L)
    h = h + np.roll(h, 1) + np.roll(h, -1)
    return math.radians(float(np.argmax(h)) + 0.5)


def _stroke_text(pdf, t, x, y, fs, pen, rng):
    """Text drawn as linework (CAD 'exploded' text): a few short strokes per glyph cell."""
    cw = fs * 0.6
    for k, ch in enumerate(t):
        if ch == " ":
            continue
        gx = x + k * cw
        n = int(rng.integers(1, 4))
        subs = []
        for _ in range(n):
            a = (gx + float(rng.uniform(0, cw * 0.8)), y + float(rng.uniform(0, fs * 0.8)))
            b = (gx + float(rng.uniform(0, cw * 0.8)), y + float(rng.uniform(0, fs * 0.8)))
            subs.append([a, b])
        if rng.random() < 0.5:
            pdf.path(subs, "textdim", pen["c"], pen["w"])
        else:
            for s_ in subs:
                pdf.path([s_], "textdim", pen["c"], pen["w"])


def _frame_coords(g, rot):
    """Wall vertices in the plan's own (unrotated) frame."""
    pts = []
    for p in _polys(g):
        pts.extend(p.exterior.coords)
    a = np.asarray(pts)
    c, s = math.cos(-rot), math.sin(-rot)
    return np.column_stack([a[:, 0] * c - a[:, 1] * s, a[:, 0] * s + a[:, 1] * c])


def _to_page(P, rot, x, y):
    c, s = math.cos(rot), math.sin(rot)
    return P(x * c - y * s, x * s + y * c)


def _dims(pdf, wall_u, rot, P, sc, pen, rng, st):
    a = _frame_coords(wall_u, rot)
    x0, y0 = a.min(0)
    x1, y1 = a.max(0)
    tick = str(rng.choice(["slash", "dot", "arrow", "tick"]))
    fs = float(rng.uniform(4, 8))
    sides = [s for s in ("S", "N", "W", "E") if rng.random() < 0.7] or ["S"]
    for side in sides:
        horiz = side in ("S", "N")
        vals = np.unique(np.round(a[:, 0] if horiz else a[:, 1], 1))
        if len(vals) > 25:
            vals = np.unique(np.concatenate([[vals[0], vals[-1]], rng.choice(vals, 23, replace=False)]))
        for chain in range(int(rng.integers(1, 3))):
            off = 1.0 + chain * 0.8 + float(rng.uniform(0, 0.5))
            pos = (y0 - off) if side == "S" else (y1 + off) if side == "N" else (x0 - off) if side == "W" else (x1 + off)
            vv = vals if chain == 0 else np.array([vals[0], vals[-1]])
            def Q(t, o=0.0):
                return _to_page(P, rot, t, pos + o) if horiz else _to_page(P, rot, pos + o, t)
            pdf.path([[Q(vv[0] - 0.2), Q(vv[-1] + 0.2)]], "textdim", pen["c"], pen["w"])
            for t in vv:
                if tick == "slash":
                    d = 0.12
                    pdf.path([[(_to_page(P, rot, t - d, pos - d) if horiz else _to_page(P, rot, pos - d, t - d)),
                               (_to_page(P, rot, t + d, pos + d) if horiz else _to_page(P, rot, pos + d, t + d))]], "textdim", pen["c"], pen["w"] * 2)
                elif tick == "dot":
                    q = Q(t)
                    pdf.path([_circle(q[0], q[1], 0.6)], "textdim", None, fill=pen["c"], closed=True, curves=[True])
                elif tick == "tick":
                    pdf.path([[Q(t, -0.15), Q(t, 0.15)]], "textdim", pen["c"], pen["w"])
                else:
                    pdf.path([[Q(t - 0.1, 0.04), Q(t), Q(t - 0.1, -0.04)]], "textdim", pen["c"], pen["w"], closed=True, fill=pen["c"])
                if rng.random() < 0.6:  # extension line
                    sgn = 1 if side in ("S", "W") else -1
                    pdf.path([[Q(t, 0.2 * sgn), Q(t, 0.8 * sgn)]], "textdim", pen["c"], pen["w"] * 0.7)
            for ta, tb in zip(vv[:-1], vv[1:]):
                if tb - ta < 0.3:
                    continue
                q = Q((ta + tb) / 2, 0.12)
                ang = rot if horiz else rot + math.pi / 2
                pdf.text("%d" % round((tb - ta) * 100), q[0], q[1], fs, ang)


def _grid(pdf, wall_u, rot, P, sc, pen, rng, st):
    a = _frame_coords(wall_u, rot)
    x0, y0 = a.min(0)
    x1, y1 = a.max(0)
    ext = 2.5
    dash = [float(rng.uniform(6, 14)), 2, 1.5, 2] if rng.random() < 0.8 else None
    for horiz in (True, False):
        vals = np.unique(np.round(a[:, 0] if horiz else a[:, 1], 0))
        k = min(len(vals), int(rng.integers(2, 8)))
        if k < 2:
            continue
        sel = np.sort(rng.choice(vals, k, replace=False))
        for j, t in enumerate(sel):
            if horiz:
                p0, p1 = _to_page(P, rot, t, y0 - ext), _to_page(P, rot, t, y1 + ext)
            else:
                p0, p1 = _to_page(P, rot, x0 - ext, t), _to_page(P, rot, x1 + ext, t)
            pdf.path([[p0, p1]], "grid", pen["c"], pen["w"], dash=dash)
            r = 0.4 * sc
            for e in (p0, p1) if rng.random() < 0.5 else (p0,):
                pdf.path([_circle(e[0], e[1], r)], "grid", pen["c"], pen["w"], closed=True, curves=[True])
                lab = chr(65 + j) if horiz else str(j + 1)
                pdf.text(lab, e[0] - r * 0.3, e[1] - r * 0.3, r * 0.9)
