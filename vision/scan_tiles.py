"""Native-resolution opening recovery, with ownership at tile seams.

Inference is sequential and bounded. Small plans retain their original pass.
Overlaps supply context; only a tile's central ownership region contributes
new objects, so two adjacent openings are never merged just for being close.
"""
from __future__ import annotations

import math


def regions(width, height, size=1024, overlap=0.2, max_tiles=16):
    if min(width, height, size) <= 0:
        return []
    nx, ny = math.ceil(width / size), math.ceil(height / size)
    if nx * ny > max_tiles:
        size = math.ceil(max(width, height) / math.sqrt(max_tiles))
        nx, ny = math.ceil(width / size), math.ceil(height / size)
        while nx * ny > max_tiles:
            size += 1
            nx, ny = math.ceil(width / size), math.ceil(height / size)
    out = []
    for j in range(ny):
        for i in range(nx):
            core = (i * width / nx, j * height / ny, (i + 1) * width / nx, (j + 1) * height / ny)
            dx, dy = (core[2] - core[0]) * overlap, (core[3] - core[1]) * overlap
            crop = (max(0, int(core[0] - dx)), max(0, int(core[1] - dy)),
                    min(width, math.ceil(core[2] + dx)), min(height, math.ceil(core[3] + dy)))
            out.append((crop, core))
    return out


def dedupe(items, iou=0.35, containment=0.8):
    """Drop repeated boxes, preserve the most confident one without box growth."""
    def area(b):
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])

    out = []
    for it in sorted(items, key=lambda i: -float(i.get("conf") or 0)):
        b = it["bbox_px"]
        duplicate = False
        for kept in out:
            if kept["kind"] != it["kind"]:
                continue
            a = kept["bbox_px"]
            inter = area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])
            if inter and (inter / max(1, area(a) + area(b) - inter) >= iou
                          or inter / max(1, min(area(a), area(b))) >= containment):
                duplicate = True
                break
        if not duplicate:
            out.append(it)
    return out


def opening_items(model, image):
    """Additional door/window items; confidence is still the model's probability.

    Tile size is the network input resolution, rather than a per-sheet threshold.
    Do not lower probability thresholds without spatial evidence from the head.
    """
    from vision.planmap import det_items

    width, height = image.size
    if max(width, height) <= model.size:
        return []
    out = []
    for crop, core in regions(width, height, model.size):
        tile = image.crop(crop)
        rooms, icons = model.maps(tile)
        for it in det_items(rooms, icons, model.icon_conf, *tile.size, model.size):
            if it["kind"] not in ("door", "window") or it["conf"] < 0.7:
                continue
            b = it["bbox_px"]
            b = [b[0] + crop[0], b[1] + crop[1], b[2] + crop[0], b[3] + crop[1]]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if not (core[0] <= cx < core[2] and core[1] <= cy < core[3]):
                continue
            # Truncated symbols are not complete evidence; the overview keeps them.
            if ((crop[0] > 0 and b[0] <= crop[0]) or (crop[1] > 0 and b[1] <= crop[1])
                    or (crop[2] < width and b[2] >= crop[2]) or (crop[3] < height and b[3] >= crop[3])):
                continue
            it = {**it, "bbox_px": b, "props": {**it["props"], "detection_pass": "native-tile"}}
            if it.get("polygon_px"):
                it["polygon_px"] = [[x + crop[0], y + crop[1]] for x, y in it["polygon_px"]]
            out.append(it)
    return dedupe(out)
