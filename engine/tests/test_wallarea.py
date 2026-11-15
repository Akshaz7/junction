"""Generated geometry for tests only; no sample drawing is used as a fixture."""
import json
import math

import pytest

from engine import wallarea as W


def model_file(tmp_path, *, schema="IFC4", unit="metre", external=False,
               openings=(), height=3., length=10., lean=0., floors=(0.,), boundary=False,
               axis=True, qto=True, rotation=0.):
    import ifcopenshell
    from ifcopenshell.guid import new
    f = ifcopenshell.file(schema=schema)
    factor = 0.3048 if unit == "foot" else .001 if unit == "mm" else 1.
    def point(coords):
        return f.create_entity("IfcCartesianPoint", Coordinates=tuple(float(x) / factor for x in coords))
    def direction(coords):
        return f.create_entity("IfcDirection", DirectionRatios=tuple(float(x) for x in coords))
    def p3(coords=(0, 0, 0), rot=0.):
        return f.create_entity("IfcAxis2Placement3D", Location=point(coords), Axis=direction((0, 0, 1)),
                               RefDirection=direction((math.cos(rot), math.sin(rot), 0)))
    def place(coords=(0, 0, 0), parent=None, rot=0.):
        return f.create_entity("IfcLocalPlacement", PlacementRelTo=parent, RelativePlacement=p3(coords, rot))
    context = f.create_entity("IfcGeometricRepresentationContext", ContextType="Model", CoordinateSpaceDimension=3,
                              Precision=1e-6 / factor, WorldCoordinateSystem=p3())
    metre = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE", Prefix="MILLI" if unit == "mm" else None)
    sqmetre = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
    lengthunit = metre
    areaunit = sqmetre
    if unit == "foot":
        dim = f.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0)
        lengthunit = f.create_entity("IfcConversionBasedUnit", Dimensions=dim, UnitType="LENGTHUNIT", Name="FOOT",
                                    ConversionFactor=f.create_entity("IfcMeasureWithUnit", f.create_entity("IfcLengthMeasure", factor), metre))
        adim = f.create_entity("IfcDimensionalExponents", 2, 0, 0, 0, 0, 0, 0)
        areaunit = f.create_entity("IfcConversionBasedUnit", Dimensions=adim, UnitType="AREAUNIT", Name="SQUARE FOOT",
                                  ConversionFactor=f.create_entity("IfcMeasureWithUnit", f.create_entity("IfcAreaMeasure", factor ** 2), sqmetre))
    f.create_entity("IfcProject", GlobalId=new(), Name="generated for demo: test only",
                    RepresentationContexts=[context], UnitsInContext=f.create_entity("IfcUnitAssignment", Units=[lengthunit, areaunit]))
    building = f.create_entity("IfcBuilding", GlobalId=new(), Name="Generated test building", ObjectPlacement=place())
    storeys = [f.create_entity("IfcBuildingStorey", GlobalId=new(), Name=f"Floor {i}", Elevation=z / factor,
                              ObjectPlacement=place((0, 0, z))) for i, z in enumerate(floors)]
    f.create_entity("IfcRelAggregates", GlobalId=new(), RelatingObject=building, RelatedObjects=storeys)
    def solid(l, t, h, lean=0.):
        pos = f.create_entity("IfcAxis2Placement2D", Location=point((l / 2, 0)))
        profile = f.create_entity("IfcRectangleProfileDef", ProfileType="AREA", Position=pos, XDim=l / factor, YDim=t / factor)
        return f.create_entity("IfcExtrudedAreaSolid", SweptArea=profile, Position=p3(),
                               ExtrudedDirection=direction((0, lean / h, 1)), Depth=math.hypot(h, lean) / factor)
    def representation(body, include_axis=False):
        reps = [f.create_entity("IfcShapeRepresentation", ContextOfItems=context, RepresentationIdentifier="Body",
                                 RepresentationType="SweptSolid", Items=[body])]
        if include_axis:
            curve = f.create_entity("IfcPolyline", Points=[point((0, 0)), point((length, 0))])
            reps.append(f.create_entity("IfcShapeRepresentation", ContextOfItems=context, RepresentationIdentifier="Axis", RepresentationType="Curve2D", Items=[curve]))
        return f.create_entity("IfcProductDefinitionShape", Representations=reps)
    wall = f.create_entity("IfcWall", GlobalId=new(), Name="Generated wall", ObjectPlacement=place((20, 30, 0), rot=rotation),
                           Representation=representation(solid(length, .2, height, lean), axis))
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=new(), RelatedElements=[wall], RelatingStructure=storeys[0])
    if external is not None:
        prop = f.create_entity("IfcPropertySingleValue", Name="IsExternal", NominalValue=f.create_entity("IfcBoolean", external))
        pset = f.create_entity("IfcPropertySet", GlobalId=new(), Name="Pset_WallCommon", HasProperties=[prop])
        f.create_entity("IfcRelDefinesByProperties", GlobalId=new(), RelatedObjects=[wall], RelatingPropertyDefinition=pset)
    for i, (x, width, h) in enumerate(openings):
        opening = f.create_entity("IfcOpeningElement", GlobalId=new(), Name=f"Void {i}", ObjectPlacement=place((x, 0, 0), wall.ObjectPlacement),
                                  Representation=representation(solid(width, .5, h)))
        f.create_entity("IfcRelVoidsElement", GlobalId=new(), RelatingBuildingElement=wall, RelatedOpeningElement=opening)
        door = f.create_entity("IfcDoor", GlobalId=new(), Name=f"Door {i}", OverallWidth=width / factor, OverallHeight=h / factor)
        f.create_entity("IfcRelFillsElement", GlobalId=new(), RelatingOpeningElement=opening, RelatedBuildingElement=door)
    if qto:
        quantities = [f.create_entity("IfcQuantityArea", Name="GrossSideArea", AreaValue=length * height / (factor ** 2 if unit == "foot" else 1)),
                      f.create_entity("IfcQuantityArea", Name="NetSideArea", AreaValue=(length * height - sum(w * h for _, w, h in openings)) / (factor ** 2 if unit == "foot" else 1))]
        qty = f.create_entity("IfcElementQuantity", GlobalId=new(), Name="Qto_WallBaseQuantities", Quantities=quantities)
        f.create_entity("IfcRelDefinesByProperties", GlobalId=new(), RelatedObjects=[wall], RelatingPropertyDefinition=qty)
    if boundary:
        room = f.create_entity("IfcSpace", GlobalId=new(), Name="101", LongName="Test room", ObjectPlacement=wall.ObjectPlacement)
        plane_pos = f.create_entity("IfcAxis2Placement3D", Location=point((0, -.1, 0)), Axis=direction((0, -1, 0)), RefDirection=direction((1, 0, 0)))
        outer = f.create_entity("IfcPolyline", Points=[point(p) for p in [(0, 0), (length, 0), (length, height), (0, height), (0, 0)]])
        surface = f.create_entity("IfcCurveBoundedPlane", BasisSurface=f.create_entity("IfcPlane", Position=plane_pos), OuterBoundary=outer, InnerBoundaries=[])
        geom = f.create_entity("IfcConnectionSurfaceGeometry", SurfaceOnRelatingElement=surface)
        f.create_entity("IfcRelSpaceBoundary", GlobalId=new(), RelatingSpace=room, RelatedBuildingElement=wall, ConnectionGeometry=geom,
                        PhysicalOrVirtualBoundary="PHYSICAL", InternalOrExternalBoundary="EXTERNAL" if external else "INTERNAL")
    path = tmp_path / "generated-test.ifc"
    f.write(str(path))
    return path


@pytest.mark.parametrize("schema,unit", [("IFC2X3", "metre"), ("IFC4", "metre"), ("IFC4X3", "mm"), ("IFC4", "foot")])
def test_true_side_areas_units_and_quantity_crosscheck(tmp_path, schema, unit):
    r = W.measure_ifc(model_file(tmp_path, schema=schema, unit=unit, openings=[(2, 1, 2)], rotation=.7))
    assert not r["skipped"]
    w, = r["walls"]
    assert w["gross_m2"] == pytest.approx(60)
    assert w["net_m2"] == pytest.approx(56)
    assert w["opening_m2"] == pytest.approx(4)
    assert w["openings"][0]["deducted_m2"] == pytest.approx(4)
    assert max(c["difference_pct"] for c in w["checks"]) < 1e-6


def test_overlapping_openings_consumed_once(tmp_path):
    r = W.measure_ifc(model_file(tmp_path, openings=[(2, 2, 2), (3, 2, 2)]))
    w, = r["walls"]
    assert w["net_m2"] == pytest.approx(48)
    assert w["opening_m2"] == pytest.approx(12)
    assert sum(o["deducted_m2"] for o in w["openings"]) == pytest.approx(12)
    assert any(c["difference_pct"] > 0 for c in w["checks"] if c["quantity"] == "NetSideArea")


def test_multistorey_wall_clipped_at_floor_planes(tmp_path):
    r = W.measure_ifc(model_file(tmp_path, height=6, floors=(0, 3), openings=[(2, 1, 4)]))
    w, = r["walls"]
    a, b = w["floors"]
    assert [a["gross_m2"], b["gross_m2"]] == pytest.approx([60, 60])
    assert [a["net_m2"], b["net_m2"]] == pytest.approx([54, 58])
    assert [p["deducted_m2"] for p in w["openings"][0]["floors"]] == pytest.approx([6, 2])


def test_real_sloped_surface_not_vertical_projection(tmp_path):
    r = W.measure_ifc(model_file(tmp_path, lean=1.5, qto=False))
    w, = r["walls"]
    assert w["gross_m2"] == pytest.approx(2 * 10 * math.hypot(3, 1.5))
    assert w["height_m"] == pytest.approx(3)


def test_external_room_face_and_boundary_area_cut_by_real_void(tmp_path):
    r = W.measure_ifc(model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)], rotation=.6))
    w, = r["walls"]
    assert w["inside_side"] is not None
    floor, = w["floors"]
    assert floor["facade_m2"] == pytest.approx(28)
    assert floor["external_inside_m2"] == pytest.approx(28)
    room, = w["rooms"]
    assert room["gross_m2"] == pytest.approx(30)
    assert room["net_m2"] == pytest.approx(28)


def test_missing_external_classification_and_missing_axis_are_explicit(tmp_path):
    r = W.measure_ifc(model_file(tmp_path, external=None, axis=False, qto=False))
    w, = r["walls"]
    assert w["is_external"] is None and w["axis_source"] == "inferred from body"
    assert w["floors"][0]["facade_m2"] is None
    assert w["checks"] == []


def test_analytic_curved_wall_faces(tmp_path):
    import ifcopenshell
    path = model_file(tmp_path, qto=False)
    f = ifcopenshell.open(str(path))
    wall = f.by_type("IfcWall")[0]
    def pt(x, y):
        return f.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y)))
    def circle(radius):
        return f.create_entity("IfcCircle", Position=f.create_entity("IfcAxis2Placement2D", Location=pt(0, 0)), Radius=radius)
    def arc(radius, start, end, same=True):
        return f.create_entity("IfcTrimmedCurve", BasisCurve=circle(radius), Trim1=[f.create_entity("IfcParameterValue", start)],
                               Trim2=[f.create_entity("IfcParameterValue", end)], SenseAgreement=same, MasterRepresentation="PARAMETER")
    profile = f.create_entity("IfcArbitraryProfileDefWithVoids", ProfileType="AREA", OuterCurve=circle(5.1), InnerCurves=[circle(4.9)])
    body, axis = wall.Representation.Representations
    body.Items[0].SweptArea = profile
    axis.Items = [circle(5.)]
    f.write(str(path))
    result = W.measure_ifc(path)
    assert not result["skipped"]
    w, = result["walls"]
    assert w["curved"]
    assert w["gross_m2"] == pytest.approx(2 * 2 * math.pi * 5 * 3, rel=1e-8)


def indexed_doc(tmp_path, path):
    import ifcopenshell
    f = ifcopenshell.open(str(path))
    d = tmp_path / "test-building"
    d.mkdir(exist_ok=True)
    (d / "doc.json").write_text(json.dumps({"kind": "ifc", "files": {"ifc": str(path)}}))
    elements = [{"item_id": e.GlobalId, "name": e.Name, "kind": "wall" if e.is_a("IfcWall") else "door" if e.is_a("IfcDoor") else "room",
                 "props": {"long_name": getattr(e, "LongName", None)}} for cls in ("IfcWall", "IfcDoor", "IfcSpace") for e in f.by_type(cls)]
    (d / "elements.json").write_text(json.dumps({"elements": elements}))
    return d.name


def test_full_dispatch_evidence_reasoning_and_csv_table(tmp_path, monkeypatch):
    from engine.answer import answer
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)]))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    res = answer("How many plasterboard sheets do I need, with 10% waste? Per wall take-off.", [did])
    assert res["answer"]["value"] == 11
    assert res["answer"]["unit"] == "count"
    assert res["wallarea"]["sheet_count"] == 11
    assert res["wallarea"]["order_area_m2"] == pytest.approx(30.8)
    assert len(res["evidence"]["scene"]["highlight_item_ids"]) == 3  # wall, opening, door
    assert len({i for c in res["citations"] for i in c["item_ids"]}) == 3
    assert "| Item | Quantity | Unit | Source |" in res["answer"]["text_md"]
    assert {s["title"] for s in res["reasoning"]["steps"]} == {"Measured", "Deducted", "Checked", "Uncertainty"}
    assert res["cost"]["usd_total"] == 0
    assert res["reasoning"]["confidence"]["label"] == "Verified"


def test_no_orientation_uses_bounded_midpoint_not_building_centre(tmp_path):
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True))
    res = W.answer("What is the facade area?", [did], tmp_path)
    assert res["answer"]["value"] == pytest.approx(30)
    assert res["wallarea"]["orientation_unresolved"]
    assert "midpoint" in res["reasoning"]["steps"][-1]["text"]


def test_room_finish_never_uses_room_floor_area(tmp_path):
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)]))
    res = W.answer("What is the net wall area in room 101?", [did], tmp_path)
    assert res["answer"]["value"] == pytest.approx(28)


def test_invalid_source_and_no_geometry_do_not_call_reader(tmp_path, monkeypatch):
    from engine.answer import answer
    d = tmp_path / "bad"; d.mkdir()
    (d / "doc.json").write_text(json.dumps({"kind": "ifc", "files": {"ifc": "source.ifc"}}))
    (d / "source.ifc").write_text("not an IFC")
    monkeypatch.setenv("MODELS_FAKE", "1"); monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    res = answer("Net wall area per floor", ["bad"])
    assert res["answer"]["value"] is None
    assert res["answer"]["abstained"] is True
    assert res["cost"]["usd_total"] == 0
    assert res["reasoning"]["confidence"]["label"] == "Estimate"


def test_scaled_plan_estimate_defaults_and_union_deductions(tmp_path):
    d = tmp_path / "plan"; d.mkdir()
    items = [{"item_id": "w", "kind": "wall", "polygon_px": [[0, 0], [1000, 0]], "props": {"is_external": False}},
             {"item_id": "d", "kind": "door", "bbox_px": [100, -10, 200, 10], "props": {"width_m": 1, "host_wall_id": "w"}},
             {"item_id": "d2", "kind": "door", "bbox_px": [150, -10, 250, 10], "props": {"width_m": 1, "host_wall_id": "w"}}]
    (d / "planmap-1.json").write_text(json.dumps({"page": 1, "scale": {"m_per_px": .01, "method": "dxf-units"}, "items": items}))
    res = W.answer("How much plasterboard do I need?", ["plan"], tmp_path)
    assert res["answer"]["value"] == pytest.approx(54 - 2 * 1.5 * 2.1)
    assert res["reasoning"]["confidence"]["label"] == "Estimate"
    assert res["wallarea"]["margin_m2"] is None
    assert "2.7" in res["answer"]["text_md"]
    assert res["wallarea"]["waste_pct"] == 0
    res2 = W.answer("Wall area assuming height 3 m", ["plan"], tmp_path)
    assert res2["answer"]["value"] == pytest.approx(60 - 2 * 1.5 * 2.1)


@pytest.mark.parametrize("question", ["How many walls?", "What material is the facade made of?", "What is the room floor area?", "What is the wall thickness?"])
def test_route_does_not_capture_unrelated_questions(question):
    assert not W.wants_wallarea(question)


def test_multiple_body_solids_are_unioned_not_summed(tmp_path):
    import ifcopenshell
    from ifcopenshell.util.element import copy_deep
    path = model_file(tmp_path)
    f = ifcopenshell.open(str(path))
    body = f.by_type("IfcWall")[0].Representation.Representations[0]
    first = body.Items[0]
    second = copy_deep(f, first)
    first.SweptArea.YDim = second.SweptArea.YDim = .1
    first.SweptArea.Position.Location.Coordinates = (5., -.05)
    second.SweptArea.Position.Location.Coordinates = (5., .05)
    body.Items = [first, second]
    f.write(str(path))
    result = W.measure_ifc(path)
    assert not result["skipped"]
    assert result["walls"][0]["gross_m2"] == pytest.approx(60)


def test_optional_ifc2x3_boundary_holes_can_be_absent(tmp_path):
    import ifcopenshell
    path = model_file(tmp_path, schema="IFC2X3", external=True, boundary=True)
    f = ifcopenshell.open(str(path))
    f.by_type("IfcCurveBoundedPlane")[0].InnerBoundaries = None
    f.write(str(path))
    result = W.measure_ifc(path)
    assert not result["skipped"]
    assert result["walls"][0]["rooms"][0]["net_m2"] == pytest.approx(30)


def test_missing_units_are_never_silently_metres(tmp_path):
    import ifcopenshell
    path = model_file(tmp_path)
    f = ifcopenshell.open(str(path))
    f.by_type("IfcProject")[0].UnitsInContext = None
    f.write(str(path))
    with pytest.raises(W.MeasurementUnavailable, match="length unit"):
        W.measure_ifc(path)


def test_gross_request_and_all_three_face_splits(tmp_path):
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)]))
    res = W.answer("Gross wall area per floor", [did], tmp_path)
    assert res["answer"]["value"] == pytest.approx(60)
    assert "gross area" in res["answer"]["text_md"]
    split, = res["wallarea"]["face_splits"]
    assert split["facade"]["net_m2"] == pytest.approx(28)
    assert split["external_inside"]["net_m2"] == pytest.approx(28)
    assert split["internal_both"]["net_m2"] == 0
    assert "outside of external walls" in res["answer"]["text_md"]


def test_filter_and_unmatched_floor_never_return_whole_model(tmp_path):
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True))
    res = W.answer("Net wall area of internal walls", [did], tmp_path)
    assert res["answer"]["value"] is None
    res = W.answer("Net wall area of floor 99", [did], tmp_path)
    assert res["answer"]["value"] is None
    assert "No matching floor" in res["answer"]["text_md"]


def test_per_room_table_and_wall_specific_citation(tmp_path):
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)]))
    res = W.answer("Net wall area per room", [did], tmp_path)
    assert res["answer"]["value"] == pytest.approx(28)
    assert "Test room · net" in res["answer"]["text_md"]
    res = W.answer("Net wall area per wall take-off", [did], tmp_path)
    assert "{wall:" not in res["answer"]["text_md"]
    assert "door void 1" in res["answer"]["text_md"]
    assert "already deducted" in res["answer"]["text_md"]
    assert len(res["citations"][0]["item_ids"]) == 3


def test_cache_invalidates_when_same_upload_path_changes(tmp_path):
    path = model_file(tmp_path)
    first = W.load_ifc(path)
    model_file(tmp_path, length=5)
    second = W.load_ifc(path)
    assert first["walls"][0]["gross_m2"] == pytest.approx(60)
    assert second["walls"][0]["gross_m2"] == pytest.approx(30)


def test_answer_is_serializable_and_matches_contract_schema(tmp_path):
    from pathlib import Path
    from jsonschema import validate
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)]))
    res = W.answer("Net wall area per wall", [did], tmp_path)
    restored = json.loads(json.dumps(res, allow_nan=False))
    schema = json.loads((Path(__file__).resolve().parents[2] / "server/schemas/answer.schema.json").read_text())
    validate(restored, schema)


def test_facade_area_of_ground_floor_is_not_a_room_filter(tmp_path):
    did = indexed_doc(tmp_path, model_file(tmp_path, external=True, boundary=True, openings=[(2, 1, 2)]))
    res = W.answer("What is the facade area of the ground floor?", [did], tmp_path)
    assert res["answer"]["value"] == pytest.approx(28)
    res = W.answer("Net wall area of external walls", [did], tmp_path)
    assert res["answer"]["value"] == pytest.approx(56)
