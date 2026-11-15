"""PLAN-WHY: plan-map wall-run / room-area answers record a calc that reproduces the answer (real artifacts)."""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "cubicasa5k__colorful-11397"
pytestmark = pytest.mark.skipif(not (ROOT / DOC / "planmap-1.json").is_file(), reason="artifact missing")


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "fake")


@pytest.mark.parametrize("q", ["How long is the longest wall?", "What is the total wall length?"])
def test_wall_runs_calc_complete(q):
    from engine.answer import answer
    r = answer(q, [DOC])
    c = r["reasoning"]["calc"]
    assert r["route"] == "planmap"
    assert c["status"] == "complete", c["issues"]
    assert any(s["id"] == "result" and s["value"] == r["answer"]["value"] for s in c["steps"])


def test_room_area_calc_reproduces_stored_total():
    from engine.calc import validate
    from engine.plan_measures import room_area_calc
    from engine.solvers.data import load_doc
    from engine.solvers.solve import _qty
    doc = load_doc(DOC, ROOT)
    rooms = [i for i in doc.items if i.kind == "room" and _qty(i, "room", "area") and (i.props or {}).get("model_room_type") != "outdoor"]
    out = [(i, "outdoor space") for i in doc.items if i.kind == "room" and (i.props or {}).get("model_room_type") == "outdoor"]
    total = round(sum(_qty(i, "room", "area") for i in rooms), 2)
    calc = room_area_calc({"answer": {"value": total, "unit": "m2"}}, doc, rooms, out)
    assert calc and validate(calc, ROOT) == []
    assert {e["reason"] for e in calc["excluded"]} == {"outdoor space"}
    assert all(r.get("measured_by") for r in calc["rows"])
