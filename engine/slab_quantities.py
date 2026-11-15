"""Slab thickness from unit-normalized quantities or material layers, never box height."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from engine.honesty import positive


def thickness(item):
    sources = item.props.get("quantity_source") or {}
    for key in ("thickness_m", "depth_m", "width_m"):
        value = positive(item.q.get(key))
        if value and sources.get(key) not in {"bbox", "geometry"}:
            return value, "quantity"
    value = positive(item.props.get("thickness_m"))
    if value:
        return value, "property"
    layers = item.props.get("material_layers")
    if isinstance(layers, list) and layers:
        values = [positive(layer.get("thickness_m")) if isinstance(layer, dict) else None for layer in layers]
        if all(value is not None for value in values):
            return sum(values), "layers"
    return None, "none"


def with_source_thickness(doc, root):
    """Fill absent indexed thickness from the original IFC when available.

    No geometry conversion and no source writes. API images without ifcopenshell
    still use the index and explicitly report missing thickness.
    """
    missing = {it.item_id for it in doc.items if it.kind == "slab" and thickness(it)[0] is None}
    if not missing:
        return doc
    from engine.wallarea import _source
    source = _source(doc.doc_id, Path(root))
    if source is None:
        return doc
    try:
        import ifcopenshell
        from ifcopenshell.util.element import get_material, get_type
        from ifcopenshell.util.unit import calculate_unit_scale, get_project_unit, get_property_unit, get_unit_scale
        model = ifcopenshell.open(str(source))
        if get_project_unit(model, "LENGTHUNIT") is None:
            return doc
        k = calculate_unit_scale(model)
        found = {}
        for element in model.by_type("IfcSlab"):
            if element.GlobalId not in missing:
                continue
            defs = [r.RelatingPropertyDefinition for r in (getattr(element, "IsDefinedBy", ()) or ()) if r.is_a("IfcRelDefinesByProperties")]
            typ = get_type(element)
            defs += list(getattr(typ, "HasPropertySets", ()) or ()) if typ else []
            values = []
            for definition in defs:
                if not definition.is_a("IfcElementQuantity"):
                    continue
                for quantity in definition.Quantities or ():
                    if quantity.is_a("IfcQuantityLength") and (quantity.Name or "").casefold() in {"thickness", "depth", "width"}:
                        unit = get_property_unit(quantity, model)
                        value = positive(quantity.LengthValue * get_unit_scale(unit)) if unit and unit.UnitType == "LENGTHUNIT" else None
                        if value:
                            values.append(value)
                if values:
                    break  # occurrence quantities take precedence over the type
            if values and max(values) - min(values) <= 1e-6:
                found[element.GlobalId] = (values[0], "Qto slab thickness")
                continue
            material = get_material(element, should_skip_usage=True, should_inherit=True)
            if material is not None and material.is_a("IfcMaterialLayerSet"):
                layers = [positive(layer.LayerThickness * k) for layer in material.MaterialLayers or ()]
                if layers and all(v is not None for v in layers):
                    found[element.GlobalId] = (sum(layers), "material layer thicknesses")
        return replace(doc, items=[replace(it, q={**it.q, "thickness_m": found[it.item_id][0]},
                                           props={**it.props, "thickness_source": found[it.item_id][1]})
                                   if it.item_id in found else it for it in doc.items])
    except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError):
        return doc
