"""F9: the user supplies the numbers ("the kitchen is 3.2 x 4.1 m, what is its area"): compute from them.

Pure arithmetic, no model. If the question names a room the drawing has, the answer also says how the stated
rectangle compares with the drawing's own value; it never silently replaces the user's numbers with the cached area.
"""
from __future__ import annotations

import re
import time
import uuid

NUM = r"(\d+(?:[.,]\d+)?)"
UNIT = r"(mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|m|met(?:re|er)s?|ft|feet|foot)(?![a-z])"
PAIR = re.compile(rf"(?<![\d.,])(?:\b(?:is|are|measures?|of|be)\s+)?{NUM}\s*(?:{UNIT})?\s*(?:x|×|\*|by)\s*{NUM}\s*(?:{UNIT})?", re.I)
WANT = re.compile(r"\b(?:area|calculate|compute|multiply|square\s+met(?:re|er)s?|sq\.?\s*m)\b", re.I)
SKIP = re.compile(r"\b(?:how many|count|total|sum|all|each|every|volume|cubic|perimeter|cost|price|paint|tiles?|sheets?)\b", re.I)
FACTOR = {"mm": .001, "cm": .01, "m": 1., "ft": .3048}


def _factor(u, default="m"):
    u = (u or default).lower()
    return FACTOR["mm" if u == "mm" or u.startswith("mill") else "cm" if u == "cm" or u.startswith("cent") else "ft" if u in ("ft", "feet", "foot") else "m"]


def parse(question: str):
    if not WANT.search(question) or SKIP.search(question) or len(PAIR.findall(question)) != 1:
        return None
    m = PAIR.search(question)
    unit = m.group(4) or m.group(2)
    if not unit:
        tail = re.search(rf"{UNIT}", question[m.end():m.end() + 25], re.I)
        unit = tail.group(1) if tail else None
    f = _factor(unit)
    a, b = float(m.group(1).replace(",", ".")), float(m.group(3).replace(",", "."))
    if a <= 0 or b <= 0:
        return None
    return {"a": a * f, "b": b * f, "a_text": m.group(1), "b_text": m.group(3), "unit": unit or "m (assumed)", "factor": f}


def _drawing_area(question, doc_ids, root):
    """(item, area_m2, doc) of the room the question names, when exactly one and it has an area; else None."""
    try:
        from engine.solvers.data import load_doc
        from engine.solvers.filters import room_filter
        for did in doc_ids[:1]:
            doc = load_doc(did, root)
            rooms = [i for i in doc.items if i.kind == "room"]
            hit = room_filter(question, rooms)
            if hit and len(hit[1]) == 1 and hit[1][0].q.get("area_m2") is not None:
                return hit[1][0], float(hit[1][0].q["area_m2"]), doc
    except Exception:  # noqa: BLE001 - the comparison is a bonus; the arithmetic never depends on it
        return None
    return None


def answer(question, doc_ids, root):
    p = parse(question)
    if not p:
        return None
    t0 = time.perf_counter()
    area = p["a"] * p["b"]
    unit_note = "" if "assumed" not in p["unit"] else " No unit was given, so metres are assumed."
    text = f"**{area:.2f} m²** = {p['a']:g} m × {p['b']:g} m, using only the numbers you gave.{unit_note}"
    trace = [{"step": "user-arithmetic", "detail": f"area = {p['a']:g} x {p['b']:g} = {area:.4f} m2 from the question's own numbers; no drawing geometry or model", "ms": 0, "model": None, "cost_usd": 0}]
    cites, boxes, scene = [], [], {"doc_id": doc_ids[0] if doc_ids else "", "highlight_item_ids": [], "camera_target_item_id": None}
    ref = _drawing_area(question, doc_ids, root) if doc_ids else None
    if ref:
        item, drawn, doc = ref
        diff = (drawn - area) / area * 100
        text += (f" The drawing's own value for {item.label or 'this room'} is {drawn:.2f} m² ({diff:+.1f}% against your rectangle)"
                 + (" — a close match." if abs(diff) <= 5 else "; check which figure is right."))
        trace.append({"step": "compare", "detail": f"drawing value {drawn:.4f} m2 vs stated rectangle {area:.4f} m2 ({diff:+.2f}%)", "ms": 0, "model": None, "cost_usd": 0})
        from engine.solvers.solve import _evidence
        boxes, cites, scene = _evidence(doc, [item])
    return {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
            "answer": {"text_md": text, "value": round(area, 4), "unit": "m2", "confidence": 1.0, "abstained": False},
            "citations": cites, "evidence": {"boxes": boxes, "scene": scene}, "trace": trace, "route": "planmap" if ref else "index",
            "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000)}
