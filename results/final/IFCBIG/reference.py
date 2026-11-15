"""Independent full native parse for comparison; no pipeline readers or geometry.

Run once via scripts/heavy.sh after implementation. Output is a small JSON file.
"""
import json
from pathlib import Path
import sys

import ifcopenshell
import ifcopenshell.util.unit as units
import ifcopenshell.util.element as element


def room_area(room):
    quantities, properties = [], []
    priority = {"NetFloorArea": 0, "GrossFloorArea": 1, "Area": 2, "NetArea": 3, "GrossArea": 4}
    for relation in room.IsDefinedBy or ():
        if not relation.is_a("IfcRelDefinesByProperties"):
            continue
        definition = relation.RelatingPropertyDefinition
        if definition.is_a("IfcElementQuantity"):
            for q in definition.Quantities or ():
                if q.is_a("IfcQuantityArea") and q.Name in priority:
                    quantities.append((priority[q.Name], q, q.AreaValue))
        elif definition.is_a("IfcPropertySet"):
            for prop in definition.HasProperties or ():
                if prop.is_a("IfcPropertySingleValue") and prop.Name in priority and prop.NominalValue is not None and prop.NominalValue.is_a() == "IfcAreaMeasure":
                    properties.append((priority[prop.Name], prop, prop.NominalValue.wrappedValue))
    for _, measure, value in sorted(quantities or properties, key=lambda entry: entry[0]):
        unit = units.get_property_unit(measure, room.file)
        if unit is not None and unit.UnitType == "AREAUNIT":
            return float(value) * units.get_unit_scale(unit)
    return None


def main():
    records = []
    for source in map(Path, sys.argv[1:]):
        model = ifcopenshell.open(str(source))
        spaces = model.by_type("IfcSpace")
        areas = [room_area(room) for room in spaces]
        record = {"file": str(source), "schema": model.schema,
                  "door_count": len(model.by_type("IfcDoor")), "window_count": len(model.by_type("IfcWindow")),
                  "pipe_count_from_explicit_type": sum(bool((t := element.get_type(e)) is not None and t.is_a("IfcPipeSegmentType")) for e in model.by_type("IfcElement")),
                  "room_count": len(spaces), "rooms_with_explicit_area": sum(a is not None for a in areas),
                  "recorded_room_area_m2": sum(a for a in areas if a is not None) if any(a is not None for a in areas) else None}
        records.append(record)
        del model
    output = Path(__file__).with_name("reference.json")
    output.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(records))


if __name__ == "__main__":
    main()
