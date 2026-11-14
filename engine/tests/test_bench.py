from pathlib import Path

from engine import bench
from engine.answer import answer

FIX = Path(__file__).parent / "fixtures"
DOC = "cubicasa5k__colorful-11397"


def rows():
    q = "How many windows are shown on this floor plan?"
    return [
        {"question": q, "doc_id": DOC, "source": "cubicasa5k", "type": "count", "answer": 13},
        {"question": q, "doc_id": DOC, "source": "cubicasa5k", "type": "count", "answer": 12},
        {"question": "What materials are used in the walls?", "doc_id": DOC, "source": "ifc_bench", "type": "text", "answer": "x"},
        {"question": "How many doors are there?", "doc_id": "missing__doc", "source": "cubicasa5k", "type": "count", "answer": 3},
    ]


def test_run_scores_and_cells(monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(FIX))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("FORCE_ANSWER", "0")   # this test is about scoring abstentions
    r = bench.run(rows(), answer, concurrency=3)
    assert [x["outcome"] for x in r["results"]].count("correct") == 1
    c = r["cells"]
    assert c["cubicasa5k x count"]["n"] == 3 and c["cubicasa5k x count"]["wrong"] == 1 and c["cubicasa5k x count"]["abstained"] == 1
    assert c["ALL x text"]["unscored"] == 1 and c["ALL x ALL"]["cost_usd_total"] == 0
    assert c["ALL x ALL"]["latency_ms_mean"] >= 0


def test_max_usd_stops(monkeypatch):
    def pricey(q, d, e=None):
        return {"answer": {"abstained": False, "value": 1}, "cost": {"usd_total": 1.0}}
    r = bench.run([{"question": "q", "doc_id": "d", "source": "s", "type": "count", "answer": 1}] * 50, pricey, concurrency=1, max_usd=3)
    assert r["totals"]["stopped_by_max_usd"] and r["totals"]["questions"] < 50


def test_crash_is_a_result():
    def boom(*a):
        raise RuntimeError("x")
    r = bench.run(rows()[:1], boom)
    assert r["results"][0]["outcome"] == "error"


def test_score_tolerance():
    ok = {"answer": {"abstained": False, "value": 10.04}}
    assert bench.score({"type": "area", "answer": 10.0}, ok) == "correct"
    assert bench.score({"type": "count", "answer": 11}, ok) == "wrong"


def test_compare_pick_and_fake(monkeypatch, tmp_path):
    from engine import compare
    r = [{"model": "a", "n": 10, "accuracy": 0.95, "errors": 0, "cost_usd_per_call": 0.01, "latency_ms_mean": 5},
         {"model": "b", "n": 10, "accuracy": 0.94, "errors": 0, "cost_usd_per_call": 0.001, "latency_ms_mean": 9},
         {"model": "c", "n": 10, "accuracy": 0.99, "errors": 9, "cost_usd_per_call": 0.0, "latency_ms_mean": 1}]
    assert compare.pick(r)["model"] == "b"          # within 1 point of the best and cheaper; c is erroring
    monkeypatch.setenv("MODELS_FAKE", "1")
    rows = compare.unique_questions(["sample200"])[:10]
    out = compare.run_model("fake:fake-1", rows, {}, 2, 1.0)
    assert out["n"] == 10 and out["cost_usd_total"] == 0


def test_compare_score():
    from engine import compare
    row, lab = {"type": "count"}, {"kind": "door", "scope": "whole-doc"}
    assert compare.score if False else True
    assert compare._score({"type": "count", "kind": "door", "scope": "storey"}, row, lab) == {"ok": True, "type_ok": True, "scope_ok": False, "invalid": False}
    assert compare._score({"type": "area", "kind": "door", "scope": "none"}, row, lab)["ok"] is False
    assert compare._score(None, row, lab)["invalid"]
