"""Synthetic inputs generated for demo/testing; no drawing-specific constants in code."""
import json
import time

import pytest
from PIL import Image, ImageDraw

from engine.scales import (
    apply_item_scales,
    region_scale,
    scale_anchors,
    scale_description,
)
from engine.solvers.data import Item, load_doc
from pipeline.scale_regions import annotate_planmap, dxf_regions


def word(text, x, y, w=130):
    return {"text": text, "bbox_px": [x, y, x+w, y+16]}


def sheet():
    return {"doc_id": "test__views", "page": 1, "image": {"w": 1200, "h": 800},
            "scale": {"m_per_px": .01, "method": "door-prior", "confidence": .3}, "items": []}


def mixed(dpi=254):
    return annotate_planmap(sheet(), [word("Main plan 1:100", 30, 710, 200), word("Section A 1:20", 850, 450, 200)],
                            dpi=dpi, frames=[[0, 0, 800, 800], [820, 0, 1200, 600]])


def room(i="r", b=None, **kw):
    b = b or [850, 100, 950, 200]
    return Item(item_id=i, kind="room", bbox_px=b,
                polygon_px=[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], **kw)


def test_metric_regions_keep_main_and_title_evidence():
    pm = mixed()
    assert len(pm["regions"]) == 2
    assert pm["scale"]["ratio"] == 100
    sc, r = region_scale(pm, [850, 100, 950, 200])
    assert sc["m_per_px"] == pytest.approx(.002)
    assert scale_description(sc, r["title"]) == "detail 'Section A' at 1:20"
    assert sc["boxes"] == [[850, 450, 1050, 466]]


def test_area_and_width_use_local_scale_and_keep_labels():
    it = room(q={"area_m2": 1, "width_m": 1}, props={"area_m2": 1})
    printed = room("label", q={"area_m2": 7}, props={"area_m2_label": 7})
    native = room("cad", q={"area_m2": 9}, source="dxf")
    apply_item_scales([it, printed, native], mixed())
    assert it.q == {"area_m2": .04, "width_m": .2}
    assert it.props["area_m2"] == .04
    assert printed.q["area_m2"] == 7
    assert native.q["area_m2"] == 9


def test_boxes_only_room_gets_local_area():
    it = room()
    apply_item_scales([it], mixed())
    assert it.q["area_m2"] == .04


@pytest.mark.parametrize("bbox", [[780, 100, 850, 200], [805, 100, 815, 200], None])
def test_crossing_and_unassigned_do_not_inherit_scale(bbox):
    sc, r = region_scale(mixed(), bbox)
    assert sc["m_per_px"] is None and r is None


def test_unresolved_mixed_ratios_never_select_first():
    pm = annotate_planmap(sheet(), [word("1:100", 20, 700), word("1:20", 850, 450)], dpi=254)
    assert pm["scale"]["m_per_px"] is None
    it = room(q={"area_m2": 1, "width_m": 1}, props={"area_m2": 1})
    apply_item_scales([it], pm)
    assert not it.q and "area_m2" not in it.props


def test_missing_dpi_retains_unmeasured_detail():
    pm = mixed(dpi=None)
    assert all(r["scale"]["m_per_px"] is None for r in pm["regions"])


@pytest.mark.parametrize("label,ratio", [("M 1 : 37.5", 37.5), ("Mittakaava 1:5", 5), ("Maßstab 1:250", 250),
                                        ("Skala 1:10000", 10000), ('Section 1/4" = 1\'-0"', 48),
                                        ('1 1/2" = 1\'-0"', 8), ('1" = 20\'-0"', 240)])
def test_ratios_languages_and_imperial(label, ratio):
    assert scale_anchors([word(label, 0, 0, 400)])[0]["ratio"] == ratio


def test_date_screw_and_dimension_fractions_are_not_scales():
    assert not scale_anchors([word('1/4/2026 1/2" screws', 0, 0, 400)])


def test_split_words_spatially_near_only():
    ws = [word("M", 10, 10, 15), word("1", 30, 10, 10), word(":", 45, 10, 10), word("50", 60, 10, 20)]
    assert scale_anchors(ws)[0]["ratio"] == 50
    ws[-1]["bbox_px"] = [900, 10, 920, 26]
    assert not scale_anchors(ws)


def test_gutters_and_frames_detect_separate_regions():
    im = Image.new("L", (1200, 800), "white")
    draw = ImageDraw.Draw(im)
    draw.rectangle([20, 20, 750, 780], outline="black", width=3)
    draw.rectangle([850, 20, 1180, 580], outline="black", width=3)
    pm = annotate_planmap(sheet(), [word("1:100", 40, 710), word("1:20", 900, 500)], im, dpi=254)
    assert len(pm["regions"]) == 2
    assert region_scale(pm, [900, 100, 1000, 200])[0]["ratio"] == 20


def test_nested_detail_wins_and_overlapping_item_is_unknown():
    pm = mixed()
    pm["regions"].sort(key=lambda r: r["scale"]["ratio"], reverse=True)
    pm["regions"][0]["bbox"] = [0, 0, 1200, 800]
    assert region_scale(pm, [850, 100, 950, 200])[0]["ratio"] == 20
    assert region_scale(pm, [700, 100, 950, 200])[0]["m_per_px"] is None


def test_intersecting_peer_regions_cannot_choose_a_scale_by_size():
    pm = mixed()
    pm["regions"].sort(key=lambda r: r["scale"]["ratio"], reverse=True)
    pm["regions"][0]["bbox"] = [0, 0, 1000, 800]
    assert region_scale(pm, [850, 100, 950, 200])[0]["m_per_px"] is None
    pm["regions"][0]["bbox"] = list(pm["regions"][1]["bbox"])
    assert region_scale(pm, [850, 100, 950, 200])[0]["m_per_px"] is None


def test_unknown_view_preserves_printed_area_but_removes_pixel_lengths():
    it = room(q={"area_m2": 7, "width_m": 1}, props={"area_m2_label": 7, "width_m": 1})
    apply_item_scales([it], mixed(dpi=None))
    assert it.q == {"area_m2": 7}
    assert "width_m" not in it.props


def test_end_to_end_detail_area_and_measured_card(tmp_path):
    pm = mixed()
    d = tmp_path / pm["doc_id"]
    d.mkdir()
    pm["items"] = [{"item_id": "room-001", "kind": "room", "label": "Office", "conf": .95,
                    "bbox_px": [850, 100, 1050, 300], "polygon_px": [[850, 100], [1050, 100], [1050, 300], [850, 300]],
                    "props": {"area_m2": 4}, "source": "seg"}]
    (d / "planmap-1.json").write_text(json.dumps(pm))
    doc = load_doc(pm["doc_id"], tmp_path)
    assert doc.items[0].q["area_m2"] == .16
    from engine import analytics, reasoning
    res = analytics.run("area of the office", doc, time.perf_counter())
    assert res["answer"]["value"] == .16
    assert res["citations"][0]["item_ids"] == ["room-001"]
    card = reasoning.build(res, "area of the office", tmp_path)
    assert any("Section A" in s["text"] and "1:20" in s["text"] for s in card["steps"] if s["kind"] == "measured")


def test_different_pages_use_own_regions(tmp_path):
    d = tmp_path / "test__views"
    d.mkdir()
    for page, ratio in [(1, 100), (2, 20)]:
        pm = annotate_planmap(sheet(), [word(f"1:{ratio}", 10, 700)], dpi=254)
        pm["page"] = page
        pm["items"] = [{"item_id": f"room-{page}", "kind": "room", "bbox_px": [10, 10, 110, 110], "conf": 1, "props": {"area_m2": 1}}]
        (d / f"planmap-{page}.json").write_text(json.dumps(pm))
    doc = load_doc(d.name, tmp_path)
    assert [r.q["area_m2"] for r in doc.items] == [1, .04]


def test_dxf_block_units_and_uniform_scale():
    import ezdxf
    doc = ezdxf.new()
    doc.units = 6
    b = doc.blocks.new("detail")
    b.block_record.dxf.units = 4  # mm, drawn enlarged into modelspace
    b.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
    doc.modelspace().add_blockref("detail", (0, 0), dxfattribs={"xscale": 2, "yscale": 2})
    rs = dxf_regions(doc, {"a": 10, "bx": 0, "by": 10000})
    assert rs[0]["scale"]["m_per_px"] == .00005
    doc.modelspace().query("INSERT")[0].dxf.yscale = 1
    assert dxf_regions(doc, {"a": 10, "bx": 0, "by": 10000})[0]["scale"]["m_per_px"] is None


def test_dxf_paper_viewports_use_model_units():
    import ezdxf
    doc = ezdxf.new()
    doc.units = 6
    layout = doc.layout()
    layout.add_viewport(center=(100, 100), size=(100, 100), view_center_point=(0, 0), view_height=10)
    layout.add_viewport(center=(300, 100), size=(100, 100), view_center_point=(0, 0), view_height=2)
    rs = dxf_regions(doc, {"a": 10, "bx": 0, "by": 3000}, layout)
    assert [r["scale"]["m_per_px"] for r in rs] == [.01, .002]
    assert [r["scale"]["ratio"] for r in rs] == [100, 20]


def test_dpi_survives_resize_and_saved_page(tmp_path):
    from pipeline.pages import cap_raster, save_page
    im = Image.new("RGB", (1600, 800), "white")
    im.info["dpi"] = (400, 400)
    im = cap_raster(im, side=800)
    assert im.info["dpi"] == (200, 200)
    save_page(im, tmp_path, 1)
    with Image.open(tmp_path / "page-1.png") as loaded:
        assert loaded.info["dpi"][0] == pytest.approx(200, abs=.02)


def test_jpeg_draft_resize_keeps_physical_dpi(tmp_path):
    from pipeline.pages import cap_raster
    path = tmp_path / "scan.jpg"
    Image.new("RGB", (4000, 2000), "white").save(path, dpi=(400, 400))
    with Image.open(path) as im:
        small = cap_raster(im, side=1000)
        assert small.info["dpi"][0] == pytest.approx(400 * small.width / 4000)


def test_missing_scale_area_is_unavailable_instead_of_zero():
    from engine import analytics
    from engine.solvers.data import Doc
    it = room(label="Office", conf=1)
    pm = mixed(dpi=None)
    apply_item_scales([it], pm)
    doc = Doc("test__views", "planmap", [it], scale=pm["scale"])
    res = analytics.named_rooms("area of the office", doc, time.perf_counter())
    assert res["answer"]["value"] is None
    assert "Area unavailable" in res["answer"]["text_md"]


def test_baseboard_uses_each_view_scale():
    from engine import analytics
    from engine.solvers.data import Doc
    pm = mixed()
    main = room("main", [100, 100, 300, 300], label="Office", conf=1)
    detail = room("detail", [850, 100, 1050, 300], label="Office", conf=1)
    apply_item_scales([main, detail], pm)
    doc = Doc("test__views", "planmap", [main, detail], scale=pm["scale"])
    res = analytics.baseboard("total baseboard for all rooms", doc, time.perf_counter())
    assert res["answer"]["value"] == 9.6  # 800px * .01 plus 800px * .002


def test_conflicting_scales_on_one_line_are_retained_as_unknown():
    ws = [word('1:100 or 1:20', 10, 10, 300)]
    assert len(scale_anchors(ws)) == 2
    assert annotate_planmap(sheet(), ws, dpi=254)["scale"]["m_per_px"] is None


def test_unknown_dxf_units_do_not_default_to_metres(tmp_path):
    import json

    import ezdxf

    from pipeline.dxf_planmap import process
    doc = ezdxf.new()
    doc.units = 0
    doc.modelspace().add_lwpolyline([(0, 0), (4, 0), (4, 3), (0, 3)], close=True)
    p = tmp_path / "unitless.dxf"
    doc.saveas(p)
    (tmp_path / "pages.json").write_text(json.dumps({"source": "dxf", "pages": [{"w": 800, "h": 600}]}))
    process("test__unitless", tmp_path, p)   # F-ROBUST: ingest continues, but nothing is measured
    scale = json.loads((tmp_path / "planmap-1.json").read_text())["scale"]
    assert scale["m_per_px"] is None and scale["method"] == "none"


def test_printed_area_wins_even_when_stale_geometry_is_present(tmp_path):
    d = tmp_path / "test__printed"
    d.mkdir()
    pm = mixed()
    pm["items"] = [{"item_id": "room-001", "kind": "room", "bbox_px": [850, 100, 1050, 300], "conf": 1,
                    "props": {"area_m2": 4, "area_m2_label": 7}}]
    (d / "planmap-1.json").write_text(json.dumps(pm))
    assert load_doc(d.name, tmp_path).items[0].q["area_m2"] == 7


def test_single_unverified_ratio_keeps_existing_scale_without_claiming_ratio():
    pm = annotate_planmap(sheet(), [word("Plan 1:100", 20, 700)])
    assert pm["scale"]["m_per_px"] == .01
    assert "ratio" not in pm["scale"]
    assert pm["scale"]["unverified_printed_ratio"] == 100


def test_native_dxf_scale_not_replaced_by_uncalibrated_text(tmp_path):
    from pipeline.scale_regions import annotate_cached
    pm = sheet()
    pm["items"] = [{"source": "dxf"}]
    (tmp_path / "scale-ocr-1.json").write_text(json.dumps([word("1:100", 20, 700)]))
    assert annotate_cached(pm, tmp_path) == pm


def test_local_scale_bar_calibrates_view_without_dpi():
    ws = [word("Section A 1:20", 850, 450, 200)]
    ws += [word(str(v), 850 + k*80, 500, 15) for k, v in enumerate([0, 1, 2, 3])]
    ws += [word("m", 1130, 500, 15)]
    pm = annotate_planmap(sheet(), ws, frames=[[820, 0, 1200, 600]])
    assert pm["scale"]["method"] == "scalebar"
    assert pm["scale"]["m_per_px"] == pytest.approx(1/80)


@pytest.mark.parametrize("points", [[[850, 100], [1050, 100]], [[850, 100], [850, 300]]])
def test_reader_measure_uses_local_scale_for_straight_lines(tmp_path, points):
    from engine.reader.tools import Session
    pm = mixed()
    d = tmp_path / pm["doc_id"]
    d.mkdir()
    (d / "planmap-1.json").write_text(json.dumps(pm))
    session = Session([d.name], tmp_path)
    measured = session.t_measure("d1", points=points)
    assert "length 0.400 m" in measured and "Section A" in measured and "1:20" in measured
    assert next(iter(session.ev.values())).bbox_px is not None


def test_reader_cannot_measure_across_views_or_override_local_scale(tmp_path):
    from engine.reader.tools import Session
    pm = mixed()
    d = tmp_path / pm["doc_id"]
    d.mkdir()
    (d / "planmap-1.json").write_text(json.dumps(pm))
    session = Session([d.name], tmp_path)
    assert "crosses views" in session.t_measure("d1", points=[[100, 100], [900, 100]], m_per_px=.01)
    assert "disagrees" in session.t_measure("d1", points=[[850, 100], [1050, 100]], m_per_px=.01)


def test_upload_hook_persists_regions_and_does_not_run_for_pdf(tmp_path):
    from pipeline.scale_regions import annotate_document
    pm = sheet()
    (tmp_path / "doc.json").write_text(json.dumps({"kind": "raster"}))
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    Image.new("RGB", (1200, 800), "white").save(tmp_path / "page-1.png", dpi=(254, 254))
    (tmp_path / "scale-ocr-1.json").write_text(json.dumps([word("Plan 1:100", 20, 700)]))
    annotate_document(tmp_path, 1)
    result = json.loads((tmp_path / "planmap-1.json").read_text())
    assert result["regions"][0]["scale"]["m_per_px"] == pytest.approx(.01, rel=.001)
    (tmp_path / "doc.json").write_text(json.dumps({"kind": "pdf"}))
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    annotate_document(tmp_path, 1)
    assert json.loads((tmp_path / "planmap-1.json").read_text()) == pm


def test_takeoff_geometry_uses_local_view_scale(tmp_path):
    from engine.takeoff import plan_geom
    d = tmp_path / "test__views"
    d.mkdir()
    pm = mixed()
    pm["items"] = [{"item_id": "r", "kind": "room", "bbox_px": [850, 100, 1050, 300],
                    "polygon_px": [[850, 100], [1050, 100], [1050, 300], [850, 300]]}]
    (d / "planmap-1.json").write_text(json.dumps(pm))
    assert plan_geom(d.name, tmp_path)["r"][0] == .16
