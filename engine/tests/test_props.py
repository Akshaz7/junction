"""F-PROPS: properties, scope, units, evidence and general text-grid links.

Generated IFCs and plan maps are test fixtures, generated for demo/testing only.
Real files are read-only; assertions derive expected dimensions from the existing
SI element index rather than hard-coding any model's counts or coordinates.
"""
import json
from pathlib import Path

import pytest

from engine import props

REPO = Path(__file__).resolve().parents[2]


def write_model(tmp_path, elements):
    d = tmp_path / "test__model"
    d.mkdir(exist_ok=True)
    (d / "elements.json").write_text(json.dumps(dict(elements=elements, storeys=[dict(name="Level 2", elevation_m=6)])))
    return "test__model"


def element(i, kind="door", pr=None, qty=None, name=None):
    return dict(item_id=i, kind=kind, name=name or i.upper(), props=pr or {}, quantities=qty or {},
                storey=dict(name="Level 2", elevation_m=6))


@pytest.fixture
def model(tmp_path):
    did = write_model(tmp_path, [
        element("d1", pr=dict(tag="D-104", fire_rating="EI30", is_external=True, acoustic_rating="32 dB"), qty=dict(width_m=1.0, height_m=2.1)),
        element("d2", pr=dict(tag="D-105", fire_rating="Not rated", is_external=False), qty=dict(width_m=.9)),
        element("d3", pr=dict(tag="D-106", fire_rating="Fire Rating")),
        element("wall1", "wall", dict(material="Timber; Insulation", is_external=True, load_bearing=True)),
        element("wall2", "wall", dict(material="Brick", is_external=False, load_bearing=False)),
        element("window1", "window", dict(ThermalTransmittance=1.2)),
        element("r1", "room", dict(WindowCount=0)),
        element("r2", "room"),
    ])
    return tmp_path, did


def ask(model, q):
    root, did = model
    r = props.answer(q, [did], root)
    assert r is not None
    assert r["cost"] == dict(usd_total=0.0, calls=[])
    return r


def ids(r):
    return {i for c in r["citations"] for i in c["item_ids"]}


def test_lookup_by_tag_and_missing_value(model):
    r = ask(model, "What is the fire rating of door D-104?")
    assert "EI30" in r["answer"]["text_md"] and ids(r) == {"d1"}
    assert r["reasoning"]["confidence"]["label"] == "Verified"
    r = ask(model, "What is the fire rating of door D-106?")
    assert "does not record fire ratings" in r["answer"]["text_md"]
    assert "0 of 1" in r["reasoning"]["steps"][1]["text"]
    assert not r["answer"]["abstained"]


def test_absent_tag_does_not_return_all(model):
    r = ask(model, "Fire rating of door D-999?")
    assert "No door matches" in r["answer"]["text_md"] and not ids(r)


@pytest.mark.parametrize("q,want", [("Which doors are wider than 900 mm?", {"d1"}),
                                   ("Which doors have width at least 900 mm?", {"d1", "d2"}),
                                   ("Which doors are wider than 36 inches?", {"d1"}),
                                   ("Which doors are narrower than 3 feet?", {"d2"})])
def test_thresholds_and_unknown_not_zero(model, q, want):
    r = ask(model, q)
    assert ids(r) == want
    assert r["answer"]["value"] == len(want)
    assert "1 lack width" in r["answer"]["text_md"]
    assert r["reasoning"]["confidence"]["label"] != "Verified"


def test_external_material_and_multiple_predicates(model):
    r = ask(model, "What are the external walls made of?")
    assert ids(r) == {"wall1"} and "Timber; Insulation" in r["answer"]["text_md"]
    assert "Brick" not in r["answer"]["text_md"]
    r = ask(model, "Which external fire-rated doors are wider than 900 mm?")
    assert ids(r) == {"d1"}


def test_rated_not_rated_unknown(model):
    assert ids(ask(model, "Which doors are fire-rated?")) == {"d1"}
    assert ids(ask(model, "Which doors are not fire-rated?")) == {"d2"}
    r = ask(model, "Are all doors fire-rated?")
    assert "cannot confirm" in r["answer"]["text_md"]
    assert "1 explicitly report no rating" in r["answer"]["text_md"]


def test_never_infer_escape_route_or_windowlessness(model):
    r = ask(model, "Are all doors on the escape route fire-rated?")
    assert "lack escape-route membership" in r["answer"]["text_md"]
    assert r["reasoning"]["confidence"]["label"] != "Verified"
    r = ask(model, "Which rooms have no window?")
    assert "cannot identify rooms" in r["answer"]["text_md"]


def test_false_is_a_recorded_property(model):
    r = ask(model, "What is the external status of door D-105?")
    assert "No" in r["answer"]["text_md"] and ids(r) == {"d2"}
    assert "1 of 1" in r["reasoning"]["steps"][1]["text"]


def test_u_value_and_grouping(model):
    r = ask(model, "What is the U-value of the windows?")
    assert "1.2 W/(m²·K)" in r["answer"]["text_md"]
    r = ask(model, "Group doors by acoustic rating")
    assert "32 dB" in r["answer"]["text_md"] and "Not recorded" in r["answer"]["text_md"]
    assert "2 of 3" in r["answer"]["text_md"]


def test_schedule_limits_scope_and_missing_fields(tmp_path):
    did = write_model(tmp_path, [element(f"d{i}", qty=dict(width_m=1)) for i in range(19)])
    r = ask((tmp_path, did), "Door schedule for level 2")
    assert "and 4 more" in r["answer"]["text_md"]
    assert r["answer"]["text_md"].count("1000 mm") == 15
    assert len(ids(r)) == 19
    assert "Not recorded" in r["answer"]["text_md"]
    r = ask((tmp_path, did), "Door schedule for level 999")
    assert "No matching level" in r["answer"]["text_md"] and not ids(r)


def test_unsupported_scope_does_not_get_simplified(model):
    root, did = model
    for q in ("Total length of external walls", "Doors wider than 900 mm near the stairs", "How many doors?", "Area of the rooms", "Which external doors or windows are rated?"):
        assert props.answer(q, [did], root) is None
    assert props.answer("Door schedule", [did, "other__model"], root) is None


@pytest.mark.parametrize("q", [
    "What materials are the doors and windows made of?",
    "Door schedule on level 1 and level 2",
    "Which doors have a fire rating of EI60?",
    "Which external doors have material Steel?",
    "What are the widths and fire ratings of doors?",
    "Which doors connect an office to a corridor and are fire-rated?",
    "What are the U-values and g-values of external windows, and how much heating energy would replacing them save?",
])
def test_unhandled_conditions_remain_for_other_routes(model, q):
    root, did = model
    assert props.answer(q, [did], root) is None


@pytest.mark.parametrize("q,want", [
    ("Which doors are not external?", {"d2"}),
    ("Which walls are non-load-bearing?", {"wall2"}),
    ("Which walls are not load-bearing?", {"wall2"}),
])
def test_negative_property_filters(model, q, want):
    assert ids(ask(model, q)) == want


def test_quoted_name_and_alphabetic_tag(tmp_path):
    did = write_model(tmp_path, [element("first", pr=dict(tag="MAIN", fire_rating="EI30"), name="Main entrance"),
                                 element("second", pr=dict(fire_rating="EI60"))])
    for q in ('What is the fire rating of door "Main entrance"?', "What does tag MAIN refer to?"):
        assert ids(ask((tmp_path, did), q)) == {"first"}


def test_false_rating_and_placeholders_are_not_positive(tmp_path):
    did = write_model(tmp_path, [element("first", pr=dict(fire_rating=False)),
                                 element("second", pr=dict(fire_rating="TBD"))])
    r = ask((tmp_path, did), "Which doors are not fire-rated?")
    assert ids(r) == {"first"} and r["answer"]["value"] == 1
    assert "1 lack fire rating" in r["answer"]["text_md"]
    r = ask((tmp_path, did), "Are all doors fire-rated?")
    assert "1 explicitly report no rating" in r["answer"]["text_md"]


def test_unreadable_original_is_not_verified_empty_model(tmp_path, monkeypatch):
    d = tmp_path / "upload__incomplete"
    d.mkdir()
    (d / "source.ifc").write_text("incomplete upload")
    monkeypatch.setattr(props, "_read_ifc", lambda *a: (_ for _ in ()).throw(ValueError("bad source")))
    assert props.answer("Door schedule", [d.name], tmp_path) is None


def make_ifc(tmp_path, schema="IFC4", imperial=False):
    import ifcopenshell
    import ifcopenshell.api.unit
    import ifcopenshell.guid
    f = ifcopenshell.file(schema=schema)
    guid = ifcopenshell.guid.new
    unit = ifcopenshell.api.unit.add_conversion_based_unit(f, name="foot") if imperial else f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    f.create_entity("IfcProject", GlobalId=guid(), UnitsInContext=f.create_entity("IfcUnitAssignment", Units=[unit]))
    door = f.create_entity("IfcDoor", GlobalId=guid(), Name="Ovi α", Tag="D-104", OverallWidth=3.0 if imperial else 1000., OverallHeight=7.0 if imperial else 2100.)
    type_class = "IfcDoorStyle" if schema == "IFC2X3" else "IfcDoorType"
    typ = f.create_entity(type_class, GlobalId=guid(), Name="Tür type", Tag="T-1")
    def pset(name, values):
        return f.create_entity("IfcPropertySet", GlobalId=guid(), Name=name, HasProperties=[f.create_entity("IfcPropertySingleValue", Name=k, NominalValue=f.create_entity("IfcLabel", v)) for k, v in values.items()])
    typ.HasPropertySets = [pset("Pset_DoorCommon", {"FireRating": "EI60", "AcousticRating": "35 dB", "Reference": "R-27"})]
    f.create_entity("IfcRelDefinesByType", GlobalId=guid(), RelatedObjects=[door], RelatingType=typ)
    f.create_entity("IfcRelDefinesByProperties", GlobalId=guid(), RelatedObjects=[door], RelatingPropertyDefinition=pset("Pset_DoorCommon", {"FireRating": "EI30"}))
    wall = f.create_entity("IfcWall", GlobalId=guid(), Name="Seinä")
    mat = f.create_entity("IfcMaterial", Name="Timber")
    layer = f.create_entity("IfcMaterialLayer", Material=mat, LayerThickness=100.)
    layer_set = f.create_entity("IfcMaterialLayerSet", MaterialLayers=[layer])
    f.create_entity("IfcRelAssociatesMaterial", GlobalId=guid(), RelatedObjects=[wall], RelatingMaterial=layer_set)
    # Explicit metre unit must override a millimetre/foot project unit on Qtos.
    metre = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    q = f.create_entity("IfcQuantityLength", Name="Width", LengthValue=1.25, Unit=metre)
    qset = f.create_entity("IfcElementQuantity", GlobalId=guid(), Name="Qto_WallBaseQuantities", Quantities=[q])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=guid(), RelatedObjects=[wall], RelatingPropertyDefinition=qset)
    d = tmp_path / "upload__generated"
    d.mkdir()
    f.write(str(d / "source.ifc"))
    return "upload__generated"


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
@pytest.mark.parametrize("imperial", [False, True])
def test_original_inheritance_materials_and_units(tmp_path, schema, imperial):
    did = make_ifc(tmp_path, schema, imperial)
    records, _, _ = props.index(did, tmp_path)
    door = next(r for r in records if r.item.kind == "door")
    wall = next(r for r in records if r.item.kind == "wall")
    assert door.values["fire_rating"] == "EI30"  # occurrence overrides type
    assert door.values["acoustic_rating"] == "35 dB"  # inherited
    assert door.values["width_m"] == pytest.approx(.9144 if imperial else 1.0)
    assert wall.values["material"] == "Timber"
    assert wall.values["width_m"] == pytest.approx(1.25)
    assert "R-27" in door.aliases and "T-1" in door.aliases
    r = ask((tmp_path, did), "What is the fire rating of door D-104?")
    assert "EI30" in r["answer"]["text_md"]
    assert "Pset_DoorCommon.FireRating" in r["citations"][0]["quote"]


def drawing(tmp_path, source="dxf", ambiguous=False, header="Mark", material="Material", rating="FireRating"):
    d = tmp_path / "drawing__generated"
    d.mkdir()
    items = []
    def text(label, bb, page=1):
        items.append(dict(item_id=f"text-{len(items)}", kind="text", label=label, bbox_px=bb, source=source, conf=.92, props={}))
    text("D12", [10, 20, 30, 30])  # on-plan occurrence
    text("OVILUETTELO", [200, 80, 350, 90])
    text(header, [200, 100, 240, 110])
    text(material, [280, 100, 350, 110])
    text(rating, [400, 100, 480, 110])
    text("D12", [200, 120, 240, 130])
    text("Timber", [280, 120, 340, 130])
    text("EI30", [400, 120, 440, 130])
    if ambiguous:
        text("D12", [200, 140, 240, 150])
        text("Steel", [280, 140, 340, 150])
        text("EI60", [400, 140, 440, 150])
    (d / "planmap-1.json").write_text(json.dumps(dict(page=1, items=items, scale=dict(method="dxf-units", m_per_px=.01, confidence=1))))
    return tmp_path, d.name


@pytest.mark.parametrize("header", ["Mark", "Tunnus", "Kennzeichen", "Beteckning"])
def test_drawing_tag_row_link_and_both_boxes(tmp_path, header):
    r = ask(drawing(tmp_path, header=header), "What is the fire rating of door D12?")
    assert "EI30" in r["answer"]["text_md"]
    assert len(r["citations"]) == len(r["evidence"]["boxes"]) == 3
    assert r["citations"][0]["quote"] == "D12"
    assert "Timber" in r["citations"][-1]["quote"]
    assert r["reasoning"]["confidence"]["label"] == "Verified"


def test_ocr_schedule_is_not_verified(tmp_path):
    r = ask(drawing(tmp_path, source="ocr"), "What does tag D12 refer to?")
    assert "Timber" in r["answer"]["text_md"]
    assert r["reasoning"]["confidence"]["label"] == "Estimate"


@pytest.mark.parametrize("header,material,rating", [("Mark", "Material", "Fire rating"),
    ("Tunnus", "Materiaali", "Paloluokka"), ("Kennzeichen", "Baustoff", "Feuerwiderstand"),
    ("Beteckning", "Material", "Brandklass")])
def test_translated_schedule_columns(tmp_path, header, material, rating):
    r = ask(drawing(tmp_path, header=header, material=material, rating=rating), "Fire rating of door D12?")
    assert "EI30" in r["answer"]["text_md"] and len(r["evidence"]["boxes"]) == 3


def test_missing_ocr_schedule_field_has_no_numeric_confidence(tmp_path):
    r = ask(drawing(tmp_path, source="ocr"), "Acoustic rating of door D12?")
    assert "does not record acoustic rating" in r["answer"]["text_md"]
    assert r["answer"]["confidence"] == r["reasoning"]["confidence"]["pct"] == 0


def test_ambiguous_schedule_does_not_pick_first(tmp_path):
    r = ask(drawing(tmp_path, ambiguous=True), "Fire rating of door D12?")
    assert "more than one" in r["answer"]["text_md"]
    assert "EI30" not in r["answer"]["text_md"]


def test_routing_keeps_exact_values_and_card(model, monkeypatch):
    from engine.answer import answer
    import engine.explain
    root, did = model
    monkeypatch.setenv("ARTIFACTS_DIR", str(root))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")
    monkeypatch.setattr(engine.explain, "explain", lambda *a, **k: pytest.fail("Property values must not go through the explanation model"))
    r = answer("What is the fire rating of door D-104?", [did])
    assert "EI30" in r["answer"]["text_md"]
    assert "1 of 1" in r["reasoning"]["steps"][1]["text"]
    assert r["reasoning"]["confidence"]["label"] == "Verified"
    import jsonschema
    jsonschema.validate(r, json.loads((REPO / "server/schemas/answer.schema.json").read_text()))


def test_scene_commands_keep_their_route_and_hidden_items_are_excluded(model, monkeypatch):
    from engine.answer import answer
    root, did = model
    monkeypatch.setenv("ARTIFACTS_DIR", str(root))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")
    r = answer("Hide external walls", [did])
    assert r["evidence"]["scene"]["commands"][0]["op"] == "hide"
    assert not any(t["step"] == "props" for t in r["trace"])
    r = answer("Door schedule", [did], scene_state=dict(hidden=["d1"]))
    assert ids(r) == {"d2", "d3"}  # the schedule request may carry no single value (fix-suite)


REAL = ["ifc_bench__ac20-arc", "ifc_models__bsc-esplanades-1807-ep-ar-v18", "ifc_bench__molio-arc",
        "ifc_bench__fzk-house-arc", "ifc_bench__dental-clinic-arc"]


@pytest.mark.parametrize("did", REAL)
def test_real_models_dimension_filter_schedule_and_missing_properties(did):
    root = REPO / "artifacts"
    path = root / did / "elements.json"
    if not path.exists():
        pytest.skip("Real IFC artifacts are not installed")
    rows = json.loads(path.read_text())["elements"]
    doors = [e for e in rows if e.get("kind") == "door"]
    expected = {e["item_id"] for e in doors if e.get("quantities", {}).get("width_m", 0) > .900000001}
    r = ask((root, did), "Which doors are wider than 900 mm?")
    assert r["answer"]["value"] == len(expected)
    assert ids(r) == expected if expected else ids(r) == {e["item_id"] for e in doors}
    r = ask((root, did), "Door schedule")
    assert r["answer"]["value"] == len(doors)
    assert len(ids(r)) == len(doors)
    r = ask((root, did), "What is the fire rating of the doors?")
    assert "Recorded fire rating" in r["answer"]["text_md"] or "does not record fire ratings" in r["answer"]["text_md"]


def test_area_questions_about_a_quoted_room_are_not_property_lookups():
    from engine.props import request
    assert request("What is the net floor area of the room 'ABIRUUM (304)' on '3.korrus', in m²?") is None


def test_imperial_question_shows_feet_inches_conversion(model):
    for q in ("What is the width of door D-104 in feet?", "What is the width and height of the doors in feet and inches?"):
        t = ask(model, q)["answer"]["text_md"]
        assert "1000 mm" in t and "3.281 ft = 3 ft 3.37 in" in t
    assert " ft = " not in ask(model, "What is the width of door D-104?")["answer"]["text_md"]


def test_imperial_thresholds_parse_feet_and_inches(model):
    assert ids(ask(model, "Which doors are wider than 2'-11.5\"?")) == {"d1"}
    assert ids(ask(model, "Which doors are narrower than 3 ft 0 in?")) == {"d2"}


def test_imperial_helpers():
    from engine import units
    assert units.feet_inches(1.0) == "3 ft 3.37 in" and units.feet_inches(0.3048) == "1 ft 0 in"
    assert units.normalize_imperial_question("wider than 12'-6\"") == "wider than 3810 mm"
    assert units.imperial_requested("area in ft²") and not units.imperial_requested("area in m2")


def test_imperial_routed_answer_is_not_scale_boilerplate(model, monkeypatch):
    from engine.answer import answer
    root, did = model
    monkeypatch.setenv("ARTIFACTS_DIR", str(root))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")
    r = answer("What is the width and height of the doors in feet and inches? Use the IFC dimensions, not a guessed image scale.", [did])
    t = r["answer"]["text_md"]
    assert "real-world size in metres" not in t and "3 ft 3.37 in" in t
