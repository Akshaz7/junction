"""Geometry-only checks, imported lazily. No bbox-as-area/length shortcuts."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def _scene(path, modified):
    import trimesh
    return trimesh.load(path, force="scene")


def mesh_quantity(path: Path, item_id: str, unit: str, kind: str):
    """Net room footprint or closed-mesh volume from the existing IFC scene.

    GLB is contract Y-up, SI metres. Geometry is reused, never regenerated.
    Missing optional dependencies or corrupt geometry mean no check.
    """
    try:
        import numpy as np
        import trimesh
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        sc = _scene(str(path), path.stat().st_mtime_ns)
        meshes = []
        for node in sc.graph.nodes_geometry:
            if node == item_id or str(node).startswith(item_id + "_"):
                transform, name = sc.graph[node]
                mesh = sc.geometry[name].copy()
                mesh.apply_transform(transform)
                meshes.append(mesh)
        if not meshes:
            return None
        if unit == "m2" and kind in ("room", "space"):
            polys = []
            for mesh in meshes:
                for triangle, normal in zip(mesh.triangles, mesh.face_normals):
                    if normal[1] > 1e-6:
                        p = Polygon(triangle[:, [0, 2]])
                        if p.is_valid and p.area > 0:
                            polys.append(p)
            return float(unary_union(polys).area) if polys else None
        if unit == "m3":
            mesh = trimesh.util.concatenate(meshes)
            if mesh.is_watertight and mesh.is_winding_consistent:
                value = abs(float(mesh.volume))
                return value if np.isfinite(value) else None
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def skeleton_length(mask, metres_per_pixel):
    """Length of a separately extracted *one-pixel skeleton*, 8-connected graph.

    Diagonals with an orthogonal bridge are omitted to avoid triangle double
    counting. Never skeletonize a vector drawing and call that independent.
    """
    import numpy as np
    import math
    a = np.asarray(mask, dtype=bool)
    if a.ndim != 2 or not math.isfinite(metres_per_pixel) or metres_per_pixel <= 0:
        return None
    length = 0.0
    h, w = a.shape
    for y, x in np.argwhere(a):
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            yy, xx = y + dy, x + dx
            if not (0 <= yy < h and 0 <= xx < w and a[yy, xx]):
                continue
            if dy and dx and (a[y, xx] or a[yy, x]):
                continue
            length += math.hypot(dx, dy)
    return length * metres_per_pixel


def floor_net_area(outer, walls, *, openings=()):
    """An explicitly supplied gross floor boundary minus the union of wall solids.

    Inputs must share metric plan coordinates and the same storey. Openings in
    wall solids can be restored. A room union is never substituted for `outer`.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    boundary = Polygon(outer)
    solids = [Polygon(p) for p in walls]
    holes = [Polygon(p) for p in openings]
    if not boundary.is_valid or not all(p.is_valid for p in solids + holes):
        return None
    occupied = unary_union(solids).difference(unary_union(holes))
    return float(boundary.difference(occupied).area)
