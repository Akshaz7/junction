import json
from types import SimpleNamespace

import pytest

from engine import scan_count


def test_box_validation_and_valve_deduplication():
    raw = [{"box": [100, 100, 200, 200]}, {"box": [105, 105, 195, 195]},
           {"box": [100, 200, 200, 300]}, {"box": [0, 0, 0, 10]},
           {"box": [float("nan"), 0, 1, 2]}, {"box": [-1, 0, 1, 2]}, {"box": []}, None]
    out = scan_count.pixel_boxes(raw, 2000, 1000, "valve")
    assert [i["bbox_px"] for i in out] == [[200, 100, 400, 200], [400, 100, 600, 200]]


@pytest.mark.parametrize("q,kind", [
    ("How many tanks or vessels are on this diagram?", "tank"),
    ("How many instruments (gauges, transmitters, controllers) are on this piping diagram?", "instrument"),
    ("How many valves and pumps are shown?", None),
    ("What pressure do the valves handle?", None),
])
def test_target(q, kind):
    assert scan_count.target(q) == kind


def test_count_equals_numbered_cited_boxes(tmp_path, monkeypatch):
    from PIL import Image
    import engine.models
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    d = tmp_path / "drawing"
    d.mkdir()
    Image.new("RGB", (1000, 1000)).save(d / "page-1.png")
    Image.new("RGB", (100, 100)).save(d / "page-1.thumb.png")
    raw = {"is_pid": True, "uncertain": True, "items": [
        {"box": [100, 100, 200, 200]}, {"box": [105, 105, 195, 195]}, {"box": [300, 300, 400, 400]}]}
    monkeypatch.setattr(engine.models, "call", lambda *a, **kw: SimpleNamespace(json=raw, cost_usd=.01, provider="test", model="test"))
    r = scan_count.answer_counts("How many valves are on this piping diagram?", ["drawing"], tmp_path)
    assert r["answer"]["value"] == len(r["evidence"]["boxes"]) == len(r["citations"]) == 2
    assert [b["label"] for b in r["evidence"]["boxes"]] == ["1", "2"]
    assert r["reasoning"]["confidence"]["label"] == "Estimate"
    assert r["cost"]["usd_total"] == .01
    assert scan_count.answer_counts("How many pumps are scheduled?", ["drawing"], tmp_path) is None
    (d / "elements.json").write_text(json.dumps({"elements": []}))
    assert scan_count.answer_counts("How many pumps are on this diagram?", ["drawing"], tmp_path) is None


def test_unreachable_provider_keeps_reader(tmp_path, monkeypatch):
    from PIL import Image
    import engine.models
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    d = tmp_path / "drawing"
    d.mkdir()
    Image.new("RGB", (20, 20)).save(d / "page-1.png")
    def fail(*a, **kw):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(engine.models, "call", fail)
    assert scan_count.answer_counts("Count valves on this diagram", ["drawing"], tmp_path) is None


def test_engine_reaches_symbol_route_before_text_fallback(tmp_path, monkeypatch):
    from PIL import Image
    from engine import answer, models
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("EXPLAIN", "0")
    d = tmp_path / "drawing"
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"kind": "raster", "title": "Process diagram", "pages": 1}))
    Image.new("RGB", (1000, 1000)).save(d / "page-1.png")
    Image.new("RGB", (100, 100)).save(d / "page-1.thumb.png")
    called = []
    def call(task, *a, **kw):
        called.append(task)
        assert kw["schema"] == scan_count.SCHEMA
        return SimpleNamespace(json={"is_pid": True, "uncertain": False, "items": [{"box": [100,100,200,200]}]},
                               cost_usd=0, provider="test", model="test")
    monkeypatch.setattr(models, "call", call)
    r = answer.answer("How many valves are on this piping diagram?", ["drawing"])
    assert r["answer"]["value"] == len(r["evidence"]["boxes"]) == 1
    assert called == ["read_drawing"]


def test_reader_does_not_assert_zero_from_missing_boxes(tmp_path, monkeypatch):
    from PIL import Image
    import engine.models
    monkeypatch.delenv("MODELS_FAKE", raising=False)
    d = tmp_path / "drawing"
    d.mkdir()
    Image.new("RGB", (100, 100)).save(d / "page-1.png")
    monkeypatch.setattr(engine.models, "call", lambda *a, **kw: SimpleNamespace(
        json={"is_pid": True, "uncertain": True, "items": []}, cost_usd=0, provider="test", model="test"))
    r = scan_count.answer_counts("Count valves on this diagram", ["drawing"], tmp_path)
    assert r["answer"]["value"] is None and "could not reliably locate" in r["answer"]["text_md"]
