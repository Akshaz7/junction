"""WHY-CORE: length/area answers carry Source, Scale, Calculation and How sure steps."""
import json
import os
from pathlib import Path

import pytest

from engine import measure_why

ROOT = Path(__file__).resolve().parents[2] / "artifacts"


def _src(did="d", page=1, **kw):
    return {"doc_id": did, "page": page, **kw}


def _res(steps, rows=(), unit="m2", value=13.75, route="planmap", trace=()):
    return {"answer": {"value": value, "unit": unit, "text_md": "x"}, "route": route, "doc_ids": ["d"],
            "citations": [{"n": 1, "doc_id": "d", "page": 1, "item_ids": ["room-7"]}], "trace": list(trace),
            "reasoning": {"steps": [{"kind": "measured", "title": "Measured", "text": "16309 px² × 0.029 m/px", "cite": 1, "ok": None}],
                          "calc": {"steps": steps, "rows": list(rows), "margin": {}, "status": "complete"}}}


def _titles(res):
    return [s["title"] for s in res["reasoning"]["steps"]]


def test_area_outline(tmp_path):
    steps = [{"id": "outline-0", "unit": "m2", "value": 13.746, "operation": "multiply",
              "inputs": [{"name": "outline", "value": 16309, "unit": "px2", "source": _src()},
                         {"name": "scale", "value": 0.0290322, "unit": "m/px", "source": _src()},
                         {"name": "scale", "value": 0.0290322, "unit": "m/px", "source": _src()}]}]
    res = measure_why.attach(_res(steps, [{"item_id": "room-7", "values": {"area_m2": 13.75, "kind": "room"},
                                            "source": _src(artifact="planmap-1.json", item_id="room-7", origin="det")}]), tmp_path)
    t = _titles(res)
    assert t == ["Source", "Scale", "Calculation", "How sure"]   # Measured merged, not repeated
    calc = res["reasoning"]["steps"][2]["text"]
    assert "16,309 px² × 0.02903² m²/px² = 13.75 m²" in calc


def test_distance_points_and_missing(tmp_path):
    steps = [{"id": "p", "unit": "px", "value": 155.05, "operation": "polyline",
              "inputs": [{"name": "point 1 x", "value": 295, "unit": "px", "source": {}}, {"name": "point 1 y", "value": 279, "unit": "px", "source": {}},
                         {"name": "point 2 x", "value": 299, "unit": "px", "source": {}}, {"name": "point 2 y", "value": 434, "unit": "px", "source": {}}]},
             {"id": "l", "unit": "m", "value": 4.5015, "operation": "multiply",
              "inputs": [{"name": "pixel length", "value": 155.05, "unit": "px", "source": {}},
                         {"name": "metres per pixel", "value": 0.0290322, "unit": "m/px", "source": _src()}]}]
    res = measure_why.attach(_res(steps, unit="m", value=4.5, route="hybrid"), tmp_path)
    text = " ".join(s["text"] for s in res["reasoning"]["steps"])
    assert "√(4² + 155²)" in text and "0.02903 m/px = 4.502 m" in text
    bare = measure_why.attach(_res([], unit="m", value=4.5, route="hybrid"), tmp_path)
    src = next(s for s in bare["reasoning"]["steps"] if s["title"] == "Source")["text"]
    assert "without recorded points" in src


def test_skips_counts_and_abstained(tmp_path):
    r = _res([], unit="count", value=3)
    assert _titles(measure_why.attach(r, tmp_path)) == ["Measured"]
    r = _res([]); r["answer"]["abstained"] = True
    assert _titles(measure_why.attach(r, tmp_path)) == ["Measured"]


def test_idempotent(tmp_path):
    r = _res([])
    once = _titles(measure_why.attach(r, tmp_path))
    assert _titles(measure_why.attach(r, tmp_path)) == once


@pytest.mark.skipif(not (ROOT / "ifc_bench__ac20-arc" / "elements.json").is_file(), reason="artifacts missing")
def test_real_ifc_area_says_model_units():
    os.environ.setdefault("MODEL_PROVIDER", "fake")
    from engine.answer import answer
    r = answer("What is the total floor area?", ["ifc_bench__ac20-arc"])
    steps = {s["title"]: s["text"] for s in r["reasoning"]["steps"]}
    assert steps["Scale"].startswith("Model units (metres)")
    assert "door" not in steps["Scale"].lower()
    assert steps["How sure"].startswith("Exact from the model")


def test_ifc_steps_kept_and_max(tmp_path):
    r = _res([{"id": "ifc-max", "operation": "max", "unit": "m", "value": 2.0,
               "inputs": [{"value": 2.0, "unit": "m"}, {"value": 2.0, "unit": "m"}, {"value": 0.9, "unit": "m"}]}],
             [{"item_id": "g", "values": {"length_m": 2.0, "kind": "door"}, "source": _src(artifact="elements.json", origin="ifc")}],
             unit="m", value=2.0)
    r["reasoning"]["steps"] = [{"id": "ifc-measured", "kind": "measured", "title": "Measured", "text": "2.0 m × 1", "cite": 1, "ok": None}]
    out = measure_why.attach(r, tmp_path)["reasoning"]["steps"]
    assert any(s.get("id") == "ifc-measured" for s in out)
    calc = next(s for s in out if s["title"] == "Calculation")["text"]
    assert calc.startswith("Largest of 3 values (2 tied) = 2 m")


def test_distance_route_steps_left_alone(tmp_path):
    r = _res([], unit="m", value=4.5)
    r["reasoning"]["calc"]["distance"] = {"items": [{"item_id": "room-7", "name": "kitchen", "how": "outline centroid"},
                                                    {"item_id": "room-9", "name": "bathroom", "how": "outline centroid"}]}
    r["reasoning"]["steps"] = [{"kind": "measured", "title": "Measured", "text": "√(Δx² + Δy²) = 155 px × 0.029 m/px", "source": "distance", "cite": None, "ok": None}]
    out = measure_why.attach(r, tmp_path)["reasoning"]["steps"]
    assert out[1]["source"] == "distance" and out[1]["text"].startswith("√")
    src = out[0]["text"]
    assert "kitchen and bathroom" in src and "centroid" in src and "without recorded points" not in src
    assert not any(s["title"] == "Calculation" for s in out)
