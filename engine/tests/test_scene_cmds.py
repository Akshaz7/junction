from pathlib import Path

import pytest

from engine.answer import answer
from engine.scene_cmds import parse_scene, scene_answer, tags
from engine.solvers.data import load_doc

FIX = Path(__file__).parent / "fixtures"
DOC = "cubicasa5k__colorful-11397"


@pytest.fixture(autouse=True)
def root(monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(FIX))
    monkeypatch.setenv("MODELS_FAKE", "1")


@pytest.mark.parametrize("q,op,kind", [
    ("Hide the windows", "hide", "window"), ("show only the toilets", "isolate", "toilet"),
    ("highlight all the sinks", "highlight", "sink"), ("bring the windows back", "restore", "window"),
    ("reset the view", "reset", None), ("show everything", "reset", None),
])
def test_parse(q, op, kind):
    i = parse_scene(q)
    assert i and i.op == op and i.kind == kind


@pytest.mark.parametrize("q", ["How many windows are there?", "What is the area of the kitchen?", "Where are the doors?", "tell me a joke"])
def test_questions_are_not_commands(q):
    assert parse_scene(q) is None


def test_tags_unique_and_lettered():
    d = load_doc(DOC, FIX)
    t = tags(d)
    assert len(set(t.values())) == len(t)
    assert sorted(v for k, v in t.items() if v.startswith("W") and not v.startswith("WC")) == sorted(f"W{n}" for n in range(1, 14))
    assert {v for v in t.values() if v.startswith("WC")} == {"WC1", "WC2"}


def test_hide_command_shape():
    a = answer("Hide the windows", [DOC])
    cmd = a["evidence"]["scene"]["commands"][0]
    assert cmd["op"] == "hide" and len(cmd["item_ids"]) == 13 and a["cost"]["usd_total"] == 0
    assert a["route"] == "planmap" and not a["answer"]["abstained"]


def test_highlight_has_labels_and_boxes():
    a = answer("highlight the toilets", [DOC])
    cmd = a["evidence"]["scene"]["commands"][0]
    assert sorted(cmd["labels"].values()) == ["WC1", "WC2"] and a["evidence"]["scene"]["highlight_item_ids"] == cmd["item_ids"]
    assert sorted(b["label"] for b in a["evidence"]["boxes"]) == ["WC1", "WC2"]


def test_by_tag_and_missing():
    d = load_doc(DOC, FIX)
    w3 = next(k for k, v in tags(d).items() if v == "W3")
    a = answer("isolate W3", [DOC])
    assert a["evidence"]["scene"]["commands"][0]["item_ids"] == [w3]
    b = answer("hide the bathtubs", [DOC])
    assert b["answer"]["abstained"] and b["evidence"]["scene"]["commands"][0]["item_ids"] == []


def test_reset():
    a = answer("reset the view", [DOC])
    assert a["evidence"]["scene"]["commands"] == [{"op": "reset", "item_ids": []}]


def test_count_after_hide_carries_note():
    d = load_doc(DOC, FIX)
    w3 = next(k for k, v in tags(d).items() if v == "W3")
    a = answer("How many windows are shown on this floor plan?", [DOC], scene_state={"hidden": [w3]})
    assert a["answer"]["value"] == 12 and "with W3 hidden" in a["answer"]["text_md"]


def test_answers_validate_against_schema():
    import json, jsonschema
    schema = json.loads((Path(__file__).resolve().parents[2] / "server/schemas/answer.schema.json").read_text())
    for q in ("Hide the windows", "highlight the toilets", "reset the view", "hide the bathtubs"):
        jsonschema.validate(answer(q, [DOC]), schema)


@pytest.mark.parametrize("q,op", [("show me all the windows", "highlight"), ("undo", "undo"), ("remove window W7", "hide"),
                                  ("could you get W3 out of the picture", "hide"), ("make the windows vanish", "hide")])
def test_more_phrasing(q, op):
    i = parse_scene(q)
    assert i and i.op == op


def test_show_measure_is_not_a_command():
    assert parse_scene("show me the area of the kitchen") is None


def test_hide_sentence_and_labels():
    a = answer("remove window W7", [DOC])
    t = a["answer"]["text_md"]
    assert t.startswith("Window (W7)") and "is hidden. 12 of 13 windows remain visible." in t
    cmd = a["evidence"]["scene"]["commands"][0]
    assert list(cmd["labels"].values()) == ["W7"]


def test_undo_restores_hidden_state():
    h = answer("remove window W7", [DOC])["evidence"]["scene"]["commands"][0]["item_ids"]
    a = answer("undo", [DOC], scene_state={"hidden": h})
    c = a["evidence"]["scene"]["commands"][0]
    assert c["op"] == "restore" and c["item_ids"] == h
    untouched = answer("undo", [DOC])
    assert untouched["evidence"]["scene"]["commands"] == []
    assert "no scene edit to undo" in untouched["answer"]["text_md"]


@pytest.mark.parametrize("question", ["undo", "undo that"])
def test_undo_reverts_last_group_and_preserves_earlier_removal(question):
    doc = load_doc(DOC, FIX)
    by_tag = {tag: iid for iid, tag in tags(doc).items()}
    first, second = by_tag["W1"], [by_tag["W2"], by_tag["W3"]]
    state = {"hidden": [first, *second], "edits": [
        {"doc_id": DOC, "op": "hide", "item_ids": [first]},
        {"doc_id": "another-doc", "op": "hide", "item_ids": ["unrelated"]},
        {"doc_id": DOC, "op": "hide", "item_ids": second},
        {"doc_id": DOC, "op": "highlight", "item_ids": [first]},
    ]}
    result = answer(question, [DOC], scene_state=state)
    assert result["evidence"]["scene"]["commands"] == [{"op": "restore", "item_ids": sorted(second)}]


def test_legacy_undo_only_restores_last_hidden_item():
    result = answer("undo that", [DOC], scene_state={"hidden": ["older", "latest"]})
    assert result["evidence"]["scene"]["commands"] == [{"op": "restore", "item_ids": ["latest"]}]


def test_undo_restore_and_reset_even_when_nothing_is_hidden():
    for op in ("restore", "reset"):
        result = answer("undo", [DOC], scene_state={"hidden": [], "edits": [
            {"op": "hide", "item_ids": ["window-001"]}, {"op": op, "item_ids": []},
        ]})
        assert any(c["op"] == "hide" and c["item_ids"] == ["window-001"] for c in result["evidence"]["scene"]["commands"])


def test_clear_highlights_never_resets_hidden_items():
    result = answer("Clear highlights", [DOC], scene_state={"hidden": ["window-001"]})
    assert result["evidence"]["scene"]["commands"] == [{"op": "highlight", "item_ids": []}]
    assert not result["answer"]["abstained"]


@pytest.mark.parametrize("question", ["is it still compliant?", "is it compliant now?", "is the building still compliant?"])
def test_compliance_followup_checks_current_hidden_items(monkeypatch, question):
    seen = []
    def check(result, doc, hidden):
        seen.append(hidden)
        result["answer"]["text_md"] += " Current rule-check result."
    monkeypatch.setattr("engine.analytics.edit_advice", check)
    doc = load_doc(DOC, FIX)
    for hidden in (["window-001"], []):
        result = scene_answer(question, doc, parse_scene(question), {"hidden": hidden})
        assert seen[-1] == hidden
        assert result["evidence"]["scene"]["commands"] == []
        assert "rule-check result" in result["answer"]["text_md"]


def test_can_we_remove_is_a_preview_without_commands():
    a = answer("Can we remove window W7?", [DOC])
    t = a["answer"]["text_md"]
    assert t.startswith("Window (W7)") and "what-if" in t and "Preview only" in t
    assert a["evidence"]["scene"]["commands"] == []
    assert a["advisor_cards"]


def test_highlight_wording_plain():
    t = answer("highlight all the windows", [DOC])["answer"]["text_md"]
    assert t.startswith("Highlighted 13 windows on the drawing.")
