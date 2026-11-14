"""Room floor area from the scene GLB when elements.json has no IfcSpace quantity (E-19).

Extruded rooms are prisms: the area of the faces that look down is the net floor area (checked against the
dataset gold on esplanades and molio). Lazy trimesh import (not in the production API image): without it, or
without a GLB, this returns None and the caller abstains as before. Cost 0, no model.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def _scene(glb: str):
    import trimesh
    return trimesh.load(glb, force="scene")


def room_floor_area_m2(glb: Path, item_id: str) -> float | None:
    try:
        sc = _scene(str(glb))
        T, gname = sc.graph[item_id]
        m = sc.geometry[gname].copy()
        m.apply_transform(T)
        down = m.face_normals[:, 1] < -0.7
        a = float(m.area_faces[down].sum())
        if a > 0.05:
            return a
        h = float(m.bounds[1][1] - m.bounds[0][1])
        v = abs(float(m.volume))
        return v / h if h > 0.1 and v > 0.05 else None
    except Exception:  # noqa: BLE001  missing file, node or trimesh: no figure
        return None


def element_volume_m3(glb: Path, item_id: str) -> float | None:
    """Volume of a closed element mesh (walls, slabs) from the scene GLB; None when the mesh is not closed or missing."""
    try:
        sc = _scene(str(glb))
        T, gname = sc.graph[item_id]
        m = sc.geometry[gname].copy()
        m.apply_transform(T)
        v = abs(float(m.volume))
        return v if v > 1e-4 and m.is_watertight else None
    except Exception:  # noqa: BLE001
        return None
