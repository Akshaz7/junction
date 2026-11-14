"""E-79 part: the 'Checked' step: an independent second source that agrees or differs.

This part owns every Checked step. Only real, computed cross-checks are emitted; with none available nothing is added.
"""
from __future__ import annotations

import re

from engine.reasoning import _fmt, _name, _shoelace

_PRINTED = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*(?:²|2)\b", re.I)
_TYPE_WORDS = {  # printed word (lowercase prefix) -> room type; only used when both reads exist
    "wc": "toilet", "bad": "bathroom", "bath": "bathroom", "kitchen": "kitchen", "küche": "kitchen", "kok": "kitchen",
}


def _inside(pt, poly) -> bool:
    x, y = pt
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            ins = not ins
    return ins


def _printed_in_room(room, doc) -> float | None:
    """A printed 'NN.N m²' text whose centre sits inside the room outline (raster plans)."""
    poly = room.polygon_px
    if not poly or len(poly) < 3 or doc is None:
        return None
    found = []
    for t in doc.items:
        if t.kind != "text" or not t.bbox_px or t.page != room.page or not t.label:
            continue
        m = _PRINTED.search(t.label)
        if not m:
            continue
        b = t.bbox_px
        if _inside(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), poly):
            found.append(float(m.group(1).replace(",", ".")))
    return found[0] if len(found) == 1 else None


def _room_pair(room, doc, mpp):
    """(printed m², measured m², source) for a plan-map room, or None."""
    p = room.props or {}
    lab, geom = p.get("area_m2_label"), p.get("area_m2_geom")
    if lab and geom:
        return float(lab), float(geom), "cad"
    if not mpp:
        return None
    printed = _printed_in_room(room, doc)
    if not printed:
        return None
    px = _shoelace(room.polygon_px) if room.polygon_px and len(room.polygon_px) >= 3 else float(p.get("area_px") or 0)
    return (printed, px * mpp * mpp, "raster") if px else None


def _pct(a, b) -> float:
    return abs(a - b) / max(abs(a), 1e-9) * 100


def run(ctx: dict) -> None:
    ans, trace, unit, value = ctx['ans'], ctx['trace'], ctx['unit'], ctx['value']
    doc, is_ifc, sc, first_cite = ctx['doc'], ctx['is_ifc'], ctx['sc'], ctx['first_cite']
    rooms = ctx.get('rooms') or [it for it in ctx['cited'] if it.kind in ("room", "space")]
    steps = [s for s in ctx['steps'] if s.get('kind') != 'checked']   # drop any Checked step another part left behind
    checked = None
    new = None
    area_q = ctx.get('area_q') or unit == "m2"

    # 1. Vision recount vs plan map
    for s in trace:
        m = re.search(r"plan map (\d+), drawing re-read (\d+)", str(s.get("detail") or ""))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            new = {"kind": "checked", "title": "Checked", "ok": a == b, "cite": None,
                   "text": f"A second, independent look counted {b}; matches the {a} boxed" if a == b
                   else f"A second, independent look counted {b}; kept the {a} boxed"}
            break

    # 2. Printed area vs measured outline (CAD label, or a printed label read inside a raster room)
    if new is None and area_q and rooms and not is_ifc:
        from engine.scales import item_scale
        pairs = [(r, _room_pair(r, doc, float(item_scale(r, sc).get("m_per_px") or 0))) for r in rooms[:12]]
        pairs = [(r, p) for r, p in pairs if p]
        if pairs:
            tol = 1.0 if all(p[2] == "cad" for _, p in pairs) else 5.0
            if len(pairs) == 1:
                r, (lab, meas, _src) = pairs[0]
                d = _pct(lab, meas)
                ok = d <= tol
                txt = (f"Printed label says {_fmt(lab)} m²; matches within {_fmt(max(d, 0.1), 1)}%" if ok
                       else f"Printed label says {_fmt(lab)} m²; outline measures {_fmt(meas, 1)} m² ({_fmt(d, 0)}% apart)")
                new = {"kind": "checked", "title": "Checked", "text": txt, "cite": first_cite.get(r.item_id), "ok": ok}
            else:
                good = sum(1 for _, (lab, meas, _s) in pairs if _pct(lab, meas) <= tol)
                ok = good == len(pairs)
                new = {"kind": "checked", "title": "Checked", "cite": None, "ok": ok,
                       "text": f"Printed areas on {good} of {len(pairs)} rooms match their measured outlines within {_fmt(tol, 0)}%"
                       if ok else f"Printed areas match the measured outlines on {good} of {len(pairs)} rooms"}

    # 3. IFC: stored room area vs the room's own geometry footprint
    if new is None and is_ifc and area_q and len(rooms) == 1:
        r = rooms[0]
        q = r.q or {}
        area = q.get("area_m2") or q.get("net_floor_area_m2")
        bb = r.bbox_m
        if area and bb and len(bb) == 2:
            dx, dz = abs(bb[1][0] - bb[0][0]), abs(bb[1][2] - bb[0][2])   # y is up
            foot = dx * dz
            if foot > 0.5:
                ok = 0.6 * foot <= float(area) <= foot * 1.02
                new = {"kind": "checked", "title": "Checked", "cite": first_cite.get(r.item_id), "ok": ok,
                       "text": (f"Stored area {_fmt(area, 1)} m² fits the room's {_fmt(dx, 1)} × {_fmt(dz, 1)} m footprint ({_fmt(foot, 1)} m²)" if ok
                                else f"Stored area {_fmt(area, 1)} m² does not fit the room's {_fmt(dx, 1)} × {_fmt(dz, 1)} m footprint")}

    # 4. Printed label agrees with the model's own room-type reading (raster, single room)
    if new is None and len(rooms) == 1 and not is_ifc:
        p = rooms[0].props or {}
        lt, mt = p.get("label_room_type"), p.get("model_room_type")
        nm = _name(rooms[0])
        if lt and mt and lt == mt and nm:
            new = {"kind": "checked", "title": "Checked", "cite": first_cite.get(rooms[0].item_id), "ok": True,
                   "text": f"The printed word \"{nm}\" and the model's own reading both say {str(lt).replace('_', ' ')}"}

    if new:
        steps.append(new)
        checked = new["ok"]
    ctx.update(steps=steps, checked=checked)
