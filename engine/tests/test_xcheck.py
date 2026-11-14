import json

import pytest

from engine import xcheck
from engine.reasoning_parts import confidence, margin
from engine.solvers.data import Doc, Item
from engine.xcheck_geometry import floor_net_area, mesh_quantity, skeleton_length


def room(iid="r", label=100, *, fill=None):
    return Item(iid, "room", source="dxf", q={"area_m2": label},
                polygon_px=[[0, 0], [100, 0], [100, 100], [0, 100]],
                props={"area_m2_label": label, "area_px": fill})


def context(doc, value=100, unit="m2", **kw):
    c = dict(root=".", doc=doc, res={"doc_ids": [doc.doc_id]}, value=value, unit=unit,
             ans={"value": value, "text_md": f"**{value} {unit}**"},
             cites=[{"doc_id": doc.doc_id, "n": 1, "item_ids": [i.item_id for i in doc.items if i.kind == "room"]}],
             steps=[], trace=[], checked=None, models_used=False, is_ifc=doc.mode == "ifc", from_cad=True,
             route="index", sc=doc.scale)
    c.update(kw)
    return c


@pytest.mark.parametrize(("a", "b", "diff", "ok"), [(0, 0, 0, True), (0, 1, 100, False), (100, 95, 5, True), (100, 94, 6, False)])
def test_symmetric_difference_and_zero(a, b, diff, ok):
    c = xcheck.compare("test", a, b, "m", [])
    assert c["diff_pct"] == pytest.approx(diff) and c["agrees"] is ok
    assert c["diff_pct"] == xcheck.compare("test", b, a, "m", [])["diff_pct"]


@pytest.mark.parametrize("bad", [None, True, -1, float("nan"), float("inf"), 10**1000])
def test_invalid_numbers_rejected(bad):
    assert xcheck.compare("test", bad, 1, "m", []) is None


def test_room_outline_and_label_with_sources():
    r = room()
    doc = Doc("d", "planmap", [r], scale={"method": "dxf-units", "m_per_px": .1})
    c = xcheck.room_checks(doc, r)[0]
    assert c["independent"] and c["value"] == pytest.approx(100)
    assert c["sources"][0]["item_id"] == "r"


def test_imperial_printed_label_converts_explicitly():
    r = room(label=None)
    text = Item("t", "text", label="1  1076.391 ft²", bbox_px=[40, 40, 60, 60])
    doc = Doc("d", "planmap", [r, text], scale={"method": "dimensions", "m_per_px": .1})
    c = xcheck.room_checks(doc, r)[0]
    assert c["agrees"] and c["primary_value"] == pytest.approx(100, abs=.001)
    assert "0.3048" in c["sources"][1]["unit_conversion"]


def test_ambiguous_labels_are_not_selected():
    r = room(label=None)
    labels = [Item(str(i), "text", label=f"{i} m²", bbox_px=[40, 40, 50, 50]) for i in (1, 2)]
    doc = Doc("d", "planmap", [r, *labels], scale={"m_per_px": .1})
    assert xcheck.room_checks(doc, r) == []


def test_scale_derived_from_labels_and_fill_are_correlated():
    r = room(fill=10000)
    doc = Doc("d", "planmap", [r], scale={"method": "printed-areas", "m_per_px": .1})
    assert all(not c["independent"] for c in xcheck.room_checks(doc, r))


def test_calc_reconciles_full_rows_and_result():
    doc = Doc("d", "planmap", [room()], scale={"method": "dxf-units", "m_per_px": .1})
    ctx = context(doc)
    calc = margin.run(ctx)["calc"]
    assert sum(r["values"]["m2"] for r in calc["rows"]) == calc["result"]["value"]
    assert calc["checks"][0]["agrees"] and ctx["checked"] is True


def test_partial_pair_does_not_check_complete_total():
    r1, r2 = room("r1"), room("r2", label=20)
    r2.polygon_px = None
    doc = Doc("d", "planmap", [r1, r2], scale={"method": "dxf-units", "m_per_px": .1})
    calc = margin.run(context(doc, value=120))["calc"]
    assert calc["checks"] == [] and len(calc["item_checks"]) == 1
    assert calc["unavailable"]


def test_disagreement_downgrades_exact_source_and_margin():
    doc = Doc("d", "planmap", [room(label=60)], scale={"method": "dxf-units", "m_per_px": .1})
    ctx = context(doc, value=60)
    out = margin.run(ctx)
    assert ctx["checked"] is False and ctx["quantified_exact"] is False
    assert out["margin"]["value"] is None
    assert confidence.run(ctx)["label"] == "Estimate"


def test_real_recount_not_fake_and_headline_policy_is_explicit():
    doc = Doc("d", "planmap", [])
    ctx = context(doc, value=6, unit="count", trace=[{"step": "recount", "model": "real", "detail": "plan map 4, drawing re-read 6"}])
    calc = xcheck.run(ctx, [], 0, None)
    assert calc["checks"][0]["primary_value"] == 6 and calc["checks"][0]["value"] == 4
    assert ctx["checked"] is False
    ctx["trace"][0]["model"] = "fake"
    assert xcheck.run(ctx, [], 0, None)["checks"] == []


def test_no_unmatched_agreement_percentage(tmp_path, monkeypatch):
    p = tmp_path / "agreement.json"
    p.write_text(json.dumps({"pairs": [{"method": "a", "cohort": "scan", "unit": "m2", "n": 20, "within_1pct": 9, "within_5pct": 12}]}))
    monkeypatch.setattr(xcheck, "REPORT", p)
    c = {"method": "a", "unit": "m2"}
    assert xcheck.calibration(c, "scan")["pct"] == 60
    assert xcheck.calibration(c, "ifc") is None


def test_net_floor_subtracts_union_not_sum_of_overlapping_walls():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    walls = [[(0, 0), (2, 0), (2, 10), (0, 10)], [(0, 0), (10, 0), (10, 2), (0, 2)]]
    assert floor_net_area(outer, walls) == pytest.approx(64)


def test_skeleton_diagonal_and_orthogonal_bridges():
    assert skeleton_length([[1, 0], [0, 1]], .1) == pytest.approx(2**.5 * .1)
    assert skeleton_length([[1, 1], [0, 1]], .1) == pytest.approx(.2)
    assert skeleton_length([[1]], 0) is None


def test_mesh_footprint_is_not_bounding_rectangle(tmp_path):
    import trimesh
    # Two separated boxes form an L; bounding box would be 16 m², union is 7.
    a = trimesh.creation.box(extents=[4, 2, 1]); a.apply_translation([2, 1, .5])
    b = trimesh.creation.box(extents=[1, 2, 3]); b.apply_translation([.5, 1, 2.5])
    scene = trimesh.Scene(); scene.add_geometry(a, node_name="room_a"); scene.add_geometry(b, node_name="room_b")
    path = tmp_path / "scene.glb"; path.write_bytes(scene.export(file_type="glb"))
    assert mesh_quantity(path, "room", "m2", "room") == pytest.approx(7)
    assert mesh_quantity(path, "room", "m3", "room") == pytest.approx(14)
    assert mesh_quantity(path, "room", "m", "room") is None


def test_missing_geometry_never_raises(tmp_path):
    assert mesh_quantity(tmp_path / "absent.glb", "room", "m2", "room") is None
