"""Read already faceted IFC geometry without building an OpenCascade solid.

Only planar polygonal faces qualify. Other representations and
products requiring opening subtraction use the native geometry kernel.
"""
import numpy as np
import ifcopenshell.util.placement as placement
import ifcopenshell.util.unit as unit


def triangulate(points, holes=()):
    """A triangle fan is exact for a convex, planar polygon; reject other faces."""
    p = np.asarray(points, dtype=float)
    if len(p) < 3 or not np.isfinite(p).all():
        raise ValueError('Invalid IFC facet')
    if len(p) == 3 and not holes:
        return [(0, 1, 2)]
    # Newell normal handles collinear starting vertices.
    normal = np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)
    length = np.linalg.norm(normal)
    if length < 1e-12:
        raise ValueError('Degenerate IFC facet')
    normal /= length
    extent = max(float(np.ptp(p, axis=0).max()), 1e-9)
    if np.abs((p - p[0]) @ normal).max() > extent * 1e-7:
        raise ValueError('Non-planar IFC facet')
    turns = np.cross(np.roll(p, -1, axis=0) - p, np.roll(p, -2, axis=0) - np.roll(p, -1, axis=0)) @ normal
    if not holes and not (turns < -extent**2 * 1e-10).any():
        return [(0, i, i + 1) for i in range(1, len(p) - 1)]
    # Constrained triangulation retains concave edges and inner voids. All
    # triangle vertices must come from the source loops; never invent geometry.
    from shapely import Polygon, constrained_delaunay_triangles
    axis = int(np.abs(normal).argmax())
    projected = np.delete(p, axis, axis=1)
    rings = [np.delete(np.asarray(h), axis, axis=1) for h in holes]
    polygon = Polygon(projected, rings)
    if not polygon.is_valid:
        raise ValueError('Invalid IFC polygon')
    all_points = np.concatenate([p, *[np.asarray(h) for h in holes]]) if holes else p
    all_projected = np.delete(all_points, axis, axis=1)
    lookup = {tuple(point): i for i, point in enumerate(all_projected)}
    triangles = []
    for triangle in constrained_delaunay_triangles(polygon).geoms:
        indices = [lookup[tuple(point)] for point in list(triangle.exterior.coords)[:3]]
        a, b, c = all_points[indices]
        if np.dot(np.cross(b - a, c - a), normal) < 0:
            indices.reverse()
        triangles.append(tuple(indices))
    return triangles


def mesh(element):
    if not element.Representation or getattr(element, 'HasOpenings', None):
        return None
    representations = [r for r in element.Representation.Representations
                       if r.RepresentationIdentifier == 'Body']
    if not representations:
        return None
    vertices, faces, lookup = [], [], {}
    scale = unit.calculate_unit_scale(element.file)
    transform = placement.get_local_placement(element.ObjectPlacement) if element.ObjectPlacement else np.eye(4)

    def polygon(points, matrix, reverse=False, holes=()):
        triangles = triangulate(points, holes)
        if holes:
            points = [*points, *[p for ring in holes for p in ring]]
        indices = []
        transformed = (matrix @ np.column_stack([points, np.ones(len(points))]).T).T[:, :3] * scale
        for point in transformed:
            key = tuple(point)
            if key not in lookup:
                lookup[key] = len(vertices)
                vertices.append(point.tolist())
            indices.append(lookup[key])
        # A reflection changes handedness; preserve front faces in mapped geometry.
        reverse = reverse != (np.linalg.det(matrix[:3, :3]) < 0)
        for a, b, c in triangles:
            faces.append((indices[c], indices[b], indices[a]) if reverse else (indices[a], indices[b], indices[c]))

    def face(face, matrix):
        if face.is_a() != 'IfcFace' or not face.Bounds:
            raise ValueError('Curved face')
        bounds = list(face.Bounds)
        outer = next((b for b in bounds if b.is_a('IfcFaceOuterBound')), bounds[0])
        if any(not b.Bound.is_a('IfcPolyLoop') for b in bounds):
            raise ValueError('Non-polygonal bound')
        holes = [[p.Coordinates for p in b.Bound.Polygon] for b in bounds if b != outer]
        polygon([p.Coordinates for p in outer.Bound.Polygon], matrix, not outer.Orientation, holes)

    def item(item, matrix, ancestors):
        if item.id() in ancestors:
            raise ValueError('Circular mapped geometry')
        if item.is_a('IfcMappedItem'):
            mapped = matrix @ placement.get_mappeditem_transformation(item)
            for child in item.MappingSource.MappedRepresentation.Items:
                item_fn(child, mapped, ancestors | {item.id()})
        elif item.is_a() == 'IfcFacetedBrep':
            for f in item.Outer.CfsFaces:
                face(f, matrix)
        elif item.is_a('IfcShellBasedSurfaceModel'):
            for shell in item.SbsmBoundary:
                for f in shell.CfsFaces:
                    face(f, matrix)
        elif item.is_a('IfcFaceBasedSurfaceModel'):
            for connected in item.FbsmFaces:
                for f in connected.CfsFaces:
                    face(f, matrix)
        elif item.is_a('IfcTriangulatedFaceSet'):
            coords = item.Coordinates.CoordList
            remap = item.PnIndex
            for triangle in item.CoordIndex:
                polygon([coords[(remap[i - 1] if remap else i) - 1] for i in triangle], matrix)
        else:
            raise ValueError('Geometry requires the native kernel')

    item_fn = item
    try:
        for representation in representations:
            for child in representation.Items:
                item_fn(child, transform, set())
    except (ValueError, TypeError, AttributeError, RuntimeError, ImportError, KeyError):
        return None
    if not faces:
        return None
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int32).reshape(-1)
