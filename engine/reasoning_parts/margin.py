"""Measured error budgets and reproducible arithmetic; no model calls.

Margins describe the reported quantity, not a guarantee that the source is complete.
Scale confidence is a ranking, never converted to a distance or probability. A
recount only narrows an error budget when an evaluation measured that cohort.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from dataclasses import replace
from pathlib import Path
from statistics import mean, stdev

REPO = Path(__file__).resolve().parents[2]
UNITS = {"m2": "m²", "m3": "m³", "count": "elements"}


def number(value):
    try:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    except OverflowError:
        return None


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _fmt(value):
    return f"{value:,.12g}" if value else "0"


def rounding(value, text, unit):
    """Half of the last displayed place; counts have no rounding uncertainty."""
    if unit == "count":
        return 0.0
    heads = re.findall(r"\*\*(.+?)\*\*", text or "", re.S)
    for token in re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w.])", " ".join(heads) if heads else text or ""):
        token = token.replace(",", "")
        places = len(token.partition(".")[2])
        if abs(float(token) - round(value, places)) < 1e-8:
            return 0.5 * 10 ** -places
    places = max(0, -Decimal(str(value)).as_tuple().exponent)
    return 0.5 * 10 ** -places


def _rows(ctx):
    """Resolve (document, item) pairs, avoiding collisions across documents."""
    from engine.solvers.data import load_doc
    docs = {}
    if ctx.get("doc"):
        docs[ctx["doc"].doc_id] = ctx["doc"]
    rows, missing, seen, lookups, page_docs = [], 0, set(), {}, {}
    for cite in ctx.get("cites", []):
        did = cite.get("doc_id") or (ctx["doc"].doc_id if ctx.get("doc") else None)
        if did not in docs:
            try:
                docs[did] = load_doc(did, ctx["root"]) if did and ctx.get("root") else None
            except (OSError, ValueError, KeyError, TypeError):
                docs[did] = None
        doc = docs.get(did)
        if did not in lookups:
            lookups[did] = {i.item_id: i for i in doc.items} if doc else {}
        items = lookups[did]
        for iid in cite.get("item_ids") or []:
            if (did, iid) in seen:
                continue
            seen.add((did, iid))
            if iid not in items:
                missing += 1
            else:
                item = items[iid]
                owner = doc
                if doc.mode == "planmap" and doc.pages > 1 and item.page != 1:
                    key = (did, item.page)
                    if key not in page_docs:
                        pm = _json(Path(ctx.get("root", ".")) / did / f"planmap-{item.page}.json")
                        page_docs[key] = replace(doc, scale=pm.get("scale"))
                    owner = page_docs[key]
                rows.append((owner, item, cite.get("n")))
    return rows, missing


def _exact(doc, item):
    method = str((doc.scale or {}).get("method") or "").lower()
    return doc.mode == "ifc" or (item.source == "dxf" and method in ("dxf", "dxf-units", "dxf_units_fit", "dxf-units-fit"))


def _quantity(item, unit):
    # Same precedence as the numeric solver. Never infer an area from a box.
    from engine.solvers.solve import _qty
    kind = "room" if item.kind == "space" else item.kind
    try:
        return number(_qty(item, kind, {"m": "length", "m2": "area", "m3": "volume"}[unit]))
    except (KeyError, TypeError, ValueError):
        return None


def _measurement(doc, item, unit, value):
    if unit != "m2":
        return None
    q = item.q or {}
    if all(q.get(k) is None for k in ("net_floor_area_m2", "area_m2", "net_area_m2", "gross_area_m2", "net_side_area_m2")):
        width, height = number(q.get("width_m")), number(q.get("height_m"))
        if width is not None and height is not None:
            return {"formula": "Multiply width by height", "operands": [{"value": width, "unit": "m"}, {"value": height, "unit": "m"}]}
    if doc.mode == "planmap":
        from engine.reasoning import _shoelace
        px = number((item.props or {}).get("area_px"))
        if px is None and item.polygon_px:
            px = _shoelace(item.polygon_px)
        scale = number((doc.scale or {}).get("m_per_px"))
        if px and scale and abs(px * scale * scale - value) <= .005 + 1e-7:
            return {"formula": "Multiply outline pixel area by metres per pixel twice",
                    "operands": [{"value": px, "unit": "px²"}, {"value": scale, "unit": "m/px"}, {"value": scale, "unit": "m/px"}]}
    return None


def arithmetic(ctx, rows, missing, value, unit, rounding_error):
    terms = []
    for doc, item, cite in rows:
        val = 1.0 if unit == "count" else _quantity(item, unit)
        if val is not None:
            term = {"doc_id": doc.doc_id, "item_id": item.item_id, "cite": cite, "value": val, "unit": unit}
            measurement = _measurement(doc, item, unit, val)
            if measurement:
                term["measurement"] = measurement
            terms.append(term)
    total = sum(t["value"] for t in terms)
    matches = bool(terms) and not missing and len(terms) == len(rows) and abs(total - value) <= rounding_error + 1e-7
    if not matches:
        return None
    word = "Count each cited element once" if unit == "count" else "Add the source quantities"
    shown = " + ".join(_fmt(t["value"]) for t in terms[:6])
    if len(terms) > 6:
        shown += f" + {len(terms) - 6} more"
    text = f"{word}: {shown} = {_fmt(value)} {UNITS.get(unit, unit)}."
    if len(terms) == 1 and terms[0].get("measurement"):
        measure = terms[0]["measurement"]
        word = measure["formula"]
        text = word + ": " + " × ".join(f"{_fmt(p['value'])} {p['unit']}" for p in measure["operands"]) + f" = {_fmt(value)} {UNITS.get(unit, unit)}."
    for step in ctx["steps"]:
        if step.get("kind") in ("measured", "calculated"):
            step["text"] = text
            break
    else:
        ctx["steps"].insert(1 if ctx["steps"] else 0, {"kind": "calculated", "title": "Calculated", "text": text, "cite": None, "ok": None})
    return {"formula": word, "terms": terms, "result": value, "unit": unit, "text": text}


def _unknown(unit, why, sources=(), **extra):
    return {"value": None, "unit": unit, "pct": None, "why": why, "sources": list(sources), **extra}


def _budget(value, unit, error, why, sources, **extra):
    if not math.isfinite(error):
        return _unknown(unit, "The recorded values exceed the supported numeric range for an error budget.", sources)
    pct = error / abs(value) * 100 if value else (0.0 if error == 0 else None)
    return {"value": error, "unit": unit, "pct": pct if pct is None or math.isfinite(pct) else None,
            "why": why, "sources": list(sources), **extra}


def _scale_budget(doc, items, value, unit, rnd):
    sc = doc.scale or {}
    method = str(sc.get("method") or "none")
    confidence = number(sc.get("confidence"))
    prefix = f"Scale method: {method.replace('-', ' ').replace('_', ' ')}"
    if confidence is not None:
        prefix += f"; scale confidence {_fmt(confidence)} (not an error bound)"
    rel = number(sc.get("relative_error"))
    mpp = number(sc.get("m_per_px"))
    absolute = number(sc.get("uncertainty_m_per_px"))
    spread = number(sc.get("spread_pct"))
    residual, bar = number(sc.get("fit_residual_px")), number(sc.get("scale_bar_px"))
    if rel is None and absolute is not None and mpp and mpp > 0:
        rel = absolute / mpp
    if rel is None and residual is not None and bar and bar > 0:
        rel = residual / bar
        prefix += f"; scale-bar fit residual {_fmt(residual)} px over {_fmt(bar)} px"
    if rel is None and spread is not None:
        rel = spread / 100
        prefix += f"; measured spread {_fmt(spread)}%"
    if "door" in method:
        widths = [max(i.bbox_px[2] - i.bbox_px[0], i.bbox_px[3] - i.bbox_px[1])
                  for i in doc.items if i.kind == "door" and i.page in {x.page for x in items} and i.bbox_px and len(i.bbox_px) == 4]
        widths = [w for w in widths if math.isfinite(w) and w > 0]
        if len(widths) > 1:
            scatter = stdev(widths) / mean(widths)
            prefix += f"; {len(widths)} door widths, sample spread {_fmt(scatter * 100)}%"
        else:
            scatter = None
        prior = number(sc.get("door_width_relative_error"))
        if prior is None:
            return _unknown(unit, prefix + ". Real door-width variation is not measured; icon spread alone cannot bound the scale error.", [f"{doc.doc_id}: scale"])
        if rel is None and scatter is not None:
            rel = prior + scatter
    if rel is None or rel < 0:
        return _unknown(unit, prefix + ". No scale spread, physical prior uncertainty or fit residual was recorded.", [f"{doc.doc_id}: scale"])
    power = {"m": 1, "m2": 2, "m3": 3}[unit]
    err = abs(value) * (power * rel) + rnd
    return _budget(value, unit, err, prefix + f". Multiply relative scale error by {power}, then add display rounding; outline error is not measured.",
                   [f"{doc.doc_id}: scale"], scope="Scale and display rounding only")


def _detector_budget(ctx, rows, value, rnd):
    if value <= 0:
        return _unknown("count", "No detections: precision and recall alone cannot estimate how many elements were missed.")
    kinds = {it.kind for _, it, _ in rows}
    if len(kinds) != 1 or len({d.doc_id for d, _, _ in rows}) != 1:
        return _unknown("count", "No matching per-kind detector evaluation is recorded for this set of sources.")
    doc, item, _ = rows[0]
    pm = _json(Path(ctx.get("root", ".")) / doc.doc_id / f"planmap-{item.page}.json")
    provenance = pm.get("provenance") or {}
    # Explicitly linked evaluation only: never borrow a score from a different model.
    ref = provenance.get("detector_evaluation")
    if not isinstance(ref, str):
        return _unknown("count", "Detector precision and recall have not been measured for this model and drawing source. Recount agreement alone cannot quantify missed elements.")
    base = (REPO / "results/vision").resolve()
    path = (REPO / ref).resolve()
    if not path.is_relative_to(base) or path.suffix != ".json":
        return _unknown("count", "The detector evaluation is not a results/vision JSON report.")
    evaluation = _json(path)
    active = (provenance.get("models") or {}).get(item.source)
    if not active or evaluation.get("model") != active or evaluation.get("source") != pm.get("doc_id", doc.doc_id).split("__")[0]:
        return _unknown("count", "The detector evaluation does not match the active model and drawing source.", [ref])
    metrics = (evaluation.get("per_kind") or {}).get(item.kind) or {}
    cohort = "all detections"
    if ctx.get("checked") is True and isinstance(metrics.get("recount_agrees"), dict):
        metrics, cohort = metrics["recount_agrees"], "detections where recount agrees"
    p, r, n = number(metrics.get("precision")), number(metrics.get("recall")), number(metrics.get("n"))
    if p is None or r is None or not 0 < p <= 1 or not 0 < r <= 1 or n is None or n <= 0:
        return _unknown("count", "The matched report has no usable measured precision, recall and sample count.", [ref])
    fp, fn = value * (1 - p), value * p * (1 / r - 1)
    return _budget(value, "count", fp + fn + rnd,
                   f"Expected false positives {_fmt(fp)} + missed elements {_fmt(fn)}; precision {_fmt(p)}, recall {_fmt(r)}, {int(n)} evaluation samples ({cohort}). This is an expected miscount, not a guaranteed bound.",
                   [ref], scope="Expected detector miscount")


def run(ctx):
    rows, missing = _rows(ctx)
    ctx["quantified_source"] = ("ifc" if rows and all(d.mode == "ifc" for d, _, _ in rows) else
                                "cad" if rows and all(_exact(d, i) for d, i, _ in rows) else
                                "scan" if rows and all(d.mode == "planmap" for d, _, _ in rows) else "unknown")
    if len({d.doc_id for d, _, _ in rows}) > 1:
        # The earlier parts work on the first document only. Do not present
        # their partial check or element count as a check of the complete sum.
        ctx["checked"] = None
        ctx["steps"] = [s for s in ctx["steps"] if s.get("kind") != "checked"]
        for step in ctx["steps"]:
            if step.get("kind") == "found":
                step["text"] = f"{len(rows)} cited elements across {len({d.doc_id for d, _, _ in rows})} source files."
    estimated = sum(not _exact(doc, item) for doc, item, _ in rows)
    source = "the model" if rows and all(d.mode == "ifc" for d, _, _ in rows) else "the source files"
    based = {"elements": len(rows), "estimated": estimated, "unresolved": missing,
             "text": f"Based on {len(rows)} cited elements from {source}; {estimated} estimated" + (f"; {missing} unresolved" if missing else "") + "."}
    result = {"based_on": based}
    value, unit = number(ctx.get("value")), ctx.get("unit") or ""
    if value is None:
        # Multi-kind values get separate budgets rather than adding unlike answers.
        values = ctx.get("value")
        if isinstance(values, dict) and unit == "count" and all(number(v) is not None for v in values.values()):
            budgets, calculations = {}, []
            for kind, count in values.items():
                subset = [(d, i, c) for d, i, c in rows if i.kind == kind]
                if len(subset) == count and subset and all(_exact(d, i) for d, i, _ in subset) and not ctx.get("models_used") and not missing:
                    budgets[kind] = _budget(count, unit, 0, "Exact count of cited source elements; source completeness is not bounded.", [])
                else:
                    budgets[kind] = _detector_budget(ctx, subset, count, 0) if subset else _unknown(unit, "No cited elements for this category.")
                subctx = {**ctx, "steps": []}
                calc = arithmetic(subctx, subset, missing, count, unit, 0)
                if calc:
                    calc["formula"] += f" ({kind})"
                    calculations.append(calc)
                    ctx["steps"].extend({**s, "text": f"{kind}: {s['text']}"} for s in subctx["steps"])
            if calculations:
                result["arithmetic"] = calculations
            ctx["quantified_exact"] = bool(budgets) and all(m["value"] == 0 for m in budgets.values()) and ctx.get("checked") is not False
            result["margin"] = _unknown(unit, "Separate margins apply to each category.", by_kind=budgets)
        elif isinstance(values, (int, float)) and not isinstance(values, bool):
            result["margin"] = _unknown(unit, "The recorded value is not a finite number, so its error cannot be estimated.")
        elif any(s.get("kind") in ("measured", "calculated") for s in ctx["steps"]):
            result["margin"] = _unknown(unit, "The answer contains several quantities; their individual error budgets were not recorded.")
        return result
    rnd = rounding(value, ctx["ans"].get("text_md"), unit)
    calc = arithmetic(ctx, rows, missing, value, unit, rnd) if unit in ("count", "m", "m2", "m3") else None
    from engine import xcheck
    independent = xcheck.run(ctx, rows, missing, calc)
    if independent:
        calc = independent.pop("_arithmetic", None) or calc
        result["calc"] = independent
    if calc:
        result["arithmetic"] = [calc]
    else:
        # A partial citation set must never masquerade as the full take-off.
        for step in ctx["steps"]:
            if step.get("kind") in ("measured", "calculated"):
                step["text"] += " Full arithmetic is unavailable: the source terms do not reconcile with this answer."
    exact = bool(calc and rows and not missing and not ctx.get("models_used") and all(_exact(d, i) for d, i, _ in rows))
    ctx["quantified_exact"] = exact and ctx.get("checked") is not False and all(c["within_1pct"] for c in ctx.get("xchecks", []))
    sources = list(dict.fromkeys(f"{d.doc_id}: source quantities" for d, _, _ in rows))
    if exact:
        margin = _budget(value, unit, rnd, "Display rounding only; the cited source quantities reproduce the answer. Source completeness, scope and construction tolerances are not bounded.", sources, scope="Source quantity and display rounding")
        if ctx.get("checked") is False:
            margin = _unknown(unit, "The source readings disagree; display rounding alone cannot bound the discrepancy.", sources)
    elif not calc:
        margin = _unknown(unit, "The full set of source quantities does not reproduce this answer; its calculation or measurement uncertainty was not recorded.", sources)
    elif unit == "count":
        margin = _detector_budget(ctx, rows, value, rnd)
    elif len({(d.doc_id, i.page) for d, i, _ in rows}) == 1 and rows:
        margin = _scale_budget(rows[0][0], [i for _, i, _ in rows], value, unit, rnd)
    else:
        margin = _unknown(unit, "This answer combines pages or sources without individual scale error budgets.", sources)
    result["margin"] = margin
    if independent:
        # Agreement is an observed discrepancy, never an uncertainty bound.
        independent["margin"] = margin
        observed = [c["calibration"] for c in independent["checks"] if c.get("calibration")]
        if observed:
            margin["agreement"] = observed
    return result
