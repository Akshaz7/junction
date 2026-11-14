"""F-EVFIX: selected count, actual boxes, linked items and recount stay honest."""
import copy
import json

import pytest

from engine import reasoning
from engine.reasoning_parts.counts import facts


def response(n=6, boxed=None, linked=None, *, reread=None, headline=None):
    boxed = n if boxed is None else boxed
    linked = n if linked is None else linked
    return {
        "doc_ids": ["test"], "route": "planmap",
        "answer": {"text_md": headline or f"There are **{n} doors** on level **2**. [1]",
                   "value": n, "unit": "count", "confidence": 0.95, "abstained": False},
        "citations": [{"n": 1, "doc_id": "test", "page": 1, "kind": "region", "quote": None,
                       "item_ids": [f"vision-{i}" for i in range(linked)]}],
        "evidence": {"boxes": [{"item_id": f"vision-{i}", "page": 1,
                                  "bbox_px": [i * 2, 0, i * 2 + 1, 1], "label": str(i + 1)} for i in range(boxed)],
                     "scene": {"doc_id": "test", "highlight_item_ids": []}},
        "trace": ([{"step": "recount", "detail": f"plan map {reread[0]}, drawing re-read {reread[1]}: test"}] if reread else []),
    }


def attach(res, tmp_path):
    return reasoning.attach(res, "How many doors are there?", tmp_path)


def texts(res):
    return " ".join(s["text"] for s in res["reasoning"]["steps"])


def test_new_vision_boxes_are_found_without_saved_planmap(tmp_path):
    r = attach(response(reread=(4, 6)), tmp_path)
    assert r["reasoning"]["steps"][0]["text"].startswith("6 doors marked")
    assert "originally counted 4" in texts(r) and "independent look counted 6" in texts(r)
    assert "headline reports the 6 boxed items" in texts(r)
    assert "kept the 4 boxed" not in texts(r) and "marked region" not in texts(r)
    assert r["reasoning"]["confidence"]["label"] == "Estimate"
    assert r["answer"]["value"] == 6 and "6 boxed doors" in r["answer"]["text_md"]


def test_unboxed_recount_has_explicit_coverage_and_selected_policy(tmp_path):
    r = attach(response(6, boxed=4, reread=(4, 6)), tmp_path)
    assert "answer reports 6 doors; 4 numbered boxes" in texts(r)
    assert "2 are not boxed yet" in texts(r)
    assert "source count; 4 have numbered boxes" in r["answer"]["text_md"]
    assert "level **2**" in r["answer"]["text_md"]
    assert r["answer"]["value"] == 6 and len(r["evidence"]["boxes"]) == 4
    assert r["reasoning"]["confidence"]["pct"] <= 69


def test_rejected_recount_reports_boxed_policy(tmp_path):
    r = attach(response(4, reread=(4, 6)), tmp_path)
    assert "headline reports the 4 boxed items" in texts(r)
    assert "suggests 2 more than are boxed" in texts(r)
    assert "4 boxed doors" in r["answer"]["text_md"]


def test_drop_does_not_call_original_plan_count_the_boxed_count(tmp_path):
    r = attach(response(2, reread=(4, 2)), tmp_path)
    assert "originally counted 4" in texts(r)
    assert "headline reports the 2 boxed items" in texts(r)
    assert "kept the 4 boxed" not in texts(r)


def test_citation_groups_are_not_item_counts(tmp_path):
    r = attach(response(6), tmp_path)
    assert len(r["citations"]) == 1 and "6 doors marked" in texts(r)
    assert "1 marked region" not in texts(r)
    assert r["reasoning"]["confidence"]["label"] != "Estimate"


def test_existing_cards_cannot_bypass_invariant(tmp_path):
    r = response(6)
    r["reasoning"] = {"steps": [{"kind": "found", "title": "Found", "text": "4 doors, each one numbered"}],
                      "confidence": {"label": "Verified", "pct": 99}}
    attach(r, tmp_path)
    assert "4 doors" not in texts(r) and "6 doors marked" in texts(r)
    assert r["reasoning"]["confidence"]["pct"] <= 69


def test_stale_headline_is_repaired_without_changing_floor_or_bullets(tmp_path):
    r = attach(response(6, headline="There are **4 doors** on level **2**. [1]\n\n- Doors are timber."), tmp_path)
    assert "**6 doors** on level **2**" in r["answer"]["text_md"]
    assert "[1]" in r["answer"]["text_md"] and r["answer"]["text_md"].endswith("- Doors are timber.")
    assert r["reasoning"]["confidence"]["label"] == "Estimate"


def test_old_checked_card_is_reconciled_even_without_trace(tmp_path):
    r = response(6, boxed=4)
    r["reasoning"] = {"steps": [{"kind": "checked", "text": "A second, independent look counted 6; kept the 4 boxed"}],
                      "confidence": {"label": "Verified", "pct": 97}}
    attach(r, tmp_path)
    assert "second, independent look counted 6" in texts(r)
    assert "only 4 have numbered boxes" in texts(r)
    assert "2 are not boxed yet" in texts(r)
    assert r["reasoning"]["confidence"]["label"] == "Estimate"


@pytest.mark.parametrize("headline", ["There are **4** doors. [1]", "**Doors:** **4**. [1]", "There are **4**. [1]", "**4**. [1]"])
def test_markdown_cannot_hide_a_stale_headline_number(headline, tmp_path):
    r = attach(response(6, headline=headline), tmp_path)
    assert "4" not in r["answer"]["text_md"]
    assert "6" in r["answer"]["text_md"] and "[1]" in r["answer"]["text_md"]


@pytest.mark.parametrize("n,boxed,linked", [(0, 0, 0), (1, 0, 1), (6, 4, 6), (4, 6, 4), (6, 6, 4), (846, 300, 846)])
def test_partial_zero_and_truncated_selections_are_explicit(n, boxed, linked, tmp_path):
    r = attach(response(n, boxed, linked), tmp_path)
    t = texts(r)
    if boxed < n:
        assert f"{n - boxed:,} are not boxed yet" in t
    if boxed > n:
        assert f"{boxed - n:,} more boxes" in t
    if linked != n:
        assert f"Citations link {linked:,} individual items" in t
    if n == 0:
        assert "does not prove none exist" in t
    if n != boxed or n != linked:
        assert r["reasoning"]["confidence"]["label"] == "Estimate"


def test_duplicate_citations_are_counted_once(tmp_path):
    r = response()
    r["citations"].append(dict(r["citations"][0], n=2))
    attach(r, tmp_path)
    assert "Citations link" not in texts(r)
    assert facts(r, "How many doors?")["linked"] == 6


def test_multidoc_item_ids_are_scoped_to_their_document(tmp_path):
    r = response(6)
    r["doc_ids"].append("other")
    r["citations"][0]["item_ids"] = ["a", "b", "c"]
    r["citations"].append(dict(r["citations"][0], n=2, doc_id="other"))
    assert facts(r, "How many doors?")["linked"] == 6


def test_multikind_distribution_is_checked_even_when_total_matches(tmp_path):
    r = response(6)
    r["answer"].update(value={"door": 2, "window": 4}, text_md="**2 doors** and **4 windows**. [1]")
    r["citations"][0].update(item_kind="door")
    for b in r["evidence"]["boxes"]:
        b["kind"] = "door"
    attach(r, tmp_path)
    assert "Boxes by kind: 6 doors and 0 windows" in texts(r)
    assert r["reasoning"]["confidence"]["label"] == "Estimate"


def test_agreeing_multikind_counts_keep_confidence(tmp_path):
    r = response(6)
    r["answer"].update(value={"door": 2, "window": 4}, text_md="**2 doors** and **4 windows**. [1]")
    for i, b in enumerate(r["evidence"]["boxes"]):
        b["kind"] = "door" if i < 2 else "window"
    attach(r, tmp_path)
    assert "2 doors and 4 windows marked" in texts(r)
    assert r["reasoning"]["confidence"]["label"] != "Estimate"


def test_invalid_boxes_and_repeated_links_do_not_prove_a_count(tmp_path):
    r = response(3)
    r["evidence"]["boxes"][1]["item_id"] = "vision-0"
    r["evidence"]["boxes"][2]["bbox_px"] = [0, 0, 0, 0]
    attach(r, tmp_path)
    assert "2 numbered boxes" in texts(r) and "repeat an item link" in texts(r)


def test_difference_operands_are_not_rewritten_to_the_answer(tmp_path):
    r = response(2, boxed=10, linked=10, headline="**Yes**: **6 doors** vs **4 windows**. [1]")
    r["trace"] = [{"step": "route", "detail": "arithmetic -> independent solver results, no model"}]
    attach(r, tmp_path)
    assert r["answer"]["text_md"] == "**Yes**: **6 doors** vs **4 windows**. [1]"
    assert "10 input items" in texts(r) and "rather than counted from the boxes" in texts(r)


def test_dimensions_are_not_confused_with_count_values(tmp_path):
    r = response()
    r["answer"].update(value=26.5, unit="m2", text_md="The area is **26.5 m²**. [1]")
    card = {"steps": [{"kind": "found", "text": "6 rooms on level 2"}], "confidence": {"label": "Verified", "pct": 95}}
    r["reasoning"] = copy.deepcopy(card)
    attach(r, tmp_path)
    assert r["reasoning"] == card


def test_invariant_is_idempotent(tmp_path):
    r = attach(response(6, boxed=4, reread=(4, 6)), tmp_path)
    original = copy.deepcopy(r)
    attach(r, tmp_path)
    assert r == original


@pytest.mark.parametrize("value", [None, True, float("nan"), -1, 1.5, {"door": None}])
def test_missing_or_non_count_values_do_not_crash(value, tmp_path):
    r = response()
    r["answer"]["value"] = value
    assert attach(r, tmp_path) is r


@pytest.mark.parametrize("reread,detected,want", [(6, 6, 6), (6, 5, 4), (2, 2, 2), (4, 4, 4), (3, 3, 4)])
def test_real_recount_ladder_keeps_all_evidence_in_sync(reread, detected, want, tmp_path, monkeypatch):
    from engine.answer import _recount_ladder
    from engine.router.parser import parse
    import engine.recount as rc
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    monkeypatch.setenv("RECOUNT", "1")
    monkeypatch.setenv("DET_BOXES", "0")
    doc = tmp_path / "test"
    doc.mkdir()
    items = [{"item_id": f"vision-{i}", "kind": "door", "bbox_px": [i * 2, 0, i * 2 + 1, 1],
              "source": "det", "conf": 0.8} for i in range(4)]
    (doc / "planmap-1.json").write_text(json.dumps({"page": 1, "items": items}))
    (doc / "page-1.png").touch()  # image access is mocked; no inference in this test
    monkeypatch.setattr(rc, "recount", lambda *a: (reread, 0, "test-model"))
    monkeypatch.setattr(rc, "detect", lambda *a: ([[i * 2, 0, i * 2 + 1, 1] for i in range(detected)], 0, "test-model"))
    r = response(4)
    r["evidence"]["scene"]["highlight_item_ids"] = [b["item_id"] for b in r["evidence"]["boxes"]]
    r["citations"][0]["label"] = "Floor plan · 4 doors"
    _recount_ladder(r, "How many doors?", "test", parse("How many doors?"), tmp_path, [], None)
    attach(r, tmp_path)
    assert r["answer"]["value"] == len(r["evidence"]["boxes"]) == want
    assert len(r["citations"][0]["item_ids"]) == want
    assert len(r["evidence"]["scene"]["highlight_item_ids"]) == want
    if want != 4:
        assert f"{want} doors" in r["citations"][0]["label"]
    assert f"headline reports the {want} boxed items" in texts(r)
    assert "marked region" not in texts(r)
