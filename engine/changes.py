"""E-11: changes engine. Compare two plan maps of the same drawing (same pixel frame) and list what changed.

  compare(doc_id, revision_dir) -> {"doc_id", "versions", "generated_for_demo", "image", "changes": [...]}
  revision_dir holds v1/planmap-1.json and v2/planmap-1.json (+ truth_changes.json when synthetic: never read here).

Each change: {change_id, type: added|removed|modified, kind, description, v1_item, v2_item, bbox_px_v1, bbox_px_v2,
field/old/new (modified), size_m / width_m}. Code only, no model call, cost 0.
  fixtures (door, window, toilet, ...): greedy IoU match; unmatched = added / removed.
  rooms: IoU match; a different label or area (> 3 %) = modified.
  walls: outline IoU match; left-overs covered by the other side's left-overs are a split (door cut into a wall), not a change.
Page-image fallback (two rasters, no plan map): `compare_images` marks the connected regions that differ.
"""
from __future__ import annotations

import json
from pathlib import Path

MIN_CONF = 0.5
MATCH_KINDS = ("door", "window", "toilet", "sink", "shower", "bathtub", "column", "stairs")
WALL_COVER = 0.5
IOU_MIN = 0.4
AREA_TOL = 0.03


def _items(path: Path) -> tuple[list[dict], dict]:
    m = json.loads(path.read_text(encoding="utf-8"))
    return [i for i in m["items"] if float(i.get("conf") or 0) >= MIN_CONF and i.get("bbox_px")], m


def _iou(a, b) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _match(a: list[dict], b: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    pairs = sorted(((_iou(x["bbox_px"], y["bbox_px"]), i, j) for i, x in enumerate(a) for j, y in enumerate(b)), reverse=True)
    ua, ub, out = set(), set(), []
    for s, i, j in pairs:
        if s < IOU_MIN:
            break
        if i in ua or j in ub:
            continue
        ua.add(i), ub.add(j)
        out.append((a[i], b[j]))
    return out, [x for i, x in enumerate(a) if i not in ua], [y for j, y in enumerate(b) if j not in ub]


def _shape(w: dict):
    from shapely.geometry import Polygon, box
    pts = w.get("polygon_px")
    if pts and len(pts) >= 3:
        g = Polygon(pts).buffer(0)
        if not g.is_empty:
            return g
    return box(*w["bbox_px"])


def _wall_diff(a: list[dict], b: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (removed from a, added in b). Walls are matched by outline IoU. Left-overs that the other side's left-overs cover
    (>= WALL_COVER of the area) are a wall split in two (or two joined), not a change."""
    from shapely.ops import unary_union
    sa, sb = [_shape(w) for w in a], [_shape(w) for w in b]
    used_a, used_b = set(), set()
    cand = []
    for i, x in enumerate(sa):
        for j, y in enumerate(sb):
            if x.bounds[2] < y.bounds[0] or y.bounds[2] < x.bounds[0] or x.bounds[3] < y.bounds[1] or y.bounds[3] < x.bounds[1]:
                continue
            u = x.union(y).area
            if u > 0:
                cand.append((x.intersection(y).area / u, i, j))
    for s_, i, j in sorted(cand, reverse=True):
        if s_ < 0.8:
            break
        if i not in used_a and j not in used_b:
            used_a.add(i), used_b.add(j)
    la = [i for i in range(len(a)) if i not in used_a]
    lb = [j for j in range(len(b)) if j not in used_b]
    ub = unary_union([sb[j].buffer(1.0) for j in lb]) if lb else None
    ua = unary_union([sa[i].buffer(1.0) for i in la]) if la else None
    rem = [a[i] for i in la if not (ub is not None and sa[i].area > 0 and sa[i].intersection(ub).area / sa[i].area >= WALL_COVER)]
    add = [b[j] for j in lb if not (ua is not None and sb[j].area > 0 and sb[j].intersection(ua).area / sb[j].area >= WALL_COVER)]
    return rem, add


def _m(box_px, mpp):
    w, h = box_px[2] - box_px[0], box_px[3] - box_px[1]
    return (round(min(w, h) * mpp, 2), round(max(w, h) * mpp, 2)) if mpp else None


def _area(it: dict):
    p = it.get("props") or {}
    for k in ("area_m2_label", "area_m2_geom", "area_m2"):
        if p.get(k) is not None:
            return float(p[k])
    return None


def _label(it: dict):
    return (it.get("label") or "").strip() or None


def compare(doc_id: str, revision_dir) -> dict:
    d = Path(revision_dir)
    a, ma = _items(d / "v1" / "planmap-1.json")
    b, mb = _items(d / "v2" / "planmap-1.json")
    mpp = ((ma.get("scale") or {}).get("m_per_px")) or ((mb.get("scale") or {}).get("m_per_px"))
    changes: list[dict] = []

    def add(type_, kind, v1, v2, desc, **extra):
        changes.append({"change_id": f"c{len(changes) + 1}", "type": type_, "kind": kind, "description": desc,
                        "v1_item": v1["item_id"] if v1 else None, "v2_item": v2["item_id"] if v2 else None,
                        "bbox_px_v1": v1["bbox_px"] if v1 else None, "bbox_px_v2": v2["bbox_px"] if v2 else None, **extra})

    # walls
    rem, new_w = _wall_diff([x for x in a if x["kind"] == "wall"], [x for x in b if x["kind"] == "wall"])
    for w in rem:
        sz = _m(w["bbox_px"], mpp)
        add("removed", "wall", w, None, f"A wall about {sz[1]:.1f} m long was removed." if sz else "A wall was removed.",
            **({"size_m": list(sz)} if sz else {}))
    for w in new_w:
        sz = _m(w["bbox_px"], mpp)
        add("added", "wall", None, w, f"A wall about {sz[1]:.1f} m long was added." if sz else "A wall was added.",
            **({"size_m": list(sz)} if sz else {}))
    # fixtures
    for kind in MATCH_KINDS:
        _, gone, new = _match([x for x in a if x["kind"] == kind], [x for x in b if x["kind"] == kind])
        for x in gone:
            sz = _m(x["bbox_px"], mpp)
            add("removed", kind, x, None, f"A {kind} was removed.", **({"width_m": sz[1]} if sz else {}))
        for x in new:
            sz = _m(x["bbox_px"], mpp)
            add("added", kind, None, x, f"A {kind}{f' ({sz[1]} m opening)' if sz else ''} was added.", **({"width_m": sz[1]} if sz else {}))
    # rooms
    pairs, gone, new = _match([x for x in a if x["kind"] == "room"], [x for x in b if x["kind"] == "room"])
    for x, y in pairs:
        la, lb = _label(x), _label(y)
        if la != lb and (la or lb):
            add("modified", "room", x, y, f"Room label changed from '{la}' to '{lb}'.", field="label", old=la, new=lb)
        aa, ab = _area(x), _area(y)
        if aa and ab and abs(ab - aa) / aa > AREA_TOL:
            add("modified", "room", x, y, f"Room area changed from {aa:.1f} m² to {ab:.1f} m².", field="area", old=round(aa, 2), new=round(ab, 2))
    for x in gone:
        add("removed", "room", x, None, f"Room {_label(x) or x['item_id']} was removed.")
    for y in new:
        add("added", "room", None, y, f"Room {_label(y) or y['item_id']} was added.")
    order = {"removed": 0, "added": 1, "modified": 2}
    changes.sort(key=lambda c: (order[c["type"]], c["kind"] != "wall", c["kind"]))
    for n, c in enumerate(changes, 1):
        c["change_id"] = f"c{n}"
    return {"doc_id": doc_id, "versions": ["v1", "v2"], "generated_for_demo": True, "source": "engine",
            "note": "Compared by the changes engine from the two plan maps (no model call).",
            "image": ma.get("image") or mb.get("image"), "changes": changes}


def compare_images(img1, img2, min_area_frac: float = 0.0005) -> dict:
    """Fallback with no plan map: boxes around regions where two same-size page images differ. Boxes only, no kinds."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(img1).convert("L"), dtype=np.int16)
    b = np.asarray(Image.open(img2).convert("L"), dtype=np.int16)
    if a.shape != b.shape:
        return {"changes": [], "image": {"w": a.shape[1], "h": a.shape[0]}, "note": "images differ in size; not compared"}
    diff = (np.abs(a - b) > 40).astype(np.uint8)
    import cv2
    diff = cv2.dilate(diff, np.ones((9, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(diff)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w * h >= min_area_frac * a.size:
            out.append({"change_id": f"c{len(out) + 1}", "type": "modified", "kind": "region", "description": "This region differs between the two drawings.",
                        "v1_item": None, "v2_item": None, "bbox_px_v1": [int(x), int(y), int(x + w), int(y + h)],
                        "bbox_px_v2": [int(x), int(y), int(x + w), int(y + h)]})
    return {"changes": out, "image": {"w": a.shape[1], "h": a.shape[0]}, "source": "engine-image"}
