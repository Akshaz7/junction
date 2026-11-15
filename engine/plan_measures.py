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


# ---------------------------------------------------------------- calc records for plan-map room areas (engine.calc format)

def _room_name(item) -> str:
    rt = str((item.props or {}).get("room_type") or "room")
    return f"{item.label} ({rt})" if item.label and item.label.casefold() != rt.casefold() else (item.label or rt)


def _room_scale(doc, item):
    """(m/px, source field) the item's area was scaled with: its own view scale, else its page's selected scale."""
    ms = (item.props or {}).get("measurement_scale")
    if isinstance(ms, dict):
        return _num(ms.get("m_per_px")), "props.measurement_scale.m_per_px"
    page = ((doc.meta or {}).get("page_scales") or {}).get(item.page) or doc.scale or {}
    return _num(page.get("m_per_px")), "scale.m_per_px"


def room_area_steps(doc, item, value: float, sid: str) -> tuple[list[dict], dict | None]:
    """Steps that rebuild one plan-map room area exactly: pixel area × (m/px)², then the stored rounding.

    The pixel area is the room's filled pixel count (``props.area_px``, what the extractor scaled) or, without
    it, the shoelace area of ``polygon_px``. Returns ([], None) when those inputs do not reproduce ``value``
    (for example a printed area label): the row then cites the stored quantity instead.
    """
    from engine.calc import close, evaluate, input_value, places, polygon_area_step, source, step, step_source
    sref = source(doc, item)
    scale, sfield = _room_scale(doc, item)
    if not scale:
        return [], None
    steps = []
    px = _num((item.props or {}).get("area_px"))
    if px is not None:
        px_input = input_value("filled pixel area", px, "px2", {**sref, "field": "props.area_px"})
        how = "filled pixel area"
    elif _poly({"polygon_px": item.polygon_px}):
        steps.append(polygon_area_step(sid + "-shoelace", [list(p) for p in _poly({"polygon_px": item.polygon_px})], sref))
        px = steps[-1]["value"]
        px_input = input_value("outline area (shoelace)", px, "px2", step_source(sid + "-shoelace"))
        how = "outline area (shoelace)"
    else:
        return [], None
    sc_ref = {**sref, "field": sfield} if sfield.startswith("props.") else {**sref, "kind": "scale", "item_id": None, "field": sfield}
    measured = evaluate("multiply", [px, scale, scale])
    nd = places(value)
    if close(measured, value):
        last = sid
    elif close(round(measured, nd), value):
        last = sid + "-round"
    else:
        return [], None
    steps.append(step(sid if last == sid else sid + "-m2", f"{_room_name(item)}: {how} × scale²", "pixel area × metres per pixel × metres per pixel",
                      measured, "m2", [px_input, input_value("metres per pixel", scale, "m/px", sc_ref),
                                       input_value("metres per pixel", scale, "m/px", sc_ref)],
                      "Scale confidence is not an error bound.", "multiply"))
    if last != sid:
        steps.append(step(sid, f"{_room_name(item)}: stored room area", f"round({measured}, {nd})", value, "m2",
                          [input_value("measured area", measured, "m2", step_source(sid + "-m2")),
                           input_value("decimal places", nd, "decimal places", {"kind": "policy", "text": "Room areas are stored to this precision in the plan map"})],
                          operation="round"))
    return steps, {"px": px, "how": how, "m_per_px": scale, "measured": measured, "rounded": last != sid}


def room_area_calc(res: dict, doc, rooms: list, excluded=(), question: str = "", total=None) -> dict | None:
    """Calc record for a plan-map room area or a sum of room areas that reproduces the answer exactly.

    rooms: Items whose stored area (engine.solvers.solve._qty) was added; excluded: (Item, reason) pairs the
    route left out, kept in ``calc['excluded']`` with their area so the reader sees what was not counted.
    None when the stored areas do not add up to the answer (overlap unions, per-element answers ...).
    """
    from engine.calc import close, evaluate, input_value, number, places, row, source, step, step_source
    from engine.solvers.solve import _qty
    value = (res.get("answer") or {}).get("value") if total is None else total
    if not number(value) or not rooms or any((it.props or {}).get("no_outline") for it in rooms):
        return None   # rooms derived from a text label (pipeline.room_labels) have no saved outline to replay
    steps, rows, terms, checks = [], [], [], []
    for idx, it in enumerate(rooms):
        v = _qty(it, "room" if it.kind == "space" else it.kind, "area", question)
        if not number(v):
            return None
        sid = f"room-{idx}"
        st, info = room_area_steps(doc, it, v, sid)
        steps += st
        r = row(doc, it, v, "m2", kind=it.kind)
        r["label"] = _room_name(it)
        r["source"]["field"] = "quantities.area_m2"
        if info:
            r["measured_by"] = sid
            r["method"] = f"{info['how']} × (m/px)²" + (", rounded as stored" if info["rounded"] else "")
            terms.append(input_value(r["label"], v, "m2", step_source(sid)))
        else:
            terms.append(input_value(r["label"], v, "m2", r["source"]))
        printed, geom = (it.props or {}).get("area_m2_label"), (it.props or {}).get("area_m2_geom")
        if number(printed) and number(geom):
            checks.append({"method": "printed label versus outline", "value": printed, "agrees": close(printed, geom, .005),
                           "diff_pct": abs(printed - geom) / abs(printed) * 100 if printed else None, "source": r["source"]})
        rows.append(r)
    raw = evaluate("sum", [t["value"] for t in terms])
    nd = places(value)
    if not close(round(raw, nd), value) and not close(raw, value):
        return None
    if len(terms) > 1:
        steps.append(step("sum", "Add room areas", " + ".join(f"{t['value']:g}" for t in terms), raw, "m2", terms, operation="sum"))
        top = "sum"
    else:
        top = rows[0].get("measured_by") or "sum"
        if top == "sum":
            steps.append(step("sum", "Stored room area", "recorded source value", raw, "m2", terms, operation="source"))
    steps.append(step("result", "Round for the answer", f"round({raw}, {nd})", value, "m2",
                      [input_value("unrounded total" if len(terms) > 1 else "room area", raw, "m2", step_source(top)),
                       input_value("decimal places", nd, "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})],
                      operation="round"))
    left = []
    for it, why in excluded:
        a = _qty(it, "room" if it.kind == "space" else it.kind, "area", question)
        left.append({"item_id": it.item_id, "label": _room_name(it), "area_m2": a if number(a) else None, "reason": why,
                     "source": source(doc, it)})
    formula = ("total = Σ(room areas); " if len(terms) > 1 else "") + "room area = pixel area × (metres per pixel)², rounded as stored"
    return {"formula": formula, "steps": steps, "rows": rows, "checks": checks, "margin": {}, "issues": [],
            "result": {"value": value, "unit": "m2", "rounded_as": f"{nd} decimal places"},
            "row_key": "area_m2", "row_total_step": top, **({"excluded": left} if excluded else {})}


def room_area_default(res: dict, question: str, root) -> dict | None:
    """engine.calc hook: an m² answer citing only plan-map rooms gets the exact per-room chain (no route seed needed)."""
    from engine.calc import _cited, number, unit_name
    ans = res.get("answer") or {}
    if unit_name(ans.get("unit")) != "m2" or not number(ans.get("value")):
        return None
    items, missing = _cited(res, root)
    if missing or not items or len({id(d) for d, _ in items}) != 1:
        return None
    doc = items[0][0]
    if doc.mode != "planmap" or any(it.kind != "room" for _, it in items):
        return None
    import json
    from pathlib import Path
    saved = {}
    for _, it in items:   # derived rooms (e.g. wet-room labels) are not in the artifact: keep the generic record
        if it.page not in saved:
            try:
                pm = json.loads((Path(root) / (doc.meta.get("sheet_of") or doc.doc_id) / f"planmap-{it.page}.json").read_text())
            except (OSError, ValueError):
                return None
            saved[it.page] = {x.get("item_id") for x in pm.get("items", [])}
        if it.item_id not in saved[it.page]:
            return None
    return room_area_calc(res, doc, [it for _, it in items], question=question)


def _short(v: float, nd: int = 2) -> str:
    return f"{v:,.{nd}f}"


def room_total_hint(calc: dict) -> list[dict]:
    """Found / Measured / Calculated lines for a plan-map room total, built from the calc record itself."""
    rows, left = calc.get("rows") or [], calc.get("excluded") or []
    steps = {s["id"]: s for s in calc.get("steps") or []}
    if not rows:
        return []
    n = len(rows)
    out_txt = "; ".join(f"{e['label']}" + (f" {_short(e['area_m2'])} m²" if e.get("area_m2") is not None else "") + f" ({e['reason']})"
                        for e in left[:6]) + (f"; {len(left) - 6} more" if len(left) > 6 else "")
    found = f"{n} {'room' if n == 1 else 'rooms'} added" + (f"; left out: {out_txt}." if left else "; nothing left out.")
    per = []
    scales = set()
    for r in rows[:10]:
        s = steps.get(r.get("measured_by") or "")
        m = steps.get((r.get("measured_by") or "") + "-m2") or s
        px = next((i["value"] for i in (m or {}).get("inputs", []) if i.get("unit") == "px2"), None)
        mpp = next((i["value"] for i in (m or {}).get("inputs", []) if i.get("unit") == "m/px"), None)
        if px is not None and mpp is not None:
            scales.add(round(mpp, 12))
            per.append(f"{r['label']} {px:,.0f} px² → {_short(r['values']['area_m2'])} m²")
        else:
            per.append(f"{r['label']} {_short(r['values']['area_m2'])} m² (stored)")
    if len(rows) > 10:
        per.append(f"{len(rows) - 10} more")
    how = rows[0].get("method") or "stored area"
    sc = f" with {next(iter(scales)):.4g} m/px" if len(scales) == 1 else ""
    measured = f"Each room: {how}{sc}. " + "; ".join(per) + "."
    total = steps.get(calc.get("row_total_step") or "")
    calc_txt = (" + ".join(_short(r["values"]["area_m2"]) for r in rows[:12]) + (f" + {len(rows) - 12} more" if len(rows) > 12 else "")
                + f" = {_short((total or {}).get('value', calc['result']['value']))} m²")
    return [{"kind": "found", "title": "Found", "text": found, "cite": 1, "ok": None},
            {"kind": "measured", "title": "Measured", "text": measured, "cite": 1, "ok": None},
            {"kind": "calculated", "title": "Calculated", "text": calc_txt + ".", "cite": None, "ok": None}]
