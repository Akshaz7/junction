"""QA-LIVE fixes: exact sizes, storey/kind comparisons, deterministic recount, markers on every route, project search coverage."""
import pytest

AC = "ifc_bench__ac20-arc"
C1 = "cubicasa5k__colorful-11397"


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")


def need(d):
    from engine.solvers import ARTIFACTS
    if not (ARTIFACTS / d).exists():
        pytest.skip("artifact not present")


def A(q, d):
    from engine.answer import answer
    return answer(q, [d])


def test_exact_width_is_equality_not_all_doors():
    need(AC)
    a = A("How many doors are 1.8 m wide?", AC)
    assert a["answer"]["value"] == 9 and a["cost"]["usd_total"] == 0


def test_two_named_storeys_are_compared():
    need(AC)
    a = A("Compare doors on the 1st vs 2nd floor", AC)
    t = a["answer"]["text_md"]
    assert "1. Obergeschoss" in t and "2. Obergeschoss" in t and "22" in t and "21" in t


@pytest.mark.parametrize("d,q,both", [(AC, "Which has more, doors or windows?", (77, 206)), (C1, "Are there more windows or doors?", None)])
def test_kind_comparison_counts_both(d, q, both):
    need(d)
    t = A(q, d)["answer"]["text_md"]
    if both:
        assert all(str(v) in t for v in both)
    else:
        assert "more" in t or "equally" in t


def test_largest_room_ignores_outdoor_spaces():
    need(C1)
    t = A("What is the largest room?", C1)["answer"]["text_md"]
    assert "terrace" not in t.lower().split("next")[0] and "TERASSI" not in t.split("Next")[0]


def test_ensure_markers_makes_a_citation_when_only_boxes_exist():
    from engine.answer import ensure_markers
    res = {"doc_ids": ["d"], "answer": {"text_md": "There are **3 windows** on this floor plan.", "abstained": False}, "citations": [],
           "evidence": {"boxes": [{"item_id": "a", "page": 1, "bbox_px": [1, 2, 3, 4], "label": "1"}, {"item_id": "b", "page": 1, "bbox_px": [5, 6, 7, 8], "label": "2"}]}}
    ensure_markers(res)
    assert "[1]" in res["answer"]["text_md"] and res["citations"][0]["item_ids"] == ["a", "b"] and res["citations"][0]["bbox_px"] == [1, 2, 7, 8]


def test_recount_is_deterministic_per_drawing(tmp_path, monkeypatch):
    from engine import recount as R
    img = tmp_path / "p.png"
    img.write_bytes(b"fake-image-bytes")
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(R, "_CACHE", {})
    monkeypatch.setattr(R, "_LOADED", True)
    seq = iter([7, 6, 5])
    monkeypatch.setattr(R, "_recount_model", lambda q, i, k=None: (next(seq), 0.001, "m"))
    first = R.recount("How many windows?", img, "window")
    again = R.recount("how many windows", img, "window")
    assert first[0] == again[0] == 7 and again[1] == 0.0


def test_door_schedule_and_kitchen_questions_find_documents():
    from engine.project_index import load_index
    ix = load_index()
    if ix is None or len(ix.docs) < 100:
        pytest.skip("project index not built")
    from engine.answer import answer
    for q in ("Which drawings have a door schedule?", "Which drawings show the kitchen?"):
        a = answer(q, [])
        assert not a["answer"]["abstained"] and a["citations"], q
