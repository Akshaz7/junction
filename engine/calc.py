"""Reproducible calculation records. No models, network access or artifact writes.

Routes can seed a calculation with the actual operands they used (``record``).
``attach`` fills ordinary sums/counts from cited items and finalizes the record
after recounts, unit conversions and the evidence card have finished.
Unreproducible answers retain an explicitly incomplete audit, never a balancing
term invented from the difference between the answer and its source quantities.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path


def number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def unit_name(unit):
    return (unit or "").replace("²", "2").replace("³", "3")


KEYS = {"count": "count", "rooms": "count", "m": "length_m", "m2": "area_m2", "m3": "volume_m3"}


@dataclass
class Input:
    name: str
    value: object
    unit: str
    source: dict


@dataclass
class Step:
    id: str
    label: str
    expr: str
    value: object
    unit: str
    inputs: list[dict] = field(default_factory=list)
    note: str = ""
    operation: str = "source"


@dataclass
class Row:
    item_id: str
    label: str
    values: dict
    source: dict


def input_value(name, value, unit, source):
    if source.get("origin") in ("det", "seg", "vlm", "vision"):
        name = "Model output: " + name
    return asdict(Input(name, value, unit_name(unit), source))


def step(id, label, expr, value, unit, inputs=(), note="", operation="source"):
    return asdict(Step(id, label, expr, value, unit_name(unit), list(inputs), note, operation))


def source(doc, item=None, field=""):
    return {"doc_id": doc.meta.get("sheet_of") or doc.doc_id, "page": item.page if item else 1,
            "item_id": item.item_id if item else None, "bbox": item.bbox_px if item else None,
            "artifact": "elements.json" if doc.mode == "ifc" else f"planmap-{item.page if item else 1}.json",
            "field": field, "kind": "element" if item else "document", "origin": item.source if item else doc.mode}


def question_source(question):
    return {"kind": "question", "text": question}


def assumption_source(note):
    return {"kind": "assumption", "text": note}


def step_source(id):
    return {"kind": "step", "step_id": id}


def row(doc, item, value, unit, **values):
    return asdict(Row(item.item_id, item.label or item.name or item.kind,
                     {KEYS.get(unit_name(unit), unit_name(unit)): value, **values}, source(doc, item)))


def polygon_area_step(id, polygon, source_ref):
    inputs = [input_value(f"vertex {i + 1} {axis}", point[j], "px", {**source_ref, "field": f"polygon_px[{i}][{j}]"})
              for i, point in enumerate(polygon) for j, axis in enumerate(("x", "y"))]
    value = evaluate("shoelace", [i["value"] for i in inputs])
    return step(id, "Polygon area by shoelace", "0.5 × abs(Σ(x[i] × y[i+1] − x[i+1] × y[i])); last vertex joins first",
                value, "px2", inputs, "Uses every recorded outline vertex; no bounding rectangle is substituted.", "shoelace")


def places(value):
    return max(0, -Decimal(str(value)).as_tuple().exponent)


def close(a, b, tolerance=1e-8):
    return number(a) and number(b) and abs(a - b) <= tolerance + 8 * max(math.ulp(float(a)), math.ulp(float(b)))


def summed(res, rows, unit=None, formula="total = Σ(source quantities)", steps=(), key=None, note=""):
    """Build a sum record, preserving the raw total and the route's rounding."""
    ans = res["answer"]
    unit = unit_name(unit or ans.get("unit"))
    key = key or KEYS.get(unit, unit)
    vals = [r["values"].get(key) for r in rows]
    good = all(number(v) for v in vals)
    total = math.fsum(vals) if good else None
    inputs = [input_value(r["label"], r["values"].get(key), unit, r["source"]) for r in rows]
    operations = list(steps) + [step("sum", "Add source quantities" if unit != "count" else "Count selected items",
                                         " + ".join(str(v) for v in vals) or "0 (no matching source items)", total, unit,
                                         inputs, note, "sum")]
    value = ans.get("value")
    if number(value) and total is not None:
        nd = places(value)
        operations.append(step("result", "Round for the answer", f"round({total}, {nd})", value, unit,
                               [input_value("unrounded total", total, unit, step_source("sum")),
                                input_value("decimal places", nd, "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})],
                               operation="round"))
    return {"formula": formula, "steps": operations, "rows": rows,
            "result": {"value": value, "unit": unit, "rounded_as": f"{places(value)} decimal places" if number(value) else "per category"},
            "checks": [], "margin": {}, "row_key": key, "row_total_step": "sum"}


def record(res, calc):
    """Private seed: do not prevent reasoning.attach from creating the card."""
    res["_calc"] = calc
    return res


def record_terms(res, terms, formula="total = Σ(source quantities)", *, unit=None, steps=()):
    """Hook for text/schedule readers without a structured ``Doc``.

    terms are {label, value, source, item_id?}; each source must identify its
    document, page and source artifact (for example text-2.json + a text field
    and bbox). The caller supplies actual parsed terms, never a headline-derived
    balancing value. Returns the answer with a private seed finalized by attach.
    """
    unit = unit_name(unit or res["answer"].get("unit"))
    rows = [asdict(Row(t.get("item_id") or f"source-term-{idx}", t["label"], {KEYS.get(unit, unit): t["value"]}, t["source"]))
            for idx, t in enumerate(terms)]
    return record(res, summed(res, rows, unit, formula, steps))


def record_items(res, doc, pairs, unit=None, formula="total = Σ(source quantities)", note=""):
    unit = unit_name(unit or res["answer"]["unit"])
    rows, steps, checks = [], [], []
    for idx, (item, value) in enumerate(pairs):
        r = row(doc, item, value, unit)
        r["values"]["kind"] = item.kind
        sref = r["source"]
        measured = False
        if unit == "m2" and not any(item.q.get(k) is not None for k in ("net_floor_area_m2", "area_m2", "net_area_m2", "gross_area_m2", "net_side_area_m2")):
            w, h = item.q.get("width_m"), item.q.get("height_m")
            if number(w) and number(h) and close(w * h, value):
                sid = f"measure-{idx}"
                steps.append(step(sid, "Opening area", "width × height", value, unit,
                                  [input_value("width", w, "m", {**sref, "field": "width_m"}), input_value("height", h, "m", {**sref, "field": "height_m"})], operation="multiply"))
                r["source"] = step_source(sid)
                measured = True
        if doc.mode == "planmap" and unit == "m2" and item.polygon_px:
            from engine.reasoning import _shoelace
            # Use the page's own scale. Refined quantities are checked against it.
            scale = ((doc.meta.get("page_scales") or {}).get(item.page) or doc.scale or {}).get("m_per_px")
            area_px = _shoelace(item.polygon_px)
            if number(scale) and close(area_px * scale * scale, value, .005):
                sid = f"measure-{idx}"
                steps.append(polygon_area_step(sid + "-shoelace", item.polygon_px, sref))
                area_px = steps[-1]["value"]
                steps.append(step(sid, "Scale room outline", "outline area in px² × scale × scale", area_px * scale * scale, unit,
                                  [input_value("outline area (shoelace)", area_px, "px2", step_source(sid + "-shoelace")),
                                   input_value("metres per pixel", scale, "m/px", {**sref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"}),
                                   input_value("metres per pixel", scale, "m/px", {**sref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"})],
                                  note="Stored area may already be rounded; the row retains that stored value.", operation="multiply"))
                measured = True
            printed = item.props.get("area_m2_label")
            geom = item.props.get("area_m2_geom")
            if number(printed) and number(geom):
                checks.append({"method": "printed label versus outline", "value": printed, "agrees": close(printed, geom, .005),
                               "diff_pct": abs(printed - geom) / abs(printed) * 100 if printed else None, "source": sref})
        if unit in ("m2", "m3") and not measured:
            from engine.solvers.solve import _qty, requested_area_key
            stored = _qty(item, "room" if item.kind == "space" else item.kind, "area" if unit == "m2" else "volume", res.get('question', ''))
            requested = requested_area_key(res.get('question', ''), item.kind)
            if unit == 'm2' and requested and close(item.q.get(requested), value):
                sref['field'] = 'quantities.' + requested
                if net_source := item.props.get('net_quantity_source'):
                    sref.update(kind='measurement', record=dict(net_source),
                                text='Typed IFC net quantity read from the source file and normalized using its own area units.')
            elif unit == 'm2' and item.source == 'ifc' and close((item.props.get('space_area') or {}).get('measured_m2'), value):
                sref.update(kind='measurement', field='space_area.measured_m2',
                            record=dict(item.props['space_area']),
                            text='IfcSpace floor footprint measured from its source geometry in square metres.')
            if not close(stored, value):
                sref.update({"artifact": "scene.glb", "kind": "geometry", "field": "mesh floor area" if unit == "m2" else "closed mesh volume"})
        rows.append(r)
    calc = summed(res, rows, unit, formula, steps, note=note)
    calc["checks"] = checks
    return record(res, calc)


def transform(res, calc, label, operation, operands, expr, value=None, unit=None, note=""):
    """Append a documented operation to a sum (waste, coverage, ratio, etc.)."""
    calc = copy.deepcopy(calc)
    # Drop the old final rounding step: the new operation uses the raw sum.
    calc["steps"] = [s for s in calc["steps"] if s["id"] != "result"]
    unit = unit_name(unit or res["answer"].get("unit"))
    value = res["answer"].get("value") if value is None else value
    sid = f"operation-{len(calc['steps']) + 1}"
    raw = evaluate(operation, [i["value"] for i in operands])
    calc["steps"].append(step(sid, label, expr, raw, unit, operands, note, operation))
    calc["steps"].append(step("result", "Round for the answer", f"round({raw}, {places(value)})", value, unit,
                               [input_value(label, raw, unit, step_source(sid)),
                                input_value("decimal places", places(value), "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})], operation="round"))
    calc["formula"] += "; " + label + " = " + expr
    calc["result"] = {"value": value, "unit": unit, "rounded_as": f"{places(value)} decimal places"}
    return record(res, calc)


def evaluate(operation, values):
    if operation == 'reader_compute':
        from engine.reader.tools import safe_eval
        return safe_eval(values[0]) if len(values) == 1 and isinstance(values[0], str) else None
    if not all(number(v) for v in values):
        return None
    if operation in ('polyline', 'polyline_closed', 'polygon_area'):
        if len(values) < 4 or len(values) % 2: return None
        from engine.reader.geom import polygon_area, polyline_length
        points = list(zip(values[::2], values[1::2]))
        return polygon_area(points) if operation == 'polygon_area' else polyline_length(points, operation == 'polyline_closed')
    if operation == "sum": return math.fsum(values)
    if operation == "median":
        from statistics import median
        return median(values) if values else None
    if operation == "component_area": return values[0] * (values[1] / values[2]) ** 2 if len(values) == 3 and values[2] else None
    if operation in ("door_scale", "door_scale_spread"):
        from statistics import median
        if len(values) < 3 or any(v <= 0 for v in values): return None
        scale = values[0] / median(values[1:])
        return scale if operation == "door_scale" else max(abs((values[0] / v) / scale - 1) for v in values[1:]) * 100
    if operation == "accuracy_pct": return round(values[0] / values[1] * 100) if len(values) == 2 and values[1] else None
    if operation == 'ratio_dpi': return values[0] * values[2] / (values[1] * (values[3] if len(values) == 4 else 1)) if len(values) in (3, 4) and values[1] and (len(values) == 3 or values[3]) else None
    if operation == 'ratio_sheet': return math.prod(values[:3]) / values[3] if len(values) == 4 and values[3] else None
    if operation == 'dimension_scale': return values[0] * values[1] / values[2] if len(values) == 3 and values[2] else None
    if operation == 'bar_scale': return (values[-3] - values[0]) * values[-1] / values[-2] if len(values) >= 4 and values[-2] else None
    if operation == 'inverse': return 1 / values[0] if len(values) == 1 and values[0] else None
    if operation == 'dxf_scale': return values[0] / abs(values[1]) if len(values) == 2 and values[1] else None
    if operation in ("multiply", "convert"): return math.prod(values)
    # DIST (engine/distance.py): two-point distances replay from the recorded points.
    if operation == "midpoint": return (values[0] + values[1]) / 2 if len(values) == 2 else None
    if operation in ("centroid_x", "centroid_y"):
        from engine.distance import centroid_xy
        return centroid_xy(values, 0 if operation == "centroid_x" else 1) if len(values) >= 6 and not len(values) % 2 else None
    if operation == "divide": return values[0] / values[1] if len(values) == 2 and values[1] else None
    if operation == "subtract": return values[0] - math.fsum(values[1:]) if values else None
    if operation == "abs_difference": return abs(values[0] - values[1]) if len(values) == 2 else None
    if operation == "round": return round(values[0], int(values[1])) if len(values) == 2 else None
    if operation == "order_ceil": return math.ceil(values[0] * values[1] - 1e-9) / values[1] if len(values) == 2 and values[1] else None
    if operation == "ceil": return math.ceil(values[0]) if len(values) == 1 else None
    if operation == "max_zero": return max(0, values[0]) if len(values) == 1 else None
    if operation == "min": return min(values) if values else None
    if operation == "max": return max(values) if values else None
    if operation == 'scale_sensitivity':
        return abs(values[0]) * ((1 + values[1]) ** values[2] - 1) if len(values) == 3 else None
    if operation == "abs": return abs(values[0]) if len(values) == 1 else None
    if operation == "median":
        from statistics import median
        return median(values) if values else None
    if operation in ("polygon_perimeter", "shoelace"):
        if len(values) < 6 or len(values) % 2: return None
        points = list(zip(values[::2], values[1::2]))
        edges = list(zip(points, points[1:] + points[:1]))
        return (math.fsum(math.dist(a, b) for a, b in edges) if operation == "polygon_perimeter" else
                abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in edges)) / 2)
    if operation == "source": return values[0] if len(values) == 1 else None
    return None


def converted_step(id, value, from_unit, to_unit, factor, source_ref):
    """Explicit conversion: callers supply the same factor used in their answer."""
    return step(id, f"Convert {from_unit} to {to_unit}", f"{value} {from_unit} × {factor} {to_unit}/{from_unit}",
                value * factor, to_unit,
                [input_value("source quantity", value, from_unit, source_ref),
                 input_value("conversion factor", factor, f"{to_unit}/{from_unit}",
                             {"kind": "conversion", "text": f"1 {from_unit} = {factor} {to_unit}"})], operation="convert")


def _json(path):
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _measurement_steps(calc, root):
    """Expose cached outline measurements using each page's recorded scale."""
    cache, extra = {}, []
    for index, r in enumerate(calc.get("rows", [])):
        ref = r.get("source") or {}
        artifact = ref.get("artifact") or ""
        value = r.get("values", {}).get("area_m2")
        if r.get("measured_by"):   # PLAN-WHY: the route already recorded this measurement
            continue
        if not number(value) or not artifact.startswith("planmap-") or not ref.get("item_id"):
            continue
        path = root / ref["doc_id"] / artifact
        if path not in cache:
            pm = _json(path)
            cache[path] = (pm, {i.get("item_id"): i for i in pm.get("items", [])})
        pm, items = cache[path]
        item = items.get(ref["item_id"]) or {}
        scale = (pm.get("scale") or {}).get("m_per_px")
        props = item.get("props") or {}
        poly = item.get("polygon_px")
        px = props.get("area_px")
        if not number(px) and poly:
            from engine.reasoning import _shoelace
            px = _shoelace(poly)
        if not number(px) or not number(scale): continue
        measured = px * scale * scale
        printed = props.get("area_m2_label")
        if number(printed):
            calc.setdefault("checks", []).append({"method": "printed room area versus outline", "value": printed,
                                                    "agrees": close(printed, measured, .005), "diff_pct": abs(printed - measured) / abs(printed) * 100 if printed else None,
                                                    "source": ref})
        if not close(measured, value, .005): continue
        sid = f"outline-{index}"
        area_ref = {**ref, "field": "props.area_px / polygon_px"}
        if poly:
            outline = polygon_area_step(sid + "-shoelace", poly, ref)
            if close(outline["value"], px):
                extra.append(outline)
                area_ref = step_source(outline["id"])
        extra.append(step(sid, "Outline area and scale", "outline area × metres per pixel × metres per pixel", measured, "m2",
                          [input_value("outline area (shoelace)", px, "px2", area_ref),
                           input_value("page scale", scale, "m/px", {**ref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"}),
                           input_value("page scale", scale, "m/px", {**ref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"})],
                          f"Page scale method: {(pm.get('scale') or {}).get('method')}; cached area may already be rounded. Scale confidence is not an error bound.", "multiply"))
    calc["steps"] = extra + calc["steps"]


def _cited(res, root):
    from engine.solvers.data import load_doc, load_sheet_parent
    docs, seen, result, missing = {}, set(), [], []
    for c in res.get("citations") or []:
        did = c.get("doc_id") or next(iter(res.get("doc_ids") or []), None)
        if did not in docs:
            try:
                docs[did] = load_doc(did, root) or load_sheet_parent(did, root) if did else None
                if docs[did] is not None and docs[did].mode == 'ifc':
                    from engine.ifc_accuracy import prepare_doc, wants_room_geometry
                    question = res.get('question', '')
                    docs[did] = prepare_doc(docs[did], root, geometry=wants_room_geometry(question), question=question)
            except (OSError, ValueError, KeyError, TypeError):
                docs[did] = None
        doc = docs[did]
        lookup = {(i.page, i.item_id): i for i in doc.items} if doc else {}
        fallback = {i.item_id: i for i in doc.items} if doc else {}
        for iid in c.get("item_ids") or []:
            identity = (did, None if doc and doc.mode == "ifc" else c.get("page", 1), iid)
            if identity in seen: continue
            seen.add(identity)
            it = lookup.get((c.get("page", 1), iid)) or fallback.get(iid)
            if it:
                result.append((doc, it))
            else:
                box = next((b for b in (res.get("evidence") or {}).get("boxes", []) if b.get("item_id") == iid and b.get("page", 1) == c.get("page", 1)), None)
                missing.append((c, iid, box))
    return result, missing


def _table_operands(res, value, root):
    """Integer table cells cited by a text/schedule answer whose sum is the answer; None unless they reproduce it exactly."""
    did0 = next(iter(res.get("doc_ids") or []), None)
    cells = []
    for c in res.get("citations") or []:
        quote = str(c.get("quote") or "").strip()
        did = c.get("doc_id") or did0
        if c.get("item_ids") or not did or not re.fullmatch(r"\d{1,6}", quote):
            continue
        page = c.get("page", 1)
        if not (Path(root) / did / f"text-{page}.json").is_file():
            continue
        src = {"kind": "document", "doc_id": did, "page": page, "artifact": f"text-{page}.json", "field": "text",
               "text": quote, "bbox": c.get("bbox_px")}
        cells.append(asdict(Row(f"cell-{len(cells) + 1}", f"Table cell {quote}", {"count": int(quote)}, src)))
    if len(cells) < 2 or sum(r["values"]["count"] for r in cells) != value:
        return None
    return cells


def _default(res, question, root):
    from engine.solvers.solve import _qty
    ans = res["answer"]
    unit, value = unit_name(ans.get("unit")) or "count", ans.get("value")
    items, missing = _cited(res, root)
    rows, issues = [], []
    if unit == "count" and not items and not missing and number(value):
        cells = _table_operands(res, value, root)
        if cells:   # F-TABLEOPS: "4 + 3 = 7" is built from the cited table cells, not an empty element list
            return summed(res, cells, "count", formula="total = Σ(quantity cells in the table)", note="Each operand is a cited table cell.") | {"issues": []}
    for doc, it in items:
        v = 1 if unit in ("count", "rooms") else _qty(it, "room" if it.kind == "space" else it.kind, {"m2": "area", "m": "length", "m3": "volume"}.get(unit, ""), question)
        r = row(doc, it, v, unit, kind=it.kind)
        # IFC parent sheets resolve through the parent artifact, never a guessed sheet index.
        if doc.meta.get("sheet_of"):
            r["source"]["doc_id"] = doc.meta["sheet_of"]
        if v is None: issues.append(f"No {unit} source quantity for {it.item_id}.")
        rows.append(r)
    for c, iid, box in missing:
        if box and unit == "count":
            rows.append(asdict(Row(iid, "Model-drawn item", {"count": 1, "kind": c.get("item_kind")},
                                  {"kind": "model", "doc_id": c.get("doc_id"), "page": box.get("page", 1), "item_id": iid,
                                   "bbox": box.get("bbox_px"), "field": "evidence.boxes", "text": "Model output, not independently verified"})))
        else:
            issues.append(f"Cited item {iid} could not be resolved.")
    if isinstance(value, dict):
        calc = {"formula": "count each category separately", "steps": [], "rows": rows,
                "result": {"value": value, "unit": unit, "rounded_as": "whole counts per category"}, "checks": [], "margin": {}}
        for kind, n in value.items():
            rs = [r for r in rows if r["values"].get("kind") == kind]
            calc["steps"].append(step(f"category-{kind}", f"Count {kind}", f"Σ({kind} items)", n, "count",
                                       [input_value(r["label"], 1, "count", r["source"]) for r in rs], operation="sum"))
    else:
        calc = summed(res, rows, unit, formula="count = Σ(1 per selected item)" if unit == "count" else "total = Σ(source quantities)")
        if not rows and value != 0:
            issues.append("No per-element operands were recorded for this numeric answer.")
        if not rows and value == 0:
            for did in res.get("doc_ids") or []:
                folder = root / did
                files = [folder / "elements.json"] if (folder / "elements.json").is_file() else sorted(folder.glob("planmap-[0-9]*.json"))
                for index, path in enumerate(files):
                    data = _json(path)
                    population = len(data.get("elements", data.get("items", [])))
                    ref = {"kind": "document", "doc_id": did, "page": data.get("page", 1), "artifact": path.name, "field": "elements" if "elements" in data else "items"}
                    calc["steps"].insert(0, step(f"scope-{did}-{index}", "Search scope", "source inventory before question filters", population, "count",
                                                 [input_value("source inventory", population, "count", ref)],
                                                 "Zero is the number of matches in this inventory, not proof that the building contains none.", "source"))
            if not any(s["id"].startswith("scope-") for s in calc["steps"]):
                issues.append("The inventory searched for this zero result is unavailable.")
    calc["issues"] = issues
    return calc


def validate(calc, root=None):
    """Return invariant failures; complete never means source completeness is known."""
    issues = list(calc.get("issues") or [])
    # Display order follows importance, not dependency order. Resolve references
    # by stable id and reject duplicate/cyclic graphs before replaying operands.
    known, artifact_cache = {}, {}
    for s in calc.get("steps", []):
        if s.get("id") in known:
            issues.append(f"{s['id']}: duplicate calculation step id.")
        known[s.get("id")] = s
    remaining = {sid: {i.get("source", {}).get("step_id") for i in s.get("inputs", [])
                       if i.get("source", {}).get("kind") == "step"}
                 for sid, s in known.items()}
    # Kahn's algorithm avoids recursion on large technical traces.
    from collections import defaultdict, deque
    dependents = defaultdict(set)
    for sid, deps in remaining.items():
        for dep in deps:
            dependents[dep].add(sid)
    ready = deque(sid for sid, deps in remaining.items() if not deps)
    resolved = set()
    while ready:
        sid = ready.popleft()
        resolved.add(sid)
        for child in dependents[sid]:
            remaining[child].discard(sid)
            if not remaining[child]:
                ready.append(child)
    if any(deps and all(dep in known for dep in deps) for sid, deps in remaining.items() if sid not in resolved):
        issues.append("Calculation step dependencies contain a cycle.")
    def check_source(ref, label):
        kind = ref.get("kind")
        if kind == "step":
            if ref.get("step_id") not in known: issues.append(f"{label}: source calculation step is missing.")
        elif kind in ("question", "assumption", "policy", "conversion"):
            if not ref.get("text"): issues.append(f"{label}: unlabelled {kind} input.")
        elif kind == "metadata":
            if not isinstance(ref.get("record"), dict) or ref["record"].get("doc_id") != ref.get("doc_id"):
                issues.append(f"{label}: catalogue snapshot is missing or inconsistent.")
        elif kind == "measurement":
            if not ref.get("doc_id") or not isinstance(ref.get("record"), dict) or not ref.get("text"):
                issues.append(f"{label}: measurement snapshot or provenance is missing.")
        elif kind in ("element", "document", "model", "scale", "geometry"):
            if not ref.get("doc_id"): issues.append(f"{label}: source document missing.")
            if root is not None and kind != "model":
                artifact = ref.get("artifact")
                p = Path(root) / str(ref.get("doc_id")) / str(artifact or "")
                if not artifact or not p.is_file():
                    issues.append(f"{label}: source artifact missing.")
                elif p.suffix == ".json" and ref.get("item_id"):
                    if p not in artifact_cache:
                        data = _json(p)
                        candidates = data.get("elements", data.get("items", []))
                        if "services" in data:
                            candidates = list(data.get("services") or []) + list(data.get("structure") or [])
                        if isinstance(candidates, list):
                            artifact_cache[p] = {x.get("item_id", x.get("id")) for x in candidates if isinstance(x, dict)}
                        else: artifact_cache[p] = set(candidates)
                    if ref["item_id"] not in artifact_cache[p]: issues.append(f"{label}: source item does not exist in its artifact.")
        else:
            issues.append(f"{label}: input source is not resolvable.")
    for s in calc.get("steps", []):
        for i in s.get("inputs", []):
            ref = i.get("source") or {}
            kind = ref.get("kind")
            if kind == "step":
                prev = known.get(ref.get("step_id"))
                if prev is None or not close(prev.get("value"), i.get("value")):
                    issues.append(f"{s['id']}: unresolved or mismatched calculation input {i.get('name')}.")
            check_source(ref, s["id"])
        actual = evaluate(s.get("operation"), [i.get("value") for i in s.get("inputs", [])])
        if not close(actual, s.get("value")):
            issues.append(f"{s['id']}: operands do not reproduce the recorded value.")
        known[s["id"]] = s
    for row in calc.get("rows", []):
        check_source(row.get("source") or {}, row.get("item_id") or "row")
    value = calc.get("result", {}).get("value")
    if isinstance(value, dict):
        for k, v in value.items():
            if not close((known.get(f"category-{k}") or {}).get("value"), v):
                issues.append(f"No matching result step for {k}.")
    elif value is None and calc.get("result", {}).get("mode") == "per-element":
        pass
    elif not close((known.get("result") or {}).get("value"), value):
        issues.append("Final calculation does not match the answer value.")
    for result in calc.get("result", {}).get("additional", []):
        s = known.get(result.get("step_id"))
        precision = result.get("rounded_as", "")
        tolerance = .5 * 10 ** -int(precision.split()[0]) if precision.split() and precision.split()[0].isdigit() else 1e-8
        if not s or not close(s["value"], result.get("value"), tolerance):
            issues.append(f"Secondary result {result.get('label')} does not match its calculation.")
    key, target = calc.get("row_key"), calc.get("row_total_step")
    if key and target:
        values = [r.get("values", {}).get(key) for r in calc.get("rows", [])]
        if not all(number(v) for v in values) or not close(math.fsum(v for v in values if number(v)), (known.get(target) or {}).get("value")):
            issues.append("Per-element rows do not reconcile with the recorded subtotal.")
    return list(dict.fromkeys(issues))


def _attach(res, question, root):
    ans = res.get("answer") or {}
    value = ans.get("value")
    if ans.get("abstained") or not (res.get("_calc") or number(value) or isinstance(value, dict) and value and all(number(v) for v in value.values())):
        res.pop("_calc", None)
        return res
    root = Path(root)
    if res.get("wallarea", {}).get("rows"):
        from engine.calc_wallarea import record_wallarea
        record_wallarea(res, question)
    calc = res.pop("_calc", None)
    if not calc or calc.get("result", {}).get("value") != value:
        from engine.ifc_why import dimension_calc   # IFC-WHY: width/height/length from the exact IFC field
        from engine.plan_measures import room_area_default   # PLAN-WHY: exact per-room pixel-area chain
        calc = dimension_calc(res, question, root) or room_area_default(res, question, root) or _default(res, question, root)
    if value is None and calc.get('rows'):
        # Sanity guards can intentionally withdraw a scalar after a route has
        # measured individual regions. Keep that arithmetic as context without
        # presenting the source sum as an answer the guard rejected.
        reason = next((t.get('detail') for t in res.get('trace', []) if t.get('step') == 'sanity'),
                      'The answer reports source rows without a scalar total.')
        calc['result'].update(mode='per-element', rounded_as='No scalar total reported', reason=reason)
        calc['row_note'] = 'These source measurements are context only. ' + reason
    _measurement_steps(calc, root)
    if number(value) and res.get("route") in ("hybrid", "vlm") and any(s.get("model") and s.get("step") not in ("explain", "context", "typos") for s in res.get("trace", [])):
        cited = (res.get("citations") or [{}])[0]
        calc["steps"].append(step("model-final", "Reported model output", "model-provided value (not independent arithmetic)", value, ans.get("unit"),
                                  [input_value("model-reported answer", value, ans.get("unit"), {"kind": "model", "doc_id": cited.get("doc_id") or next(iter(res.get("doc_ids") or []), None),
                                                                                           "page": cited.get("page", 1), "bbox": cited.get("bbox_px"), "field": "answer.value"})],
                                  "The source rows above show what can be checked independently; unresolved differences stay marked incomplete.", "source"))
    reasoning = res.setdefault("reasoning", {"steps": [], "confidence": {"label": "Estimate", "pct": None,
                                                                            "reason": "Calculation sources have not been independently verified."}})
    # The independent-check and scale builders run before final arithmetic.
    # Keep their provenance when the route's exact seed replaces their sum.
    prior = reasoning.get("calc") or {}
    for key in ("checks", "item_checks", "sanity_checks", "unavailable"):
        for entry in prior.get(key) or []:
            if entry not in calc.setdefault(key, []): calc[key].append(copy.deepcopy(entry))
    if prior.get("scale_proof"):
        calc["scale_proof"] = copy.deepcopy(prior["scale_proof"])
    calc["margin"] = copy.deepcopy(reasoning.get("margin") or {"value": None, "unit": unit_name(ans.get("unit")), "pct": None,
                                                                 "why": "No measured error budget was recorded.", "sources": []})
    extras = res.pop("_calc_extras", [])
    for extra in extras:
        calc["steps"].extend(extra["steps"])
        calc["result"].setdefault("additional", []).append(extra["result"])
    for idx, model in enumerate(res.pop("_calc_models", [])):
        ref = {"kind": "model", "doc_id": model.get("doc_id"), "page": model.get("page", 1),
               "text": model["label"], "field": "trace.recount"}
        calc["steps"].append(step(f"model-{idx}", model["label"], "recorded model output", model["value"], ans.get("unit"),
                                  [input_value(model["label"], model["value"], ans.get("unit"), ref)], model.get("policy", "") + f" Reported answer: {value}; model output: {model['value']}.", "source"))
        if number(value):
            calc["checks"].append({"method": model["label"], "value": model["value"], "reported_value": value,
                                    "agrees": close(model["value"], value), "diff_pct": abs(model["value"] - value) / abs(model["value"]) * 100 if model["value"] else None,
                                    "source": ref, "note": "Agreement is a cross-check, not proof that no items were missed."})
    # Keep the exact API value and the rounded quantity printed in the headline.
    if number(value):
        import re
        heads = re.findall(r"\*\*(.+?)\*\*", ans.get("text_md") or "")
        for index, token in enumerate(re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w.])", " ".join(heads))):
            token = token.replace(",", "")
            nd = len(token.partition(".")[2])
            shown = float(token)
            if close(round(value, nd), shown) and not close(value, shown):
                sid = f"display-result-{index}"
                calc["steps"].append(step(sid, "Round for display", f"round({value}, {nd})", shown, calc["result"]["unit"],
                                          [input_value("recorded result", value, calc["result"]["unit"], step_source("result")),
                                           input_value("display decimal places", nd, "decimal places", {"kind": "policy", "text": "Precision printed in the answer headline"})], operation="round"))
                calc["result"].setdefault("additional", []).append({"label": "Displayed answer", "value": shown, "unit": calc["result"]["unit"], "step_id": sid, "rounded_as": f"{nd} decimal places"})
                break
    from engine.ifc_why import add_measured_step, label_rows   # IFC-WHY: name the IFC field + "Measured" step
    label_rows(calc, root)
    issues = validate(calc, root)
    calc["issues"], calc["status"] = issues, "incomplete" if issues else "complete"
    reasoning["calc"] = calc
    add_measured_step(res, calc, root)
    return res


def attach(res, question, root):
    """Malformed/missing source data must never turn an answer into a crash."""
    try:
        res = _attach(res, question, root)
        from engine.method_trace import attach as attach_method
        return attach_method(res, question, root)
    except (ArithmeticError, ValueError, TypeError, KeyError, OSError) as exc:
        for key in ("_calc", "_calc_models", "_calc_extras"):
            res.pop(key, None)
        reasoning = res.setdefault("reasoning", {"steps": [], "confidence": {"label": "Estimate", "pct": None,
                                                                                "reason": "The calculation could not be reproduced from source data."}})
        reasoning["calc"] = {"formula": "Calculation unavailable", "steps": [], "rows": [], "checks": [],
                              "result": {"value": (res.get("answer") or {}).get("value"), "unit": unit_name((res.get("answer") or {}).get("unit")), "rounded_as": "as reported"},
                              "margin": reasoning.get("margin") or {"value": None, "unit": unit_name((res.get("answer") or {}).get("unit")), "pct": None,
                                                                      "why": "The source operands could not be resolved.", "sources": []},
                              "status": "incomplete", "issues": [f"Source calculation unavailable ({type(exc).__name__})."]}
        return res
