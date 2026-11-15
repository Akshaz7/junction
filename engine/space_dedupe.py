"""F-MEPSPACES: one footprint, one room.

A model can hold architectural IfcSpaces and MEP/HVAC spaces or zones over the same footprint ("A101" and "A101-M",
"Foyer MEP Space"). Summing both double-counts the floor area. This module splits a space list into the spaces to count and
the ones to leave out, with a reason for each, so the answer can say what was excluded.
"""
from __future__ import annotations

import re

MEP_WORDS = re.compile(r"\b(?:mep|hvac|mechanical|ventilation|air[- ]?condition\w*|thermal|heating|cooling)\s+(?:spaces?|zones?)\b|\b(?:hvac|thermal|mep)\s+zones?\b", re.I)
OVERLAP = 0.9


def _fields(it):
    p = it.props or {}
    vals = [it.name, it.type_name, it.label, p.get("long_name"), p.get("object_type"), p.get("ObjectType"), p.get("classification"), p.get("predefined_type")]
    cl = p.get("classifications") or p.get("classification_refs")
    if isinstance(cl, (list, tuple)):
        vals += [str(c) for c in cl]
    return " ".join(str(v) for v in vals if v)


def is_mep_space(it) -> bool:
    return bool(MEP_WORDS.search(_fields(it)))


def _foot(it):
    b = it.bbox_m
    if not b or len(b) != 2:
        return None
    (x0, _, z0), (x1, _, z1) = b            # y up: the footprint is x/z
    return (min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1))


def _overlap(a, b) -> float:
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return iw * ih / small if small > 0 else 0.0


def _same_footprint(a, b) -> bool:
    f, g = _foot(a), _foot(b)
    if not f or not g or a.storey != b.storey or _overlap(f, g) <= OVERLAP:
        return False
    fa, ga = (f[2] - f[0]) * (f[3] - f[1]), (g[2] - g[0]) * (g[3] - g[1])
    return ga > 0 and 0.9 <= fa / ga <= 1 / 0.9


def split_spaces(rooms):
    """-> (kept, excluded) where excluded is [(item, reason)].

    Only an MEP/HVAC-marked space that duplicates an architectural room is left out: same storey, same footprint (>90%
    overlap, same size within 10%). An MEP space with no matching architectural footprint, and every architectural
    space, is kept, so distinct rooms that share or abut a footprint (a location plan) are never merged. A space with no
    geometry that is marked MEP is left out when architectural spaces exist. A pure MEP model keeps all its spaces."""
    arch = [r for r in rooms if not is_mep_space(r)]
    kept, excluded = [], []
    for r in rooms:
        if not is_mep_space(r) or not arch:
            kept.append(r)
            continue
        twin = next((a for a in arch if _same_footprint(r, a)), None)
        if twin is not None:
            excluded.append((r, f"marked as an MEP/HVAC space or zone; same footprint as {twin.name or twin.item_id}"))
        elif not _foot(r):
            excluded.append((r, "marked as an MEP/HVAC space or zone"))
        else:
            kept.append(r)
    return kept, excluded


def note(excluded) -> str:
    if not excluded:
        return ""
    names = ", ".join(str(r.name or r.item_id) for r, _ in excluded[:6]) + (" …" if len(excluded) > 6 else "")
    why = sorted({w.split(";")[0] for _, w in excluded})
    return (f" Not counted, so each footprint counts once: {len(excluded)} space(s) ({names}), "
            f"{'; '.join(why)}.")
