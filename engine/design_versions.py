"""Saved design versions (3D edits) and the exact, item-by-item diff between any two of them.

A design version is a snapshot of edits over the original document (version 0 = no edits):
  {"removed": [item_id, ...], "moved": {item_id: [dx_m, dz_m]}, "materials": {item_id: name}}
Moves are metres in world X (east) and Z (south), as the 3D viewer reports them (EditState.moveDelta). The plan map
projects X/Z onto the page with m_per_px (CONTRACT plan map scale), so a move is a pixel shift dx/m_per_px, dz/m_per_px.

Edits never renumber items, so versions are matched by item id (not geometry, unlike engine.changes). Code only, no model
call, cost 0. Change records follow the changes-engine shape (type added|removed|modified, kind, description, v1_item,
v2_item, bbox_px_v1, bbox_px_v2, field/old/new) plus optional `action` (removed|added|moved|material), `item_id`, `tag`,
`delta_m` and `pages`.
"""
from __future__ import annotations

import json
from pathlib import Path

MOVE_TOL = 0.05          # metres; the viewer snaps moves to 0.1 m
MAX_IDS = 2000
MAX_ID_LEN = 120
MAX_MOVE_M = 500.0
ACTIONS = ("removed", "added", "moved", "material")


def _id(v) -> bool:
    return isinstance(v, str) and 0 < len(v) <= MAX_ID_LEN


def clean_edits(raw) -> dict | None:
    """Validate a client snapshot. Returns {"removed": [...], "moved": {...}, "materials": {...}} or None."""
    if not isinstance(raw, dict):
        return None
    removed, moved, materials = raw.get("removed") or [], raw.get("moved") or {}, raw.get("materials") or {}
    if not isinstance(removed, list) or not isinstance(moved, dict) or not isinstance(materials, dict):
        return None
    if len(removed) > MAX_IDS or len(moved) > MAX_IDS or len(materials) > MAX_IDS:
        return None
    out_r = sorted({i for i in removed if _id(i)})
    out_m = {}
    for k, v in moved.items():
        if not _id(k) or not isinstance(v, (list, tuple)) or len(v) != 2:
            return None
        try:
            dx, dz = float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return None
        if not (abs(dx) <= MAX_MOVE_M and abs(dz) <= MAX_MOVE_M):
            return None
        if abs(dx) >= MOVE_TOL / 2 or abs(dz) >= MOVE_TOL / 2:
            out_m[k] = [round(dx, 3), round(dz, 3)]
    out_t = {k: v for k, v in materials.items() if _id(k) and isinstance(v, str) and 0 < len(v) <= 40}
    return {"removed": out_r, "moved": dict(sorted(out_m.items())), "materials": dict(sorted(out_t.items()))}


def empty() -> dict:
    return {"removed": [], "moved": {}, "materials": {}}


def is_empty(e: dict) -> bool:
    return not (e.get("removed") or e.get("moved") or e.get("materials"))


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _page_no(p: Path) -> int:
    try:
        return int(p.stem.split("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def load_doc(doc_dir) -> tuple[dict, dict]:
    """-> (items, pages). items: {item_id: {kind, label, tag, name, storey, boxes: {page: bbox_px}}};
    pages: {page: {"image": {w, h}, "m_per_px": float | None}}. Reads planmap-*.json and scene.json only."""
    d = Path(doc_dir)
    items: dict[str, dict] = {}
    pages: dict[int, dict] = {}
    for f in sorted(d.glob("planmap-*.json"), key=_page_no):
        n, m = _page_no(f), _read(f)
        if not n or not isinstance(m, dict):
            continue
        pages[n] = {"image": m.get("image"), "m_per_px": (m.get("scale") or {}).get("m_per_px")}
        for it in m.get("items") or []:
            iid = it.get("item_id")
            if not _id(iid):
                continue
            e = items.setdefault(iid, {"kind": it.get("kind"), "label": it.get("label"), "tag": None, "name": None,
                                       "storey": (it.get("props") or {}).get("storey"), "boxes": {}})
            e["tag"] = e["tag"] or (it.get("props") or {}).get("tag")
            if it.get("bbox_px"):
                e["boxes"][n] = [float(x) for x in it["bbox_px"]]
    scene = _read(d / "scene.json")
    for iid, s in ((scene or {}).get("items") or {}).items():
        e = items.setdefault(iid, {"kind": s.get("kind"), "label": None, "tag": None, "name": None,
                                   "storey": s.get("storey"), "boxes": {}})
        e["kind"] = e["kind"] or s.get("kind")
        e["tag"] = s.get("tag") or e["tag"]
        e["name"] = s.get("name") or e["name"]
        e["storey"] = e["storey"] or s.get("storey")
    return items, pages


def name_of(iid: str, it: dict | None) -> str:
    it = it or {}
    kind = (it.get("kind") or "item").replace("_", " ").replace("-", " ")
    ref = it.get("tag") or it.get("label") or it.get("name")
    extra = it.get("label") or it.get("name")
    if ref and extra and extra != ref:
        ref = f"{ref} ({extra})"
    return f"{kind.capitalize()} {ref}" if ref else kind.capitalize()


def describe_move(dx: float, dz: float) -> str:
    parts = []
    if abs(dx) >= MOVE_TOL:
        parts.append(f"{abs(dx):.1f} m {'east' if dx > 0 else 'west'}")
    if abs(dz) >= MOVE_TOL:
        parts.append(f"{abs(dz):.1f} m {'south' if dz > 0 else 'north'}")
    return ", ".join(parts)


def shift(box, move, mpp):
    """bbox_px moved by a world X/Z offset in metres; unchanged without a move or a scale."""
    if box is None or not move or not mpp:
        return list(box) if box is not None else None
    kx, ky = move[0] / mpp, move[1] / mpp
    return [round(box[0] + kx, 1), round(box[1] + ky, 1), round(box[2] + kx, 1), round(box[3] + ky, 1)]


def diff(a: dict, b: dict) -> list[dict]:
    """Snapshot a -> snapshot b, by item id: [{action, item_id, ...}] (removed, added back, moved, material)."""
    ra, rb = set(a.get("removed") or []), set(b.get("removed") or [])
    ma, mb = a.get("moved") or {}, b.get("moved") or {}
    ta, tb = a.get("materials") or {}, b.get("materials") or {}
    out = [{"action": "removed", "item_id": i} for i in sorted(rb - ra)]
    out += [{"action": "added", "item_id": i} for i in sorted(ra - rb)]
    for i in sorted((set(ma) | set(mb)) - rb):
        pa, pb = ma.get(i, [0.0, 0.0]), mb.get(i, [0.0, 0.0])
        d = [round(pb[0] - pa[0], 3), round(pb[1] - pa[1], 3)]
        if abs(d[0]) >= MOVE_TOL or abs(d[1]) >= MOVE_TOL:
            out.append({"action": "moved", "item_id": i, "delta_m": d})
    for i in sorted((set(ta) | set(tb)) - rb):
        if ta.get(i) != tb.get(i):
            out.append({"action": "material", "item_id": i, "old": ta.get(i), "new": tb.get(i)})
    return out


def counts(changes: list[dict]) -> dict:
    return {k: sum(1 for c in changes if c.get("action") == k) for k in ACTIONS}


def compare(doc_dir, a: dict, b: dict, items_pages: tuple[dict, dict] | None = None) -> dict:
    """Changes engine output for two design versions of one document (same pixel frame on every page)."""
    items, pages = items_pages or load_doc(doc_dir)
    changes = []
    for d in diff(a, b):
        iid, act = d["item_id"], d["action"]
        it = items.get(iid)
        boxes = (it or {}).get("boxes") or {}
        page = min(boxes) if boxes else None
        mpp = (pages.get(page) or {}).get("m_per_px") if page else None
        box = boxes.get(page) if page else None
        b1 = shift(box, (a.get("moved") or {}).get(iid), mpp)
        b2 = shift(box, (b.get("moved") or {}).get(iid), mpp)
        name = name_of(iid, it)
        c = {"action": act, "item_id": iid, "kind": (it or {}).get("kind") or "item", "tag": (it or {}).get("tag"),
             "label": (it or {}).get("label") or (it or {}).get("name"), "storey": (it or {}).get("storey"),
             "page": page, "page_v1": page, "page_v2": page, "pages": sorted(boxes), "v1_item": iid, "v2_item": iid}
        if act == "removed":
            c.update(type="removed", description=f"{name} was removed.", bbox_px_v1=b1, bbox_px_v2=None, v2_item=None)
        elif act == "added":
            c.update(type="added", description=f"{name} was added back.", bbox_px_v1=None, bbox_px_v2=b2, v1_item=None)
        elif act == "moved":
            text = describe_move(*d["delta_m"])
            c.update(type="modified", field="position", delta_m=d["delta_m"], description=f"{name} moved {text}.",
                     bbox_px_v1=b1, bbox_px_v2=b2)
        else:
            c.update(type="modified", field="material", old=d["old"], new=d["new"], bbox_px_v1=b1, bbox_px_v2=b2,
                     description=f"{name} material changed from {d['old'] or 'original'} to {d['new'] or 'original'}.")
        changes.append(c)
    order = {"removed": 0, "added": 1, "moved": 2, "material": 3}
    changes.sort(key=lambda c: (order[c["action"]], c["page"] is None, c["page"] or 0, c["kind"], c["tag"] or "", c["item_id"]))
    for n, c in enumerate(changes, 1):
        c["change_id"] = f"c{n}"
    plist = [{"page_a": n, "page_b": n, "image": p.get("image"), "n_changes": sum(1 for c in changes if c["page"] == n)}
             for n, p in sorted(pages.items())]
    return {"source": "edit-diff", "pages": plist, "changes": changes, "counts": counts(changes),
            "note": "Compared item by item from the saved 3D edits (no model call). Edited versions are generated "
                    "from 3D edits, not issued drawings."}


def headline(changes: list[dict]) -> str:
    c = counts(changes)
    parts = [f"{c[k]} {w}" for k, w in (("removed", "removed"), ("added", "added back"), ("moved", "moved"),
                                          ("material", "material changed")) if c[k]]
    return ", ".join(parts).capitalize() + "." if parts else "No differences."
