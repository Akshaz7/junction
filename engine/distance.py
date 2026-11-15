"""Straight-line distances between two named things ("distance between the kitchen and the bathroom", "how far is
the entrance from the stairs", "gap between bedroom and kitchen"), measured in code with every input recorded.

Plan maps: the area centroid of each room outline (or the centre of its box when no outline was found), in page
pixels; Δx, Δy, √(Δx² + Δy²) px, × the page/view scale (m/px and its method) = metres.
IFC models: the centre of each element's bounding box in model metres (x, z; y is up), no scale involved.
Closest edges (outline to outline) are measured as well; "gap" / "clearance" questions report those.

`answer` is the code route (code before models, CLAUDE.md ladder). `annotate` is a post-pass for distance answers
that came from the model reader instead: it shows the model-picked points and arithmetic, says plainly that they
were not independently measured, and adds a code check when the endpoints fall inside detected items.
Nothing here calls a model.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from engine.calc import input_value, record, step, step_source

MIN_CONF = 0.5
_STOP = r"(?:\s+(?:on|in|at|of)\s+(?:the\s+)?(?:(?:\w+\s+)?(?:floor|level|storey|story|plan|drawing|sheet|model|building)|[\w.]*\s*(?:kerros|obergeschoss|og|geschoss|keller|erdgeschoss|dachgeschoss))\b.*|\s+(?:in|into)\s+(?:metres|meters|m|feet|ft|mm)\b.*|\s+apart\b.*|\s+(?:centre|center)\s+to\s+(?:centre|center)\b.*|\s*\?.*|\s*\.$)"
_PAIR = [
    re.compile(r"\b(?P<w>distance|gap|clearance|spacing|separation|space)\s+(?:is\s+there\s+)?(?:between|from)\s+(?P<a>.+?)\s+(?:and|to)\s+(?P<b>.+)", re.I),
    re.compile(r"\bhow\s+far\s+apart\s+(?:is|are)\s+(?P<a>.+?)\s+and\s+(?P<b>.+)", re.I),
    re.compile(r"\bhow\s+far\s+(?:away\s+)?(?:is|are)\s+(?P<a>.+?)\s+(?:from|to)\s+(?P<b>.+)", re.I),
    re.compile(r"\bhow\s+far\s+(?:is\s+it\s+)?from\s+(?P<a>.+?)\s+to\s+(?P<b>.+)", re.I),
    re.compile(r"\bhow\s+(?:close|near)\s+(?:is|are)\s+(?P<a>.+?)\s+to\s+(?P<b>.+)", re.I),
    re.compile(r"\b(?:is|are)\s+(?P<a>.+?)\s+and\s+(?P<b>.+?)\s+(?P<w>apart)\b", re.I),
]
# Route lengths and heights are different questions; a straight line would understate a walking route.
_NOT = re.compile(r"\b(?:travel|walk\w*|escape|egress|evacuat\w*|route|path|along|via|through|fire|steps?\s+to|minutes?|"
                  r"floor\s+to\s+ceiling|ceiling|height|tall|within|less than|more than|at least|at most|compl\w*|regulat\w*|"
                  r"required|minimum|maximum|should|must)\b", re.I)
_VERT = re.compile(r"^(?:the\s+)?(?:floor|ceiling|roof|ground|storeys?|levels?|floors?)$", re.I)
_EDGE = re.compile(r"\b(?:gap|clearance|closest|nearest\s+(?:edge|wall|point)s?|edge\s+to\s+edge|wall\s+to\s+wall|space\s+between)\b", re.I)


def parse(question: str) -> dict | None:
    """{a, b, mode: 'centre'|'edge'} for a two-item distance question, else None."""
    q = re.sub(r"\s+", " ", str(question or "")).strip()
    if not q or _NOT.search(q):
        return None
    for pat in _PAIR:
        m = pat.search(q)
        if not m:
            continue
        a, b = (_clean(m.group("a")), _clean(m.group("b")))
        if not a or not b or a.lower() == b.lower() or _VERT.match(a) or _VERT.match(b):
            return None
        if re.search(r"\d+(?:[.,]\d+)?\s*(?:m|mm|cm|metres?|meters?|ft|feet)\b", f"{a} {b}", re.I):
            return None
        word = (m.groupdict().get("w") or "").lower()
        return {"a": a, "b": b, "mode": "edge" if word in ("gap", "clearance", "space") or _EDGE.search(q) else "centre"}
    return None


def _clean(s: str) -> str:
    s = re.sub(_STOP, "", s.strip(), flags=re.I)
    s = re.sub(r"^(?:the|a|an|this|that|our)\s+", "", s.strip(" ,'\"“”‘’"), flags=re.I)
    return s.strip(" ,'\"“”‘’")


# ------------------------------------------------------------------ resolving a phrase to items
_KINDS = {"door": "door", "doors": "door", "window": "window", "windows": "window", "toilet": "toilet", "toilets": "toilet",
          "sink": "sink", "sinks": "sink", "basin": "sink", "bathtub": "bathtub", "bath tub": "bathtub", "tub": "bathtub",
          "shower": "shower", "column": "column", "columns": "column", "stairs": "stairs", "stair": "stairs",
          "staircase": "stairs", "stairway": "stairs", "stairwell": "stairs"}


def _fold(s) -> str:
    from engine.solvers.filters import fold
    return fold(s)


def _name(it) -> str:
    lab = (it.props or {}).get("long_name") or it.label or ""
    if lab:
        return str(lab)
    rt = (it.props or {}).get("room_type")
    return str(rt or it.name or it.kind)


def display(it) -> str:
    """'kitchen', 'bathroom KPH', 'WC Damen (Erdgeschoss)', 'door Tür-019'."""
    lab = (it.props or {}).get("long_name") or it.label
    rt = (it.props or {}).get("room_type")
    if it.kind in ("room", "space"):
        base = f"{rt} {lab}" if lab and rt and _fold(rt) not in _fold(lab) and not it.source == "ifc" else (lab or rt or "room")
    else:
        base = f"{it.kind} {lab or it.name}" if (lab or it.name) else it.kind
    return f"{base} ({it.storey})" if it.storey else str(base)


def _geom_ok(it, ifc: bool) -> bool:
    return bool(it.bbox_m) if ifc else bool(it.bbox_px or (it.polygon_px and len(it.polygon_px) >= 3))


def resolve(doc, phrase: str, question: str = "") -> tuple[list, str]:
    """Items the phrase names and how they were matched; ([], reason) when nothing matches."""
    from engine.solvers.filters import ROOM_TYPES, _room_type, room_type_matches
    ifc = doc.mode == "ifc"
    pool = [i for i in doc.items if i.kind != "text" and (ifc or i.conf >= MIN_CONF) and _geom_ok(i, ifc)
            and not (i.props or {}).get("excluded_from_plan_counts")]
    p = _fold(phrase)
    paren = re.search(r"\(([^)]+)\)", phrase)
    for target in ([_fold(paren.group(1))] if paren else []) + [p]:
        exact = [i for i in pool if target and target in {_fold(v) for v in (i.label, (i.props or {}).get("long_name"), i.name) if v}]
        if exact:
            return exact, "label"
    p_room = re.sub(r"\s*\([^)]*\)", "", p).strip()
    from engine import entrance
    if entrance.is_entrance_phrase(phrase) or re.fullmatch(r"(?:main |front )?(?:entrance|entry door|front door)", p_room):
        doors = entrance.ifc_entrances(doc) if ifc else entrance.planmap_entrances(doc)
        doors = [d for d in doors if d in pool]
        if doors:
            return (doors[:1] if entrance.wants_single(phrase) or not re.search(r"doors\b", phrase, re.I) else doors), "entrance"
        return [], f"no door on the outer edge was found for '{phrase}'"
    base = _room_type(p_room) or _room_type(re.sub(r"s$", "", p_room)) or _room_type(re.sub(r"\s+room$", "", p_room))
    if base and base != "stairs":
        rooms = [i for i in pool if i.kind in ("room", "space") and room_type_matches(i, base)]
        if rooms:
            return rooms, f"room type {base}"
    kind = _KINDS.get(p_room) or _KINDS.get(re.sub(r"^(?:main|front|entrance|first|second)\s+", "", p_room))
    if kind:
        items = [i for i in pool if i.kind == kind or (kind == "stairs" and i.kind in ("stair", "stairs"))]
        if not items and kind == "stairs":
            items = [i for i in pool if i.kind in ("room", "space") and re.search(ROOM_TYPES["stairs"], _fold(_name(i)))]
        if items:
            return items, f"kind {kind}"
    if base:
        return [], f"no {base} in this {'model' if ifc else 'drawing'}"
    words = [w for w in p_room.split() if len(w) >= 2]
    if words:
        part = [i for i in pool if all(re.search(rf"\b{re.escape(w)}", _fold(_name(i))) for w in words)]
        if part:
            return part, "partial label"
    return [], f"nothing named '{phrase}' in this {'model' if ifc else 'drawing'}"


def _storey_filter(doc, question: str, items: list) -> list:
    if doc.mode != "ifc":
        return items
    from engine.complex_q import storeys_in
    names = [s.get("name") for s in doc.storeys if s.get("name")]
    want = set(storeys_in(question, names)) | {n for n in names if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", question, re.I)}
    keep = [i for i in items if i.storey in want] if want else items
    return keep or items


# ------------------------------------------------------------------ geometry
def _centroid(poly) -> tuple[float, float] | None:
    n = len(poly)
    a = cx = cy = 0.0
    for i in range(n):
        x0, y0 = float(poly[i][0]), float(poly[i][1])
        x1, y1 = float(poly[(i + 1) % n][0]), float(poly[(i + 1) % n][1])
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(a) < 1e-9:
        return None
    return cx / (3 * a), cy / (3 * a)


def centroid_xy(values, axis: int):
    """calc.evaluate hook: polygon area centroid from flattened x, y vertices (axis 0 = x, 1 = y)."""
    pts = list(zip(values[::2], values[1::2]))
    c = _centroid(pts) if len(pts) >= 3 else None
    return c[axis] if c else None


def _shape(it, ifc: bool):
    from shapely.geometry import Polygon, box
    if ifc:
        b = it.bbox_m
        return box(min(b[0][0], b[1][0]), min(b[0][2], b[1][2]), max(b[0][0], b[1][0]), max(b[0][2], b[1][2]))
    if it.polygon_px and len(it.polygon_px) >= 3:
        g = Polygon([(float(x), float(y)) for x, y in it.polygon_px])
        g = g if g.is_valid else g.buffer(0)
        if not g.is_empty and g.area > 0:
            return g
    b = it.bbox_px
    return box(*map(float, b))


def point(it, ifc: bool) -> dict:
    """Centre used for the item, with the operands that produce it."""
    if ifc:
        b = it.bbox_m
        return {"x": (b[0][0] + b[1][0]) / 2, "y": (b[0][2] + b[1][2]) / 2, "how": "bounding-box centre",
                "x_in": [b[0][0], b[1][0]], "y_in": [b[0][2], b[1][2]], "fields": ("bbox_m[0][0]", "bbox_m[1][0]", "bbox_m[0][2]", "bbox_m[1][2]")}
    if it.polygon_px and len(it.polygon_px) >= 3 and (c := _centroid(it.polygon_px)):
        return {"x": c[0], "y": c[1], "how": "outline centre", "poly": [[float(x), float(y)] for x, y in it.polygon_px]}
    b = it.bbox_px
    return {"x": (b[0] + b[2]) / 2, "y": (b[1] + b[3]) / 2, "how": "box centre (no outline)",
            "x_in": [b[0], b[2]], "y_in": [b[1], b[3]], "fields": ("bbox_px[0]", "bbox_px[2]", "bbox_px[1]", "bbox_px[3]")}


def _same_view(a, b) -> bool:
    if a.page != b.page:
        return False
    va, vb = (a.props or {}).get("view_id"), (b.props or {}).get("view_id")
    return not (va and vb and va != vb)


def _scale(doc, a, b) -> dict | None:
    """The physical scale both points share: the items' view scale, else the page scale. None when they disagree."""
    from engine.scales import positive
    sa, sb = ((a.props or {}).get("measurement_scale") or {}), ((b.props or {}).get("measurement_scale") or {})
    ma, mb = positive(sa.get("m_per_px")), positive(sb.get("m_per_px"))
    if ma and mb:
        return {**sa, "field": "props.measurement_scale.m_per_px", "region": (a.props or {}).get("scale_region")} if abs(ma / mb - 1) <= .01 else None
    page = ((doc.meta.get("page_scales") or {}).get(a.page) or (doc.scale if a.page == 1 else None) or {})
    return {**page, "field": "scale.m_per_px"} if positive(page.get("m_per_px")) else None


def measure(doc, A: list, B: list, question: str = "") -> dict | None:
    """Nearest pair between the two candidate sets, with centre and closest-edge distances. None without a usable pair."""
    ifc = doc.mode == "ifc"
    pairs = []
    for a in A:
        for b in B:
            if a is b or a.item_id == b.item_id or (not ifc and not _same_view(a, b)):
                continue
            pa, pb = point(a, ifc), point(b, ifc)
            d = math.hypot(pb["x"] - pa["x"], pb["y"] - pa["y"])
            same = (a.storey == b.storey) if ifc else True
            pairs.append((not same, d, a, b, pa, pb))
    if not pairs:
        return None
    pairs.sort(key=lambda t: (t[0], t[1]))
    _, d, a, b, pa, pb = pairs[0]
    scale = None
    if not ifc:
        scale = _scale(doc, a, b)
        if scale is None:
            return {"a": a, "b": b, "error": "the two items have no shared physical scale"}
    k = 1.0 if ifc else float(scale["m_per_px"])
    gap = None
    try:
        from shapely.ops import nearest_points
        ga, gb = _shape(a, ifc), _shape(b, ifc)
        g = ga.distance(gb)
        if g > 0:
            na, nb = nearest_points(ga, gb)
            gap = {"a": [na.x, na.y], "b": [nb.x, nb.y], "px": g, "m": g * k}
        else:
            gap = {"a": None, "b": None, "px": 0.0, "m": 0.0, "touch": True}
    except Exception:  # noqa: BLE001 — closest edges are a second figure, never required
        gap = None
    others = []
    for _, d2, a2, b2, _pa, _pb in pairs[1:]:
        others.append({"a": a2, "b": b2, "m": d2 * k})
    level = None
    if ifc and a.storey != b.storey:
        level = (min(b.bbox_m[0][1], b.bbox_m[1][1]) - min(a.bbox_m[0][1], a.bbox_m[1][1]))
    return {"a": a, "b": b, "pa": pa, "pb": pb, "px": d, "m": d * k, "scale": scale, "ifc": ifc, "gap": gap,
            "others": others, "n_a": len(A), "n_b": len(B), "level": level}


# ------------------------------------------------------------------ calculation record
def _src(doc, it, field, ifc):
    art = "elements.json" if ifc else f"planmap-{it.page}.json"
    ref = {"kind": "element", "doc_id": doc.meta.get("sheet_of") or doc.doc_id, "page": it.page, "artifact": art,
           "item_id": it.item_id, "bbox": it.bbox_px, "field": field, "origin": it.source or doc.mode}
    if not _in_artifact(doc, it, art):
        ev = (it.props or {}).get("evidence_items") or []
        ref.update(item_id=None, derived_item_id=it.item_id, derived_from=list(ev),
                   text=f"Box built at load time from {', '.join(ev) or 'source items'} (no outline in {art}).")
    return ref


_ART_IDS: dict = {}


def _in_artifact(doc, it, art) -> bool:
    from engine.answer import _root
    key = (doc.doc_id, art)
    if key not in _ART_IDS:
        import json
        try:
            data = json.loads((Path(_root()) / (doc.meta.get("sheet_of") or doc.doc_id) / art).read_text(encoding="utf-8"))
            _ART_IDS[key] = {x.get("item_id") for x in data.get("elements", data.get("items", [])) if isinstance(x, dict)}
        except (OSError, ValueError):
            _ART_IDS[key] = set()
    return it.item_id in _ART_IDS[key]


def _point_steps(doc, it, p, tag, ifc, unit):
    """Steps producing the point's x and y; returns (steps, x_step_id, y_step_id)."""
    out = []
    nm = display(it)
    if "poly" in p:
        verts = [input_value(f"vertex {i + 1} {ax}", v[j], "px", _src(doc, it, f"polygon_px[{i}][{j}]", ifc))
                 for i, v in enumerate(p["poly"]) for j, ax in enumerate(("x", "y"))]
        for axis, ax in ((0, "x"), (1, "y")):
            out.append(step(f"dist-{tag}-{ax}", f"Centre of {nm}: {ax}", f"area centroid {ax} = Σ(({ax}ᵢ + {ax}ᵢ₊₁)(xᵢyᵢ₊₁ − xᵢ₊₁yᵢ)) / (6 × signed area)",
                            p["x"] if axis == 0 else p["y"], "px", verts, "Area centroid of the recorded room outline (every vertex).",
                            f"centroid_{ax}"))
    else:
        fx0, fx1, fy0, fy1 = p["fields"]
        for ax, vals, fields in (("x", p["x_in"], (fx0, fx1)), ("y", p["y_in"], (fy0, fy1))):
            out.append(step(f"dist-{tag}-{ax}", f"Centre of {nm}: {ax}", f"({fields[0]} + {fields[1]}) / 2", p[ax], unit,
                            [input_value(f"{fields[0]}", float(vals[0]), unit, _src(doc, it, fields[0], ifc)),
                             input_value(f"{fields[1]}", float(vals[1]), unit, _src(doc, it, fields[1], ifc))],
                            p["how"].capitalize() + ("; model x/z plan axes (y is up)." if ifc else "."), "midpoint"))
    return out, f"dist-{tag}-x", f"dist-{tag}-y"


def calc_record(res: dict, doc, mres: dict, value: float, mode: str) -> dict:
    """The full arithmetic: two points, Δx, Δy, √(Δx² + Δy²), × scale, round. Closest edges as a secondary result."""
    ifc, a, b = mres["ifc"], mres["a"], mres["b"]
    unit = "m" if ifc else "px"
    steps = []
    sa, ax, ay = _point_steps(doc, a, mres["pa"], "a", ifc, unit)
    sb, bx, by = _point_steps(doc, b, mres["pb"], "b", ifc, unit)
    steps += sa + sb
    dx, dy = mres["pb"]["x"] - mres["pa"]["x"], mres["pb"]["y"] - mres["pa"]["y"]
    steps.append(step("dist-dx", "Δx between the two centres", "x(B) − x(A)", dx, unit,
                      [input_value("x of B", mres["pb"]["x"], unit, step_source(bx)), input_value("x of A", mres["pa"]["x"], unit, step_source(ax))],
                      operation="subtract"))
    steps.append(step("dist-dy", "Δy between the two centres" if not ifc else "Δz between the two centres (plan axis)", "y(B) − y(A)", dy, unit,
                      [input_value("y of B", mres["pb"]["y"], unit, step_source(by)), input_value("y of A", mres["pa"]["y"], unit, step_source(ay))],
                      operation="subtract"))
    steps.append(step("dist-px" if not ifc else "dist-m", "Straight-line distance" + (" in pixels" if not ifc else " in model metres"),
                      "√(Δx² + Δy²) = √((x₂−x₁)² + (y₂−y₁)²)", mres["px"], unit,
                      [input_value(f"point {n} {axn}", p[axn], unit, {**step_source(sid), "item_id": it.item_id})
                       for n, it, p, ids in ((1, a, mres["pa"], (ax, ay)), (2, b, mres["pb"], (bx, by)))
                       for axn, sid in zip(("x", "y"), ids)],
                      f"Plan (horizontal) distance between the two centres; Δx = {dx:.6g}, Δy = {dy:.6g} (steps dist-dx, dist-dy).", "polyline"))
    scale_ref = None
    if not ifc:
        sc = mres["scale"]
        scale_ref = {"kind": "scale", "doc_id": doc.meta.get("sheet_of") or doc.doc_id, "page": a.page, "artifact": f"planmap-{a.page}.json",
                     "field": sc.get("field") or "scale.m_per_px", "item_id": None, "method": sc.get("method"),
                     "confidence": sc.get("confidence"), "evidence": sc.get("evidence"), "region": sc.get("region")}
        steps.append(step("dist-m", "Convert pixels to metres", "pixel distance × metres per pixel", mres["m"], "m",
                          [input_value("pixel distance", mres["px"], "px", step_source("dist-px")),
                           input_value("metres per pixel", float(sc["m_per_px"]), "m/px", scale_ref)],
                          f"Scale method: {sc.get('method')}; confidence {sc.get('confidence')} (not an error bound).", "multiply"))
    main_sid = "dist-m"
    extras = []
    gap = mres.get("gap")
    if gap and gap.get("a"):
        ga, gb = gap["a"], gap["b"]
        def gsrc(it, p):
            fld = "polygon_px" if "poly" in p else ("bbox_m" if ifc else "bbox_px")
            return {**_src(doc, it, fld, ifc), "text": "Closest point on the recorded outline/box (shapely nearest_points)."}
        for tag, it, pt in (("ga", a, ga), ("gb", b, gb)):
            for j, axn in enumerate(("x", "y")):
                steps.append(step(f"dist-{tag}-{axn}", f"Closest point on {display(it)}: {axn}", "recorded outline geometry", pt[j], unit,
                                  [input_value(f"closest point {axn}", pt[j], unit, gsrc(it, mres["pa" if tag == "ga" else "pb"]))],
                                  "Closest pair of points between the two outlines.", "source"))
        steps.append(step("dist-gap-dx", "Δx between the closest points", "x(B) − x(A)", gb[0] - ga[0], unit,
                          [input_value("x of B", gb[0], unit, step_source("dist-gb-x")), input_value("x of A", ga[0], unit, step_source("dist-ga-x"))], operation="subtract"))
        steps.append(step("dist-gap-dy", "Δy between the closest points", "y(B) − y(A)", gb[1] - ga[1], unit,
                          [input_value("y of B", gb[1], unit, step_source("dist-gb-y")), input_value("y of A", ga[1], unit, step_source("dist-ga-y"))], operation="subtract"))
        gpx = math.hypot(gb[0] - ga[0], gb[1] - ga[1])
        steps.append(step("dist-gap-px" if not ifc else "dist-gap-m", "Closest-edge distance" + (" in pixels" if not ifc else ""), "√(Δx² + Δy²)", gpx, unit,
                          [input_value(f"closest point {n} {axn}", pt[j], unit, {**step_source(f"dist-{tag}-{axn}"), "item_id": it.item_id})
                           for n, tag, it, pt in ((1, "ga", a, ga), (2, "gb", b, gb)) for j, axn in enumerate(("x", "y"))],
                          "Δx, Δy in steps dist-gap-dx, dist-gap-dy.", operation="polyline"))
        if not ifc:
            steps.append(step("dist-gap-m", "Convert closest-edge pixels to metres", "pixel distance × metres per pixel", gpx * float(mres["scale"]["m_per_px"]), "m",
                              [input_value("pixel distance", gpx, "px", step_source("dist-gap-px")),
                               input_value("metres per pixel", float(mres["scale"]["m_per_px"]), "m/px", scale_ref)], operation="multiply"))
        if mode == "edge":
            main_sid = "dist-gap-m"
        else:
            g = round(gpx * (1.0 if ifc else float(mres["scale"]["m_per_px"])), 2)
            steps.append(step("dist-gap-result", "Round closest-edge distance", f"round(closest-edge distance, 2)", g, "m",
                              [input_value("closest-edge distance", steps[-1]["value"], "m", step_source("dist-gap-m")),
                               input_value("decimal places", 2, "decimal places", {"kind": "policy", "text": "Precision of the secondary figure"})], operation="round"))
            extras.append({"label": "Closest edges", "value": g, "unit": "m", "step_id": "dist-gap-result", "rounded_as": "2 decimal places"})
    if mode != "edge":
        main_sid = "dist-m"
    raw = next(s["value"] for s in steps if s["id"] == main_sid)
    from engine.calc import places
    steps.append(step("result", "Round for the answer", f"round({raw}, {places(value)})", value, "m",
                      [input_value("distance", raw, "m", step_source(main_sid)),
                       input_value("decimal places", places(value), "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})],
                      operation="round"))
    formula = ("distance = √(Δx² + Δy²) between bounding-box centres, in model metres" if ifc else
               "distance = √(Δx² + Δy²) px × metres per pixel, between the two centres")
    if mode == "edge":
        formula = "gap = √(Δx² + Δy²) between the closest points of the two outlines" + ("" if ifc else " × metres per pixel")
    calc = {"formula": formula, "steps": steps, "rows": [],
            "result": {"value": value, "unit": "m", "rounded_as": f"{places(value)} decimal places", **({"additional": extras} if extras else {})},
            "row_note": "Two points measured in code from the recorded geometry; no per-element sum.",
            "checks": [], "margin": {},
            "distance": {"items": [{"item_id": it.item_id, "name": display(it), "point": [round(p["x"], 3), round(p["y"], 3)], "how": p["how"],
                                    "unit": unit} for it, p in ((a, mres["pa"]), (b, mres["pb"]))],
                         "dx": dx, "dy": dy, "pixels": None if ifc else mres["px"], "m_per_px": None if ifc else float(mres["scale"]["m_per_px"]),
                         "scale_method": None if ifc else mres["scale"].get("method"), "metres": mres["m"],
                         "closest_edges_m": (gap or {}).get("m"), "mode": mode, "candidates": [mres["n_a"], mres["n_b"]]}}
    return calc


# ------------------------------------------------------------------ visible text
def _n(v, nd=1) -> str:
    return f"{v:,.{nd}f}"


def measured_text(mres: dict, mode: str = "centre") -> str:
    a, b, pa, pb = mres["a"], mres["b"], mres["pa"], mres["pb"]
    dx, dy = abs(pb["x"] - pa["x"]), abs(pb["y"] - pa["y"])
    if mres["ifc"]:
        return (f"Centre of {display(a)} ({_n(pa['x'], 2)}, {_n(pa['y'], 2)} m) to centre of {display(b)} ({_n(pb['x'], 2)}, {_n(pb['y'], 2)} m): "
                f"√({_n(dx, 2)}² + {_n(dy, 2)}²) = {_n(mres['m'], 2)} m (model metres, no scale)")
    k = float(mres["scale"]["m_per_px"])
    return (f"Centre of {display(a)} ({pa['x']:.0f}, {pa['y']:.0f} px) to centre of {display(b)} ({pb['x']:.0f}, {pb['y']:.0f} px): "
            f"√({dx:.0f}² + {dy:.0f}²) = {mres['px']:.1f} px × {k:.4f} m/px = {_n(mres['m'])} m")


def _gap_text(mres) -> str | None:
    g = mres.get("gap")
    if not g:
        return None
    if g.get("touch"):
        return f"The outlines of {display(mres['a'])} and {display(mres['b'])} touch or overlap (closest edges 0 m)."
    if mres["ifc"]:
        return f"Closest edges: {_n(g['m'], 2)} m (bounding boxes in model metres)."
    return f"Closest edges: {g['px']:.1f} px × {float(mres['scale']['m_per_px']):.4f} m/px = {_n(g['m'], 2)} m."


def _scale_note(mres) -> str | None:
    if mres["ifc"]:
        return None
    from engine.reasoning import _scale_words
    words, conf = _scale_words(mres["scale"])
    if conf < 0.5:
        return f"The scale comes from {words}, not a printed scale, so treat it as approximate."
    return f"Scale from {words}."


# ------------------------------------------------------------------ code route
def answer(question: str, doc_ids: list[str], root, t0) -> dict | None:
    """Code answer for a two-item distance question on one document, or None to leave it to other routes."""
    if len(doc_ids or []) != 1:
        return None
    pq = parse(question)
    if pq is None:
        return None
    from engine.solvers.data import load_doc
    doc = load_doc(doc_ids[0], Path(root))
    if doc is None or doc.mode not in ("planmap", "ifc"):
        return None
    A, why_a = resolve(doc, pq["a"], question)
    B, why_b = resolve(doc, pq["b"], question)
    from engine.solvers.solve import _answer_obj, _step
    trace = [_step("distance", f"two-item distance: '{pq['a']}' -> {len(A)} ({why_a}); '{pq['b']}' -> {len(B)} ({why_b})")]
    if not A or not B:
        missing = why_a if not A else why_b
        if missing.startswith("no ") and " in this " in missing:
            text = f"**I cannot measure that distance: there is {missing}.**"
            trace.append(_step("abstain", missing))
            return _answer_obj(question, doc_ids, text, None, None, 0.0, True, [], [],
                               {"doc_id": doc_ids[0], "highlight_item_ids": [], "camera_target_item_id": None}, trace,
                               "index" if doc.mode == "ifc" else "planmap", t0)
        return None   # an unknown name: the reader may still find it in the drawing text
    A, B = _storey_filter(doc, question, A), _storey_filter(doc, question, B)
    mres = measure(doc, A, B, question)
    if mres is None:
        return None
    if mres.get("error"):
        trace.append(_step("abstain", mres["error"]))
        text = f"**I cannot measure that distance reliably: {mres['error']}.**"
        return _answer_obj(question, doc_ids, text, None, None, 0.0, True, [], [],
                           {"doc_id": doc_ids[0], "highlight_item_ids": [], "camera_target_item_id": None}, trace,
                           "planmap", t0)
    return build(question, doc_ids, doc, mres, pq, trace, t0)


def _cite(doc, n, it):
    bb = [float(v) for v in it.bbox_px] if it.bbox_px else None
    q = f"{display(it)}" + (f" ({it.item_id})" if doc.mode != "ifc" else "")
    return {"n": n, "doc_id": doc.meta.get("sheet_of") or doc.doc_id, "page": it.page or 1, "kind": "element", "bbox_px": bb,
            "item_ids": [it.item_id], "quote": q}


def build(question, doc_ids, doc, mres, pq, trace, t0) -> dict:
    mode = pq["mode"]
    from engine.solvers.solve import _answer_obj, _step
    a, b = mres["a"], mres["b"]
    gap = mres.get("gap")
    edge = mode == "edge" and gap is not None
    raw = (gap["m"] if edge else mres["m"])
    value = round(raw, 2)
    na, nb = display(a), display(b)
    if edge:
        head = (f"**The {na} and the {nb} touch: their outlines meet (0 m apart).**" if gap.get("touch") else
                f"**The closest edges of the {na} and the {nb} are about {_n(raw)} m apart.**")
    else:
        head = f"**The {na} and the {nb} are about {_n(raw)} m apart, centre to centre.**"
    bullets = []
    if mres["ifc"]:
        bullets.append(f"Measured in code between the bounding-box centres of the two, in model metres (plan x/z).")
    else:
        bullets.append(f"Measured in code from the {mres['pa']['how']} of the {na} to the {mres['pb']['how']} of the {nb}.")
    if edge:
        bullets.append(f"Centre to centre they are {_n(mres['m'])} m apart.")
    elif gap is not None:
        bullets.append("Their outlines touch or overlap." if gap.get("touch") else f"Closest edges: {_n(gap['m'], 2)} m apart.")
    for n_c, phrase, chosen, alts in ((mres["n_a"], pq["a"], a, [o for o in mres["others"] if o["b"] is b and o["a"] is not a]),
                                      (mres["n_b"], pq["b"], b, [o for o in mres["others"] if o["a"] is a and o["b"] is not b])):
        if n_c > 1:
            alt_txt = "; ".join(f"{display(o['a'] if chosen is a else o['b'])} {_n(o['m'])} m" for o in alts[:3])
            bullets.append(f"{n_c} items match '{phrase}'; the nearest, {display(chosen)}, is used." + (f" Others: {alt_txt}." if alt_txt else ""))
    if mres.get("level"):
        bullets.append(f"They are on different storeys ({a.storey} and {b.storey}, {abs(mres['level']):.1f} m level difference); the figure is the plan distance.")
    if (note := _scale_note(mres)):
        bullets.append(note)
    text = head + "\n\n" + "\n".join(f"- {x}" for x in bullets) + " [1][2]"
    cites = [_cite(doc, 1, a), _cite(doc, 2, b)]
    boxes = [{"item_id": c["item_ids"][0], "page": c["page"], "bbox_px": c["bbox_px"], "label": str(c["n"]), "kind": it.kind}
             for c, it in zip(cites, (a, b)) if c["bbox_px"]]
    scene = {"doc_id": cites[0]["doc_id"], "highlight_item_ids": [a.item_id, b.item_id], "camera_target_item_id": a.item_id}
    trace.append(_step("measure", measured_text(mres) + (f"; {_gap_text(mres)}" if _gap_text(mres) else "")))
    conf = .9 if mres["ifc"] else min(.9, max(.3, float(mres["scale"].get("confidence") or .3)))
    res = _answer_obj(question, doc_ids, text, value, "m", conf, False, boxes, cites, scene, trace,
                      "index" if mres["ifc"] else "planmap", t0)
    record(res, calc_record(res, doc, mres, value, "edge" if edge else "centre"))
    res["reasoning_hint"] = {"steps": visible_steps(mres, edge)}
    return res


def visible_steps(mres, edge=False) -> list[dict]:
    a, b = mres["a"], mres["b"]
    many = [f"{n} {'matches' if n > 1 else 'match'} for {display(it)}" for n, it in ((mres["n_a"], a), (mres["n_b"], b)) if n > 1]
    found = f"{display(a).capitalize()} and {display(b)} in the {'building model (IFC)' if mres['ifc'] else 'plan map'}" + (
        f"; nearest pair of {', '.join(many)}" if many else "")
    out = [{"kind": "found", "title": "Found", "text": found, "cite": 1, "ok": None}]
    m = {"kind": "measured", "title": "Measured", "text": measured_text(mres), "cite": 1, "ok": None, "calc_step": "dist-m"}
    g = _gap_text(mres)
    if edge and g:
        out.append({"kind": "measured", "title": "Measured", "text": g, "cite": 1, "ok": None, "calc_step": "dist-gap-m"})
        m["title"] = "Centre to centre"
        out.append(m)
    else:
        out.append(m)
        if g:
            out.append({"kind": "measured", "title": "Closest edges", "text": g, "cite": 2, "ok": None, "calc_step": "dist-gap-m"})
    if (note := _scale_note(mres)):
        out.append({"kind": "checked", "title": "Scale", "text": note, "cite": None, "ok": None})
    return out


# ------------------------------------------------------------------ post-pass for model (reader) distance answers
def annotate(res: dict, question: str, root) -> dict:
    """Reader answers to distance questions: show the model's points and arithmetic, say that they were not
    independently measured, and add a code check of where the points fall. Never changes the answer value."""
    try:
        return _annotate(res, question, root)
    except Exception:  # noqa: BLE001 — an explanation must never break an answer
        return res


def _annotate(res, question, root):
    ans = res.get("answer") or {}
    if res.get("route") not in ("hybrid", "vlm") or ans.get("abstained") or parse(question) is None:
        return res
    rs = res.get("reasoning")
    if not isinstance(rs, dict):
        return res
    steps = rs.setdefault("steps", [])
    if any(s.get("kind") == "measured" and s.get("source") == "distance" for s in steps):
        return res
    calc = rs.get("calc") or {}
    reader = calc.get("reader") or {}
    meas = [c for c in reader.get("calculations") or [] if c.get("tool") == "measure" and len(c.get("points") or []) == 2 and not c.get("closed")]
    value = ans.get("value")
    chosen = None
    for c in reversed(meas):
        (x1, y1), (x2, y2) = c["points"]
        mm = math.hypot(x2 - x1, y2 - y1) * float(c["m_per_px"])
        if isinstance(value, (int, float)) and abs(mm - value) <= max(.051, abs(value) * .02):
            chosen = (c, mm)
            break
    if chosen is None:
        if isinstance(value, (int, float)):
            steps.insert(min(1, len(steps)), {"kind": "read", "title": "Model estimate", "source": "distance",
                                              "text": f"The model gave {_n(value)} m without measuring between points on the drawing; it was not independently measured.",
                                              "cite": None, "ok": False})
            calc.setdefault("unavailable", []).append("Distance: no measured points were recorded for the model's figure.")
        return res
    c, mm = chosen
    (x1, y1), (x2, y2) = c["points"]
    dx, dy, px = x2 - x1, y2 - y1, math.hypot(x2 - x1, y2 - y1)
    text = (f"Model-picked points ({x1:.0f}, {y1:.0f} px) and ({x2:.0f}, {y2:.0f} px): √({abs(dx):.0f}² + {abs(dy):.0f}²) = {px:.1f} px × "
            f"{float(c['m_per_px']):.4f} m/px = {_n(mm)} m. The model chose these points; they are not tied to detected outlines, so this was not independently measured.")
    check = _point_check(res, root, c)
    calc["distance"] = {"source": "model points", "points_px": c["points"], "dx": dx, "dy": dy, "pixels": px,
                        "m_per_px": c["m_per_px"], "scale_origin": c.get("scale_origin"), "metres": mm, "code_check": check}
    new = [{"kind": "measured", "title": "Measured", "text": text, "cite": None, "ok": None, "source": "distance"}]
    if check and check.get("text"):
        new.append({"kind": "checked", "title": "Code check", "text": check["text"], "cite": None, "ok": check.get("ok"), "source": "distance"})
        if check.get("metres") is not None:
            calc.setdefault("checks", []).append({"method": "room centres from the plan map (code)", "value": round(check["metres"], 2),
                                                  "reported_value": value, "agrees": check.get("ok"),
                                                  "diff_pct": abs(check["metres"] - value) / abs(check["metres"]) * 100 if check["metres"] else None,
                                                  "source": {"kind": "element", "doc_id": c["doc_id"], "page": c["page"],
                                                             "artifact": f"planmap-{c['page']}.json", "field": "polygon_px / bbox_px"}})
    if any(str(s.get("id") or "") in ("why-source", "why-calc") for s in steps):
        new = new[1:]   # WHY-CORE already shows the model points and arithmetic; add only the code check
        pos = next((i for i, s in enumerate(steps) if s.get("id") == "why-sure"), len(steps))
    else:
        pos = next((i + 1 for i, s in enumerate(steps) if s.get("kind") == "found"), 0)
    steps[pos:pos] = new
    return res


def _point_check(res, root, c) -> dict | None:
    """Which detected items each model point falls in, and the code distance between their centres."""
    from shapely.geometry import Point
    from engine.solvers.data import load_doc
    doc = load_doc(c["doc_id"], Path(root))
    if doc is None or doc.mode != "planmap":
        return None
    rooms = [i for i in doc.items if i.kind == "room" and i.page == c["page"] and i.conf >= MIN_CONF and _geom_ok(i, False)]
    hits = []
    for x, y in c["points"]:
        inside = [r for r in rooms if _shape(r, False).covers(Point(float(x), float(y)))]
        inside.sort(key=lambda r: _shape(r, False).area)
        hits.append(inside[0] if inside else None)
    names = [display(h) if h else "no detected room" for h in hits]
    out = {"in": [h.item_id if h else None for h in hits], "text": f"Point 1 lies in {names[0]}; point 2 lies in {names[1]}."}
    if all(hits) and hits[0] is not hits[1]:
        m = measure(doc, [hits[0]], [hits[1]])
        if m and not m.get("error"):
            out["metres"] = m["m"]
            v = (res.get("answer") or {}).get("value")
            out["ok"] = bool(isinstance(v, (int, float)) and abs(m["m"] - v) <= max(.2, .1 * m["m"]))
            out["text"] += f" Their centres are {_n(m['m'])} m apart in code ({measured_text(m)})" + ("." if out["ok"] else "; this disagrees with the model's figure.")
    return out
