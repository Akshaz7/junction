"""Wall finish take-off, measured from gross and void-cut IFC side faces.

Heavy dependencies are lazy. No model calls, source mutations, or document-specific
rules. IFC coordinates here are metres, Z up (not the viewer's Y-up coordinates).
Area is the two longitudinal faces, excluding ends, tops, bottoms and reveals.
Geometry precision is a numerical allowance, never a promise about model accuracy.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class MeasurementUnavailable(ValueError):
    """Missing or ambiguous geometry; do not substitute a guessed exact area."""


@dataclass
class Face:
    area: float
    vertices: object
    triangles: object
    normal: object
    origin: object
    u: object
    v: object
    planar: bool
    polygon: object
    side: int = 0


def _faces(shape, settings, tolerance):
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    out = []
    for face in shape.facets():
        mesh = face.triangulate(settings)
        verts = np.asarray(mesh.verts).reshape(-1, 3)
        tris = np.asarray(mesh.faces).reshape(-1, 3)
        if not len(tris):
            continue
        cross = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
        lengths = np.linalg.norm(cross, axis=1)
        good = lengths > tolerance ** 2
        if not good.any():
            continue
        tris, cross, lengths = tris[good], cross[good], lengths[good]
        k = int(lengths.argmax())
        n = cross[k] / lengths[k]
        origin = verts[tris[k, 0]]
        u = verts[tris[k, 1]] - origin
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        planar = bool(np.max(np.abs((verts - origin) @ n)) <= tolerance * 4)
        polygon = None
        if planar:
            xy = np.column_stack(((verts - origin) @ u, (verts - origin) @ v))
            polygon = unary_union([Polygon(xy[t]) for t in tris])
        area = float(face.area().to_double())
        if not math.isfinite(area) or area < 0:
            raise MeasurementUnavailable("Wall surface area is not finite")
        out.append(Face(area, verts, tris, n, origin, u, v, planar, polygon))
    return out


def _shape(settings, element):
    import ifcopenshell.geom
    reps = getattr(getattr(element, "Representation", None), "Representations", ()) or ()
    if not any((r.RepresentationType or "").casefold() not in ("curve2d", "curve3d", "boundingbox", "geometriccurveset") for r in reps):
        raise MeasurementUnavailable("No wall/void body: only an axis or bounding box is recorded")
    result = ifcopenshell.geom.create_shape(settings, element)
    if result is None or result.geometry.size() == 0:
        raise MeasurementUnavailable("No solid body representation")
    solid = result.geometry.item(0)
    for index in range(1, result.geometry.size()):
        # Boolean union removes shared interfaces between wall layers and joins
        # exporters' multiple void solids. Summing their faces would overcount.
        solid = solid.add(result.geometry.item(index))
    return result, solid  # retain the owner of the native shape


def _points(curve):
    if curve.is_a("IfcPolyline"):
        return [list(p.Coordinates) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve"):
        pts = [list(p) for p in curve.Points.CoordList]
        if not curve.Segments:
            return pts
        if all(s.is_a("IfcLineIndex") for s in curve.Segments):
            return [pts[i - 1] for s in curve.Segments for i in s.wrappedValue]
    if curve.is_a("IfcCompositeCurve"):
        pts = []
        for s in curve.Segments:
            part = _points(s.ParentCurve)
            pts.extend(part if s.SameSense else part[::-1])
        return pts
    if curve.is_a("IfcTrimmedCurve") and curve.BasisCurve.is_a("IfcLine"):
        a = next((p for p in curve.Trim1 if p.is_a("IfcCartesianPoint")), None)
        b = next((p for p in curve.Trim2 if p.is_a("IfcCartesianPoint")), None)
        if a and b:
            pts = [list(a.Coordinates), list(b.Coordinates)]
            return pts if curve.SenseAgreement else pts[::-1]
    raise MeasurementUnavailable("Boundary/axis curve is not a supported polygon")


def _placement(element, scale):
    import numpy as np
    from ifcopenshell.util.placement import get_local_placement
    matrix = get_local_placement(element.ObjectPlacement) if element.ObjectPlacement else np.eye(4)
    matrix = matrix.copy()
    matrix[:3, 3] *= scale
    return matrix


def _axis(wall, faces, scale, tolerance):
    import numpy as np
    from ifcopenshell.util.placement import get_axis2placement
    matrix = _placement(wall, scale)
    for rep in wall.Representation.Representations:
        if (rep.RepresentationIdentifier or "").casefold() != "axis" or len(rep.Items) != 1:
            continue
        curve = rep.Items[0]
        base = curve.BasisCurve if curve.is_a("IfcTrimmedCurve") else curve
        if base.is_a("IfcCircle"):
            local = get_axis2placement(base.Position).copy()
            local[:3, 3] *= scale
            circle = matrix @ local
            if abs(circle[2, 2]) < 1 - 1e-6:
                raise MeasurementUnavailable("Tilted curved axis needs a surface classifier")
            return {"kind": "circle", "origin": circle[:3, 3], "radius": base.Radius * scale, "source": "IFC axis"}
        try:
            pts = np.array([list(p[:3]) + [0.] * (3 - len(p)) for p in _points(curve)]) * scale
        except MeasurementUnavailable:
            continue
        pts = pts @ matrix[:3, :3].T + matrix[:3, 3]
        direction = pts[-1] - pts[0]
        direction[2] = 0
        if np.linalg.norm(direction) <= tolerance:
            continue
        direction /= np.linalg.norm(direction)
        normal = np.array([-direction[1], direction[0], 0.])
        if np.max(np.abs((pts - pts[0]) @ normal)) > tolerance * 4:
            continue
        return {"kind": "line", "origin": pts[0], "normal": normal, "source": "IFC axis"}
    # Some exporters omit Axis. PCA determines a likely straight direction, but
    # the answer explicitly remains an estimate when that direction was inferred.
    xy = np.concatenate([f.vertices for f in faces])[:, :2]
    vals, vectors = np.linalg.eigh(np.cov(xy.T))
    if vals[-1] <= 4 * max(vals[0], tolerance ** 2):
        raise MeasurementUnavailable("Wall has no unambiguous longitudinal axis")
    normal = np.r_[vectors[:, 0], 0.]
    return {"kind": "line", "origin": np.r_[xy.mean(0), 0.], "normal": normal, "source": "inferred from body"}


def _side_faces(faces, axis, tolerance, references=None):
    import numpy as np
    chosen = []
    for f in faces:
        xyz = f.vertices[f.triangles]
        cross = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
        xy_norm = np.linalg.norm(cross[:, :2], axis=1)
        norm = np.linalg.norm(cross, axis=1)
        # Horizontal caps are not wall finish. Inclined longitudinal sides remain.
        if np.any(xy_norm <= norm * 1e-6):
            continue
        normals = cross[:, :2] / xy_norm[:, None]
        if axis["kind"] == "line":
            aligned = np.abs(normals @ axis["normal"][:2]) > 1 - 1e-6
        else:
            radial = xyz.mean(1)[:, :2] - axis["origin"][:2]
            radial /= np.maximum(np.linalg.norm(radial, axis=1)[:, None], tolerance)
            aligned = np.abs(np.sum(normals * radial, axis=1)) > 0.999
        if not aligned.all():
            continue
        if references is not None:
            matches = []
            for ref in references:
                if f.planar and ref.planar:
                    distance = np.max(np.abs((f.vertices - ref.origin) @ ref.normal))
                elif not f.planar and not ref.planar and axis["kind"] == "circle":
                    r1 = np.linalg.norm(f.vertices[:, :2] - axis["origin"][:2], axis=1).mean()
                    r2 = np.linalg.norm(ref.vertices[:, :2] - axis["origin"][:2], axis=1).mean()
                    distance = abs(r1 - r2)
                else:
                    continue
                if distance <= tolerance * 8:
                    matches.append(ref)
            if not matches:
                continue  # reveal / niche back, rather than an original side face
            # Disconnected patches can share a plane but belong to different
            # sides (e.g. a roof-cut wall). Plane coincidence alone is not a
            # correspondence: use the actual overlapping surface region.
            if f.planar:
                matches.sort(key=lambda ref: ref.polygon.intersection(
                    _project(ref, f.vertices, f.triangles)).area, reverse=True)
            f.side = matches[0].side
        chosen.append(f)
    if references is None:
        if axis["kind"] == "line":
            offsets = [float((f.vertices.mean(0) - axis["origin"]) @ axis["normal"]) for f in chosen]
        else:
            offsets = [float(np.linalg.norm(f.vertices[:, :2] - axis["origin"][:2], axis=1).mean()) for f in chosen]
        if not offsets or max(offsets) - min(offsets) <= tolerance * 4:
            raise MeasurementUnavailable("Could not identify both wall sides")
        mid = (max(offsets) + min(offsets)) / 2
        for f, offset in zip(chosen, offsets):
            f.side = int(offset > mid)
    return chosen


def _clip(points, bound, above):
    """Sutherland-Hodgman clipping in 3D against an elevation plane."""
    out = []
    for a, b in zip(points, points[1:] + points[:1]):
        ina = a[2] >= bound if above else a[2] <= bound
        inb = b[2] >= bound if above else b[2] <= bound
        if ina:
            out.append(a)
        if ina != inb:
            t = (bound - a[2]) / (b[2] - a[2])
            out.append(a + t * (b - a))
    return out


def _mesh_area(face, low=-math.inf, high=math.inf):
    import numpy as np
    area = 0.
    for tri in face.triangles:
        pts = list(face.vertices[tri])
        if math.isfinite(low):
            pts = _clip(pts, low, True)
        if math.isfinite(high) and pts:
            pts = _clip(pts, high, False)
        for k in range(1, len(pts) - 1):
            area += float(np.linalg.norm(np.cross(pts[k] - pts[0], pts[k + 1] - pts[0]))) / 2
    return area


def _band_polygon(face, region, low, high):
    import numpy as np
    from shapely.geometry import Polygon
    if region.is_empty:
        return region
    x0, y0, x1, y1 = region.bounds
    xy = [(x0 - 1, y0 - 1), (x1 + 1, y0 - 1), (x1 + 1, y1 + 1), (x0 - 1, y1 + 1)]
    pts = [face.origin + x * face.u + y * face.v for x, y in xy]
    if math.isfinite(low):
        pts = _clip(pts, low, True)
    if math.isfinite(high) and pts:
        pts = _clip(pts, high, False)
    if len(pts) < 3:
        return Polygon()
    pts = np.array(pts) - face.origin
    return region.intersection(Polygon(np.column_stack((pts @ face.u, pts @ face.v))))


def _area(face, low=-math.inf, high=math.inf):
    mesh = _mesh_area(face)
    return face.area * _mesh_area(face, low, high) / mesh if mesh else 0.


def _project(face, vertices, triangles):
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    xy = np.column_stack(((vertices - face.origin) @ face.u, (vertices - face.origin) @ face.v))
    return unary_union([Polygon(xy[t]) for t in triangles if Polygon(xy[t]).area > 0])


def _boundary_polygon(boundary, scale):
    import numpy as np
    from ifcopenshell.util.placement import get_axis2placement
    geom = boundary.ConnectionGeometry
    surface = getattr(geom, "SurfaceOnRelatingElement", None) if geom else None
    if surface is None or not surface.is_a("IfcCurveBoundedPlane"):
        raise MeasurementUnavailable("No polygonal room boundary")
    plane = get_axis2placement(surface.BasisSurface.Position).copy()
    plane[:3, 3] *= scale
    matrix = _placement(boundary.RelatingSpace, scale) @ plane
    def world(curve):
        pts = np.array([p[:2] for p in _points(curve)]) * scale
        return pts @ matrix[:3, :2].T + matrix[:3, 3]
    return world(surface.OuterBoundary), [world(c) for c in (surface.InnerBoundaries or ())]


def _quantities(wall, model):
    """Respect explicit area units as well as the project's area unit."""
    from ifcopenshell.util.element import get_psets
    from ifcopenshell.util.unit import calculate_unit_scale, convert, get_project_unit
    psets = get_psets(wall, qtos_only=True)
    out = {}
    for name, values in psets.items():
        definition = model.by_id(values["id"])
        for q in getattr(definition, "Quantities", ()):
            if q.is_a("IfcQuantityArea") and q.Name in ("GrossSideArea", "NetSideArea"):
                if q.Unit:
                    value = convert(q.AreaValue, getattr(q.Unit, "Prefix", None), q.Unit.Name, None, "SQUARE_METRE")
                else:
                    factor = calculate_unit_scale(model, "AREAUNIT") if get_project_unit(model, "AREAUNIT") else calculate_unit_scale(model) ** 2
                    value = q.AreaValue * factor
                if value >= 0 and math.isfinite(value):
                    out[q.Name] = float(value)
    return out


def _external(wall, boundaries):
    from ifcopenshell.util.element import get_psets
    for props in get_psets(wall, psets_only=True).values():
        v = props.get("IsExternal")
        if isinstance(v, bool):
            return v, "IsExternal"
        if v in ("TRUE", "FALSE", "true", "false", 0, 1):
            return v in ("TRUE", "true", 1), "IsExternal"
    enums = {b.InternalOrExternalBoundary for b in boundaries}
    if any(str(e).startswith("EXTERNAL") for e in enums):
        return True, "space boundary"
    spaces = {b.RelatingSpace.id() for b in boundaries if b.RelatingSpace and b.InternalOrExternalBoundary == "INTERNAL"}
    if len(spaces) >= 2:
        return False, "two room boundaries"
    return None, "not recorded"


def _bands(model, scale):
    from ifcopenshell.util.element import get_aggregate
    storeys = []
    for s in model.by_type("IfcBuildingStorey"):
        elevation = float(_placement(s, scale)[2, 3]) if s.ObjectPlacement else float(s.Elevation or 0) * scale
        parent = get_aggregate(s)
        while parent and not parent.is_a("IfcBuilding"):
            parent = get_aggregate(parent)
        storeys.append({"item_id": s.GlobalId, "name": s.Name or "Unnamed floor", "elevation_m": elevation,
                        "building_id": parent.GlobalId if parent else None})
    # Do not conflate two buildings' coincident storeys. Use containment when
    # elevations collide; cross-storey clipping then has no unambiguous mapping.
    return sorted(storeys, key=lambda x: x["elevation_m"])


def _rooms_for_wall(boundaries, gross, net, scale, tolerance):
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    rooms, inward = [], set()
    for b in boundaries:
        try:
            outer, holes = _boundary_polygon(b, scale)
            candidates = []
            for face in gross:
                if not face.planar:
                    continue
                distance = float(np.max(np.abs((outer - face.origin) @ face.normal)))
                candidates.append((distance, face))
            if not candidates:
                continue
            candidates.sort(key=lambda x: x[0])
            distance, face = candidates[0]
            # Boundary must lie on the actual wall surface. A centreline boundary
            # cannot establish which side faces this room.
            if distance > tolerance * 8:
                continue
            inward.add(face.side)
            def xy(points, face=face):
                return np.column_stack(((points - face.origin) @ face.u, (points - face.origin) @ face.v))
            region = Polygon(xy(outer), [xy(h) for h in holes])
            if not region.is_valid:
                continue
            region = region.intersection(face.polygon)
            cut = unary_union([_project(face, f.vertices, f.triangles) for f in net if f.planar and
                               np.max(np.abs((f.vertices - face.origin) @ face.normal)) <= tolerance * 8])
            actual = region.intersection(cut)
            if region.area > tolerance ** 2:
                rooms.append({"room_id": b.RelatingSpace.GlobalId,
                              "name": b.RelatingSpace.LongName or b.RelatingSpace.Name or "Unnamed room",
                              "face": face, "gross": region, "net": actual, "boundary_id": b.GlobalId})
        except (MeasurementUnavailable, RuntimeError, ValueError, AttributeError, TypeError):
            continue
    return rooms, (next(iter(inward)) if len(inward) == 1 else None)


def measure_ifc(path: str | Path) -> dict:
    """Read a real IFC; return JSON-safe per-wall/per-storey measurements.

    Whole-wall analytic areas come from native BRep faces. Curved storey splits
    use the mesh area fraction and are explicitly estimates. Missing walls are
    reported and the measured subtotal is never presented as a building total.
    """
    import ifcopenshell
    import ifcopenshell.geom
    import numpy as np
    from ifcopenshell import ifcopenshell_wrapper as wrapper
    from ifcopenshell.util.element import get_container, get_material, get_type
    from ifcopenshell.util.unit import calculate_unit_scale, get_project_unit

    model = ifcopenshell.open(str(path))
    if get_project_unit(model, "LENGTHUNIT") is None:
        raise MeasurementUnavailable("No length unit is declared in the IFC")
    scale = calculate_unit_scale(model)
    contexts = [c for c in model.by_type("IfcGeometricRepresentationContext") if not c.is_a("IfcGeometricRepresentationSubContext")]
    precision = max([float(c.Precision) * scale for c in contexts if c.Precision and c.Precision > 0] or [1e-5])
    settings = ifcopenshell.geom.settings()
    settings.set("iterator-output", wrapper.NATIVE)
    settings.set("use-world-coords", True)
    settings.set("precision", precision)
    settings.set("context-identifiers", ["Body"])
    gross_settings = ifcopenshell.geom.settings()
    for name in ("iterator-output", "use-world-coords", "precision", "context-identifiers"):
        gross_settings.set(name, settings.get(name))
    gross_settings.set("disable-opening-subtractions", True)
    storeys = _bands(model, scale)
    boundaries = {}
    for b in model.by_type("IfcRelSpaceBoundary"):
        e = b.RelatedBuildingElement
        if e and e.is_a("IfcWall"):
            boundaries.setdefault(e.GlobalId, []).append(b)
    result = {"schema": model.schema, "length_unit_to_m": scale, "precision_m": precision,
              "storeys": storeys, "walls": [], "skipped": [], "source": "IFC body side faces",
              "applications": [a.ApplicationFullName for a in model.by_type("IfcApplication")]}
    for assembly in model.by_type("IfcCurtainWall"):
        result["skipped"].append({"item_id": assembly.GlobalId, "reason": "Curtain-wall assemblies need a separate frame/glazing take-off; excluded from solid wall finishes"})
    for wall in model.by_type("IfcWall"):
        try:
            _owner_g, body_g = _shape(gross_settings, wall)
            gross_all = _faces(body_g, gross_settings, precision)
            axis = _axis(wall, gross_all, scale, precision)
            gross = _side_faces(gross_all, axis, precision)
            _owner_n, body_n = _shape(settings, wall)
            net = _side_faces(_faces(body_n, settings, precision), axis, precision, gross)
            if not net:
                raise MeasurementUnavailable("Void-cut wall has no matching side faces")
            container = get_container(wall, ifc_class="IfcBuildingStorey")
            wall_boundaries = boundaries.get(wall.GlobalId, [])
            rooms, inward = _rooms_for_wall(wall_boundaries, gross, net, scale, precision)
            external, flag_source = _external(wall, wall_boundaries)
            typ = get_type(wall)
            mat = get_material(wall, should_skip_usage=True)
            materials = []
            if mat:
                for e in model.traverse(mat):
                    if e.is_a("IfcMaterial") and e.Name and e.Name not in materials:
                        materials.append(e.Name)
            row = {"item_id": wall.GlobalId, "name": wall.Name or "Wall", "type": typ.Name if typ else None,
                   "materials": materials, "is_external": external, "classification_source": flag_source,
                   "axis_source": axis["source"], "inside_side": inward if external else None,
                   "height_m": float(max(f.vertices[:, 2].max() for f in gross) - min(f.vertices[:, 2].min() for f in gross)),
                   "openings": [], "floors": [], "rooms": [], "quantities": _quantities(wall, model),
                   "curved": any(not f.planar for f in gross), "notes": []}
            # Area removed is measured once from the boolean result, not the sum
            # of nominal opening sizes. Per-opening allocations intersect that
            # removed region and consume it once, even for overlapping voids.
            removed, kept_regions = [], {}
            for face in gross:
                if face.planar:
                    from shapely.ops import unary_union
                    matching = [f for f in net if f.planar and
                                np.max(np.abs((f.vertices - face.origin) @ face.normal)) <= precision * 8]
                    kept = face.polygon.intersection(unary_union([
                        _project(face, f.vertices, f.triangles) for f in matching]))
                    kept_regions[id(face)] = kept
                    removed.append([face, face.polygon.difference(kept)])
            for rel in wall.HasOpenings:
                opening = rel.RelatedOpeningElement
                fills = [r.RelatedBuildingElement for r in opening.HasFillings]
                record = {"item_id": opening.GlobalId, "fill_ids": [e.GlobalId for e in fills],
                          "kind": "window" if any(e.is_a("IfcWindow") for e in fills) else "door" if any(e.is_a("IfcDoor") for e in fills) else "opening",
                          "floors": [], "deducted_m2": None}
                try:
                    _op_owner, op_shape = _shape(gross_settings, opening)
                    op_mesh = op_shape.triangulate(gross_settings)
                    op_vertices = np.asarray(op_mesh.verts).reshape(-1, 3)
                    op_tris = np.asarray(op_mesh.faces).reshape(-1, 3)
                    bounds = op_vertices.max(0) - op_vertices.min(0)
                    record["height_m"] = float(bounds[2])
                    record["bottom_m"] = float(op_vertices[:, 2].min())
                    record["top_m"] = float(op_vertices[:, 2].max())
                    if axis["kind"] == "line":
                        tangent = np.array([axis["normal"][1], -axis["normal"][0], 0])
                        x = op_vertices @ tangent
                        record["width_m"] = float(x.max() - x.min())
                    allocations = []
                    for f, remaining in removed:
                        footprint = _project(f, op_vertices, op_tris)
                        part = remaining.intersection(footprint)
                        allocations.append((f, part))
                        # In-place remaining region for the next opening.
                        for entry in removed:
                            if entry[0] is f:
                                entry[1] = remaining.difference(part)
                    record["deducted_m2"] = sum(p.area for _, p in allocations) if len(removed) == len(gross) else None
                    record["_allocations"] = allocations
                except (RuntimeError, ValueError, AttributeError):
                    row["notes"].append("An opening has no measurable outline; its total cut is still in the wall geometry")
                row["openings"].append(record)
            container_id = container.GlobalId if container else None
            building = get_container(wall, ifc_class="IfcBuilding")
            relevant = storeys
            if building:
                relevant = [s for s in storeys if s.get("building_id") == building.GlobalId]
            if not relevant:
                relevant = [{"item_id": container_id, "name": container.Name if container else "Unassigned floor", "elevation_m": 0.}]
            elevations = [s["elevation_m"] for s in relevant]
            collisions = len(set(elevations)) != len(elevations)
            if collisions:
                relevant = [s for s in relevant if s["item_id"] == container_id]
                row["notes"].append("Coincident floor elevations; wall assigned by containment without height splitting")
            for k, st in enumerate(relevant):
                low = st["elevation_m"] if k and not collisions else -math.inf
                high = relevant[k + 1]["elevation_m"] if k + 1 < len(relevant) and not collisions else math.inf
                def surface_area(face, region):
                    return (_band_polygon(face, region, low, high).area * face.area / face.polygon.area
                            if face.polygon.area else 0.)
                g = [sum(surface_area(f, f.polygon) if f.planar else _area(f, low, high)
                         for f in gross if f.side == side) for side in (0, 1)]
                # Measure retained regions on each original face. A merged cut
                # face may overlap several gross patches; assigning its entire
                # area to a single reference would move area between sides.
                n = [sum(surface_area(f, kept_regions[id(f)]) for f in gross if f.side == side and f.planar)
                     + sum(_area(f, low, high) for f in net if f.side == side and not f.planar)
                     for side in (0, 1)]
                if sum(g) <= precision ** 2:
                    continue
                if sum(n) > sum(g) + precision * sum(math.sqrt(f.area) * 4 for f in gross):
                    raise MeasurementUnavailable("Cut side area exceeds gross side area")
                for side in (0, 1):
                    if n[side] > g[side] + precision ** 2:
                        raise MeasurementUnavailable("Unattributed cut surface exceeds its gross face")
                    n[side] = min(g[side], n[side])
                allowance = sum(abs(f.area - _mesh_area(f)) + precision * (f.polygon.length if f.planar else 4 * math.sqrt(f.area)) for f in gross + net)
                category = "external" if external else "internal" if external is False else "unclassified"
                floor = {"storey_id": st["item_id"], "storey": st["name"], "gross_m2": sum(g), "net_m2": sum(n),
                         "opening_m2": max(0., sum(g) - sum(n)), "gross_sides_m2": g, "net_sides_m2": n,
                         "category": category, "numerical_allowance_m2": allowance,
                         "facade_m2": n[1 - inward] if external and inward is not None else None,
                         "external_inside_m2": n[inward] if external and inward is not None else None,
                         "internal_both_m2": sum(n) if external is False else None}
                if external and inward is None:
                    # With no oriented boundary, either side may be outside.
                    # The midpoint and half-range bound that ambiguity without
                    # guessing a building centre (which fails at courtyards).
                    floor["facade_m2"] = floor["external_inside_m2"] = sum(n) / 2
                    floor["orientation_allowance_m2"] = abs(n[0] - n[1]) / 2
                    floor["orientation_unresolved"] = True
                else:
                    floor["orientation_allowance_m2"] = 0.
                    floor["orientation_unresolved"] = False
                row["floors"].append(floor)
                if axis["kind"] == "line":
                    tangent = np.array([axis["normal"][1], -axis["normal"][0], 0])
                    floor["extent_gross_m2"] = sum(float(np.ptp(f.vertices @ tangent)) * max(0., min(float(f.vertices[:, 2].max()), high) - max(float(f.vertices[:, 2].min()), low)) for f in gross)
                for op in row["openings"]:
                    allocations = op.get("_allocations", [])
                    check_area = 2 * op["width_m"] * max(0., min(high, op["top_m"]) - max(low, op["bottom_m"])) if "width_m" in op else None
                    op["floors"].append({"storey_id": st["item_id"], "deducted_m2": sum(_band_polygon(f, p, low, high).area for f, p in allocations) if op["deducted_m2"] is not None else None,
                                         "rectangle_check_m2": check_area})
                if axis["kind"] == "line" and all(o["floors"][-1]["rectangle_check_m2"] is not None for o in row["openings"]):
                    floor["rectangle_opening_check_m2"] = sum(o["floors"][-1]["rectangle_check_m2"] for o in row["openings"])
                    floor["extent_net_check_m2"] = floor["extent_gross_m2"] - floor["rectangle_opening_check_m2"]
                # Duplicate space-boundary records (e.g. first/second level) must
                # not duplicate a room finish. Union before taking the area.
                groups = {}
                for r in rooms:
                    key = (r["room_id"], id(r["face"]))
                    groups.setdefault(key, []).append(r)
                for group in groups.values():
                    from shapely.ops import unary_union
                    r = group[0]
                    rg = _band_polygon(r["face"], unary_union([x["gross"] for x in group]), low, high).area
                    rn = _band_polygon(r["face"], unary_union([x["net"] for x in group]), low, high).area
                    if rg > precision ** 2:
                        row["rooms"].append({"room_id": r["room_id"], "name": r["name"], "storey_id": st["item_id"],
                                             "storey": st["name"], "gross_m2": rg, "opening_m2": max(0., rg - rn), "net_m2": rn,
                                             "numerical_allowance_m2": allowance})
            for op in row["openings"]:
                op.pop("_allocations", None)
            row["gross_m2"] = sum(f["gross_m2"] for f in row["floors"])
            row["net_m2"] = sum(f["net_m2"] for f in row["floors"])
            row["opening_m2"] = row["gross_m2"] - row["net_m2"]
            row["opening_unallocated_m2"] = max(0., row["opening_m2"] - sum(o["deducted_m2"] or 0 for o in row["openings"]))
            # Independent straight-wall check: axis-aligned extent x height.
            # Mitres, slopes and irregular profiles legitimately disagree.
            if axis["kind"] == "line":
                tangent = np.array([axis["normal"][1], -axis["normal"][0], 0])
                row["extent_gross_m2"] = sum(float(np.ptp(f.vertices @ tangent) * np.ptp(f.vertices[:, 2])) for f in gross)
            checks = []
            for key, measured in (("GrossSideArea", row["gross_m2"] / 2), ("NetSideArea", row["net_m2"] / 2)):
                if key in row["quantities"]:
                    q = row["quantities"][key]
                    checks.append({"quantity": key, "stored_m2": q, "measured_one_side_mean_m2": measured,
                                   "difference_m2": measured - q, "difference_pct": 100 * abs(measured - q) / q if q else None})
            row["checks"] = checks
            result["walls"].append(row)
        except (RuntimeError, ValueError, AttributeError, TypeError, IndexError) as exc:
            result["skipped"].append({"item_id": wall.GlobalId, "reason": str(exc)[:160]})
    return _reconcile_sides(result)


@lru_cache(maxsize=4)
def _cached_ifc(path, size, mtime_ns):
    return measure_ifc(path)


def load_ifc(path):
    path = Path(path).resolve()
    stat = path.stat()
    return copy.deepcopy(_cached_ifc(str(path), stat.st_size, stat.st_mtime_ns))


def _source(doc_id, root):
    directory = Path(root) / doc_id
    meta = json.loads((directory / "doc.json").read_text()) if (directory / "doc.json").exists() else {}
    repo = Path(__file__).resolve().parents[1]
    for p in directory.glob("source.*"):
        if p.suffix.casefold() == ".ifc" and p.is_file():
            return p
    for kind, rel in (meta.get("files") or {}).items():
        if kind.casefold() != "ifc":
            continue
        for base in (repo, repo / "data/full/junction-dataset", repo / "data/junction-dataset-preview", directory):
            p = base / rel
            if p.is_file():
                return p
    return None


WALLGEOM = "wallgeom.json"


def _reconcile_sides(data):
    """Handle legacy face assignments without changing measured building totals.

    No removed area means each side is unchanged. With real cuts and no face
    attribution, use the existing unresolved-orientation midpoint convention;
    retain the original operands and the unattributed cut in the audit trail.
    """
    for wall in data["walls"]:
        for floor in wall["floors"]:
            gross, net = floor.get("gross_sides_m2"), floor.get("net_sides_m2")
            if gross is None or net is None or not any(n > g for g, n in zip(gross, net)):
                continue
            excess = sum(max(0., n - g) for g, n in zip(gross, net))
            if excess <= 1e-9:
                floor["net_sides_m2"] = [min(g, n) for g, n in zip(gross, net)]
                continue
            cut = floor["gross_m2"] - floor["net_m2"]
            if cut < -1e-9:
                raise MeasurementUnavailable("Stored cut area exceeds gross wall area")
            audit = {"item_id": wall["item_id"], "storey_id": floor["storey_id"],
                     "area_m2": max(0., cut), "side_transfer_m2": excess,
                     "gross_sides_m2": list(gross), "net_sides_m2": list(net),
                     "reason": "Legacy coplanar face correspondence moved retained area between sides"}
            data.setdefault("unattributed", []).append(audit)
            if abs(cut) <= 1e-9:
                floor["net_sides_m2"] = list(gross)
                audit["resolution"] = "No removed area: both net sides equal their gross sides"
            else:
                floor["gross_sides_m2"] = [floor["gross_m2"] / 2] * 2
                floor["net_sides_m2"] = [floor["net_m2"] / 2] * 2
                wall["inside_side"] = None
                floor["orientation_unresolved"] = True
                floor["orientation_allowance_m2"] = floor["gross_m2"] / 2
                audit["resolution"] = "Cut unattributed to a side; unresolved-orientation midpoint estimate"
                note = "Some cuts are unattributed to a wall face; side finishes use a midpoint estimate"
                if note not in wall.setdefault("notes", []):
                    wall["notes"].append(note)
            if wall["is_external"]:
                side = wall.get("inside_side")
                ns = floor["net_sides_m2"]
                floor["external_inside_m2"] = ns[side] if side is not None else floor["net_m2"] / 2
                floor["facade_m2"] = ns[1 - side] if side is not None else floor["net_m2"] / 2
    return data


def _wallgeom(doc_id, root):
    """Stored measure_ifc result (built at ingest/backfill) so deployments without the IFC can still answer."""
    path = Path(root) / doc_id / WALLGEOM
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return _reconcile_sides(data) if isinstance(data, dict) and data.get("walls") is not None and data.get("storeys") is not None else None


def build_wallgeom(doc_dir, source):
    """Write wallgeom.json beside the document's other artifacts; returns the measurement."""
    measured = measure_ifc(source)
    tmp = Path(doc_dir) / (WALLGEOM + ".tmp")
    tmp.write_text(json.dumps(measured, allow_nan=False))
    tmp.replace(Path(doc_dir) / WALLGEOM)
    return measured


def wants_wallarea(question):
    q = (question or "").casefold()
    if re.search(r"\b(?:plasterboard|drywall|gypsum board|wallboard|facade|façade)\b", q):
        return not bool(re.search(r"\b(?:thickness|fire rating|material is|made of|how many walls)\b", q))
    return bool(re.search(r"\bwalls?\b", q) and re.search(r"\b(?:area|surface|paint|render|cladding|insulation|take.?off|sheets? (?:of|needed|required|to buy|to order))\b", q))


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def _stated_height(text):
    m = re.search(r"(?:wall\s+height|ceiling\s+height|storey\s+height|room\s+height|raumh[oö]he|huonekorkeus|rumsh[oö]jd|height|walls?\s+(?:are|is))\s*(?:of|is|=|:)?\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|metres?|meters?|m|ft|feet)\b", text, re.I)
    if not m:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(mm|cm|m|ft|feet)\s+(?:high|tall)\b", text, re.I)
    if not m:
        return None
    return float(m[1].replace(",", ".")) * {"mm": .001, "cm": .01, "ft": .3048, "feet": .3048}.get(m[2].lower(), 1.)


def estimate_planmaps(doc_id, root, question):
    """Conditional 2D estimate; no hidden height/scale accuracy percentages.

    Needs source lengths or a page scale. Rectangular outlines and centrelines
    are supported. Complex closed wall networks are reported as unsupported,
    rather than measured as one enormous bounding rectangle.
    """
    from shapely.geometry import LineString, Polygon, box
    from shapely.ops import unary_union
    directory = Path(root) / doc_id
    out = {"source": "2D plan estimate", "walls": [], "skipped": [], "storeys": [], "assumptions": [], "precision_m": 0.}
    for path in sorted(directory.glob("planmap-[0-9]*.json")):
        pm = json.loads(path.read_text())
        page = int(pm.get("page") or 1)
        sc = pm.get("scale") or {}
        mpp = _number(sc.get("m_per_px"))
        label = pm.get("storey") or f"Page {page}"
        label = label.get("name") if isinstance(label, dict) else label
        st = {"item_id": str(page), "name": label, "elevation_m": page - 1}
        out["storeys"].append(st)
        height = _stated_height(question)
        height_source = "stated in question" if height else None
        if not height:
            heights = set()
            text_paths = [directory / f"text-{page}.json"]
            for tp in text_paths:
                if tp.exists():
                    data = json.loads(tp.read_text())
                    text = data.get("text") or " ".join(str(w.get("text") or "") for w in data.get("words", []))
                    value = _stated_height(text)
                    if value:
                        heights.add(value)
            if len(heights) == 1:
                height, = heights
                height_source = "printed height"
        if not height:
            height, height_source = 2.7, "assumed; no wall height found"
        page_rows = []
        for it in pm.get("items", []):
            if it.get("kind") != "wall":
                continue
            props = it.get("props") or {}
            if props.get("derived") == "room-outline":
                out["skipped"].append({"item_id": it.get("item_id"), "reason": "Room detection rectangle, not a measured wall"})
                continue
            pts = props.get("centerline_px") or it.get("polygon_px")
            if not pts and it.get("bbox_px"):
                x0, y0, x1, y1 = it["bbox_px"]
                # A slender detected wall box can supply an explicit rectangle
                # estimate; a whole network/square box cannot define an axis.
                if min(x1 - x0, y1 - y0) > 0 and max(x1 - x0, y1 - y0) > 2 * min(x1 - x0, y1 - y0):
                    pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            length = _number(props.get("length_m"))
            thick = _number(props.get("thickness_m") or props.get("width_m"))
            h = _number(props.get("height_m")) or height
            method = "source length" if length else ""
            line = None
            if pts and len(pts) >= 2 and mpp:
                coords = [(float(x) * mpp, float(y) * mpp) for x, y in pts]
                if props.get("centerline_px") or len(coords) == 2:
                    line = LineString(coords)
                    length = length or line.length
                    method = "centreline length"
                else:
                    poly = Polygon(coords)
                    if poly.is_valid and poly.area > 0:
                        rect = poly.minimum_rotated_rectangle
                        c = list(rect.exterior.coords)
                        lengths = [math.dist(c[k], c[k + 1]) for k in range(4)]
                        long, short = max(lengths), min(lengths)
                        # Source pixel rounding may move each edge by a pixel.
                        if rect.area - poly.area <= poly.length * mpp:
                            k = lengths.index(long)
                            a, b = c[k], c[k + 1]
                            d, e = c[(k + 3) % 4], c[(k + 2) % 4]
                            line = LineString([((a[0] + d[0]) / 2, (a[1] + d[1]) / 2), ((b[0] + e[0]) / 2, (b[1] + e[1]) / 2)])
                            length = length or long
                            thick = thick or short
                            method = "rectangular wall outline"
            if not length or h <= 0:
                out["skipped"].append({"item_id": it.get("item_id"), "reason": "No scaled straight wall length/outline"})
                continue
            external = props.get("is_external") if isinstance(props.get("is_external"), bool) else None
            row = {"item_id": it["item_id"], "name": it.get("label") or "Wall", "type": props.get("type_name"),
                   "materials": [props["material"]] if props.get("material") else [], "is_external": external,
                   "height_m": h, "length_m": length, "height_source": "wall data" if props.get("height_m") else height_source,
                   "axis_source": method, "quantities": {}, "checks": [], "curved": False, "rooms": [], "openings": [],
                   "page": page, "floors": [], "notes": [], "_line": line, "_thickness": thick,
                   "_holes": [], "scale_relative_error": sc.get("relative_error"), "scale_method": sc.get("method")}
            row["_floor"] = {"storey_id": str(page), "storey": label, "gross_m2": 2 * length * h,
                             "category": "external" if external else "internal" if external is False else "unclassified",
                             "numerical_allowance_m2": 0., "face_offset_allowance_m2": 2 * (thick or 0) * h}
            page_rows.append(row)
        unallocated = 0
        for it in pm.get("items", []):
            if it.get("kind") not in ("door", "window"):
                continue
            props = it.get("props") or {}
            bb = it.get("bbox_px")
            explicit = props.get("host_wall_id") or props.get("wall_id")
            candidates = [w for w in page_rows if w["item_id"] == explicit] if explicit else []
            loc = None
            if bb and mpp:
                from shapely.geometry import Point
                loc = Point((bb[0] + bb[2]) * mpp / 2, (bb[1] + bb[3]) * mpp / 2)
                if not explicit:
                    close = [(w["_line"].distance(loc), w) for w in page_rows if w["_line"] is not None]
                    close.sort(key=lambda x: x[0])
                    if close and close[0][0] <= (close[0][1]["_thickness"] or 0) / 2 + 2 * mpp:
                        if len(close) == 1 or close[1][0] - close[0][0] > mpp:
                            candidates = [close[0][1]]
            width = _number(props.get("width_m"))
            if not width and bb and mpp:
                width = max(bb[2] - bb[0], bb[3] - bb[1]) * mpp
            if len(candidates) != 1 or not width:
                unallocated += 1
                continue
            w = candidates[0]
            oh = _number(props.get("height_m")) or (2.1 if it["kind"] == "door" else 1.5)
            sill = props.get("sill_height_m", 0. if it["kind"] == "door" else .9)
            if w["_line"] is not None and loc is not None:
                x = w["_line"].project(loc)
                region = box(max(0., x - width / 2), max(0., sill), min(w["length_m"], x + width / 2), min(w["height_m"], sill + oh))
                if sill >= w["height_m"]:
                    region = Polygon()
            else:
                # No location: nominal area may overlap another opening. Keep
                # it separate and report this source of uncertainty explicitly.
                x = sum(p.bounds[2] - p.bounds[0] for p in w["_holes"] if not p.is_empty)
                region = box(x, 0, x + width, min(oh, w["height_m"]))
                w["notes"].append("Opening locations unavailable; overlapping deductions cannot be checked")
            previous = unary_union(w["_holes"])
            allocated = region.difference(previous).area * 2
            w["_holes"].append(region)
            w["openings"].append({"item_id": it["item_id"], "fill_ids": [], "kind": it["kind"], "width_m": width,
                                  "height_m": oh, "deducted_m2": allocated, "height_assumed": not bool(props.get("height_m")),
                                  "floors": [{"storey_id": str(page), "deducted_m2": allocated}]})
        for w in page_rows:
            floor = w.pop("_floor")
            floor["opening_m2"] = min(floor["gross_m2"], unary_union(w["_holes"]).area * 2)
            floor["net_m2"] = floor["gross_m2"] - floor["opening_m2"]
            floor["facade_m2"] = floor["external_inside_m2"] = floor["net_m2"] / 2 if w["is_external"] else None
            floor["internal_both_m2"] = floor["net_m2"] if w["is_external"] is False else None
            floor["orientation_allowance_m2"] = 0.
            floor["orientation_unresolved"] = False
            w.update({k: floor[k] for k in ("gross_m2", "net_m2", "opening_m2")})
            w["floors"] = [floor]
            for k in ("_line", "_thickness", "_holes"):
                w.pop(k)
            out["walls"].append(w)
        out["assumptions"].append(f"{label}: wall height {height:g} m ({height_source}); missing door/window heights use 2.10/1.50 m, window sill 0.90 m; {unallocated} detected openings not assigned to a wall")
        out.setdefault("unallocated_openings", 0)
        out["unallocated_openings"] += unallocated
    return out


def _metric(question):
    q = question.casefold()
    if re.search(r"\b(?:facade|façade|outside|outward|exterior face|external face)\b", q):
        return "facade"
    if re.search(r"\b(?:plasterboard|drywall|wallboard|gypsum|paint|inside|inward|interior faces?)\b", q):
        return "inside"
    return "both"


def _selected_values(wall, floor, metric):
    """Gross, deducted, net, orientation allowance for the requested finish."""
    if metric == "both" or (metric == "inside" and wall["is_external"] is False):
        return floor["gross_m2"], floor["opening_m2"], floor["net_m2"], 0.
    if wall["is_external"] is False:
        return 0., 0., 0., 0.
    if wall["is_external"] is None:
        return None
    side = wall.get("inside_side")
    if side is None:
        gross, net = floor["gross_m2"] / 2, floor["net_m2"] / 2
    else:
        side = side if metric == "inside" else 1 - side
        gross, net = floor["gross_sides_m2"][side], floor["net_sides_m2"][side]
    return gross, gross - net, net, floor.get("orientation_allowance_m2", 0.)


def _safe_label(text):
    from engine.wording import clean_type_name
    return clean_type_name(str(text or "Unspecified")).replace("|", "/").replace("\n", " ")


def answer(question, doc_ids, root, t0=None, hidden=None):
    if not wants_wallarea(question) or not doc_ids:
        return None
    from engine.solvers.data import Item, load_doc
    from engine.solvers.filters import room_filter, storey_requested
    from engine.solvers.solve import _answer_obj, _evidence, _step, resolve_storey
    t0 = t0 or time.perf_counter()
    did = doc_ids[0]
    try:
        doc = load_doc(did, Path(root))
    except (OSError, ValueError, TypeError, KeyError):
        doc = None
    metric = _metric(question)
    trace = [_step("route", "wall side area: gross body minus actual void cuts; code only")]
    report = {"source": "unavailable", "rows": [], "openings": [], "warnings": [], "metric": metric,
              "gross_m2": 0., "opening_m2": 0., "net_m2": 0., "numerical_allowance_m2": 0.,
              "orientation_allowance_m2": 0., "complete": False, "checks": [], "assumptions": []}
    def finish(text, value=None, items=(), unit="m²"):
        boxes, cites, scene = _evidence(doc, list(items)) if doc else ([], [], {"doc_id": did, "highlight_item_ids": [], "camera_target_item_id": None})
        if doc and report["rows"] and "{wall:" in text:
            # A per-wall row must open that wall, not every wall on its floor.
            cites = []
            ids_to_items = {i.item_id: i for i in items}
            for w in measured["walls"]:
                if not any(r["item_id"] == w["item_id"] for r in report["rows"]):
                    continue
                related = [w["item_id"], *[iid for op in w["openings"] for iid in [op["item_id"], *op.get("fill_ids", [])]]]
                wall_items = [ids_to_items[i] for i in related if i in ids_to_items]
                _, wall_cites, _ = _evidence(doc, wall_items)
                n = len(cites) + 1
                c = wall_cites[0] if wall_cites else {"doc_id": did, "page": 1, "kind": "element", "bbox_px": None}
                label = next(r["label"] for r in report["rows"] if r["item_id"] == w["item_id"])
                c.update(n=n, item_ids=related, label=label)
                cites.append(c)
                text = text.replace("{wall:" + w["item_id"] + "}", f"[{n}]")
        scene["item_kinds"] = {it.item_id: it.kind for it in items}
        marks = " ".join(f"[{c['n']}]" for c in cites[:3])
        text = text.replace("{marks}", marks)
        route = "planmap" if report["source"] == "2D plan estimate" else "index"
        res = _answer_obj(question, doc_ids, text, value, unit if value is not None else None, .99 if report["complete"] else .4,
                          value is None, boxes, cites, scene, trace, route, t0)
        res["wallarea"] = report
        from engine.reasoning_parts.wallarea_steps import card
        res["reasoning"] = card(report)
        return res
    if len(doc_ids) != 1:
        return finish("**Select one building model for a wall-area take-off.** Combining models could count the same walls twice.")
    try:
        source = _source(did, root)
        stored = _wallgeom(did, root)
        if stored is not None:
            measured, source = stored, True
        elif source:
            measured = load_ifc(source)
        elif doc and doc.mode == "planmap":
            measured = estimate_planmaps(did, root, question)
        else:
            metadata_path = Path(root) / did / "doc.json"
            metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
            if metadata.get("kind") in {"raster", "pdf", "dxf", "dwg", "svg"}:
                report["source"] = "2D plan estimate"
                return finish("**Wall surface area cannot be measured from this sheet.** No usable scaled wall lengths are recorded; floor area cannot establish wall surface area.")
            return finish("**Wall surface area cannot be verified from this data.** The original IFC body geometry, or a scaled wall plan with heights, is needed; floor area is not wall area.")
    except Exception as exc:  # noqa: BLE001 — IFC backends also have their own exception classes
        trace.append(_step("wallarea", f"wall measurement unavailable: {type(exc).__name__}"))
        return finish("**The wall geometry could not be measured.** Check that the file contains valid wall bodies and units; no nominal area has been substituted.")
    report["source"] = measured["source"]
    if measured["source"] == "2D plan estimate":
        trace[0]["detail"] = "2D wall length × stated/printed/assumed height, both faces minus detected openings; estimate"
    if doc is None and source:
        from engine.solvers.data import Doc
        doc = Doc(did, "ifc", [Item(w["item_id"], "wall", name=w["name"]) for w in measured["walls"]], storeys=measured["storeys"])
    report["assumptions"] = measured.get("assumptions", [])
    report["skipped_walls"] = len(measured.get("skipped", []))
    report["unallocated_openings"] = measured.get("unallocated_openings", 0)
    if report["skipped_walls"]:
        report["warnings"].append(f"{report['skipped_walls']} walls could not be measured; totals are measured subtotals")
    if report["unallocated_openings"]:
        report["warnings"].append(f"{report['unallocated_openings']} detected openings could not be assigned and are not deducted")
    storey = resolve_storey(question, measured["storeys"])
    if storey_requested(question) and storey is None:
        return finish("**No matching floor was found.** Floors available: " + ", ".join(_safe_label(s["name"]) for s in measured["storeys"]) + ".")
    walls = [w for w in measured["walls"] if w["item_id"] not in (hidden or set())]
    ext_filter = bool(re.search(r"\b(?:external|exterior|outer)\s+walls?\b", question, re.I))
    int_filter = bool(re.search(r"\b(?:internal|interior|partition)\s+walls?\b", question, re.I))
    if ext_filter != int_filter:
        if any(w["is_external"] is None for w in walls):
            report["warnings"].append("Walls with unknown exterior/interior classification are excluded from the requested wall filter")
        walls = [w for w in walls if w["is_external"] is ext_filter]
    # Room selection uses multilingual room labels and numbers, never a name in code.
    room_scope = room_filter(question, [i for i in doc.items if i.kind == "room"]) if doc else None
    if room_scope and not re.search(r"\broom\b", question, re.I):
        from engine.solvers.filters import fold
        target = fold(room_scope[0])
        # The shared room filter also treats "area of <anything>" as a room.
        # A finish scope such as "area of the ground floor / external walls"
        # belongs to the storey/wall filters already applied above.
        if (storey and target == fold(storey)) or re.search(r"\b(?:floors?|levels?|storeys?|story|walls?|facade|building|model|outside|inside)\b", target):
            room_scope = None
    per_room = bool(re.search(r"\b(?:per|each|by) room\b", question, re.I))
    requested_room = bool(per_room or room_scope or re.search(r"\broom\s+[\w\d]+", question, re.I))
    room_ids = {r.item_id for r in room_scope[1]} if room_scope else set()
    if per_room:
        room_ids = {r["room_id"] for w in walls for r in w["rooms"]}
        known_rooms = {i.item_id for i in doc.items if i.kind == "room"} if doc else set()
        if known_rooms - room_ids:
            report["warnings"].append(f"{len(known_rooms - room_ids)} rooms have no usable wall boundaries and are excluded")
    number = re.search(r"\broom\s+([A-Za-z]?\d[\w.\-]*)", question, re.I)
    if number and doc:
        room_ids = {i.item_id for i in doc.items if i.kind == "room" and
                    any(str(v or "").casefold() == number[1].rstrip(".").casefold() for v in (i.name, i.label, i.props.get("number")))}
    if requested_room and not room_ids:
        return finish("**No matching room with verifiable wall boundaries was found.** Use the room's printed name or number.")
    # Exact wall name/type requests; no unfiltered fallback for an unknown quote.
    quoted = re.findall(r'["“]([^"”]+)["”]', question)
    quoted = [x for x in quoted if not any(x.casefold() == s["name"].casefold() for s in measured["storeys"])]
    if quoted and not requested_room:
        candidates = [w for w in walls if any(x.casefold() in str(w.get(k) or "").casefold() for x in quoted for k in ("name", "type"))]
        if not candidates:
            return finish("**No matching wall or wall type was found.** No unfiltered wall total is substituted.")
        walls = candidates
    by_floor = {}
    unknown = 0
    selected_ids = set()
    for index, w in enumerate(walls, 1):
        floor_rows = w["rooms"] if requested_room else w["floors"]
        used = False
        for floor in floor_rows:
            if storey and floor["storey"] != storey:
                continue
            if requested_room and floor["room_id"] not in room_ids:
                continue
            values = (floor["gross_m2"], floor["opening_m2"], floor["net_m2"], 0.) if requested_room else _selected_values(w, floor, metric)
            if values is None:
                unknown += 1
                continue
            gross, opening, net, orientation = values
            if gross == 0:
                continue
            used = True
            row = {"item_id": w["item_id"], "label": f"Wall {index}", "storey": floor["storey"], "storey_id": floor["storey_id"],
                   "type": _safe_label(w.get("type")), "material": ", ".join(_safe_label(m) for m in w.get("materials", [])) or "Unspecified",
                   "gross_m2": gross, "opening_m2": opening, "net_m2": net,
                   "category": "external" if w["is_external"] else "internal" if w["is_external"] is False else "unclassified"}
            if requested_room:
                row.update(room_id=floor["room_id"], room_name=_safe_label(floor["name"]))
            report["rows"].append(row)
            totals = by_floor.setdefault(floor["storey_id"], {"name": floor["storey"], "gross_m2": 0., "opening_m2": 0., "net_m2": 0.})
            for key, val in zip(("gross_m2", "opening_m2", "net_m2"), values[:3]):
                totals[key] += val
                report[key] += val
            report["numerical_allowance_m2"] += floor.get("numerical_allowance_m2", 0.)
            report["orientation_allowance_m2"] += orientation
            if floor.get("orientation_unresolved") and metric != "both":
                report.setdefault("orientation_unresolved", True)
            if w.get("curved"):
                report["warnings"].append("Curved wall areas are measured; splitting them between floors uses an approximation")
            if w["axis_source"] == "inferred from body":
                report["warnings"].append("Some wall directions were inferred from their bodies because axes were absent")
            if report["source"] == "2D plan estimate":
                report.setdefault("height_sensitivity_m2_per_m", 0.)
                report["height_sensitivity_m2_per_m"] += w["length_m"] * (2 if metric == "both" or w["is_external"] is False else 1)
                report.setdefault("face_offset_allowance_m2", 0.)
                report["face_offset_allowance_m2"] += floor.get("face_offset_allowance_m2", 0.)
        if used:
            selected_ids.add(w["item_id"])
            report["checks"].extend({**c, "wall_id": w["item_id"]} for c in w.get("checks", []))
            for op in w["openings"]:
                if op["item_id"] in (hidden or set()) or set(op.get("fill_ids", [])) & set(hidden or []):
                    report["warnings"].append("Hidden doors/windows remain geometric openings; hiding a filling does not close its void")
                selected_ids.add(op["item_id"])
                selected_ids.update(op.get("fill_ids", []))
                report["openings"].append(op)
            if w.get("opening_unallocated_m2", 0.) > measured.get("precision_m", 0.):
                report["warnings"].append("Some geometric cuts could not be allocated to individual opening outlines")
            report["warnings"].extend(w.get("notes", []))
    if unknown:
        report["warnings"].append(f"{unknown} wall/floor entries lack exterior/interior classification and are excluded from this finish subtotal")
    if requested_room and not report["rows"]:
        return finish("**This room has no usable wall-surface boundaries.** A room floor area or bounding box cannot verify its wall finish area.")
    report["floors"] = list(by_floor.values())
    # Every answer retains all three finish categories, including explicit
    # unclassified area. Building totals can therefore be audited independently.
    splits = {}
    for w in walls:
        for floor in w["floors"]:
            if storey and floor["storey"] != storey:
                continue
            st = splits.setdefault(floor["storey_id"], {"name": floor["storey"], "facade": {"gross_m2": 0., "opening_m2": 0., "net_m2": 0.},
                "external_inside": {"gross_m2": 0., "opening_m2": 0., "net_m2": 0.}, "internal_both": {"gross_m2": 0., "opening_m2": 0., "net_m2": 0.}, "unclassified_net_m2": 0.})
            if w["is_external"] is None:
                st["unclassified_net_m2"] += floor["net_m2"]
                continue
            categories = (("facade", "facade"), ("external_inside", "inside")) if w["is_external"] else (("internal_both", "both"),)
            for category, mode in categories:
                values = _selected_values(w, floor, mode)
                for key, val in zip(("gross_m2", "opening_m2", "net_m2"), values[:3]):
                    st[category][key] += val
    report["face_splits"] = list(splits.values())
    selected_floors = {(r["item_id"], r["storey_id"]) for r in report["rows"]}
    report["unattributed"] = [entry for entry in measured.get("unattributed", [])
                              if (entry["item_id"], entry["storey_id"]) in selected_floors]
    for entry in report["unattributed"]:
        trace.append(_step("unattributed", f"Wall {entry['item_id']}: {entry['area_m2']:.6f} m² cut; "
                           f"{entry['side_transfer_m2']:.6f} m² side correspondence discrepancy. {entry['resolution']}"))
    report["warnings"] = list(dict.fromkeys(report["warnings"]))
    report["wall_count"] = len({r["item_id"] for r in report["rows"]})
    report["opening_count"] = len(report["openings"])
    report["complete"] = bool(report["rows"]) and report["source"] != "2D plan estimate" and not report["warnings"]
    if not report["rows"]:
        if measured["source"] == "2D plan estimate":
            return finish("**Wall surface area cannot be measured from this sheet.** No usable scaled wall lengths were found; room detection boxes cannot establish wall surfaces.")
        return finish("**No wall surfaces could be measured for this request.** Check the wall bodies, room boundaries and exterior/interior flags.")
    report["margin_m2"] = report["numerical_allowance_m2"] + report["orientation_allowance_m2"] if report["source"] != "2D plan estimate" and not report["skipped_walls"] and not unknown else None
    report["margin_pct"] = 100 * report["margin_m2"] / report["net_m2"] if report.get("margin_m2") is not None and report["net_m2"] else None
    items = [i for i in doc.items if i.item_id in selected_ids] if doc else []
    present = {i.item_id for i in items}
    kinds = {w["item_id"]: "wall" for w in walls}
    for op in report["openings"]:
        kinds[op["item_id"]] = "opening"
        kinds.update({iid: op["kind"] for iid in op.get("fill_ids", [])})
    items.extend(Item(item_id=iid, kind=kinds.get(iid, "wall"), source="ifc") for iid in sorted(selected_ids - present))
    title = {"facade": "Facade", "inside": "Interior wall finish", "both": "Both wall faces"}[metric]
    scope = f" on {_safe_label(storey)}" if storey else ""
    qualifier = "estimated " if report["source"] == "2D plan estimate" or report.get("orientation_allowance_m2") else ""
    qualifier += "measured subtotal" if not report["complete"] and report["warnings"] else "net area"
    requested = "gross" if (re.search(r"\bgross\b|\bbefore (?:deducting|subtracting)\b|\b(?:do not|don't|without) deduct", question, re.I) and not re.search(r"\bnet\b", question, re.I)) else "net"
    report["requested_quantity"] = requested
    value = round(report[requested + "_m2"], 6)
    if requested == "gross":
        qualifier = qualifier.replace("net area", "gross area")
    report["value_m2"] = value
    text = f"**{title}{scope}: {value:,.2f} m² {qualifier}.** {{marks}}\n\n- Gross {report['gross_m2']:,.2f} m² − openings {report['opening_m2']:,.2f} m² = net {report['net_m2']:,.2f} m²."
    if report["source"] == "2D plan estimate":
        text += "\n- Estimate from a 2D plan; " + "; ".join(report["assumptions"]) + "."
    elif report.get("margin_m2") is not None:
        text += f"\n- Numerical/orientation allowance ±{report['margin_m2']:.4f} m²; source-model accuracy is not quantified."
    if report["warnings"]:
        text += "\n- " + "; ".join(report["warnings"][:2]) + "."
    waste = re.search(r"\b(\d+(?:\.\d+)?)\s*%\s*(?:waste|extra|allowance)\b|\b(?:waste|allowance)\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)\s*%", question, re.I)
    factor = 1 + float(waste[1] or waste[2]) / 100 if waste else 1.
    report["waste_pct"] = (factor - 1) * 100
    report["order_area_m2"] = value * factor
    answer_unit = "m²"
    if re.search(r"\b(?:sheet|board)s?\b|\bhow many\b.*\b(?:plasterboard|drywall)\b", question, re.I):
        dimensions = re.search(r"(\d+(?:\.\d+)?)\s*[×x]\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|ft|feet)?\b", question, re.I)
        width, height = (float(dimensions[1]), float(dimensions[2])) if dimensions else (1.2, 2.4)
        unit_scale = {"mm": .001, "cm": .01, "ft": .3048, "feet": .3048}.get(dimensions[3] if dimensions else "m", 1.)
        sheet_area = width * height * unit_scale ** 2
        if sheet_area > 0:
            report["sheet_area_m2"] = sheet_area
            report["sheet_count"] = math.ceil(report["order_area_m2"] / sheet_area - 1e-10)
            text = re.sub(r"^\*\*.*?\*\*", f"**At least {report['sheet_count']} sheets{scope} by area ({value:,.2f} m² before waste).**", text, count=1)
            value, answer_unit = report["sheet_count"], "count"
            waste_note = f"{report['waste_pct']:g}% stated waste" if waste else "no waste added"
            text += f"\n- {report['sheet_count']} sheets at {width:g} × {height:g} {dimensions[3] or 'm' if dimensions else 'm'} (area minimum, one layer; {waste_note})."
    elif waste:
        text += f"\n- With {report['waste_pct']:g}% stated waste: {report['order_area_m2']:,.2f} m² to order."
    # The existing Take-off sheet recognises Item | Quantity | Unit | Source.
    # Include the complete breakdown (not a truncated first N) for CSV export.
    text += "\n\n| Item | Quantity | Unit | Source |\n| --- | ---: | --- | --- |"
    if per_room:
        groups = {}
        for r in report["rows"]:
            g = groups.setdefault(r["room_id"], dict(name=r["room_name"], gross_m2=0., opening_m2=0., net_m2=0.))
            for k in ("gross_m2", "opening_m2", "net_m2"):
                g[k] += r[k]
        entries = list(groups.values())
    elif re.search(r"\b(?:per wall|each wall|take.?off|breakdown|export|sheet)\b", question, re.I):
        entries = [dict(r, name=f"{r['label']} · {_safe_label(r['storey'])}") for r in report["rows"]]
    elif re.search(r"\b(?:by|per)\s+(?:wall\s+)?(?:type|material)\b", question, re.I):
        key = "material" if "material" in question.casefold() else "type"
        groups = {}
        for r in report["rows"]:
            g = groups.setdefault((r["storey_id"], r[key]), dict(name=f"{_safe_label(r['storey'])} · {r[key]}", gross_m2=0., opening_m2=0., net_m2=0.))
            for k in ("gross_m2", "opening_m2", "net_m2"):
                g[k] += r[k]
        entries = list(groups.values())
    elif metric == "both" and not requested_room:
        entries = []
        for split in report["face_splits"]:
            for key, label in (("facade", "outside of external walls"), ("external_inside", "inside of external walls"), ("internal_both", "both sides of internal walls")):
                entries.append(dict(split[key], name=f"{_safe_label(split['name'])} · {label}"))
            if split["unclassified_net_m2"]:
                entries.append(dict(name=f"{_safe_label(split['name'])} · unclassified walls (both sides)", gross_m2=sum(r["gross_m2"] for r in report["rows"] if r["storey_id"] in splits and r["storey"] == split["name"] and r["category"] == "unclassified"),
                                    net_m2=split["unclassified_net_m2"], opening_m2=sum(r["opening_m2"] for r in report["rows"] if r["storey"] == split["name"] and r["category"] == "unclassified")))
    else:
        entries = [dict(f, name=_safe_label(f["name"])) for f in report["floors"]]
    for entry in entries:
        for label, key in (("gross", "gross_m2"), ("openings deducted", "opening_m2"), ("net", "net_m2")):
            mark = "{wall:" + entry["item_id"] + "}" if entry.get("item_id") else "{marks}"
            text += f"\n| {entry['name']} · {label} | {entry[key]:.4f} | m² | {mark} |"
    if any(e.get("item_id") for e in entries):
        relevant_floors = {r["storey_id"] for r in report["rows"]}
        for w in walls:
            wall_label = next((r["label"] for r in report["rows"] if r["item_id"] == w["item_id"]), None)
            if not wall_label:
                continue
            for k, op in enumerate(w["openings"], 1):
                values = [f["deducted_m2"] for f in op["floors"] if f["storey_id"] in relevant_floors]
                area = sum(values) if values and all(v is not None for v in values) else None
                dimensions = f" ({op['width_m']:.3g} × {op['height_m']:.3g} m extents)" if op.get("width_m") and op.get("height_m") else ""
                shown = f"{area:.4f}" if area is not None else "not in this file: individual cut unallocated"
                text += f"\n| {wall_label} · {op['kind']} void {k}{dimensions} · cut on both sides, already deducted | {shown} | m² | {{wall:{w['item_id']}}} |"
    trace.append(_step("wallarea", f"{report['wall_count']} walls: {report['gross_m2']:.6f} - {report['opening_m2']:.6f} = {report['net_m2']:.6f} m²; {metric}"))
    return finish(text, value, items, answer_unit)


def validation_summary(path, result=None):
    """Independent bounding-rectangle check, not a claim of drawing ground truth."""
    result = result if result is not None else measure_ifc(path)
    floors = {}
    for wall in result["walls"]:
        for row in wall["floors"]:
            target = floors.setdefault(row["storey_id"], {"name": row["storey"], "walls": 0, "gross_m2": 0., "opening_m2": 0., "net_m2": 0.,
                "independent_gross_m2": 0., "independent_net_m2": 0., "independent_walls": 0, "numeric_allowance_m2": 0.})
            target["walls"] += 1
            for key in ("gross_m2", "opening_m2", "net_m2"):
                target[key] += row[key]
            target["numeric_allowance_m2"] += row["numerical_allowance_m2"]
            if "extent_net_check_m2" in row:
                target["independent_gross_m2"] += row["extent_gross_m2"]
                target["independent_net_m2"] += row["extent_net_check_m2"]
                target["independent_walls"] += 1
    for target in floors.values():
        if target["walls"] == target["independent_walls"]:
            target["gross_difference_pct"] = 100 * abs(target["gross_m2"] - target["independent_gross_m2"]) / target["gross_m2"] if target["gross_m2"] else None
            target["net_difference_pct"] = 100 * abs(target["net_m2"] - target["independent_net_m2"]) / target["net_m2"] if target["net_m2"] else None
        else:
            target["gross_difference_pct"] = target["net_difference_pct"] = None
    quantities = [c for w in result["walls"] for c in w["checks"] if c["quantity"] == "NetSideArea"]
    return {"path": str(path), "schema": result["schema"], "applications": result["applications"], "length_unit_to_m": result["length_unit_to_m"],
            "walls_measured": len(result["walls"]), "walls_skipped": len(result["skipped"]), "skipped": result["skipped"],
            "rooms_with_boundaries": len({r["room_id"] for w in result["walls"] for r in w["rooms"]}),
            "openings": sum(len(w["openings"]) for w in result["walls"]),
            "unallocated_cut_m2": sum(w["opening_unallocated_m2"] for w in result["walls"]),
            "exterior_classified_walls": sum(w["is_external"] is not None for w in result["walls"]),
            "inferred_axes": sum(w["axis_source"] != "IFC axis" for w in result["walls"]),
            "net_quantity_walls": len(quantities), "stored_net_one_side_m2": sum(c["stored_m2"] for c in quantities),
            "measured_net_one_side_mean_m2": sum(c["measured_one_side_mean_m2"] for c in quantities),
            "max_wall_net_quantity_difference_pct": max((c["difference_pct"] for c in quantities if c["difference_pct"] is not None), default=None),
            "gross_m2": sum(w["gross_m2"] for w in result["walls"]), "net_m2": sum(w["net_m2"] for w in result["walls"]),
            "floors": list(floors.values()), "independent_check": "World wall-axis extent × clipped height, minus each void's width × clipped height on both sides. Rectangular check only: overlaps, mitres, slopes and irregular void outlines can disagree legitimately. No quantity tuned to this check."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": []}
    for path in args.check:
        started = time.monotonic()
        row = validation_summary(path)
        row["elapsed_s"] = round(time.monotonic() - started, 3)
        report["files"].append(row)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(f"{path.name}: {row['walls_measured']} measured, {row['walls_skipped']} skipped ({row['elapsed_s']} s)", flush=True)


if __name__ == "__main__":
    main()
