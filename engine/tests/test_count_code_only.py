import engine.models as models
from engine.explain import explain


def _res(unit, value):
    return {"answer": {"text_md": f"**There are {value} doors in this model.** [1]", "value": value, "unit": unit, "abstained": False,
                       "confidence": 1.0},
            "route": "index", "citations": [{"n": 1, "item_ids": ["a"]}], "trace": [{"step": "count", "detail": "254 door", "model": None}],
            "cost": {"usd_total": 0, "calls": []}}


def test_count_is_never_reworded_by_a_model(monkeypatch, tmp_path):
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    monkeypatch.setenv("EXPLAIN", "1")
    monkeypatch.setattr(models, "call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called for a count")))
    r = explain(_res("count", 254), "How many doors?", tmp_path)
    assert r["cost"]["usd_total"] == 0 and r["answer"]["text_md"].startswith("**There are 254")


def test_ifc_count_proof_says_model_not_drawing():
    from engine.reasoning_parts import counts
    f = {"counts": {"door": 254}, "total": 254, "boxes": 254, "per_kind": {"door": 254}, "linked": 254, "problems": [],
         "model": True, "cite": 1}
    assert "building model" in counts._found(f)["text"] and "drawing" not in counts._found(f)["text"]
    f["model"] = False
    assert "drawing" in counts._found(f)["text"]


def test_threshold_number_is_never_taken_as_a_count_noun():
    from engine.reasoning_parts import counts
    res = {"answer": {"text_md": "**Two doors: Bathroom door is 760 mm wide, below your 900 mm threshold.**", "value": 2, "unit": "count",
                      "abstained": False}, "citations": [], "evidence": {"boxes": []}, "trace": []}
    f = counts.facts(res, "What are the widths of each door? Which are below my 900 mm screening threshold?")
    assert list(f["counts"]) == ["door"]
    ans = res["answer"]
    counts._rewrite_headline(ans, f)
    assert "900 mm threshold" in ans["text_md"] and "2 mm" not in ans["text_md"]
    assert "mm threshold" not in counts._found(f)["text"]
