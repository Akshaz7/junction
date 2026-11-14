"""E-60: how many floor plans are drawn on one sheet (a scan or picture of a house often shows ground + upper floor side by side).

Two independent readings, no model call:
  layout   split the drawn structure (walls, rooms, doors, windows) by empty bands along x, then y (recursively). Each block
           that keeps a real share of the structure is one floor plan. A band must be wide against the block and against the
           sheet, so a courtyard, balcony or a gap inside one plan does not split it.
  labels   distinct floor names printed on the sheet ("1. KERROS", "2 KRS", "GROUND FLOOR", "UPPER FLOOR", "KELLARI", "BASEMENT").
Layout wins when it finds more than one block; labels decide only when the layout found a single block and the names are
consecutive floors from the ground up. Nothing is read from the document id."""
from __future__ import annotations

import re

STRUCT = {"wall", "room", "door", "window"}
MIN_BAND = 0.012          # empty band, as a share of the drawing extent along that axis (swept 0..0.045 on 700 plans: flat 0.004-0.015)
MIN_BLOCK_SHARE = 0.14    # a block must hold this share of the structure's footprint (ink) to be a floor plan
MIN_BLOCK_ITEMS = 6

_ORD = {"1": 1, "2": 2, "3": 3, "4": 4, "first": 2, "second": 3, "third": 4}
LABEL_RES = [
    (re.compile(r"\b([1-5])\s*\.?\s*(?:kerros|krs|kerr)\b", re.I), lambda m: int(m.group(1))),
    (re.compile(r"\b(?:alakerta|alakerr?os|ala-krs|ground\s*floor|gf)\b", re.I), lambda m: 1),
    (re.compile(r"\b(?:ylakerta|yläkerta|ylakerros|yläkerros|ylä-krs|upper\s*floor|first\s*floor|1st\s*floor)\b", re.I), lambda m: 2),
    (re.compile(r"\b(?:2nd|second)\s*floor\b", re.I), lambda m: 3),
    (re.compile(r"\b(?:kellari|kellarikerros|basement|cellar)\b", re.I), lambda m: 0),
    (re.compile(r"\b(?:vinttikerros|attic|loft)\b", re.I), lambda m: 9),
]


def _bands(boxes: list[list[float]], axis: int) -> list[tuple[float, float]]:
    """Empty intervals along an axis between merged item extents."""
    iv = sorted((b[axis], b[axis + 2]) for b in boxes)
    gaps, end = [], iv[0][1]
    for a, b in iv[1:]:
        if a > end:
            gaps.append((end, a))
        end = max(end, b)
    return gaps


def _split(boxes, extent, depth=0):
    """Recursively cut a block of boxes at its widest empty band; returns the leaf blocks."""
    if depth > 3 or len(boxes) < 2 * MIN_BLOCK_ITEMS:
        return [boxes]
    best = None
    for axis in (0, 1):
        for a, b in _bands(boxes, axis):
            if (b - a) >= MIN_BAND * extent[axis] and (best is None or (b - a) / extent[axis] > best[0]):
                best = ((b - a) / extent[axis], axis, (a + b) / 2)
    if best is None:
        return [boxes]
    _, axis, cut = best
    lo = [b for b in boxes if (b[axis] + b[axis + 2]) / 2 < cut]
    hi = [b for b in boxes if (b[axis] + b[axis + 2]) / 2 >= cut]
    if len(lo) < MIN_BLOCK_ITEMS or len(hi) < MIN_BLOCK_ITEMS:
        return [boxes]
    return _split(lo, extent, depth + 1) + _split(hi, extent, depth + 1)


def layout_blocks(items) -> list[dict]:
    """Floor-plan blocks on the sheet: [{bbox_px, n_items, share}] (largest first). Items are plan-map items (kind, bbox_px, conf)."""
    boxes = [list(map(float, it.bbox_px)) for it in items
             if it.kind in STRUCT and it.bbox_px and float(getattr(it, "conf", 1) or 0) >= 0.3]
    if len(boxes) < 2 * MIN_BLOCK_ITEMS:
        return []
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    extent = (max(x1 - x0, 1.0), max(y1 - y0, 1.0))
    leaves = _split(boxes, extent)

    def ink(bs):
        return sum(max(b[2] - b[0], 1) * max(b[3] - b[1], 1) for b in bs)
    tot = sum(ink(l) for l in leaves) or 1.0
    out = [{"bbox_px": [min(b[0] for b in l), min(b[1] for b in l), max(b[2] for b in l), max(b[3] for b in l)],
            "n_items": len(l), "share": ink(l) / tot} for l in leaves if len(l) >= MIN_BLOCK_ITEMS and ink(l) / tot >= MIN_BLOCK_SHARE]
    return sorted(out, key=lambda b: -b["share"])


def label_levels(texts) -> set[int]:
    lv = set()
    for t in texts:
        t = (t or "").strip()
        if not t or len(t) > 40:
            continue
        for rx, fn in LABEL_RES:
            m = rx.search(t)
            if m:
                lv.add(fn(m))
    return lv


def _stacked(lv: set[int]) -> bool:
    """Floor names that make a building: consecutive from the ground (or cellar) up. '3 / 4 / 5 KRS' on a plan is room numbering, not floors."""
    ls = sorted(x for x in lv if x != 9)
    return len(ls) >= 2 and ls[0] <= 1 and all(b - a == 1 for a, b in zip(ls, ls[1:]))


def count_storeys(items) -> dict:
    """{n, blocks, levels, basis}. n >= 1."""
    blocks = layout_blocks(items)
    lv = label_levels(getattr(it, "label", None) for it in items if it.kind == "text")
    n_layout = max(len(blocks), 1)
    n_label = len(lv)
    if len(blocks) >= 2:
        return {"n": len(blocks), "blocks": blocks, "levels": sorted(lv), "basis": "layout"}
    if n_label >= 2 and len(blocks) <= 1 and _stacked(lv):
        # labels for 2+ floors on a sheet whose structure did not split: trust the labels only when each floor name appears
        # (a lone "KELLARI" note on a one-floor plan is not a second plan)
        return {"n": len([x for x in lv if x != 9]), "blocks": blocks, "levels": sorted(lv), "basis": "labels"}
    return {"n": n_layout, "blocks": blocks, "levels": sorted(lv), "basis": "layout"}
