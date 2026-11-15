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
        return {"runs": runs, "total_m": total, "thick_px": 0.0, "method": "centreline"} if runs else None
    pts = it.polygon_px
    if not pts and it.bbox_px:
        x0, y0, x1, y1 = it.bbox_px
        pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    if not pts or len(pts) < 3:
        return None
    ring = [(float(x), float(y)) for x, y in pts]
    poly = Polygon(ring)
    if not poly.is_valid:
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
        return {"runs": runs, "total_m": max(sides) * mpp, "thick_px": min(sides), "method": "rectangular outline"}
    runs = [(l * mpp, a, b) for l, a, b in chains if l * mpp >= MIN_RUN_M]
    # Both faces of a thin wall give a run each; the longer one is within a wall thickness of the other.
    return {"runs": runs, "total_m": poly.length * mpp / 2, "thick_px": thick_px, "method": "wall network outline"}


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
        trace.append(_step(word, f"{word} run {length:.3f} m = {math.dist(a, b):.1f} px x {mpp:.5f} m/px on {it.item_id}"))
    conf = min(float(sc.get("confidence") or 0.3), 0.5) if est else min(float(sc.get("confidence") or 0.7), 0.9)
    scene["highlight_item_ids"] = [i.item_id for i in hl]
    scene["camera_target_item_id"] = hl[0].item_id
    scene["item_kinds"] = {i.item_id: "wall" for i in hl}
    res = _answer_obj(question, doc_ids, text, value, "m", conf, False, boxes, cites, scene, trace, "planmap", t0)
    res["reasoning_hint"] = {"steps": [{"kind": "measured", "title": "Measured", "text": f"{value} m from wall outline runs; {scale_txt}",
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
