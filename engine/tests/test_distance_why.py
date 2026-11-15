"""DIST: distance answers record their two points, Δx, Δy, pixels, scale and result (real artifacts; skip if missing)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("MODEL_PROVIDER", "fake")
from engine import distance  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
RASTER = "cubicasa5k__colorful-11397"
IFC = "ifc_bench__ac20-arc"


def test_parse():
    assert distance.parse("What is the distance between the kitchen and the bathroom?")["a"] == "kitchen"
    assert distance.parse("How far is the kitchen from the bathroom?")["b"] == "bathroom"
    assert distance.parse("What is the gap between the bedroom and the kitchen?")["mode"] == "edge"
    assert distance.parse("What is the travel distance to the exit?") is None
    assert distance.parse("How many doors are there?") is None


@pytest.mark.skipif(not (ROOT / RASTER).is_dir(), reason="artifact missing")
def test_raster_distance_records_inputs():
    from engine.answer import answer
    r = answer("What is the distance between the kitchen and the bathroom?", [RASTER])
    assert r["route"] == "planmap" and not r["answer"]["abstained"]
    calc = r["reasoning"]["calc"]
    d = calc["distance"]
    assert [i["item_id"] for i in d["items"]][0] == "room-007" and d["m_per_px"] and d["pixels"]
    ids = {s["id"] for s in calc["steps"]}
    assert {"dist-a-x", "dist-a-y", "dist-b-x", "dist-b-y", "dist-dx", "dist-dy", "dist-px", "dist-m", "result"} <= ids
    assert abs(d["pixels"] * d["m_per_px"] - d["metres"]) < 1e-9
    assert not [i for i in calc["issues"] if i.startswith("dist-") or "Final calculation" in i], calc["issues"]
    assert len(r["citations"]) == 2 and len(r["evidence"]["boxes"]) == 2
    text = " ".join(s.get("text") or "" for s in r["reasoning"]["steps"])
    assert "√(" in text or "px" in text


@pytest.mark.skipif(not (ROOT / IFC).is_dir(), reason="artifact missing")
def test_ifc_no_kitchen_abstains_instead_of_wall_total():
    from engine.answer import answer
    r = answer("What is the distance between the kitchen and the bathroom?", [IFC])
    assert r["answer"]["abstained"] and r["answer"]["value"] is None


@pytest.mark.skipif(not (ROOT / RASTER).is_dir(), reason="artifact missing")
def test_px_step_is_polyline_with_item_points():
    from engine.answer import answer
    r = answer("What is the distance between the kitchen and the bathroom?", [RASTER])
    s = next(x for x in r["reasoning"]["calc"]["steps"] if x["id"] == "dist-px")
    assert s["operation"] == "polyline"
    assert [i["name"] for i in s["inputs"]] == ["point 1 x", "point 1 y", "point 2 x", "point 2 y"]
    assert [i["source"]["item_id"] for i in s["inputs"]][::2] == ["room-007", "room-wet-text-006"]


def test_annotate_reader_points_code_check():
    if not (ROOT / RASTER).is_dir():
        pytest.skip("artifact missing")
    res = {"route": "hybrid", "answer": {"value": 4.5, "unit": "m", "abstained": False},
           "reasoning": {"steps": [{"kind": "found", "title": "Found", "text": "x"}],
                         "calc": {"reader": {"calculations": [{"tool": "measure", "doc_id": RASTER, "page": 1, "closed": False,
                                                              "points": [[295, 279], [299, 434]], "m_per_px": 0.02903225806451613}]}}}}
    out = distance.annotate(res, "What is the distance between the kitchen and the bathroom?", ROOT)
    texts = [s["text"] for s in out["reasoning"]["steps"] if s.get("source") == "distance"]
    assert any("Model-picked points (295, 279 px)" in t and "not independently measured" in t for t in texts)
    assert out["reasoning"]["calc"]["distance"]["points_px"] == [[295, 279], [299, 434]]
