"""Plain display wording. Structural IDs and numeric tokens stay untouched.

Shared entry point for answer writers: plain(s: str) -> str.
"""
from __future__ import annotations

import re

_CLASSES = {
    "BuildingElementProxy": "building element", "BuildingElementPart": "building part",
    "FlowSegment": "service segment", "PipeSegment": "pipe segment", "DuctSegment": "duct segment",
    "CableCarrierSegment": "cable tray segment", "CableSegment": "cable segment",
    "FlowFitting": "service fitting", "PipeFitting": "pipe fitting", "DuctFitting": "duct fitting",
    "FlowTerminal": "service outlet", "WasteTerminal": "drain", "SanitaryTerminal": "sanitary fixture",
    "AirTerminal": "air outlet", "DistributionElement": "building service", "DistributionSystem": "service system",
    "WallStandardCase": "wall", "WallElementedCase": "wall", "DoorStandardCase": "door",
    "WindowStandardCase": "window", "Space": "room", "BuildingStorey": "floor",
    "StairFlight": "stair flight", "Stair": "staircase", "Slab": "slab", "Roof": "roof",
    "Wall": "wall", "Door": "door", "Window": "window", "Column": "column", "Beam": "beam",
    "Railing": "railing", "FurnishingElement": "furniture", "OpeningElement": "opening",
}
_IFC = re.compile(r"\bIfc([A-Za-z]+)\b", re.I)
_LOOKUP = {k.casefold(): v for k, v in _CLASSES.items()}
_TYPE = re.compile(r"\b((?:Basic|Generic|Compound|Stacked)[ _-]+(?:Wall|Floor|Roof)|"
                   r"(?:M[ _-]+)?(?:Single[ _-]+Flush|Double[ _-]+Flush)|"
                   r"(?:System[ _-]+Family|Family[ _-]+Type|Revit[ _-]+Type))\b(?!\s+door\b)", re.I)


def plain(s: str) -> str:
    """Translate technical names without deleting or changing any number."""
    def ifc(m):
        name = m.group(1)
        key = name.casefold()
        if key.endswith("type"):
            key = key[:-4]
        return _LOOKUP.get(key) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()

    def revit(m):
        t = re.sub(r"[ _-]+", " ", m.group()).lower()
        if "flush" in t:
            return "double flush door" if "double" in t else "single flush door"
        if t.endswith(("wall", "floor", "roof")):
            return t.split()[-1]
        return "type"

    out = _TYPE.sub(revit, _IFC.sub(ifc, str(s or "")))
    out = re.sub(r"\bDN\s*(\d+(?:[.,]\d+)?)\b", r"nominal diameter \1", out)
    return out


def apply(res: dict) -> dict:
    """Only display text is rewritten; source quotes and IDs remain verbatim."""
    ans = res.get("answer") or {}
    if isinstance(ans.get("text_md"), str):
        ans["text_md"] = plain(ans["text_md"])
    reasoning = res.get("reasoning") or {}
    for step in reasoning.get("steps") or []:
        for key in ("title", "text"):
            if isinstance(step.get(key), str):
                step[key] = plain(step[key])
    for key in ("reason", "improve"):
        conf = reasoning.get("confidence") or {}
        if isinstance(conf.get(key), str):
            conf[key] = plain(conf[key])
    for citation in res.get("citations") or []:
        if isinstance(citation.get("label"), str):
            citation["label"] = plain(citation["label"])
    return res


def headline(text: str) -> str:
    """Bold the opening answer sentence without changing facts or source markers."""
    if not text or text.lstrip().startswith(("**", "|", "#", "```", "- ")):
        return text
    first, newline, rest = text.partition("\n")
    # Numbered levels ("1. Obergeschoss") and decimal values contain periods
    # that are not sentence boundaries.
    parts = re.split(r"(?<!\d\.)(?<=[.!?])\s+|\s+(?=\[\d+\])", first, maxsplit=1)
    lead = parts[0].strip().replace("**", "")
    tail = (" " + parts[1]) if len(parts) == 2 else ""
    return "**" + lead + "**" + tail + newline + rest
