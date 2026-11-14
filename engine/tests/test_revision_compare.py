"""Generated for demo fixtures. No models, source geometry or private data."""
from copy import deepcopy
import json

import jsonschema
import pytest

from engine.revision_compare import compare_documents, compare_ifc, compare_planmaps, comparison_answer


def element(iid, box=None, kind="door", **kwargs):
    return {"item_id": iid, "kind": kind, "bbox_m": box or [[0, 0, 0], [1, 2, .2]],
            "storey": {"name": "Erdgeschoss", "elevation_m": 0}, "props": {}, **kwargs}


def index(*items, **kwargs):
    return {"elements": list(items), "units": "m", **kwargs}


def fixture(iid, box, kind="door", **kwargs):
    return {"item_id": iid, "kind": kind, "conf": 1, "bbox_px": box, "props": {}, **kwargs}


def plan(*items, image=None, scale=None):
    return {"items": list(items), "image": image or {"w": 1000, "h": 800}, "scale": scale or {}}


def anchors():
    return [fixture("position-1", [50, 60, 70, 100]), fixture("position-2", [180, 270, 200, 315]),
            fixture("position-3", [450, 160, 510, 178], "window"), fixture("position-4", [600, 510, 625, 566], "column")]


def save(root, doc, name, value):
    path = root / doc
    path.mkdir(exist_ok=True)
    (path / name).write_text(json.dumps(value))


def test_ifc_events_sources_and_storeys():
    a = index(element("gone"), element("move"), element("size"), element("property"))
    b = index(element("new", kind="window"), element("move", [[.06, 0, 0], [1.06, 2, .2]]),
              element("size", [[0, 0, 0], [1.2, 2, .2]]), element("property", props={"fire_rating": "EI60"}))
    result = compare_ifc(a, b, "old", "new")
    assert result["status"] == "ready"
    assert sorted(c["type"] for c in result["changes"]) == sorted(["added", "removed", "moved", "resized", "property_changed"])
    for c in result["changes"]:
        assert [cite["doc_id"] for cite in c["citations"]] == ["old", "new"]
        for src, cite in zip((c["v1"], c["v2"]), c["citations"]):
            assert cite["item_ids"] == ([src["item_id"]] if src else [])
        assert c["storey"] == "Erdgeschoss"


@pytest.mark.parametrize("distance,changed", [(.04999, False), (.05, False), (.05001, True), (.1, True)])
def test_movement_is_strictly_more_than_five_cm(distance, changed):
    a = index(element("a"))
    b = index(element("a", [[distance, 0, 0], [1 + distance, 2, .2]]))
    assert bool(compare_ifc(a, b)["changes"]) is changed


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
def test_schema_units_and_labels_do_not_change_matching(schema):
    a = index(element("id", name="Porte / Ovi / Tür / Dörr"), schema=schema)
    b = deepcopy(a)
    b["elements"][0]["props"] = {"material": "Stål"}
    assert compare_ifc(a, b)["changes"][0]["type"] == "property_changed"


def test_recentering_is_undone_before_movement_check():
    a = index(element("stable", [[0, 0, 0], [1, 2, .2]]), coords="recentred in X/Z")
    b = index(element("stable", [[-10, 0, 6], [-9, 2, 6.2]]), coords="recentred in X/Z")
    assert compare_ifc(a, b, scene_a={"origin_offset_m": [10, 0, -6]}, scene_b={"origin_offset_m": [20, 0, -12]})["changes"] == []
    assert compare_ifc(a, b)["status"] == "partial"
    assert compare_ifc(a, b)["changes"] == []


def test_missing_box_does_not_hide_property_change_or_claim_no_changes():
    a = index({"item_id": "x", "kind": "pipe", "bbox_m": None, "props": {}})
    b = deepcopy(a); b["elements"][0]["props"]["material"] = "Copper"
    result = compare_ifc(a, b)
    assert result["status"] == "partial"
    assert [c["type"] for c in result["changes"]] == ["property_changed"]
    assert "could not be checked" in result["warnings"][0]


def test_replaced_globalids_are_flagged_not_claimed_as_physical_demolition():
    result = compare_ifc(index(element("old")), index(element("new")))
    assert result["matched_items"] == 0
    assert result["status"] == "partial"
    assert "exporter may have replaced" in result["warnings"][0]


def test_plan_registration_scale_translation_renumbering_and_addition():
    a = plan(*anchors())
    b = deepcopy(a)
    b["image"] = {"w": 2000, "h": 1600}
    for n, item in enumerate(b["items"]):
        item["item_id"] = f"renumbered-{n}"
        item["bbox_px"] = [v * 2 + (37 if k % 2 == 0 else -19) for k, v in enumerate(item["bbox_px"])]
    b["items"].append(fixture("new", [1400, 1200, 1430, 1250], "sink"))
    original = deepcopy(b)
    result = compare_planmaps(a, b, "old", "new")
    assert result["alignment"]["verified"]
    assert result["alignment"]["scale"] == 2
    assert result["alignment"]["translation_px"] == [37, -19]
    assert [(c["type"], c["kind"]) for c in result["changes"]] == [("added", "sink")]
    assert result["changes"][0]["v2"]["bbox_px"] == [1400, 1200, 1430, 1250]
    assert b == original  # alignment must not rewrite original citation coordinates


def test_room_unique_label_and_area_change():
    room = fixture("room-1", [100, 100, 300, 300], "room", label="Küche", props={"area_m2": 20})
    a = plan(*anchors(), room)
    b = deepcopy(a)
    b["items"][-1].update(item_id="room-78", bbox_px=[100, 100, 330, 300], props={"area_m2": 23})
    result = compare_planmaps(a, b)
    area = next(c for c in result["changes"] if c["type"] == "property_changed")
    assert area["v1"]["item_id"] == "room-1" and area["v2"]["item_id"] == "room-78"
    assert area["old"]["area_m2"] == 20 and area["new"]["area_m2"] == 23


def test_lone_moved_item_cannot_establish_a_translation():
    a = plan(fixture("1", [10, 10, 20, 30]))
    b = plan(fixture("1", [110, 110, 120, 130]))
    result = compare_planmaps(a, b)
    assert not result["alignment"]["verified"]
    assert result["status"] == "partial"
    assert len(result["changes"]) == 2


def test_omitted_confidence_and_missing_area_are_not_zero():
    a = plan(*anchors(), fixture("room", [100, 100, 300, 300], "room", label="Room", props={"area_m2": 12}))
    b = deepcopy(a); del b["items"][-1]["conf"]; b["items"][-1]["props"] = {}
    result = compare_planmaps(a, b)
    change = next(c for c in result["changes"] if c["type"] == "property_changed")
    assert change["new"]["area_m2"] is None
    assert "0 m²" not in change["description"]


def test_unavailable_is_not_zero_and_path_traversal_rejected(tmp_path):
    result = compare_documents("a", "b", tmp_path)
    assert result["status"] == "unavailable" and result["summary"] is None
    for bad in ("../a", "..", "/tmp/a", "a/b"):
        with pytest.raises(ValueError):
            compare_documents(bad, "b", tmp_path)


def test_multi_page_citations_are_unique_and_summary_is_complete(tmp_path):
    for n in (1, 2):
        save(tmp_path, "a", f"planmap-{n}.json", plan())
        save(tmp_path, "b", f"planmap-{n}.json", plan(fixture("sink", [10, 10, 30, 30], "sink")))
    result = compare_documents("a", "b", tmp_path)
    assert result["summary"]["added"] == 2
    assert result["summary"]["by_kind"]["sink"]["total"] == 2
    assert result["summary"]["by_storey"]["Storey not recorded"]["total"] == 2
    assert result["summary"]["affected_items"] == 2
    cites = [cite for c in result["changes"] for cite in c["citations"]]
    assert [c["n"] for c in cites] == [1, 2, 3, 4]
    assert [c["page"] for c in cites] == [1, 1, 2, 2]


def test_unpaired_page_is_partial_not_silently_unchanged(tmp_path):
    for doc in ("a", "b"):
        save(tmp_path, doc, "planmap-1.json", plan(*anchors()))
    save(tmp_path, "b", "planmap-2.json", plan(*anchors()))
    result = compare_documents("a", "b", tmp_path)
    assert result["status"] == "partial" and "Page 2" in result["warnings"][0]


def test_chat_route_is_code_only_and_matches_contract(tmp_path, monkeypatch):
    save(tmp_path, "a", "elements.json", index(element("x")))
    save(tmp_path, "b", "elements.json", index(element("x", props={"material": "Wood"})))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    def no_models(*args, **kwargs):
        raise AssertionError("Comparison must not call a model")
    monkeypatch.setattr("engine.models.call", no_models)
    from engine.answer import answer
    result = answer("What changed between A and B?", ["a", "b"])
    schema = json.loads((__import__('pathlib').Path(__file__).parents[2] / 'server/schemas/answer.schema.json').read_text())
    jsonschema.validate(result, schema)
    assert result["cost"] == {"usd_total": 0, "calls": []}
    assert result["answer"]["value"] == 1
    assert {c["doc_id"] for c in result["citations"]} == {"a", "b"}
    assert [s["title"] for s in result["reasoning"]["steps"]] == ["Found", "Checked"]
    assert "#/changes?a=a&b=b" in result["answer"]["text_md"]


def test_chat_needs_two_versions_but_unrelated_questions_keep_existing_route(tmp_path):
    assert comparison_answer("How many windows?", ["a"], tmp_path) is None
    assert comparison_answer("What changed?", ["a"], tmp_path)["answer"]["abstained"]


def test_generated_versions_keep_the_demo_label(tmp_path):
    for doc in ("a", "b"):
        save(tmp_path, doc, "elements.json", index(element("x")))
    save(tmp_path, "b", "doc.json", {"generated_for_demo": True})
    assert compare_documents("a", "b", tmp_path)["generated_for_demo"] is True
    result = comparison_answer("Compare these versions", ["a", "b"], tmp_path)
    assert "generated for demo" in result["answer"]["text_md"]
