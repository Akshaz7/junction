"""IFC storey identity, source proof and downstream level scopes."""
import json
import time
from copy import deepcopy

import pytest

from engine.analytics import storey_compare
from engine.ifc_storeys import canonical_storeys
from engine.solvers import solve
from engine.solvers.data import load_doc
from engine.solvers.solve import resolve_storey


def level(name, elevation_m, **kwargs):
    return {"name": name, "elevation_m": elevation_m, **kwargs}


@pytest.mark.parametrize("names", [(" Ground  floor ", "GROUND FLOOR"), ("Étage", "E\u0301tage"),
                                    ("KELLARI", "kellari"), ("Våning", "våning")])
def test_unicode_and_whitespace_names(names):
    assert len(canonical_storeys([level(names[0], 3), level(names[1], 3.0008)])) == 1


def test_tolerance_is_metric_and_does_not_chain():
    assert len(canonical_storeys([level("Level", 0), level("Level", .0008), level("Level", .0016)])) == 2
    assert len(canonical_storeys([level("Level", 0), level("Level", .002)])) == 2


def test_distinct_names_heights_buildings_and_unknowns_stay_distinct():
    cases = [(level("A", 0), level("B", 0)), (level("A", 0), level("A", 3)),
             (level("A", None), level("A", None)), (level("", 0), level("", 0)),
             (level("A", 0, building_id="a"), level("A", 0, building_id="b")),
             (level("1. Floor", 0), level("2. Floor", 0))]
    for pair in cases:
        assert len(canonical_storeys(list(pair))) == 2


def test_numbered_alias_requires_unprefixed_name_at_same_height():
    raw = [level("7. Deck", 6), level("Deck", 6.0005), level("Deck", 6), level("8. Deck", 9)]
    original = deepcopy(raw)
    groups = canonical_storeys(raw)
    assert len(groups) == 2
    assert groups[0]["source_indices"] == [0, 1, 2]
    assert raw == original
    assert resolve_storey("How many rooms on Deck?", groups) == "7. Deck"


def fixture(tmp_path, elevations=(0, 0, 0, 3, 3), names=None):
    names = names or ["0. Ground", "Ground", "Ground", "1. Upper", "Upper"]
    raw = [level(n, z) for n, z in zip(names, elevations)]
    elements = [{"item_id": f"room-{k}", "kind": "room", "name": f"Room {k}", "storey": st,
                 "quantities": {"area_m2": k + 10}, "props": {}, "ifc_class": "IfcSpace"} for k, st in enumerate(raw)]
    folder = tmp_path / "test__levels"
    folder.mkdir()
    (folder / "elements.json").write_text(json.dumps({"storeys": raw, "elements": elements}))
    return "test__levels", raw


def test_count_preserves_citations_trace_and_original_calc_pointers(tmp_path):
    doc_id, raw = fixture(tmp_path, elevations=(3, 3, 3, 0, 0))
    result = solve("How many storeys?", doc_id, root=tmp_path)
    assert result["answer"]["value"] == 2
    assert result["citations"] and result["evidence"]["scene"]["highlight_item_ids"]
    trace = next(t for t in result["trace"] if t["step"] == "dedupe_storeys")
    assert "3 duplicate" in trace["detail"]
    assert sum(len(g["sources"]) - 1 for g in trace["groups"]) == 3
    rows = result["_calc"]["rows"]
    assert sum(r["values"]["count"] for r in rows) == 2
    for row in rows:
        idx = int(row["source"]["field"].removeprefix("storeys[").removesuffix("]"))
        assert row["label"] == raw[idx]["name"]
    assert len({r["source"]["field"] for r in rows}) == len(raw)


def test_aliases_are_grouped_once_for_rooms_and_ordinals(tmp_path):
    doc_id, _ = fixture(tmp_path)
    doc = load_doc(doc_id, tmp_path)
    assert len(doc.storeys) == 2
    assert [i.storey for i in doc.items] == ["0. Ground"] * 3 + ["1. Upper"] * 2
    assert resolve_storey("rooms on first floor", doc.storeys) == "1. Upper"
    assert solve("How many rooms on the ground floor?", doc_id, root=tmp_path)["answer"]["value"] == 3
    assert solve("How many rooms on Upper?", doc_id, root=tmp_path)["answer"]["value"] == 2
    result = storey_compare("How many rooms per floor?", doc, time.perf_counter())
    assert result["answer"]["value"] == 5
    assert result["answer"]["text_md"].count("0. Ground") == 1
    assert any(t["step"] == "dedupe_storeys" for t in result["trace"])


def test_unknown_elevations_count_without_crashing_or_assuming_order(tmp_path):
    doc_id, _ = fixture(tmp_path, elevations=(None,) * 5)
    result = solve("How many storeys?", doc_id, root=tmp_path)
    assert result["answer"]["value"] == 5
    assert "elevation unavailable" in result["answer"]["text_md"]
    assert resolve_storey("rooms on the first floor", load_doc(doc_id, tmp_path).storeys) is None


def test_raw_duplicate_list_is_deduped_before_ordinal_resolution():
    raw = [level("Ground", 0), level("Ground", .0005), level("Upper", 3)]
    assert resolve_storey("first floor", raw) == "Upper"


def test_same_name_different_heights_remain_separate_room_scopes(tmp_path):
    doc_id, _ = fixture(tmp_path, elevations=(0, 0, 3, 3, 3), names=["Deck"] * 5)
    doc = load_doc(doc_id, tmp_path)
    assert len(doc.storeys) == 2
    assert len({s["name"] for s in doc.storeys}) == 2
    assert resolve_storey("rooms on Deck", doc.storeys) is None
    assert solve("How many rooms on the first floor?", doc_id, root=tmp_path)["answer"]["value"] == 3
    result = storey_compare("How many rooms per floor?", doc, time.perf_counter())
    assert result["answer"]["value"] == 5
