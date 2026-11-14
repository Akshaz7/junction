"""S-22: dashboard uses completed measured runs and actual stored answer costs."""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server import config, db
from server.app import app

MEASURED = Path(__file__).resolve().parents[2] / "results" / "bench" / "e-s200-z1.json"


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO", tmp_path / "package")
    runtime = tmp_path / "runtime"
    (runtime / "bench").mkdir(parents=True)
    monkeypatch.setenv("RESULTS_DIR", str(runtime))
    monkeypatch.setenv("MODELS_COSTS_LOG", str(runtime / "costs.jsonl"))
    # No lifespan: these endpoints need neither ingestion nor background tasks.
    return TestClient(app), runtime


def write_run(directory, tag, *, fake=False, complete=True, mtime=1):
    data = json.loads(MEASURED.read_text())
    data["tag"] = tag
    data["fake"] = fake
    if not complete:
        data["totals"]["questions"] -= 1
    path = directory / f"{tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    os.utime(path, (mtime, mtime))
    return data


def test_prefers_report_run_over_newer_completed_run(dashboard):
    client, runtime = dashboard
    measured = write_run(runtime / "bench", "e-s200-z1", mtime=1)
    write_run(runtime / "bench", "newer-real", mtime=2)
    response = client.get("/api/bench/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["tag"] == "e-s200-z1" and body["file"] == "e-s200-z1.json"
    assert body["n"] == 200 and body["numeric_correct"] == 143 and body["numeric_total"] == 187
    assert body["accuracy"] == 0.7647 and body["abstentions"] == 0
    assert body["cost_usd_total"] == 0.020677 and body["cost_per_answer"] == 0.00010339
    assert body["by_type"]["count"] == measured["cells"]["ALL x count"]
    assert body["by_type"]["text"] == measured["cells"]["ALL x text"]
    assert body["data"] == measured
    assert client.get("/api/bench/latest?tag=newer-real").json()["tag"] == "newer-real"


@pytest.mark.parametrize("invalid", ["fake", "partial", "budget"])
def test_selects_newest_completed_real_run(dashboard, invalid):
    client, runtime = dashboard
    write_run(runtime / "bench", "older-real", mtime=1)
    write_run(runtime / "bench", "newer-real", mtime=2)
    write_run(runtime / "bench", "invalid", fake=invalid == "fake", complete=invalid != "partial", mtime=3)
    if invalid == "budget":
        path = runtime / "bench" / "invalid.json"
        data = json.loads(path.read_text())
        data["totals"]["stopped_by_max_usd"] = True
        path.write_text(json.dumps(data))
    (runtime / "bench" / "broken.json").write_text("broken")
    (runtime / "bench" / "row-dump.rows.jsonl").write_text('{"tag":"row-dump"}')
    assert client.get("/api/bench/latest").json()["tag"] == "newer-real"


def test_baked_results_survive_empty_runtime_directory(dashboard):
    client, runtime = dashboard
    write_run(config.REPO / "results" / "bench", "e-s200-z1")
    assert not list((runtime / "bench").iterdir())
    response = client.get("/api/bench/latest")
    assert response.status_code == 200 and response.json()["tag"] == "e-s200-z1"
    assert client.get("/api/bench").json()["benches"][0]["tag"] == "e-s200-z1"


def test_missing_measurements_are_not_zero_or_404(dashboard):
    client, runtime = dashboard
    write_run(runtime / "bench", "fake-only", fake=True)
    response = client.get("/api/bench/latest")
    assert response.status_code == 200
    assert response.json()["status"] == "no_bench"
    for field in ("n", "numeric_correct", "numeric_total", "accuracy", "cost_per_answer"):
        assert response.json()[field] is None
    assert client.get("/api/bench/latest?tag=fake-only").json()["data"]["fake"] is True
    assert client.get("/api/bench/latest?tag=missing").status_code == 404


def test_cost_summary_uses_24h_answers_and_trace_fallback(dashboard, monkeypatch):
    client, runtime = dashboard
    pool = AsyncMock()
    pool.fetch.return_value = [
        {"answer": json.dumps({"cost": {"usd_total": 0}, "trace": [{"cost_usd": 10}]})},
        {"answer": {"cost": {"usd_total": 0.01}, "trace": [{"cost_usd": 10}]}},
        {"answer": {"trace": [{"cost_usd": 0.02}, {"cost_usd": 0.01}]}},
        {"answer": {"trace": [{"step": "no recorded cost"}]}},
        {"answer": {"cost": {"usd_total": "NaN"}}},
    ]
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=pool))
    (runtime / "costs.jsonl").write_text(
        '{"cost_usd":0.1}\n{"cost_usd":0.2}\ninvalid\n[]\n{"cost_usd":"NaN"}\n')
    response = client.get("/api/costs/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_usd"] == 0.3 and body["calls"] == 2
    assert body["answers"] == 5 and body["answers_with_cost"] == 3 and body["answers_missing_cost"] == 2
    assert body["answer_cost_usd_total"] == 0.04
    assert body["median_cost_per_answer"] == 0.01
    assert body["cost_sources"] == {"answer.cost.usd_total": 2, "answer.trace": 1}
    assert body["window_hours"] == 24
    assert "created_at >= now() - interval '24 hours'" in pool.fetch.call_args.args[0]


def test_cost_summary_empty_and_unavailable_database(dashboard, monkeypatch):
    client, _ = dashboard
    pool = AsyncMock()
    pool.fetch.return_value = []
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=pool))
    body = client.get("/api/costs/summary").json()
    assert body["total_usd"] == 0 and body["answers"] == 0
    assert body["median_cost_per_answer"] is None
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=None))
    assert client.get("/api/costs/summary").status_code == 503
