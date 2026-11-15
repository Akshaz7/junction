"""Property indexing must preserve explicit quantities across schemas and units."""
import json

import ifcopenshell
import ifcopenshell.api
import pytest

from pipeline import ifc_index


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
@pytest.mark.parametrize("imperial", [False, True])
def test_property_index_preserves_units_ids_and_no_geometry(tmp_path, schema, imperial):
    f = ifcopenshell.file(schema=schema)
    length = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    if imperial:
        dims = f.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0)
        metre = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
        value = f.create_entity("IfcMeasureWithUnit", f.create_entity("IfcLengthMeasure", 0.3048), metre)
        length = f.create_entity("IfcConversionBasedUnit", dims, "LENGTHUNIT", "foot", value)
    area = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
    units = f.create_entity("IfcUnitAssignment", [length, area])
    f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), UnitsInContext=units)
    st = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Kerros / Geschoss", Elevation=3.)
    room = f.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name="Raum", LongName="Küche")
    door = f.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="Tür", OverallWidth=3. if imperial else 900.)
    q = f.create_entity("IfcQuantityArea", Name="NetFloorArea", AreaValue=42.5)
    qs = f.create_entity("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(), Name="Qto_SpaceBaseQuantities", Quantities=[q])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[room], RelatingPropertyDefinition=qs)
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=st, RelatedObjects=[room])
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(), RelatedElements=[door], RelatingStructure=st)
    # Substantial geometry must be absent from the property-only file.
    point = f.create_entity("IfcCartesianPoint", (1., 2., 3.))
    src = tmp_path / "model.ifc"
    f.write(str(src))
    ifc_index.process(src, {"doc_id": "test"}, tmp_path / "index")
    data = json.loads((tmp_path / "index/elements.json").read_text())
    by_id = {e["item_id"]: e for e in data["elements"]}
    assert by_id[room.GlobalId]["quantities"]["area_m2"] == 42.5
    assert by_id[room.GlobalId]["props"]["long_name"] == "Küche"
    assert by_id[door.GlobalId]["quantities"]["width_m"] == pytest.approx(.9144 if imperial else .9)
    assert by_id[door.GlobalId]["storey"]["name"] == st.Name
    assert all(e["bbox_m"] is None and e["bbox_source"] is None for e in data["elements"])
    assert data['unit_provenance']['m_per_unit'] == pytest.approx(.3048 if imperial else .001)
    assert not ifc_index.open_properties(src).by_type("IfcCartesianPoint")
    assert point.id() > 0


def test_missing_units_are_unknown(tmp_path):
    f = ifcopenshell.file(schema="IFC4")
    f.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), OverallWidth=900.)
    f.write(str(tmp_path / "model.ifc"))
    ifc_index.process(tmp_path / "model.ifc", {"doc_id": "test"}, tmp_path)
    data = json.loads((tmp_path / "elements.json").read_text())
    assert not data["elements"][0]["quantities"]
    assert "does not declare length units" in data["warnings"][-1]


def test_bad_header_is_actionable(tmp_path):
    src = tmp_path / "bad.ifc"
    src.write_bytes(b"ISO-10303-21;")
    with pytest.raises(ValueError, match="Export the model again"):
        ifc_index.open_properties(src)


@pytest.mark.parametrize("name", ["Area", "Fläche", "Pinta-ala", "Areal"])
def test_typed_property_area_and_unrelated_values(tmp_path, name):
    f = ifcopenshell.file(schema="IFC4")
    units = f.create_entity("IfcUnitAssignment", [
        f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE"),
        f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")])
    f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), UnitsInContext=units)
    room = f.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new())
    props = [f.create_entity("IfcPropertySingleValue", Name=name, NominalValue=f.create_entity("IfcAreaMeasure", 12.5)),
             f.create_entity("IfcPropertySingleValue", Name="Area per person", NominalValue=f.create_entity("IfcAreaMeasure", 80.)),
             f.create_entity("IfcPropertySingleValue", Name="GrossArea", NominalValue=f.create_entity("IfcReal", 99.))]
    ps = f.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="Dimensions", HasProperties=props)
    f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[room], RelatingPropertyDefinition=ps)
    f.write(str(tmp_path / "model.ifc"))
    ifc_index.process(tmp_path / "model.ifc", {"doc_id": "test"}, tmp_path)
    e = json.loads((tmp_path / "elements.json").read_text())["elements"][0]
    assert e["quantities"] == {"area_m2": 12.5}
    assert e["quantity_source"] == {"area_m2": "property"}
