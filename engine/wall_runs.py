"""Wall-run lengths on plan maps: "longest wall", "total wall length", "wall length".

Raster and DXF wall components are often connected networks (several runs plus junctions), so a component is
not one wall. Each outline is split into straight runs (collinear outline edges merged) and the longest run is
reported with its own bbox. Totals use the same thin-wall relation as engine.wallarea (run length = half the
outline perimeter for a network, the long side for a rectangle). Plain code, no model.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

MIN_RUN_M = 0.3          # shorter outline edges are caps, jogs and pixel noise, not wall runs
ANGLE_TOL = math.radians(4)
RE_ASK = re.compile(r"\bwalls?\b")
RE_EXCL = re.compile(r"\b(?:area|surface|volume|thickness|height|how many|count|number of|take.?off|paint|plaster|wide|width)\b")
RE_SUPER_LEN = re.compile(r"\b(?:longest|biggest|largest)\b|\bhow long is the (?:longest|biggest|largest)\b")
RE_TOTAL = re.compile(r"\bwall lengths?\b|\blengths? of (?:the |all )?(?:\w+ )?walls\b|\bhow long are (?:the |all )?(?:\w+ )?walls\b|"
                      r"\b(?:total|sum|combined|overall)\b.*\b(?:length|long)\b|\b(?:length|long)\b.*\b(?:total|sum|combined|overall)\b")


def wants_wall_runs(question: str) -> str | None:
    """'longest' | 'shortest' | 'total' | None. Every phrasing of a wall-length question lands here, not on a count."""
    q = (question or "").casefold()
    if not RE_ASK.search(q) or RE_EXCL.search(q):
        return None
    if RE_SUPER_LEN.search(q):
        return "longest"
    if re.search(r"\bshortest\b", q):
        return "shortest"   # plan maps decline it below (an outline edge is a cap, not a wall); IFC has stored lengths
    if RE_TOTAL.search(q):
        return "total"
    return None


def _merge(pts: list, closed: bool) -> list[tuple]:
    """Straight chains of a ring/polyline: [(length, p0, p1)], collinear consecutive edges merged."""
    n = len(pts)
    if n < 2:
        return []
    edges = [(pts[k], pts[(k + 1) % n]) for k in range(n if closed else n - 1)]
    edges = [(a, b) for a, b in edges if math.dist(a, b) > 1e-9]
    if not edges:
        return []
    ang = lambda a, b: math.atan2(b[1] - a[1], b[0] - a[0])
    diff = lambda x, y: abs((x - y + math.pi) % (2 * math.pi) - math.pi)
    # Start the walk at a real corner so a chain is not split by the ring's first vertex.
    start = 0
    if closed:
        for k in range(len(edges)):
            if diff(ang(*edges[k - 1]), ang(*edges[k])) > ANGLE_TOL:
                start = k
                break
    edges = edges[start:] + edges[:start]
    chains, cur = [], [edges[0]]
    for e in edges[1:]:
        a0, b0 = cur[0][0], cur[-1][1]
        if diff(ang(a0, b0), ang(*e)) <= ANGLE_TOL and diff(ang(*cur[-1]), ang(*e)) <= 3 * ANGLE_TOL:
            cur.append(e)
        else:
            chains.append(cur)
            cur = [e]
    chains.append(cur)
    out = []
    for c in chains:
        a, b = c[0][0], c[-1][1]
        out.append((math.dist(a, b), a, b))
    return out


def item_runs(it, mpp: float) -> dict | None:
    """{'runs': [(len_m, p0_px, p1_px)], 'total_m', 'thick_px', 'method'} for one wall item, or None."""
    from shapely.geometry import LineString, Polygon
    props = it.props or {}
    if props.get("derived") == "room-outline":
        return None
    cl = props.get("centerline_px")
    if cl and len(cl) >= 2:
        runs = [(l * mpp, a, b) for l, a, b in _merge([tuple(map(float, p)) for p in cl], False)]
        total = sum(r[0] for r in runs)
        return {"runs": runs, "total_m": total, "thick_px": 0.0, "method": "centreline", "m_per_px": mpp,
                "total_runs": runs, "rings": []} if runs else None
    pts = it.polygon_px
    if not pts and it.bbox_px:
        x0, y0, x1, y1 = it.bbox_px
        pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    if not pts or len(pts) < 3:
        return None
    ring = [(float(x), float(y)) for x, y in pts]
    poly = Polygon(ring)
    repaired = not poly.is_valid
    if repaired:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area <= 0 or poly.geom_type != "Polygon":
        return None
    tol = 0.03 / mpp                                # outline jitter of about 3 cm
    simple = poly.simplify(tol, preserve_topology=True)
    rings = [list(simple.exterior.coords)[:-1]] + [list(h.coords)[:-1] for h in simple.interiors]
    chains = [c for r in rings if len(r) >= 3 for c in _merge(r, True)]
    holes = bool(list(poly.interiors))
    rect = poly.minimum_rotated_rectangle
    rc = list(rect.exterior.coords)
    sides = [math.dist(rc[k], rc[k + 1]) for k in range(4)]
    rectlike = not holes and poly.area / max(rect.area, 1e-9) >= 0.9
    thick_px = 2 * poly.area / poly.length
    if rectlike:
        k = sides.index(max(sides))
        runs = [(max(sides) * mpp, rc[k], rc[k + 1])]
        return {"runs": runs, "total_m": max(sides) * mpp, "thick_px": min(sides), "method": "rectangular outline",
                "m_per_px": mpp, "total_runs": runs, "rings": [], "repaired": repaired}
    runs = [(l * mpp, a, b) for l, a, b in chains if l * mpp >= MIN_RUN_M]
    # Both faces of a thin wall give a run each; the longer one is within a wall thickness of the other.
    return {"runs": runs, "total_m": poly.length * mpp / 2, "thick_px": thick_px, "method": "wall network outline",
            "m_per_px": mpp, "total_runs": [], "repaired": repaired,
            "rings": [list(poly.exterior.coords)[:-1]] + [list(h.coords)[:-1] for h in poly.interiors]}


_RUN_FIELD = {"centreline": "props.centerline_px (ends of a merged straight run)",
              "rectangular outline": "polygon_px -> minimum rotated rectangle, long side",
              "wall network outline": "polygon_px simplified to 3 cm -> ends of a straight outline run"}


def _scale_ref(doc, it, r) -> dict:
    from engine.calc import source
    ref = source(doc, it)
    if "measurement_scale" in (it.props or {}):
        return {**ref, "field": "props.measurement_scale.m_per_px"}
    return {**ref, "kind": "scale", "item_id": None, "field": "scale.m_per_px"}


def _run_steps(doc, it, r, run, sid) -> list[dict]:
    """Pixel length of one straight run from its two ends, then metres = px × m/px (the route's own arithmetic)."""
    from engine.calc import evaluate, input_value, source, step, step_source
    _, a, b = run
    ref = {**source(doc, it), "field": _RUN_FIELD.get(r["method"], "polygon_px")}
    ends = [input_value(f"point {k + 1} {axis}", float(pt[j]), "px", ref)   # the run's two ends
            for k, pt in enumerate((a, b)) for j, axis in enumerate(("x", "y"))]
    px = evaluate("polyline", [i["value"] for i in ends])
    m = evaluate("multiply", [px, r["m_per_px"]])
    return [step(sid + "-px", "Straight run length in pixels", "√((x₂ − x₁)² + (y₂ − y₁)²)", px, "px", ends, operation="polyline"),
            step(sid, "Run length in metres", "pixel length × metres per pixel", m, "m",
                 [input_value("run length", px, "px", step_source(sid + "-px")),
                  input_value("metres per pixel", r["m_per_px"], "m/px", _scale_ref(doc, it, r))], operation="multiply")]


def _result_steps(raw, value, source_step):
    from engine.calc import input_value, places, step, step_source
    nd = places(value)
    return step("result", "Round for the answer", f"round({raw}, {nd})", value, "m",
                [input_value("unrounded length", raw, "m", step_source(source_step)),
                 input_value("decimal places", nd, "decimal places", {"kind": "policy", "text": "Route's recorded answer precision"})],
                operation="round")


def longest_calc(doc, cand, chosen, value) -> dict | None:
    """Calc record for the longest run: px length of the chosen run × m/px, max over every compared run, rounded."""
    from engine.calc import close, input_value, places, row, source, step, step_source
    length, it, run, r = chosen
    steps = _run_steps(doc, it, r, run, "run")
    if not close(steps[-1]["value"], length):
        return None
    inputs = []
    for k, (l, ci, crun, cr) in enumerate(cand):
        if ci is it and crun is run:
            inputs.append(input_value(f"{ci.item_id} run (chosen)", steps[-1]["value"], "m", step_source("run")))
        else:
            inputs.append(input_value(f"{ci.item_id} run", l, "m", {**source(doc, ci), "field": _RUN_FIELD.get(cr["method"], "polygon_px")}))
    raw = steps[1]["value"]
    steps.append(step("longest", "Longest straight run", "max(run lengths)", raw, "m", inputs,
                      f"{len(cand)} straight runs of at least {MIN_RUN_M} m compared; shorter outline edges are caps, jogs and pixel noise.",
                      "max"))
    if not close(round(raw, places(value)), value):
        return None
    steps.append(_result_steps(raw, value, "longest"))
    rw = row(doc, it, steps[1]["value"], "m", kind="wall", length_px=steps[0]["value"])
    rw["measured_by"] = "run"
    return {"formula": "longest wall run = max(run length); run length = pixel length × metres per pixel",
            "steps": steps, "rows": [rw], "checks": [], "margin": {}, "issues": [],
            "result": {"value": value, "unit": "m", "rounded_as": f"{places(value)} decimal places"},
            "row_key": "length_m", "row_total_step": "longest"}


def total_calc(doc, rows, value) -> dict | None:
    """Calc record for the total run length: per wall the long side / straight runs, or half the outline perimeter."""
    from engine.calc import close, evaluate, input_value, places, row, source, step, step_source
    steps, out, sums = [], [], []
    for w, (it, r) in enumerate(rows):
        sid = f"wall-{w}"
        ref = source(doc, it)
        if r["total_runs"]:
            parts = []
            for k, run in enumerate(r["total_runs"]):
                part = _run_steps(doc, it, r, run, f"{sid}-run-{k}")
                steps += part
                parts.append(part[-1])
            if len(parts) == 1:
                last = parts[0]
                last_id = last["id"]
            else:
                last_id = sid + "-runs"
                last = step(last_id, "Add straight runs", "Σ(run lengths)", evaluate("sum", [p["value"] for p in parts]), "m",
                            [input_value("run", p["value"], "m", step_source(p["id"])) for p in parts], operation="sum")
                steps.append(last)
            wall = step(sid, f"{it.item_id} run length", "Σ(straight runs)", last["value"], "m",
                        [input_value("run length", last["value"], "m", step_source(last_id))], operation="source")
        else:
            field = "polygon_px repaired by buffer(0)" if r.get("repaired") else "polygon_px"
            rings = []
            for k, ring in enumerate(r["rings"]):
                if len(ring) < 3:
                    continue
                pts = [input_value(f"vertex {n + 1} {axis}", float(pt[j]), "px", {**ref, "field": f"{field}[{n}]" if k == 0 else f"{field} hole {k}[{n}]"})
                       for n, pt in enumerate(ring) for j, axis in enumerate(("x", "y"))]
                rings.append(step(f"{sid}-ring-{k}", "Outline perimeter" if k == 0 else f"Hole {k} perimeter", "Σ edge lengths, closed outline",
                                  evaluate("polygon_perimeter", [i["value"] for i in pts]), "px", pts, operation="polygon_perimeter"))
            if not rings:
                return None
            steps += rings
            perim = evaluate("sum", [x["value"] for x in rings])
            if len(rings) > 1:
                steps.append(step(f"{sid}-perimeter", "Whole outline perimeter", "Σ ring perimeters", perim, "px",
                                  [input_value("ring", x["value"], "px", step_source(x["id"])) for x in rings], operation="sum"))
            pref = step_source(f"{sid}-perimeter" if len(rings) > 1 else rings[0]["id"])
            wall = step(sid, f"{it.item_id} run length", "outline perimeter ÷ 2 × metres per pixel",
                        evaluate("multiply", [perim, 0.5, r["m_per_px"]]), "m",
                        [input_value("outline perimeter", perim, "px", pref),
                         input_value("half (two faces of one thin wall)", 0.5, "factor",
                                     {"kind": "policy", "text": "A thin wall network's centreline run is half its outline perimeter (same relation as engine.wallarea)."}),
                         input_value("metres per pixel", r["m_per_px"], "m/px", _scale_ref(doc, it, r))], operation="multiply")
        if not close(wall["value"], r["total_m"], 1e-6):
            return None
        steps.append(wall)
        sums.append(input_value(it.item_id, wall["value"], "m", step_source(sid)))
        rw = row(doc, it, wall["value"], "m", kind="wall")
        rw["measured_by"] = sid
        rw["method"] = r["method"]
        out.append(rw)
    total = evaluate("sum", [i["value"] for i in sums])
    if not close(round(total, places(value)), value):
        return None
    steps.append(step("sum", "Add wall run lengths", " + ".join(f"{i['value']:.3f}" for i in sums), total, "m", sums, operation="sum"))
    steps.append(_result_steps(total, value, "sum"))
    return {"formula": "total = Σ(wall run length); run length = long side (straight wall) or outline perimeter ÷ 2 (network), × metres per pixel",
            "steps": steps, "rows": out, "checks": [], "margin": {}, "issues": [],
            "result": {"value": value, "unit": "m", "rounded_as": f"{places(value)} decimal places"},
            "row_key": "length_m", "row_total_step": "sum"}


def _sig(v: float) -> str:
    return f"{v:.4g}"


def _scale_text(sc: dict) -> tuple[str, bool]:
    from engine.scale_policy import LABEL
    m = sc.get("method") or "none"
    est = m == "door-prior" or float(sc.get("confidence") or 0) < 0.5
    if m == "door-prior":
        txt = "scale from door widths (no printed scale; median door symbol taken as 0.9 m)"
        if sc.get("spread_pct"):
            txt += f"; door symbols in this drawing differ by up to {sc['spread_pct']:.0f}% (observed spread, not a bound)"
    else:
        txt = "scale from " + LABEL.get(m, m.replace("_", " ")).lower()
    return txt, est


def answer(question, doc_ids, root, t0=None):
    import os
    mode = None if os.environ.get("WALLRUNS_OFF") else wants_wall_runs(question)
    if not mode or len(doc_ids) != 1:
        return None
    from engine.solvers.data import load_doc
    from engine.solvers.solve import _answer_obj, _evidence, _step, _fmt
    t0 = t0 or time.perf_counter()
    did = doc_ids[0]
    try:
        doc = load_doc(did, Path(root))
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if doc is None:
        return None
    if doc.mode == "ifc":
        return _ifc_answer(question, doc, doc_ids, root, t0, mode)
    if mode == "shortest":
        return None
    sc = doc.scale or {}
    mpp = sc.get("m_per_px")
    walls = [i for i in doc.items if i.kind == "wall"]
    if not walls:
        return None
    trace = [_step("route", f"wall runs / {mode} -> code, no model")]
    if not mpp or sc.get("method") in (None, "none"):
        res = _answer_obj(question, doc_ids, "This drawing has no scale I can trust, so wall lengths cannot be given in metres.",
                          None, None, 0.0, True, [], [], {"doc_id": did, "highlight_item_ids": [], "camera_target_item_id": None},
                          trace, "planmap", t0)
        return res
    rows = []
    for it in walls:
        r = item_runs(it, float(((it.props or {}).get("measurement_scale") or sc).get("m_per_px") or mpp))
        if r and r["runs"]:
            rows.append((it, r))
    if not rows:
        return None
    scale_txt, est = _scale_text(sc)
    tag = " (estimate)" if est else ""
    trace.append(_step("wall_runs", f"{len(rows)} wall components split into straight outline runs (>= {MIN_RUN_M} m)"))
    if mode == "total":
        total = sum(r["total_m"] for _, r in rows)
        items = [it for it, _ in rows]
        boxes, cites, scene = _evidence(doc, items)
        text = (f"The walls on this drawing add up to about **{_fmt(total, 'length')} m**{tag} over {len(rows)} wall components "
                f"(each component's run length: long side of a straight wall, half the outline perimeter for a connected network); "
                f"{scale_txt}. {''.join(f'[{c['n']}]' for c in cites)}")
        value, hl = round(total, 3), items
        trace.append(_step("sum", f"total run length = {total:.3f} m"))
        calc = total_calc(doc, rows, value)
        mpps = {round(r["m_per_px"], 12) for _, r in rows}
        sc_txt = f"{_sig(next(iter(mpps)))} m/px" if len(mpps) == 1 else "each view's own m/px"
        found = (f"{len(rows)} wall outlines; each wall's run length is its long side (straight wall) or half its outline "
                 f"perimeter (connected network).")
        measured = f"Run lengths in pixels × {sc_txt}, added over {len(rows)} walls = {_fmt(total, 'length')} m."
    else:
        pick = max if mode == "longest" else min
        cand = [(r_[0], it, r_, r) for it, r in rows for r_ in r["runs"]]
        length, it, run, r = pick(cand, key=lambda c: c[0])
        _, a, b = run
        pad = max(r["thick_px"], 2.0) / 2
        bbox = [round(min(a[0], b[0]) - pad, 1), round(min(a[1], b[1]) - pad, 1),
                round(max(a[0], b[0]) + pad, 1), round(max(a[1], b[1]) + pad, 1)]
        boxes, cites, scene = _evidence(doc, [it])
        if cites and cites[0].get("bbox_px") is not None:
            cites[0]["bbox_px"] = bbox
        for bx in boxes:
            bx["bbox_px"] = bbox
        word = "longest" if mode == "longest" else "shortest"
        text = (f"The {word} straight wall run is about **{_fmt(length, 'length')} m**{tag}, measured along the wall outline "
                f"({'one run of a connected wall network' if r['method'] == 'wall network outline' else 'a single straight wall'}); "
                f"{scale_txt}. [1]")
        value, hl = round(length, 3), [it]
        trace.append(_step(word, f"{word} run {length:.3f} m = {math.dist(a, b):.1f} px x {r['m_per_px']:.5f} m/px on {it.item_id}"))
        calc = longest_calc(doc, cand, (length, it, run, r), value) if mode == "longest" else None
        how = {"wall network outline": "one straight run of a connected wall outline", "centreline": "a straight run of the wall centreline",
               "rectangular outline": "the long side of a straight wall"}.get(r["method"], "a straight wall run")
        found = (f"{word.capitalize()} straight wall: {it.item_id}, {math.dist(a, b):,.0f} px long ({how}); the {word} of "
                 f"{len(cand)} straight runs of at least {MIN_RUN_M} m on {len(rows)} wall outlines.")
        measured = f"{it.item_id}: {math.dist(a, b):,.0f} px × {_sig(r['m_per_px'])} m/px = {_fmt(length, 'length')} m."
    conf = min(float(sc.get("confidence") or 0.3), 0.5) if est else min(float(sc.get("confidence") or 0.7), 0.9)
    scene["highlight_item_ids"] = [i.item_id for i in hl]
    scene["camera_target_item_id"] = hl[0].item_id
    scene["item_kinds"] = {i.item_id: "wall" for i in hl}
    res = _answer_obj(question, doc_ids, text, value, "m", conf, False, boxes, cites, scene, trace, "planmap", t0)
    if calc:   # exact operands, replayed by engine.calc.validate (F-CALC)
        from engine.calc import record
        record(res, calc)
    # Found names what was measured; Measured carries the arithmetic (engine.measure_why may replace it with
    # its Calculation line built from the same calc steps, and adds Source / Scale / How sure).
    res["reasoning_hint"] = {"steps": [{"kind": "found", "title": "Found", "text": found, "cite": 1, "ok": None},
                                       {"kind": "measured", "title": "Measured", "text": f"{measured} {scale_txt[0].upper()}{scale_txt[1:]}.",
                                        "cite": 1, "ok": None}],
                             "pct_cap": 50 if est else 90,
                             "reason": "Wall runs come from the detected wall outlines and a scale " + ("assumed from door widths." if est else "recorded for this drawing."),
                             "improve": "Print or enter a scale (or a known dimension) to turn this estimate into a measurement."}
    return res


def _ifc_answer(question, doc, doc_ids, root, t0, mode):
    """Model walls carry a stored length_m; report the longest (ties named) or the total, per storey when asked."""
    from engine.solvers.filters import storey_requested
    from engine.solvers.solve import _answer_obj, _evidence, _step, _fmt, resolve_storey
    did = doc_ids[0]
    # Totals and qualified walls (exterior, load-bearing...) belong to the existing quantity handlers.
    if mode not in ("longest", "shortest") or re.search(r"\b(?:exter\w+|inter\w+|outer|inner|load.?bearing|partition|fire|curved|hidden)\b", question, re.I):
        return None
    trace = [_step("route", f"wall lengths / {mode} -> stored wall quantities, code, no model")]
    storey = resolve_storey(question, doc.storeys)
    if storey_requested(question) and storey is None:
        return None
    walls = [(i, float(i.q["length_m"])) for i in doc.items
             if i.kind == "wall" and i.q.get("length_m") not in (None, 0) and float(i.q["length_m"]) > 0
             and (storey is None or i.storey == storey)]
    where = f" on {storey}" if storey else ""
    if not walls:
        return None
    if mode == "total":
        total = sum(v for _, v in walls)
        items = [i for i, _ in walls]
        boxes, cites, scene = _evidence(doc, items)
        text = (f"The **{len(walls)} walls**{where} add up to **{_fmt(total, 'length')} m** of stored wall length. "
                + "".join(f"[{c['n']}]" for c in cites))
        value, hl = round(total, 3), items
        trace.append(_step("sum", f"sum of length_m over {len(walls)} walls = {total:.3f} m"))
    else:
        top = (max if mode == "longest" else min)(v for _, v in walls)
        tied = sorted([(i, v) for i, v in walls if abs(v - top) <= top * 0.005], key=lambda iv: (iv[0].storey or "", iv[0].item_id))
        hl = [i for i, _ in tied][:12]
        boxes, cites, scene = _evidence(doc, hl)
        first = tied[0][0]
        name = first.label or first.name or first.item_id
        text = f"The {mode} wall{where} is **{_fmt(top, 'length')} m**: {name}" + (f" ({first.storey})" if first.storey else "") + "."
        if len(tied) > 1:
            levels = list(dict.fromkeys(i.storey for i, _ in tied if i.storey))
            text += (f" {len(tied)} walls share this length" + (f" across {', '.join(levels[:6])}" if levels else "")
                     + "; all are highlighted.")
        text += " " + "".join(f"[{c['n']}]" for c in cites)
        value = round(top, 3)
        trace.append(_step(mode, f"{'max' if mode == 'longest' else 'min'} length_m over {len(walls)} walls = {top:.3f} m; {len(tied)} within 0.5%"))
    scene["highlight_item_ids"] = [i.item_id for i in hl]
    scene["camera_target_item_id"] = hl[0].item_id
    scene["item_kinds"] = {i.item_id: "wall" for i in hl}
    res = _answer_obj(question, doc_ids, text, value, "m", 0.9, False, boxes, cites, scene, trace, "index", t0)
    return res
