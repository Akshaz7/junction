"""Plan map from a DXF that does not use the Swiss Dwellings layer names.

Only what the CAD file itself says: wall layers by name, rooms as the closed gaps between wall rings (door openings
closed by a morphological closing no wider than a door), room labels from TEXT, and doors/windows from their layers.
Units come from $INSUNITS (pipeline.scale_provenance); nothing here reads an image or calls a model. Fixtures are
handled by pipeline.dxf_symbols (named blocks / sanitary layers); a fixture with no block or layer is never invented.
"""
from __future__ import annotations

import math
import re

from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import unary_union

WALL_LAYER = re.compile(r"(?i)(?:^|[^a-z])(?:walls?|mur|murs|wand|waende|wande|sein[aä]|vagg)(?:$|[^a-z])")
DOOR_LAYER = re.compile(r"(?i)(?:^|[^a-z])(?:doors?|tuer\w*|portes?|ovi)(?:$|[^a-z])")
WINDOW_LAYER = re.compile(r"(?i)(?:^|[^a-z])(?:windows?|glaz\w*|glazing|fenster\w*|ikkuna\w*)(?:$|[^a-z])")
LABEL_SKIP = re.compile(r"\d")
MAX_LABEL_WORDS = 4
DOOR_GAP_M = 1.3   # widest opening a room boundary may bridge (a cased opening, not an open-plan room)


def _is(rx, layer):
    return bool(rx.search(layer or ""))


def wall_polygons(ms):
    polys = []
    for e in ms.query("LWPOLYLINE POLYLINE"):
        if not _is(WALL_LAYER, e.dxf.layer):
            continue
        pts = [(float(p.x), float(p.y)) for p in (e.vertices_in_wcs() if e.dxftype() == "LWPOLYLINE" else e.points_in_wcs())]
        if len(pts) >= 3:
            g = Polygon(pts)
            polys.append(g if g.is_valid else g.buffer(0))
    return polys


def room_labels(ms):
    """TEXT/MTEXT that names a space: letters only, short. Dimensions, areas and titles carry digits or are long."""
    out = []
    for e in ms.query("TEXT MTEXT"):
        text = (e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text).strip()
        if not text or LABEL_SKIP.search(text) or len(text.split()) > MAX_LABEL_WORDS or len(text) > 32:
            continue
        v = e.dxf.insert
        out.append((text, float(v.x), float(v.y)))
    return out


def derive_rooms(ms, unit_m):
    """Closed room polygons in native units: holes of the wall footprint after bridging door-sized gaps."""
    walls = wall_polygons(ms)
    if not walls or not unit_m:
        return []
    g = DOOR_GAP_M / unit_m / 2
    footprint = unary_union(walls).buffer(g, join_style=2).buffer(-g, join_style=2)
    parts = list(footprint.geoms) if footprint.geom_type == "MultiPolygon" else [footprint]
    holes = [Polygon(i) for p in parts for i in p.interiors]
    min_area = (0.9 / unit_m) ** 2  # a closet is bigger than 0.9 m square
    return [[(float(x), float(y)) for x, y in h.exterior.coords[:-1]] for h in holes if h.area >= min_area]


def openings(ms, unit_m):
    """Doors: one per swing ARC on a door layer. Windows: each connected group of glazing lines. Native coordinates."""
    doors, windows = [], []
    for e in ms.query("ARC"):
        if _is(DOOR_LAYER, e.dxf.layer):
            pts = [(float(p.x), float(p.y)) for p in e.flattening(max(e.dxf.radius / 8, 1e-6))]
            hull = MultiPoint(pts + [(float(e.dxf.center.x), float(e.dxf.center.y))]).convex_hull
            if hull.geom_type == "Polygon":
                doors.append({"polygon": list(hull.exterior.coords[:-1]), "leaf_len": float(e.dxf.radius)})
    lines = []
    for e in ms.query("LINE LWPOLYLINE"):
        if _is(WINDOW_LAYER, e.dxf.layer):
            if e.dxftype() == "LINE":
                lines.append(LineString([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]))
            else:
                lines.append(LineString([(p[0], p[1]) for p in e.get_points()]))
    if lines:
        tol = 0.1 / unit_m if unit_m else 1.0
        merged = unary_union([l.buffer(tol) for l in lines])
        for comp in (merged.geoms if merged.geom_type == "MultiPolygon" else [merged]):
            box = comp.minimum_rotated_rectangle
            if box.geom_type == "Polygon":
                windows.append({"polygon": list(box.exterior.coords[:-1])})
    return doors, windows


FEET_INCH = re.compile(r"""^\s*(\d+)'(?:-?\s*(\d+(?:\.\d+)?)")?\s*[xX×]\s*(\d+)'(?:-?\s*(\d+(?:\.\d+)?)")?\s*$""")


def printed_size_m(text):
    """'7'-8" x 6'-4"' -> (2.337, 1.930) m, else None. Exact conversion: 1 ft = 0.3048 m."""
    m = FEET_INCH.match(text or "")
    if not m:
        return None
    f = lambda ft, inch: (int(ft) + float(inch or 0) / 12) * 0.3048
    return f(m.group(1), m.group(2)), f(m.group(3), m.group(4))
