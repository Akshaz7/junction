"""Regressions from the six-file judge simulation; generated geometry labelled below."""
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from engine.answer import answer
from engine import analytics, honesty
from engine.solvers.data import Doc, Item

FLOOR = "What is the total floor area in square metres?"
BASE = "How many linear metres of baseboard do I need?"
SLAB = "What is the slab area by thickness?"
WALL = "What is the wall surface area per floor?"
SERVICES = "What is the total length of pipes or ducts, in metres?"
TRICK = "What is the fire rating of the doors in the third basement?"


@pytest.fixture(autouse=True)
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MODELS_COSTS_LOG", str(tmp_path / "costs.jsonl"))
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")


def write_plan(root, items=(), *, scale=None, kind="pdf"):
    """Small geometry generated for demo/testing, unless supplied from the real excerpt."""
    d = root / "test__drawing"
    d.mkdir(exist_ok=True)
    (d / "doc.json").write_text(json.dumps({"doc_id": d.name, "kind": kind, "title": "Test sheet", "pages": 1}))
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": d.name, "page": 1, "image": {"w": 1200, "h": 1000},
        "scale": scale or {"m_per_px": .01, "method": "dimension", "confidence": .9}, "items": list(items)}))
    return d


@pytest.mark.parametrize("kind", ["dxf", "raster", "pdf"])
def test_non_floor_plan_or_no_rooms_never_gets_an_invented_area(tmp_path, monkeypatch, kind):
    d = write_plan(tmp_path, [{"item_id": "shape", "kind": "other", "bbox_px": [0, 0, 500, 500], "props": {}, "conf": 1}], kind=kind)
    model = Mock(side_effect=AssertionError("No model should invent a floor area"))
    monkeypatch.setattr("engine.models.call", model)
    result = answer(FLOOR, [d.name])
    assert result["answer"]["abstained"] and result["answer"]["value"] is None
    assert "No room boundaries" in result["answer"]["text_md"]
    assert result["reasoning"]["confidence"]["pct"] == 0
    model.assert_not_called()


def test_trick_stops_without_ratings_codes_or_unrelated_advice(tmp_path, monkeypatch):
    d = write_plan(tmp_path)
    model = Mock(side_effect=AssertionError("Missing fire rating must stop"))
    monkeypatch.setattr("engine.models.call", model)
    result = answer(TRICK, [d.name])
    assert result["answer"]["text_md"] == "**The requested door fire rating is not recorded in this drawing.**"
    assert result["answer"]["abstained"] and not result["citations"]
    model.assert_not_called()


def test_abstention_is_terminal_even_with_force_enabled(tmp_path, monkeypatch):
    from engine import answer as dispatch
    monkeypatch.setenv("FORCE_ANSWER", "1")
    result = honesty.unavailable(TRICK, ["test"], "**Not recorded.**")
    monkeypatch.setattr(dispatch, "_answer_core", lambda *a, **k: result)
    forced = Mock(side_effect=AssertionError("Must not force an answer"))
    monkeypatch.setattr("engine.forced.forced_answer", forced)
    assert dispatch._answer_forced(TRICK, ["test"])["answer"] == result["answer"]
    forced.assert_not_called()


def test_real_fit_plan_does_not_sum_overlapping_detection_boxes(tmp_path):
    pm = json.loads(Path(__file__).with_name("fixtures").joinpath("honesty_fit_plan.json").read_text())
    d = write_plan(tmp_path, pm["items"], scale=pm["scale"])
    result = answer(BASE, [d.name])
    assert result["answer"]["value"] is None  # previously 83.1 m; no verified perimeter in these boxes
    assert result["answer"]["abstained"]
    assert "not wall boundaries" in result["answer"]["text_md"]


def test_polygon_baseboard_uses_outline_and_measured_door_width():
    # Generated for demo: L-shaped room, perimeter 16 m, one 1.2 m door.
    poly = [[0, 0], [400, 0], [400, 100], [100, 100], [100, 400], [0, 400]]
    room = Item("r", "room", bbox_px=[0, 0, 400, 400], polygon_px=poly)
    door = Item("d", "door", bbox_px=[140, -5, 260, 5], q={"width_m": 1.2})
    doc = Doc("test", "planmap", [room, door], scale={"m_per_px": .01, "method": "dimension", "confidence": .9})
    result = analytics.baseboard(BASE, doc, time.perf_counter())
    assert result["answer"]["value"] == pytest.approx(14.8)
    assert "minus 1 door" in result["answer"]["text_md"]


@pytest.mark.parametrize("q", [BASE, SERVICES, "What is the duct length in metres?", "What is the pipe length in metres?", "DN9999 length", "total duct lengths"])
def test_length_count_mismatch_is_rejected(q):
    result = honesty.unavailable(q, ["test"], "temporary")
    result["answer"].update(value=235, unit="count", abstained=False)
    assert honesty.validate_result(result, q)["answer"]["abstained"]


def test_count_with_a_length_filter_still_requests_a_count():
    assert not honesty.requests_length("How many ducts are longer than 3 metres?")


def test_duct_length_routes_to_ducts_not_pipes(tmp_path):
    items = [Item("d", "duct", bbox_px=[0, 0, 100, 10], q={"length_m": 3}),
             Item("p", "pipe", bbox_px=[0, 20, 100, 30], q={"length_m": 7})]
    doc = Doc("test", "planmap", items)
    duct = honesty.plan_services_length("total duct length in metres", doc, tmp_path)
    both = honesty.plan_services_length(SERVICES, doc, tmp_path)
    assert duct["answer"]["value"] == 3 and duct["answer"]["unit"] == "m"
    assert both["answer"]["value"] == 10
    assert duct["evidence"]["scene"]["highlight_item_ids"] == ["d"]
    assert duct["reasoning"]["confidence"]["label"] == "Estimate"


def test_duct_outline_is_not_a_centreline_and_missing_is_not_absent(tmp_path):
    item = Item("d", "duct", bbox_px=[0, 0, 100, 10], polygon_px=[[0, 0], [100, 0], [100, 10], [0, 10]])
    doc = Doc("test", "planmap", [item], scale={"m_per_px": .01, "method": "dimension"})
    res = honesty.plan_services_length(SERVICES, doc, tmp_path)
    assert res["answer"]["abstained"] and res["answer"]["value"] is None
    res = honesty.plan_services_length("duct length in metres", Doc("test", "planmap", []), tmp_path)
    assert "does not establish that none are drawn" in res["answer"]["text_md"]
    assert "No piping is drawn" not in res["answer"]["text_md"]


def test_pdf_mep_hook_consumes_calibrated_runs_without_pdf_ingestion(tmp_path):
    d = tmp_path / "test"; d.mkdir()
    (d / "mep-lengths.json").write_text(json.dumps({"runs": [{"item_id": "duct-a", "kind": "duct", "page": 1,
          "length_m": 8.4, "bbox_px": [0, 0, 100, 10], "source": "pdf_mep"}]}))
    res = honesty.plan_services_length("duct length in metres", Doc("test", "planmap", []), tmp_path)
    assert res["answer"]["value"] == 8.4 and res["citations"][0]["item_ids"] == ["duct-a"]


def test_slab_does_not_relabel_floor_area(tmp_path):
    d = write_plan(tmp_path, [{"item_id": "r", "kind": "room", "props": {"area_m2": 103.5}, "conf": 1}])
    res = answer(SLAB, [d.name])
    assert res["answer"]["abstained"] and res["answer"]["value"] is None
    assert "not recorded" in res["answer"]["text_md"]


def test_slab_thickness_never_comes_from_bbox_height():
    slab = Item("s", "slab", bbox_m=[[0, 0, 0], [10, .25, 10]], q={"area_m2": 100}, props={"ifc_class": "IfcSlab"})
    res = analytics.slab_by_type(SLAB, Doc("test", "ifc", [slab]), time.perf_counter())
    assert res["answer"]["abstained"] and res["answer"]["value"] is None


def test_slab_qto_depth_and_material_layers_form_distinct_groups():
    a = Item("a", "slab", q={"depth_m": .25, "area_m2": 100}, props={"ifc_class": "IfcSlab"})
    b = Item("b", "slab", q={"area_m2": 20}, props={"ifc_class": "IfcSlab", "material_layers": [{"thickness_m": .2}, {"thickness_m": .1}]})
    c = Item("c", "slab", q={"area_m2": 10}, props={"ifc_class": "IfcSlab"})
    res = analytics.slab_by_type(SLAB, Doc("test", "ifc", [a, b, c]), time.perf_counter())
    assert res["answer"]["value"] == 120
    assert "250 mm" in res["answer"]["text_md"] and "300 mm" in res["answer"]["text_md"]
    assert "1 slabs lack thickness" in res["answer"]["text_md"]
    assert set(res["evidence"]["scene"]["highlight_item_ids"]) == {"a", "b"}


def test_wall_area_estimate_states_height_and_subtracts_openings(tmp_path):
    # Generated for demo: 10 m × 2.7 m, both sides, less a 1 m × 2.1 m door on both faces.
    d = write_plan(tmp_path, [
        {"item_id": "w", "kind": "wall", "bbox_px": [0, 0, 1000, 10], "props": {}, "conf": .9},
        {"item_id": "d", "kind": "door", "bbox_px": [100, -5, 200, 15], "props": {"width_m": 1}, "conf": .9}])
    res = answer(WALL, [d.name])
    assert res["answer"]["value"] == pytest.approx(49.8)
    assert res["reasoning"]["confidence"]["label"] == "Estimate"
    assert "2.7 m (assumed" in res["answer"]["text_md"]
    assert any("2.7 m (assumed" in s["text"] for s in res["reasoning"]["steps"])
    assert res["wallarea"]["opening_m2"] == pytest.approx(4.2)
    assert res["citations"] and res["evidence"]["boxes"]


def test_no_wall_geometry_gets_sheet_wording(tmp_path):
    d = write_plan(tmp_path)
    res = answer(WALL, [d.name])
    assert res["answer"]["abstained"] and "from this sheet" in res["answer"]["text_md"]
    assert "IFC" not in res["answer"]["text_md"]
    (d / "planmap-1.json").unlink()  # site scan with no plan map, as in the HABS case
    missing = answer(WALL, [d.name])
    assert missing["answer"]["abstained"] and "from this sheet" in missing["answer"]["text_md"]
    assert "IFC" not in missing["reasoning"]["confidence"]["improve"]


def test_explanation_cannot_append_a_typical_fire_rating():
    from engine.explain import _ok
    assert not _ok("**Not recorded.** [1]", "**Not recorded.** Typical doors need 90 minutes. [1]")


def test_failed_ingest_reports_the_actual_limit_instead_of_guessing(tmp_path):
    d = write_plan(tmp_path)
    (d / "ingest.json").write_text(json.dumps({"status": "failed", "detail": "This server converts IFC files up to 15 MB."}))
    res = answer(FLOOR, [d.name])
    assert res["answer"]["abstained"] and "15 MB" in res["answer"]["text_md"]


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
@pytest.mark.parametrize("unit", ["metre", "foot"])
@pytest.mark.parametrize("source", ["layers", "qto"])
def test_original_ifc_thickness_units_and_schemas(tmp_path, schema, unit, source):
    """Tiny IFC generated for demo: no source geometry or model calls."""
    import ifcopenshell
    from engine.slab_quantities import with_source_thickness
    model = ifcopenshell.file(schema=schema)
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    if unit == "foot":
        dims = model.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0)
        factor = model.create_entity("IfcMeasureWithUnit", model.create_entity("IfcLengthMeasure", .3048), metre)
        length_unit = model.create_entity("IfcConversionBasedUnit", dims, "LENGTHUNIT", "FOOT", factor)
        scale = .3048
    else:
        length_unit, scale = metre, 1.
    units = model.create_entity("IfcUnitAssignment", [length_unit])
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), UnitsInContext=units)
    gid = ifcopenshell.guid.new()
    slab = model.create_entity("IfcSlab", GlobalId=gid, Name="generated for demo")
    if source == "layers":
        material = model.create_entity("IfcMaterial", Name="generated for demo")
        layers = [model.create_entity("IfcMaterialLayer", Material=material, LayerThickness=value / scale) for value in (.2, .05)]
        layer_set = model.create_entity("IfcMaterialLayerSet", MaterialLayers=layers)
        model.create_entity("IfcRelAssociatesMaterial", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[slab], RelatingMaterial=layer_set)
    else:
        depth = model.create_entity("IfcQuantityLength", Name="Depth", LengthValue=.25 / scale)
        qto = model.create_entity("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(), Name="Qto_SlabBaseQuantities", Quantities=[depth])
        model.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[slab], RelatingPropertyDefinition=qto)
    d = tmp_path / "test"; d.mkdir()
    model.write(str(d / "source.ifc"))
    original = Doc("test", "ifc", [Item(gid, "slab", q={"area_m2": 10}, props={"ifc_class": "IfcSlab"})])
    enriched = with_source_thickness(original, tmp_path)
    assert enriched.items[0].q["thickness_m"] == pytest.approx(.25)
    assert "thickness_m" not in original.items[0].q  # never mutate shared source/index
    assert analytics.slab_by_type(SLAB, enriched, time.perf_counter())["answer"]["value"] == 10


def test_overlapping_room_polygons_are_not_separate_perimeters():
    rooms = [Item(str(n), "room", bbox_px=[x, 0, x+200, 200], polygon_px=[[x, 0], [x+200, 0], [x+200, 200], [x, 200]]) for n, x in enumerate((0, 100))]
    doc = Doc("test", "planmap", rooms, scale={"m_per_px": .01, "method": "dimension"})
    result = analytics.baseboard(BASE, doc, time.perf_counter())
    assert result["answer"]["abstained"] and "overlap" in result["answer"]["text_md"]
