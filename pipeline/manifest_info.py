"""Blueprint info on every scene.json item, for the AR / 3D info cards.

Adds `name` and `props` to the items of artifacts/<doc>/scene.json without touching ids, usd names, boxes or tags:
  rooms:  name (LongName, else Name / plan label / room type), props.LongName, props.area_m2, props.area_source
  doors:  props.width_m, props.height_m, props.axis ("x" or "z": the wall direction it sits in), props.swing
          (IFC OperationType, when the model has it), props.operation_type
  others: name from the IFC element or the plan-map label, width/height when known.
Sources: elements.json (IFC), planmap-<n>.json (raster / DXF / PDF), the item bbox as the last resort.
CLI: python -m pipeline.manifest_info [--only DOC_ID...] [--root DIR]    (default root: artifacts)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _ifc_operation(ifc_path: Path | None) -> dict:
    if not ifc_path or not ifc_path.exists():
        return {}
    try:
        import ifcopenshell
        f = ifcopenshell.open(str(ifc_path))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for d in f.by_type("IfcDoor"):
        op = getattr(d, "OperationType", None)
        if op is None:
            for rel in getattr(d, "IsTypedBy", None) or []:
                op = getattr(rel.RelatingType, "OperationType", None)
        if op and str(op) not in ("NOTDEFINED", "USERDEFINED"):
            out[d.GlobalId] = str(op)
    return out


def _swing(op: str | None) -> str | None:
    if not op:
        return None
    o = op.upper()
    if "LEFT" in o:
        return "left"
    if "RIGHT" in o:
        return "right"
    if "DOUBLE" in o:
        return "double"
    if "SLIDING" in o:
        return "sliding"
    return None


def enrich(art: Path, ifc_path: Path | None = None) -> dict:
    sp = art / "scene.json"
    sj = json.loads(sp.read_text())
    elements = {}
    if (art / "elements.json").exists():
        elements = {e["item_id"]: e for e in json.loads((art / "elements.json").read_text())["elements"]}
    pm_items = {}
    pm_file = sj.get("source_planmap")
    if pm_file and (art / pm_file).exists():
        pm_items = {i["item_id"]: i for i in json.loads((art / pm_file).read_text())["items"]}
    ops = _ifc_operation(ifc_path) if elements else {}
    named = areas = widths = 0
    for iid, it in sj["items"].items():
        kind = it.get("kind")
        props = dict(it.get("props") or {})
        el, pm = elements.get(iid), pm_items.get(iid)
        lo, hi = it["bbox_m"]
        ext = [hi[i] - lo[i] for i in range(3)]
        name = None
        if el:
            q = el.get("quantities") or {}
            p = el.get("props") or {}
            long_name = p.get("long_name")
            name = long_name or el.get("name")
            if kind == "room":
                props["LongName"] = long_name or None
                a = q.get("net_floor_area_m2") or q.get("gross_floor_area_m2") or q.get("area_m2")
                if a:
                    props["area_m2"] = round(float(a), 2)
                    props["area_source"] = "qto"
            for k in ("width_m", "height_m"):
                if kind in ("door", "window") and q.get(k):
                    props[k] = round(float(q[k]), 3)
            if iid in ops:
                props["operation_type"] = ops[iid]
                if _swing(ops[iid]):
                    props["swing"] = _swing(ops[iid])
        elif pm:
            pp = pm.get("props") or {}
            label = pm.get("label")
            name = label or (str(pp.get("room_type")).replace("_", " ").title() if pp.get("room_type") else None)
            if kind == "room":
                props["LongName"] = label
                if pp.get("room_type"):
                    props["room_type"] = pp["room_type"]
                if pp.get("area_m2"):
                    props["area_m2"] = round(float(pp["area_m2"]), 2)
                    props["area_source"] = "planmap"
        if kind == "room" and "area_m2" not in props:
            props["area_m2"] = round(ext[0] * ext[2], 2)
            props["area_source"] = "bbox"
        if kind in ("door", "window"):
            horiz = max(ext[0], ext[2])
            props.setdefault("width_m", round(horiz, 3))
            props.setdefault("height_m", round(ext[1], 3))
            props["axis"] = "x" if ext[0] >= ext[2] else "z"
        if name:
            it["name"] = str(name)
            named += 1
        if kind == "room" and props.get("area_m2"):
            areas += 1
        if props.get("width_m"):
            widths += 1
        if props:
            it["props"] = props
    sp.write_text(json.dumps(sj, indent=1))
    return {"items": len(sj["items"]), "named": named, "room_areas": areas, "widths": widths}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--root", default=str(REPO / "artifacts"))
    a = ap.parse_args()
    for art in sorted(Path(a.root).glob("*__*")):
        if a.only and art.name not in a.only or not (art / "scene.json").exists():
            continue
        ifc = None
        try:
            dj = json.loads((art / "doc.json").read_text())
            if dj.get("files", {}).get("ifc"):
                ifc = REPO / dj["files"]["ifc"]
                if not ifc.exists():  # the preview dataset keeps files under data/junction-dataset-preview/
                    ifc = REPO / "data" / "junction-dataset-preview" / dj["files"]["ifc"].removeprefix("data/")
        except Exception:  # noqa: BLE001
            pass
        print(art.name, enrich(art, ifc))


if __name__ == "__main__":
    main()
