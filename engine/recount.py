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
