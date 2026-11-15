"""Wall thickness answers on ac20 carry a value in metres and a complete IFC dimension calc."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"
need = pytest.mark.skipif(not (ROOT / DOC / "elements.json").is_file(), reason="ac20 artifacts missing")


@need
@pytest.mark.parametrize("q, value, formula", [
    ("How thick is the thickest wall?", 0.3, "answer = max(stored IFC quantities)"),
    ("How thick is the thinnest wall?", 0.2, "answer = min(stored IFC quantities)"),
    ("How thick are the walls?", 0.3, "answer = stored IFC quantity (metres)"),
])
def test_thickness_value_and_calc(q, value, formula):
    from engine.answer import answer
    r = answer(q, [DOC])
    assert r["conditions"]["handler"] == "h_thickness"
    assert r["answer"]["value"] == pytest.approx(value) and r["answer"]["unit"] == "m"
    ids = [i for c in r["citations"] for i in c.get("item_ids") or []]
    assert ids
    calc = r["reasoning"]["calc"]
    assert calc["status"] == "complete" and not calc.get("issues")
    assert calc["formula"] == formula
    assert {row["ifc_quantity"]["field"] for row in calc["rows"]} == {"quantities.width_m"}
    assert all(row["values"]["width_m"] == pytest.approx(value) for row in calc["rows"])
