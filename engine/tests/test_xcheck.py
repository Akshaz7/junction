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


def test_one_to_five_percent_discrepancy_cannot_be_verified():
    doc = Doc("d", "planmap", [room(label=97)], scale={"method": "dxf-units", "m_per_px": .1})
    ctx = context(doc, value=97)
    out = margin.run(ctx)
    assert out["calc"]["checks"][0]["diff_pct"] == pytest.approx(3)
    assert confidence.run(ctx)["label"] == "Cross-checked"


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


def test_floor_check_rejects_missing_selected_outlines_and_partial_scope():
    r1, r2 = room("r1", 100), room("r2", 100)
    r2.polygon_px = [[100, 0], [200, 0], [200, 100], [100, 100]]
    unit = Item("u", "other", source="dxf", polygon_px=[[0, 0], [200, 0], [200, 100], [0, 100]], props={"role": "unit"})
    wall = Item("w", "wall", source="dxf", polygon_px=[[99, 0], [101, 0], [101, 100], [99, 100]])
    doc = Doc("d", "planmap", [r1, r2, unit, wall], scale={"method": "dxf-units", "m_per_px": .1})
    ctx = context(doc, value=200)
    check = xcheck.floor_check(ctx, [(doc, r1, 1), (doc, r2, 1)], {"terms": []})
    assert check["value"] == pytest.approx(198)
    assert xcheck.floor_check(ctx, [(doc, r1, 1), (doc, Item("absent", "room"), 1)], {"terms": []}) is None
    r2.polygon_px = None
    assert xcheck.floor_check(ctx, [(doc, r1, 1), (doc, r2, 1)], {"terms": []}) is None


def test_correlated_checks_do_not_propagate_old_cross_checked_label():
    doc = Doc("d", "planmap", [room()], scale={"method": "printed-areas", "m_per_px": .1})
    ctx = context(doc, checked=True)
    calc = margin.run(ctx)["calc"]
    assert calc["checks"] == [] and ctx["checked"] is None


def test_agreement_is_not_presented_as_accuracy_or_an_error_bound(tmp_path, monkeypatch):
    p = tmp_path / "agreement.json"
    p.write_text(json.dumps({"pairs": [{"method": "printed area / room outline", "cohort": "cad", "kind": "room", "unit": "m2", "n": 10, "within_1pct": 6, "within_5pct": 8}]}))
    monkeypatch.setattr(xcheck, "REPORT", p)
    monkeypatch.setattr(confidence, "CALIBRATION_PATH", tmp_path / "missing.json")
    doc = Doc("d", "planmap", [room()], scale={"method": "dxf-units", "m_per_px": .1})
    ctx = context(doc)
    result = margin.run(ctx)
    assert result["margin"]["agreement"][0]["pct"] == 80
    assert result["margin"]["value"] != 20  # disagreement frequency is not ±20 m²
    conf = confidence.run(ctx)
    assert conf["pct"] is None and conf["agreement"][0]["pct"] == 80
    assert "8 of 10" in conf["reason"] and "not answer accuracy" in conf["reason"]


def test_raster_skeleton_hook_keeps_shared_opening_deduction_explicit():
    r = Item("w", "wall")
    doc = Doc("d", "planmap", [r], scale={"m_per_px": .1})
    src = {"doc_id": "d", "page": 1, "item_id": "w", "input": "page image", "method": "independent threshold and thinning"}
    c = xcheck.raster_length_check(doc, r, .15, [[1, 1, 1]], src, openings_m=.05)
    assert c["value"] == pytest.approx(.15) and c["agrees"]
    src["input"] = "rendered vector outlines"
    assert xcheck.raster_length_check(doc, r, .2, [[1, 1, 1]], src) is None


def test_recovered_mep_arithmetic_uses_complete_sourced_pairs(tmp_path):
    pipe = Item("p", "pipe", source="ifc")
    doc = Doc("d", "ifc", [pipe])
    folder = tmp_path / "d"; folder.mkdir()
    c = xcheck.compare("IFC Qto / model axis", 5, 5, "m", [{"doc_id": "d", "item_id": "p", "quantity": "Length"}])
    (folder / "xcheck.json").write_text(json.dumps({"elements": {"p": [c]}}))
    ctx = context(doc, value=5, unit="m", root=tmp_path, cites=[{"doc_id": "d", "n": 1, "item_ids": ["p"]}])
    result = margin.run(ctx)
    assert result["calc"]["reconciled"] and result["arithmetic"][0]["terms"][0]["value"] == 5
    assert result["calc"]["checks"][0]["agrees"]
    assert "_arithmetic" not in result["calc"]


def test_duplicate_checks_for_one_item_cannot_cover_missing_second_item(tmp_path):
    a, b = Item("a", "pipe"), Item("b", "pipe")
    doc = Doc("d", "ifc", [a, b])
    folder = tmp_path / "d"; folder.mkdir()
    check = xcheck.compare("IFC Qto / model axis", 5, 5, "m", [{"doc_id": "d", "item_id": "a"}])
    (folder / "xcheck.json").write_text(json.dumps({"elements": {"a": [check, check]}}))
    ctx = context(doc, value=10, unit="m", root=tmp_path)
    calc = xcheck.run(ctx, [(doc, a, 1), (doc, b, 1)], 0, None)
    assert not calc["reconciled"] and not calc["checks"]


def test_storey_regrouping_is_not_an_independent_verification():
    a = Item("a", "room", source="ifc", storey="A", q={"area_m2": 3})
    b = Item("b", "room", source="ifc", storey="B", q={"area_m2": 7})
    doc = Doc("d", "ifc", [a, b])
    ctx = context(doc, value=10)
    calc = margin.run(ctx)["calc"]
    assert not calc["checks"] and calc["sanity_checks"][0]["independent"] is False
    assert calc["sanity_checks"][0]["value"] == 10 and ctx["checked"] is None
    assert confidence.run(ctx)["label"] == "Estimate"


def test_legacy_numeric_card_does_not_bypass_measured_confidence(tmp_path, monkeypatch):
    from engine.reasoning import attach
    monkeypatch.setattr(confidence, "CALIBRATION_PATH", tmp_path / "missing.json")
    res = {"doc_ids": ["d"], "answer": {"value": 2, "unit": "count", "text_md": "**2 items**"},
           "reasoning": {"steps": [{"kind": "found", "text": "Two symbols"}], "confidence": {"label": "Verified", "pct": 99}},
           "citations": [], "trace": []}
    attach(res, "How many?", tmp_path)
    assert res["reasoning"]["calc"]["result"]["value"] == 2
    assert res["reasoning"]["confidence"]["pct"] is None
    assert res["reasoning"]["confidence"]["label"] == "Estimate"
    assert res["reasoning"]["steps"][0]["text"] == "Two symbols"


def test_existing_structured_calc_is_preserved(tmp_path):
    card = {"calc": {"result": {"value": 2}}, "confidence": {"label": "Estimate"}}
    res = {"answer": {"value": 2, "unit": "count"}, "reasoning": card}
    assert xcheck.augment_existing(res, "Count", tmp_path)["reasoning"] is card


def test_unreadable_sources_cannot_retain_legacy_percentage(tmp_path, monkeypatch):
    import engine.reasoning
    def broken(*args):
        raise ValueError("Invalid source")
    monkeypatch.setattr(engine.reasoning, "build", broken)
    res = {"answer": {"value": 2, "unit": "count"}, "reasoning": {"confidence": {"label": "Verified", "pct": 99}}}
    xcheck.augment_existing(res, "Count", tmp_path)
    assert res["reasoning"]["confidence"]["pct"] is None
    assert res["reasoning"]["confidence"]["label"] == "Estimate"
