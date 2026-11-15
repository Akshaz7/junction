"""Deterministic measurements for one plan-map item (no models, plain geometry).

    measures(item, m_per_px) -> dict

All lengths in metres, areas in m², rounded to 3 decimals. Values printed or
measured on the drawing (item ``props``) win over geometry; geometry needs a
scale. With no scale and no prop values the result is ``{}`` (never invented).

``source`` is 'drawing' when every value came from props, 'geometry' when every
value was computed from polygon/bbox with the scale, 'mixed' otherwise.
"""
from __future__ import annotations

import math

OPENING_KINDS = {"door", "window", "opening"}
NO_MEASURE_KINDS = {"text", "dimension", "label"}


def _r(v: float) -> float:
    return round(float(v), 3)


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _poly(item: dict) -> list[tuple[float, float]] | None:
    pts = item.get("polygon_px")
    if not pts or len(pts) < 3:
        return None
    try:
        out = [(float(p[0]), float(p[1])) for p in pts]
    except (TypeError, ValueError, IndexError):
        return None
    if len(out) > 3 and out[0] == out[-1]:
        out = out[:-1]
    return out if len(out) >= 3 else None


def shoelace_area(pts) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def perimeter(pts) -> float:
    n = len(pts)
    return sum(math.dist(pts[i], pts[(i + 1) % n]) for i in range(n))


def _bbox_wh(item: dict) -> tuple[float, float] | None:
    b = item.get("bbox_px")
    try:
        w, h = abs(float(b[2]) - float(b[0])), abs(float(b[3]) - float(b[1]))
    except (TypeError, ValueError, IndexError):
        return None
    return (w, h) if w > 0 or h > 0 else None


def wall_from_polygon(area: float, perim: float) -> tuple[float, float] | None:
    """(thickness, centreline length) of a constant-thickness strip polygon.

    For a strip of thickness t and centreline length L (straight, L, T, U...):
    A = t*L and P/2 = L + t, so t² - (P/2)t + A = 0; t is the smaller root.
    Exact for rectangles and L shapes; a fair estimate for other strips.
    """
    if area <= 0 or perim <= 0:
        return None
    half = perim / 2.0
    disc = max(half * half - 4.0 * area, 0.0)
    t = (half - math.sqrt(disc)) / 2.0
    if t <= 0:
        return None
    return t, area / t


def measures(item: dict, m_per_px: float | None) -> dict:
    kind = str(item.get("kind") or "").lower()
    props = item.get("props") or {}
    scale = _num(m_per_px)
    if kind in NO_MEASURE_KINDS:
        return {}

    out: dict = {}
    origins: set[str] = set()  # 'drawing' | 'geometry'

    def put(key, value, origin):
        if value is None:
            return
        out[key] = [_r(v) for v in value] if isinstance(value, (list, tuple)) else _r(value)
        origins.add(origin)

    poly = _poly(item)
    wh = _bbox_wh(item)

    if kind == "wall":
        length = _num(props.get("length_m"))
        thick = _num(props.get("thickness_m"))
        put("length_m", length, "drawing")
        put("thickness_m", thick, "drawing")
        if scale and (length is None or thick is None):
            g_len = g_thk = None
            lp, tp = _num(props.get("length_px")), _num(props.get("thickness_px"))
            if poly:
                est = wall_from_polygon(shoelace_area(poly), perimeter(poly))
                if est:
                    g_thk, g_len = est[0] * scale, est[1] * scale
            elif wh:
                g_len, g_thk = max(wh) * scale, min(wh) * scale
            if lp:
                g_len = lp * scale
            if tp:
                g_thk = tp * scale
            if length is None:
                put("length_m", g_len, "geometry")
            if thick is None:
                put("thickness_m", g_thk, "geometry")
        height = _num(props.get("height_m"))
        if height and "length_m" in out:
            out["face_area_m2"] = _r(out["length_m"] * height)

    elif kind == "room":
        area_p = _num(props.get("area_m2"))
        put("area_m2", area_p, "drawing")
        if scale and poly:
            a_meas = shoelace_area(poly) * scale * scale
            if area_p is None:
                put("area_m2", a_meas, "geometry")
            put("area_measured_m2", a_meas, "geometry")
            put("perimeter_m", perimeter(poly) * scale, "geometry")
        elif _num(props.get("perimeter_m")):
            put("perimeter_m", _num(props.get("perimeter_m")), "drawing")

    else:  # openings and fixtures (toilet, sink, shower, bathtub, stair, column, ...)
        width_p = _num(props.get("width_m"))
        depth_p = _num(props.get("depth_m"))
        put("width_m", width_p, "drawing")
        put("depth_m", depth_p, "drawing")
        if scale and wh:
            if width_p is None:
                put("width_m", max(wh) * scale, "geometry")
            if depth_p is None:
                put("depth_m", min(wh) * scale, "geometry")
            if kind not in OPENING_KINDS:
                put("size_m", (wh[0] * scale, wh[1] * scale), "geometry")

    if not out:
        return {}
    if origins == {"drawing"}:
        out["source"] = "drawing"
    elif origins == {"geometry"}:
        out["source"] = "geometry"
    else:
        out["source"] = "mixed"
    if "geometry" in origins:
        out["m_per_px"] = scale
    return out
