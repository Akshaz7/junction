"""Calculation integrity, explicit conversion, missing evidence and audit safety."""
import copy
import csv
import io
import json

import pytest

from engine import calc, calc_export
from engine.solvers.data import Doc, Item


def response(value=3, unit="count"):
    return {"question": "How many doors?", "answer": {"value": value, "unit": unit, "text_md": f"**{value} doors**", "abstained": False},
            "doc_ids": ["test"], "citations": [{"doc_id": "test", "page": 1, "item_ids": ["a", "b", "c"]}], "trace": []}


def artifact(tmp_path):
    d = tmp_path / "test"
    d.mkdir()
    (d / "elements.json").write_text(json.dumps({"elements": [{"item_id": x, "kind": "door"} for x in "abc"]}))
    return tmp_path


def test_complete_count_and_tampered_operands(tmp_path):
    root = artifact(tmp_path)
    r = calc.attach(response(), "How many doors?", root)
    c = r["reasoning"]["calc"]
    assert c["status"] == "complete" and len(c["rows"]) == 3
    assert c["result"]["value"] == r["answer"]["value"]
    c["steps"][0]["inputs"][0]["value"] = 9
    assert "operands do not reproduce" in ";".join(calc.validate(c, root))


def test_never_invent_balancing_term(tmp_path):
    r = calc.attach(response(6), "How many doors?", artifact(tmp_path))
    c = r["reasoning"]["calc"]
    assert c["status"] == "incomplete"
    assert sum(x["values"]["count"] for x in c["rows"]) == 3
    assert c["result"]["value"] == 6


def test_cross_document_id_collision(tmp_path):
    artifact(tmp_path)
    other = tmp_path / "second"
    other.mkdir()
    (other / "elements.json").write_text(json.dumps({"elements": [{"item_id": "a", "kind": "door"}]}))
    r = response(4)
    r["citations"].append({"doc_id": "second", "page": 1, "item_ids": ["a"]})
    c = calc.attach(r, r["question"], tmp_path)["reasoning"]["calc"]
    assert c["status"] == "complete" and len(c["rows"]) == 4


def test_ifc_citations_on_two_pages_do_not_double_count(tmp_path):
    r = response(3)
    r["citations"].append({"doc_id": "test", "page": 2, "item_ids": ["a"]})
    assert calc.attach(r, r["question"], artifact(tmp_path))["reasoning"]["calc"]["status"] == "complete"


def test_explicit_allowance_and_rounding(tmp_path):
    from engine.calc_routes import allowance
    root = artifact(tmp_path)
    d = Doc("test", "ifc", [Item("a", "room")])
    r = response(18.2, "m2")
    allowance(r, [calc.row(d, d.items[0], 16.5, "m2")], 10, calc.question_source("10% waste"))
    c = calc.attach(r, r["question"], root)["reasoning"]["calc"]
    assert c["status"] == "complete" and c["steps"][-2]["value"] == 18.150000000000002
    assert any(s["operation"] == "divide" for s in c["steps"])
    assert c["result"]["value"] == 18.2


def test_conversion_factor_is_input():
    s = calc.converted_step("feet", 1, "m", "ft", 1 / .3048, calc.question_source("1 metre"))
    assert s["inputs"][1]["value"] == 1 / .3048
    assert calc.evaluate(s["operation"], [i["value"] for i in s["inputs"]]) == s["value"]


def test_distinct_types_not_element_count(tmp_path):
    from engine.calc_routes import grouped
    root = artifact(tmp_path)
    d = Doc("test", "ifc", [Item(x, "door") for x in "abc"])
    r = response(2)
    grouped(r, d, d.items, {"a": "large", "b": "large", "c": "small"}, "type")
    c = calc.attach(r, r["question"], root)["reasoning"]["calc"]
    assert c["status"] == "complete" and [x["values"]["count"] for x in c["rows"]] == [1, 0, 1]


def test_exports_include_all_rows_and_escape(tmp_path):
    r = calc.attach(response(), "How many doors?", artifact(tmp_path))
    c = r["reasoning"]["calc"]
    c["rows"][0]["label"] = '=HYPERLINK("bad")'
    c["rows"][1]["label"] = "<script>alert(1)</script>|pipe"
    rows = list(csv.DictReader(io.StringIO(calc_export.to_csv(r))))
    assert len(rows) == 3 and rows[0]["label"].startswith("'=")
    for exported in (calc_export.to_markdown(r), calc_export.to_html(r)):
        assert "Calculation report" in exported and "source quantities" not in exported
        assert "&lt;script&gt;" in exported and "<script>" not in exported
    assert "Per-element quantities" in calc_export.to_markdown(r)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, None, "3"])
def test_non_numeric_is_not_a_calculation(tmp_path, value):
    assert "reasoning" not in calc.attach(response(value), "question", tmp_path)


def test_invalid_source_step_is_incomplete():
    r = response(1)
    d = Doc("test", "ifc", [Item("a", "door")])
    c = calc.summed(r, [calc.row(d, d.items[0], 1, "count")])
    c["steps"][0]["inputs"][0]["source"] = calc.step_source("missing")
    assert any("unresolved" in issue for issue in calc.validate(c))


def test_source_item_must_exist_in_artifact(tmp_path):
    r = response(1)
    d = Doc("test", "ifc", [Item("not-in-file", "door")])
    calc.record_items(r, d, [(d.items[0], 1)])
    c = calc.attach(r, r["question"], artifact(tmp_path))["reasoning"]["calc"]
    assert c["status"] == "incomplete" and any("does not exist" in s for s in c["issues"])


def test_reader_number_is_labelled_as_model_input(tmp_path):
    r = response(6)
    r["route"] = "hybrid"
    r["trace"] = [{"step": "answer", "model": "test-model"}]
    c = calc.attach(r, r["question"], artifact(tmp_path))["reasoning"]["calc"]
    assert c["status"] == "incomplete"
    assert any(i["source"].get("kind") == "model" and i["value"] == 6 for s in c["steps"] for i in s["inputs"])


def test_display_precision_keeps_api_value_and_headline(tmp_path):
    root = artifact(tmp_path)
    d = Doc("test", "ifc", [Item("a", "room", q={"area_m2": 16.5432})])
    r = response(16.5432, "m2")
    r["answer"]["text_md"] = "**16.5 m²**"
    calc.record_items(r, d, [(d.items[0], 16.5432)])
    c = calc.attach(r, r["question"], root)["reasoning"]["calc"]
    assert c["status"] == "complete" and c["result"]["value"] == 16.5432
    assert any(v["value"] == 16.5 for v in c["result"]["additional"])


def test_non_finite_source_never_crashes_or_claims_complete(tmp_path):
    root = artifact(tmp_path)
    raw = json.loads((root / "test/elements.json").read_text())
    raw["elements"][0]["quantities"] = {"area_m2": float("inf")}
    (root / "test/elements.json").write_text(json.dumps(raw))
    r = response(7, "m2")
    assert calc.attach(r, r["question"], root)["reasoning"]["calc"]["status"] == "incomplete"
