"""Independent quantity comparisons. No inference, provider calls or hidden units.

An arithmetic identity, a bounding rectangle and a mask made from an outline are
not independent measurements. Missing second readings stay explicitly unavailable.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1] / "results/final/XCHECK/agreement.json"
AREA = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(m[²2]|ft[²2]|sq\.?\s*ft)(?!\w)", re.I)


def finite(value):
    try:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    except OverflowError:
        return None


@lru_cache(maxsize=32)
def _read(path, modified):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read(path):
    try:
        path = Path(path)
        return _read(str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}


def source(doc, item):
    return {"doc_id": doc.doc_id, "page": item.page, "item_id": item.item_id, "bbox": item.bbox_px}


def compare(method, primary, second, unit, sources, *, independent=True, **extra):
    a, b = finite(primary), finite(second)
    if a is None or b is None or a < 0 or b < 0:
        return None
    # Symmetric, bounded relative difference; a zero vs a nonzero is 100%.
    diff = abs(a - b) / max(abs(a), abs(b)) * 100 if a or b else 0.0
    return {"method": method, "primary_value": a, "value": b, "unit": unit,
            "agrees": diff <= 5 + 1e-9, "diff_pct": diff, "within_1pct": diff <= 1 + 1e-9,
            "independent": independent, "sources": sources, **extra}


def room_checks(doc, item):
    """Printed label vs outline, and detector pixel fill vs outline (correlated)."""
    from engine.reasoning import _shoelace
    from engine.reasoning_parts.checked import _inside
    props = item.props or {}
    sc = doc.scale or {}
    scale = finite(sc.get("m_per_px"))
    poly = item.polygon_px
    if not poly or len(poly) < 3 or not scale or scale <= 0:
        return []
    outline = _shoelace(poly) * scale ** 2
    label = finite(props.get("area_m2_label"))
    label_sources = [source(doc, item)]
    if label is None:
        labels = []
        for text in doc.items:
            b = text.bbox_px
            if text.kind != "text" or text.page != item.page or not b or len(b) != 4:
                continue
            matches = list(AREA.finditer(text.label or ""))
            if len(matches) == 1 and _inside(((b[0]+b[2])/2, (b[1]+b[3])/2), poly):
                m = matches[0]
                factor = 1.0 if m[2].lower().startswith("m") else 0.3048 ** 2
                labels.append((float(m[1].replace(",", ".")) * factor, text, factor))
        if len(labels) == 1:
            label, text, factor = labels[0]
            label_sources.append({**source(doc, text), "unit_conversion": "ft² × 0.3048² = m²" if factor != 1 else "m²"})
    checks = []
    if label is not None:
        dependent_scale = any(s in str(sc.get("method", "")).lower() for s in ("printed-area", "room-area", "rooms-printed"))
        c = compare("printed area / room outline", label, outline, "m2", label_sources,
                    independent=not dependent_scale, kind="room", note="Outline area = shoelace(px) × (m/px)²; shared scale uncertainty is not bounded.")
        if c:
            checks.append(c)
    fill = finite(props.get("area_px"))
    if fill is not None:
        c = compare("filled pixels / room outline", fill * scale ** 2, outline, "m2", [source(doc, item)], independent=False,
                    note="Both come from the same segmentation; this checks contour simplification, not detection accuracy.")
        if c:
            checks.append(c)
    return checks


def calibration(check, cohort):
    """Descriptive method agreement, explicitly never a probability of correctness."""
    report = read(REPORT)
    for row in report.get("pairs", []):
        if row.get("method") == check["method"] and row.get("cohort") == cohort and row.get("unit") == check["unit"] and row.get("kind") == check.get("kind"):
            n = row.get("n")
            a, b = row.get("within_1pct"), row.get("within_5pct")
            if type(n) is int and n > 0 and all(type(v) is int and 0 <= v <= n for v in (a, b)):
                return {"n": n, "within_1pct": a, "within_5pct": b, "pct": b / n * 100,
                        "source": "results/final/XCHECK/agreement.json", "scope": "Observed method agreement, not accuracy or an error bound"}
    return None


def item_checks(doc, item, unit, root):
    if doc.mode != "ifc":
        return room_checks(doc, item) if unit == "m2" and item.kind in ("room", "space") else []
    # Produced by xcheck_ifc offline, or at ingestion. Read only; never run an IFC
    # geometry pass in a request. Missing dependencies do not break the API.
    data = read(Path(root) / doc.doc_id / "xcheck.json")
    records = data.get("elements", {})
    if not isinstance(records, dict):
        return []
    cached = []
    for c in records.get(item.item_id, []):
        if not isinstance(c, dict) or c.get("unit") != unit or c.get("independent") is not True or not c.get("sources"):
            continue
        fresh = compare(c.get("method", "IFC quantity / geometry"), c.get("primary_value"), c.get("value"), unit, c["sources"])
        if fresh:
            cached.append({**fresh, "kind": item.kind})
    if cached:
        return cached
    # Reuse the already converted scene, where available. Provenance must prove
    # the primary is a quantity set, not a bbox/mesh fallback of the same shape.
    raw = read(Path(root) / doc.doc_id / "elements.json")
    element = next((e for e in raw.get("elements", []) if e.get("item_id") == item.item_id), {})
    keys = {"m2": ("net_floor_area_m2", "area_m2", "net_area_m2", "gross_area_m2"),
            "m3": ("net_volume_m3", "volume_m3", "gross_volume_m3"), "m": ("length_m",)}.get(unit, ())
    key = next((k for k in keys if item.q.get(k) is not None), None)
    semantic = "net_floor_area_m2" if unit == "m2" else "net_volume_m3"
    # Generic aliases can be gross quantities. Compare only a known net
    # quantity with a net mesh measurement, with solver precedence unchanged.
    if not key or item.q.get(semantic) != item.q[key] or (element.get("quantity_source") or {}).get(key) != "qto":
        return []
    if unit == "m" or (unit == "m2" and item.kind not in ("room", "space")):
        return []
    from engine.xcheck_geometry import mesh_quantity
    measured = mesh_quantity(Path(root) / doc.doc_id / "scene.glb", item.item_id, unit, item.kind)
    method = "IFC Qto / geometry footprint" if unit == "m2" else "IFC Qto / closed geometry volume"
    c = compare(method, item.q[key], measured, unit, [{**source(doc, item), "quantity": key, "geometry": "scene.glb", "geometry_units": "metres, Y-up"}])
    return [{**c, "kind": item.kind}] if c else []


def floor_check(ctx, rows, arithmetic):
    """Room sum vs independently drawn unit boundaries minus wall solids.

    Applies only when the selected rooms completely cover those units. Shared
    stairs/corridors outside the units and partial room selections are rejected.
    """
    if not arithmetic or len(rows) < 2 or any(d.mode == "ifc" or i.kind not in ("room", "space") for d, i, _ in rows):
        return None
    if len({(d.doc_id, i.page) for d, i, _ in rows}) != 1:
        return None
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        doc, first, _ = rows[0]
        scale = finite((doc.scale or {}).get("m_per_px"))
        if not scale or scale <= 0:
            return None
        selected = {i.item_id for _, i, _ in rows}
        all_rooms = [(i, Polygon(i.polygon_px)) for i in doc.items if i.page == first.page and i.kind in ("room", "space") and i.polygon_px]
        units = [(i, Polygon(i.polygon_px)) for i in doc.items if i.page == first.page and i.props.get("role") in ("unit", "floor_outline") and i.polygon_px]
        walls = [(i, Polygon(i.polygon_px)) for i in doc.items if i.page == first.page and i.kind == "wall" and i.polygon_px]
        if len([i for i, _ in all_rooms if i.item_id in selected]) != len(selected):
            return None
        if not units or not walls or not all(p.is_valid for _, p in all_rooms + units + walls):
            return None
        chosen = [(i, p) for i, p in units if any(iid.item_id in selected and p.covers(rp) for iid, rp in all_rooms)]
        outer = unary_union([p for _, p in chosen])
        if not all(outer.covers(p) for i, p in all_rooms if i.item_id in selected):
            return None
        if any(outer.intersection(p).area > max(outer.area, 1) * 1e-8 for i, p in all_rooms if i.item_id not in selected):
            return None
        net = outer.difference(unary_union([p for _, p in walls])).area * scale ** 2
        c = compare("room sum / outer outline minus walls", ctx["value"], net, "m2",
                    [source(doc, i) for i, _ in chosen + walls],
                    note="Net area = union of drawn unit outlines minus union of wall solids, in px² × (m/px)². Scope excludes uncovered or unselected rooms.")
        if c:
            c["kind"] = "room"
            c["cohort"] = "cad" if all(i.source == "dxf" for _, i, _ in rows) else "scan"
            c["calibration"] = calibration(c, c["cohort"])
        return c
    except (ImportError, TypeError, ValueError):
        return None


def run(ctx, rows, missing, arithmetic):
    value, unit = finite(ctx.get("value")), ctx.get("unit")
    if value is None or unit not in ("count", "m", "m2", "m3"):
        return None
    checks, per_item = [], []
    groups = {}
    for doc, item, _ in rows:
        for c in item_checks(doc, item, unit, ctx.get("root", ".")):
            per_item.append({**c, "item_id": item.item_id, "doc_id": doc.doc_id})
            groups.setdefault(c["method"], []).append((doc, item, c))
    for method, group in groups.items():
        # Partial checks never stand for the complete headline quantity.
        if arithmetic and not missing and len(group) == len(rows) and all(c["independent"] for _, _, c in group):
            a = sum(c["primary_value"] for _, _, c in group)
            b = sum(c["value"] for _, _, c in group)
            # One reading must reproduce the headline; swapping is explicit.
            tol = max(1e-6, abs(value) * 1e-6)
            if abs(a - value) <= tol or abs(b - value) <= tol:
                second = b if abs(a-value) <= tol else a
                c = compare(method, value, second, unit, [s for _, _, c in group for s in c["sources"]])
                if c:
                    c["kind"] = next(iter({i.kind for _, i, _ in group})) if len({i.kind for _, i, _ in group}) == 1 else "mixed"
                    c["cohort"] = "ifc" if all(d.mode == "ifc" for d, _, _ in group) else "cad" if all(i.source == "dxf" for _, i, _ in group) else "scan"
                    c["calibration"] = calibration(c, c["cohort"])
                    checks.append(c)
    if unit == "m2":
        floor = floor_check(ctx, rows, arithmetic)
        if floor:
            checks.append(floor)
    # Existing real recounts only. Never pay for an additional call here.
    if unit == "count" and len(ctx.get("res", {}).get("doc_ids", [])) == 1:
        for step in ctx.get("trace", []):
            match = re.search(r"plan map (\d+), drawing re-read (\d+)", str(step.get("detail", "")))
            if match and step.get("model") and "fake" not in str(step["model"]).lower():
                a, b = map(int, match.groups())
                if value in (a, b):
                    c = compare("detector / drawing recount", value, b if value == a else a, unit,
                                [{"doc_id": ctx["res"]["doc_ids"][0], "page": 1, "trace_step": step.get("step"), "model": step["model"]}])
                    c["cohort"] = "scan"
                    from engine.router.parser import parse
                    c["kind"] = parse(ctx.get("question") or "").kind
                    c["calibration"] = calibration(c, "scan")
                    checks.append(c)
                    break
    ctx["xchecks"] = checks
    if checks:
        # Disagreement takes precedence over any older plausibility check.
        ctx["checked"] = all(c["agrees"] for c in checks)
        ctx["steps"] = [s for s in ctx["steps"] if s.get("kind") != "checked"]
        c = max(checks, key=lambda c: c["diff_pct"])
        ctx["steps"].append({"kind": "checked", "title": "Checked", "ok": ctx["checked"], "cite": None,
                             "text": f"{c['method']}: {c['primary_value']:.6g} and {c['value']:.6g} {unit}; {c['diff_pct']:.3g}% apart."})
    elif ctx.get("checked") is True and unit in ("m2", "m", "m3"):
        # A room's enclosing box is not an independent measurement of its area.
        ctx["checked"] = None
        ctx["steps"] = [s for s in ctx["steps"] if s.get("kind") != "checked"]
    terms = (arithmetic or {}).get("terms", [])
    resolved = {(d.doc_id, i.item_id): (d, i) for d, i, _ in rows}
    calc_rows, inputs = [], []
    for t in terms:
        d, i = resolved[(t["doc_id"], t["item_id"])]
        src = source(d, i)
        label = i.label or i.name or i.kind.replace("_", " ").capitalize()
        calc_rows.append({"item_id": i.item_id, "label": label, "values": {unit: t["value"]}, "source": src})
        inputs.append({"name": label, "value": t["value"], "unit": unit, "source": src})
    return {"formula": (arithmetic or {}).get("formula", "Full source arithmetic unavailable"),
            "steps": [{"id": "sum", "label": "Add cited quantities", "expr": "Σ source quantities", "value": value,
                       "unit": unit, "inputs": inputs}] if terms else [], "rows": calc_rows,
            "result": {"value": value, "unit": unit, "rounded_as": "as reported in the answer"},
            "checks": checks, "item_checks": per_item,
            "unavailable": [] if checks else ["No independent second reading covers the complete answer."],
            "reconciled": bool(arithmetic)}
