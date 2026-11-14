"""Offline IFC Qto vs independent geometry, suitable for an ingest hook.

build(path, doc_id, item_ids=None) -> xcheck.json content (no writes).
Run geometry jobs through scripts/heavy.sh. Native IFC Z-up is used here.
"""
from __future__ import annotations

from pathlib import Path

from engine.xcheck import compare


def _unit_factor(unit, power):
    """Named IFC units, including custom conversion names and explicit overrides."""
    import ifcopenshell.util.unit as units
    if unit.is_a("IfcSIUnit"):
        return units.get_prefix_multiplier(unit.Prefix) ** power
    if unit.is_a("IfcConversionBasedUnit"):
        if getattr(unit, "ConversionOffset", 0):
            raise ValueError("Offset units are not a length/area/volume scale")
        conversion = unit.ConversionFactor
        return float(conversion.ValueComponent.wrappedValue) * _unit_factor(conversion.UnitComponent, power)
    raise ValueError("Unsupported IFC quantity unit")


def axis_length(el, scale):
    """Length from an explicit polyline axis, or a single straight MEP sweep.

    Mapping transforms and nonunit direction ratios are applied geometrically.
    Curves without a supported axis remain unavailable; boxes are never used.
    """
    import ifcopenshell.util.placement as placement
    import numpy as np
    reps = getattr(getattr(el, "Representation", None), "Representations", ()) or ()

    def walk(items, transform):
        found = []
        for item in items:
            if item.is_a("IfcMappedItem"):
                found.extend(walk(item.MappingSource.MappedRepresentation.Items, transform @ placement.get_mappeditem_transformation(item)))
            else:
                found.append((item, transform))
        return found

    for rep in reps:
        if rep.RepresentationIdentifier != "Axis":
            continue
        lengths = []
        for item, transform in walk(rep.Items, np.eye(4)):
            if item.is_a("IfcPolyline"):
                pts = [p.Coordinates for p in item.Points]
            elif item.is_a("IfcIndexedPolyCurve") and not item.Segments:
                pts = item.Points.CoordList
            else:
                return None
            points = np.array([list(p) + [0] * (3 - len(p)) + [1] for p in pts])
            world = (transform @ points.T).T[:, :3]
            lengths.append(float(np.linalg.norm(np.diff(world, axis=0), axis=1).sum()) * scale)
        if lengths:
            return sum(lengths), "explicit model axis", rep.id()
    straight = any(el.is_a(k) for k in ("IfcPipeSegment", "IfcDuctSegment", "IfcCableSegment", "IfcCableCarrierSegment", "IfcFlowSegment"))
    if not straight:
        return None
    bodies = [entry for rep in reps if rep.RepresentationIdentifier == "Body" for entry in walk(rep.Items, np.eye(4))]
    if len(bodies) != 1:
        return None
    item, transform = bodies[0]
    if not item.is_a("IfcExtrudedAreaSolid") or item.SweptArea.is_a() not in ("IfcCircleProfileDef", "IfcCircleHollowProfileDef", "IfcRectangleProfileDef", "IfcRectangleHollowProfileDef"):
        return None
    direction = np.array(item.ExtrudedDirection.DirectionRatios, dtype=float)
    direction /= np.linalg.norm(direction)
    position = placement.get_axis2placement(item.Position) if item.Position else np.eye(4)
    vector = transform[:3, :3] @ position[:3, :3] @ direction
    return float(item.Depth) * float(np.linalg.norm(vector)) * scale, "straight extrusion depth", item.id()


def build(path: Path, doc_id: str, item_ids=None, *, geometry=True):
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
    assigned_length = units.get_project_unit(f, "LENGTHUNIT") if f.by_type("IfcProject") else None
    if assigned_length is None:
        return {"doc_id": doc_id, "schema": f.schema, "elements": {}, "skipped": [{"reason": "No project length unit"}]}
    length_scale = _unit_factor(assigned_length, 1)
    factors = {"m": length_scale}
    for unit, ifc_unit, power in (("m2", "AREAUNIT", 2), ("m3", "VOLUMEUNIT", 3)):
        assigned = units.get_project_unit(f, ifc_unit)
        factors[unit] = _unit_factor(assigned, power) if assigned else None
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
                    if not geometry and unit != "m":
                        continue
                    # Explicit per-quantity Unit overrides the project assignment.
                    definition = f.by_id(quantities["id"])
                    quantity = next((q for q in definition.Quantities if q.Name == name), None)
                    own_unit = getattr(quantity, "Unit", None)
                    scale = _unit_factor(own_unit, {"m": 1, "m2": 2, "m3": 3}[unit]) if own_unit else factors[unit]
                    if scale is None:
                        skipped.append({"item_id": el.GlobalId, "quantity": name, "reason": "No unit assigned for this quantity dimension"})
                        continue
                    pairs.append((pset_name, name, raw, unit, scale, quantity))
        if not pairs:
            continue
        try:
            measurements = {}
            if geometry and any(p[3] in ("m2", "m3") for p in pairs):
                shaped = ifcopenshell.geom.create_shape(settings, el)
                triangulation = shaped.geometry
                verts = shape.get_vertices(triangulation)
                faces = shape.get_faces(triangulation)
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
                if any(p[3] == "m2" for p in pairs):
                    measurements["m2"] = shape.get_footprint_area(triangulation, axis="Z")
                if mesh.is_watertight and mesh.is_winding_consistent:
                    measurements["m3"] = abs(float(mesh.volume))
            axis = axis_length(el, length_scale)
            if axis:
                measurements["m"] = axis[0]
            for pset, name, raw, unit, scale, quantity in pairs:
                measured = measurements.get(unit)
                if measured is None or not np.isfinite(measured):
                    continue
                src = {"doc_id": doc_id, "item_id": el.GlobalId, "ifc_entity": el.id(), "quantity_set": pset, "quantity": name,
                       "raw_value": raw, "si_factor": scale, "unit_conversion": f"source quantity × {scale:.12g} = {unit}"}
                if unit == "m":
                    src.update(geometry_method=axis[1], geometry_entity=axis[2])
                c = compare("IFC Qto / model axis" if unit == "m" else "IFC Qto / geometry footprint" if unit == "m2" else "IFC Qto / closed geometry volume", raw * scale, measured, unit, [src])
                if c:
                    records.setdefault(el.GlobalId, []).append(c)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            skipped.append({"item_id": el.GlobalId, "reason": type(exc).__name__})
    return {"doc_id": doc_id, "schema": f.schema, "elements": records, "skipped": skipped,
            "units": factors, "geometry_units": "SI metres from ifcopenshell.geom; footprint in XY (native Z-up)"}


def ingest_lengths(path: Path, doc_id: str, directory: Path):
    """Cheap ingest hook: parse axes/sweeps only, no additional geometry pass."""
    import json
    checks = build(path, doc_id, geometry=False)
    temporary = directory / "xcheck.json.tmp"
    temporary.write_text(json.dumps(checks, allow_nan=False))
    temporary.replace(directory / "xcheck.json")
