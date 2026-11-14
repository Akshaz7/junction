import json
import time

import pytest

from engine import library as L, project_index as PI
from server.schema import validate_answer


def record(n, **kw):
    return {"doc_id": f"plans__building-{n}", "title": f"Building {n}", "source": "plans", "kind": "pdf", "pages": 1, **kw}


def test_live_catalogue_not_baked_search_index(tmp_path):
    docs = [record(n) for n in range(384)]
    a = L.library_answer("How many drawings are in the library?", tmp_path, records=docs)
    validate_answer(a)
    assert a["answer"]["value"] == len(docs) == 384
    assert "same visible catalogue as Data" in a["answer"]["text_md"]
    assert a["cost"]["usd_total"] == 0


def test_ifc_projects_are_enumerated_from_metadata(tmp_path):
    docs = [record(1, title="Example Tower", kind="ifc"), record(2, title="River School", formats=["pdf", "ifc"]),
            record(3, title="Community Hall", files={"ifc": "hall.ifc"}), record(4, title="PDF only")]
    a = L.library_answer("Which projects have IFC models?", tmp_path, docs)
    validate_answer(a)
    assert a["answer"]["value"] == 3
    assert all(s in a["answer"]["text_md"] for s in ("Example Tower", "River School", "Community Hall"))
    assert "PDF only" not in a["answer"]["text_md"]
    assert len(a["citations"]) == 3


@pytest.mark.parametrize("title", ["smoke-new-plan", "STRESS-uploads", "qa-small", "web3-notes-run", "generated for demo house"])
def test_noise_excluded_from_counts_and_search(tmp_path, title):
    docs = [record(1, title="Public sauna floor plan"), record(2, title=title)]
    for d in docs:
        folder = tmp_path / d["doc_id"]
        folder.mkdir()
        (folder / "doc.json").write_text(json.dumps(d))
        (folder / "text-1.json").write_text(json.dumps({"text": "Sauna", "page": 1}))
    PI.build_all(tmp_path)
    assert L.library_answer("How many drawings are in the library?", tmp_path)["answer"]["value"] == 1
    a = L.library_search_answer("Find floor plans with a sauna.", tmp_path)
    validate_answer(a)
    assert a["doc_ids"] == [docs[0]["doc_id"]]
    assert title not in a["answer"]["text_md"]


def test_sheet_count_prefers_pdf_metadata_and_does_not_invent_count(tmp_path):
    docs = [record(1, title="Cedar School pricing set", pages=11), record(2, title="Cedar School IFC", kind="ifc", pages=1)]
    a = L.sheet_count_answer("How many sheets are in the Cedar School pricing set?", root=tmp_path, records=docs)
    validate_answer(a)
    assert a["answer"]["value"] == 11 and a["doc_ids"] == [docs[0]["doc_id"]]
    b = L.sheet_count_answer("How many sheets are in this drawing set?", [docs[0]["doc_id"]], tmp_path, docs)
    assert b["answer"]["value"] == 11
    docs[0]["pages"] = None
    assert L.sheet_count_answer("How many pages?", [docs[0]["doc_id"]], tmp_path, docs)["answer"]["abstained"]


def test_no_selection_does_not_pick_even_one_available_drawing(tmp_path):
    docs = [record(1, title="Only available plan")]
    a = L.drawing_selection_answer("How many windows are there?", tmp_path, records=docs)
    validate_answer(a)
    assert a["doc_ids"] == [] and a["answer"]["value"] is None
    assert "Which drawing" in a["answer"]["text_md"] and "Only available plan" in a["answer"]["text_md"]
    assert L.drawing_selection_answer("How many windows in Only available plan?", tmp_path, records=docs) is None
    assert L.drawing_selection_answer("Find floor plans with a sauna.", tmp_path, records=docs) is None


def test_selection_lists_at_most_three_and_keeps_followup_context(tmp_path):
    docs = [record(n) for n in range(10)]
    a = L.drawing_selection_answer("What is the floor area?", tmp_path, records=docs)
    assert a["answer"]["text_md"].count("\n- ") == 3
    history = [{"role": "assistant", "content": "Four windows.", "doc_ids": [docs[0]["doc_id"]]}]
    assert L.drawing_selection_answer("And doors?", tmp_path, history, docs) is None


def test_catalogue_is_request_local(tmp_path):
    token = L.CATALOGUE.set([record(1)])
    try:
        assert L.library_answer("How many drawings are in the library?", tmp_path)["answer"]["value"] == 1
    finally:
        L.CATALOGUE.reset(token)
    assert L.CATALOGUE.get() is None


def test_reader_snapshot_uses_registered_quotes_and_citations(tmp_path):
    from engine.reader.tools import Session
    session = Session(["plans__building-1"], tmp_path)
    session.reg("text", "plans__building-1", 2, [10, 20, 30, 40], "Slab reinforcement: D13 @ 300", ["note-1"])
    calls = [{"task": "reader_plan", "provider": "fake", "model": "fake", "cost_usd": 0.0}]
    a = L.reader_partial("What reinforcement?", session.doc_ids, session, [], calls, time.perf_counter())
    validate_answer(a)
    assert "D13 @ 300" in a["answer"]["text_md"]
    assert a["citations"][0]["page"] == 2 and a["citations"][0]["quote"] == "Slab reinforcement: D13 @ 300"
    assert a["evidence"]["boxes"][0]["label"] == "1"
    assert a["evidence"]["scene"]["highlight_item_ids"] == ["note-1"]
    assert a["answer"]["value"] is None and a["answer"]["confidence"] <= 0.5
