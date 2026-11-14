"""Vision recount for plan-map counts that are often wrong on raster plans (CubiCasa: windows, doors, showers/baths, sinks, WCs, saunas).

recount(question, image) -> (n | None, cost_usd). One cheap vision call through call("recount"); the page image plus the dataset's own
question text, answer is a bare integer. Reconciliation with the plan-map count lives in engine.solvers (see `reconcile`).
"""
from __future__ import annotations

import os
from pathlib import Path

SCHEMA = {"type": "object", "required": ["count"], "additionalProperties": False, "properties": {"count": {"type": "integer", "minimum": 0}}}
HINTS = {
    "window": "Windows are thin double or triple lines set in an outer wall, or glazed wall segments; count each separate window opening once.",
    "door": "Doors are drawn with a swing arc or a door leaf in a wall gap; count doors with a leaf, not empty openings.",
    "toilet": "A toilet bowl is a small oval or keyhole shape with a cistern, usually in a WC or bathroom.",
    "sink": "Sinks and wash basins are small rectangles or ovals with a tap mark in kitchens and bathrooms; a double-bowl sink counts as one.",
    "shower_bathtub": "Count each bathtub (long rounded rectangle) and each shower tray (square with a drain or corner diagonal).",
    "sauna": "A sauna is a room labelled SAUNA (or S in Finnish plans), usually with benches drawn inside.",
}
PROMPT = ("You are looking at a floor plan. Count carefully, one object at a time, then answer the question.\n%s\n"
          "Question: %s\nReply JSON only: {\"count\": <integer>}.")


def recount(question: str, image: Path, kind: str | None = None) -> tuple[int | None, float, str]:
    """-> (count or None when no model is reachable, usd, model)."""
    try:
        from engine.models import call
        ov = os.environ.get("RECOUNT_ONLY", "")   # "provider|model": pin one model (calibration of stronger models)
        r = call("recount", [{"role": "user", "content": PROMPT % (HINTS.get(kind or "", ""), question)}], images=[Path(image)], schema=SCHEMA,
                 only=tuple(ov.split("|", 1)) if "|" in ov else None)
        n = (r.json or {}).get("count") if isinstance(r.json, dict) else None
        return (int(n) if isinstance(n, int) else None), r.cost_usd, r.model
    except Exception:  # noqa: BLE001  budget, network, no key: the caller keeps the plan-map count
        return None, 0.0, ""


# Reconciliation, picked on the 156 clean calibration drawings (results/recount_calib.json), never on held-out ones:
#   shower/bathtub: plan map 11.5 % vs vision 65.4 %  -> vision
#   window 31.4 -> min 35.9; door 33.3 -> min 37.8; sink 23.1 -> min 26.3; toilet 77.6 -> min 79.5 (vision alone is worse than the plan map)
KIND_OF = {"window": "window", "door": "door", "toilet": "toilet", "sink": "sink", "shower": "shower_bathtub", "bathtub": "shower_bathtub"}


def reconcile(kind: str, plan_n: int, vision_n: int | None) -> int:
    if vision_n is None:
        return plan_n
    return vision_n if KIND_OF.get(kind, kind) == "shower_bathtub" else min(plan_n, vision_n)


# ---------------------------------------------------------------- boxes (so a higher vision count can be drawn and verified)
BOX_SCHEMA = {"type": "object", "required": ["items"], "additionalProperties": False,
              "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["box"], "additionalProperties": False,
                                       "properties": {"box": {"type": "array", "items": {"type": "number"}}}}}}}
BOX_PROMPT = ("You are looking at a floor plan. Find every instance of the object described and give one bounding box per instance.\n%s\n"
              "Object: %s\nBoxes are [ymin, xmin, ymax, xmax], integers normalised to 0-1000 over the whole image. "
              "Tight boxes, one per object, no duplicates. Reply JSON only: {\"items\": [{\"box\": [ymin, xmin, ymax, xmax]}]}.")
NOUN = {"window": "windows", "door": "doors with a door leaf", "toilet": "toilet bowls", "sink": "sinks and wash basins",
        "shower_bathtub": "bathtubs and shower trays"}
# plausible size of one object as a fraction of the page's long side (min, max) per kind
SIZE = {"window": (0.01, 0.2), "door": (0.01, 0.15), "toilet": (0.01, 0.1), "sink": (0.008, 0.1), "shower_bathtub": (0.02, 0.25)}
BOX_MODEL = os.environ.get("RECOUNT_BOX_ONLY", "runware|google:gemini@3.5-flash")


def detect(image: Path, kind: str) -> tuple[list[list[int]] | None, float, str]:
    """-> (pixel boxes [x0,y0,x1,y1] that pass the size checks, usd, model); None when no model is reachable."""
    try:
        from PIL import Image as _I
        from engine.models import call
        w, h = _I.open(image).size
        ov = os.environ.get("RECOUNT_BOX_ONLY", BOX_MODEL)
        r = call("recount_boxes", [{"role": "user", "content": BOX_PROMPT % (HINTS.get(kind, ""), NOUN.get(kind, kind))}], images=[Path(image)],
                 schema=BOX_SCHEMA, only=tuple(ov.split("|", 1)) if "|" in ov else None)
    except Exception:  # noqa: BLE001
        return None, 0.0, ""
    lo, hi = SIZE.get(kind, (0.005, 0.3))
    out: list[list[int]] = []
    for it in (r.json or {}).get("items", []) if isinstance(r.json, dict) else []:
        b = it.get("box") or []
        if len(b) != 4:
            continue
        y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) for v in b]
        if y1 <= y0 or x1 <= x0:
            continue
        box = [int(x0 / 1000 * w), int(y0 / 1000 * h), int(x1 / 1000 * w), int(y1 / 1000 * h)]
        side = max(box[2] - box[0], box[3] - box[1]) / max(w, h)
        if lo <= side <= hi:
            out.append(box)
    return out, r.cost_usd, r.model


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def merge_boxes(plan: list[list[int]], new: list[list[int]]) -> list[list[int]]:
    """Keep every plan-map box, add each new box that does not overlap a kept one (IoU < 0.2 and centre outside)."""
    out = list(plan)
    for b in new:
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if any(_iou(b, k) >= 0.2 or (k[0] <= cx <= k[2] and k[1] <= cy <= k[3]) for k in out):
            continue
        out.append(b)
    return out
