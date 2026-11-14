"""General regressions from judge QA. All fixtures here are generated for testing."""
import json
import time

import pytest

from engine import mep, props
from engine.order import answer_order
from engine.revision_compare import comparison_answer
from engine.solvers.data import Doc, Item


def store(root, did, name, data):
    target = root / did
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_text(json.dumps(data))


def services(root, n=2, kind="pipe", did="upload"):
    rows = [dict(id=f"run-{i}", k=kind, st="M", t="Run", d=None, L=2.5, ls="quantity") for i in range(n)]
    store(root, did, "mep.json", dict(version=mep.MEP_VERSION, services=rows, structure=[]))
    return Doc(did, "ifc", [Item(r["id"], "mep_other", storey="M") for r in rows],
               storeys=[dict(name="M", elevation_m=0)])


@pytest.mark.parametrize("kind,noun", [("pipe", "pipe"), ("duct", "duct"), ("cable_tray", "cable tray")])
@pytest.mark.parametrize("wording", ["How many {noun} segments are recorded?", "Count {noun} segments on storey M."])
def test_mep_counts_objects_even_with_length_unit_in_storey_name(tmp_path, monkeypatch, kind, noun, wording):
    doc = services(tmp_path, kind=kind)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    result = mep.answer(wording.format(noun=noun), doc, time.perf_counter())
    assert (result["answer"]["value"], result["answer"]["unit"]) == (2, "count")
    assert {i for c in result["citations"] for i in c["item_ids"]} == {"run-0", "run-1"}


@pytest.mark.parametrize("wording", ["How many m of pipe?", "How many metres of pipe?", "How many meters of pipe?",
                                    "What is the number of linear metres of pipe?", "What is the total pipe length?"])
def test_mep_length_units_do_not_become_object_counts(tmp_path, monkeypatch, wording):
    doc = services(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    result = mep.answer(wording, doc, time.perf_counter())
    assert (result["answer"]["value"], result["answer"]["unit"]) == (5, "m")


def test_mep_cache_separates_artifact_roots_and_cites_entire_large_total(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    doc = services(a, n=3100)
    other = services(b, n=3)
    monkeypatch.setenv("ARTIFACTS_DIR", str(a))
    result = mep.answer("How many pipes?", doc, time.perf_counter())
    assert result["answer"]["value"] == 3100
    assert len({i for c in result["citations"] for i in c["item_ids"]}) == 3100
    monkeypatch.setenv("ARTIFACTS_DIR", str(b))
    assert mep.answer("How many pipes?", other, time.perf_counter())["answer"]["value"] == 3


@pytest.mark.parametrize("noun,kind", [("light fittings", "light"), ("pipe fittings", "pipe_fitting"), ("duct fittings", "duct_fitting")])
def test_compound_service_nouns_do_not_include_unrelated_fittings(tmp_path, monkeypatch, noun, kind):
    doc = services(tmp_path, kind=kind)
    path = tmp_path / doc.doc_id / "mep.json"
    data = json.loads(path.read_text())
    data["services"].append(dict(data["services"][0], id="other", k="cable_fitting"))
    path.write_text(json.dumps(data))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    assert mep.answer(f"How many {noun}?", doc, time.perf_counter())["answer"]["value"] == 2


def test_legacy_pipe_extract_uses_selected_root_and_counts_segments(tmp_path, monkeypatch):
    from engine.analytics import piping
    doc = Doc("upload", "ifc", [Item("a", "mep_other"), Item("b", "mep_other")])
    store(tmp_path, doc.doc_id, "piping.json", dict(pipes=[
        dict(item_id="a", length_m=3.5, dn_mm=50), dict(item_id="b", length_m=1.25, dn_mm=50)]))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    result = piping("How many pipe segments are recorded?", doc, time.perf_counter())
    assert (result["answer"]["value"], result["answer"]["unit"]) == (2, "count")
    length = piping("How many metres of piping?", doc, time.perf_counter())
    assert (length["answer"]["value"], length["answer"]["unit"]) == (4.75, "m")


@pytest.mark.parametrize("noun", ["doors", "windows"])
@pytest.mark.parametrize("n", [0, 1, 11])
def test_order_recorded_count_is_not_a_room_and_zero_has_source(tmp_path, noun, n):
    doc = Doc("upload", "ifc", [Item(str(i), noun[:-1]) for i in range(n)])
    question = f"How many {noun} should I order for the recorded {noun[:-1]} count plus a 10% spare allowance, rounded up?"
    result = answer_order(question, doc, root=tmp_path)
    import math
    assert result["answer"]["value"] == math.ceil(n * 1.1)
    assert result["citations"]
    assert "not in this file" not in result["answer"]["text_md"]


def test_missing_fire_rating_counts_presence_instead_of_summarising(tmp_path):
    store(tmp_path, "upload", "elements.json", dict(elements=[
        dict(item_id="rated", kind="door", props=dict(fire_rating="EI60")),
        dict(item_id="unrated", kind="door", props=dict(fire_rating="Not rated")),
        dict(item_id="missing", kind="door"),
    ]))
    missing = props.answer("How many door objects have no fire rating recorded?", ["upload"], tmp_path)
    assert missing["answer"]["value"] == 1
    assert {i for c in missing["citations"] for i in c["item_ids"]} == {"missing"}
    recorded = props.answer("How many doors have a recorded fire rating?", ["upload"], tmp_path)
    assert recorded["answer"]["value"] == 2  # 'Not rated' is recorded, not missing.


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
@pytest.mark.parametrize("imperial", [False, True])
def test_overall_width_is_source_dimension_not_index_estimate(tmp_path, schema, imperial):
    import ifcopenshell
    import ifcopenshell.api.unit
    import ifcopenshell.guid
    model = ifcopenshell.file(schema=schema)
    guid = ifcopenshell.guid.new
    unit = ifcopenshell.api.unit.add_conversion_based_unit(model, name="foot") if imperial else model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    model.create_entity("IfcProject", GlobalId=guid(), UnitsInContext=model.create_entity("IfcUnitAssignment", Units=[unit]))
    narrow = model.create_entity("IfcDoor", GlobalId=guid(), OverallWidth=2.5 if imperial else 800.)
    model.create_entity("IfcDoor", GlobalId=guid(), OverallWidth=0.)
    model.create_entity("IfcDoor", GlobalId=guid())
    target = tmp_path / "upload"
    target.mkdir()
    model.write(str(target / "source.ifc"))
    # A generic index measurement differs from the explicitly requested source field.
    store(tmp_path, "upload", "elements.json", dict(elements=[dict(item_id=narrow.GlobalId, kind="door", quantities=dict(width_m=1.2))]))
    result = props.answer("How many doors have a recorded overall width strictly below 0.9 metres?", ["upload"], tmp_path)
    assert result["answer"]["value"] == 1
    assert {i for c in result["citations"] for i in c["item_ids"]} == {narrow.GlobalId}
    assert "lack overall width" in result["answer"]["text_md"]


@pytest.mark.parametrize("old,new", [(0, 0), (0, 2), (3, 1), (4, 4)])
def test_net_revision_count_is_signed_and_independent_of_other_changes(tmp_path, old, new):
    for did, n in (("first", old), ("second", new)):
        store(tmp_path, did, "elements.json", dict(elements=[
            dict(item_id=f"{did}-{i}", kind="door", quantities=dict(width_m=1 if did == "first" else 2)) for i in range(n)]))
    q = "Comparing the first model with the second model, what is the net change in recorded door count? Give second minus first."
    result = comparison_answer(q, ["first", "second"], tmp_path)
    assert result["answer"]["value"] == new - old
    reverse = comparison_answer(q.replace("second minus first", "first minus second"), ["first", "second"], tmp_path)
    assert reverse["answer"]["value"] == old - new
    assert {c["doc_id"] for c in result["citations"]} == {"first", "second"}
    assert len(result["reasoning"]["steps"]) == 2


def test_zero_inventory_check_is_not_presented_as_a_source_quote(tmp_path):
    from engine import reasoning
    from engine.solvers.solve import _answer_obj, _evidence
    doc = Doc("upload", "ifc", [])
    store(tmp_path, "upload", "elements.json", dict(elements=[]))
    boxes, cites, scene = _evidence(doc, [])
    result = _answer_obj("How many doors?", [doc.doc_id], "**0 doors.** [1]", 0, "count", 1, False,
                         boxes, cites, scene, [], "index", time.perf_counter())
    reasoning.attach(result, result["question"], tmp_path)
    assert result["reasoning"]["steps"][0]["title"] == "Inventory checked"
    assert "Printed" not in str(result["reasoning"])


def test_headline_keeps_decimal_numbers_and_source_markers():
    from engine.plainwords import headline
    text = "There are **12 windows** with 0.9 m width. [1] Check openings.\n\n- Source data."
    result = headline(text)
    assert result.startswith("**There are 12 windows with 0.9 m width.** [1]")
    assert headline(result) == result
    assert "\n\n- Source data." in result
    assert headline("There are **22 doors on 1. Obergeschoss**. [1]") == "**There are 22 doors on 1. Obergeschoss.** [1]"
