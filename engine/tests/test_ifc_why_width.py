"""Width-extreme answers on IFC carry a value in metres, cite every tie, and get a complete IFC calc."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
IFC = "ifc_bench__ac20-arc"
RASTER = "cubicasa5k__colorful-11397"
need = pytest.mark.skipif(not (ROOT / IFC / "elements.json").is_file(), reason="ac20 artifacts missing")


@need
@pytest.mark.parametrize("q,value,n", [
    ("How wide is the largest window?", 1.0, 197),
    ("What is the width of the widest window?", 1.0, 197),
    ("What is the width of the widest door?", 2.0, 1),
])
def test_width_extreme_value_and_calc(q, value, n):
    from engine.answer import answer
    r = answer(q, [IFC])
    assert r["answer"]["value"] == value and r["answer"]["unit"] == "m"
    ids = {i for c in r["citations"] for i in c.get("item_ids") or []}
    assert len(ids) == n
    calc = r["reasoning"]["calc"]
    assert calc["status"] == "complete" and not calc.get("issues")
    assert any(s["id"] in ("ifc-max", "ifc-quantity") for s in calc["steps"])
    assert all(row["source"]["field"] == "quantities.width_m" for row in calc["rows"])


@pytest.mark.skipif(not (ROOT / RASTER).is_dir(), reason="raster artifacts missing")
def test_width_extreme_raster_honest():
    from engine.answer import answer
    r = answer("How wide is the largest window?", [RASTER])
    a = r["answer"]
    assert a.get("value") is None or a.get("unit") == "m"
    assert a.get("text_md")
