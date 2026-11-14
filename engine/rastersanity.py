"""E-61: plausibility guard and plain 'what was found' note for raster/PDF plan maps (uploads and web plans).

A scale guessed from door icons can make a closet 0.8 m2 or a flat 3,000 m2. When the answer is an area from such a scale and
the numbers are implausible, say 'the scale looks wrong' instead of stating them. On sparse uploaded plans, say plainly what
the reader found and how."""
from __future__ import annotations
import re

MIN_ROOM_M2 = 1.5
MAX_PLAN_M2 = 2000.0
SPARSE_ROOMS = 3
Q_COUNT = re.compile(r"\bhow many\b.*\b(rooms?|doors?|windows?|toilets?|bedrooms?|bathrooms?)\b|\b(largest|biggest|smallest|total)\b.*\b(room|area)\b|\barea\b", re.I)


def _guessed_scale(doc) -> bool:
    sc = doc.scale or {}
    return sc.get("method") == "door-prior" or (bool(sc.get("m_per_px")) and float(sc.get("confidence") or 0) < 0.5)


def _area(it) -> float | None:
    for k in ("net_floor_area_m2", "area_m2", "net_area_m2"):
        if it.q.get(k) is not None:
            return float(it.q[k])
    return None


def scale_problem(doc, res: dict) -> str | None:
    """-> why the area looks wrong, or None."""
    if doc.mode != "planmap" or not _guessed_scale(doc):
        return None
    ans = res.get("answer") or {}
    if ans.get("unit") != "m2" or ans.get("abstained") or ans.get("value") is None:
        return None
    rooms = [i for i in doc.items if i.kind == "room" and _area(i) is not None]
    total = sum(_area(i) for i in rooms)
    ids = set(((res.get("evidence") or {}).get("scene") or {}).get("highlight_item_ids") or [])
    shown = [_area(i) for i in rooms if i.item_id in ids]
    v = float(ans["value"])
    if total > MAX_PLAN_M2 or v > MAX_PLAN_M2:
        return f"it would make the whole plan about {max(total, v):,.0f} m²"
    tiny = [a for a in shown if a < MIN_ROOM_M2]
    if len(shown) <= 1 and 0 < v < MIN_ROOM_M2:
        tiny = [v]
    elif len(tiny) < max(2, len(shown) / 2):      # a few closets in a list are normal; half the rooms tiny is a scale problem
        tiny = []
    if tiny:
        return f"it would make a room only {min(tiny):.1f} m²"
    return None


def _try(doc) -> str:
    """What the user can ask on this drawing that works, from what the reader actually found."""
    labels = [str(i.label) for i in doc.items if i.kind == "room" and i.label and len(str(i.label)) > 2]
    ex = ["how many rooms are there"]
    if labels:
        ex += [f"where is the {labels[0].lower()}", f"area of the {labels[0].lower()}"]
    else:
        ex += ["where are the doors", "how many windows"]
    return "Try: " + ", ".join(ex) + "."


CAVEAT = "Areas are estimated from door sizes because no printed scale was found, so treat them as approximate."
ROOMWORD = re.compile(r"kitchen|bed ?room|bath|living|dining|hall|closet|office|\bwc\b|garage|laundry|toilet|lounge|study|utility|pantry|foyer|balcon", re.I)


def _undercounted(doc) -> bool:
    """More room-like words printed on the drawing than rooms the reader found."""
    words = sum(1 for i in doc.items if i.kind == "text" and ROOMWORD.search(str(i.label or i.props.get("text") or "")))
    return words >= 3 and words > sum(1 for i in doc.items if i.kind == "room") + 1


def sparse_note(doc, question: str, res: dict) -> str | None:
    if doc.mode != "planmap" or not doc.doc_id.startswith("uploads__") or not Q_COUNT.search(question):
        return None
    n = lambda k: sum(1 for i in doc.items if i.kind == k)
    rooms, doors, wins = n("room"), n("door"), n("window")
    if rooms >= SPARSE_ROOMS and doors + wins >= 3 and not _undercounted(doc):
        return None
    return (f"On this drawing the automatic reader found {rooms} room{'s' if rooms != 1 else ''}, {doors} door{'s' if doors != 1 else ''} "
            f"and {wins} window{'s' if wins != 1 else ''}. It reads the image, and a sparse or unusual plan can be missed, so treat these as what was found, not a full count. {_try(doc)}")


def guard(res: dict, question: str, doc) -> dict:
    ans = res.get("answer") or {}
    why = scale_problem(doc, res)
    if why:
        ans.update({"text_md": f"**The scale looks wrong for this plan, so I won't state an area.** The drawing has no printed scale and the size was guessed from door icons; {why}. "
                               "Add a scale (a drawn dimension or a note like “1:100”) and ask again. Room names, doors and windows are still counted from the drawing.",
                    "value": None, "confidence": 0.3, "abstained": False})
        res["trace"] = list(res.get("trace") or []) + [{"step": "sanity", "detail": f"area withheld: {why}", "ms": 0, "model": None, "cost_usd": 0}]
        return res
    if doc.mode == "planmap" and _guessed_scale(doc) and not ans.get("abstained") and ("m²" in ans.get("text_md", "") or " m2 |" in ans.get("text_md", "")):
        t = ans["text_md"].rstrip()
        for old in (" This is approximate: the drawing has no printed scale, so the size is estimated from the doors.",
                    " The drawing has no printed scale, so areas are estimated from door sizes and are approximate."):
            t = t.replace(old, "")
        ans["text_md"] = f"{t.rstrip()}\n\n{CAVEAT}" if "estimated from door sizes" not in t else t
        ans["confidence"] = min(float(ans.get("confidence") or 0.4), 0.4)
    note = sparse_note(doc, question, res)
    if note and not ans.get("abstained") and note not in ans.get("text_md", ""):
        ans["text_md"] = f"{ans.get('text_md', '').rstrip()}\n\n{note}"
    return res
