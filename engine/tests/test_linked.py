from pathlib import Path

import pytest

from engine import linked

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"
pytestmark = pytest.mark.skipif(not (ROOT / DOC).exists(), reason="artifact missing")


def test_door_by_item_id_returns_storey_type_properties():
    r = linked.lookup(DOC, "3qloCPnZDEQBom1ZjBlwJP")
    assert r["kind"] == "door" and r["storey"] == "Keller"
    assert r["type"] and r["properties"].get("material")
    assert r["quantities"]["width_m"] == 1.0
    assert r["tag"]


def test_tag_and_name_resolve_same_item():
    a = linked.lookup(DOC, "3qloCPnZDEQBom1ZjBlwJP")
    b = linked.lookup(DOC, a["tag"])
    c = linked.lookup(DOC, "Tür-014")
    assert a["item_id"] == b["item_id"] == c["item_id"]


def test_same_type_lists_other_places():
    r = linked.lookup(DOC, "Tür-014")
    assert r["same_type"]["count"] >= 2 and r["same_type"]["items"]


def test_unknown_ref_is_none():
    assert linked.lookup(DOC, "no-such-thing") is None
    assert linked.lookup("nope", "x") is None
    assert linked.lookup(DOC, "") is None
