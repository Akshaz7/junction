"""Room candidates from connected interior regions, separated at wall openings.

Semantic labels describe a region; they do not create a new room boundary.
This avoids splitting one open room just because the classifier changes its mind.
"""
from __future__ import annotations

import cv2
import numpy as np

from vision.planmap import _components, _poly_off
from vision.rooms_scale import ROOM_CLASSES

DEFINITION = "Connected interior spaces separated by walls and closed door/window openings; open-plan zones count together."


def room_regions(rooms, confidence, openings):
    height, width = rooms.shape
    interior = np.isin(rooms, tuple(k for k in ROOM_CLASSES if k != 1)).astype(np.uint8)
    wall = (rooms == 2).astype(np.uint8)
    sizes = []
    for it in openings:
        if it["kind"] not in ("door", "window"):
            continue
        x0, y0, x1, y1 = [round(v) for v in it["bbox_px"]]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        if it["kind"] == "door":
            sizes.append(max(x1 - x0, y1 - y0))
        sub = wall[y0:y1, x0:x1]
        hs, vs = sub.sum(1), sub.sum(0)
        # Seal along the existing wall, rather than erasing the door's swing area.
        if hs.max() / max(1, x1 - x0) >= vs.max() / max(1, y1 - y0):
            if hs.max() >= .2 * (x1 - x0):
                y = y0 + int(hs.argmax())
                interior[max(0, y - 1):min(height, y + 2), x0:x1] = 0
        elif vs.max() >= .2 * (y1 - y0):
            x = x0 + int(vs.argmax())
            interior[y0:y1, max(0, x - 1):min(width, x + 2)] = 0
    # A room must have usable floor space, roughly a fraction of a door footprint.
    min_area = max(25, .3 * float(np.median(sizes)) ** 2) if sizes else max(25, .0005 * width * height)
    comps, labels = _components(interior, min_area)
    out = []
    for j, stat in comps:
        x, y, w, h = map(int, stat[:4])
        if x == 0 or y == 0 or x + w == width or y + h == height:
            continue
        mask = labels[y:y + h, x:x + w] == j
        if not mask.any():
            continue
        vals, counts = np.unique(rooms[y:y + h, x:x + w][mask], return_counts=True)
        cls = int(vals[counts.argmax()])
        typ = ROOM_CLASSES.get(cls, "undefined")
        out.append({"kind": "room", "label": None, "bbox_px": [x, y, x + w, y + h],
                    "polygon_px": _poly_off(mask, x, y), "source": "rule",
                    "conf": round(float(confidence[y:y + h, x:x + w][mask].mean()), 3),
                    "props": {"room_type": typ, "model_room_type": typ, "area_px": int(stat[4]), "area_m2": None,
                              "room_definition": DEFINITION, "boundary_method": "connected-interior"}})
    return out
