"""Printed/stated/written total area: quote it from the text layer with its box. No scale, no pixels, no model.

Falls through (returns None) when the page has no such printed total, or several different ones.
"""
from __future__ import annotations

import re
import time
import uuid

_ASK = re.compile(r"\b(?:printed|stated|written|listed|shown|labell?ed|noted|given|marked|schedule[sd]?)\b", re.I)
_TOTAL_AREA = re.compile(r"\b(?:total|gross|overall|sum)\b[^.?]{0,40}\barea\b|\barea\b[^.?]{0,40}\btotal\b|\bGFA\b", re.I)
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:[   ]\d{3})+|\d+)(?:\.\d+)?"
_UNIT = r"(㎡|m²|m2|sq\.?\s*m(?:et(?:re|er)s?)?\.?|sqm|sq\.?\s*f(?:ee|oo)?t\.?|sf|ft²)"
_KEY = r"(?:approx(?:imate|\.)?(?:\s+(?:total|floor))*(?:\s+area)?|計|合計|総計|total(?:\s+(?:gross|floor))?(?:\s+area)?|gross\s+floor\s+area|total\s+floor\s+area|GFA|summe|yhteens[aä]|totalt?)"
_LINE = re.compile(rf"(?:{_KEY})\s*[:=]?\s*({_NUM})\s*{_UNIT}", re.I)


_PAIR = re.compile(rf"\s*\(\s*({_NUM})\s*{_UNIT}\s*\)", re.I)
_AREA_UNIT = re.compile(rf"({_NUM})\s*{_UNIT}", re.I)
_ROOMS = r"(?:master\s+bed(?:room)?|bed(?:room)?\s*\d*|bath(?:room)?\s*\d*|living(?:\s+room)?|dining(?:\s+room)?|kitchen(?:ette)?|hall(?:way)?|corridor|toilet|wc|office|garage|study|laundry|utility|pantry|closet|lobby|store(?:room)?|balcony|terrace|studio|lounge|foyer|entry|stair(?:s|case)?|lift|room\s*\d+)"
_ROOM_ASK = re.compile(rf"\b(?:area|size|m²|square)\b[^.?]*\b({_ROOMS})\b|\b({_ROOMS})\b[^.?]*\b(?:area|size)\b", re.I)
_LEVEL = re.compile(r"\b(?:level|floor|storey|story)\s+([A-Z]{0,2}\d{1,2}[A-Z]?)\b|\bfor\s+([A-Z]{1,2}\d{1,2})\b|\b(\d{1,2}F|B\d{1,2}F?)\b", re.I)
_AREA_ASK = re.compile(r"\b(?:floor\s+)?area\b", re.I)


def level_of(question: str):
    m = _LEVEL.search(question)
    return next((g for g in m.groups() if g), None) if m else None


def wants_level(question: str) -> bool:
    return bool(level_of(question) and _AREA_ASK.search(question) and re.search(r"\b(?:schedule|listed|printed|stated|table|shown)\b", question, re.I)
                and not re.search(r"\b(?:estimate|measure|calculate|compute)\b", question, re.I))


def find_level(words, level: str):
    """[(value, unit, quote, bbox)] for printed rows whose label is the level and that carry an area."""
    out = []
    num = re.compile(rf"({_NUM})\s*{_UNIT}", re.I)
    for ws in _lines(words):
        text, spans = "", []
        for w in ws:
            spans.append((len(text), len(text) + len(w["text"]), w))
            text += w["text"] + " "
        if not re.search(rf"(?<![\w.]){re.escape(level)}(?![\w])", text, re.I):
            continue
        m = num.search(text)
        if not m:
            continue
        hit = [w for a, b, w in spans if a < m.end() and b > m.start()] + [w for a, b, w in spans if re.fullmatch(re.escape(level), w["text"], re.I)]
        bb = [min(w["bbox_px"][0] for w in hit), min(w["bbox_px"][1] for w in hit), max(w["bbox_px"][2] for w in hit), max(w["bbox_px"][3] for w in hit)]
        u = m[2].lower().replace(" ", "").replace(".", "")
        out.append((float(re.sub(r"[,\s\u00a0\u202f]", "", m[1])), "ft²" if re.match(r"sqf|sf$|ft", u) else "m²", text.strip(), bb))
    return out


def wants(question: str) -> bool:
    return bool(_ASK.search(question) and _TOTAL_AREA.search(question)
                and not re.search(r"\b(?:for|of)\s+(?:the\s+)?(?:level|storey|floor|room|unit|apartment)\b|\blevel\s+\w+\b", question, re.I)
                and not re.search(r"\b(?:estimate|measure|calculate|compute|from the (?:plan|pixels))\b", question, re.I))


def _lines(words):
    rows = sorted((w for w in words if w.get("bbox_px")), key=lambda w: (w["bbox_px"][1] + w["bbox_px"][3]) / 2)
    out = []
    for w in rows:
        b = w["bbox_px"]
        cy, h = (b[1] + b[3]) / 2, max(b[3] - b[1], 1)
        if out and abs(out[-1]["cy"] - cy) <= 0.6 * max(h, out[-1]["h"]):
            out[-1]["words"].append(w)
        else:
            out.append({"cy": cy, "h": h, "words": [w]})
    for ln in out:
        ln["words"].sort(key=lambda w: w["bbox_px"][0])
    return [ln["words"] for ln in out]


def find(words):
    """[(value, unit, quote, bbox)] for every 'total <number><unit>' printed in the words."""
    found = []
    for ws in _lines(words):
        text, spans = "", []
        for w in ws:
            spans.append((len(text), len(text) + len(w["text"]), w))
            text += w["text"] + " "
        for m in _LINE.finditer(text):
            hit = [w for a, b, w in spans if a < m.end() and b > m.start()]
            bb = [min(w["bbox_px"][0] for w in hit), min(w["bbox_px"][1] for w in hit),
                  max(w["bbox_px"][2] for w in hit), max(w["bbox_px"][3] for w in hit)]
            u = m[2].lower().replace(" ", "").replace(".", "")
            unit = "ft²" if re.match(r"sqf|sf$|ft", u) else "m²"
            value, quote = float(re.sub(r"[,\s\u00a0\u202f]", "", m[1])), m[0].strip()
            pair = _PAIR.match(text, m.end())    # "1295 sq. feet (120.31 sq. metres)": prefer the metric figure
            if pair and unit == "ft²" and not re.match(r"sqf|sf$|ft", pair[2].lower().replace(" ", "").replace(".", "")):
                value, unit, quote = float(re.sub(r"[,\s\u00a0\u202f]", "", pair[1])), "m²", (m[0] + pair[0]).strip()
                hit += [w for a, b, w in spans if a < pair.end() and b > pair.start()]
                bb = [min(w["bbox_px"][0] for w in hit), min(w["bbox_px"][1] for w in hit), max(w["bbox_px"][2] for w in hit), max(w["bbox_px"][3] for w in hit)]
            found.append((value, unit, quote, bb))
    return found


def answer(question, doc_ids, root, t0=None):
    level = level_of(question) if wants_level(question) else None
    room = room_of(question) if wants_room(question) else None
    if not level and not room and not wants(question):
        return None
    from engine.titleblock import _pages
    t0 = t0 or time.perf_counter()
    hits = []
    for did in doc_ids:
        for pt in _pages_any(did, root, question):
            for value, unit, quote, bbox in (find_room(pt.words, room) if room else find_level(pt.words, level) if level else find(pt.words)):
                hits.append((pt, value, unit, quote, bbox))
    if not hits or len({(v, u) for _, v, u, _, _ in hits}) != 1:
        return None
    pt, value, unit, quote, bbox = hits[0]
    n_pages = len({h[0].page for h in hits})
    what = (f"area printed for {room} on page {pt.page}" if room else f"area printed for {level.upper()} on page {pt.page}" if level
            else f"total area printed on page {pt.page}")
    text = f"**The {what} is {value:,.2f} {unit}.** Quoted from the drawing's text layer: “{quote}” [1]. No scale or pixel estimate was used."
    if room or not level:
        text += _cross_check(doc_ids, root, question, room, value, unit)
    if n_pages > 1:
        text += f" The same total is printed on {n_pages} pages."
    ms = int((time.perf_counter() - t0) * 1000)
    return dict(answer_id=uuid.uuid4().hex, question=question, doc_ids=list(doc_ids),
                answer=dict(text_md=text, value=value, unit=unit, confidence=.95, abstained=False),
                citations=[dict(n=1, doc_id=pt.doc_id, page=pt.page, kind="text", bbox_px=bbox, item_ids=[], quote=quote)],
                evidence=dict(boxes=[dict(item_id=f"printed-total-{pt.page}", page=pt.page, bbox_px=bbox, label="1")],
                              scene=dict(doc_id=pt.doc_id, highlight_item_ids=[], camera_target_item_id=None)),
                trace=[dict(step="printed_total", detail=f"quoted printed total from the {pt.source} on page {pt.page}", ms=ms, model=None, cost_usd=0)],
                route="index", cost=dict(usd_total=0.0, calls=[]), latency_ms=ms)


def room_of(question: str):
    m = _ROOM_ASK.search(question)
    return re.sub(r"\s+", " ", next(g for g in m.groups() if g)).strip() if m else None


def wants_room(question: str) -> bool:
    return bool(room_of(question) and _ASK.search(question) and re.search(r"\barea\b|\bsize\b", question, re.I)
                and not _TOTAL_AREA.search(question)
                and not re.search(r"\b(?:estimate|measure|calculate|compute|from the (?:plan|pixels))\b", question, re.I))


def find_room(words, room: str):
    """[(value, unit, quote, bbox)] for printed lines naming the room next to an AREA figure (m2/sq ft, never a bare length)."""
    out = []
    for ws in _lines(words):
        text, spans = "", []
        for w in ws:
            spans.append((len(text), len(text) + len(w["text"]), w))
            text += w["text"] + " "
        if not re.search(rf"(?<![\w]){re.escape(room)}(?![\w])", text, re.I):
            continue
        m = _AREA_UNIT.search(text)
        if not m:
            continue
        hit = [w for a, b, w in spans if a < m.end() and b > m.start()] + [w for a, b, w in spans if re.fullmatch(re.escape(room.split()[0]), w["text"], re.I)]
        bb = [min(w["bbox_px"][0] for w in hit), min(w["bbox_px"][1] for w in hit), max(w["bbox_px"][2] for w in hit), max(w["bbox_px"][3] for w in hit)]
        u = m[2].lower().replace(" ", "").replace(".", "")
        out.append((float(re.sub(r"[,\s\u00a0\u202f]", "", m[1])), "ft²" if re.match(r"sqf|sf$|ft", u) else "m²", text.strip(), bb))
    return out


from engine.titleblock import _pages as _pages_pdf  # noqa: E402


def _pages_any(did, root, question):
    """PDF text layer, else the OCR text of a raster (rtext), as page objects with .words/.page/.source/.doc_id."""
    got = list(_pages_pdf(did, root, question) or [])
    if got:
        return got
    import json
    from pathlib import Path
    from types import SimpleNamespace
    out = []
    for f in sorted(Path(root, did).glob("rtext-*.json")):
        try:
            t = json.loads(f.read_text())
            words = [x for x in t.get("words", []) if x.get("bbox_px")]
            if words:
                out.append(SimpleNamespace(doc_id=did, page=int(t.get("page") or 1), words=words, source=t.get("source") or "ocr"))
        except (OSError, ValueError, TypeError):
            continue
    return out


def _cross_check(doc_ids, root, question, room, printed, unit):
    """Computed geometry value for the cross-check line, or ''. Never replaces the printed figure."""
    try:
        from engine.order import _floor_area
        from engine.solvers.data import load_doc
        from engine.solvers.filters import room_filter
        doc = load_doc(doc_ids[0], root)
        if doc is None:
            return ""
        rooms = [i for i in doc.items if i.kind in ("room", "space")]
        if room:
            sel = room_filter(question, rooms)
            rooms = sel[1] if sel else []
        if not rooms:
            return ""
        areas = [_floor_area(r, doc, root) for r in rooms]
        if not areas or any(a is None for a in areas):
            return ""
        calc = sum(areas)
    except Exception:
        return ""
    if unit != "m²" or calc <= 0:
        return ""
    d = calc - printed
    return f" Cross-check only: the plan geometry gives {calc:,.2f} m², {d:+,.2f} m² ({d / printed * 100:+.1f}%) from the printed figure; the printed figure is the one quoted."
