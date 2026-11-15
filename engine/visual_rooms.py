"""Visual evidence for room classes absent from the plan-map classifier.

A count alone is insufficient: the independent localisation must agree and
provide one source box per room. Otherwise the tool reader still gets a turn.
"""
from __future__ import annotations

import os
from pathlib import Path


def answer(question, doc_ids, root, trace, calls, t0, *, hidden=()):
    if os.environ.get("MODELS_FAKE") or os.environ.get("RECOUNT", "1") == "0" or hidden or len(doc_ids) != 1:
        return None
    from engine.router.parser import parse
    from engine.solvers.solve import room_subtype, _answer_obj, _evidence
    from engine.answer import _step
    from engine.solvers.data import Item, load_doc
    p = parse(question)
    subtype = room_subtype(question)
    if p.type != "count" or p.kind != "room" or subtype is None:
        return None
    doc = load_doc(doc_ids[0], root)
    if doc is None or doc.mode != "planmap":
        return None
    # Multi-page scopes require the tool reader, rather than silently counting
    # the first sheet. An edit layer likewise must not resurrect hidden rooms.
    image = Path(root) / doc.doc_id / "page-1.png"
    if doc.pages != 1 or not image.is_file():
        return None
    from engine.recount import recount, detect
    name = subtype[0]
    count, usd, model = recount(question, image, name)
    calls.append({"task": "recount", "provider": "vision", "model": model, "cost_usd": usd})
    trace.append(_step("visual_rooms", f"Visual check for {name} labels and room symbols", model=model, cost=usd))
    if count is None or count <= 0 or "fake" in model:
        return None
    boxes, usd, model = detect(image, name)
    calls.append({"task": "recount_boxes", "provider": "vision", "model": model, "cost_usd": usd})
    if boxes is None or len(boxes) != count or "fake" in model:
        trace.append(_step("visual_rooms", "Visual count could not be matched to one source box per room", model=model, cost=usd))
        return None
    from engine.recount import merge_boxes
    if len(merge_boxes([], boxes)) != count:
        return None
    items = [Item(f"visual-room-{n}", "room", label=name, page=1, bbox_px=bb,
                  props={"room_type": name}, conf=.5, source="vlm") for n, bb in enumerate(boxes, 1)]
    marked, cites, scene = _evidence(doc, items)
    text = (f"**{count} {name if count == 1 else name + 's'} identified on this drawing.** [1] "
            "Read from the room labels and symbols; check the numbered regions.")
    trace.append(_step("visual_rooms", f"Visual count {count} agrees with {len(boxes)} source regions", model=model, cost=usd))
    res = _answer_obj(question, doc_ids, text, count, "count", .5, False,
                      marked, cites, scene, trace, "hybrid", t0)
    res["cost"] = {"usd_total": round(sum(c.get("cost_usd", 0) for c in calls), 6), "calls": calls}
    return res
