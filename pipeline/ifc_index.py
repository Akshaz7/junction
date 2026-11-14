"""Property-only IFC index: skip representation/placement instances at parse time.

Uses the installed IFC schema and the same quantity/unit readers as the scene
pipeline. No tessellation, geometry-derived measurements or invented boxes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as uel
import ifcopenshell.util.schema as uschema
import ifcopenshell.util.unit as uunit

# None of these branches carries product identity, quantities, material or units.
GEOMETRY_ROOTS = (
    "IfcRepresentationItem", "IfcRepresentation", "IfcProductRepresentation",
    "IfcObjectPlacement", "IfcPresentationStyle", "IfcPresentationLayerAssignment",
)


def open_properties(path: Path):
    # Read only the SPF header to select the actual schema, including IFC4x3
    # versions. Avoid a preliminary full-model load just to discover its schema.
    header = bytearray()
    with path.open("rb") as source:
        while len(header) < 1024 * 1024:
            chunk = source.read(4096)
            if not chunk:
                break
            header.extend(chunk)
            match = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", header, re.I)
            if match:
                break
        else:
            match = None
    if not match:
        raise ValueError("The IFC schema header is missing or unreadable. Export the model again as IFC.")
    schema = ifcopenshell.schema_by_name(match[1].decode("ascii"))
    skip = {d.name() for root in GEOMETRY_ROOTS
            for d in uschema.get_subtypes(schema.declaration_by_name(root))}
    return ifcopenshell.open(str(path), bypass_types=sorted(skip))


def process(path: Path, doc: dict, out: Path) -> dict:
    from pipeline.ifc_scene import attr_dims, kind_of, props_of, quantities_of, storey_of
    from pipeline.ifc_props import building_meta, enrich_elements

    f = open_properties(path)
    has_project = bool(f.by_type("IfcProject"))
    length_known = has_project and uunit.get_project_unit(f, "LENGTHUNIT") is not None
    scale = uunit.calculate_unit_scale(f) if length_known else 1.0

    def level(st):
        return {"name": st.Name or "Unnamed level",
                "elevation_m": round(float(st.Elevation) * scale, 4)
                if st.Elevation is not None and length_known else None}

    storeys = [level(s) for s in f.by_type("IfcBuildingStorey")]
    storeys.sort(key=lambda s: (s["elevation_m"] is None, s["elevation_m"] or 0))
    elements, seen = [], set()
    for e in (*f.by_type("IfcElement"), *f.by_type("IfcSpace"), *f.by_type("IfcSite")):
        if e.is_a("IfcOpeningElement"):
            continue
        gid = e.GlobalId
        if not gid or gid in seen:
            raise ValueError("The IFC has missing or duplicate object identifiers. Export the model again as IFC.")
        seen.add(gid)
        st, typ = storey_of(e), uel.get_type(e)
        q = attr_dims(e, scale) if length_known else {}
        sources = {k: "attribute" for k in q}
        for k, v in (quantities_of(e, scale) if has_project else {}).items():
            q[k], sources[k] = v, "qto"
        elements.append({
            "item_id": gid, "name": e.Name, "ifc_class": e.is_a(), "kind": kind_of(e),
            "predefined_type": uel.get_predefined_type(e), "type_name": typ.Name if typ else None,
            "storey": level(st) if st is not None else None, "bbox_m": None, "bbox_source": None,
            "quantities": q, "quantity_source": sources, "props": props_of(e),
        })
    enrich_elements(f, elements)
    warnings = ["The 3D view is still being prepared. Counts and quantities stored in the model are available; "
                "measurements that require geometry are not available yet."]
    if not length_known:
        warnings.append("This IFC does not declare length units. Length measurements are unavailable.")
    result = {"doc_id": doc["doc_id"], "version": 2, "schema": f.schema, "units": "m",
              "building": building_meta(f), "storeys": storeys, "elements": elements,
              "geometry": "pending", "warnings": warnings}
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "tmp" / "elements-index.json"
    tmp.parent.mkdir(exist_ok=True)
    with tmp.open("w") as target:
        json.dump(result, target, ensure_ascii=False)
    tmp.replace(out / "elements.json")
    return {"elements": len(elements), "storeys": len(storeys), "schema": f.schema}
