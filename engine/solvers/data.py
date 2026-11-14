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
        return Doc(doc_id, "planmap", items, title, [], scale, len(pms))
    return None
