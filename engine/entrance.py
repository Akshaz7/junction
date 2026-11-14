"""FIX-4: which door is "the front door" / "the outer doors". Code only, cost 0.

IFC models: doors that engine.findings.exits_map counts as exits (outer doors by geometry; named ones first).
Plan maps (raster/DXF): a door whose box touches the outer extent of walls + windows + doors, within a margin.
Both are inferences from the data; callers say so. Never raises for a missing geometry, returns [].
"""
from __future__ import annotations

import re

from engine.solvers.data import Doc, Item

SINGLE = re.compile(r"\b(front|main|entrance|entry|street)\s+doors?\b|\b(?:the\s+)?entrance\b", re.I)
MANY = re.compile(r"\b(outer|outside|exterior|external|exit|outdoor)\s+doors?\b|\bdoors?\s+to\s+(?:the\s+)?outside\b", re.I)
NAMED = re.compile(r"exit|ausgang|notausgang|haupteingang|eingang|entrance|entry", re.I)
OUTDOOR_ROOMS = re.compile(r"balcon|terrace|patio|porch|garden|yard|outdoor", re.I)
MARGIN_FRAC = 0.03          # a door within 3 % of the content extent counts as on the outer edge
MARGIN_MIN_PX = 6.0


def is_entrance_phrase(question: str) -> bool:
    return bool(SINGLE.search(question) or MANY.search(question))


def wants_single(question: str) -> bool:
    return bool(SINGLE.search(question)) and not MANY.search(question)


def ifc_entrances(doc: Doc) -> list[Item]:
    from engine import findings
    out: list[Item] = []
    for ex in findings.exits_map(doc).values():
        out += [i for i in ex if i.kind == "door"]
    out.sort(key=lambda d: (not NAMED.search(f"{d.name or ''} {d.type_name or ''}"), d.storey != _ground(doc)))
    return out


def _ground(doc: Doc) -> str | None:
    st = sorted(doc.storeys, key=lambda s: abs(s.get("elevation_m", 0)))
    return st[0]["name"] if st else None


def planmap_entrances(doc: Doc) -> list[Item]:
    """Doors on the outer edge of the drawn content. Outdoor rooms (balcony, terrace) do not count as inside."""
    ref = [i for i in doc.items if i.kind in ("wall", "window", "door") and i.bbox_px]
    if len(ref) < 3:
        return []
    out: list[Item] = []
    for page in sorted({i.page for i in ref}):
        pr = [i for i in ref if i.page == page]
        x0, y0 = min(i.bbox_px[0] for i in pr), min(i.bbox_px[1] for i in pr)
        x1, y1 = max(i.bbox_px[2] for i in pr), max(i.bbox_px[3] for i in pr)
        mx, my = max(MARGIN_MIN_PX, MARGIN_FRAC * (x1 - x0)), max(MARGIN_MIN_PX, MARGIN_FRAC * (y1 - y0))
        for d in pr:
            if d.kind != "door":
                continue
            b = d.bbox_px
            if b[0] - x0 <= mx or x1 - b[2] <= mx or b[1] - y0 <= my or y1 - b[3] <= my:
                out.append(d)
    return out


def entrance_doors(doc: Doc) -> list[Item]:
    return ifc_entrances(doc) if doc.mode == "ifc" else planmap_entrances(doc)
