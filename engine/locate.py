"""FIX-LOCATE: "where is the stair core / stairs / lift / entrance (on level N)" from IFC elements. Code only, cost 0.
Replaces a ~40 s reader call. Answers are inferences from element kinds, names and outer-door geometry; the text says so."""
from __future__ import annotations

import re
import time

from engine import entrance
from engine.exits import _numbered, _out
from engine.scene_cmds import tags
from engine.solvers.data import Doc, Item
from engine.solvers.solve import resolve_storey

ASK = re.compile(r"^\W*(?:please\s+)?(?:where(?:'s| is| are| can i find)?|find|locate|show(?: me)?|point (?:to|out)|which)\b", re.I)
THING = [
    ("lift", re.compile(r"\b(lifts?|elevators?|aufzug|aufz[uü]ge|hissi|fahrstuhl)\b", re.I)),
    ("stair core", re.compile(r"\b(stair ?cores?|stair ?wells?|stairwells?|staircase cores?|treppenhaus|porrashuone)\b", re.I)),
    ("stairs", re.compile(r"\b(stairs?|staircases?|stairways?|treppen?)\b", re.I)),
    ("entrance", re.compile(r"\b(entrances?|front doors?|main doors?|main entrance)\b", re.I)),
]
NAME = {"lift": re.compile(r"lift|aufzug|elevator|hissi|fahrstuhl", re.I), "stairs": re.compile(r"treppe|stair|porras", re.I)}


def thing(q: str) -> str | None:
    if not ASK.search(q) or re.search(r"\bhow many\b", q, re.I):
        return None
    for name, rx in THING:
        if rx.search(q):
            return name
    return None


def _match(doc: Doc, what: str) -> list[Item]:
    if what == "entrance":
        return entrance.ifc_entrances(doc)
    rx = NAME["lift" if what == "lift" else "stairs"]
    out = [i for i in doc.items if i.kind not in ("wall", "slab", "furniture") and not (i.kind == "door" and what != "lift")
           and (i.kind == "stairs" and what != "lift" or rx.search(f"{i.name or ''} {i.type_name or ''} {i.props.get('room_type') or ''}"))]
    return out


def locate_answer(question: str, doc: Doc, what: str, t0: float | None = None) -> dict:
    t0 = t0 or time.perf_counter()
    st = resolve_storey(question, doc.storeys) or _numbered(question, doc)
    items = [i for i in _match(doc, what) if i.bbox_m]
    if st:
        items = [i for i in items if i.storey == st]
    where = f"on **{st}**" if st else "in this model"
    if not items:
        text = (f"I found no {what} {where} in the model data (checked element kinds, names and, for entrances, outer doors), so I cannot point to one."
                if what != "lift" else f"No lift or elevator is modelled {where}: no element or space is named or typed as one.")
        return _out(question, doc, text, [], [], t0, abstained=what != "lift", trace_detail=f"{what}: none")
    tg = tags(doc)
    ids = [i.item_id for i in items]
    by: dict[str | None, list[Item]] = {}
    for i in items:
        by.setdefault(i.storey, []).append(i)
    order = {s["name"]: s.get("elevation_m", 0) for s in doc.storeys}
    parts = [f"{len(v)} on {k}" + (f" ({', '.join(tg.get(i.item_id, i.name or i.item_id) for i in v[:4])})" if len(v) <= 4 else "")
             for k, v in sorted(by.items(), key=lambda kv: order.get(kv[0], 0))]
    label = {"stair core": "stair core element", "stairs": "stair", "lift": "lift", "entrance": "entrance door"}[what] + ("s" if len(items) != 1 else "")
    text = f"**{len(items)} {label}** {where}: {'; '.join(parts)}. [1] Found from the model's elements" + \
           (" and outer-door geometry, an inference rather than a marked entrance." if what == "entrance" else ".")
    res = _out(question, doc, text, ids, [({i: tg[i] for i in ids if i in tg}, st)], t0, trace_detail=f"{what}: {len(items)} items")
    try:   # numbered boxes on the storey plans and one citation per page, same numbers as 3D / AR
        from engine.solvers.solve import _evidence
        boxes, cites, _scene = _evidence(doc, items)
        if boxes:
            res["evidence"]["boxes"], res["citations"] = boxes, cites
            res["answer"]["text_md"] = text.replace("[1]", "".join(f"[{c['n']}]" for c in cites), 1)
    except Exception:  # noqa: BLE001
        pass
    return res


# ---- plan maps: "where are the toilets / sinks / showers / bathtubs" (hard case cubicasa-toilet-locator). Code only.
FIXTURE_ASK = re.compile(r"^\W*(?:please\s+)?(?:where(?:'s| is| are| can i find)?|find|locate|show(?: me)?|point (?:to|out))\b", re.I)
FIXTURE = [("toilet", re.compile(r"\b(toilets?|wc|loos?|lavator(?:y|ies)|toilet bowls?)\b", re.I), "toilet"),
           ("sink", re.compile(r"\b(sinks?|wash ?basins?|basins?)\b", re.I), "sink"),
           ("shower", re.compile(r"\b(showers?)\b", re.I), "shower"),
           ("bathtub", re.compile(r"\b(bath ?tubs?|baths?)\b", re.I), "bathtub")]


def fixture_thing(q: str) -> str | None:
    if not FIXTURE_ASK.search(q) or re.search(r"\bhow many\b", q, re.I):
        return None
    for kind, rx, _ in FIXTURE:
        if rx.search(q):
            return kind
    return None


def _centre(i: Item):
    b = i.bbox_px
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None


def _inside(i: Item, r: Item) -> bool:
    c = _centre(i)
    b = r.bbox_px
    return bool(c and b and b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3])


def fixture_locate(question: str, doc: Doc, kind: str, t0: float | None = None) -> dict:
    t0 = t0 or time.perf_counter()
    from engine.solvers.solve import MIN_CONF, _evidence, _plural
    items = [i for i in doc.items if i.kind == kind and i.conf >= MIN_CONF and i.bbox_px]
    allb = [i.bbox_px for i in doc.items if i.bbox_px]
    if not items:
        text = (f"I found no {kind} in the plan map of this drawing (checked every detected element), so I cannot point to one. "
                "That does not prove there is none: it may not be drawn or detected.")
        r0 = _out(question, doc, text, [], [], t0, abstained=True, trace_detail=f"{kind}: none")
        r0["route"] = "planmap"
        return r0
    x0, y0 = min(b[0] for b in allb), min(b[1] for b in allb)
    x1, y1 = max(b[2] for b in allb), max(b[3] for b in allb)
    rooms = [r for r in doc.items if r.kind == "room" and r.bbox_px]
    items.sort(key=lambda i: (_centre(i)[1] // max(1.0, (y1 - y0) / 6), _centre(i)[0]))
    parts = []
    for k, i in enumerate(items[:8], 1):
        cx, cy = _centre(i)
        vert = "top" if cy < y0 + (y1 - y0) / 3 else "bottom" if cy > y0 + 2 * (y1 - y0) / 3 else "middle"
        hor = "left" if cx < x0 + (x1 - x0) / 3 else "right" if cx > x0 + 2 * (x1 - x0) / 3 else "centre"
        inn = sorted((r for r in rooms if _inside(i, r)), key=lambda r: (r.bbox_px[2] - r.bbox_px[0]) * (r.bbox_px[3] - r.bbox_px[1]))
        room = (inn[0].label or inn[0].props.get("room_type")) if inn else None
        parts.append(f"{k}: {vert}-{hor}" + (f", in the {room}" if room else ""))
    n = len(items)
    boxes, cites, scene = _evidence(doc, items)
    text = (f"**{n} {_plural(kind, n)}** on this floor plan, numbered on the drawing: " + "; ".join(parts) + ". "
            + "".join(f"[{c['n']}]" for c in cites) + " Positions are approximate.")
    res = _out(question, doc, text, [i.item_id for i in items], [], t0, trace_detail=f"{kind}: {n} detected on the plan map")
    res["evidence"]["boxes"], res["citations"], res["evidence"]["scene"] = boxes, cites, scene
    res["route"] = "planmap"
    return res
