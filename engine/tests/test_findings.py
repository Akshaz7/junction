from pathlib import Path

import pytest

from engine import findings
from engine.rules import load_rules
from engine.solvers.data import Doc, Item

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"


@pytest.mark.skipif(not (ROOT / DOC).exists(), reason="artifact missing")
def test_ac20_findings_cite_rule_and_item():
    fs = findings.run(DOC)
    assert fs
    ids = {r["id"] for r in load_rules()}
    for f in fs:
        assert f["rule_id"] in ids and f["source"]["quote"] and f["item_ids"]
        assert f["severity"] in ("fail", "suggestion")
    assert any(f["check_id"] == "exits_per_storey" for f in fs)


def _doc(width):
    d = Item("d1", "door", q={"width_m": width, "height_m": 2.1}, storey="L1", name="Door 1", bbox_m=[[0, 0, 0], [width, 2.1, 0.1]])
    return Doc("x", "ifc", [d], "x", [{"name": "L1", "elevation_m": 0}])


def test_narrow_door_fails_and_wide_is_silent():
    bad = [f for f in findings.run_doc(_doc(0.7)) if f["check_id"] == "door_clear_width"]
    assert bad and bad[0]["severity"] == "fail" and bad[0]["item_ids"] == ["d1"]
    assert not [f for f in findings.run_doc(_doc(1.0)) if f["check_id"] == "door_clear_width"]


def test_near_limit_is_a_suggestion():
    f = [f for f in findings.run_doc(_doc(0.9)) if f["check_id"] == "door_clear_width"]
    assert f and f[0]["severity"] == "suggestion"
