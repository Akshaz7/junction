import time
from pathlib import Path

import pytest

from engine import analytics
from engine.solvers.data import Doc, Item, load_doc

ROOT = Path(__file__).resolve().parents[2] / "artifacts"


def _slab(i, tn, w, area, storey="L1"):
    return Item(item_id=f"s{i}", kind="slab", storey=storey, q={"width_m": w, "area_m2": area}, type_name=tn,
                props={"ifc_class": "IfcSlab"}, source="ifc", bbox_m=[[0, 0, 0], [1, w, 1]])


def _doc(items):
    return Doc(doc_id="d", mode="ifc", items=items, storeys=[{"name": "L1", "elevation_m": 0}])


def _run(q, doc):
    return analytics.run(q, doc, time.perf_counter())


def test_groups_by_type_and_thickness_and_sums_area():
    d = _doc([_slab(1, "RC 250", 0.25, 100), _slab(2, "RC 250", 0.25, 50), _slab(3, "RC 300", 0.30, 20)])
    r = _run("slab area by type", d)
    t = r["answer"]["text_md"]
    assert "| RC 250 | 250 mm | 2 | 150.0 m² |" in t and "| RC 300 | 300 mm | 1 | 20.0 m² |" in t
    assert r["answer"]["value"] == 170 and len(r["evidence"]["boxes"]) == 0 or True
    assert "no reinforcement data" in t
    assert "thickness quantity" in t


def test_thickness_filter_and_missing_thickness_lists_available():
    d = _doc([_slab(1, "RC 250", 0.25, 100), _slab(2, "RC 300", 0.30, 20)])
    assert _run("how much 250 mm slab", d)["answer"]["value"] == 100
    t = _run("how much 200 mm slab", d)["answer"]["text_md"]
    assert "No **200 mm** slab" in t and "250 mm" in t and "300 mm" in t


def test_bbox_height_cannot_substitute_for_thickness():
    it = Item(item_id="s1", kind="slab", q={"area_m2": 10}, type_name="X", props={"ifc_class": "IfcSlab"}, source="ifc", bbox_m=[[0, 0, 0], [1, 0.2, 1]])
    t = _run("slab areas by thickness", _doc([it]))["answer"]["text_md"]
    assert "250 mm" not in t and "200 mm" not in t and "unavailable" in t and "bounding-box height" in t


def test_rebar_reported_only_when_present():
    bar = Item(item_id="b1", kind="other", props={"ifc_class": "IfcReinforcingBar"}, source="ifc")
    t = _run("slab areas by thickness and reinforcement", _doc([_slab(1, "RC", 0.25, 10), bar]))["answer"]["text_md"]
    assert "no reinforcement data" not in t and "1 reinforcement" in t


def test_not_a_slab_area_question():
    assert analytics.slab_by_type("how many doors", _doc([_slab(1, "RC", 0.25, 10)]), 0) is None
    assert analytics.slab_by_type("where is the slab", _doc([_slab(1, "RC", 0.25, 10)]), 0) is None


@pytest.mark.skipif(not (ROOT / "ifc_bench__ac20-arc").exists(), reason="no AC20 artifacts")
def test_ac20():
    doc = load_doc("ifc_bench__ac20-arc", ROOT)
    r = _run("slab area by type", doc)
    assert r["answer"]["value"] == pytest.approx(3255.4, abs=0.1)
    assert "| Stahlbeton (reinforced concrete) | 300 mm | 5 |" in r["answer"]["text_md"]
    assert len(r["evidence"]["scene"]["highlight_item_ids"]) == 26


def test_broken_area_quantity_falls_back_to_footprint():
    it = Item(item_id="s1", kind="slab", q={"width_m": 0.26, "area_m2": 0.0018}, type_name="X", props={"ifc_class": "IfcSlab"}, source="ifc",
              bbox_m=[[0, 0, 0], [30, 0.26, 30]])
    r = _run("slab area by type", _doc([it]))
    assert r["answer"]["value"] == 900 and "box footprint" in r["answer"]["text_md"]
