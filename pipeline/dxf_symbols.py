"""Conservative CAD symbol grouping; no model calls or document-specific rules.

Only semantic fixture/opening layers and named fixture blocks are considered.
The geometry kernel ``classify_fixture_shapes`` also accepts vector paths from a
different reader; it never opens a PDF. Coordinates stay in the caller's units.
Unrecognised geometry is retained as an uncertain fixture, never as a zero count.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Point, Polygon


def _words(text):
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in unicodedata.normalize("NFKD", str(text or "")).lower()
                                             if not unicodedata.combining(c))).strip()


FIXTURE_KINDS = {
    "toilet": r"\b(?:toilet\w*|wc|water closet|toalett\w*)\b",
    "sink": r"\b(?:sink\w*|wash ?basin\w*|basin\w*|lavabo\w*|waschbecken|waschtisch|pesuallas|tvattstall)\b",
    "shower": r"\b(?:shower\w*|dusche\w*|douche\w*|doccia|suihku\w*|dusch)\b",
    "bathtub": r"\b(?:bath ?tub\w*|badewanne\w*|wanne|baignoire\w*|vasca|kylpyamme|badkar)\b",
}
FIXTURE_LAYER = re.compile(r"\b(?:fixture\w*|fixt|sanitar\w*|sanitair\w*|sanitaire\w*|sanita\w*|saniteetti\w*|vesikaluste\w*|plumbing)\b")
OPENING_LAYERS = {
    "door": re.compile(r"\b(?:doors?|tur\w*|tuer\w*|portes?|dorr\w*|ovi|ovet)\b"),
    "window": re.compile(r"\b(?:windows?|fenster\w*|fenetre\w*|fonster\w*|ikkuna\w*)\b"),
}


def fixture_kind(*names):
    text = _words(" ".join(str(n or "") for n in names))
    matches = [kind for kind, rx in FIXTURE_KINDS.items() if re.search(rx, text)]
    return matches[0] if len(matches) == 1 else None


# Measured on 12 nonforbidden drawings from distinct sites. Full distributions,
# sample sizes and source handles: results/final/ACC-VECTOR/constants.json.
# These are dimensionless shape boundaries, NOT calibrated probabilities.
BOWL_OFFSET_SPLIT = 0.05040196184783172
ELLIPSE_ERROR_SPLIT = 0.17096219889872966
DRAIN_DIAMETER_SPLIT = 0.17940298507462793
TUB_ASPECT_SPLIT = 1.5199349945828817
ESTIMATE_CONF = 0.5  # existing solver's MIN_CONF; estimates remain countable
EPS = 1e-7  # numerical relative tolerance, not a symbol-size threshold


@dataclass
class VectorShape:
    """Reader-neutral path. Circle centre/radius are optional analytic metadata.

    ``closed`` may be false for paths whose last point repeats the first.
    ``props`` should contain source handles/layers, never benchmark labels.
    """
    points: list
    closed: bool = False
    primitive: str = "polyline"
    center: tuple | None = None
    radius: float | None = None
    props: dict = field(default_factory=dict)


def _points(shape):
    p = np.asarray(shape.points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        return np.empty((0, 2))
    if len(p) > 1:
        span = max(float(np.ptp(p, axis=0).max()), np.finfo(float).eps)
        if np.linalg.norm(p[0] - p[-1]) <= EPS * span:
            p = p[:-1]
    return p


def _is_closed(shape):
    if shape.closed:
        return True
    p = np.asarray(shape.points)
    return len(p) > 2 and len(_points(shape)) < len(p)


def rectangle(shape):
    """Four straight orthogonal sides, with either explicit or repeated closure."""
    p = _points(shape)
    if shape.primitive != "polyline" or len(p) != 4 or not _is_closed(shape):
        return None
    edges = np.roll(p, -1, axis=0) - p
    lengths = np.linalg.norm(edges, axis=1)
    if min(lengths) <= EPS * max(lengths):
        return None
    if any(abs(float(np.dot(edges[i], edges[(i + 1) % 4]))) > EPS * lengths[i] * lengths[(i + 1) % 4] for i in range(4)):
        return None
    return p


def _item(kind, polygon, props, conf=ESTIMATE_CONF, label=""):
    return {"kind": kind, "label": label, "polygon": [list(map(float, p)) for p in polygon],
            "props": props, "conf": conf}


def _bounds_polygon(shapes):
    p = np.concatenate([_points(s) for s in shapes if len(_points(s))])
    lo, hi = p.min(axis=0), p.max(axis=0)
    return [lo, [hi[0], lo[1]], hi, [lo[0], hi[1]]]


def _ellipse_features(shape, frame):
    p = _points(shape)
    if len(p) <= 4 or not _is_closed(shape):
        return None
    origin = frame[0]
    u, v = frame[1] - origin, frame[3] - origin
    w, h = np.linalg.norm(u), np.linalg.norm(v)
    q = np.c_[(p - origin) @ u / w ** 2, (p - origin) @ v / h ** 2]
    lo, hi = q.min(axis=0), q.max(axis=0)
    radii = (hi - lo) / 2
    if min(radii) <= EPS:
        return None
    center = (lo + hi) / 2
    rho = np.sqrt(np.sum(((q - center) / radii) ** 2, axis=1))
    extents = (hi - lo) * [w, h]
    return {"offset": float(np.max(np.abs(center - .5))),
            "ellipse_error": float(np.max(np.abs(rho - 1))),
            "aspect": float(max(extents) / min(extents)), "vertices": len(p)}


def classify_fixture_shapes(shapes: list[VectorShape]) -> list[dict]:
    """Group shapes into the smallest containing closed rectangle and classify.

    Hook for Awais: supply ONE sanitary layer/block at a time, with flattened
    closed curves and circles (including centre/radius). Returns kind, polygon,
    props and conf in input coordinates. The caller supplies page transforms,
    IDs and citations. No reader or raster detections are changed here.
    """
    shapes = [s for s in shapes if len(_points(s)) >= 2]
    frames = {i: rectangle(s) for i, s in enumerate(shapes) if rectangle(s) is not None}
    polygons = {i: Polygon(p) for i, p in frames.items()}
    groups = defaultdict(list)
    unowned = []
    for i, s in enumerate(shapes):
        p = _points(s)
        geom = LineString([*p, p[0]]) if _is_closed(s) else LineString(p)
        owners = [j for j, poly in polygons.items() if j != i
                  and (i not in polygons or poly.area > polygons[i].area * (1 + EPS))
                  and poly.buffer(EPS * math.sqrt(poly.area)).covers(geom)]
        if owners:
            groups[min(owners, key=lambda j: polygons[j].area)].append(i)
        elif i not in frames:
            unowned.append(i)
    out = []
    # Duplicate rectangles are one symbol. A nested fixture is classified by
    # its own smallest frame; a larger enclosing counter is not counted again.
    seen = []
    for i, frame in frames.items():
        if any(polygons[i].equals(p) for p in seen):
            continue
        seen.append(polygons[i])
        children = [shapes[j] for j in groups[i] if j not in frames]
        child_frames = [shapes[j] for j in groups[i] if j in frames]
        props = {**shapes[i].props, "role": "fixture", "classification": "unknown", "needs_review": True,
                 "symbol_parts": [shapes[j].props for j in [i, *groups[i]]], "confidence_basis": "uncalibrated geometry rule"}
        w, h = np.linalg.norm(frame[1] - frame[0]), np.linalg.norm(frame[3] - frame[0])
        circles = [s for s in children if s.primitive == "circle" and s.radius is not None]
        drains = [s for s in circles if 2 * s.radius / min(w, h) < DRAIN_DIAMETER_SPLIT]
        large_circles = [s for s in circles if 2 * s.radius / min(w, h) >= DRAIN_DIAMETER_SPLIT]
        curves = [(s, f) for s in children if s.primitive != "circle" and (f := _ellipse_features(s, frame))]
        bowls = [(s, f) for s, f in curves if f["ellipse_error"] < ELLIPSE_ERROR_SPLIT]
        tubs = [(s, f) for s, f in curves if f["ellipse_error"] >= ELLIPSE_ERROR_SPLIT and f["aspect"] > TUB_ASPECT_SPLIT]
        def has_drain(curve):
            poly = Polygon(_points(curve))
            return poly.is_valid and any(s.center is not None and poly.covers(Point(s.center)) for s in drains)

        kind, anatomy = "other", None
        if len(tubs) == 1 and not bowls and has_drain(tubs[0][0]):
            kind, anatomy = "bathtub", "rounded elongated outline and drain"
        elif len(bowls) == 1 and not tubs:
            _, features = bowls[0]
            props["bowl_offset_fraction"] = features["offset"]
            if has_drain(bowls[0][0]) and features["offset"] < BOWL_OFFSET_SPLIT:
                kind, anatomy = "sink", "centred bowl and drain"
            elif not circles and features["offset"] >= BOWL_OFFSET_SPLIT:
                kind, anatomy = "toilet", "off-centre bowl without drain"
        elif drains and not curves and not large_circles:
            # Rectangular tray itself is the smallest enclosing frame; its
            # larger decorative rectangle, if any, is not a second fixture.
            if max(w, h) / min(w, h) < TUB_ASPECT_SPLIT:
                kind, anatomy = "shower", "compact rectangular tray and drain"
        elif len(large_circles) >= 2 and not curves and not drains:
            props.update(role="appliance", classification="kitchen_hob", needs_review=True,
                         anatomy="multiple large circles; not evidence of a sink")
        elif not children:
            props.update(role="furniture", classification="empty_outline", needs_review=True)
        elif children and not circles and not curves and not child_frames:
            # Partitioned rectangular furniture/treads are not sanitary bowls.
            # Crossing diagonals are deliberately left unknown (not a shower
            # without a drain or explicit semantics).
            lines = [_points(s) for s in children]
            if all(len(p) == 2 for p in lines) and len(lines) >= 2:
                vectors = [p[1] - p[0] for p in lines]
                first = vectors[0]
                if all(abs(float(first[0] * v[1] - first[1] * v[0])) <= EPS * np.linalg.norm(first) * np.linalg.norm(v) for v in vectors[1:]):
                    props.update(role="furniture", classification="parallel_partitions", needs_review=True)
        if anatomy:
            props.update(classification="geometry", anatomy=anatomy)
        out.append(_item(kind, frame, props))
    for i in unowned:
        s = shapes[i]
        out.append(_item("other", _bounds_polygon([s]), {**s.props, "role": "fixture", "classification": "unknown", "needs_review": True}))
    return out


def _shape(entity, layer=None):
    """Use native vertices where straight; flatten bulges/curves relatively."""
    from ezdxf import bbox, path
    t = entity.dxftype()
    if t not in ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "ARC", "SPLINE"):
        return None
    bounds = bbox.extents([entity])
    if not bounds.has_data:
        return None
    span = max(bounds.size.x, bounds.size.y)
    if not math.isfinite(span) or span <= 0:
        return None
    closed = False
    primitive = "polyline"
    if t == "LWPOLYLINE" and not entity.has_arc:
        points = [(p.x, p.y) for p in entity.vertices_in_wcs()]
        closed = entity.closed
    elif t == "POLYLINE" and not entity.has_arc:
        points = [(p.x, p.y) for p in entity.points_in_wcs()]
        closed = entity.is_closed
    else:
        curve = path.make_path(entity)
        points = [(p.x, p.y) for p in curve.flattening(span / 1024)]
        closed = curve.is_closed
        primitive = "circle" if t == "CIRCLE" else "curve" if t != "LINE" else "polyline"
    props = {"dxf_layer": layer or entity.dxf.layer, "dxf_handle": entity.dxf.get("handle", "")}
    return VectorShape(points, closed, primitive,
                       (entity.dxf.center.x, entity.dxf.center.y) if t == "CIRCLE" else None,
                       float(entity.dxf.radius) if t == "CIRCLE" else None, props)


def extract_fixtures(layout):
    """Named blocks are one object; exploded sanitary layers use nested anatomy."""
    from ezdxf import bbox
    by_layer = defaultdict(list)
    out = []

    def visit(entity, inherited_layer=None, depth=0):
        layer = inherited_layer if entity.dxf.layer == "0" and inherited_layer else entity.dxf.layer
        name = entity.dxf.name if entity.dxftype() == "INSERT" else ""
        kind = fixture_kind(layer, name)
        candidate = bool(FIXTURE_LAYER.search(_words(layer))) or kind is not None
        if entity.dxftype() == "INSERT":
            if kind:
                bounds = bbox.extents([entity])
                if bounds.has_data:
                    lo, hi = bounds.extmin, bounds.extmax
                    out.append(_item(kind, [(lo.x, lo.y), (hi.x, lo.y), (hi.x, hi.y), (lo.x, hi.y)],
                                     {"role": "fixture", "classification": "explicit", "dxf_layer": layer, "dxf_block": name}, 1.0, name))
                return
            if depth < 16:
                for child in entity.virtual_entities():
                    visit(child, layer, depth + 1)
            return
        if not candidate:
            return
        shape = _shape(entity, layer)
        if shape is not None:
            by_layer[layer].append(shape)

    for entity in layout:
        visit(entity)
    for layer, shapes in by_layer.items():
        classified = classify_fixture_shapes(shapes)
        explicit = fixture_kind(layer)
        if explicit:
            # An explicit fixture layer names whole symbols, not every inset
            # outline or drain. Keep its outer objects once, as for a block.
            polygons = [Polygon(item["polygon"]) for item in classified]
            classified = [item for i, item in enumerate(classified)
                          if not any(j != i and p.area > polygons[i].area * (1 + EPS)
                                     and p.covers(polygons[i]) for j, p in enumerate(polygons))]
        for item in classified:
            if explicit:
                item.update(kind=explicit, conf=1.0)
                item["props"].update(role="fixture", classification="explicit", needs_review=False)
        out.extend(classified)
    return out


def extract_openings(layout, kind, unit_m=None):
    """Count closed frame polylines once; arcs/leaf lines are not objects."""
    candidates = []

    def visit(entity, layer=None, depth=0, symbol_id=None):
        effective = layer if entity.dxf.layer == "0" and layer else entity.dxf.layer
        if entity.dxftype() == "INSERT":
            # Only an explicitly grouped opening can justify collapsing its
            # frame subpaths. Distinct bare entities may represent separate
            # doors/windows at the same coordinates; proximity is not identity.
            if OPENING_LAYERS[kind].search(_words(effective + " " + entity.dxf.name)):
                symbol_id = symbol_id or entity.dxf.get("handle", str(id(entity)))
                if not OPENING_LAYERS[kind].search(_words(effective)):
                    effective = entity.dxf.name
            if depth < 16:
                for child in entity.virtual_entities():
                    visit(child, effective, depth + 1, symbol_id)
            return
        if not OPENING_LAYERS[kind].search(_words(effective)) or entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
            return
        shape = _shape(entity, effective)
        if shape is None:
            return
        p = rectangle(shape) if kind == "door" else _points(shape) if _is_closed(shape) else None
        if p is not None and len(p) >= 3 and Polygon(p).is_valid and Polygon(p).area > 0:
            candidates.append((shape, p, Polygon(p), symbol_id))

    for entity in layout:
        visit(entity)
    out, kept = [], []
    # Outer common frame wins over inset frame outlines and duplicate exports.
    for shape, p, polygon, symbol_id in sorted(candidates, key=lambda c: -c[2].area):
        if symbol_id and any(owner == symbol_id and existing.buffer(EPS * math.sqrt(existing.area)).covers(polygon)
                             for existing, owner in kept):
            continue
        kept.append((polygon, symbol_id))
        props = {**shape.props, "classification": "closed_frame", "swing_radius_m": None}
        if kind == "door":
            props["leaf_len_m"] = float(max(np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1))) * unit_m if unit_m else None
        out.append(_item(kind, p, props, 1.0))
    return out
