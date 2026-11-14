"""E-33: project search covers registry, restored datasets and structured data without model calls."""
import json
import time

import pytest

from engine import project_index as PI
from engine.project_answer import project_answer


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def doc(root, did, title, **meta):
    d = root / did
    write(d / "doc.json", {"doc_id": did, "title": title, "source": did.split("__")[0], **meta})
    return d


def plan(d, label, page=1):
    write(d / f"planmap-{page}.json", {"page": page, "items": [
        {"item_id": "room-001", "kind": "room", "label": label, "conf": 1,
         "bbox_px": [10, 10, 100, 100], "props": {"area_m2": 12}}]})


def ask(root, question):
    return project_answer(question, [], None, [], time.perf_counter(), root)


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    PI._CACHE.clear()

    def unexpected(*args, **kwargs):
        pytest.fail("Document lists must not call a model")

    monkeypatch.setattr("engine.models.call", unexpected)


def test_schedule_titles_and_registry_metadata_are_indexed(tmp_path):
    # Production may have a registry entry before that sheet's files are restored.
    records = [
        {"doc_id": "opening_design__aalseth-residence-a600-schedules", "title": "A600 Schedules", "kind": "pdf"},
        {"doc_id": "opening_design__ctr-a700-schedules", "title": "A700 Schedules", "kind": "pdf"},
    ]
    (tmp_path / "registry.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    d = doc(tmp_path, "opening_design__a801", "A-801 Door Schedule", kind="pdf")
    write(d / "text-1.json", {"words": [{"text": "Door table"}]})
    d = doc(tmp_path, "opening_design__notes", "General notes", kind="pdf")
    write(d / "text-1.json", {"words": [{"text": "List of equipment and table of materials"}]})
    ix = PI.build_all(tmp_path)
    expected = {r["doc_id"] for r in records} | {"opening_design__a801"}
    assert len(ix.docs) == 4
    assert {h["doc_id"] for h in ix.search("a600 schedules")} >= {records[0]["doc_id"]}
    for question in ("Which drawings have a door schedule?", "List the drawings with schedules", "Which sheets have a table of doors?",
                     "Which drawings have a door list?"):
        a = ask(tmp_path, question)
        assert set(a["doc_ids"]) == expected
        assert not a["answer"]["abstained"]
        assert len(a["citations"]) == len(expected)
        assert a["cost"]["usd_total"] == 0
        assert "check the sheet" in a["answer"]["text_md"]
        for c in a["citations"]:
            assert ix.docs[c["doc_id"]]["title"] in a["answer"]["text_md"]
            assert c["page"] == 1


@pytest.mark.parametrize("space", [
    {"kind": "room", "props": {"long_name": "Küche"}},
    {"ifc_class": "IfcSpace", "LongName": "Küche"},
])
def test_kitchen_ifc_longname_planmap_labels_and_page_text(tmp_path, space):
    d = doc(tmp_path, "ifc_bench__office", "Office building", kind="ifc")
    write(d / "elements.json", {"elements": [space, {"kind": "door", "name": "D1"}]})
    # IFC documents must also index their plan-map labels, rather than choosing one data source.
    plan(d, "Archive", page=2)
    d = doc(tmp_path, "swiss_dwellings__ground", "Ground floor", kind="dxf", pages=3)
    plan(d, "Kitchen", page=3)
    d = doc(tmp_path, "plans__swedish", "Swedish plan", kind="pdf")
    write(d / "text-2.json", {"page": 2, "words": [{"text": "Kök"}]})
    d = doc(tmp_path, "plans__finnish", "Finnish plan", kind="dxf")
    plan(d, "Keittiö")
    ix = PI.build_all(tmp_path)
    assert ix.search("archive")[0]["doc_id"] == "ifc_bench__office"
    assert ix.search("door")[0]["doc_id"] == "ifc_bench__office"
    for term in ("kitchen", "Küche", "kök", "keittiö"):
        a = ask(tmp_path, f"Which drawings show the {term}?")
        assert set(a["doc_ids"]) == set(ix.docs)
        pages = {c["doc_id"]: c["page"] for c in a["citations"]}
        assert pages["swiss_dwellings__ground"] == 3
        assert pages["plans__swedish"] == 2


def test_fixtures_and_generated_docs_excluded_before_limit(tmp_path, monkeypatch):
    for i in range(20):
        plan(doc(tmp_path, f"uploads__upload-fixture-{i}", "Kitchen Kitchen Kitchen"), "Kitchen")
    plan(doc(tmp_path, "samples__flagged", "Example", generated_for_demo=True), "Kitchen")
    plan(doc(tmp_path, "samples__title", "Kitchen generated for demo"), "Kitchen")
    real = doc(tmp_path, "uploads__real-plan", "Actual upload", kind="dxf")
    plan(real, "Kitchen")
    ix = PI.build_all(tmp_path)
    a = ask(tmp_path, "Which drawings show the kitchen?")
    assert a["doc_ids"] == [real.name]
    assert {h["doc_id"] for h in ix.search("kitchen")} == {real.name}
    # Explicit selection still uses the normal per-document path, even for fixtures.
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("RECOUNT", "0")
    monkeypatch.setenv("TEXT_WITH_MODEL", "0")
    from engine.answer import answer
    selected = answer("How many rooms?", ["uploads__upload-fixture-0"])
    assert not selected["answer"]["abstained"]
    assert selected["answer"]["value"] == 1


def test_lists_cap_at_fifteen_with_exact_remaining_count(tmp_path):
    for i in range(18):
        doc(tmp_path, f"sheets__a{i:03}-schedules", f"A{i:03} Schedules", kind="pdf")
    PI.build_all(tmp_path)
    a = ask(tmp_path, "Which drawings have a door schedule?")
    assert len(a["doc_ids"]) == len(a["citations"]) == 15
    assert len(set(c["doc_id"] for c in a["citations"])) == 15
    assert "and 3 more" in a["answer"]["text_md"]
    assert [c["n"] for c in a["citations"]] == list(range(1, 16))


def test_load_discovers_dataset_docs_restored_after_image_build(tmp_path):
    doc(tmp_path, "baked__a100", "A100 Floor plan")
    PI.build_all(tmp_path)
    assert set(PI.load_index(tmp_path).docs) == {"baked__a100"}
    # server.artifact_store restores dataset ids, not just uploads__ ids.
    d = doc(tmp_path, "opening_design__a600-schedules", "A600 Schedules")
    write(d / "text-2.json", {"words": [{"text": "Door schedule table"}]})
    a = ask(tmp_path, "Which drawings have a door schedule?")
    assert a["doc_ids"] == [d.name]
    assert a["citations"][0]["page"] == 2
    PI._CACHE.clear()
    assert d.name in PI.load_index(tmp_path).docs


def test_wc_toilet_synonyms_and_structured_page_refresh(tmp_path):
    d = doc(tmp_path, "plans__bathrooms", "Bathrooms")
    plan(d, "WC", page=2)
    ix = PI.build_all(tmp_path)
    assert ask(tmp_path, "Which drawings have toilets?")["doc_ids"] == [d.name]
    (d / "planmap-2.json").unlink()
    plan(d, "Kitchen", page=3)
    assert PI.upsert_doc(d.name, tmp_path)
    ix = PI.load_index(tmp_path)
    assert not ix.search("toilet")
    assert (d.name, 2) not in ix.chunks
    assert ask(tmp_path, "Which drawings show the kitchen?")["citations"][0]["page"] == 3


def test_no_match_does_not_invent_a_document(tmp_path):
    doc(tmp_path, "plans__a100", "A100 Floor plan")
    PI.build_all(tmp_path)
    a = ask(tmp_path, "Which drawings have a kitchen?")
    assert a["answer"]["abstained"]
    assert a["doc_ids"] == a["citations"] == []


def test_empty_schedule_list_does_not_call_paid_reader(tmp_path, monkeypatch):
    d = doc(tmp_path, "plans__a100", "A100 Floor plan")
    write(d / "planmap-1.json", {"items": [{"kind": "door", "item_id": "door-001", "conf": 1}]})
    PI.build_all(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("READER", "1")
    from engine.answer import answer
    a = answer("Which drawings have a door schedule?", [])
    assert a["answer"]["abstained"]
    assert a["doc_ids"] == a["citations"] == []
    assert not any(s["step"] == "reader" for s in a["trace"])
