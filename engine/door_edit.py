"""FIRE F11: a proposed door-width change ("widen the Bathroom door from 760 mm to 900 mm") is a door what-if.

Pure code, no model, nothing persisted. It finds the one door asked about, highlights it, states the width the file
records, the proposed width and the difference, and says plainly what this preview does not model. It never claims
the result is code-compliant.
"""
from __future__ import annotations

import re

_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|m|met(?:re|er)s?)"
_VERB = r"(?:widen|broaden|enlarge|increase|expand|narrow|reduce|shrink|decrease|resize|change|make|set|alter|modify|adjust|propose|create|draft)"
_TO = re.compile(rf"\b(?:to|=|at)\s+{_NUM}\s*{_UNIT}\b", re.I)
_WIDE = re.compile(rf"{_NUM}\s*{_UNIT}\s+wide\b", re.I)
_FROM = re.compile(rf"\bfrom\s+{_NUM}\s*{_UNIT}\b", re.I)
_BY = re.compile(rf"\bby\s+{_NUM}\s*{_UNIT}\b", re.I)
_DOOR = re.compile(r"\b(?:doors?|doorways?|entrances?)\b|\bD\d+\b", re.I)
_EDIT = re.compile(rf"\b{_VERB}\b|\bwider\b|\bnarrower\b", re.I)
_QUERY = re.compile(r"^\W*(?:how many|what(?:'s| is| are)|which|list|count|is |are |does |do )", re.I)
_STOP = {"the", "a", "an", "this", "that", "door", "doors", "doorway", "of", "proposed", "change", "to", "widen", "narrow", "create", "make", "draft", "judge", "fire", "ifc"}


def _mm(num, unit):
    v = float(num.replace(",", "."))
    u = unit.lower()
    return v * (1000 if u.startswith("m") and not u.startswith("mm") and not u.startswith("mi") else 10 if u.startswith("c") else 1)


def parse(question: str):
    q = question.strip()
    if _QUERY.match(q) or not _DOOR.search(q) or not _EDIT.search(q):
        return None
    to, frm, by = _TO.search(q) or _WIDE.search(q), _FROM.search(q), _BY.search(q)
    if not (to or by):
        return None
    if re.search(r"\b(?:wall|window|room|stair|slab)s?\b", q, re.I) and not re.search(r"\bdoors?\b", q, re.I):
        return None
    out = {"from_mm": _mm(*frm.groups()) if frm else None}
    if to:
        out["to_mm"] = _mm(*to.groups())
    else:
        out["by_mm"] = _mm(*by.groups()) * (-1 if re.search(r"\b(?:narrow|reduce|shrink|decrease)\w*\b", q, re.I) else 1)
    out["words"] = _target_words(q)
    out["tag"] = (re.search(r"\b([Dd]\d+)\b", q) or [None, None])[1]
    return out


def _target_words(q):
    m = re.search(r"\b((?:[A-Za-z]+\s+){0,3})(?:doors?|doorways?)\b", re.sub(r"^\W*(?:judge-[\w-]+:\s*)", "", q), re.I)
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", m.group(1))] if m else []
    return [w for w in words if w not in _STOP and w not in {"widen", "narrow", "enlarge", "increase", "reduce", "make", "change", "resize", "proposed", "wider", "narrower", "from"}]


def _width_mm(it):
    v = (it.q or {}).get("width_m") or (it.props or {}).get("width_m")
    try:
        return float(v) * 1000 if v else None
    except (TypeError, ValueError):
        return None


def _blob(it, doc):
    parts = [it.name, it.label, it.type_name, str((it.props or {}).get("room_type") or "")]
    rid = (it.props or {}).get("room_id") or (it.props or {}).get("room_ids")
    rooms = {r.item_id: r for r in doc.items if r.kind in ("room", "space")}
    for r in ([rid] if isinstance(rid, str) else (rid or [])):
        if r in rooms:
            parts += [rooms[r].label, rooms[r].name]
    return " ".join(p for p in parts if p).lower()


def pick(doc, p):
    doors = [i for i in doc.items if i.kind == "door"]
    if p.get("tag"):
        from engine.scene_cmds import tags
        tg = tags(doc)
        return [i for i in doors if tg.get(i.item_id, "").upper() == p["tag"].upper()]
    if p["words"]:
        hit = [i for i in doors if all(w in _blob(i, doc) for w in p["words"])]
        if hit:
            return hit
        return [i for i in doors if any(w in _blob(i, doc) for w in p["words"])]
    return doors


def answer(question: str, doc, p, t0):
    from engine.solvers.solve import _answer_obj, _evidence, _step
    hit = pick(doc, p)
    trace = [_step("route", "proposed door-width change -> door what-if, code only, nothing saved")]
    scene0 = {"doc_id": doc.doc_id, "highlight_item_ids": [], "camera_target_item_id": None}
    lim = ("This is a preview only: the model is not edited and nothing is saved. A real change also needs the wall opening, frame, "
           "door swing and neighbouring walls to be adjusted, which this preview does not model. It makes no statement about code compliance; "
           "check the required width for this door in the applicable rules. To apply a change, use the Edit controls in the 3D view.")
    if len(hit) != 1:
        names = "; ".join(f"{(i.name or i.label or i.item_id)}" for i in hit[:6])
        text = ((f"**I could not tell which door you mean.** {len(hit)} doors match ({names}). Name one, for example by its tag." if hit
                 else "**I could not find that door in this file**, so no change was proposed.") + " " + lim)
        return _answer_obj(question, [doc.doc_id], text, None, "mm", 0.6, True, [], [], scene0, trace, doc.mode, t0)
    d = hit[0]
    cur = _width_mm(d)
    new = p.get("to_mm") if p.get("to_mm") is not None else (cur + p["by_mm"] if cur is not None else None)
    nm = d.name or d.label or "the door"
    lines = [f"**Proposed change to {nm}:** width {('%g' % round(cur)) + ' mm' if cur is not None else 'not recorded'} -> {('%g' % round(new)) + ' mm' if new is not None else 'unknown'}."]
    if cur is not None and new is not None:
        lines.append(f"That is {new - cur:+.0f} mm ({(new - cur) / cur * 100:+.0f}%) on the door leaf/opening width recorded in the file.")
    if p.get("from_mm") is not None and cur is not None and abs(p["from_mm"] - cur) > 5:
        lines.append(f"You said it is {p['from_mm']:.0f} mm now, but the file records {cur:.0f} mm; the file value is used.")
    if cur is None:
        lines.append("The file records no width for this door, so I cannot say how much it would change.")
    lines.append(lim)
    boxes, cites, scene = _evidence(doc, [d])
    text = " ".join(lines[:-1]) + "".join(f"[{c['n']}]" for c in cites) + "\n\n" + lines[-1]
    trace.append(_step("what-if", f"{nm}: {cur} mm -> {new} mm (preview, not saved)"))
    res = _answer_obj(question, [doc.doc_id], text, round(new) if new is not None else None, "mm", 0.9, False, boxes, cites, scene, trace, doc.mode, t0)
    res["evidence"]["scene"]["commands"] = []
    return res
