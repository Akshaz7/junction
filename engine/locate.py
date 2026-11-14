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
