"""Small generated-for-demo IFC fixtures; never included in agreement data."""
import json

import ifcopenshell
import pytest

from engine.xcheck_ifc import _unit_factor, axis_length, build, ingest_lengths


def make_file(schema="IFC4", *, length_prefix=None):
    f = ifcopenshell.file(schema=schema)
    unit = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix=length_prefix, Name="METRE")
    f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="generated for demo", UnitsInContext=f.create_entity("IfcUnitAssignment", Units=[unit]))
    return f


def wall(f, points, quantity=5, own_unit=None):
    line = f.create_entity("IfcPolyline", Points=[f.create_entity("IfcCartesianPoint", Coordinates=tuple(float(x) for x in p)) for p in points])
    rep = f.create_entity("IfcShapeRepresentation", RepresentationIdentifier="Axis", RepresentationType="Curve2D", Items=[line])
    w = f.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="generated for demo", Representation=f.create_entity("IfcProductDefinitionShape", Representations=[rep]))
    q = f.create_entity("IfcQuantityLength", Name="Length", LengthValue=float(quantity), Unit=own_unit)
    pset = f.create_entity("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(), Name="Qto_WallBaseQuantities", Quantities=[q])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[w], RelatingPropertyDefinition=pset)
    return w


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
def test_axis_measurement_is_schema_independent(tmp_path, schema):
    f = make_file(schema)
    w = wall(f, [(0, 0), (3, 0), (3, 4)], quantity=7)
    p = tmp_path / "generated.ifc"; f.write(str(p))
    result = build(p, "generated", geometry=False)
    c = result["elements"][w.GlobalId][0]
    assert c["primary_value"] == c["value"] == 7 and c["agrees"]
    assert c["sources"][0]["geometry_method"] == "explicit model axis"


def test_millimetres_and_explicit_override(tmp_path):
    f = make_file(length_prefix="MILLI")
    metre = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    w = wall(f, [(0, 0), (3000, 4000)], quantity=5, own_unit=metre)
    p = tmp_path / "generated.ifc"; f.write(str(p))
    c = build(p, "generated", geometry=False)["elements"][w.GlobalId][0]
    assert c["primary_value"] == c["value"] == 5
    assert c["sources"][0]["si_factor"] == 1


def test_custom_imperial_unit_uses_conversion_factor_not_name(tmp_path):
    f = make_file()
    metre = f.by_type("IfcSIUnit")[0]
    conversion = f.create_entity("IfcMeasureWithUnit", ValueComponent=f.create_entity("IfcLengthMeasure", .3048), UnitComponent=metre)
    foot = f.create_entity("IfcConversionBasedUnit", Dimensions=f.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0), UnitType="LENGTHUNIT", Name="custom untranslated foot", ConversionFactor=conversion)
    f.by_type("IfcUnitAssignment")[0].Units = [foot]
    w = wall(f, [(0, 0), (10, 0)], quantity=10)
    p = tmp_path / "generated.ifc"; f.write(str(p))
    c = build(p, "generated", geometry=False)["elements"][w.GlobalId][0]
    assert c["value"] == pytest.approx(3.048) and c["primary_value"] == pytest.approx(3.048)


def test_no_project_unit_does_not_assume_metres(tmp_path):
    f = ifcopenshell.file()
    wall(f, [(0, 0), (3, 4)])
    p = tmp_path / "generated.ifc"; f.write(str(p))
    result = build(p, "generated", geometry=False)
    assert result["elements"] == {} and "No project length unit" in result["skipped"][0]["reason"]


def test_ingest_hook_writes_json_without_native_geometry(tmp_path, monkeypatch):
    import ifcopenshell.geom
    def forbidden(*args):
        raise AssertionError("Ingest length checks must not triangulate")
    monkeypatch.setattr(ifcopenshell.geom, "create_shape", forbidden)
    f = make_file(); w = wall(f, [(0, 0), (3, 4)])
    p = tmp_path / "generated.ifc"; f.write(str(p))
    ingest_lengths(p, "generated", tmp_path)
    result = json.loads((tmp_path / "xcheck.json").read_text())
    assert result["elements"][w.GlobalId][0]["agrees"]


def test_straight_sweep_length_is_not_vertical_wall_height():
    f = make_file()
    profile = f.create_entity("IfcCircleProfileDef", ProfileType="AREA", Radius=.1)
    extrusion = f.create_entity("IfcExtrudedAreaSolid", SweptArea=profile, ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0., 0., 5.)), Depth=5.)
    rep = f.create_entity("IfcShapeRepresentation", RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[extrusion])
    definition = f.create_entity("IfcProductDefinitionShape", Representations=[rep])
    pipe = f.create_entity("IfcPipeSegment", GlobalId=ifcopenshell.guid.new(), Representation=definition)
    w = f.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Representation=definition)
    assert axis_length(pipe, 1)[0] == 5
    assert axis_length(w, 1) is None


def test_unit_prefix_uses_dimensional_power():
    f = make_file()
    area = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Prefix="MILLI", Name="SQUARE_METRE")
    volume = f.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Prefix="MILLI", Name="CUBIC_METRE")
    assert _unit_factor(area, 2) == pytest.approx(1e-6)
    assert _unit_factor(volume, 3) == pytest.approx(1e-9)
