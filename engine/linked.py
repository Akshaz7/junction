"""E-12: linked-information index. A tag, mark, name, label or item id resolves to the item,
every other place the same thing appears, and the source properties. Plain code, no model calls."""
from __future__ import annotations

import json
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


def _planmap_places(doc_id: str, root: Path) -> dict[str, list[dict]]:
    """item_id -> [{page, bbox_px}] from the plan maps (IFC items also appear on drawings)."""
    out: dict[str, list[dict]] = {}
    d = Path(root) / doc_id
    for p in sorted(d.glob("planmap-[0-9]*.json"), key=lambda p: int(p.stem.split("-")[1])):
        with p.open(encoding="utf-8") as f:
            m = json.load(f)
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
        return None
    raw = _raw_elements(doc_id, root).get(it.item_id, {})
    pm = _planmap_places(doc_id, root)
    props = {**(it.props or {})}
    props.update({k: v for k, v in (raw.get("props") or {}).items()})
    quantities = {k: v for k, v in (it.q or {}).items() if v is not None}
    same_type = [i for i in doc.items if i.item_id != it.item_id and it.type_name and i.type_name == it.type_name and i.kind == it.kind]
    key = _norm(it.label) or ""
    same_label = [i for i in doc.items if i.item_id != it.item_id and key and _norm(i.label) == key]
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
        "places": _place(it, tg.get(it.item_id, ""), pm)["drawings"] or ([{"page": it.page, "bbox_px": it.bbox_px}] if it.bbox_px else []),
        "same_type": {"type": it.type_name, "count": len(same_type) + (1 if it.type_name else 0),
                      "storeys": sorted({i.storey for i in same_type + [it] if i.storey}),
                      "items": [_place(i, tg.get(i.item_id, ""), pm) for i in same_type[:50]]},
        "same_label": [_place(i, tg.get(i.item_id, ""), pm) for i in same_label[:50]],
    }
