"""Calculation hook for F-WALLAREA's public ``res['wallarea']`` report.

Consumes its measurements without importing IFC/geometry libraries or copying
the wall-area worker's module. It becomes active as soon as that route is merged.
"""
from dataclasses import asdict
import re

from engine.calc import Row, input_value, record, step, step_source, summed, transform


def record_wallarea(res, question):
    report = res.get("wallarea") or {}
    did = next(iter(res.get("doc_ids") or []), None)
    quantity = report.get("requested_quantity", "net") + "_m2"
    rows, steps = [], []
    for index, measured in enumerate(report.get("rows", [])):
        ref = {"kind": "measurement", "doc_id": did, "page": 1, "item_id": measured["item_id"],
               "field": f"wallarea.rows[{index}]", "record": measured,
               "text": f"{report.get('source')}; wall-area geometry measurement retained with the answer"}
        sid = f"wall-face-{index}"
        net = measured["gross_m2"] - measured["opening_m2"]
        steps.append(step(sid, "Net wall surface", "gross side faces − actual opening cuts", net, "m2",
                          [input_value("gross side faces", measured["gross_m2"], "m2", {**ref, "field": ref["field"] + ".gross_m2"}),
                           input_value("opening cuts", measured["opening_m2"], "m2", {**ref, "field": ref["field"] + ".opening_m2"})],
                          "The deduction is the measured void intersection; nominal door width × height is not substituted.", "subtract"))
        rows.append(asdict(Row(measured["item_id"], measured.get("label") or "Wall", {"area_m2": measured[quantity],
                                       "gross_m2": measured["gross_m2"], "opening_m2": measured["opening_m2"], "net_m2": measured["net_m2"],
                                       "storey": measured.get("storey")}, step_source(sid) if quantity == "net_m2" else ref)))
    area = report.get("value_m2")
    base = {"answer": {"value": area, "unit": "m2"}}
    calc = summed(base, rows, "m2", f"wall surface = Σ({quantity.replace('_m2', '')} side-face areas)", steps,
                  note="Measurements are partitioned by wall and floor/room; ends, caps and reveals are excluded by the wall-area route.")
    calc["checks"] = [{"method": c.get("quantity", "stored area check"), "value": c.get("stored_m2"),
                       "agrees": abs(c.get("difference_m2", 0)) <= report.get("numerical_allowance_m2", 0),
                       "diff_pct": c.get("difference_pct"), "wall_id": c.get("wall_id")} for c in report.get("checks", [])]
    margin = {"value": report.get("margin_m2"), "unit": "m2", "pct": report.get("margin_pct"),
              "why": "Numerical and orientation allowance from the wall geometry measurement; source-model accuracy and construction tolerances are unquantified.",
              "sources": [f"{did}: wall surface geometry"]}
    if report.get("sheet_count") is not None:
        for s in calc["steps"]:
            if s["id"] == "result": s["id"] = "area-result"
        area_source = step_source("area-result")
        pct = report.get("waste_pct", 0)
        question_ref = {"kind": "question", "text": question}
        dimensions = re.search(r"(\d+(?:\.\d+)?)\s*[×x]\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|ft|feet)?\b", question, re.I)
        width, height = (float(dimensions[1]), float(dimensions[2])) if dimensions else (1.2, 2.4)
        from_unit = (dimensions[3] or "m").lower() if dimensions else "m"
        unit_factor = {"mm": .001, "cm": .01, "ft": .3048, "feet": .3048}.get(from_unit, 1.)
        dims_ref = question_ref if dimensions else {"kind": "assumption", "text": "Wall-area route's default sheet dimensions: 1.2 × 2.4 m"}
        from engine.calc import converted_step
        calc["steps"].extend([
            converted_step("sheet-width", width, from_unit, "m", unit_factor, dims_ref),
            converted_step("sheet-height", height, from_unit, "m", unit_factor, dims_ref),
            step("sheet-area", "Area per sheet", "converted width × converted height", width * height * unit_factor ** 2, "m2",
                 [input_value("width", width * unit_factor, "m", step_source("sheet-width")), input_value("height", height * unit_factor, "m", step_source("sheet-height"))], operation="multiply")])
        calc["steps"].extend([
            step("waste-fraction", "Stated waste fraction", "waste percent / 100", pct / 100, "fraction",
                 [input_value("waste", pct, "%", question_ref), input_value("percent divisor", 100, "%/fraction", {"kind": "conversion", "text": "100 percent = 1"})], operation="divide"),
            step("waste-factor", "Include base area", "1 + waste fraction", 1 + pct / 100, "factor",
                 [input_value("base factor", 1, "factor", {"kind": "policy", "text": "Include the measured base area"}), input_value("waste fraction", pct / 100, "fraction", step_source("waste-fraction"))], operation="sum"),
            step("order-area", "Area including waste", "area × waste factor", report["order_area_m2"], "m2",
                 [input_value("area", area, "m2", area_source), input_value("waste factor", 1 + pct / 100, "factor", step_source("waste-factor"))], operation="multiply"),
            step("fractional-sheets", "Sheets by area", "order area / sheet area", report["order_area_m2"] / report["sheet_area_m2"], "count",
                 [input_value("order area", report["order_area_m2"], "m2", step_source("order-area")), input_value("sheet area", report["sheet_area_m2"], "m2/sheet", step_source("sheet-area"))], operation="divide"),
            step("ceil-tolerance", "Whole-sheet boundary tolerance", "fractional sheets − numeric tolerance", report["order_area_m2"] / report["sheet_area_m2"] - 1e-10, "count",
                 [input_value("fractional sheets", report["order_area_m2"] / report["sheet_area_m2"], "count", step_source("fractional-sheets")), input_value("numeric tolerance", 1e-10, "count", {"kind": "policy", "text": "Wall-area solver tolerance before rounding up"})], operation="subtract"),
        ])
        transform(res, calc, "Whole sheets", "ceil", [input_value("fractional sheets", report["order_area_m2"] / report["sheet_area_m2"] - 1e-10, "count", step_source("ceil-tolerance"))], "ceil(order area / sheet area − numeric tolerance)", unit="count")
        calc = res["_calc"]
        margin = {"value": None, "unit": "count", "pct": None, "why": "The wall-area uncertainty and sheet cutting layout do not establish a finite error bound for whole sheets; this is the area minimum.", "sources": margin["sources"]}
    else:
        if report.get("waste_pct"):
            pct = report["waste_pct"]
            calc["steps"].extend([
                step("waste-fraction", "Stated waste fraction", "waste percent / 100", pct / 100, "fraction",
                     [input_value("waste", pct, "%", {"kind": "question", "text": question}), input_value("percent divisor", 100, "%/fraction", {"kind": "conversion", "text": "100 percent = 1"})], operation="divide"),
                step("waste-factor", "Include base area", "1 + waste fraction", 1 + pct / 100, "factor",
                     [input_value("base factor", 1, "factor", {"kind": "policy", "text": "Include the base area"}), input_value("waste fraction", pct / 100, "fraction", step_source("waste-fraction"))], operation="sum"),
                step("order-area", "Area including waste", "area × (1 + waste fraction)", report["order_area_m2"], "m2",
                     [input_value("area", area, "m2", step_source("result")), input_value("factor", 1 + pct / 100, "factor", step_source("waste-factor"))], operation="multiply")])
            calc["result"]["additional"] = [{"label": "Area including stated waste", "value": report["order_area_m2"], "unit": "m2", "step_id": "order-area"}]
        record(res, calc)
    # The existing wall-area card does not always carry a structured margin.
    res.setdefault("reasoning", {})["margin"] = margin
    calc["margin"] = margin
    return res
