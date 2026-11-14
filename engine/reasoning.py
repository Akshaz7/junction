"""E-79: "How we know" steps and a confidence label for every answer, built by code from what the answer already carries.

res["reasoning"] = {
  "steps": [{"kind": found|measured|checked|calculated|read, "title", "text", "cite": n|None, "ok": bool|None}],
  "confidence": {"label": "Verified"|"Cross-checked"|"Estimate", "pct": int, "reason": str, "improve": str|None},
}
Nothing here calls a model or invents a value: every number comes from the plan map / model data the answer cited,
from its trace, or from the answer object itself.
"""
from __future__ import annotations

import re
from pathlib import Path

KIND_WORD = {"door": "door", "window": "window", "room": "room", "wall": "wall", "toilet": "toilet", "sink": "sink",
             "bathtub": "bathtub", "shower": "shower", "stair": "staircase", "slab": "slab", "column": "column",
             "space": "room", "text": "label"}
SCALE_WORDS = {
    "printed-ratio": "the printed scale", "ratio": "the printed scale", "scale-bar": "the scale bar", "scalebar": "the scale bar",
    "printed-areas": "the printed room areas", "rooms-printed": "the printed room areas", "room-areas": "the printed room areas",
    "dimensions": "the printed dimensions", "door-prior": "door widths (about 0.9 m each)", "dxf_units_fit": "the CAD file's own units",
    "dxf": "the CAD file's own units", "pdf_vector": "the PDF's printed scale",
}


def _fmt(v, nd=2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{f:,.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _shoelace(poly) -> float:
    try:
        n = len(poly)
        return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2
    except Exception:  # noqa: BLE001
        return 0.0


def _scale_words(sc: dict | None) -> tuple[str, float]:
    sc = sc or {}
    m = str(sc.get("method") or "")
    for k, w in SCALE_WORDS.items():
        if k in m:
            return w, float(sc.get("confidence") or 0.5)
    return (m.replace("_", " ") or "an estimated scale"), float(sc.get("confidence") or 0.5)


def _name(it) -> str:
    lab = (it.label or it.name or "").strip()
    num = (it.props or {}).get("number")
    if lab and num and str(num) not in lab:
        lab = f"{lab} {num}"
    return lab


def build(res: dict, question: str, root: Path) -> dict | None:
    ans = res.get("answer") or {}
    if ans.get("abstained"):
        return None
    cites = res.get("citations") or []
    route = res.get("route")
    trace = res.get("trace") or []
    unit = (ans.get("unit") or "").replace("²", "2").replace("³", "3")
    value = ans.get("value")
    doc = None
    try:
        from engine.solvers.data import load_doc
        if res.get("doc_ids"):
            doc = load_doc(res["doc_ids"][0], root)
    except Exception:  # noqa: BLE001
        doc = None
    items = {i.item_id: i for i in (doc.items if doc else [])}
    cited = []
    first_cite = {}
    for c in cites:
        for iid in c.get("item_ids") or []:
            if iid in items and items[iid] not in cited:
                cited.append(items[iid])
                first_cite.setdefault(iid, c.get("n"))
    steps: list[dict] = []
    models_used = any(s.get("model") and s.get("step") not in ("explain", "context", "typos") for s in trace)
    is_ifc = bool(doc and doc.mode == "ifc")
    sc = doc.scale if doc else None
    scale_w, scale_c = _scale_words(sc)
    from_cad = bool(sc and "dxf" in str(sc.get("method") or ""))
    ctx = dict(res=res, question=question, ans=ans, cites=cites, route=route, trace=trace, unit=unit, value=value, doc=doc, items=items,
               cited=cited, first_cite=first_cite, models_used=models_used, is_ifc=is_ifc, sc=sc, scale_w=scale_w, scale_c=scale_c,
               from_cad=from_cad, steps=steps, checked=None, area_q=None, rooms=[])
    from engine.reasoning_parts import checked as _checked, confidence as _confidence, found as _found, measured as _measured
    for part in (_found, _measured, _checked):
        try:
            part.run(ctx)
        except Exception:  # noqa: BLE001 — one weak step never drops the others
            pass
    c = _confidence.run(ctx)
    steps = c.pop("_steps", ctx["steps"])
    hint = res.get("reasoning_hint")   # F-MEP: engine/mep.py supplies its own Found / Measured / Checked lines and an optional confidence cap
    if hint and hint.get("steps"):
        steps = list(hint["steps"])
        cap = hint.get("pct_cap")
        if cap and c.get("pct", 0) > cap:
            c["pct"] = cap
            c["label"] = "Cross-checked" if cap >= 80 else "Estimate"
            c["reason"] = hint.get("reason") or c.get("reason")
            c["improve"] = hint.get("improve") or c.get("improve")
    from engine.reasoning_parts.counts import enforce
    card = enforce(res, {"steps": steps[:4], "confidence": c}, question)
    return card if card["steps"] else None


def attach(res: dict, question: str, root: Path) -> dict:
    if res.get("reasoning"):   # these routes bring their own card; the invariant still applies
        from engine.reasoning_parts.counts import enforce
        res["reasoning"] = enforce(res, res["reasoning"], question)
        res.pop("reasoning_hint", None)
        return res
    try:
        r = build(res, question, root)
        if r:
            res["reasoning"] = r
        res.pop("reasoning_hint", None)
    except Exception:  # noqa: BLE001 — evidence is a convenience, never break the answer
        # A failed optional factor must not bypass count/evidence consistency.
        from engine.reasoning_parts.counts import enforce
        r = enforce(res, None, question)
        if r:
            res["reasoning"] = r
    return res
