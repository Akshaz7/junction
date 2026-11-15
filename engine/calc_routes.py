"""Small route hooks: retain the operands before numeric solvers discard them."""
from __future__ import annotations

from dataclasses import asdict

from engine.calc import (Row, assumption_source, input_value, number, record, row,
                         source, step, step_source, summed, transform, unit_name)


def allowance(res, rows, pct, ref, *, paint=False):
    calc = summed(res, rows, "m2", "net floor area = Σ(selected room areas)")
    total = next(s["value"] for s in calc["steps"] if s["id"] == "sum")
    if paint:
        calc["steps"] = [s for s in calc["steps"] if s["id"] != "result"]
        calc["steps"].append(step("coats", "Apply coats", "net ceiling area × coats", total * 2, "m2",
                                  [input_value("net area", total, "m2", step_source("sum")),
                                   input_value("coats", 2, "count", assumption_source("Assumed two coats; not stated in the file"))], operation="multiply"))
        return transform(res, calc, "Paint required", "divide",
                         [input_value("coated area", total * 2, "m2", step_source("coats")),
                          input_value("coverage", 10, "m2/litre", assumption_source("Assumed coverage 10 m2/litre; check the product data sheet"))],
                         "coated ceiling area / coverage", unit="litre")
    calc["steps"] = [s for s in calc["steps"] if s["id"] != "result"]
    calc["steps"].append(step("waste-fraction", "Convert percent to fraction", f"{pct} / 100", pct / 100, "fraction",
                              [input_value("waste allowance", pct, "%", ref),
                               input_value("percent divisor", 100, "%/fraction", {"kind": "conversion", "text": "100 percent = 1"})], operation="divide"))
    calc["steps"].append(step("waste-factor", "Include net quantity", f"1 + {pct / 100}", 1 + pct / 100, "factor",
                              [input_value("net quantity factor", 1, "factor", {"kind": "policy", "text": "Include 100% of the net quantity"}),
                               input_value("waste fraction", pct / 100, "fraction", step_source("waste-fraction"))], operation="sum"))
    return transform(res, calc, "Order quantity", "multiply",
                     [input_value("net area", total, "m2", step_source("sum")),
                      input_value("waste factor", 1 + pct / 100, "factor", step_source("waste-factor"))], "net area × (1 + waste fraction)")


def grouped(res, doc, items, labels, group_name):
    seen, rows = set(), []
    for it in items:
        label = labels[it.item_id]
        first = label not in seen
        seen.add(label)
        rows.append(row(doc, it, int(first), "count", group=label))
    return record(res, summed(res, rows, formula=f"{group_name} count = number of distinct {group_name} values",
                               note=f"First item in each {group_name} group contributes 1; remaining items in the same group contribute 0."))


def storeys(res, doc, declared=None, detected=None):
    rows = []
    if declared is not None:
        for index, s in enumerate(declared):
            for member, (source_index, raw) in enumerate(zip(s.get("source_indices", [index]), s.get("source_storeys", [s]))):
                ref = {**source(doc), "field": f"storeys[{source_index}]"}
                rows.append(asdict(Row(f"storey-{source_index}", raw["name"],
                                      {"count": int(member == 0), "elevation_m": raw.get("elevation_m"), "canonical_name": s["name"]}, ref)))
        formula = "storey count = Σ(1 per distinct name and elevation; duplicate declarations contribute 0)"
    else:
        for pg, result in enumerate(detected, 1):
            ref = {**source(doc), "artifact": f"planmap-{pg}.json", "page": pg, "field": "items"}
            rows.append(asdict(Row(f"page-{pg}", f"Floor plans on page {pg}", {"count": result["n"]}, ref)))
        formula = "floor count = Σ(floor plans detected on each page)"
    return record(res, summed(res, rows, formula=formula))


def baseboard(res, doc, results, openings, scale):
    rows, steps = [], []
    for idx, (it, perimeter, deducted, n, net) in enumerate(results):
        ref = source(doc, it, "bbox_m" if doc.mode == "ifc" else "bbox_px")
        box = it.bbox_m if doc.mode == "ifc" else it.bbox_px
        dx = box[1][0] - box[0][0] if doc.mode == "ifc" else box[2] - box[0]
        dy = box[1][2] - box[0][2] if doc.mode == "ifc" else box[3] - box[1]
        u = "m" if doc.mode == "ifc" else "px"
        k = 1 if doc.mode == "ifc" else scale
        sid = f"room-{idx}"
        steps.append(step(sid + "-sides", "Room rectangle sides", "width + depth", dx + dy, u,
                          [input_value("rectangle width", dx, u, ref), input_value("rectangle depth", dy, u, ref)], operation="sum"))
        factors = [input_value("sum of sides", dx + dy, u, step_source(sid + "-sides")),
                   input_value("two opposite sides", 2, "factor", {"kind": "policy", "text": "Rectangle perimeter is twice width plus depth"})]
        if doc.mode != "ifc":
            factors.append(input_value("scale", k, "m/px", {**ref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"}))
        steps.append(step(sid + "-perimeter", "Rectangle perimeter", "2 × (width + depth) × scale", perimeter, "m", factors,
                          "Rectangle approximation; other wall openings are not deducted.", "multiply"))
        door_inputs = []
        for door_index, (door, raw_width, capped_width) in enumerate(openings.get(it.item_id, [])):
            cap_id = sid + f"-door-{door_index}"
            width_ref = source(doc, door, "width_m / footprint")
            if doc.mode != "ifc" and door.bbox_px:
                px_width = max(door.bbox_px[2] - door.bbox_px[0], door.bbox_px[3] - door.bbox_px[1])
                steps.append(step(cap_id + "-width", "Scale drawn door width", "longest box side × page scale", raw_width, "m",
                                  [input_value("drawn width", px_width, "px", width_ref), input_value("scale", scale, "m/px", {**width_ref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"})], operation="multiply"))
                width_ref = step_source(cap_id + "-width")
            steps.append(step(cap_id, "Limit doorway deduction", "min(door width, maximum doorway deduction)", capped_width, "m",
                              [input_value("door width", raw_width, "m", width_ref), input_value("deduction cap", 3, "m", {"kind": "policy", "text": "Baseboard solver's maximum doorway deduction is 3 m"})], operation="min"))
            door_inputs.append(input_value("adjacent doorway deduction", capped_width, "m", step_source(cap_id)))
        steps.append(step(sid + "-openings", "Door widths deducted", "Σ(capped widths of adjacent doors)", deducted, "m",
                          door_inputs,
                          "Door association uses the solver's proximity band; each width is capped at 3 m as in the solver.", "sum"))
        steps.append(step(sid + "-difference", "Subtract openings", "perimeter − door openings", perimeter - deducted, "m",
                          [input_value("perimeter", perimeter, "m", step_source(sid + "-perimeter")),
                           input_value("openings", deducted, "m", step_source(sid + "-openings"))], operation="subtract"))
        steps.append(step(sid + "-net", "Non-negative baseboard", "max(0, perimeter − door openings)", net, "m",
                          [input_value("net outline", perimeter - deducted, "m", step_source(sid + "-difference"))], operation="max_zero"))
        r = row(doc, it, net, "m", perimeter_m=perimeter, openings_m=deducted, doors=n)
        r["source"] = step_source(sid + "-net")
        rows.append(r)
    return record(res, summed(res, rows, formula="baseboard = Σ(max(0, rectangle perimeter − adjacent door widths))", steps=steps))


def mep(res, doc, index, ids, groups=None, values=None):
    unit = unit_name(res["answer"].get("unit"))
    lookup = {i.item_id: i for i in doc.items}
    items = [lookup[i] for i in dict.fromkeys(ids) if i in lookup]
    if groups is not None:
        grouped(res, doc, items, groups, "recorded category")
        indexed_ids = {r["id"] for r in [*(index.get("services") or []), *(index.get("structure") or [])]}
        refs = [r["source"] for r in res["_calc"]["rows"]]
        refs.extend(i["source"] for s in res["_calc"]["steps"] for i in s["inputs"])
        for ref in refs:
            if ref.get("item_id") in indexed_ids:
                ref.update(artifact="mep.json", field="recorded type / size / material category")
        return res
    indexed = {r["id"]: r for r in index.get("services", [])}
    rows, steps = [], []
    for index, it in enumerate(items):
        r = indexed.get(it.item_id) or {}
        value = values.get(it.item_id) if values is not None else (r.get("L") if unit == "m" else 1)
        if isinstance(value, dict):
            component = value
            value = component["value"]
            ref = source(doc, it, "structure.v" if component.get("indexed") else "volume quantity")
            if component.get("indexed"): ref["artifact"] = "mep.json"
            sid = f"concrete-{index}"
            steps.append(step(sid, "Volume of selected material", "element volume × material fraction", value, "m3",
                              [input_value("element volume", component["volume"], "m3", ref),
                               input_value("material fraction", component["fraction"], "fraction", {**ref, "field": "structure.cf (concrete layer thickness / total layer thickness)"})],
                              "Layered elements contribute only the stored concrete thickness fraction; missing materials are excluded as stated.", "multiply"))
        else:
            sid = None
        rr = row(doc, it, value, unit)
        if sid: rr["source"] = step_source(sid)
        if unit == "m":
            rr["source"].update({"artifact": "mep.json", "field": "services.L"})
        rows.append(rr)
    return record(res, summed(res, rows, formula="total = Σ(selected element quantities)", steps=steps))


def tile_order(res, need, boxes, box_area, rate, cost):
    """Secondary quantities in the order headline use the exact solver inputs."""
    calc = res["_calc"]
    order_id = next(s["id"] for s in calc["steps"] if s["label"] == "Order quantity")
    assumed = assumption_source("Packaging and price assumed by the answer; not from the drawing or a supplier quote")
    calc["steps"].extend([
        step("boxes-fractional", "Boxes before rounding", "order area / area per box", need / box_area, "boxes",
             [input_value("order area", need, "m2", step_source(order_id)), input_value("area per box", box_area, "m2/box", assumed)], operation="divide"),
        step("boxes-whole", "Order whole boxes", "ceil(fractional boxes)", boxes, "boxes",
             [input_value("fractional boxes", need / box_area, "boxes", step_source("boxes-fractional"))], operation="ceil"),
        step("purchased-area", "Purchased area", "whole boxes × area per box", boxes * box_area, "m2",
             [input_value("whole boxes", boxes, "boxes", step_source("boxes-whole")), input_value("area per box", box_area, "m2/box", assumed)], operation="multiply"),
        step("order-price", "Assumed order price", "purchased area × assumed unit price", cost, "EUR",
             [input_value("purchased area", boxes * box_area, "m2", step_source("purchased-area")), input_value("assumed price", rate, "EUR/m2", assumed)], operation="multiply"),
    ])
    calc["result"]["additional"] = [{"label": "Whole boxes", "value": boxes, "unit": "boxes", "step_id": "boxes-whole", "rounded_as": "round up"},
                                        {"label": "Assumed price", "value": round(cost), "unit": "EUR", "step_id": "order-price", "rounded_as": "0 decimal places"}]


def combine(res, parts, operation, formula, *, multiplier=None, denominator=None, absolute=False):
    """Combine independent solver results, retaining each operand's full rows."""
    from engine.calc import _default, evaluate, places
    rows, steps, operands = [], [], []
    for idx, part in enumerate(parts):
        c = part.get("_calc")
        if not c:
            # Parts normally carry citations; attach at the caller when a root is needed.
            c = part.get("reasoning", {}).get("calc")
        if not c:
            raise ValueError("Calculation operand was not retained")
        prefix = f"part-{idx}-"
        for old in c["steps"]:
            import copy
            s = copy.deepcopy(old)
            s["id"] = prefix + s["id"]
            for inp in s["inputs"]:
                if inp["source"].get("kind") == "step": inp["source"]["step_id"] = prefix + inp["source"]["step_id"]
            steps.append(s)
        for old in c["rows"]:
            import copy
            r = copy.deepcopy(old)
            if r["source"].get("kind") == "step": r["source"]["step_id"] = prefix + r["source"]["step_id"]
            r["values"]["operand"] = idx
            rows.append(r)
        operands.append(input_value(part["question"], part["answer"]["value"], part["answer"]["unit"], step_source(prefix + "result")))
    if denominator is not None: operands.append(denominator)
    raw = evaluate(operation, [i["value"] for i in operands])
    steps.append(step("combined", "Combine independent quantities", formula, raw, res["answer"].get("unit"), operands, operation=operation))
    if multiplier is not None:
        steps.append(step("multiplied", "Express as percent", "ratio × 100", raw * multiplier["value"], "%",
                          [input_value("ratio", raw, "ratio", step_source("combined")), multiplier], operation="multiply"))
        raw *= multiplier["value"]
    sid = "multiplied" if multiplier is not None else "combined"
    value = res["answer"]["value"]
    steps.append(step("result", "Round for the answer", f"round({raw}, {places(value)})", value, res["answer"].get("unit"),
                      [input_value("combined result", raw, res["answer"].get("unit"), step_source(sid)),
                       input_value("decimal places", places(value), "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})], operation="round"))
    return record(res, {"formula": formula, "steps": steps, "rows": rows, "result": {"value": value, "unit": unit_name(res["answer"].get("unit")), "rounded_as": f"{places(value)} decimal places"},
                        "checks": [], "margin": {}, "row_note": "Rows are partitioned by operand; a source can legitimately appear in numerator and denominator. Each operand is summed before combination."})


def chain(res, doc, pairs, base_unit, operations):
    """Sequential arithmetic captured directly where a complex route uses it.

    operations: [(label, operation, extra_inputs, output_unit)]. Each operation
    takes the previous result followed by those explicit extra inputs.
    """
    from engine.calc import evaluate, places
    rows = [row(doc, i, v, base_unit) for i, v in pairs]
    c = summed(res, rows, base_unit)
    c["steps"] = [s for s in c["steps"] if s["id"] != "result"]
    prev, raw, unit = "sum", next(s["value"] for s in c["steps"] if s["id"] == "sum"), base_unit
    extras = []
    for index, (label, op, extra, new_unit) in enumerate(operations):
        normalized = []
        for input_index, inp in enumerate(extra):
            inp = dict(inp)
            if "percent_input" in inp:
                pct = inp.pop("percent_input")
                sid = f"chain-{index}-percent-{input_index}"
                c["steps"].append(step(sid, "Convert percentage", "percentage / 100", pct / 100, "fraction",
                                       [input_value("stated percentage", pct, "%", inp["source"]),
                                        input_value("percent divisor", 100, "%/fraction", {"kind": "conversion", "text": "100 percent = 1"})], operation="divide"))
                c["steps"].append(step(sid + "-factor", "Include base quantity", "1 + percentage fraction", 1 + pct / 100, "factor",
                                       [input_value("base quantity factor", 1, "factor", {"kind": "policy", "text": "Include the base quantity"}),
                                        input_value("percentage fraction", pct / 100, "fraction", step_source(sid))], operation="sum"))
                inp["source"] = step_source(sid + "-factor")
            normalized.append(inp)
        extra = normalized
        args = [input_value("previous quantity", raw, unit, step_source(prev)), *extra]
        raw = evaluate(op, [i["value"] for i in args])
        prev, unit = f"chain-{index}", new_unit
        c["steps"].append(step(prev, label, label, raw, unit, args, operation=op))
        extras.append({"label": label, "value": raw, "unit": unit, "step_id": prev})
    value = res["answer"]["value"]
    c["steps"].append(step("result", "Round for the answer", f"round({raw}, {places(value)})", value, unit,
                           [input_value("unrounded quantity", raw, unit, step_source(prev)),
                            input_value("decimal places", places(value), "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})], operation="round"))
    c["formula"] += "; " + "; ".join(o[0] for o in operations)
    c["result"] = {"value": value, "unit": unit, "rounded_as": f"{places(value)} decimal places", "additional": extras}
    return record(res, c)


def percentage_factor(name, pct, ref):
    return {**input_value(name, 1 + pct / 100, "factor", ref), "percent_input": pct}


def difference_groups(res, doc, items, a, b, area=False, by="storey"):
    from engine.calc import record_items
    from engine.solvers.solve import _qty
    parts = []
    for name in (a, b):
        its = [i for i in items if getattr(i, by) == name]
        vals = [(i, _qty(i, i.kind, "area") if area else 1) for i in its]
        unit = "m2" if area else "count"
        val = round(sum(v for i, v in vals if v is not None), 2) if area else len(its)
        part = {"question": name, "answer": {"value": val, "unit": unit}}
        record_items(part, doc, [(i, v) for i, v in vals if v is not None])
        parts.append(part)
    return combine(res, parts, "abs_difference", "difference = |first source subtotal − second source subtotal|")


def individual(res, doc, items, columns):
    """Several source quantities, intentionally no scalar total in the answer."""
    steps, rows, results = [], [], []
    for idx, it in enumerate(items):
        values = {}
        for key, (unit, getter) in columns.items():
            value = getter(it)
            values[key] = value
            if number(value):
                sid = f"item-{idx}-{key}"
                ref = source(doc, it, key)
                steps.append(step(sid, f"{it.label or it.name or it.kind}: {key}", "source quantity", value, unit,
                                  [input_value(key, value, unit, ref)], operation="source"))
                results.append({"label": f"{it.label or it.name or it.kind}: {key}", "value": value, "unit": unit, "step_id": sid})
        rows.append(asdict(Row(it.item_id, it.label or it.name or it.kind, values, source(doc, it))))
    ref = source(doc, field="items" if doc.mode != "ifc" else "elements")
    steps.append(step("selected-items", "Number of selected items", "count selected source items", len(items), "count",
                      [input_value("selected source items", len(items), "count", ref)], operation="source"))
    results.append({"label": "Selected items", "value": len(items), "unit": "count", "step_id": "selected-items"})
    return record(res, {"formula": "Read each source quantity separately; no combined total is claimed", "steps": steps, "rows": rows,
                        "result": {"value": res["answer"].get("value"), "unit": unit_name(res["answer"].get("unit")), "rounded_as": "individual source quantities", "mode": "per-element", "additional": results},
                        "checks": [], "margin": {}})


def append_calculation(calc, child, prefix, *, neutralize_count=True, include_rows=True):
    """Include a sub-report without colliding step ids or dropping source rows."""
    import copy
    for old in child["steps"]:
        s = copy.deepcopy(old)
        s["id"] = prefix + s["id"]
        for i in s["inputs"]:
            if i["source"].get("kind") == "step": i["source"]["step_id"] = prefix + i["source"]["step_id"]
        calc["steps"].append(s)
    for old in child["rows"] if include_rows else []:
        r = copy.deepcopy(old)
        if r["source"].get("kind") == "step": r["source"]["step_id"] = prefix + r["source"]["step_id"]
        if neutralize_count: r["values"]["count"] = 0
        r["values"]["section"] = prefix.rstrip("-")
        calc["rows"].append(r)
    if number(child.get("result", {}).get("value")):
        calc["result"].setdefault("additional", []).append({"label": prefix.rstrip("-"), "value": child["result"]["value"],
                                                             "unit": child["result"]["unit"], "step_id": prefix + "result",
                                                             "rounded_as": child["result"].get("rounded_as", "as reported")})


def quantity_table(res, doc, room_results, doors, windows, baseboard_result, slab_result, piping):
    rows = []
    for result in room_results:
        r = row(doc, result["r"], 1, "count", area_m2=result["area"], length_m=result["bb"],
                area_method="bounding rectangle" if result["approx"] else "source quantity", section="rooms")
        rows.append(r)
    calc = summed(res, rows, "rooms", "room count = Σ(1 per room); other quantities have separate units and totals")
    calc["result"]["additional"] = []
    # Include full derivations before adding the per-room schedule values.
    for prefix, report in (("baseboard-", baseboard_result), ("slabs-", slab_result)):
        if report and report.get("_calc"):
            append_calculation(calc, report["_calc"], prefix)
    for idx, result in enumerate(room_results):
        if not number(result["area"]): continue
        it = result["r"]
        ref = source(doc, it, "bbox_m (bounding rectangle)" if result["approx"] else "room area quantity")
        sid = f"room-area-{idx}"
        calc["steps"].append(step(sid, "Room floor area", "source room area" if not result["approx"] else "bounding rectangle area", result["area"], "m2",
                                  [input_value("floor area", result["area"], "m2", ref)],
                                  "Rectangle approximation, as stated in the answer" if result["approx"] else "", "source"))
        calc["result"]["additional"].append({"label": it.label or it.name or "Room floor area", "value": result["area"], "unit": "m2", "step_id": sid})
    for label, items in (("doors", doors), ("windows", windows)):
        sid = f"schedule-{label}"
        extra = [row(doc, it, 0, "count", **{label + "_count": 1}, section=label) for it in items]
        calc["rows"].extend(extra)
        calc["steps"].append(step(sid, f"Count {label}", "Σ(1 per selected item)", len(items), "count",
                                  [input_value(it.label or it.name or label, 1, "count", source(doc, it)) for it in items], operation="sum"))
        calc["result"]["additional"].append({"label": label, "value": len(items), "unit": "count", "step_id": sid})
    if piping:
        for index, (name, group) in enumerate((piping.get("rollups", {}).get("by_system") or {}).items()):
            val = group.get("length_m")
            if not number(val): continue
            ref = {**source(doc), "artifact": "piping.json", "field": f"rollups.by_system.{name}.length_m"}
            sid = f"piping-system-{index}"
            calc["steps"].append(step(sid, f"Pipe length: {name}", "stored system length", val, "m", [input_value("system length", val, "m", ref)], operation="source"))
            calc["result"]["additional"].append({"label": name, "value": val, "unit": "m", "step_id": sid})
    return record(res, calc)


def storey_schedule(res, doc, names):
    from engine.calc import record_items
    from engine.solvers.solve import _qty
    calc = {"formula": "Each floor and quantity is totalled separately; units are not mixed", "steps": [], "rows": [],
            "result": {"value": None, "unit": "", "mode": "per-element", "rounded_as": "per quantity", "additional": []},
            "checks": [], "margin": {}, "row_note": "Rows are partitioned by floor and quantity section; room counts and floor areas use separate totals."}
    for index, name in enumerate(names):
        for key, kind, unit in (("rooms", "room", "count"), ("doors", "door", "count"), ("windows", "window", "count"), ("area", "room", "m2")):
            its = [i for i in doc.items if i.kind == kind and i.storey == name]
            pairs = [(i, 1 if unit == "count" else _qty(i, "room", "area")) for i in its]
            pairs = [(i, v) for i, v in pairs if number(v)]
            total = sum(v for i, v in pairs)
            part = {"answer": {"value": total if unit == "count" else round(total, 1), "unit": unit}}
            record_items(part, doc, pairs)
            append_calculation(calc, part["_calc"], f"floor-{index}-{key}-", neutralize_count=False)
            calc["result"]["additional"][-1]["label"] = f"{name}: {key}"
    return record(res, calc)


def ranked_storeys(res, doc, items, selected, scores, area=False):
    from engine.calc import record_items
    from engine.solvers.solve import _qty
    unit = "m2" if area else "count"
    vals = [(i, (_qty(i, i.kind, "area") or 0) if area else 1) for i in items]
    rows = [row(doc, it, v if it.storey == selected else 0, unit, source_quantity=v, storey=it.storey,
                excluded_reason="" if it.storey == selected else "Another floor; excluded from the selected floor subtotal") for it, v in vals]
    calc = summed(res, rows, unit, "selected floor subtotal = Σ(source quantities on the selected floor)",
                  note="Only the selected winning floor contributes to this subtotal. Tied floors are reported separately, not added together.")
    for idx, (name, value) in enumerate(scores.items()):
        part = {"answer": {"value": value, "unit": unit}}
        record_items(part, doc, [(i, v) for i, v in vals if i.storey == name])
        append_calculation(calc, part["_calc"], f"rank-{idx}-", include_rows=False)
        calc["result"]["additional"][-1]["label"] = name
    return record(res, calc)


def piping(res, doc, data, ids, groups=None):
    indexed = {r["item_id"]: r for r in [*(data.get("pipes") or []), *(data.get("drains") or [])]}
    rows, seen = [], set()
    unit = res["answer"]["unit"]
    for iid in dict.fromkeys(ids):
        r = indexed.get(iid)
        if r is None: continue
        value = r.get("length_m") if unit == "m" else 1
        if groups is not None:
            value = int(groups[iid] not in seen)
            seen.add(groups[iid])
        ref = {"kind": "measurement", "doc_id": doc.doc_id, "page": 1, "item_id": iid, "field": "piping extract",
               "record": r, "text": "Normalized piping-extract quantities retained with this answer; lengths are in metres"}
        rows.append(asdict(Row(iid, r.get("name") or r.get("type_name") or "Pipe", {"length_m" if unit == "m" else "count": value,
                                                                                   "group": groups[iid] if groups is not None else None}, ref)))
    return record(res, summed(res, rows, formula="sum normalized pipe lengths" if unit == "m" else "count distinct groups" if groups is not None else "count selected pipe/drain items",
                               note="For grouped counts, one representative contributes 1 per group and the remaining rows contribute 0." if groups is not None else ""))
