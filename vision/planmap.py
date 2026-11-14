"""Raster plan -> plan map (CONTRACT 5.4).

V-01: walls/doors/windows from the UNet masks (source "seg").
V-02: fixtures (+ doors/windows) from the official CubiCasa5K icon heads (source "det").
Merge rule (see docs in report): walls = seg; doors/windows/toilets/sinks/bathtubs = det; seg doors/windows are
kept only in planmap-seg.json (they over-count: fragments + swing arcs).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((Path(__file__).parent / "planmap_schema.json").read_text())
ICON_KIND = {1: "window", 2: "door", 5: "toilet", 6: "sink", 9: "bathtub"}  # official icon class -> kind
PARAMS = {"seg_wall_min_frac": 0.005, "seg_size": 512, "det_size": 1024, "seg_min_frac": 1e-4, "det_min_px": 20, "wall_len_frac": 0.03}


def validate(pm):
    errs = sorted(Draft202012Validator(SCHEMA).iter_errors(pm), key=lambda e: list(e.path))
    ids = [i["item_id"] for i in pm["items"]]
    msgs = [f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs[:10]]
    if len(ids) != len(set(ids)):
        msgs.append("duplicate item_id")
    for i in pm["items"]:
        if not i["item_id"].startswith(i["kind"] + "-"):
            msgs.append(f"{i['item_id']} does not start with kind {i['kind']}")
    return msgs


def _components(mask, min_area):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [(k, st[k]) for k in range(1, n) if st[k][4] >= min_area], lab


def _poly(contour_mask):
    cs, _ = cv2.findContours(contour_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cs, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 1.5, True)[:, 0, :]
    return [[int(x), int(y)] for x, y in c] if len(c) >= 3 else None


def _poly_off(sub, x, y):
    p = _poly(sub) if sub.any() else None
    return [[px + x, py + y] for px, py in p] if p else None


def wall_items(wall_mask, conf_map, W, H, source):
    """Split a wall mask into horizontal and vertical bars (plans are mostly orthogonal)."""
    items = []
    wall = wall_mask.astype(np.uint8)
    L = max(8, int(PARAMS["wall_len_frac"] * max(W, H)))
    for orient, ker in (("h", (L, 1)), ("v", (1, L))):
        bars = cv2.morphologyEx(wall, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, ker))
        comps, lab = _components(bars, L)
        for j, st in comps:
            x, y, w, h = map(int, st[:4])
            sub = lab[y:y + h, x:x + w] == j
            conf = float(conf_map[y:y + h, x:x + w][sub].mean())
            length, thick = (w, st[4] / max(w, 1)) if orient == "h" else (h, st[4] / max(h, 1))
            items.append(dict(kind="wall", label=None, bbox_px=[x, y, x + w, y + h],
                              polygon_px=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                              props={"orientation": orient, "length_px": int(length), "thickness_px": round(float(thick), 1)},
                              conf=round(conf, 3), source=source))
    return items


def seg_items(cls, probs, W, H):
    """cls: (H,W) uint8 0..3, probs: (4,H,W). Returns items (walls, doors, windows) with source 'seg'."""
    items = []
    min_area = max(12, PARAMS["seg_min_frac"] * W * H)
    # doors and windows: connected components of the cleaned masks
    for k, kind in ((2, "door"), (3, "window")):
        m = cv2.morphologyEx((cls == k).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        comps, lab = _components(m, min_area)
        for j, st in comps:
            x, y, w, h = map(int, st[:4])
            sub = lab[y:y + h, x:x + w] == j
            conf = float(probs[k][y:y + h, x:x + w][sub].mean())
            items.append(dict(kind=kind, label=None, bbox_px=[x, y, x + w, y + h], polygon_px=_poly_off(sub, x, y), props={"area_px": int(st[4])}, conf=round(conf, 3), source="seg"))
    items += wall_items((cls == 1), probs[1], W, H, "seg")
    return items


def det_items(rooms, icons, icon_conf, W, H, size):
    """Items from official icon heads. Components are counted on the original-res mask; min area scales with resolution."""
    items = []
    min_area = PARAMS["det_min_px"] * (max(W, H) / size) ** 2
    for k, kind in ICON_KIND.items():
        comps, lab = _components(icons == k, min_area)
        for j, st in comps:
            x, y, w, h = map(int, st[:4])
            sub = lab[y:y + h, x:x + w] == j
            conf = float(icon_conf[y:y + h, x:x + w][sub].mean())
            props = {"area_px": int(st[4])}
            if kind == "bathtub":
                props["includes_shower"] = True  # official icon class has no separate shower
            items.append(dict(kind=kind, label=None, bbox_px=[x, y, x + w, y + h],
                              polygon_px=_poly_off(sub, x, y),
                              props=props, conf=round(conf, 3), source="det"))
    return items


def det_walls(rooms, room_conf, W, H):
    return wall_items(rooms == 2, room_conf, W, H, "det")


def assemble(doc_id, W, H, items, models, ms, scale=None, page=1):
    counters, out = {}, []
    for it in sorted(items, key=lambda i: (i["kind"], i["bbox_px"][1], i["bbox_px"][0])):
        counters[it["kind"]] = counters.get(it["kind"], 0) + 1
        out.append({"item_id": f"{it['kind']}-{counters[it['kind']]:03d}", **it})
    return {"doc_id": doc_id, "page": page, "image": {"w": W, "h": H},
            "scale": scale or {"m_per_px": None, "method": "none", "confidence": 0.0},
            "items": out,
            "provenance": {"models": models, "params": PARAMS, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ms": int(ms)}}
