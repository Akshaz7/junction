"""Offline IFC Qto vs independent geometry, suitable for an ingest hook.

build(path, doc_id, item_ids=None) -> xcheck.json content (no writes).
Run geometry jobs through scripts/heavy.sh. Native IFC Z-up is used here.
"""
from __future__ import annotations

from pathlib import Path

from engine.xcheck import compare


def build(path: Path, doc_id: str, item_ids=None):
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as element
    import ifcopenshell.util.shape as shape
    import ifcopenshell.util.unit as units
    import numpy as np
    import trimesh
    f = ifcopenshell.open(str(path))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    length_scale = units.calculate_unit_scale(f, "LENGTHUNIT")
    factors = {"m": length_scale}
    for unit, ifc_unit, power in (("m2", "AREAUNIT", 2), ("m3", "VOLUMEUNIT", 3)):
        assigned = units.get_project_unit(f, ifc_unit)
        factors[unit] = units.calculate_unit_scale(f, ifc_unit) if assigned else length_scale ** power
    records, skipped = {}, []
    targets = [f.by_guid(i) for i in item_ids] if item_ids is not None else f.by_type("IfcProduct")
    for el in targets:
        if not getattr(el, "Representation", None):
            continue
        pairs = []
        # Occurrence Qto overrides type Qto; no label/language matching needed.
        for pset_name, quantities in element.get_psets(el, qtos_only=True).items():
            for name, raw in quantities.items():
                if name == "id" or not isinstance(raw, (int, float)):
                    continue
                normal = name.casefold().replace(" ", "")
                unit = "m" if normal == "length" else "m2" if el.is_a("IfcSpace") and normal == "netfloorarea" else "m3" if normal == "netvolume" else None
                if unit:
                    # Explicit per-quantity Unit overrides the project assignment.
                    definition = f.by_id(quantities["id"])
                    quantity = next((q for q in definition.Quantities if q.Name == name), None)
                    own_unit = getattr(quantity, "Unit", None)
                    scale = units.convert_unit(1, own_unit, units.get_project_unit(f, {"m": "LENGTHUNIT", "m2": "AREAUNIT", "m3": "VOLUMEUNIT"}[unit])) * factors[unit] if own_unit else factors[unit]
                    pairs.append((pset_name, name, raw, unit, scale, quantity))
        if not pairs:
            continue
        try:
            shaped = ifcopenshell.geom.create_shape(settings, el)
            geometry = shaped.geometry
            verts = shape.get_vertices(geometry)
            faces = shape.get_faces(geometry)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
            measurements = {}
            if any(p[3] == "m2" for p in pairs):
                measurements["m2"] = shape.get_footprint_area(geometry, axis="Z")
            if mesh.is_watertight and mesh.is_winding_consistent:
                measurements["m3"] = abs(float(mesh.volume))
            # Straight MEP runs: a single swept circular/rectangular profile's
            # extrusion depth is a centreline length, independent of Qto.
            # Wall vertical extrusion depth would be height, so excluded.
            straight = any(el.is_a(k) for k in ("IfcPipeSegment", "IfcDuctSegment", "IfcCableSegment", "IfcCableCarrierSegment", "IfcFlowSegment"))
            extrusions = shape.get_extrusions(el) or []
            if straight and len(extrusions) == 1 and extrusions[0].SweptArea.is_a() in ("IfcCircleProfileDef", "IfcCircleHollowProfileDef", "IfcRectangleProfileDef", "IfcRectangleHollowProfileDef"):
                measurements["m"] = float(extrusions[0].Depth) * length_scale
            for pset, name, raw, unit, scale, quantity in pairs:
                measured = measurements.get(unit)
                if measured is None or not np.isfinite(measured):
                    continue
                src = {"doc_id": doc_id, "item_id": el.GlobalId, "ifc_entity": el.id(), "quantity_set": pset, "quantity": name,
                       "raw_value": raw, "si_factor": scale, "unit_conversion": f"source quantity × {scale:.12g} = {unit}"}
                c = compare("IFC Qto / swept centreline" if unit == "m" else "IFC Qto / geometry footprint" if unit == "m2" else "IFC Qto / closed geometry volume", raw * scale, measured, unit, [src])
                if c:
                    records.setdefault(el.GlobalId, []).append(c)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            skipped.append({"item_id": el.GlobalId, "reason": type(exc).__name__})
    return {"doc_id": doc_id, "schema": f.schema, "elements": records, "skipped": skipped,
            "units": factors, "geometry_units": "SI metres from ifcopenshell.geom; footprint in XY (native Z-up)"}
