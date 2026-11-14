"""Project-wide search: index build/upsert on a tiny temp artifacts dir, retrieval, take-off, passage citations."""
import json

import pytest

from engine import project_index as PI
from engine.answer import answer
from engine.project_answer import page_lines


def _doc(root, doc_id, **meta):
    d = root / doc_id
    d.mkdir(parents=True)
    (d / "doc.json").write_text(json.dumps({"doc_id": doc_id, "source": "acme", "title": meta.pop("title", doc_id), **meta}))
    return d


def _words(lines):
    ws = []
    for r, (y, text) in enumerate(lines):
        x = 100.0
        for w in text.split():
            ws.append({"text": w, "bbox_px": [x, y, x + 10 * len(w), y + 20]})
            x += 10 * len(w) + 8
    return {"doc_id": "x", "page": 1, "image": {"w": 2000, "h": 1500}, "words": ws}


def _plan(d, rooms, windows=3):
    items = [{"item_id": f"room-{i}", "kind": "room", "label": n, "bbox_px": [i * 100, 0, i * 100 + 90, 90], "polygon_px": None,
              "props": {"area_m2": a}, "conf": 1.0, "source": "dxf"} for i, (n, a) in enumerate(rooms, 1)]
    items += [{"item_id": f"window-{i}", "kind": "window", "label": None, "bbox_px": [i * 10, 5, i * 10 + 8, 9], "polygon_px": None,
               "props": {}, "conf": 0.9, "source": "rule"} for i in range(1, windows + 1)]
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": d.name, "page": 1, "image": {"w": 800, "h": 600},
                                                  "scale": {"m_per_px": 0.02, "method": "dxf_units_fit", "confidence": 1.0}, "items": items}))


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    PI._CACHE.clear()
    d = _doc(tmp_path, "acme__fire-strategy", kind="pdf", title="Fire Strategy Report", pages=2, formats=["pdf"])
    (d / "text-1.json").write_text(json.dumps(_words([(100, "General notes for the project"), (140, "Stair core walls shall achieve EI 60 fire resistance"),
                                                      (160, "with self closing doors"), (600, "Site address 12 Example Road")])))
    (d / "text-2.json").write_text(json.dumps({**_words([(100, "Car park ventilation requirements")]), "page": 2}))
    d = _doc(tmp_path, "acme__ground-floor", kind="dxf", title="Ground Floor Plan Block A", pages=1, formats=["dxf"])
    _plan(d, [("WC", 4.0), ("WC 2", 3.5), ("Kitchen", 12.0), ("Bad", 6.0)])
    d = _doc(tmp_path, "acme__basement", kind="pdf", title="Basement Layout", pages=1, formats=["pdf"])
    (d / "text-1.json").write_text(json.dumps(_words([(100, "Basement storage and plant room")])))
    d = _doc(tmp_path, "acme__first-floor", kind="dxf", title="First Floor Plan Block A", pages=1, formats=["dxf"])
    _plan(d, [("Office", 20.0)], windows=5)
    PI.build_all(tmp_path)
    return tmp_path


def test_build_search_and_incremental_upsert(root):
    ix = PI.load_index(root)
    assert set(ix.docs) == {"acme__fire-strategy", "acme__ground-floor", "acme__basement", "acme__first-floor"}
    top = ix.search("EI 60 stair core")[0]
    assert top["doc_id"] == "acme__fire-strategy" and top["page"] == 1
    assert ix.search("car park ventilation")[0]["page"] == 2
    # a doc ingested later becomes searchable without a rebuild
    d = _doc(root, "uploads__roof-plan", kind="pdf", title="Roof Plan", pages=1, source="uploads")
    (d / "text-1.json").write_text(json.dumps(_words([(100, "Green roof drainage layer detail")])))
    assert PI.upsert_doc("uploads__roof-plan", root) is True
    assert PI.load_index(root).search("green roof drainage")[0]["doc_id"] == "uploads__roof-plan"
    # refresh replaces the old chunks
    (d / "text-1.json").write_text(json.dumps(_words([(100, "Solar panels array")])))
    PI.upsert_doc("uploads__roof-plan", root)
    ix = PI.load_index(root)
    assert not [h for h in ix.search("drainage") if h["doc_id"] == "uploads__roof-plan"]
    assert ix.search("solar panels")[0]["doc_id"] == "uploads__roof-plan"
    assert PI.upsert_doc("nope", root) is False


def test_no_index_keeps_old_chat_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    PI._CACHE.clear()
    a = answer("EI 60 stair core", [])
    assert a["doc_ids"] == [] and a["citations"] == [] and not a["trace"][-1]["step"] == "search"


def test_passage_citation_quotes_real_text_with_bbox(root):
    ev = []
    a = answer("Which fire resistance do the stair core walls need? EI 60", [], lambda k, p: ev.append((k, p)))
    assert any(p["text"].startswith("Searching: ") for k, p in ev if k == "status")
    assert a["doc_ids"] == ["acme__fire-strategy"] and a["citations"]
    c = a["citations"][0]
    lines = " ".join(l["text"] for l in page_lines("acme__fire-strategy", c["page"], root))
    assert c["kind"] == "text" and c["quote"] in lines and "EI 60" in c["quote"]
    assert c["bbox_px"] and c["bbox_px"][1] <= 140 and c["bbox_px"][3] >= 160
    assert a["evidence"]["boxes"][0]["bbox_px"] == c["bbox_px"]
    assert "[1]" in a["answer"]["text_md"]


def test_nothing_relevant_says_what_was_searched(root):
    a = answer("Where is the helicopter landing pad hydraulic crane?", [])
    assert a["answer"]["abstained"] and "helicopter" in a["answer"]["text_md"] and a["citations"] == []


def test_small_talk_keeps_chat_path(root):
    a = answer("Hello", [])
    assert not any(s["step"] == "search" for s in a["trace"]) and a["citations"] == []


def test_no_doc_numeric_question_routes_to_per_doc_path(root):
    a = answer("How many windows are in acme__ground-floor?", [])
    assert a["doc_ids"] == ["acme__ground-floor"] and a["answer"]["value"] == 3 and a["cost"]["usd_total"] == 0
    assert a["trace"][0]["step"] == "search" and any(s["step"] == "route" for s in a["trace"])


def test_ambiguous_numeric_question_does_not_guess(root):
    a = answer("How many windows are shown on this floor plan?", [])
    assert a["answer"]["value"] is None and a["answer"]["abstained"] is True


def test_takeoff_toilets_sums_rooms_with_waste_and_cites_each(root):
    a = answer("How many square metres of tiling should I order for the toilets in acme__ground-floor?", [])
    assert a["answer"]["unit"] == "m2" and a["doc_ids"] == ["acme__ground-floor"]
    assert a["answer"]["value"] == pytest.approx((4.0 + 3.5) * 1.10, abs=0.06)       # WC + WC 2 only
    t = a["answer"]["text_md"]
    assert "general guidance" in t and "7.5" in t and "Formula" in t
    assert len(a["citations"]) == 2 and {c["kind"] for c in a["citations"]} == {"region"}
    assert [b["label"] for b in a["evidence"]["boxes"]] == ["1", "2"]
    assert a["cost"]["usd_total"] == 0


def test_takeoff_german_room_names_and_no_match(root):
    from engine.solvers.data import load_doc
    from engine.takeoff import parse_takeoff, rooms_of
    doc = load_doc("acme__ground-floor", root)
    names = [i.label for i, _ in rooms_of(doc, parse_takeoff("how much tile for the bathroom"))]
    assert names == ["Bad"]
    a = answer("How many square metres of tiling for the sauna in acme__ground-floor?", [])
    assert a["answer"]["abstained"] and a["answer"]["value"] is None


def test_named_doc_with_selected_docs_path_unchanged(root):
    a = answer("How many windows are shown on this floor plan?", ["acme__ground-floor"])
    assert a["answer"]["value"] == 3 and a["trace"][0]["step"] == "route"
