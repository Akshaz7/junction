"""Exclusion clauses ("excluding the porch", "except the WC", "not the laundry closet") and overlapping room boxes.

One shared reading for area, order and take-off answers:
  split(question)            -> (scope question, exclusion text or None)
  excluded_rooms(text, rooms)-> (rooms to leave out, exclusion words that matched no room)
  union_total(have, ...)     -> area of the union of box-derived rooms (overlaps counted once), minus excluded boxes
"""
from __future__ import annotations

import re

EXCL = re.compile(r"(?:,\s*|\b)(?:excluding|exclude|excludes|except(?:\s+for)?|without|not\s+including|not\s+counting|other\s+than|apart\s+from|"
                  r"leaving\s+out|leave\s+out|ignoring|ignore|but\s+not|and\s+not|,\s*not(?=\s+the\b))\s+", re.I)

TERMS = {  # words in the exclusion clause -> room types / label words
    r"porch(?:es)?|veranda\w*|patio\w*|deck\w*|terrace\w*|balcon\w*|loggia\w*|outdoor|outside": ({"terrace", "balcony", "porch", "patio", "deck", "outdoor", "veranda"}, r"porch|veranda|patio|deck|terrace|balcon|loggia|outdoor"),
    r"laundry|utility|washing machine": ({"laundry", "utility"}, r"laundry|utility|washing"),
    r"wcs?|toilets?|water closets?": ({"wc", "toilet"}, r"\bwcs?\b|toilet|water closet"),
    r"bath ?rooms?|shower rooms?": ({"bathroom"}, r"bath|shower"),
    r"kitchen\w*": ({"kitchen"}, r"kitchen"),
    r"bed ?rooms?": ({"bedroom"}, r"bed ?room"),
    r"living ?rooms?|lounge": ({"living"}, r"living|lounge"),
    r"halls?|hallways?|corridors?|entry": ({"hall", "corridor", "hallway"}, r"hall|corridor|entry"),
    r"storage|store ?rooms?|closets?|pantr\w+": ({"storage", "closet", "pantry"}, r"storage|store|closet|pantr"),
    r"garages?|carports?": ({"garage"}, r"garage|carport"),
    r"offices?|studys?": ({"office", "study"}, r"office|study"),
}


def split(question: str):
    """(scope part, exclusion part). The exclusion part ends at the sentence end."""
    m = EXCL.search(question)
    if not m:
        return question, None
    tail = re.split(r"[.?!;]\s|[.?!]$", question[m.end():], maxsplit=1)[0]
    scope = question[:m.start()] + " " + question[m.end() + len(tail):]
    return scope.strip(), tail.strip() or None


def _room_words(room):
    return f"{room.label or ''} {room.name or ''}".casefold()


def excluded_rooms(text: str, rooms: list):
    """Rooms the clause names (by room type or printed label) and the clause words that matched no room."""
    out, unmatched = [], []
    for term_rx, (types, label_rx) in TERMS.items():
        word = re.search(rf"\b(?:{term_rx})\b", text or "", re.I)
        if not word:
            continue
        hit = [r for r in rooms if str((r.props or {}).get("room_type") or "").casefold() in types or re.search(label_rx, _room_words(r), re.I)]
        if hit:
            out += [r for r in hit if r not in out]
        else:
            unmatched.append(word.group(0))
    return out, unmatched


def _box(room):
    b = room.bbox_px
    return (float(b[0]), float(b[1]), float(b[2]), float(b[3])) if b and len(b) == 4 else None


def box_derived(room) -> bool:
    """Area came from the room's detection rectangle times the scale (no printed area, no outline)."""
    p = room.props or {}
    return p.get("area_m2_geom_bbox") is not None and p.get("area_m2_label") is None and not room.polygon_px and _box(room) is not None


def union_total(kept: list, excluded: list, mpp):
    """None when nothing overlaps; else {total, raw_sum, removed} with overlaps counted once and excluded boxes cut out."""
    if not mpp or not kept or not all(box_derived(r) for r in kept):
        return None
    from shapely.geometry import box
    from shapely.ops import unary_union
    boxes = [box(*_box(r)) for r in kept]
    cut = [box(*_box(r)) for r in excluded if box_derived(r)]
    raw = sum(b.area for b in boxes) * mpp * mpp
    area = unary_union(boxes)
    if cut:
        area = area.difference(unary_union(cut))
    total = area.area * mpp * mpp
    if raw - total < 0.005 * max(raw, 1e-9) and raw - total < 0.05:
        return None
    return {"total": total, "raw_sum": raw, "removed": raw - total}


def note(excluded: list, unmatched: list, text: str | None) -> str:
    parts = []
    if excluded:
        parts.append("Left out as asked: " + ", ".join(sorted({(r.label or str((r.props or {}).get("room_type") or "room")) for r in excluded})) + ".")
    if unmatched:
        parts.append(f"“{', '.join(unmatched)}” matched no room on this drawing, so nothing was left out for it.")
    return " ".join(parts)
