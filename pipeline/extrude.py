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
from shapely import constrained_delaunay_triangles

REPO = Path(__file__).resolve().parent.parent
WALL_H, DOOR_H, SILL, HEAD, FLOOR_T = 2.7, 2.1, 0.9, 2.1, 0.02
COLORS = {"wall": (175, 175, 180, 255), "door": (200, 130, 60, 255), "window": (90, 150, 215, 200),
          "room": (160, 190, 225, 255)}
TEX_MAX = 2048


def usd_name(item_id: str) -> str:
    return "i_" + hashlib.sha1(item_id.encode()).hexdigest()[:16]


def _polys(pts):
    g = Polygon(pts)
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
    g = Polygon(pts_m)
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


def process(doc_id: str, art: Path, page: int = 1) -> dict:
    pm = json.loads((art / f"planmap-{page}.json").read_text())
    W, H = pm["image"]["w"], pm["image"]["h"]
    mpp = pm["scale"]["m_per_px"]
    to_m = lambda p: ((p[0] - W / 2) * mpp, (p[1] - H / 2) * mpp)
    scene = trimesh.Scene()
    items, counts = {}, {}
    # textured floor: the plan image
    img = Image.open(art / f"page-{page}.png").convert("RGB")
    s = TEX_MAX / max(img.size)
    if s < 1:
        img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    hx, hz = W * mpp / 2, H * mpp / 2
    V = np.array([[-hx, 0, -hz], [hx, 0, -hz], [hx, 0, hz], [-hx, 0, hz]], float)
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float)
    floor = trimesh.Trimesh(V, [[0, 2, 1], [0, 3, 2]], process=False)
    floor.vertex_normals = np.tile([0.0, 1.0, 0.0], (4, 1))
    floor.visual = trimesh.visual.TextureVisuals(uv=uv, image=img)
    scene.add_geometry(floor, node_name="plan_floor", geom_name="plan_floor")

    def height_of(it, default):
        return float(it["props"].get("height_m") or default)

    for it in pm["items"]:
        k = it["kind"]
        if k not in ("wall", "door", "window", "room"):
            continue
        poly = it.get("polygon_px") or _bbox_poly(it)
        pts = [to_m(p) for p in poly]
        if k == "wall":
            y0, y1 = 0.0, height_of(it, WALL_H)
        elif k == "door":
            y0, y1 = 0.0, height_of(it, DOOR_H)
        elif k == "window":
            y0, y1 = SILL, HEAD
        else:
            y0, y1 = 0.0, FLOOR_T
        m = prism(pts, y0, y1)
        if m is None:
            continue
        m.visual = trimesh.visual.ColorVisuals(vertex_colors=np.tile(COLORS[k], (len(m.vertices), 1)))
        iid = it["item_id"]
        scene.add_geometry(m, node_name=iid, geom_name=iid)
        counts[k] = counts.get(k, 0) + 1
        items[iid] = {"node": iid, "usd_name": usd_name(iid),
                      "bbox_m": [[round(v, 4) for v in m.bounds[0]], [round(v, 4) for v in m.bounds[1]]],
                      "storey": "Floor 1", "kind": k}
    glb = scene.export(file_type="glb")
    (art / "scene.glb").write_bytes(glb)
    doc = json.loads((art / "doc.json").read_text()) if (art / "doc.json").exists() else {}
    lic = doc.get("licence") or ""
    sc = {"doc_id": doc_id, "glb": "scene.glb", "usdz": None, "units": "m", "up": "Y",
          "origin_offset_m": [round(W * mpp / 2, 4), 0.0, round(H * mpp / 2, 4)],
          "storeys": [{"name": "Floor 1", "elevation_m": 0.0}], "plan_image": f"page-{page}.png",
          "items": items, "source_planmap": f"planmap-{page}.json",
          "defaults": {"wall_m": WALL_H, "door_m": DOOR_H, "window_sill_m": SILL, "window_head_m": HEAD},
          "note": "generated for demo: extruded from plan map with default heights",
          "publishable": not (lic.startswith("CC-BY-ND") or lic.startswith("GPL"))}
    (art / "scene.json").write_text(json.dumps(sc, indent=1))
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
