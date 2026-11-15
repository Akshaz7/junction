from engine.answer import reconcile_cost


def test_refusal_cost_equals_recorded_calls():
    res = {"answer": {"abstained": True}, "cost": {"usd_total": 0, "calls": []},
           "trace": [{"step": "read", "model": "claude-opus-5-5", "cost_usd": 0.0078},
                     {"step": "read", "model": "claude-opus-5-5", "cost_usd": 0.0078},
                     {"step": "abstain", "model": None, "cost_usd": 0}]}
    r = reconcile_cost(res)
    assert len(r["cost"]["calls"]) == 2 and r["cost"]["usd_total"] == 0.0156


def test_no_double_count_when_calls_already_listed():
    res = {"cost": {"usd_total": 0.01, "calls": [{"model": "m", "cost_usd": 0.01}]},
           "trace": [{"step": "x", "model": "m", "cost_usd": 0.01}]}
    assert reconcile_cost(res)["cost"] == {"usd_total": 0.01, "calls": [{"model": "m", "cost_usd": 0.01}]}


def test_total_recomputed_from_calls():
    res = {"cost": {"usd_total": 0, "calls": [{"model": "m", "cost_usd": 0.02}]}, "trace": []}
    assert reconcile_cost(res)["cost"]["usd_total"] == 0.02


def test_raster_count_not_reworded(monkeypatch, tmp_path):
    import engine.models as models
    from engine.explain import explain
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    monkeypatch.setenv("EXPLAIN", "1")
    monkeypatch.setattr(models, "call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    res = {"answer": {"text_md": "**4 windows.** [1]", "value": 4, "unit": "count", "abstained": False},
           "route": "planmap", "citations": [{"n": 1}], "trace": [], "cost": {"usd_total": 0, "calls": []}}
    assert explain(res, "How many windows?", tmp_path)["cost"]["calls"] == []
