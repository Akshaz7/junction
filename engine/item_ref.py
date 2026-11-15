"""'Tell me about door D5: its size and where it is.' -> that one item, by id, tag, label or its number.

The web's "Ask about this door" button names the item the way the panel labels it (D5, a tag, an id). This resolves
that reference to exactly one item and answers from its stored data: no planner, no model, one cited box.
"""
from __future__ import annotations

import re
import time

_ASK = re.compile(r"\btell me about\s+([a-z][a-z ]*?)\s+([A-Za-z0-9][\w.\-/ ]*?)\s*:\s*its size and where it is", re.I)


def _num(ref: str):
    m = re.fullmatch(r"[A-Za-z]{0,2}[\s\-_]*0*(\d+)", ref.strip())
    return int(m[1]) if m else None


def resolve(items, kind: str, ref: str):
    kind_l, ref_l = kind.casefold().strip(), ref.casefold().strip()
    same = [i for i in items if (i.kind or "").casefold() == kind_l]
    if not same:
        return []
    for key in (lambda i: i.item_id, lambda i: i.props.get("tag"), lambda i: i.label, lambda i: i.name):
        hit = [i for i in same if key(i) and str(key(i)).casefold() == ref_l]
        if hit:
            return hit
    n = _num(ref)
    if n is not None:
        hit = [i for i in same if re.search(rf"(?:^|[-_])0*{n}$", i.item_id)]
        if hit:
            return hit
    return []


def _center(i):
    b = i.bbox_px
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None


def _room_of(item, doc):
    c = _center(item)
    if not c:
        return None
    best = None
    for r in doc.items:
        if r.kind not in ("room", "space") or not r.bbox_px or r.page != item.page:
            continue
        b = r.bbox_px
        if b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3]:
            area = (b[2] - b[0]) * (b[3] - b[1])
            if best is None or area < best[0]:
                best = (area, r)
    return best[1] if best else None


def answer(question, doc_ids, root, t0=None):
    m = _ASK.search(question)
    if not m or len(doc_ids) != 1:
        return None
    from engine.solvers.data import load_doc
    from engine.solvers.solve import _answer_obj, _evidence, _step
    doc = load_doc(doc_ids[0], root)
    if doc is None:
        return None
    kind = re.sub(r"\s+", " ", m[1]).strip()
    kind = {"stair": "stairs"}.get(kind.lower(), kind)
    hit = resolve(doc.items, kind, m[2])
    if len(hit) != 1:
        return None
    it = hit[0]
    t0 = t0 or time.perf_counter()
    from engine.order import _number, _scale
    w = _number(it.props.get("width_m"), it.q.get("width_m"), it.props.get("width"))
    h = _number(it.props.get("height_m"), it.q.get("height_m"), it.props.get("height"))
    if w is None and it.bbox_px:
        s = _scale(doc, it, root)
        if s:
            w = max(it.bbox_px[2] - it.bbox_px[0], it.bbox_px[3] - it.bbox_px[1]) * s
    name = m[2].strip()
    parts = [f"**{kind.capitalize()} {name}** is one {kind} on page {it.page}."]
    parts.append(f"Width {w:.2f} m." if w else "Width is not stored for it.")
    parts.append(f"Height {h:.2f} m." if h else "Height is not drawn on this plan." if doc.mode == "planmap" else "Height is not stored for it.")
    room = _room_of(it, doc)
    where = []
    if room is not None:
        where.append(f"inside {room.label or room.name or room.item_id}")
    if it.storey:
        where.append(f"on {it.storey}")
    c = _center(it)
    if c and not where:
        where.append(f"at x {c[0]:.0f}, y {c[1]:.0f} px on the drawing")
    if where:
        parts.append("It is " + ", ".join(where) + ".")
    text = " ".join(parts) + " Read from the stored drawing data [1]."
    boxes_cites = _evidence(doc, [it])
    boxes, cites = boxes_cites[0], boxes_cites[1]
    trace = [_step("item", f"resolved {kind} {name} to {it.item_id}")]
    return _answer_obj(question, doc_ids, text, w, "m" if w else None, 0.9, False, boxes, cites,
                       {"doc_id": doc.doc_id, "highlight_item_ids": [it.item_id], "camera_target_item_id": it.item_id},
                       trace, "planmap", t0)
