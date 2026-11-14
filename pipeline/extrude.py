"""D-09: plan map -> scene.glb + scene.json (the "Visualise it" extrusion).

One GLB node per wall, door, window and room floor, node name = item_id (CONTRACT 5.1).
Plan coordinates (px, top-left origin) -> metres: X = (px - W/2)*m_per_px, Z = (py - H/2)*m_per_px,
Y up. So the scene is recentred on the image centre and the textured floor quad "plan_floor"
spans exactly image size * scale. Defaults (override with item props height_m): wall 2.7 m,
door opening 2.1 m, window sill 0.9 m / head 2.1 m. Generated for demo.

CLI: python -m pipeline.extrude [--only DOC_ID...] [--page N] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely import constrained_delaunay_triangles

REPO = Path(__file__).resolve().parent.parent
WALL_H, DOOR_H, SILL, HEAD, FLOOR_T = 2.7, 2.1, 0.9, 2.1, 0.02
TEX_MAX = 2048


def usd_name(item_id: str) -> str:
    return "i_" + hashlib.sha1(item_id.encode()).hexdigest()[:16]


def _polys(pts):
    g = pts if isinstance(pts, Polygon) else Polygon(pts)
    if g.area < 1e-9 and len(set(map(tuple, pts))) >= 2:  # zero-thickness drawn line: give it 5 cm
        g = LineString(list(dict.fromkeys(map(tuple, pts)))).buffer(0.025, cap_style="flat")
    if not g.is_valid:
        g = g.buffer(0)
    gs = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    return [p for p in gs if p.geom_type == "Polygon" and p.area > 1e-9]


def prism(pts_m, y0, y1):
    """Extrude a 2D polygon (list of (x, z) in metres) from y0 to y1 -> Trimesh (or None)."""
    V, F = [], []
    for poly in _polys(pts_m):
        poly = Polygon(poly.exterior.coords, [r.coords for r in poly.interiors])
        for tri in constrained_delaunay_triangles(poly).geoms:
            c = list(tri.exterior.coords)[:3]
            a, b, d = c
            if (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0]) < 0:
                b, d = d, b
            # y-up, x right, z toward viewer: this winding faces +Y in (x, z)
            for y in (y1, y0):
                tri3 = [(a[0], y, a[1]), (b[0], y, b[1]), (d[0], y, d[1])]
                n = _normal_y(tri3)
                if (y == y1 and n < 0) or (y == y0 and n > 0):
                    tri3 = [tri3[0], tri3[2], tri3[1]]
                i = len(V); V.extend(tri3); F.append([i, i + 1, i + 2])
        rings = [poly.exterior] + list(poly.interiors)
        for ri, ring in enumerate(rings):
            cs = list(ring.coords)
            for p, q in zip(cs, cs[1:]):
                if p == q:
                    continue
                quad = [(p[0], y0, p[1]), (q[0], y0, q[1]), (q[0], y1, q[1]), (p[0], y1, p[1])]
                i = len(V); V.extend(quad)
                F.extend([[i, i + 1, i + 2], [i, i + 2, i + 3]])
    if not F:
        return None
    m = trimesh.Trimesh(np.array(V, float), np.array(F), process=False)
    # make side faces point outward: flip any face whose normal points toward the polygon interior
    m = _orient(m, pts_m)
    vn = np.zeros_like(m.vertices)  # set by hand: trimesh's own vertex_normals needs scipy
    vn[m.faces.reshape(-1)] = np.repeat(m.face_normals, 3, axis=0)
    m.vertex_normals = vn
    return m


def _normal_y(t):
    a, b, c = (np.array(p) for p in t)
    return float(np.cross(b - a, c - a)[1])


def _orient(m, pts_m):
    """Flip side faces that point into the polygon (works for the exterior ring and holes)."""
    g = pts_m if isinstance(pts_m, Polygon) else Polygon(pts_m)
    g = g if g.is_valid else g.buffer(0)
    nrm = m.face_normals
    for i, f in enumerate(m.faces):
        if abs(nrm[i][1]) > 0.9:
            continue
        c = m.vertices[f].mean(axis=0)
        probe = (c[0] + nrm[i][0] * 1e-4, c[2] + nrm[i][2] * 1e-4)
        if g.contains(Point(probe)):
            m.faces[i] = f[::-1]
    m._cache.clear()
    return m


def _bbox_poly(it):
    x0, y0, x1, y1 = it["bbox_px"]
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


ROOM_TINT = {"bedroom": (214, 190, 156), "living": (222, 200, 165), "livingroom": (222, 200, 165),
             "kitchen": (205, 214, 222), "bathroom": (186, 210, 228), "bath": (186, 210, 228),
             "wc": (190, 212, 226), "toilet": (190, 212, 226), "sauna": (205, 170, 130),
             "hall": (225, 218, 205), "entrance": (225, 218, 205), "corridor": (225, 218, 205),
             "balcony": (178, 200, 178), "terrace": (178, 200, 178), "storage": (200, 200, 204),
             "laundry": (205, 214, 222)}
ROOM_DEFAULT = (226, 220, 208)
FIXTURES = ("toilet", "sink", "bathtub", "shower", "stairs", "stair")
RISER = 0.18


def _mat(rgb, alpha=255, rough=0.85, blend=False, double=False, tex=None):
    from trimesh.visual.material import PBRMaterial
    kw = dict(baseColorFactor=[*rgb, alpha], metallicFactor=0.0, roughnessFactor=rough, doubleSided=double)
    if blend:
        kw["alphaMode"] = "BLEND"
    if tex is not None:
        kw["baseColorTexture"] = tex
    return PBRMaterial(**kw)


MATS = {"wall": lambda: _mat((236, 232, 224)), "frame": lambda: _mat((246, 246, 246), rough=0.5),
        "glass": lambda: _mat((140, 200, 240), 90, rough=0.1, blend=True, double=True),
        "doorframe": lambda: _mat((150, 105, 65)), "leaf": lambda: _mat((196, 146, 92)),
        "ceramic": lambda: _mat((248, 248, 250), rough=0.35), "dark": lambda: _mat((90, 110, 125), rough=0.4),
        "stair": lambda: _mat((214, 208, 198))}


def _flat(m, mat):
    """Unshare vertices (flat shading), set normals by hand and attach a PBR material."""
    f = m.faces.reshape(-1)
    out = trimesh.Trimesh(m.vertices[f], np.arange(len(f)).reshape(-1, 3), process=False)
    out.vertex_normals = np.repeat(out.face_normals, 3, axis=0)
    out.visual = trimesh.visual.TextureVisuals(material=MATS[mat]() if isinstance(mat, str) else mat)
    return out


def _boxes(specs):
    """specs: (x0, x1, y0, y1, z0, z1) world-aligned boxes -> one mesh (None if empty)."""
    ms = []
    for x0, x1, y0, y1, z0, z1 in specs:
        if x1 - x0 < 1e-4 or y1 - y0 < 1e-4 or z1 - z0 < 1e-4:
            continue
        b = trimesh.creation.box(extents=(x1 - x0, y1 - y0, z1 - z0))
        b.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
        ms.append(b)
    return trimesh.util.concatenate(ms) if ms else None


def _opening(it, to_m):
    """Axis-aligned opening box in metres: (x0, x1, z0, z1, axis) with axis 'x' or 'z' = long direction."""
    x0, y0, x1, y1 = it["bbox_px"]
    (ax, az), (bx, bz) = to_m((x0, y0)), to_m((x1, y1))
    return min(ax, bx), max(ax, bx), min(az, bz), max(az, bz), ("x" if abs(bx - ax) >= abs(bz - az) else "z")


def _wb(ax, u0, u1, y0, y1, v0, v1):
    """Box from long-axis range u and across-axis range v (v is centred, given as offsets)."""
    return (u0, u1, y0, y1, v0, v1) if ax == "x" else (v0, v1, y0, y1, u0, u1)


def window_parts(o):
    x0, x1, z0, z1, ax = o
    u0, u1 = (x0, x1) if ax == "x" else (z0, z1)
    c = ((z0 + z1) / 2) if ax == "x" else ((x0 + x1) / 2)
    T = min(max((z1 - z0) if ax == "x" else (x1 - x0), 0.12), 0.3)
    f = 0.05
    B = lambda a, b, ya, yb, va, vb: _wb(ax, a, b, ya, yb, c + va, c + vb)
    fr = [B(u0, u1, SILL, SILL + f, -T / 2, T / 2), B(u0, u1, HEAD - f, HEAD, -T / 2, T / 2),
          B(u0, u0 + f, SILL, HEAD, -T / 2, T / 2), B(u1 - f, u1, SILL, HEAD, -T / 2, T / 2),
          B((u0 + u1) / 2 - f / 4, (u0 + u1) / 2 + f / 4, SILL, HEAD, -T / 2 + 0.02, T / 2 - 0.02)]
    if u1 - u0 < 0.7:
        fr = fr[:4]
    glass = [B(u0 + f, u1 - f, SILL + f, HEAD - f, -0.01, 0.01)]
    return [("frame", _flat(_boxes(fr), "frame")), ("glass", _flat(_boxes(glass), "glass"))]


def door_parts(o):
    x0, x1, z0, z1, ax = o
    u0, u1 = (x0, x1) if ax == "x" else (z0, z1)
    c = ((z0 + z1) / 2) if ax == "x" else ((x0 + x1) / 2)
    T = min(max((z1 - z0) if ax == "x" else (x1 - x0), 0.12), 0.3)
    f = 0.05
    B = lambda a, b, ya, yb, va, vb: _wb(ax, a, b, ya, yb, c + va, c + vb)
    fr = [B(u0, u0 + f, 0, DOOR_H, -T / 2, T / 2), B(u1 - f, u1, 0, DOOR_H, -T / 2, T / 2),
          B(u0, u1, DOOR_H - f, DOOR_H, -T / 2, T / 2)]
    w = max(u1 - u0 - 2 * f, 0.2)
    leaf = _boxes([B(u0 + f, u0 + f + w, 0.01, DOOR_H - f, -0.02, 0.02)])
    hinge = np.array([(u0 + f) if ax == "x" else c, 0, c if ax == "x" else (u0 + f)])
    leaf.apply_transform(trimesh.transformations.rotation_matrix(np.radians(28), [0, 1, 0], hinge))
    return [("frame", _flat(_boxes(fr), "doorframe")), ("leaf", _flat(leaf, "leaf"))]


def _cyl(cx, cz, r, y0, y1, n=12):
    c = trimesh.creation.cylinder(radius=r, height=y1 - y0, sections=n)
    c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))  # axis -> Y
    c.apply_translation((cx, (y0 + y1) / 2, cz))
    return c


def fixture_parts(kind, bb):
    """bb = (x0, x1, z0, z1) metres. Simple low-poly shapes, long side along the longer axis."""
    x0, x1, z0, z1 = bb
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    ax = "x" if (x1 - x0) >= (z1 - z0) else "z"
    L, Wd = max(x1 - x0, z1 - z0), min(x1 - x0, z1 - z0)
    W_ = lambda u0, u1, y0, y1, v0, v1: _wb(ax, cx - L / 2 + u0 * L, cx - L / 2 + u1 * L, y0, y1,
                                           (cz if ax == "x" else cx) - Wd / 2 + v0 * Wd,
                                           (cz if ax == "x" else cx) - Wd / 2 + v1 * Wd)
    if kind == "toilet":
        tank = _boxes([W_(0, 0.3, 0.0, 0.8, 0.1, 0.9)])
        bowl = _cyl(cx + (0.15 * L if ax == "x" else 0), cz + (0.15 * L if ax == "z" else 0), min(L * 0.3, Wd * 0.45), 0.0, 0.4)
        seat_c = trimesh.util.concatenate([tank, bowl])
        return [("body", _flat(seat_c, "ceramic"))]
    if kind == "sink":
        return [("body", _flat(_boxes([W_(0, 1, 0, 0.8, 0, 1)]), "ceramic")),
                ("basin", _flat(_boxes([W_(0.15, 0.85, 0.8, 0.84, 0.2, 0.8)]), "dark"))]
    if kind == "bathtub":
        t = 0.1
        parts = [W_(0, 1, 0, 0.1, 0, 1), W_(0, 1, 0.1, 0.55, 0, t), W_(0, 1, 0.1, 0.55, 1 - t, 1),
                 W_(0, t * 0.6, 0.1, 0.55, 0, 1), W_(1 - t * 0.6, 1, 0.1, 0.55, 0, 1)]
        return [("body", _flat(_boxes([(a, b, c, d, e, f) for a, b, c, d, e, f in parts]), "ceramic"))]
    if kind == "shower":
        return [("body", _flat(_boxes([W_(0, 1, 0, 0.08, 0, 1)]), "ceramic")),
                ("glass", _flat(_boxes([W_(0, 1, 0.08, 2.0, 0.97, 1.0)]), "glass"))]
    # stairs: flight along the long axis, risers ~0.18 m up to one storey
    n = max(2, min(int(round(WALL_H / RISER)), int(L / 0.25)))
    steps = [W_(i / n, 1, 0, (i + 1) * WALL_H / n, 0, 1) for i in range(n)]
    return [("steps", _flat(_boxes(steps), "stair"))]



def _shell(pm, img_gray, mpp):
    """Outline shell for drawings with no readable wall pixels: perimeter walls around the content box."""
    from shapely.geometry import box as _box
    H, W = img_gray.shape
    boxes = [it["bbox_px"] for it in pm["items"] if it["kind"] in ("room", "door", "window", "wall") and it.get("bbox_px")]
    if boxes:
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    else:
        paper = float(np.percentile(img_gray, 70))
        ys, xs = np.where(img_gray < 0.7 * paper)
        if len(xs) < 50:
            x0, y0, x1, y1 = 0.05 * W, 0.05 * H, 0.95 * W, 0.95 * H
        else:
            x0, x1 = np.percentile(xs, 2), np.percentile(xs, 98)
            y0, y1 = np.percentile(ys, 2), np.percentile(ys, 98)
    t = 0.18 / mpp
    outer = _box(x0 - t / 2, y0 - t / 2, x1 + t / 2, y1 + t / 2)
    inner = _box(x0 + t / 2, y0 + t / 2, x1 - t / 2, y1 - t / 2)
    if inner.is_empty or not inner.area:
        return None
    return {"walls": [outer.difference(inner)], "floor": outer, "wall_frac": 0.0}


def process(doc_id: str, art: Path, page: int = 1, raster_walls: bool = False) -> dict:
    pm = json.loads((art / f"planmap-{page}.json").read_text())
    W, H = pm["image"]["w"], pm["image"]["h"]
    mpp = pm["scale"]["m_per_px"]
    to_m = lambda p: ((p[0] - W / 2) * mpp, (p[1] - H / 2) * mpp)
    scene = trimesh.Scene()
    items, counts = {}, {}
    img = Image.open(art / f"page-{page}.png").convert("RGB")
    s = TEX_MAX / max(img.size)
    if s < 1:
        img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    hx, hz = W * mpp / 2, H * mpp / 2
    # faint plan underlay, just above the room slabs
    V = np.array([[-hx, 0, -hz], [hx, 0, -hz], [hx, 0, hz], [-hx, 0, hz]], float) + [0, FLOOR_T + 0.003, 0]
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float)
    floor = trimesh.Trimesh(V, [[0, 2, 1], [0, 3, 2]], process=False)
    floor.vertex_normals = np.tile([0.0, 1.0, 0.0], (4, 1))
    floor.visual = trimesh.visual.TextureVisuals(uv=uv, material=_mat((255, 255, 255), 90, rough=1.0, blend=True, tex=img))
    scene.add_geometry(floor, node_name="plan_floor", geom_name="plan_floor")

    def height_of(it, default):
        return float(it["props"].get("height_m") or default)

    rw = None
    if raster_walls and (art / f"page-{page}.png").is_file():
        try:
            from pipeline import raster_walls as _rw
            rw = _rw.read(np.asarray(Image.open(art / f"page-{page}.png").convert("L"), dtype=float), mpp)
        except Exception as ex:  # noqa: BLE001
            print("raster walls skipped:", repr(ex)[:200])
    approx = False
    if raster_walls and rw is None and sum(1 for it in pm["items"] if it["kind"] == "wall") < 3:
        # ladder step 3: no wall pixels and no usable plan-map walls -> clean shell around the drawing's outline
        try:
            rw = _shell(pm, img_gray=np.asarray(Image.open(art / f"page-{page}.png").convert("L"), dtype=float), mpp=mpp)
            approx = rw is not None
            if approx:
                floor.visual = trimesh.visual.TextureVisuals(uv=uv, material=_mat((255, 255, 255), 255, rough=1.0, tex=img))
        except Exception as ex:  # noqa: BLE001
            print("shell fallback skipped:", repr(ex)[:200])
    win_o = [_opening(it, to_m) for it in pm["items"] if it["kind"] == "window"]
    door_o = [_opening(it, to_m) for it in pm["items"] if it["kind"] == "door"]

    def register(iid, k, parts):
        parts = [(n, m) for n, m in parts if m is not None]
        if not parts:
            return
        if len(parts) == 1:
            scene.add_geometry(parts[0][1], node_name=iid, geom_name=iid)
        else:  # group node carries the item id; frame/glass/... hang under it
            scene.graph.update(frame_to=iid, frame_from=scene.graph.base_frame, matrix=np.eye(4))
            for n, m in parts:
                scene.add_geometry(m, node_name=f"{iid}:{n}", geom_name=f"{iid}:{n}", parent_node_name=iid)
        b = np.array([m.bounds for _, m in parts])
        lo, hi = b[:, 0].min(axis=0), b[:, 1].max(axis=0)
        counts[k] = counts.get(k, 0) + 1
        items[iid] = {"node": iid, "usd_name": usd_name(iid),
                      "bbox_m": [[round(float(v), 4) for v in lo], [round(float(v), 4) for v in hi]],
                      "storey": "Floor 1", "kind": k}

    if rw:
        rw["walls_u"] = unary_union(rw["walls"])
        rw["taken"] = Polygon()
        tm = lambda g: Polygon([to_m(q) for q in g.exterior.coords], [[to_m(q) for q in r.coords] for r in g.interiors])
        fl = rw["floor"]
        sl = [x for x in (prism(tm(g), 0.0, FLOOR_T) for g in (fl.geoms if fl.geom_type == "MultiPolygon" else [fl])) if x is not None]
        slab = trimesh.util.concatenate(sl) if sl else None
        if slab is not None:
            slab.visual = trimesh.visual.TextureVisuals(material=_mat((178, 168, 152), rough=0.9, double=True))
            register("floor-slab", "floor", [("floor", slab)])
        wo_all, do_all = win_o, door_o
        for wi, wp in enumerate(rw["walls"], 1):
            g = Polygon([to_m(q) for q in wp.exterior.coords], [[to_m(q) for q in r.coords] for r in wp.interiors])
            g = g if g.is_valid else g.buffer(0)
            PAD = 0.08

            def cut(opens):
                shp = []
                for x0, x1, z0, z1, ax in opens:
                    sh = Polygon([(x0 - PAD, z0 - PAD), (x1 + PAD, z0 - PAD), (x1 + PAD, z1 + PAD), (x0 - PAD, z1 + PAD)])
                    if sh.intersects(g):
                        shp.append(sh)
                return unary_union(shp) if shp else None
            dc, wc = cut(do_all), cut(wo_all)
            low = g if dc is None else g.difference(dc)
            mid = low if wc is None else low.difference(wc)
            ms = []
            for sh, y0, y1 in ((low, 0.0, SILL), (mid, SILL, HEAD), (g, HEAD, WALL_H)):
                if sh.is_empty:
                    continue
                for q in (list(sh.geoms) if sh.geom_type in ("MultiPolygon", "GeometryCollection") else [sh]):
                    if q.geom_type == "Polygon" and q.area > 1e-5:
                        mm = prism(q, y0, y1)
                        if mm is not None:
                            ms.append(mm)
            if ms:
                mesh = trimesh.util.concatenate(ms)
                vn = np.zeros_like(mesh.vertices)
                vn[mesh.faces.reshape(-1)] = np.repeat(mesh.face_normals, 3, axis=0)
                mesh.vertex_normals = vn
                mesh.visual = trimesh.visual.TextureVisuals(material=MATS["wall"]())
                register(f"wall-r{wi:03d}", "wall", [("wall", mesh)])
    for it in pm["items"]:
        k = it["kind"]
        if k not in ("wall", "door", "window", "room") + FIXTURES:
            continue
        iid = it["item_id"]
        if rw and k == "wall":
            continue
        poly = it.get("polygon_px") or _bbox_poly(it)
        pts = [to_m(p) for p in poly]
        if k == "wall":
            hh = height_of(it, WALL_H)
            g = Polygon(pts)
            g = g if g.is_valid else g.buffer(0)
            hit = lambda opens: [o for o in opens if g.bounds[0] - 0.5 < o[1] and o[0] < g.bounds[2] + 0.5
                                 and g.bounds[1] - 0.5 < o[3] and o[2] < g.bounds[3] + 0.5]
            wo, do = hit(win_o), hit(door_o)
            if not wo and not do:
                m = prism(pts, 0.0, hh)
            else:
                from shapely.geometry import Polygon as P

                half = max(0.15, float(it["props"].get("thickness_px") or 0) * mpp / 2 + 0.05)

                def cutter(opens):
                    shapes = []
                    for x0, x1, z0, z1, ax in opens:
                        e = max(0.0, half - ((z1 - z0) if ax == "x" else (x1 - x0)) / 2) + 0.01
                        sh = P([(x0, z0 - e), (x1, z0 - e), (x1, z1 + e), (x0, z1 + e)]) if ax == "x" \
                            else P([(x0 - e, z0), (x1 + e, z0), (x1 + e, z1), (x0 - e, z1)])
                        if sh.intersection(g).area > 1e-4:
                            shapes.append(sh)
                    return unary_union(shapes) if shapes else None
                dc, wc = cutter(do), cutter(wo)
                low = g if dc is None else g.difference(dc)           # below sill: doors only
                mid = low if wc is None else low.difference(wc)        # sill..head: doors + windows
                lv = [(low, 0.0, SILL), (mid, SILL, min(HEAD, hh)), (g, min(HEAD, hh), hh)]
                ms = [prism(p, y0, y1)
                      for sh, y0, y1 in lv if sh is not None and not sh.is_empty and y1 - y0 > 1e-4
                      for p in (list(sh.geoms) if sh.geom_type == "MultiPolygon" else [sh])
                      if p.geom_type == "Polygon" and p.area > 1e-6]
                ms = [x for x in ms if x is not None]
                m = trimesh.util.concatenate(ms) if ms else None
                if m is not None:
                    vn = np.zeros_like(m.vertices)
                    vn[m.faces.reshape(-1)] = np.repeat(m.face_normals, 3, axis=0)
                    m.vertex_normals = vn
            if m is not None:
                m.visual = trimesh.visual.TextureVisuals(material=MATS["wall"]())
            register(iid, k, [("wall", m)])
        elif k == "door":
            register(iid, k, door_parts(_opening(it, to_m)))
        elif k == "window":
            register(iid, k, window_parts(_opening(it, to_m)))
        elif k == "room":
            if rw:
                from shapely.geometry import box as _box
                g = _box(*it["bbox_px"]).intersection(rw["floor"]).difference(rw["walls_u"]).difference(rw["taken"])
                rw["taken"] = rw["taken"].union(g)
                g = max(list(g.geoms), key=lambda q: q.area) if g.geom_type in ("MultiPolygon", "GeometryCollection") and not g.is_empty else g
                m = prism(Polygon([to_m(q) for q in g.exterior.coords], [[to_m(q) for q in r.coords] for r in g.interiors]), 0.0, FLOOR_T) if g.geom_type == "Polygon" and g.area > 40 else None
            else:
                m = prism(pts, 0.0, FLOOR_T)
            if m is not None:
                rgb = ROOM_TINT.get(str(it["props"].get("room_type") or "").lower(), ROOM_DEFAULT)
                if rw:  # darker, so the floor reads against a white wall and a light background
                    rgb = tuple(int(c * 0.78) for c in rgb)
                m.visual = trimesh.visual.TextureVisuals(material=_mat(rgb, rough=0.9, double=True))
            register(iid, k, [("floor", m)])
        else:
            x0, y0, x1, y1 = it["bbox_px"]
            (ax_, az_), (bx_, bz_) = to_m((x0, y0)), to_m((x1, y1))
            register(iid, k, fixture_parts(k, (min(ax_, bx_), max(ax_, bx_), min(az_, bz_), max(az_, bz_))))
    glb = scene.export(file_type="glb")
    (art / "scene.glb").write_bytes(glb)
    doc = json.loads((art / "doc.json").read_text()) if (art / "doc.json").exists() else {}
    lic = doc.get("licence") or ""
    sc = {"doc_id": doc_id, "glb": "scene.glb", "usdz": None, "units": "m", "up": "Y",
          "origin_offset_m": [round(W * mpp / 2, 4), 0.0, round(H * mpp / 2, 4)],
          "storeys": [{"name": "Floor 1", "elevation_m": 0.0}], "plan_image": f"page-{page}.png",
          "items": items, "source_planmap": f"planmap-{page}.json",
          "defaults": {"wall_m": WALL_H, "door_m": DOOR_H, "window_sill_m": SILL, "window_head_m": HEAD},
          "note": "generated for demo: extruded from plan map with default heights; "
                  "stairs only when the plan map has a stairs item (none from raster plans)",
          "publishable": not (lic.startswith("CC-BY-ND") or lic.startswith("GPL"))}
    if approx:
        sc["props"] = {"approx": True}
        sc["note"] = "3D approximated from the drawing"
    (art / "scene.json").write_text(json.dumps(sc, indent=1))
    try:  # names, room areas, door widths for the info cards (pipeline/manifest_info.py)
        from pipeline import manifest_info
        manifest_info.enrich(art, None)
    except Exception as ex:  # noqa: BLE001
        print('manifest_info skipped:', repr(ex)[:200])
    return {"counts": counts, "glb_kb": len(glb) // 1024}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="also overwrite IFC scenes")
    a = ap.parse_args()
    for art in sorted((REPO / "artifacts").glob("*__*")):
        if a.only and art.name not in a.only:
            continue
        if not (art / f"planmap-{a.page}.json").exists():
            continue
        if (art / "elements.json").exists() and not a.force:
            continue  # IFC doc: scene already built by ifc_scene
        try:
            print(art.name, process(art.name, art, a.page))
        except Exception as ex:
            print(art.name, "FAILED", repr(ex))


if __name__ == "__main__":
    main()
