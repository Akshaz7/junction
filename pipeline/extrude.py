"""D-09: plan map -> scene.glb + scene.json (the "Visualise it" extrusion).

One GLB node per wall, door, window and room floor, node name = item_id (CONTRACT 5.1).
Plan coordinates (px, top-left origin) -> metres: X = (px - W/2)*m_per_px, Z = (py - H/2)*m_per_px,
Y up. So the scene is recentred on the image centre and the textured floor quad "plan_floor"
spans exactly image size * scale. Wall height is shared per storey (median height_m, default 2.7 m),
door opening 2.1 m, window sill 0.9 m / head 2.1 m. Generated for demo.

CLI: python -m pipeline.extrude [--only DOC_ID...] [--page N] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

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
    if m is None:
        return None
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


def _fit_opening(o, walls):
    """Find the neighbouring wall axis/thickness, including diagonal DXF walls.

    Returns a local opening, its world transform, footprint and host wall id.
    The fallback keeps the detected box when there is no neighbouring wall.
    """
    x0, x1, z0, z1, ax = o
    corners = np.array([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])
    center = corners.mean(axis=0)
    width = max(x1 - x0, z1 - z0, 0.1)
    hint = np.array([1., 0.]) if ax == "x" else np.array([0., 1.])
    # An elongated detection box already gives the wall direction. Raster plans
    # often lose the host wall itself (a window runs corner to corner, leaving
    # no wall pixels beside it), so the nearest piece is a perpendicular end
    # wall; fitting to that turns the opening into a strip one wall thick.
    elongated = max(x1 - x0, z1 - z0) > 1.7 * min(x1 - x0, z1 - z0)
    choices, crossing = [], []
    for iid, wall in walls:
        if wall.is_empty or wall.geom_type != "Polygon":
            continue
        candidates = [wall]
        # Raster contours often contain a whole connected wall network. Its
        # bounding rectangle says nothing about local wall thickness; inspect
        # nearby pieces at several radii instead of treating the network as a bar.
        for radius in (width * .65, width + .35):
            nearby = wall.intersection(Point(center).buffer(radius).envelope)
            candidates.extend(list(nearby.geoms) if hasattr(nearby, "geoms") else [nearby])
        for candidate in candidates:
            if candidate.is_empty or candidate.geom_type != "Polygon":
                continue
            rect = np.asarray(candidate.minimum_rotated_rectangle.exterior.coords)[:4]
            edges = np.roll(rect, -1, axis=0) - rect
            lengths = np.linalg.norm(edges, axis=1)
            longest = int(np.argmax(lengths))
            if lengths[longest] < 1e-6 or max(lengths) < 1.5 * min(lengths):
                continue
            u = edges[longest] / lengths[longest]
            v = np.array([-u[1], u[0]])
            vs = rect @ v
            c = float((vs.min() + vs.max()) / 2)
            across = abs(center @ v - c)
            distance = candidate.distance(Point(center))
            if distance > width + 0.5 or across > max(width * 0.6, 0.35):
                continue
            penalty = (1 - abs(u @ hint)) * width if elongated else 0
            choice = (distance + across + penalty, iid, u, v, c, float(vs.max() - vs.min()))
            (crossing if elongated and abs(u @ hint) < 0.8 else choices).append(choice)
    host = None
    u, v = hint, np.array([-hint[1], hint[0]])
    c = float(center @ v)
    thickness = max(0.12, min(x1 - x0, z1 - z0))
    if choices:
        _, host, u, v, c, thickness = min(choices, key=lambda q: q[0])
    elif crossing:  # keep the box frame; the touching end wall still hosts the sill/head masonry
        host = min(crossing, key=lambda q: q[0])[1]
    # A fitted piece that includes a wall junction reports the junction depth as
    # thickness; the cut and sill/head masonry would then bulge past the faces.
    short = max(min(x1 - x0, z1 - z0), 0.06)
    # (The icon itself may be much thinner than its wall, so it is no cap.)
    thickness = min(thickness, 0.6)
    if elongated and abs(c - center @ v) > max(short, thickness) / 2:
        c = float(center @ v)
    us = corners @ u
    a, b = float(us.min()), float(us.max())
    # Coordinates in this frame are still metres; the rotation also aligns frames/glass.
    local = (a, b, c - thickness / 2, c + thickness / 2, "x")
    matrix = np.eye(4)
    matrix[0, 0], matrix[2, 0] = u
    matrix[0, 2], matrix[2, 2] = v
    footprint = Polygon([u * s + v * t for s, t in ((a, local[2]), (b, local[2]), (b, local[3]), (a, local[3]))])
    return local, matrix, footprint, host


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
    """Door in its wall opening: thin jambs + head (wall-deep frame) and a closed 4 cm leaf in the wall plane.

    The plan map has no swing direction for raster doors, so the leaf is shown closed, centred in the
    wall; it never exceeds the opening (u0..u1) or the door height. Narrow openings get thinner jambs.
    """
    x0, x1, z0, z1, ax = o
    u0, u1 = (x0, x1) if ax == "x" else (z0, z1)
    c = ((z0 + z1) / 2) if ax == "x" else ((x0 + x1) / 2)
    T = min(max((z1 - z0) if ax == "x" else (x1 - x0), 0.12), 0.3)
    f = min(0.05, (u1 - u0) / 8)
    B = lambda a, b, ya, yb, va, vb: _wb(ax, a, b, ya, yb, c + va, c + vb)
    fr = [B(u0, u0 + f, 0, DOOR_H, -T / 2, T / 2), B(u1 - f, u1, 0, DOOR_H, -T / 2, T / 2),
          B(u0, u1, DOOR_H - f, DOOR_H, -T / 2, T / 2)]
    leaf = [B(u0 + f + 0.003, u1 - f - 0.003, 0.01, DOOR_H - f - 0.003, -0.02, 0.02)]
    return [("frame", _flat(_boxes(fr), "doorframe")), ("leaf", _flat(_boxes(leaf), "leaf"))]


def _door_box(it, to_m):
    """Door opening box. A detector box that also holds the swing arc is square; the door polygon
    (leaf/threshold strip) then gives the true width and wall direction."""
    o = _opening(it, to_m)
    x0, x1, z0, z1, _ = o
    poly = it.get("polygon_px")
    if not poly or max(x1 - x0, z1 - z0) > 1.7 * min(x1 - x0, z1 - z0):
        return o
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    q = _opening({"bbox_px": [min(xs), min(ys), max(xs), max(ys)]}, to_m)
    dx, dz = q[1] - q[0], q[3] - q[2]
    return q if max(dx, dz) > 1.7 * min(dx, dz) and max(dx, dz) > 0.4 else o


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


def _stack_storeys(doc_id, art, page, raster_walls, pm, blocks):
    """Build each detected layout block independently, preserving source item ids.

    Heights/stacking are generated for demo, not measured floor elevations.
    Temporary sub-scenes never overwrite the input document's derived assets.
    """
    import copy
    import tempfile
    from engine.storeys import label_levels
    from shapely.geometry import box

    regions = [box(*b["bbox_px"]) for b in blocks]
    groups = [[] for _ in blocks]
    for it in pm["items"]:
        if not it.get("bbox_px"):
            continue
        bb = box(*it["bbox_px"])
        group = min(range(len(regions)), key=lambda i: (regions[i].distance(bb.centroid), regions[i].centroid.distance(bb.centroid)))
        groups[group].append(it)

    def level(index):
        levels = label_levels(it.get("label") for it in groups[index] if it["kind"] == "text")
        return min(levels) if len(levels) == 1 else 99

    order = sorted(range(len(blocks)), key=lambda i: (level(i), blocks[i]["bbox_px"][1], blocks[i]["bbox_px"][0]))
    merged = trimesh.Scene()
    items, counts, storeys = {}, {}, []
    anchor = None
    original_ids = {it["item_id"] for it in pm["items"]}
    image_path = art / f"page-{page}.png"
    with Image.open(image_path) as page_image, tempfile.TemporaryDirectory(prefix="cx-pipe-storeys-") as tmp:
        for floor_index, group_index in enumerate(order):
            source_items = groups[group_index]
            bbs = [it["bbox_px"] for it in source_items]
            x0 = max(0, int(np.floor(min(b[0] for b in bbs))) - 3)
            y0 = max(0, int(np.floor(min(b[1] for b in bbs))) - 3)
            x1 = min(page_image.width, int(np.ceil(max(b[2] for b in bbs))) + 3)
            y1 = min(page_image.height, int(np.ceil(max(b[3] for b in bbs))) + 3)
            crop = (x0, y0, x1, y1)
            local = copy.deepcopy(pm)
            local["image"] = {"w": x1 - x0, "h": y1 - y0}
            local["items"] = copy.deepcopy(source_items)
            for it in local["items"]:
                a, b, c, d = it["bbox_px"]
                it["bbox_px"] = [a - x0, b - y0, c - x0, d - y0]
                if it.get("polygon_px"):
                    it["polygon_px"] = [[x - x0, y - y0] for x, y in it["polygon_px"]]
            scratch = Path(tmp) / str(floor_index)
            scratch.mkdir()
            (scratch / f"planmap-{page}.json").write_text(json.dumps(local))
            page_image.crop(crop).save(scratch / f"page-{page}.png")
            if (art / "doc.json").exists():
                (scratch / "doc.json").write_bytes((art / "doc.json").read_bytes())
            result = process(doc_id, scratch, page, raster_walls, _split_storeys=False)
            manifest = json.loads((scratch / "scene.json").read_text())
            child = trimesh.load_scene(scratch / "scene.glb")
            # The textured underlay must participate in storey visibility too.
            transform, geometry = child.graph["plan_floor"]
            underlay = child.geometry[geometry].bounds
            manifest["items"]["plan_floor"] = {"node": "plan_floor", "kind": "floor", "bbox_m": underlay.tolist()}
            wall_boxes = np.array([it["bbox_m"] for it in manifest["items"].values() if it["kind"] == "wall"])
            bounds = np.array([wall_boxes[:, 0].min(axis=0), wall_boxes[:, 1].max(axis=0)]) if len(wall_boxes) else child.bounds
            center = (bounds[0] + bounds[1]) / 2
            if anchor is None:
                anchor = center
            offset = np.array([anchor[0] - center[0], 3.0 * floor_index, anchor[2] - center[2]])
            name = f"Floor {floor_index + 1}"
            storeys.append({"name": name, "elevation_m": float(offset[1]), "source_bbox_px": blocks[group_index]["bbox_px"],
                            "wall_height_m": manifest["defaults"]["wall_m"]})
            # Generated raster wall ids and slabs repeat in independent sub-scenes.
            rename = {iid: iid if iid in original_ids else f"{iid}-floor-{floor_index + 1}" for iid in manifest["items"]}
            node_names = {}
            for node in child.graph.nodes:
                if node in rename:
                    node_names[node] = rename[node]
                elif node.startswith("wall-infill:"):
                    node_names[node] = node
                elif ":" in node and node.split(":")[0] in rename:
                    root, part = node.split(":", 1)
                    node_names[node] = rename[root] + ":" + part
                else:
                    node_names[node] = f"{node}-floor-{floor_index + 1}"
            root = f"storey-{floor_index + 1}"
            transform = trimesh.transformations.translation_matrix(offset)
            merged.graph.update(frame_to=root, matrix=transform)
            for key, geometry in child.geometry.items():
                merged.geometry[f"floor-{floor_index + 1}:{key}"] = geometry
            for parent, node, data in child.graph.to_edgelist():
                attrs = dict(data)
                if attrs.get("geometry"):
                    attrs["geometry"] = f"floor-{floor_index + 1}:{attrs['geometry']}"
                merged.graph.update(frame_from=root if parent == child.graph.base_frame else node_names[parent], frame_to=node_names[node], **attrs)
            for iid, it in manifest["items"].items():
                it["node"] = rename[iid]
                it["usd_name"] = usd_name(rename[iid])
                it["bbox_m"] = np.round(np.asarray(it["bbox_m"]) + offset, 4).tolist()
                it["storey"] = name
                items[rename[iid]] = it
            counts["floor"] = counts.get("floor", 0) + 1
            for kind, count in result["counts"].items():
                counts[kind] = counts.get(kind, 0) + count
    glb = merged.export(file_type="glb")
    (art / "scene.glb").write_bytes(glb)
    mpp = pm["scale"]["m_per_px"]
    manifest.update({"items": items, "storeys": storeys, "plan_image": f"page-{page}.png",
                     "origin_offset_m": [pm["image"]["w"] * mpp / 2, 0., pm["image"]["h"] * mpp / 2],
                     "note": "generated for demo: separate layout blocks aligned on wall bounds and stacked at 3 m; elevations are assumed"})
    (art / "scene.json").write_text(json.dumps(manifest, indent=1))
    return {"counts": counts, "glb_kb": len(glb) // 1024, "storeys": len(storeys)}


def process(doc_id: str, art: Path, page: int = 1, raster_walls: bool = False, *, _split_storeys: bool = True) -> dict:
    pm = json.loads((art / f"planmap-{page}.json").read_text())
    if _split_storeys:
        from engine.storeys import count_storeys
        layout = count_storeys([SimpleNamespace(**it) for it in pm["items"]])
        if layout["basis"] == "layout" and layout["n"] >= 2:
            return _stack_storeys(doc_id, art, page, raster_walls, pm, layout["blocks"])
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

    heights = [float(it.get("props", {}).get("height_m") or WALL_H) for it in pm["items"] if it["kind"] == "wall"]
    heights = [h for h in heights if np.isfinite(h) and h > HEAD]
    wall_h = float(np.median(heights)) if heights else WALL_H

    rw = None
    if raster_walls and (art / f"page-{page}.png").is_file():
        try:
            from pipeline import raster_walls as _rw
            rw = _rw.read(np.asarray(Image.open(art / f"page-{page}.png").convert("L"), dtype=np.uint8), mpp)
        except Exception as ex:  # noqa: BLE001
            print("raster walls skipped:", repr(ex)[:200])
    approx = False
    if raster_walls and rw is None and mpp <= 1 and sum(1 for it in pm["items"] if it["kind"] == "wall") < 3:
        # ladder step 3: no wall pixels and no usable plan-map walls -> clean shell around the drawing's outline
        try:
            rw = _shell(pm, img_gray=np.asarray(Image.open(art / f"page-{page}.png").convert("L"), dtype=np.uint8), mpp=mpp)
            approx = rw is not None
            if approx:
                floor.visual = trimesh.visual.TextureVisuals(uv=uv, material=_mat((255, 255, 255), 255, rough=1.0, tex=img))
        except Exception as ex:  # noqa: BLE001
            print("shell fallback skipped:", repr(ex)[:200])
    tm = lambda g: Polygon([to_m(q) for q in g.exterior.coords], [[to_m(q) for q in r.coords] for r in g.interiors])
    wall_polys = [(f"wall-r{i:03d}", tm(g)) for i, g in enumerate(rw["walls"], 1)] if rw else [
        (it["item_id"], unary_union(_polys([to_m(p) for p in (it.get("polygon_px") or _bbox_poly(it))])))
        for it in pm["items"] if it["kind"] == "wall"]
    openings = {it["item_id"]: _fit_opening((_door_box if it["kind"] == "door" else _opening)(it, to_m), wall_polys)
                for it in pm["items"] if it["kind"] in ("window", "door")}
    win_o = [openings[it["item_id"]][2] for it in pm["items"] if it["kind"] == "window"]
    door_o = [openings[it["item_id"]][2] for it in pm["items"] if it["kind"] == "door"]

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
            def cut(opens):
                shp = [o.buffer(0.01, join_style="mitre") for o in opens if o.intersects(g)]
                return unary_union(shp) if shp else None
            dc, wc = cut(do_all), cut(wo_all)
            low = g if dc is None else g.difference(dc)
            mid = low if wc is None else low.difference(wc)
            ms = []
            for sh, y0, y1 in ((low, 0.0, SILL), (mid, SILL, HEAD), (g, HEAD, wall_h)):
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
            hh = wall_h
            g = Polygon(pts)
            g = g if g.is_valid else g.buffer(0)
            hit = lambda opens: [o for o in opens if o.intersects(g)]
            wo, do = hit(win_o), hit(door_o)
            if not wo and not do:
                m = prism(pts, 0.0, hh)
            else:
                def cutter(opens):
                    shapes = [o.buffer(0.01, join_style="mitre") for o in opens if o.intersects(g)]
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
            o, matrix, _, _ = openings[iid]
            register(iid, k, [(n, m.apply_transform(matrix)) for n, m in door_parts(o) if m is not None])
        elif k == "window":
            o, matrix, _, _ = openings[iid]
            register(iid, k, [(n, m.apply_transform(matrix)) for n, m in window_parts(o) if m is not None])
        elif k == "room":
            if rw:
                from shapely.geometry import box as _box
                try:
                    g = _box(*it["bbox_px"]).intersection(rw["floor"]).difference(rw["walls_u"]).difference(rw["taken"])
                except Exception:  # GEOS overlay on a degenerate/invalid operand: repair and retry
                    fx = lambda q: q.buffer(0)
                    g = _box(*it["bbox_px"]).intersection(fx(rw["floor"])).difference(fx(rw["walls_u"])).difference(fx(rw["taken"]))
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
    # Segmented walls stop at openings: add masonry to the host wall without
    # creating extra answer items or changing the window/door item identity.
    kinds = {it["item_id"]: it["kind"] for it in pm["items"]}
    for iid, (_, _, footprint, host) in openings.items():
        specs = [(footprint, HEAD, wall_h)]
        if kinds[iid] == "window":
            specs.append((footprint, 0.0, SILL))
        meshes = [prism(g, lo, hi) for g, lo, hi in specs if hi > lo]
        meshes = [m for m in meshes if m is not None]
        if not meshes:
            continue
        infill = _flat(trimesh.util.concatenate(meshes), "wall")
        parent = host if host in items else iid
        scene.add_geometry(infill, node_name=f"wall-infill:{iid}", geom_name=f"wall-infill:{iid}", parent_node_name=parent)
        if parent == host:
            bounds = np.array([items[host]["bbox_m"], infill.bounds])
            items[host]["bbox_m"] = np.round([bounds[:, 0].min(axis=0), bounds[:, 1].max(axis=0)], 4).tolist()
    glb = scene.export(file_type="glb")
    (art / "scene.glb").write_bytes(glb)
    doc = json.loads((art / "doc.json").read_text()) if (art / "doc.json").exists() else {}
    lic = doc.get("licence") or ""
    sc = {"doc_id": doc_id, "glb": "scene.glb", "usdz": None, "units": "m", "up": "Y",
          "origin_offset_m": [round(W * mpp / 2, 4), 0.0, round(H * mpp / 2, 4)],
          "storeys": [{"name": "Floor 1", "elevation_m": 0.0}], "plan_image": f"page-{page}.png",
          "items": items, "source_planmap": f"planmap-{page}.json",
          "defaults": {"wall_m": wall_h, "door_m": DOOR_H, "window_sill_m": SILL, "window_head_m": HEAD},
          "note": "generated for demo: extruded from plan map with default heights; "
                  "stairs only when the plan map has a stairs item (none from raster plans)",
          "publishable": not (lic.startswith("CC-BY-ND") or lic.startswith("GPL"))}
    if approx or rw is not None:  # walls read from pixels or a shell: 3D is approximated from the drawing
        sc["props"] = {"approx": True}
        sc["note"] = "generated for demo: 3D approximated from the drawing"
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
