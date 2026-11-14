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
            ref = {**source(doc), "field": f"storeys[{index}]"}
            rows.append(asdict(Row(f"storey-{index}", s["name"], {"count": 1, "elevation_m": s.get("elevation_m")}, ref)))
        formula = "storey count = Σ(1 per declared storey)"
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
        steps.append(step(sid + "-openings", "Door widths deducted", "Σ(capped widths of adjacent doors)", deducted, "m",
                          [input_value("adjacent door width (capped)", w, "m", source(doc, d, "width_m / footprint")) for d, w in openings.get(it.item_id, [])],
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
        return grouped(res, doc, items, groups, "recorded category")
    indexed = {r["id"]: r for r in index.get("services", [])}
    rows = []
    for it in items:
        r = indexed.get(it.item_id) or {}
        value = values.get(it.item_id) if values is not None else (r.get("L") if unit == "m" else 1)
        rr = row(doc, it, value, unit)
        if unit == "m":
            rr["source"].update({"artifact": "mep.json", "field": "services.L"})
        rows.append(rr)
    return record(res, summed(res, rows, formula="total = Σ(selected element quantities)"))


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
