"""IFC project/building metadata and derived wall flags, shared by ifc_scene.process and the in-place enrich step.

Usage (no IfcConvert, patches artifacts/<doc>/elements.json only):
    PYTHONPATH=. .venv/bin/python -m pipeline.ifc_props [--only DOC_ID ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as uel

REPO = Path(__file__).resolve().parent.parent


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _ent(e) -> dict:
    if e is None:
        return {}
    out = {"name": _clean(e.Name), "description": _clean(getattr(e, "Description", None)),
           "long_name": _clean(getattr(e, "LongName", None)), "object_type": _clean(getattr(e, "ObjectType", None)),
           "phase": _clean(getattr(e, "Phase", None))}
    return {k: v for k, v in out.items() if v}


def building_meta(f) -> dict:
    """Header, project, site, building, Pset_BuildingCommon, authoring applications. Only what the file states."""
    meta: dict = {"schema": f.schema}
    try:
        h = f.header
        fn = h.file_name
        meta["header"] = {k: _clean(v) for k, v in (("originating_system", getattr(fn, "originating_system", None)),
                                                    ("preprocessor_version", getattr(fn, "preprocessor_version", None)),
                                                    ("authorization", getattr(fn, "authorization", None)),
                                                    ("time_stamp", getattr(fn, "time_stamp", None))) if _clean(v)}
        desc = list(getattr(h.file_description, "description", None) or [])
        if desc:
            meta["header"]["view_definition"] = "; ".join(str(d) for d in desc)
    except Exception:  # noqa: BLE001
        pass
    for key, cls in (("project", "IfcProject"), ("site", "IfcSite"), ("building", "IfcBuilding")):
        es = f.by_type(cls)
        if es:
            meta[key] = _ent(es[0])
    b = (f.by_type("IfcBuilding") or [None])[0]
    if b is not None:
        ps = uel.get_psets(b)
        common = {k: v for k, v in (ps.get("Pset_BuildingCommon") or {}).items() if k != "id" and v not in (None, "")}
        if common:
            meta["building_common"] = {k: (v if isinstance(v, (int, float, bool)) else str(v)) for k, v in common.items()}
        other = {}
        for pn, vals in ps.items():
            if pn == "Pset_BuildingCommon":
                continue
            for k, v in vals.items():
                if k.lower() in ("occupancytype", "buildingtype", "usage", "function", "nutzung", "gebaeudetyp", "gebäudetyp") and v:
                    other[k] = str(v)
        if other:
            meta["building_other"] = other
    apps = []
    for a in f.by_type("IfcApplication"):
        nm = _clean(getattr(a, "ApplicationFullName", None))
        if nm:
            ver = _clean(getattr(a, "Version", None))
            s = nm + (f" {ver}" if ver and ver not in nm else "")
            if s not in apps:
                apps.append(s)
    if apps:
        meta["applications"] = apps[:6]
    return meta


def external_from_boundaries(f) -> set[str]:
    """GlobalIds of walls/doors/windows with an EXTERNAL space boundary face (used when no IsExternal property exists)."""
    out = set()
    for r in f.by_type("IfcRelSpaceBoundary"):
        e = getattr(r, "RelatedBuildingElement", None)
        if e is not None and getattr(r, "InternalOrExternalBoundary", None) == "EXTERNAL" and e.is_a("IfcBuildingElement"):
            out.add(e.GlobalId)
    return out


def load_bearing_of(el):
    for _, vals in uel.get_psets(el).items():
        v = vals.get("LoadBearing")
        if v is not None:
            return bool(v)
    return None


def enrich_elements(f, elements: list[dict]) -> None:
    """Fill props.long_name (IfcSpace LongName = the room name), props.is_external (source space_boundary) for wall/door/window docs lacking IsExternal, and props.load_bearing."""
    cover = [e for e in elements if e["kind"] in ("wall", "door", "window")]
    has_flag = sum(1 for e in cover if e["props"].get("is_external") is not None)
    bnd = external_from_boundaries(f) if cover and has_flag == 0 and f.by_type("IfcRelSpaceBoundary") else set()
    for e in elements:
        p = e["props"]
        if e["kind"] in ("wall", "door", "window") and p.get("is_external") is None and bnd:
            p["is_external"] = e["item_id"] in bnd
            p["is_external_source"] = "space_boundary"
        if e["kind"] == "room" and "long_name" not in p:
            el = f.by_guid(e["item_id"]) if e["item_id"] else None
            ln = _clean(getattr(el, "LongName", None)) if el is not None else None
            if ln:
                p["long_name"] = ln
        if e["kind"] in ("wall", "column", "beam", "slab") and "load_bearing" not in p:
            el = f.by_guid(e["item_id"]) if e["item_id"] else None
            lb = load_bearing_of(el) if el is not None else None
            if lb is not None:
                p["load_bearing"] = lb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO / "data" / "junction-dataset-preview"))
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    art = Path(a.artifacts)
    for line in open(art / "registry.jsonl"):
        d = json.loads(line)
        if "ifc" not in d["formats"] or (a.only and d["doc_id"] not in a.only):
            continue
        ej = art / d["doc_id"] / "elements.json"
        ifc = Path(a.root) / d["files"]["ifc"]
        if not ej.exists():
            continue
        if not ifc.exists():
            ifc = Path(a.root).parent / "full" / "junction-dataset" / d["files"]["ifc"]
        if not ifc.exists():
            print(json.dumps({"doc_id": d["doc_id"], "error": "ifc file missing"}), flush=True)
            continue
        try:
            f = ifcopenshell.open(str(ifc))
            data = json.loads(ej.read_text())
            data["building"] = building_meta(f)
            enrich_elements(f, data["elements"])
            ej.write_text(json.dumps(data, indent=1))
            print(json.dumps({"doc_id": d["doc_id"], "ok": True}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"doc_id": d["doc_id"], "error": repr(e)}), flush=True)


if __name__ == "__main__":
    main()
