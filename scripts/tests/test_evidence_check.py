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
        {"item_id": "a", "kind": "room", "props": {"area_m2": 12}},
        {"item_id": "b", "kind": "room", "props": {"area_m2": 8}}]}))
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
    (lambda r: r["reasoning"]["calc"]["steps"][0]["inputs"][0].update(name="model count"), "calc.model_input"),
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


def test_unparseable_headline_does_not_silently_pass(source):
    res = good()
    res["answer"]["text_md"] = "The quantity is twenty."
    assert checker.audit(res, source)["status"] == "uncheckable"


def test_calibration_uses_measured_sample_counts(source):
    res = good()
    res["reasoning"]["confidence"].update(pct=75, calibration={"n": 4, "correct": 3})
    assert "confidence.uncalibrated" not in codes(res, source)


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
