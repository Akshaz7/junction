"""E-12: linked-information index. A tag, mark, name, label or item id resolves to the item,
every other place the same thing appears, and the source properties. Plain code, no model calls."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from engine import scene_cmds
from engine.solvers import ARTIFACTS
from engine.solvers.data import Doc, Item, load_doc



def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def _raw_elements(doc_id: str, root: Path) -> dict[str, dict]:
    p = Path(root) / doc_id / "elements.json"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return {e["item_id"]: e for e in json.load(f).get("elements", [])}


def _planmap_places(doc_id: str, root: Path, maps: list[dict] | None = None) -> dict[str, list[dict]]:
    """item_id -> [{page, bbox_px}] from the plan maps (IFC items also appear on drawings)."""
    out: dict[str, list[dict]] = {}
    for m in (maps if maps is not None else _load_planmaps(doc_id, root)):
        for x in m.get("items", []):
            out.setdefault(x["item_id"], []).append({"page": m.get("page", 1), "bbox_px": x.get("bbox_px"), "storey": m.get("storey")})
    return out


def _place(it: Item, tag: str, pm: dict[str, list[dict]]) -> dict:
    return {"item_id": it.item_id, "tag": tag, "kind": it.kind, "name": it.name or it.label, "storey": it.storey,
            "page": it.page, "bbox_px": it.bbox_px, "drawings": pm.get(it.item_id, [])}


def _resolve(doc: Doc, tg: dict[str, str], ref: str) -> Item | None:
    by_id = {i.item_id: i for i in doc.items}
    if ref in by_id:
        return by_id[ref]
    r = _norm(ref)
    for iid, t in tg.items():
        if _norm(t) == r:
            return by_id[iid]
    named = [i for i in doc.items if _norm(i.name) == r or _norm(i.label) == r]
    return named[0] if len(named) == 1 else (named[0] if named else None)


def lookup(doc_id: str, ref: str, root: Path | None = None) -> dict | None:
    """Return {item, properties, type, also_here, same_type, same_label, places} or None if ref is unknown."""
    root = Path(root or ARTIFACTS)
    doc = load_doc(doc_id, root)
    if doc is None or not ref or not str(ref).strip():
        return None
    tg = scene_cmds.tags(doc)
    it = _resolve(doc, tg, str(ref))
    if it is None:
        from engine.wall_details import scene_wall
        generated = scene_wall(doc_id, str(ref), root)
        if generated is None:
            return None
        it = Item(item_id=str(ref), kind="wall", name="Wall (generated for demo)", storey=generated.get("storey"),
                  page=generated.get("page", 1), bbox_px=generated.get("bbox_px"), source="generated")
    raw = _raw_elements(doc_id, root).get(it.item_id, {})
    maps = _load_planmaps(doc_id, root)
    pm = _planmap_places(doc_id, root, maps)
    plan = _plan_info(it.item_id, maps, it.page)
    props = {**(it.props or {})}
    props.update({k: v for k, v in (raw.get("props") or {}).items()})
    quantities = {k: v for k, v in (it.q or {}).items() if v is not None}
    same_type = [i for i in doc.items if i.item_id != it.item_id and it.type_name and i.type_name == it.type_name and i.kind == it.kind]
    key = _norm(it.label) or ""
    same_label = [i for i in doc.items if i.item_id != it.item_id and key and _norm(i.label) == key]
    wall_details = None
    if it.kind == "wall":
        from engine.wall_details import details
        wall_details = details(doc_id, it.item_id, root, quantities=quantities, props=props, storey=it.storey)
    return {
        "doc_id": doc_id,
        "item_id": it.item_id,
        "tag": tg.get(it.item_id),
        "kind": it.kind,
        "name": it.name or it.label,
        "storey": it.storey,
        "type": it.type_name or props.get("room_type"),
        "ifc_class": raw.get("ifc_class") or props.get("ifc_class"),
        "properties": props,
        "quantities": quantities,
        "quantity_source": raw.get("quantity_source") or {},
        "wall_details": wall_details,
        "places": _place(it, tg.get(it.item_id, ""), pm)["drawings"] or ([{"page": it.page, "bbox_px": it.bbox_px}] if it.bbox_px else []),
        "same_type": {"type": it.type_name, "count": len(same_type) + (1 if it.type_name else 0),
                      "storeys": sorted({i.storey for i in same_type + [it] if i.storey}),
                      "items": [_place(i, tg.get(i.item_id, ""), pm) for i in same_type[:50]]},
        "same_label": [_place(i, tg.get(i.item_id, ""), pm) for i in same_label[:50]],
        "measures": plan.get("measures") or {},
        "scale": plan.get("scale"),
        "relations": plan.get("relations") or {},
    }


# --- 2D inspect: plan-map measures, scale and geometric relations (plain code, page pixels) ---
_SKIP = {"text", "dimension", "label"}
_OPEN = {"door", "window", "opening"}


def _load_planmaps(doc_id: str, root: Path) -> list[dict]:
    out = []
    for p in sorted((Path(root) / doc_id).glob("planmap-[0-9]*.json"), key=lambda p: int(p.stem.split("-")[1])):
        with p.open(encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def _bb(x: dict):
    b = x.get("bbox_px")
    return [float(v) for v in b] if b and len(b) == 4 else None


def _poly_of(x: dict):
    p = x.get("polygon_px")
    if p and len(p) >= 3:
        return [(float(a[0]), float(a[1])) for a in p]
    b = _bb(x)
    return [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])] if b else None


def _centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _inside(pt, poly) -> bool:
    x, y, c, n = pt[0], pt[1], False, len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _seg_d(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def _pt_poly_d(p, poly) -> float:
    return min(_seg_d(p, poly[i - 1], poly[i]) for i in range(len(poly)))


def _poly_poly_d(a, b) -> float:
    if any(_inside(p, b) for p in a) or any(_inside(p, a) for p in b):
        return 0.0
    return min(min(_pt_poly_d(p, b) for p in a), min(_pt_poly_d(p, a) for p in b))


def _bb_overlap(a, b, g: float = 0.0) -> bool:
    return a[0] - g <= b[2] and b[0] - g <= a[2] and a[1] - g <= b[3] and b[1] - g <= a[3]


def _entry(x: dict) -> dict:
    pr = x.get("props") or {}
    e = {"item_id": x["item_id"], "kind": x.get("kind"), "label": x.get("label") or pr.get("name") or pr.get("room_type")}
    if pr.get("number") is not None:
        e["number"] = pr["number"]
    return e


def _wall_thr(w: dict) -> float:
    t = (w.get("props") or {}).get("thickness_px")
    return max(8.0, 1.5 * float(t)) if isinstance(t, (int, float)) else 8.0


def _opening_rooms(o: dict, rooms: list[dict]) -> list[dict]:
    b = _bb(o)
    c = _centre(b)
    hits = []
    for r in rooms:
        rb = _bb(r)
        if not rb or not _bb_overlap(rb, [c[0], c[1], c[0], c[1]], 12):
            continue
        poly = _poly_of(r)
        d = 0.0 if _inside(c, poly) else _pt_poly_d(c, poly)
        if d <= 12:
            hits.append((d, r))
    return [_entry(r) for _, r in sorted(hits, key=lambda h: h[0])]


def _wall_rooms(w: dict, rooms: list[dict]) -> list[dict]:
    wb, thr, wp = _bb(w), _wall_thr(w), _poly_of(w)
    out = []
    for r in rooms:
        rb = _bb(r)
        if wb and rb and _bb_overlap(wb, rb, thr) and _poly_poly_d(wp, _poly_of(r)) <= thr:
            out.append(r)
    return out


def _relations(x: dict, items: list[dict]) -> dict:
    kind = x.get("kind")
    if not _bb(x):
        return {}
    items = [i for i in items if i.get("kind") not in _SKIP and _bb(i) and i["item_id"] != x["item_id"]]
    rooms = [i for i in items if i.get("kind") == "room"]
    walls = [i for i in items if i.get("kind") == "wall"]
    if kind == "room":
        poly, contains = _poly_of(x), []
        for o in items:
            k = o.get("kind")
            if k in ("room", "wall"):
                continue
            if k in _OPEN:
                if any(e["item_id"] == x["item_id"] for e in _opening_rooms(o, [x])):
                    contains.append(o)
            elif _inside(_centre(_bb(o)), poly):
                contains.append(o)
        counts: dict[str, int] = {}
        for o in contains:
            counts[o["kind"]] = counts.get(o["kind"], 0) + 1
        ws = [w for w in walls if _wall_rooms(w, [x])]
        return {"contains": [_entry(o) for o in contains[:50]], "counts": counts,
                "walls": [{**_entry(w), "length_m": (w.get("props") or {}).get("length_m")} for w in ws[:50]]}
    if kind in _OPEN:
        b = _bb(x)
        near = [(w, _poly_poly_d(_poly_of(x), _poly_of(w))) for w in walls if _bb_overlap(b, _bb(w), 60)]
        wall = min(near, key=lambda t: t[1])[0] if near else None
        return {"rooms": _opening_rooms(x, rooms), "wall": _entry(wall) if wall else None}
    if kind == "wall":
        g = _bb(x)
        ops = [o for o in items if o.get("kind") in _OPEN and _bb_overlap(g, _bb(o), 4)]
        return {"rooms": [_entry(r) for r in _wall_rooms(x, rooms)], "openings": [_entry(o) for o in ops[:50]]}
    c = _centre(_bb(x))
    room = next((r for r in rooms if _inside(c, _poly_of(r))), None)
    return {"room": _entry(room) if room else None}


def _plan_info(item_id: str, maps: list[dict], page: int | None) -> dict:
    """measures/scale/relations for an item found in a plan map (prefers the item's own page)."""
    order = sorted(maps, key=lambda m: m.get("page", 1) != page)
    for m in order:
        x = next((i for i in m.get("items", []) if i.get("item_id") == item_id), None)
        if x is None:
            continue
        sc = m.get("scale") or {}
        mpp = sc.get("m_per_px")
        out = {"page": m.get("page", 1), "measures": {}, "relations": _relations(x, m.get("items", [])),
               "scale": {"m_per_px": mpp, "method": sc.get("method") or sc.get("source"),
                         "confidence": sc.get("confidence")} if sc else None}
        try:
            from engine.plan_measures import measures
            out["measures"] = measures(x, mpp) or {}
        except Exception:  # noqa: BLE001 - module may not have landed yet
            pass
        return out
    return {}
