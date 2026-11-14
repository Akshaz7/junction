"""Ordering quantities from cited source data, with explicit waste and no model calls.

Areas are coverage, never invented pack sizes, sheet counts, paint yields or prices.
Missing measurements remain visible in the same exportable table.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from engine.solvers.data import Doc, Item
from engine.solvers.filters import STOREY_REQUEST, room_filter, storey_requested
from engine.solvers.solve import MIN_CONF, _answer_obj, _evidence, _step, resolve_storey
from engine.takeoff import CLASS_Q, ROOM_CLASSES, Takeoff, _matches, _tag_inside

_ASK = re.compile(r"\b(?:order|buy|purchase|procure|need|how much|how many|take[- ]?off)\b", re.I)
_MATERIALS = (
    ("Doors", "count", r"\bdoors?\b"),
    ("Windows", "count", r"\bwindows?\b"),
    ("Plasterboard", "wall", r"\b(?:plasterboard|drywall|gypsum board)\b"),
    ("Paint coverage", "wall", r"\bpaint(?:ing)?\b"),
    ("Floor tiles", "floor", r"\b(?:tiles?|tiling)\b"),
    ("Flooring", "floor", r"\b(?:flooring|laminate|parquet|vinyl|carpet|floor finish)\b"),
    ("Skirting", "length", r"\b(?:skirting|base ?boards?)\b"),
)
_WASTE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent)\s*(?:waste|wastage|extra|allowance|overage)?", re.I)


def wants_order(question: str) -> bool:
    if re.search(r"\bin what order\b|\border (?:of|by)\b", question, re.I):
        return False
    if re.search(r"\b(?:linear|metres?|meters?|lengths?|per room)\b", question, re.I) and not re.search(
            r"\b(?:order|buy|purchase|procure|waste|wastage|allowance|overage)\b", question, re.I):
        return False   # plain measurement questions stay with the measuring solvers
    return bool(_ASK.search(question) and (
        re.search(r"\b(?:order|buy|purchase|procure)\b", question, re.I)
        or any(re.search(rx, question, re.I) for _, typ, rx in _MATERIALS if typ != "count")))


def _number(*values):
    for value in values:
        try:
            if isinstance(value, bool):
                continue
            f = float(value)
            if math.isfinite(f) and f > 0:
                return f
        except (TypeError, ValueError):
            pass
    return None


def _scale(doc, room, root):
    # A multi-sheet drawing may have a different scale on every sheet.
    sc = doc.scale or {}
    if root is not None:
        try:
            sc = json.loads((Path(root) / doc.doc_id / f"planmap-{room.page}.json").read_text()).get("scale") or {}
        except (OSError, ValueError):
            if doc.pages > 1:
                return None
    elif doc.pages > 1:
        return None
    return _number(sc.get("m_per_px")) if sc.get("method") not in (None, "none") else None


def _floor_area(room, doc, root):
    p, q = room.props, room.q
    area = _number(q.get("net_floor_area_m2"), q.get("area_m2"), q.get("net_area_m2"), p.get("area_m2"))
    if area is not None:
        return area
    poly, scale = room.polygon_px, _scale(doc, room, root)
    if poly and len(poly) >= 3 and scale:
        from engine.reasoning import _shoelace
        return _number(_shoelace(poly) * scale ** 2)
    return None


def _selection(question, doc):
    st = resolve_storey(question, doc.storeys)
    if storey_requested(question) and st is None:
        return [], [], "The requested floor cannot be identified in this file; no other floor was substituted."
    items = [i for i in doc.items if (doc.mode == "ifc" or i.conf >= MIN_CONF) and (not st or i.storey == st)]
    rooms = [r for r in items if r.kind in ("room", "space")]
    scope_rooms = rooms
    scope_q = re.split(r"\b(?:excluding|except|not counting|without)\b", question, flags=re.I)[0]
    classes = [c for c, rx in CLASS_Q.items() if re.search(rx, scope_q, re.I)]
    scoped = False
    if classes:
        # Match the established wet-room take-off scope, while honouring explicit exclusions.
        if "bathroom" in classes and not re.search(r"\b(?:excluding|except|not counting|without)\b.*\b(?:wcs?|toilets?)\b", question, re.I):
            classes.append("toilet")
        ids = set()
        for cls in classes:
            tk = Takeoff(None, cls, re.compile(ROOM_CLASSES[cls], re.I))
            ids.update(r.item_id for r in rooms if _matches(r, tk))
            ids.update(r.item_id for r in rooms if r.name and re.search(rf"\b(?:{tk.rx.pattern})\b", r.name, re.I))
            if doc.mode == "planmap":
                tags = [i for i in items if i.kind in ("text", "other") and i.label and tk.rx.search(i.label)]
                ids.update(r.item_id for r in rooms if _tag_inside(r, tags) is not None)
        rooms = [r for r in rooms if r.item_id in ids]
        scoped = True
    else:
        picked = room_filter(scope_q, rooms)
        if picked:
            rooms = picked[1]
            scoped = True
        else:
            # An unknown explicit room name must not silently select the whole building.
            m = re.search(r"\bfor\s+(?:the\s+)?(.+?)(?=\s+(?:with|including|plus)\b|[?.]|$)", scope_q, re.I)
            if m:
                target = STOREY_REQUEST.sub("", m[1])
                if st:
                    target = re.sub(re.escape(st), "", target, flags=re.I)
                target = re.sub(r"\b(?:on|in|of|the)\b", "", target, flags=re.I).strip()
                if target and not re.fullmatch(r"(?:all |whole |entire )*(?:rooms?|building|model|plan|floor)", target, re.I):
                    return [], [], "The requested rooms cannot be identified in this file; no other rooms were substituted."
    excluded = re.split(r"\b(?:excluding|except|not counting|without)\b", question, maxsplit=1, flags=re.I)
    if len(excluded) == 2:
        # Resolve exclusions independently of the positive selection. A WC can
        # exist on this floor while already absent from the bathroom subset.
        picked = room_filter(excluded[1], scope_rooms)
        exclusion_classes = [c for c, rx in CLASS_Q.items() if re.search(rx, excluded[1], re.I)]
        excluded_ids = {r.item_id for r in picked[1]} if picked else set()
        for cls in exclusion_classes:
            tk = Takeoff(None, cls, re.compile(ROOM_CLASSES[cls], re.I))
            excluded_ids.update(r.item_id for r in scope_rooms if _matches(r, tk) or (r.name and tk.rx.search(r.name)))
        if not excluded_ids:
            return [], [], "The excluded rooms cannot be identified in this file; no exclusion was guessed."
        rooms = [r for r in rooms if r.item_id not in excluded_ids]
        scoped = True
    if scoped:
        if not rooms:
            return [], [], "No matching rooms were found in this file; no other rooms were substituted."
        ids = {r.item_id for r in rooms}
        opening_ids = {iid for r in rooms for iid in (r.props.get("door_ids") or [])}
        # Explicit spatial containment is preferable to guessing from overlapping bounding boxes.
        items = [i for i in items if i.item_id in ids or i.item_id in opening_ids or i.props.get("room_id") in ids
                 or set(i.props.get("room_ids") or []) & ids]
    return items, rooms, None


def _skirting(rooms, items, doc, root):
    """Use source net lengths or actual polygons and explicitly associated door widths."""
    values, used = [], []
    for r in rooms:
        net = _number(r.q.get("net_skirting_length_m"), r.props.get("net_skirting_length_m"))
        if net is None:
            if "door_ids" not in r.props:
                return _skirting_geometry(rooms, items, doc, root)
            doors = [i for i in items if i.item_id in r.props["door_ids"]]
            widths = [_number(d.q.get("width_m"), d.props.get("width_m")) for d in doors]
            if len(doors) != len(r.props["door_ids"]) or any(w is None for w in widths):
                return None, [], "Some associated door widths are missing."
            per = _number(r.q.get("perimeter_m"), r.props.get("perimeter_m"))
            scale, poly = _scale(doc, r, root), r.polygon_px
            if per is None and scale and poly and len(poly) >= 3:
                per = sum(math.dist(a, b) for a, b in zip(poly, poly[1:] + poly[:1])) * scale
            if per is None:
                return None, [], "A measured room perimeter is needed."
            net = per - sum(widths)
            if net < 0:
                return None, [], "Door widths exceed the recorded room perimeter; check the source."
            used.extend(doors)
        values.append(net)
        used.append(r)
    return (sum(values), used, "Room perimeters minus associated door widths.") if values else (None, [], "No room perimeters are recorded.")


def _skirting_geometry(rooms, items, doc, root):
    """Geometric best effort, labelled as such; uses outlines before rectangles."""
    if doc.mode != "ifc":
        from engine.honesty import room_boundary_problem
        if problem := room_boundary_problem(rooms):
            return None, [], problem
    from engine.analytics import DOOR_BAND, _foot
    total, used, rectangular = 0.0, [], False
    for r in rooms:
        scale = 1.0 if doc.mode == "ifc" else _scale(doc, r, root)
        if not scale:
            return None, [], "A drawing scale is needed for skirting lengths."
        if r.polygon_px and len(r.polygon_px) >= 3 and doc.mode != "ifc":
            poly = r.polygon_px
        else:
            box = _foot(r, doc.mode == "ifc")
            if not box:
                return None, [], "Room outlines are missing."
            x0, y0, x1, y1 = box
            poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            rectangular = True
        edges = list(zip(poly, poly[1:] + poly[:1]))
        per = sum(math.dist(a, b) for a, b in edges) * scale
        deduction = 0.0
        for d in items:
            if d.kind != "door" or (doc.mode == "ifc" and d.storey != r.storey) or (doc.mode != "ifc" and d.page != r.page):
                continue
            box = _foot(d, doc.mode == "ifc")
            if not box:
                continue
            p = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            def distance(a, b):
                vx, vy = b[0] - a[0], b[1] - a[1]
                den = vx * vx + vy * vy
                t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / den)) if den else 0.0
                return math.dist(p, (a[0] + t * vx, a[1] + t * vy)) * scale
            if min(distance(a, b) for a, b in edges) <= DOOR_BAND:
                width = _number(d.q.get("width_m"), d.props.get("width_m"))
                if width is None:
                    return None, [], "A nearby door has no measured width; its opening cannot be deducted."
                deduction += width
                used.append(d)
        if deduction > per:
            return None, [], "Detected door openings exceed the room perimeter; check the drawing."
        total += per - deduction
        used.append(r)
    how = "Estimated room rectangles minus nearby door widths." if rectangular else "Room outlines minus nearby door widths; check opening associations."
    return (total, used, how) if rooms else (None, [], "Room outlines are missing.")


def answer_order(question: str, doc: Doc, t0=None, *, root=None) -> dict | None:
    if not wants_order(question):
        return None
    t0 = t0 or time.perf_counter()
    materials = [(label, typ) for label, typ, rx in _MATERIALS if re.search(rx, question, re.I)]
    unspecified = not materials
    if unspecified:
        materials = [("Floor finish (confirm material)", "floor"), ("Wall finish (confirm material)", "wall"), ("Doors", "count")]
    if re.search(r"\bwall\s+(?:tiles?|tiling)\b|\b(?:tiles?|tiling)\s+(?:for|on)\s+(?:the\s+)?walls?\b", question, re.I):
        materials = [("Wall tiles", "wall") if label == "Floor tiles" else (label, typ) for label, typ in materials]
    if re.search(r"\bceiling\b", question, re.I):
        materials = [("Ceiling paint coverage", "floor") if label == "Paint coverage" else (label, typ) for label, typ in materials]
    items, rooms, error = _selection(question, doc)
    wm = _WASTE.search(question)
    pct = float(wm[1].replace(",", ".")) if wm else 0.0
    notes = []
    if wm and (not math.isfinite(pct) or (wm.start() > 0 and question[wm.start() - 1] in "-−")):
        error = "Waste must be a finite, non-negative percentage; no allowance was guessed."
        pct = 0.0
    percentages = [float(m[1].replace(",", ".")) for m in _WASTE.finditer(question)]
    if len(set(percentages)) > 1:
        error = "Several percentages are given; specify one waste percentage for this order list."
    if re.search(r"\b(?:waste|allowance)\b", question, re.I) and not wm:
        error = "Specify a numeric waste percentage; no allowance was guessed."
    if error:
        notes.append(error)
    if unspecified:
        notes.append("Finish materials are not specified here; confirm the finish schedule before ordering.")
    if re.search(CLASS_Q["bathroom"], question, re.I) and not re.search(r"\b(?:excluding|except|not counting|without)\b", question, re.I):
        notes.append("Bathroom quantities include shower rooms and WCs.")
    if error:
        notes.append("Resolve the missing scope or allowance before placing this order.")
    elif not wm:
        notes.append("0% waste applied; change it by asking for a waste percentage.")
    else:
        notes.append(f"{pct:g}% waste applied as requested.")
    if doc.mode == "planmap" and (doc.scale or {}).get("method") == "door-prior":
        notes.append("The drawing scale is estimated from door widths; verify sizes before ordering.")
    rows, cites, boxes, highlights, values, calculations = [], [], [], [], {}, []
    incomplete = bool(error)
    estimated = False
    for label, typ in materials:
        unit = "count" if typ == "count" else "m" if typ == "length" else "m2"
        measured, used, how = None, [], "No matching measurements in this file."
        if not error and typ == "count":
            kind = "door" if label == "Doors" else "window"
            used = [i for i in items if i.kind == kind]
            if used:
                measured, how = len(used), "Counted the cited elements."
        elif not error and typ == "floor":
            areas = [_floor_area(r, doc, root) for r in rooms]
            if rooms and all(a is not None for a in areas):
                measured, used, how = sum(areas), rooms, "Sum of recorded floor areas or scaled room outlines."
                if label.startswith("Ceiling"):
                    how = "Ceiling coverage estimated from floor area; check slopes and voids."
                    estimated = True
                    notes.append("Paint is coverage area; litres need product coverage and coat count.")
            elif rooms:
                how = "Some room areas are missing; no partial total was used."
        elif not error and typ == "wall":
            # Only explicit NET side areas: gross or generic area may include openings.
            candidates = rooms if any(_number(r.q.get("net_wall_area_m2"), r.props.get("net_wall_area_m2")) for r in rooms) else [i for i in items if i.kind == "wall"]
            areas = [_number(i.q.get("net_wall_area_m2"), i.props.get("net_wall_area_m2")) if i.kind in ("room", "space")
                     else _number(i.q.get("net_side_area_m2"), i.props.get("net_side_area_m2")) for i in candidates]
            if candidates and all(a is not None for a in areas):
                measured, used, how = sum(areas), candidates, "Net wall area; openings deducted in source quantities, one face."
            else:
                how = "Net wall areas with openings deducted are missing; gross areas were not used."
            if label == "Paint coverage":
                notes.append("Paint is listed as coverage area; litres need the product coverage rate and number of coats.")
            if label == "Plasterboard":
                notes.append("Plasterboard is listed as one layer of coverage; sheets need board dimensions and layer count.")
        elif not error and typ == "length":
            measured, used, how = _skirting(rooms, doc.items, doc, root)
            estimated |= measured is not None and ("Estimated" in how or "nearby" in how)
        if measured is not None and not math.isfinite(measured * (1 + pct / 100) * 100):
            measured, used, how = None, [], "The recorded quantity or allowance is too large to calculate reliably."
        src = ""
        if used and measured is not None:
            bx, cs, _ = _evidence(doc, used)
            offset = len(cites)
            for c in cs:
                cites.append(dict(c, n=offset + c["n"]))
            src = "".join(f"[{c['n']}]" for c in cites[offset:])
            seen = {b["item_id"] for b in boxes}
            for b in bx:
                if b["item_id"] not in seen:
                    boxes.append(dict(b, label=str(len(boxes) + 1)))
                    seen.add(b["item_id"])
            highlights.extend(i.item_id for i in used if i.item_id not in highlights)
        if measured is None:
            incomplete = True
            quantity = "not in this file"
        else:
            need = measured * (1 + pct / 100)
            # Counts are whole items; area/length rounded upward to avoid under-ordering.
            need = math.ceil(need - 1e-9) if typ == "count" else math.ceil(need * 100 - 1e-9) / 100
            values[label] = need
            quantity = str(need) if typ == "count" else f"{need:.2f}".rstrip("0").rstrip(".")
            calculations.append(f"{label}: {str(measured).removesuffix('.0')} {unit} × (1 + {pct:g}%) = {quantity} {unit}" + (", rounded up to whole items" if typ == "count" else ", rounded up to 0.01"))
        rows.append(f"| {label} | {quantity} | {unit if measured is not None else ''} | {pct:g}% | {how} | {src} |")
    if len(values) == 1 and len(materials) == 1:
        label, value = next(iter(values.items()))
        head = f"**Order {quantity} {'items' if materials[0][1] == 'count' else 'm' if materials[0][1] == 'length' else 'm²'} of {label.lower()}.**"
    else:
        value = values or None
        head = f"**Order list: {len(values)} measured quantities" + ("; missing data needs checking." if incomplete else ".") + "**"
    text = head + "\n\n| Item | Quantity | Unit | Waste % | How measured | Source |\n|---|---|---|---|---|---|\n" + "\n".join(rows)
    text += "\n\n" + "\n".join(f"- {n}" for n in dict.fromkeys(notes))
    trace = [_step("order", "Ordering from cited source measurements; no model call."),
             *[_step("order_compute", c) for c in calculations]]
    scene = {"doc_id": doc.doc_id, "highlight_item_ids": highlights, "camera_target_item_id": highlights[0] if highlights else None}
    conf = 0.5 if incomplete or estimated or (doc.mode == "planmap" and (doc.scale or {}).get("confidence", 0) < 0.5) else 0.9
    return _answer_obj(question, [doc.doc_id], text, value, unit if len(materials) == 1 else "quantities", conf, False,
                       boxes, cites, scene, trace, "index" if doc.mode == "ifc" else "planmap", t0)
