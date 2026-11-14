"""Load a document's items as one flat list. json only: no heavy imports."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Item:
    item_id: str
    kind: str
    label: str | None = None
    page: int = 1
    bbox_px: list | None = None
    storey: str | None = None
    conf: float = 1.0
    q: dict = field(default_factory=dict)       # quantities (m, m2, m3)
    props: dict = field(default_factory=dict)
    name: str | None = None
    type_name: str | None = None
    source: str = ""
    bbox_m: list | None = None                  # IFC only: [[minx,miny,minz],[maxx,maxy,maxz]], y up
    polygon_px: list | None = None              # plan map only


@dataclass
class Doc:
    doc_id: str
    mode: str                      # "ifc" | "planmap"
    items: list[Item]
    title: str = ""
    storeys: list[dict] = field(default_factory=list)   # [{name, elevation_m}]
    scale: dict | None = None      # plan map only (first page)
    pages: int = 1
    meta: dict = field(default_factory=dict)            # IFC only: project/building/software metadata (elements.json 'building')

    def kinds(self) -> set[str]:
        return {i.kind for i in self.items}


def _json(p: Path):
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _iou(a, b) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def dedupe_openings(items: list, thr: float = 0.3) -> list:
    """FIX-21: one opening read as both a door and a window (overlapping boxes on the same page): keep the more confident label."""
    ds = [i for i in items if i.kind == "door" and i.bbox_px]
    ws = [i for i in items if i.kind == "window" and i.bbox_px]
    drop = set()
    for d in ds:
        for w in ws:
            if d.page == w.page and id(d) not in drop and id(w) not in drop and _iou(d.bbox_px, w.bbox_px) > thr:
                drop.add(id(w if d.conf >= w.conf else d))
    return [i for i in items if id(i) not in drop] if drop else items


def load_doc(doc_id: str, root: Path, prefer: str | None = None) -> Doc | None:
    d = Path(root) / doc_id
    if not d.is_dir():
        return None
    meta = _json(d / "doc.json") if (d / "doc.json").exists() else {}
    title = meta.get("title") or doc_id
    el = d / "elements.json"
    pms = sorted(d.glob("planmap-[0-9]*.json"), key=lambda p: int(p.stem.split("-")[1]))
    if el.exists() and prefer != "planmap":
        e = _json(el)
        items = [
            Item(item_id=x["item_id"], kind=x.get("kind") or "other", page=1,
                 storey=(x.get("storey") or {}).get("name"), q=x.get("quantities") or {},
                 props={**(x.get("props") or {}), "ifc_class": x.get("ifc_class"), "predefined_type": x.get("predefined_type")},
                 name=x.get("name"), type_name=x.get("type_name"), source="ifc", bbox_m=x.get("bbox_m"))
            for x in e["elements"]
        ]
        # D-07 storey plans: one page per storey. Give each element its page and pixel box so answers can draw 2D boxes.
        placed = {}
        for p in pms:
            m = _json(p)
            for x in m.get("items", []):
                if x.get("bbox_px"):
                    placed[x["item_id"]] = (m.get("page", 1), x["bbox_px"])
        for it in items:
            if it.item_id in placed:
                it.page, it.bbox_px = placed[it.item_id]
        return Doc(doc_id, "ifc", items, title, e.get("storeys") or [], meta=e.get("building") or {})
    if pms:
        items, scale = [], None
        for p in pms:
            m = _json(p)
            scale = scale or m.get("scale")
            for x in m["items"]:
                pr = x.get("props") or {}
                q = {}
                for ak in ("area_m2", "area_m2_label", "area_m2_geom"):   # printed label area wins over polygon area
                    if pr.get(ak) is not None:
                        q["area_m2"] = pr[ak]
                        break
                for k in ("width_m", "height_m", "length_m"):
                    if pr.get(k) is not None:
                        q[k] = pr[k]
                items.append(Item(item_id=x["item_id"], kind=x["kind"], label=x.get("label"), page=m.get("page", 1),
                                  bbox_px=x.get("bbox_px"), polygon_px=x.get("polygon_px"), conf=float(x.get("conf") or 0), q=q, props=pr,
                                  source=x.get("source", "")))
        items = dedupe_openings(items)
        try:   # E-57: a printed scale (scale bar, or 1:200 + sheet size / dpi) beats the door-size guess
            from engine import scale_text
            better = scale_text.refine_scale(d, 1, scale)
            if better:
                scale_text.rescale_items(items, (scale or {}).get("m_per_px"), better["m_per_px"])
                scale = {**better, "replaced": (scale or {}).get("method")}
        except Exception:  # noqa: BLE001 - never block a document on scale reading
            pass
        return Doc(doc_id, "planmap", items, title, [], scale, len(pms))
    return None


def load_sheet_parent(doc_id: str, root: Path, whole: bool = False) -> Doc | None:
    """A per-floor sheet of an IFC model (`<model>-plan-NN-<slug>`, only a text layer, no plan map): answer from the parent
    model's elements, limited to the storey named in the sheet's title ("... Floor plan: 2. Level"). None when not applicable."""
    import re as _re
    m = _re.match(r"^(.+?)-plan-\d+-", doc_id)
    d = Path(root) / doc_id
    if not m or not d.is_dir() or (d / "elements.json").exists() or list(d.glob("planmap-[0-9]*.json")):
        return None
    parent = load_doc(m.group(1), root)
    if parent is None or parent.mode != "ifc" or not parent.storeys:
        return None
    title = (_json(d / "doc.json") if (d / "doc.json").exists() else {}).get("title") or ""
    nm = title.rsplit(":", 1)[-1].strip().casefold()
    st = next((s for s in parent.storeys if s["name"].strip().casefold() == nm), None)
    if st is None:
        return None
    if whole:   # "... in the model 'X'": the whole building, not just this sheet's floor
        return Doc(doc_id, "ifc", parent.items, title, parent.storeys, meta={**parent.meta, "sheet_of": parent.doc_id})
    items = [i for i in parent.items if i.storey == st["name"]]
    return Doc(doc_id, "ifc", items, title, [st], meta={**parent.meta, "sheet_of": parent.doc_id})
