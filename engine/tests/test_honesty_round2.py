"""Round 2 regressions. Geometry is generated for demo; real cases replay separately."""
from unittest.mock import Mock

import pytest

from engine.answer import answer
from engine.tests.test_honesty import write_plan


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")
    monkeypatch.setenv("EXPLAIN", "0")


@pytest.mark.parametrize("noun", ["sauna", "bedroom", "kitchen"])
def test_unclassified_room_gets_visual_count_and_numbered_source_box(tmp_path, monkeypatch, noun):
    d = write_plan(tmp_path, [{"item_id": "room-1", "kind": "room", "bbox_px": [0, 0, 400, 400], "props": {}, "conf": .9}])
    (d / "page-1.png").touch()  # model calls below are mocked; no image decoding
    monkeypatch.delenv("MODELS_FAKE")
    count = Mock(return_value=(1, .001, "test-vision"))
    boxes = Mock(return_value=([[10, 10, 100, 100]], .002, "test-boxes"))
    monkeypatch.setattr("engine.recount.recount", count)
    monkeypatch.setattr("engine.recount.detect", boxes)
    reader = Mock(side_effect=AssertionError("Evidence already found"))
    monkeypatch.setattr("engine.answer._reader", reader)
    result = answer(f"How many {noun}s are on this floor plan?", [d.name])
    assert result["answer"]["value"] == 1 and not result["answer"]["abstained"]
    assert result["answer"]["unit"] == "count"
    assert len(result["evidence"]["boxes"]) == 1
    assert result["citations"][0]["item_ids"] == [result["evidence"]["boxes"][0]["item_id"]]
    assert result["cost"]["usd_total"] == .003
    assert result["reasoning"]["confidence"]["label"] == "Estimate"
    count.assert_called_once_with(f"How many {noun}s are on this floor plan?", d / "page-1.png", noun)


@pytest.mark.parametrize("boxes", [None, [], [[10, 10, 100, 100], [20, 20, 110, 110]]])
def test_unbacked_visual_count_still_reaches_reader(tmp_path, monkeypatch, boxes):
    import engine.answer as mod
    d = write_plan(tmp_path)
    (d / "page-1.png").touch()
    monkeypatch.delenv("MODELS_FAKE")
    monkeypatch.setattr("engine.recount.recount", lambda *a: (1, 0, "test"))
    monkeypatch.setattr("engine.recount.detect", lambda *a: (boxes, 0, "test"))
    reader = Mock(return_value=None)
    monkeypatch.setattr(mod, "_reader", reader)
    result = answer("How many saunas are on this floor plan?", [d.name])
    reader.assert_called_once()
    assert result["answer"]["abstained"] and result["answer"]["value"] is None


def test_hidden_rooms_are_not_resurrected_by_visual_recount(tmp_path, monkeypatch):
    d = write_plan(tmp_path)
    (d / "page-1.png").touch()
    monkeypatch.delenv("MODELS_FAKE")
    count = Mock(side_effect=AssertionError("Must respect edit layer"))
    monkeypatch.setattr("engine.recount.recount", count)
    monkeypatch.setattr("engine.answer._reader", lambda *a: None)
    result = answer("How many saunas are on this floor plan?", [d.name], scene_state={"hidden": ["room-1"]})
    assert result["answer"]["abstained"]
    count.assert_not_called()


@pytest.mark.parametrize("question", ["What is the floor area?", "What is the fire rating of the doors?"])
def test_missing_index_looks_at_readable_source_before_abstaining(tmp_path, monkeypatch, question):
    d = write_plan(tmp_path)
    (d / "page-1.png").touch()
    reader = Mock(return_value=None)
    monkeypatch.setattr("engine.answer._reader", reader)
    result = answer(question, [d.name])
    reader.assert_called_once()
    assert result["answer"]["abstained"] and result["answer"]["value"] is None


def test_source_reader_can_supply_cited_area_without_room_polygons(tmp_path, monkeypatch):
    import engine.answer as mod
    d = write_plan(tmp_path)
    (d / "page-1.png").touch()
    def reader(q, ids, root, trace, calls, t0, emit):
        result = mod._abstained(q, ids, "**Room 302: 1240 ft².** [1]", trace, t0)
        result["answer"].update(value=1240, unit="ft²", confidence=.8, abstained=False)
        result["citations"] = [{"n": 1, "doc_id": ids[0], "page": 1, "kind": "text", "bbox_px": [10, 10, 100, 20], "item_ids": [], "quote": "302 Reading 1240 SF"}]
        return result
    monkeypatch.setattr(mod, "_reader", reader)
    result = answer("What is the area of room 302?", [d.name])
    assert result["answer"]["value"] == 1240 and result["answer"]["unit"] == "ft²"
    assert not result["answer"]["abstained"] and result["citations"]


def test_printed_schedule_precedes_missing_floor_geometry(tmp_path, monkeypatch):
    from engine.tests.test_od_pdf import write_doc, DOC
    write_doc(tmp_path)
    reader = Mock(side_effect=AssertionError("Printed schedule answers without models"))
    monkeypatch.setattr("engine.answer._reader", reader)
    result = answer("What is the area of room 302 in the finish room schedule?", [DOC])
    assert result["answer"]["value"] == 1240 and result["answer"]["unit"] == "ft²"
    assert result["citations"] and not result["answer"]["abstained"]


def test_unsuccessful_source_lookup_still_reports_its_cost(tmp_path, monkeypatch):
    d = write_plan(tmp_path)
    (d / "page-1.png").touch()
    def reader(q, ids, root, trace, calls, t0, emit):
        calls.append({"task": "reader_plan", "provider": "mock", "model": "mock", "cost_usd": .02})
        return None
    monkeypatch.setattr("engine.answer._reader", reader)
    result = answer("What is the floor area?", [d.name])
    assert result["answer"]["abstained"] and result["cost"]["usd_total"] == .02


def test_reader_cost_preserves_existing_calls_without_double_counting(tmp_path, monkeypatch):
    import time
    import engine.answer as mod
    first = {"task": "read_drawing", "cost_usd": .01}
    second = dict(first)  # two separate calls can have identical metadata
    res = mod._abstained("q", ["doc"], "Unavailable", [], time.perf_counter(), calls=[first, second])
    shared = [first]
    monkeypatch.setattr(mod, "_reader", lambda *a: None)
    result = mod._use_reader(res, "q", ["doc"], tmp_path, [], shared, time.perf_counter(), lambda *a: None)
    assert result["cost"]["usd_total"] == .02 and len(result["cost"]["calls"]) == 2

