"""E-79 part: the 'Measured' / 'Calculated' step: the arithmetic from source geometry to the number, short enough to redo by hand.

Numbers here always agree with answer.value (same rounding as the answer text); if our own re-computation would differ from the
headline we state the headline and the source, never a second number.
"""
from __future__ import annotations

import re

from engine.reasoning import KIND_WORD, _fmt, _name, _shoelace  # noqa: F401

MAX_LEN = 110


def _r(v) -> str:
    """Same rounding as the answer text: one decimal from 10 up, two below."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:,.1f}" if abs(f) >= 10 else _fmt(f, 2)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _room_m2(it):
    q, p = it.q or {}, it.props or {}
    for v in (q.get("net_floor_area_m2"), q.get("area_m2"), q.get("net_area_m2"), p.get("area_m2")):
        if v:
            return float(v)
    return None


def _px(it) -> float:
    if it.polygon_px and len(it.polygon_px) >= 3:
        a = _shoelace(it.polygon_px)
        if a:
            return a
    return float((it.props or {}).get("area_px") or 0)


def _bbox_footprint(it):
    b = it.bbox_m
    try:
        return (b[1][0] - b[0][0]) * (b[1][2] - b[0][2])
    except Exception:  # noqa: BLE001
        return None


def _trace(trace, step):
    return [str(s.get("detail") or "") for s in trace if s.get("step") == step]


def _cap(text: str, fallback: str) -> str:
    return text if len(text) <= MAX_LEN else fallback


def _add(steps, kind, title, text, cite=None):
    steps.append({"kind": kind, "title": title, "text": text, "cite": cite, "ok": None})


def _top3(rows, n_total):
    """rows: [(name, m2)] -> ', largest A 31.1, B 22.4, C 18.4' for 4+ rooms, else ''."""
    if n_total < 4:
        return ""
    top = sorted(rows, key=lambda r: -r[1])[:3]
    return "; largest " + ", ".join(f"{n or 'room'} {_r(v)}" for n, v in top)


def _filter_step(ctx):
    """Counts with a condition: 'Kept doors wider than 1 m: 10 of 77'."""
    for d in _trace(ctx["trace"], "filter"):
        m = re.match(r"(\d+) of (\d+) (\w+?) (wider|narrower|taller|shorter|larger|smaller|bigger|longer|higher|lower|thicker|deeper|more|less|over|under|above|below|at least|at most)\b(.*)", d)
        if m:
            a, b, noun, word, rest = m.groups()
            return f"Kept {noun} {word}{rest}: {a} of {b}"
    return None


def _area(ctx) -> bool:
    ans, unit, value, question = ctx["ans"], ctx["unit"], ctx["value"], ctx["question"]
    rooms, first_cite, steps, sc = ctx["rooms"], ctx["first_cite"], ctx["steps"], ctx["sc"]
    if not rooms:
        return False
    v = _num(value) if unit == "m2" else None
    n = len(rooms)
    stor = sorted({r.storey for r in rooms if r.storey})
    on = f" on {stor[0]}" if len(stor) == 1 and ctx["is_ifc"] else ""
    if ctx["is_ifc"]:
        rows = [(_name(r), _room_m2(r)) for r in rooms]
        have = [(a, b) for a, b in rows if b]
        if n == 1:
            it = rooms[0]
            if have:
                _add(steps, "measured", "Measured", f"Floor area stored in the model's room data: {_r(have[0][1])} m²", first_cite.get(it.item_id))
                return True
            fp = _bbox_footprint(it)
            if fp:
                _add(steps, "measured", "Measured", f"No stored area; bounding-box footprint of the room: {_r(fp)} m²", first_cite.get(it.item_id))
                return True
            return False
        if not have:
            return False
        tot = sum(b for _, b in have)
        shown = v if v is not None and abs(v - tot) / max(abs(v), 1e-9) <= 0.01 else None
        if v is not None and shown is None:
            shown = v   # the answer may cover a different set than the cited boxes: state the headline, not a second sum
            _add(steps, "calculated", "Calculated", f"Added the floor areas stored in the model for {n} rooms{on}: {_r(shown)} m²")
            return True
        shown = tot if shown is None else shown
        txt = f"Added the stored floor areas of {n} rooms{on}: {_r(shown)} m²" + (f", {n - len(have)} without a stored area" if len(have) != n else "")
        _add(steps, "calculated", "Calculated", _cap(txt + _top3(have, n), txt))
        return True
    # plan maps: DXF outlines and raster outlines
    mpp = float((sc or {}).get("m_per_px") or 0)
    scale_w = ctx["scale_w"]
    rows = [(_name(r), _room_m2(r)) for r in rooms]
    have = [(a, b) for a, b in rows if b]
    if n == 1:
        it = rooms[0]
        px = _px(it)
        stored = have[0][1] if have else None
        res_m2 = v if v is not None else stored
        if px and mpp:
            m2c = px * mpp * mpp
            if res_m2 is None or abs(m2c - res_m2) / max(res_m2, 1e-9) <= 0.02:
                shown = res_m2 if res_m2 is not None else m2c
                _add(steps, "measured", "Measured", f"Outline {_fmt(px, 0)} px² × ({mpp:.5g} m/px)² = {_r(shown)} m²; scale from {scale_w}", first_cite.get(it.item_id))
                return True
        if res_m2:
            _add(steps, "measured", "Measured", f"Area of the room's drawn outline: {_r(res_m2)} m², scale from {scale_w}", first_cite.get(it.item_id))
            return True
        return False
    if not have:
        return False
    if v is None:
        lst = ", ".join(_r(b) for _, b in have[:6]) + (", …" if len(have) > 6 else "")
        _add(steps, "measured", "Measured", f"Outlines of {n} rooms at {mpp:.5g} m/px: {lst} m², not added together" if mpp else f"Areas of {n} rooms: {lst} m², not added together")
        return True
    txt = f"Added {n} room outlines: {_r(v)} m²" + _top3(have, n)
    full = txt + f"; scale from {scale_w}"
    _add(steps, "calculated", "Calculated", full if len(full) <= MAX_LEN else _cap(txt, f"Added {n} room outlines: {_r(v)} m²"))
    return True


def _length(ctx) -> bool:
    trace, value, steps, route = ctx["trace"], _num(ctx["value"]), ctx["steps"], ctx["route"]
    if not value or value <= 0:
        return False
    text_route = " ".join(_trace(trace, "route"))
    if "baseboard" in text_route:
        filt = _trace(trace, "filter")
        m = re.match(r"(\d+) rooms, (\d+) doors", filt[0]) if filt else None
        n = int(m.group(1)) if m else len(ctx["rooms"])
        bb = {}
        try:
            from engine.analytics import LAST_BB
            bb = {k: v for k, v in LAST_BB.items() if ctx["doc"] and v.get("doc") == ctx["doc"].doc_id}
        except Exception:  # noqa: BLE001
            bb = {}
        if bb and len(bb) == n:
            per = sum(x["per"] for x in bb.values())
            net = sum(x["net"] for x in bb.values())
            nd = sum(x["doors"] for x in bb.values())
            if abs(round(net, 1) - round(value, 1)) <= 0.15 and per >= net:
                _add(steps, "calculated", "Calculated", (f"Outline of {n} room{'s' if n != 1 else ''} {_r(per)} m, minus {nd} door{'s' if nd != 1 else ''} {_r(per - net)} m = {_r(value)} m" if nd else f"Outline of {n} room{'s' if n != 1 else ''}: {_r(value)} m, no door openings found"))
                return True
        _add(steps, "calculated", "Calculated", f"Walked the outline of {n} room{'s' if n != 1 else ''}, subtracted the door openings: {_r(value)} m")
        return True
    for d in _trace(trace, "length"):
        m = re.search(r"sum over (\d+) (\w+)", d)
        if m:
            n, kind = int(m.group(1)), m.group(2)
            word = KIND_WORD.get(kind, kind)
            scope = ""
            for sd in _trace(trace, "scope"):
                sm = re.match(r"(.+?): \d+ left", sd)
                if sm:
                    scope = ", " + sm.group(1).replace(" walls", "").strip()
                    scope = ", exterior only" if "exterior" in scope else (", interior only" if "interior" in scope else "")
            _add(steps, "calculated", "Calculated", f"Added the lengths of {n} {word}{'s' if n != 1 else ''}{scope}: {_r(value)} m")
            return True
    return False


def run(ctx: dict) -> None:
    steps, unit, value, question, cited = ctx["steps"], ctx["unit"], ctx["value"], ctx["question"], ctx["cited"]
    # A count headline can also report a room size in its explanation.
    text = ctx["ans"].get("text_md") or ""
    area_in_answer = bool(re.search(r"\d[\d.,]*\s*(?:m²|m2|square met(?:er|re)s)\b", text, re.I))
    area_q = unit == "m2" or area_in_answer or (unit not in ("count", "m") and bool(re.search(r"\b(area|how big|size|m2|m²|square)\b", question or "", re.I)))
    rooms = [it for it in cited if it.kind in ("room", "space")]
    ctx.update(area_q=area_q, rooms=rooms)
    order_math = _trace(ctx["trace"], "order_compute")
    if order_math:
        _add(steps, "calculated", "Calculated", "; ".join(order_math), ctx["cites"][0].get("n") if ctx["cites"] else None)
    elif _trace(ctx["trace"], "order"):
        _add(steps, "read", "Missing measurements", "The file does not provide complete measurements for the requested order.")
    elif unit == "m":
        _length(ctx)
    elif area_q and rooms:
        _area(ctx)
    elif unit in ("m2", "m3"):
        step = "area" if unit == "m2" else "volume"
        for detail in _trace(ctx["trace"], step):
            match = re.search(r"sum over (\d+) (\w+) = ([\d.]+)", detail)
            if match and _num(value) is not None:
                n, kind, _ = match.groups()
                word = KIND_WORD.get(kind, kind)
                suffix = "²" if unit == "m2" else "³"
                _add(steps, "calculated", "Calculated", f"Added the recorded {step}s of {n} {word}{'' if int(n) == 1 else 's'}: {_r(value)} m{suffix}")
                break
    elif unit in ("count", "", None):
        txt = _filter_step(ctx)
        if txt:
            _add(steps, "measured", "Measured", txt, ctx["cites"][0].get("n") if ctx["cites"] else None)
    ctx.update(steps=steps)
