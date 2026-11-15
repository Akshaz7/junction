"""Apartment labels, room membership and net CAD outlines; no document-specific rules."""
from __future__ import annotations

import math
import re
import unicodedata

# Observed labels and outdoor names, plus the task's multilingual vocabulary:
# results/final/ACC-UNITS/constants.json. No learned geometry/size thresholds.
UNIT_LABEL = re.compile(
    r"^(?:whg|app|appt|apt|wohnung|appartement|appartamento|logement|apartment|flat|unit|"
    r"asunto|huoneisto|lgh|lägenhet|lagenhet|bostad)"
    r"\.?\s*(?:[-:#]\s*)?((?:[A-Za-zÀ-ÖØ-öø-ÿ]|[A-Za-z]*\d+[A-Za-z]*)(?:[-.][A-Za-z0-9]+)*)$", re.IGNORECASE)
ROOM_NUMBER = re.compile(r"^\d+(?:[.,]\d+)+$")
WRITTEN_AREA = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(m²|m2|sqm|sq\.?\s*m|ft²|ft2|sq\.?\s*ft)$", re.IGNORECASE)
OUTDOOR = re.compile(
    r"\b(?:balcon\w*|balkon\w*|loggi\w*|terrass\w*|terrac\w*|terraz\w*|dachterrass\w*|"
    r"sitzplatz\w*|verand\w*|wintergart\w*|jardin\w*|gart\w*|giardin\w*|patio\w*|"
    r"garden\w*|outdoor\w*|parveke\w*|terassi\w*|balkong\w*|uterum\w*)\b", re.IGNORECASE)


def unit_key(text):
    match = UNIT_LABEL.fullmatch(str(text or "").strip())
    return match.group(1).casefold() if match else None


def outdoor_room(text):
    folded = "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c))
    return bool(OUTDOOR.search(folded.replace("_", " ")))


def written_area(text):
    """Area and its written rounding precision, in m²; 1 ft = exactly 0.3048 m."""
    match = WRITTEN_AREA.fullmatch(text.strip())
    if not match:
        return None
    number = match.group(1).replace(",", ".")
    factor = 0.3048 ** 2 if "ft" in match.group(2).lower() else 1.0
    decimals = len(number.split(".")[1]) if "." in number else 0
    return float(number) * factor, 0.5 * 10 ** -decimals * factor


def polygon(points):
    """Invalid outlines stay visible, but must not silently yield a measured area."""
    from shapely.geometry import Polygon
    try:
        poly = Polygon(points)
        return poly if poly.is_valid and not poly.is_empty and math.isfinite(poly.area) and poly.area > 0 else None
    except (ValueError, TypeError):
        return None


def open_plan_split(net, names, unit_m):
    """Several differently named labels inside one closed region: the CAD gives no wall between them (an open-plan
    space, or openings the room builder bridged). Report each named sub-area from the nearest-label partition of the
    region. It is an estimate, not a drawn boundary, so the caller flags it; the region itself is never cut."""
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram
    seen = {}
    for t, x, y in names:
        seen.setdefault(t.casefold(), (t, x, y))
    if net is None or len(seen) < 2:
        return None
    pts = list(seen.values())
    try:
        cells = list(voronoi_diagram(MultiPoint([(x, y) for _, x, y in pts]), envelope=net.envelope.buffer(1)).geoms)
    except Exception:
        return None
    out = []
    for t, x, y in pts:
        from shapely.geometry import Point
        cell = next((c for c in cells if c.covers(Point(x, y))), None)
        part = net.intersection(cell) if cell is not None else None
        if part is None or part.is_empty:
            return None
        out.append({"name": t, "label_point": [x, y],
                    "area_m2_approx": round(part.area * unit_m ** 2, 6) if unit_m else None})
    return out


def assign_texts(rooms, texts):
    from shapely.geometry import Point
    polys = [polygon(r) for r in rooms]
    assigned = {i: [] for i in range(len(rooms))}
    for text, x, y in texts:
        if unit_key(text) is not None:
            continue
        owners = [i for i, poly in enumerate(polys) if poly is not None and poly.covers(Point(x, y))]
        if owners:
            # Labels on an outline's boundary count; innermost enclosing outline wins.
            owner = min(owners, key=lambda i: polys[i].area)
            assigned[owner].append((text, x, y))
    return assigned


def _membership(anchors, centroid, units):
    """A unique label-point owner wins; only a missing owner permits centroid fallback."""
    from shapely.geometry import Point
    def owners(point):
        return {i for i, unit in enumerate(units) if unit is not None and unit.covers(Point(point))}
    labelled = set().union(*(owners(p) for p in anchors)) if anchors else set()
    found = labelled or (owners(centroid) if centroid is not None else set())
    return (next(iter(found)), "label" if labelled else "centroid") if len(found) == 1 else (
        None, "ambiguous" if found else "unassigned")


def analyse(rooms, texts, outlines, unit_texts, unit_m, unit_closed=None):
    """Return room and unit records in source order; unrecognised outlines are retained.

    Each unlabelled descendant of a labelled room toggles filled area (even-odd).
    Labelled nested rooms are separate spaces, not holes inferred from their size.
    """
    polys = [polygon(r) for r in rooms]
    upolys = [polygon(r) if unit_closed is None or unit_closed[i] else None for i, r in enumerate(outlines)]
    assigned = assign_texts(rooms, texts)
    unit_assigned = {i: [] for i in range(len(outlines))}
    for text, x, y in unit_texts:
        if unit_key(text) is None:
            continue
        owner, _ = _membership([(x, y)], None, upolys)
        if owner is not None:
            unit_assigned[owner].append(text)
    units = []
    for i, poly in enumerate(upolys):
        labels = list(dict.fromkeys(unit_assigned[i]))
        keys = {unit_key(t) for t in labels}
        units.append({"label": labels[0] if len(keys) == 1 else "", "props": {
            "role": "unit", "unit_key": next(iter(keys)) if len(keys) == 1 else None,
            "unit_membership_version": 1,
            "area_m2_geom": round(poly.area * unit_m ** 2, 6) if poly is not None and unit_m else None,
            "classification": "labelled" if len(keys) == 1 else "ambiguous" if keys else "unlabelled",
            "geometry_valid": poly is not None}})

    # A void belongs to the nearest labelled ancestor, so a nested labelled room
    # does not cause its holes to be subtracted from both rooms.
    void_owner = {}
    for i, poly in enumerate(polys):
        if poly is None or assigned[i]:
            continue
        parents = [j for j, parent in enumerate(polys) if j != i and assigned[j] and parent is not None
                   and parent.area > poly.area and parent.covers(poly)]
        if parents:
            void_owner[i] = min(parents, key=lambda j: polys[j].area)
    records = []
    for i, poly in enumerate(polys):
        ts = assigned[i]
        names = [(t, x, y) for t, x, y in ts if not ROOM_NUMBER.fullmatch(t) and written_area(t) is None]
        name = names[0][0] if names else ""
        number = next((t for t, _, _ in ts if ROOM_NUMBER.fullmatch(t)), "")
        areas = [written_area(t) for t, _, _ in ts if written_area(t) is not None]
        props = {"number": number, "labelled": bool(name), "geometry_valid": poly is not None,
                 "area_m2_label": areas[0][0] if len(areas) == 1 else None,
                 "area_m2_geom": None, "unit_membership_version": 1}
        if i in void_owner:
            props.update(role="room_void", parent_room_index=void_owner[i])
        else:
            net = poly
            holes = [j for j, owner in void_owner.items() if owner == i]
            if poly is not None:
                for j in holes:
                    net = net.symmetric_difference(polys[j])
                if unit_m:
                    props["area_m2_geom"] = round(net.area * unit_m ** 2, 6)
                    props["void_area_m2"] = round((poly.area - net.area) * unit_m ** 2, 6)
            if holes:
                props["void_outline_indices"] = holes
            anchors = [(x, y) for _, x, y in (names or ts)]
            owner, method = _membership(anchors, (net.centroid.x, net.centroid.y) if net is not None else None, upolys)
            props.update(unit_index=owner, unit_membership_method=method, is_outdoor=outdoor_room(name))
            if anchors:
                props["label_point"] = list(anchors[0])
            if net is not None:
                props["centroid"] = [net.centroid.x, net.centroid.y]
            if props["area_m2_label"] is not None and props["area_m2_geom"] is not None:
                delta = props["area_m2_geom"] - props["area_m2_label"]
                props["area_crosscheck"] = {"difference_m2": round(delta, 6),
                    "agrees_at_written_precision": abs(delta) <= areas[0][1] + 0.5e-6}
            split = open_plan_split(net, names, unit_m)
            if split:
                props.update(open_plan=True, sub_areas=split,
                             sub_area_method="nearest label within one region with no drawn wall between the labels")
            if not ts:
                props["classification"] = "unlabelled"
        records.append({"label": name, "props": props})
    return records, units
