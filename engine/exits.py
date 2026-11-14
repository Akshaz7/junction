"""E-13: exit finder for "where is the fire exit on level N". Code only, cost 0. IFC models.

A door is a candidate exit when it is an outer door: sampling a point 0.7 m off each face of the door (perpendicular
to its thin axis), at most one side lies inside a room of that storey. Doors or rooms named Exit / Ausgang / Notausgang
/ Haupteingang / Eingang rank first. Stairs on the storey are listed as ways to another level. The answer always says
it is an inference from the model data, not a marked fire exit. Elements are y-up; the plan is x/z.
"""
from __future__ import annotations

import re
import time
import uuid

from engine.scene_cmds import tags
from engine.solvers.data import Doc, Item
from engine.solvers.solve import resolve_storey

INTENT = re.compile(r"\b(fire[- ]?exits?|emergency exits?|escape (?:route|door|stairs?)|exits?|way out|notausgang|ausgang|evacuat\w*)\b", re.I)
WHERE = re.compile(r"\b(where|which|show|find|locate|point)\b", re.I)
NAMED = re.compile(r"exit|ausgang|notausgang|haupteingang|eingang|entrance", re.I)
STAIR_NAMED = re.compile(r"treppe|stair", re.I)
OFFSET_M = 0.7
INFERENCE = "This is an inference from the model data (outer doors and stairs), not a marked fire exit."


def is_exit_question(q: str) -> bool:
    return bool(INTENT.search(q)) and not re.match(r"\s*how many\b", q, re.I)


def _bbox(it: Item, boxes: dict[str, list]) -> list | None:
    return boxes.get(it.item_id)


def _inside(pt, box) -> bool:
    (x0, _, z0), (x1, _, z1) = box
    return x0 <= pt[0] <= x1 and z0 <= pt[1] <= z1


def outer_side_count(door_box, room_boxes) -> int | None:
    """How many of the two faces look into a room (0, 1, 2). None if no geometry."""
    if not door_box:
        return None
    (x0, _, z0), (x1, _, z1) = door_box
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    if (x1 - x0) >= (z1 - z0):          # door lies along x -> faces are +-z
        pts = [(cx, z0 - OFFSET_M), (cx, z1 + OFFSET_M)]
    else:
        pts = [(x0 - OFFSET_M, cz), (x1 + OFFSET_M, cz)]
    return sum(any(_inside(p, rb) for rb in room_boxes) for p in pts)


def find_exits(doc: Doc, storey: str, boxes: dict[str, list]) -> dict:
    doors = [i for i in doc.items if i.kind == "door" and i.storey == storey]
    rooms = [boxes[i.item_id] for i in doc.items if i.kind == "room" and i.storey == storey and i.item_id in boxes]
    named_rooms = [i for i in doc.items if i.kind == "room" and i.storey == storey and NAMED.search(f"{i.name or ''} {i.type_name or ''}")]
    outer, named = [], []
    for d in doors:
        side = outer_side_count(boxes.get(d.item_id), rooms) if rooms else None
        if NAMED.search(f"{d.name or ''} {d.type_name or ''}"):
            named.append(d)
        elif side is not None and side <= 1:
            outer.append(d)
    stairs = [i for i in doc.items if i.kind == "stairs" and i.storey == storey]
    return {"named": named, "outer": outer, "stairs": stairs, "named_rooms": named_rooms, "doors": len(doors), "rooms": len(rooms)}


def _numbered(q: str, doc: Doc) -> str | None:
    """"level 2": a storey whose name holds that number, else the Nth level above the ground level."""
    m = re.search(r"\b(?:level|floor|storey)\s+(-?\d+)\b", q, re.I)
    if not m or not doc.storeys:
        return None
    n = m.group(1)
    for s in doc.storeys:
        if re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", s["name"]):
            return s["name"]
    srt = sorted(doc.storeys, key=lambda s: s["elevation_m"])
    ground = next((i for i, s in enumerate(srt) if s["elevation_m"] >= -0.01), 0)
    i = ground + int(n)
    return srt[i]["name"] if 0 <= i < len(srt) else None


def exit_answer(question: str, doc: Doc, t0: float | None = None) -> dict:
    t0 = t0 or time.perf_counter()
    boxes = {i.item_id: i.bbox_m for i in doc.items if i.bbox_m}
    st = resolve_storey(question, doc.storeys) or _numbered(question, doc)
    if st is None and re.search(r"\b(top|attic)\b", question, re.I) and doc.storeys:
        st = max(doc.storeys, key=lambda s: s["elevation_m"])["name"]
    if st is None and len(doc.storeys) > 1:
        names = ", ".join(s["name"] for s in sorted(doc.storeys, key=lambda s: s["elevation_m"]))
        return _out(question, doc, f"Which level do you mean? This model has: {names}.", [], [], t0, abstained=True, trace_detail="no level named")
    st = st or (doc.storeys[0]["name"] if doc.storeys else None)
    tg = tags(doc)
    r = find_exits(doc, st, boxes)
    if not boxes:
        return _out(question, doc, "This model has no door positions I can use, so I cannot say where the exits are.", [], [], t0,
                    abstained=True, trace_detail="no geometry")
    ex = r["named"] + [d for d in r["outer"] if d not in r["named"]]
    ids = [d.item_id for d in ex] + [s.item_id for s in r["stairs"]]
    if not ids:
        return _out(question, doc, f"I found no outer doors or stairs on **{st}** in the model, so I cannot point to an exit. {INFERENCE}",
                    [], [], t0, abstained=True, trace_detail=f"{r['doors']} doors, none outer")
    parts = []
    if ex:
        names = ", ".join(tg.get(d.item_id, d.name or d.item_id) for d in ex[:8]) + (f" and {len(ex) - 8} more" if len(ex) > 8 else "")
        parts.append(f"**{len(ex)} outer door{'s' if len(ex) != 1 else ''} on {st}** ({names})")
    else:
        parts.append(f"**No outer door on {st}**")
    if r["stairs"]:
        parts.append(f"{len(r['stairs'])} stair{'s' if len(r['stairs']) != 1 else ''} to other levels ({', '.join(s.name or s.item_id for s in r['stairs'])})")
    text = "; ".join(parts) + ". [1] " + INFERENCE
    labels = {i: tg[i] for i in ids if i in tg}
    return _out(question, doc, text, ids, [(labels, st)], t0, trace_detail=f"{st}: {len(ex)} exit doors, {len(r['stairs'])} stairs from {r['doors']} doors / {r['rooms']} rooms")


def _label(doc, ids) -> str:
    from engine.solvers.solve import _cite_label
    its = [i for i in doc.items if i.item_id in set(ids)]
    base = _cite_label(doc, its, 1)
    doors = sum(1 for i in its if i.kind == "door")
    stairs = sum(1 for i in its if i.kind == "stairs")
    if doors or stairs:
        head = base.split(" · ", 1)[0]
        bits = ([f"{doors} exit door{'s' if doors != 1 else ''}"] if doors else []) + ([f"{stairs} staircase{'s' if stairs != 1 else ''}"] if stairs else [])
        return f"{head} · " + ", ".join(bits)
    return base


def _out(question, doc, text, ids, extra, t0, abstained=False, trace_detail=""):
    cmd = {"op": "highlight", "item_ids": ids}
    if extra:
        cmd["labels"] = extra[0][0]
    scene = {"doc_id": doc.doc_id, "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None, "commands": [cmd] if ids else []}
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc.doc_id],
        "answer": {"text_md": text, "value": len(ids) if ids else None, "unit": None, "confidence": 0.0 if abstained else 0.7, "abstained": abstained},
        "citations": [{"n": 1, "doc_id": doc.doc_id, "page": 1, "kind": "element", "bbox_px": None, "item_ids": ids, "quote": None, "label": _label(doc, ids)}] if ids else [],
        "evidence": {"boxes": [], "scene": scene},
        "trace": [{"step": "exits", "detail": trace_detail, "ms": 0, "model": None, "cost_usd": 0}],
        "route": "index", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
