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


def split_spaces(rooms):
    """-> (kept, excluded) where excluded is [(item, reason)]. MEP/HVAC-marked spaces go first; then a space whose footprint is
    more than 90% inside an already-kept space on the same storey (nested or duplicate) goes, but only when both footprints
    are the same size within 10% (a duplicate), so a small room inside a big hall is never dropped."""
    kept, excluded = [], []
    arch = [r for r in rooms if not is_mep_space(r)]
    for r in rooms:
        if is_mep_space(r):
            if arch:
                excluded.append((r, "marked as an MEP/HVAC space or zone"))
            else:
                kept.append(r)       # a pure MEP model: its spaces are all there is, keep them
        else:
            kept.append(r)
    out = []
    for r in sorted(kept, key=lambda i: str(i.item_id)):
        f = _foot(r)
        dup = None
        if f:
            for k in out:
                g = _foot(k)
                if g and k.storey == r.storey and _overlap(f, g) > OVERLAP:
                    fa, ga = (f[2] - f[0]) * (f[3] - f[1]), (g[2] - g[0]) * (g[3] - g[1])
                    if ga > 0 and 0.9 <= fa / ga <= 1 / 0.9:
                        dup = k
                        break
        if dup is not None:
            excluded.append((r, f"same footprint as {dup.name or dup.item_id}"))
        else:
            out.append(r)
    keep_ids = {i.item_id for i in out}
    return [r for r in rooms if r.item_id in keep_ids], excluded


def note(excluded) -> str:
    if not excluded:
        return ""
    names = ", ".join(str(r.name or r.item_id) for r, _ in excluded[:6]) + (" …" if len(excluded) > 6 else "")
    why = sorted({w.split(" as ")[0] if w.startswith("same") else w for _, w in excluded})
    return (f" Not counted, so each footprint counts once: {len(excluded)} space(s) ({names}), "
            f"{'; '.join(why)}.")
