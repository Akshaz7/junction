"""Ordering arithmetic, source coverage, scope and export contract."""
import json
import re
from pathlib import Path

import pytest

from engine.order import answer_order
from engine.solvers.data import Doc, Item


def _doc():
    return Doc("test", "ifc", [
        Item("r1", "room", name="Badezimmer", storey="Level 1", q={"net_floor_area_m2": 12, "net_wall_area_m2": 32, "perimeter_m": 14}, props={"door_ids": ["d1"]}),
        Item("d1", "door", storey="Level 1", q={"width_m": .9}, props={"room_id": "r1"}),
        Item("r2", "room", name="Office", storey="Level 2", q={"area_m2": 100}),
        Item("d2", "door", storey="Level 2"),
        Item("w1", "wall", storey="Level 1", q={"gross_side_area_m2": 40, "net_side_area_m2": 32}),
    ], storeys=[{"name": "Level 1", "elevation_m": 0}, {"name": "Level 2", "elevation_m": 3}])


def test_order_doors_floor_scope_and_whole_item_rounding():
    res = answer_order("how many doors do I need to order for level 1 with 10% waste", _doc())
    assert res["answer"]["value"] == 2
    assert "| Doors | 2 | count | 10% |" in res["answer"]["text_md"]
    assert {i for c in res["citations"] for i in c["item_ids"]} == {"d1"}
    assert "rounded up to whole items" in res["trace"][1]["detail"]


@pytest.mark.parametrize("material", ["flooring", "tiles"])
def test_room_area_waste_and_citation(material):
    res = answer_order(f"How much {material} for the bathrooms with 10% waste?", _doc())
    assert res["answer"]["value"] == 13.2
    assert res["citations"][0]["item_ids"] == ["r1"]
    assert "10% waste applied as requested" in res["answer"]["text_md"]
    assert res["cost"]["usd_total"] == 0


@pytest.mark.parametrize("material", ["plasterboard", "paint", "wall tiles"])
def test_wall_openings_deducted_and_no_floor_substitution(material):
    res = answer_order(f"How much {material} for the bathrooms with 10% waste?", _doc())
    assert res["answer"]["value"] == 35.2
    assert "openings deducted" in res["answer"]["text_md"]
    assert "litre" not in res["answer"]["unit"]


def test_wall_area_is_one_face_and_net_not_gross():
    doc = _doc()
    doc.items[0].q.pop("net_wall_area_m2")
    res = answer_order("How much plasterboard for level 1?", doc)
    assert res["answer"]["value"] == 32
    assert "one face" in res["answer"]["text_md"]
    doc.items[-1].q.pop("net_side_area_m2")
    res = answer_order("How much plasterboard for level 1?", doc)
    assert res["answer"]["value"] is None
    assert "gross areas were not used" in res["answer"]["text_md"]


def test_skirting_subtracts_measured_door_width():
    res = answer_order("How much skirting for the bathrooms with 10% waste?", _doc())
    assert res["answer"]["value"] == 14.41  # (14 - .9) * 1.1
    assert {i for c in res["citations"] for i in c["item_ids"]} == {"r1", "d1"}


def test_skirting_real_outline_beats_rectangle_and_marks_geometry_association():
    doc = Doc("scan", "planmap", [
        Item("r", "room", label="bathroom", polygon_px=[[0, 0], [400, 0], [400, 200], [200, 200], [200, 400], [0, 400]], bbox_px=[0, 0, 400, 400]),
        Item("d", "door", bbox_px=[0, 100, 10, 190], q={"width_m": .9}),
    ], scale={"method": "dimension", "m_per_px": .01, "confidence": .9})
    res = answer_order("How much skirting for the bathrooms?", doc)
    assert res["answer"]["value"] == 15.1
    assert res["answer"]["confidence"] == .5


def test_missing_area_never_becomes_partial_order():
    doc = _doc()
    doc.items.append(Item("r3", "room", name="Bathroom", storey="Level 1"))
    res = answer_order("How much flooring for the bathrooms?", doc)
    assert res["answer"]["value"] is None
    assert "no partial total" in res["answer"]["text_md"]


@pytest.mark.parametrize("scope", ["level 99", "the wizard laboratory"])
def test_unknown_scope_never_uses_whole_building(scope):
    res = answer_order(f"Order flooring for {scope}", _doc())
    assert res["answer"]["value"] is None and not res["citations"]
    assert "substituted" in res["answer"]["text_md"]


def test_no_hidden_waste_or_paint_yield():
    res = answer_order("Order paint for the bathrooms", _doc())
    assert res["answer"]["value"] == 32
    assert "0% waste applied" in res["answer"]["text_md"]
    assert "product coverage rate" in res["answer"]["text_md"]
    assert "10 m" not in res["answer"]["text_md"]


def test_unspecified_waste_requires_percentage():
    res = answer_order("Order flooring for the bathrooms with waste", _doc())
    assert res["answer"]["value"] is None
    assert "Specify a numeric waste" in res["answer"]["text_md"]


def test_multi_material_rows_and_csv_contract():
    res = answer_order("Order flooring and skirting for the bathrooms with 10% waste", _doc())
    assert res["answer"]["value"] == {"Flooring": 13.2, "Skirting": 14.41}
    assert "| Item | Quantity | Unit | Waste % | How measured | Source |" in res["answer"]["text_md"]
    ns = {str(c["n"]) for c in res["citations"]}
    for row in res["answer"]["text_md"].splitlines():
        if row.startswith(("| Flooring", "| Skirting")):
            assert set(re.findall(r"\[(\d+)\]", row)) <= ns
            assert re.findall(r"\[(\d+)\]", row)


def test_unspecified_finishes_not_invented():
    res = answer_order("What is the order list for the bathrooms?", _doc())
    assert "confirm material" in res["answer"]["text_md"]
    assert "confirm the finish schedule" in res["answer"]["text_md"]
    assert "price" not in res["answer"]["text_md"]


def test_ceiling_is_labelled_estimate():
    res = answer_order("Order ceiling paint for the bathrooms", _doc())
    assert res["answer"]["value"] == 12
    assert "estimated from floor area" in res["answer"]["text_md"]
    assert res["answer"]["confidence"] == .5


def test_page_specific_scale(tmp_path):
    doc = Doc("scan", "planmap", [Item("r", "room", label="bathroom", page=2, polygon_px=[[0, 0], [10, 0], [10, 10], [0, 10]])], pages=2,
              scale={"method": "dimension", "m_per_px": .1, "confidence": 1})
    dest = tmp_path / doc.doc_id
    dest.mkdir()
    (dest / "planmap-2.json").write_text(json.dumps({"scale": {"method": "dimension", "m_per_px": .2}}))
    assert answer_order("Order tiles for the bathrooms", doc, root=tmp_path)["answer"]["value"] == 4
    assert answer_order("Order tiles for the bathrooms", doc)["answer"]["value"] is None


def test_missing_data_confidence_never_claims_verified(tmp_path):
    from engine import reasoning
    doc = _doc()
    res = answer_order("Order paint for level 2", doc)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "elements.json").write_text(json.dumps({"elements": [{"item_id": "r2", "kind": "room", "name": "Office"}]}))
    reasoning.attach(res, res["question"], tmp_path)
    assert not res.get("reasoning") or res["reasoning"]["confidence"]["label"] != "Verified"


def test_answer_integration_keeps_table_and_plain_text(monkeypatch, tmp_path):
    from engine.answer import answer
    d = tmp_path / "new-upload"
    d.mkdir()
    (d / "elements.json").write_text(json.dumps({"elements": [{"item_id": "d", "kind": "door", "ifc_class": "IfcDoor"}]}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    res = answer("How many doors do I need to order?", [d.name])
    assert "| Doors | 1 | count | 0% |" in res["answer"]["text_md"]
    assert res["reasoning"]["steps"][1]["kind"] == "calculated"
    import jsonschema
    jsonschema.validate(res, json.loads(Path("server/schemas/answer.schema.json").read_text()))


def test_normal_counts_and_other_questions_untouched():
    assert answer_order("How many doors are on level 1?", _doc()) is None
    assert answer_order("Is the bathroom accessible?", _doc()) is None


def test_explicit_room_exclusion_and_multiple_room_types():
    doc = _doc()
    doc.items.append(Item("wc", "room", name="WC", q={"area_m2": 2}))
    assert answer_order("Order tiles for the bathrooms", doc)["answer"]["value"] == 14
    assert answer_order("Order tiles for the bathrooms excluding WCs", doc)["answer"]["value"] == 12
    doc.items.append(Item("k", "room", label="Kitchen", q={"area_m2": 20}))
    assert answer_order("Order tiles for the bathrooms and kitchens", doc)["answer"]["value"] == 34


@pytest.mark.parametrize("waste", ["-10% waste", "10% waste and 20% extra"])
def test_invalid_or_ambiguous_allowances_do_not_create_an_order(waste):
    assert answer_order(f"Order tiles for the bathrooms with {waste}", _doc())["answer"]["value"] is None
