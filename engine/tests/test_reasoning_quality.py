import json

from engine.reasoning_parts import quality


def _doc(tmp_path, scene=None, planmap=None):
    d = tmp_path / "d1"
    d.mkdir()
    if scene is not None:
        (d / "scene.json").write_text(json.dumps(scene))
    if planmap is not None:
        (d / "planmap-1.json").write_text(json.dumps(planmap))
    return d


def test_scene_quality_copied(tmp_path):
    _doc(tmp_path, scene={"quality": {"summary": " Walls match within 2% ", "score": 0.93, "ci95": [0.9, 0.95]}})
    res = {"doc_ids": ["d1"], "reasoning": {"steps": [1], "confidence": {}}}
    quality.attach(res, tmp_path)
    assert res["reasoning"]["quality"] == {"summary": "Walls match within 2%", "score": 0.93}


def test_falls_back_to_planmap(tmp_path):
    _doc(tmp_path, scene={}, planmap={"quality": {"summary": "Rooms match"}})
    assert quality.for_doc("d1", tmp_path) == {"summary": "Rooms match"}


def test_error_blank_or_missing_is_ignored(tmp_path):
    _doc(tmp_path, scene={"quality": {"error": "boom", "summary": "x"}})
    assert quality.for_doc("d1", tmp_path) is None
    _doc_dir = tmp_path / "d1"
    (_doc_dir / "scene.json").write_text(json.dumps({"quality": {"summary": "  "}}))
    assert quality.for_doc("d1", tmp_path) is None
    assert quality.for_doc("nope", tmp_path) is None
    res = {"doc_ids": ["d1"], "reasoning": {"steps": [1]}}
    quality.attach(res, tmp_path)
    assert "quality" not in res["reasoning"]
    quality.attach({"doc_ids": ["d1"]}, tmp_path)  # no reasoning: no crash
