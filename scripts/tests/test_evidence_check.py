"""Generated audit fixtures: check that dishonest evidence fails independently."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("evidence_check", Path(__file__).parents[1] / "evidence_check.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.fixture
def source(tmp_path):
    doc = tmp_path / "generated__audit"
    doc.mkdir()
    (doc / "doc.json").write_text(json.dumps({"pages": 2, "kind": "ifc"}))
    (doc / "planmap-1.json").write_text(json.dumps({"image": {"w": 100, "h": 80}, "items": [
        {"item_id": "a", "kind": "room", "source": "dxf", "props": {"area_m2": 12}},
        {"item_id": "b", "kind": "room", "source": "dxf", "props": {"area_m2": 8}}], "scale": {"method": "dxf-units"}}))
    return checker.Sources(tmp_path)


def good():
    source = {"doc_id": "generated__audit", "page": 1, "item_id": "a", "bbox": [1, 1, 20, 20]}
    margin = {"value": 0.05, "unit": "m2", "pct": 0.25, "why": "Display rounding only", "sources": []}
    return {"doc_ids": ["generated__audit"], "answer": {"value": 20, "unit": "m2", "text_md": "**20 m²** total area. [1]"},
            "citations": [{"doc_id": "generated__audit", "page": 1, "item_ids": ["a", "b"]}],
            "reasoning": {"confidence": {"label": "Verified", "pct": None}, "based_on": {"estimated": 0, "unresolved": 0},
                          "margin": margin, "steps": [], "calc": {"formula": "area = sum of rooms", "steps": [
                              {"id": "s1", "label": "Sum source areas", "value": 20, "unit": "m2", "inputs": [
                                  {"name": "source room area", "value": 12, "unit": "m2", "source": source}]}],
                              "rows": [{"item_id": iid, "values": {"area_m2": value}, "source": {**source, "item_id": iid}} for iid, value in (("a", 12), ("b", 8))],
                              "result": {"value": 20, "unit": "m2", "rounded_as": "1 decimal"}, "checks": [], "margin": copy.deepcopy(margin)}}}


def codes(res, source):
    return {f["code"] for f in checker.audit(res, source)["findings"]}


def test_reconciled_source_quantities_pass(source):
    assert checker.audit(good(), source)["status"] == "pass"


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r["reasoning"].pop("calc"), "calc.missing"),
    (lambda r: r["reasoning"]["calc"]["result"].update(value=21), "calc.headline_result"),
    (lambda r: r["answer"].update(text_md="**21 m²** total area."), "card.headline_value"),
    (lambda r: r["reasoning"]["calc"]["result"].update(unit="ft2"), "calc.result_unit"),
    (lambda r: r["reasoning"]["calc"]["rows"][0]["values"].update(area_m2=13), "calc.rows_sum"),
    (lambda r: r["reasoning"]["calc"]["rows"].append(copy.deepcopy(r["reasoning"]["calc"]["rows"][0])), "calc.duplicate_row"),
    (lambda r: r["reasoning"]["calc"]["rows"][0].update(source=None), "source.unresolved"),
    (lambda r: r["reasoning"]["calc"]["rows"][0]["source"].update(item_id="missing"), "source.unresolved"),
    (lambda r: r["reasoning"]["calc"]["rows"][0]["source"].update(bbox=[1, 1, 101, 80]), "source.unresolved"),
    (lambda r: r["reasoning"]["calc"]["steps"][0]["inputs"][0].pop("unit"), "calc.input_unit"),
    (lambda r: r["reasoning"]["calc"]["steps"][0].pop("unit"), "calc.step_unit"),
    (lambda r: r["reasoning"]["calc"]["steps"][0]["inputs"][0].update(source={"doc_id": "generated__audit"}), "source.unresolved"),
    (lambda r: r["reasoning"]["calc"]["steps"][0]["inputs"][0]["source"].update(kind="model"), "calc.model_input"),
    (lambda r: r["reasoning"]["calc"].pop("rounded_as", None) or r["reasoning"]["calc"]["result"].pop("rounded_as"), "calc.rounding_missing"),
    (lambda r: r["reasoning"]["calc"].pop("formula"), "calc.formula_missing"),
    (lambda r: r["reasoning"].pop("margin"), "scale.margin_missing"),
    (lambda r: r["reasoning"]["margin"].update(pct=25), "calc.margin_pct"),
    (lambda r: r["reasoning"]["margin"].update(value=None, pct=1), "calc.margin_unknown"),
    (lambda r: r["reasoning"]["margin"].update(value=-1), "calc.margin_invalid"),
    (lambda r: r["reasoning"]["margin"].update(unit="m"), "calc.margin_unit"),
    (lambda r: r["reasoning"]["margin"].update(why=""), "calc.margin_reason"),
    (lambda r: r["reasoning"]["confidence"].update(label="Cross-checked"), "confidence.unchecked"),
    (lambda r: r["reasoning"]["confidence"].update(pct=99), "confidence.uncalibrated"),
    (lambda r: r["reasoning"]["based_on"].update(estimated=1), "confidence.overclaim"),
    (lambda r: r["reasoning"]["calc"].update(checks=[{"method": "label", "value": 22, "agrees": True, "diff_pct": 0}]), "check.diff_pct"),
    (lambda r: r["reasoning"]["calc"].update(checks=[{"method": "label", "value": 22, "agrees": True}]), "check.agreement_unbounded"),
    (lambda r: r["answer"].update(text_md="**20 m²** in IfcSpace."), "card.jargon"),
    (lambda r: r["reasoning"].update(steps=[{"text": "Read 1 marked region of the scanned drawing"}]), "card.meaningless_read"),
])
def test_corrupt_evidence_is_detected(source, mutation, code):
    res = good()
    mutation(res)
    assert code in codes(res, source)


@pytest.mark.parametrize("box", [[-1, 0, 20, 20], [1, 1, 0, 0], [0, 0, 101, 80], [0, 0, float("nan"), 20], [0, 1, 2]])
def test_invalid_pixel_boxes(source, box):
    assert source.resolve({"doc_id": "generated__audit", "page": 1, "bbox": box})


def test_sources_resolve_by_document_and_page(source):
    assert source.resolve({"doc_id": "absent", "item_id": "a"})
    assert source.resolve({"doc_id": "../generated__audit", "item_id": "a"})
    assert source.resolve({"doc_id": "generated__audit", "page": 2, "item_id": "a"})
    assert not source.resolve({"doc_id": "generated__audit", "page": 1, "item_id": "a"})


def test_unknown_uncertainty_is_honest(source):
    res = good()
    for margin in (res["reasoning"]["margin"], res["reasoning"]["calc"]["margin"]):
        margin.update(value=None, pct=None, why="Outline uncertainty was not measured")
    res["reasoning"]["confidence"]["label"] = "Estimate"
    assert checker.audit(res, source)["status"] == "pass"


def test_large_measured_uncertainty_is_not_arbitrarily_capped(source):
    res = good()
    for margin in (res["reasoning"]["margin"], res["reasoning"]["calc"]["margin"]):
        margin.update(value=30, pct=150)
    res["reasoning"]["confidence"]["label"] = "Estimate"
    assert "calc.margin_pct" not in codes(res, source)


def test_numeric_zero_is_a_result(source):
    res = good()
    res["answer"].update(value=0, text_md="**0 m²** total area.")
    calc = res["reasoning"]["calc"]
    calc["result"]["value"] = 0
    calc["rows"] = []
    for margin in (res["reasoning"]["margin"], calc["margin"]):
        margin.update(value=0, pct=0)
    assert checker.audit(res, source)["status"] == "pass"


def test_room_identifiers_and_citations_are_not_quantities():
    assert checker.headline_values("Room 205 has **47.0 m²**. [1]", "m2") == [47]
    assert checker.headline_values("**1,234 doors** on level 2. [3]", "count") == [1234]
    assert checker.headline_values("**5 m²**", "m") == []


def test_extra_headline_quantity_cannot_hide_behind_matching_primary(source):
    res = good()
    res["answer"]["text_md"] = "**20 m²** and **999 m²**."
    assert "card.headline_value" in codes(res, source)


def test_display_rounding_matches_its_written_precision(source):
    res = good()
    res["answer"].update(value=20.04, text_md="**20.0 m²** total area.")
    assert "card.headline_value" not in codes(res, source)
    res["answer"]["text_md"] = "**20.00 m²** total area."
    assert "card.headline_value" in codes(res, source)


def test_real_page_artifact_overrides_stale_doc_page_count(source):
    doc = source.root / "generated__audit"
    (doc / "doc.json").write_text('{"pages": 1}')
    (doc / "planmap-3.json").write_text('{"image": {"w": 100, "h": 80}}')
    assert not source.resolve({"doc_id": "generated__audit", "page": 3, "bbox": [0, 0, 20, 20]})


def test_unparseable_headline_does_not_silently_pass(source):
    res = good()
    res["answer"]["text_md"] = "The quantity is twenty."
    assert checker.audit(res, source)["status"] == "uncheckable"


def test_calibration_uses_measured_sample_counts(source):
    res = good()
    source.repo = source.root
    (source.repo / "calibration.json").write_text('{"n": 4, "correct": 3}')
    res["reasoning"]["confidence"].update(pct=75, calibration={"n": 4, "correct": 3, "source": "calibration.json"})
    assert "confidence.uncalibrated" not in codes(res, source)
    assert "confidence.calibration_source" not in codes(res, source)


def test_count_card_contradiction_requires_an_explanation(source):
    res = good()
    res["answer"].update(value=6, unit="count", text_md="There are **6 doors**. [1]")
    res["reasoning"]["steps"] = [{"kind": "found", "text": "Found 4 doors marked on the drawing."}]
    res["evidence"] = {"boxes": [{"item_id": "a", "page": 1}, {"item_id": "b", "page": 1}]}
    assert {"card.found_count", "card.box_count"} <= codes(res, source)
    res["reasoning"]["steps"][0]["text"] += " Two are not boxed; the second reading differs."
    assert not {"card.found_count", "card.box_count"} & codes(res, source)


def test_overlay_copies_json_and_never_rewrites_shared_artifacts(tmp_path):
    src, dst = tmp_path / "shared", tmp_path / "local"
    (src / "generated__demo").mkdir(parents=True)
    original = src / "generated__demo/planmap-1.json"
    original.write_text('{"scale": 1}')
    image = src / "generated__demo/page-1.png"
    image.write_bytes(b"generated for demo")
    checker.copy_artifacts(src, dst, ["generated__demo"])
    (dst / "generated__demo/planmap-1.json").write_text('{"scale": 2}')
    assert original.read_text() == '{"scale": 1}'
    assert (dst / "generated__demo/page-1.png").is_symlink()


@pytest.mark.parametrize("expression,value", [("12 + 8", 20), ("0.9 / 31", .9 / 31), ("5 × 4", 20), ("3 ** 2", 9), ("20 − 8", 12)])
def test_literal_arithmetic(expression, value):
    assert checker.close(checker.expression_value(expression), value)


@pytest.mark.parametrize("expression", ["__import__('os').getcwd()", "sum([1, 2])", "10 ** 100000000", "False", "1 / 0", "area / scale", "9 m / 31 px"])
def test_expressions_are_never_executed_or_guessed(expression):
    assert checker.expression_value(expression) is None


def test_exclusion_is_accepted_only_when_explicit_and_reproducible(source):
    res = good()
    res["answer"].update(value=12, text_md="**12 m²** after excluding the second room.")
    calc = res["reasoning"]["calc"]
    calc["result"]["value"] = 12
    calc["steps"] = [{"label": "Exclude outdoor area", "expr": "20 - 8", "value": 12, "unit": "m2", "inputs": [
        {"value": 20, "unit": "m2", "source": calc["rows"][0]["source"]},
        {"value": 8, "unit": "m2", "source": calc["rows"][1]["source"]}]}]
    assert "calc.rows_sum" not in codes(res, source)
    calc["steps"][0]["expr"] = "12"
    assert "calc.rows_sum" in codes(res, source)
    assert "calc.hidden_factor" in codes(res, source)


def test_no_matching_kind_is_distinct_from_number_of_inspected_rooms():
    assert checker.headline_values("There are no balconies. I checked all 14 rooms and none has that label.", "count") == [0]
    assert checker.headline_values("**294 structural elements**: 208 columns, 86 beams.", "count") == [294, 208, 86]


def test_swapped_multikind_counts_are_detected(source):
    res = good()
    res["answer"].update(value={"window": 6, "door": 4}, unit="count", text_md="**4 windows** and **6 doors**.")
    res["reasoning"]["calc"]["result"].update(value={"window": 6, "door": 4}, unit="count")
    assert "card.headline_category" in codes(res, source)


def test_step_sources_are_resolved_through_calculation_graph(source):
    res = good()
    calc = res["reasoning"]["calc"]
    calc["steps"].append({"id": "rounded", "label": "Round", "value": 20, "unit": "m2", "operation": "round", "inputs": [
        {"name": "total", "value": 20, "unit": "m2", "source": {"kind": "step", "step_id": "s1"}},
        {"name": "places", "value": 1, "unit": "decimal places", "source": {"kind": "policy", "text": "one decimal"}}]})
    assert checker.audit(res, source)["status"] == "pass"
    calc["steps"][-1]["inputs"][0]["value"] = 19
    assert {"source.step_value", "calc.step_operands"} <= codes(res, source)


def test_cyclic_step_reference_is_an_error(source):
    res = good()
    calc = res["reasoning"]["calc"]
    calc["steps"][0]["inputs"][0]["source"] = {"kind": "step", "step_id": "s1"}
    assert "source.unresolved" in codes(res, source)


def test_artifact_reference_and_declared_assumption_are_distinct_from_missing_source(source):
    ref = {"doc_id": "generated__audit", "artifact": "planmap-1.json", "field": "scale"}
    assert not source.resolve(ref)
    res = good()
    res["reasoning"]["calc"]["steps"][0]["inputs"][0]["source"] = {"assumption": "Assumed 0.9 m leaf; not a measured door width"}
    assert "source.unresolved" not in codes(res, source)


def test_symmetric_method_difference_is_accepted(source):
    res = good()
    res["reasoning"]["calc"]["checks"] = [{"method": "printed / outline", "primary_value": 20, "value": 22, "agrees": False, "diff_pct": 2/22*100}]
    assert "check.diff_pct" not in codes(res, source)


def test_named_arithmetic_is_verified_using_operands(source):
    res = good()
    step = res["reasoning"]["calc"]["steps"][0]
    step.update(operation="sum", expr="sum of room areas")
    assert "calc.step_operands" in codes(res, source)


@pytest.mark.parametrize("text", ["**Total doors: 64.** [1]", "**Ceiling height: 2.58 m.** [1]", "**Structural elements: 657 in total**"])
def test_numeric_prose_cannot_bypass_audit_with_null_value(source, text):
    res = good()
    res["answer"].update(value=None, unit=None, text_md=text)
    assert "calc.numeric_value_missing" in codes(res, source)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 10**1000])
def test_nonfinite_or_nonnumeric_is_never_a_valid_measurement(value):
    assert checker.number(value) is None


def test_json_pointer_locates_a_real_value_in_the_source(source):
    ref = {"doc_id": "generated__audit", "artifact": "planmap-1.json", "pointer": "/items/0/props/area_m2"}
    assert not source.resolve(ref)
    ref["pointer"] = "/items/99/props/area_m2"
    assert source.resolve(ref)


def test_repeated_item_on_different_pages_is_still_a_duplicate(source):
    res = good()
    other = copy.deepcopy(res["reasoning"]["calc"]["rows"][0])
    other["source"]["page"] = 2
    res["reasoning"]["calc"]["rows"].append(other)
    assert "calc.duplicate_row" in codes(res, source)


def test_read_only_binary_links_resolve_only_to_original_artifacts(source, tmp_path):
    shared = tmp_path.parent / (tmp_path.name + "-original")
    shared.mkdir()
    (shared / "scene.glb").write_bytes(b"generated for demo")
    source.original_artifacts = shared
    target = source.root / "generated__audit/scene.glb"
    target.symlink_to(shared / "scene.glb")
    assert not source.resolve({"doc_id": "generated__audit", "artifact": "scene.glb"})
    source.original_artifacts = source.root / "untrusted"
    assert source.resolve({"doc_id": "generated__audit", "artifact": "scene.glb"})


def test_nonfinite_source_values_are_preserved_as_defects_in_valid_json():
    data = json.loads(checker.report_json({"answer": {"value": float("nan")}}))
    assert data["answer"]["value"] == {"invalid_numeric": "nan"}


def test_labelled_model_input_can_be_added_by_a_plain_sum_step(source):
    res = good()
    operand = res["reasoning"]["calc"]["steps"][0]["inputs"][0]
    operand["name"] = "Model output: room outline"
    operand["source"]["origin"] = "seg"
    assert "calc.model_input" not in codes(res, source)


def test_element_comparison_does_not_compare_a_room_to_the_floor_total(source):
    res = good()
    res["reasoning"]["calc"]["checks"] = [{"method": "printed / outline", "value": 12, "diff_pct": 0,
                                               "agrees": True, "source": {"doc_id": "generated__audit", "page": 1, "item_id": "a"}}]
    assert "check.diff_pct" not in codes(res, source)
