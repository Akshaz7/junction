"""Room membership for apartment sums, including older CAD plan-map caches."""
import math

from pipeline.dxf_units import outdoor_room


def covers(point, poly):
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        cross = (x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)
        if cross == 0 and min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1):
            return True
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def centroid(poly):
    """Area-weighted polygon centroid; a bounding-box centre is wrong for concave rooms."""
    if not poly or len(poly) < 3:
        return None
    area = xsum = ysum = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        xsum += (x0 + x1) * cross
        ysum += (y0 + y1) * cross
    return (xsum / (3 * area), ysum / (3 * area)) if area else None


def indoor_rooms(doc, unit):
    """Return matched indoor rooms and any matched rooms with unavailable measurements."""
    units = [u for u in doc.items if u.props.get("role") == "unit" and u.page == unit.page and u.polygon_px]
    rooms, missing = [], []
    for room in doc.items:
        if room.kind != "room" or room.page != unit.page or outdoor_room(room.label) or room.props.get("is_outdoor"):
            continue
        props = room.props
        if props.get("unit_membership_version"):
            belongs = props.get("unit_item_id") == unit.item_id
        else:
            anchor = props.get("label_point_px") or props.get("centroid_px") or centroid(room.polygon_px)
            if anchor is None and room.bbox_px:
                b = room.bbox_px
                anchor = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            owners = [u for u in units if anchor is not None and covers(anchor, u.polygon_px)]
            belongs = len(owners) == 1 and owners[0].item_id == unit.item_id
        if not belongs:
            continue
        area = room.q.get("area_m2")
        # Preserve the existing geometric sum for unlabelled standalone outlines.
        # Their use is unknown: the caller must flag the total as an estimate.
        unknown_outline = props.get("classification") == "unlabelled" and props.get("geometry_valid")
        if (room.conf < 0.5 and not unknown_outline) or not isinstance(area, (int, float)) or isinstance(area, bool) or not math.isfinite(area) or area < 0:
            missing.append(room)
        else:
            rooms.append(room)
    return rooms, missing


def uncertain_hint(rooms, total):
    unknown = [r for r in rooms if r.props.get("classification") == "unlabelled"]
    if not unknown:
        return None
    reason = f"The sum includes {len(unknown)} unlabelled outlines; their room use is unknown."
    hint = {"pct_cap": round(min(r.conf for r in unknown) * 100), "reason": reason,
            "improve": "Check the unlabelled outlines before relying on the apartment total.",
            "steps": [
                {"kind": "found", "title": "Found", "text": f"{len(rooms)} indoor room outlines assigned to this apartment", "cite": 1, "ok": None},
                {"kind": "calculated", "title": "Calculated", "text": f"Indoor room areas sum to {total:.2f} m²; outdoor rooms excluded", "cite": None, "ok": None},
                {"kind": "checked", "title": "Checked", "text": reason, "cite": None, "ok": False}]}
    pairs = [r.props["area_crosscheck"] for r in rooms if r.props.get("area_crosscheck")]
    if pairs:
        good = sum(p["agrees_at_written_precision"] for p in pairs)
        hint["steps"].append({"kind": "checked", "title": "Checked", "cite": None,
                              "text": f"{good} of {len(pairs)} written room areas match geometry at their written precision",
                              "ok": good == len(pairs)})
    return hint
