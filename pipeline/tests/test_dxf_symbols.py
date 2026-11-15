"""Generated for demo: synthetic symbols, never held-out drawings."""
import math
from collections import Counter

import ezdxf
import numpy as np
import pytest

from pipeline.dxf_symbols import (VectorShape, classify_fixture_shapes, extract_fixtures,
                                  extract_openings, fixture_kind)


def rect(ms, x, y, w, h, layer="FIXTURE", repeat=False):
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return ms.add_lwpolyline(pts + pts[:1] if repeat else pts, close=not repeat, dxfattribs={"layer": layer})


def bowl(ms, x, y, rx, ry, layer="FIXTURE", drain=False):
    ms.add_ellipse((x, y), (rx, 0) if rx >= ry else (0, ry), ratio=min(rx, ry) / max(rx, ry),
                   dxfattribs={"layer": layer})
    if drain:
        ms.add_circle((x, y), .025, dxfattribs={"layer": layer})


def tub(ms, x, y, layer="FIXTURE", vertices_per_corner=6):
    rect(ms, x, y, 1.8, .75, layer)
    pts = []
    for cx, cy, start in [(x + 1.65, y + .6, 0), (x + .15, y + .6, 90),
                          (x + .15, y + .15, 180), (x + 1.65, y + .15, 270)]:
        for angle in np.linspace(start, start + 90, vertices_per_corner):
            a = math.radians(angle)
            pts.append((cx + .09 * math.cos(a), cy + .09 * math.sin(a)))
    ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    ms.add_circle((x + 1.6, y + .375), .025, dxfattribs={"layer": layer})


def sanitary_set(ms, layer="FIXTURE"):
    rect(ms, 0, 0, .6, .8, layer)
    bowl(ms, .3, .4, .20, .30, layer, drain=True)
    rect(ms, 2, 0, .6, .8, layer)
    bowl(ms, 2.24, .4, .20, .30, layer)
    tub(ms, 4, 0, layer)
    rect(ms, 7, 0, .8, .8, layer)
    rect(ms, 7.05, .05, .7, .7, layer)
    ms.add_circle((7.4, .4), .025, dxfattribs={"layer": layer})


def counts(items):
    return Counter(i["kind"] for i in items if i["kind"] != "other")


@pytest.mark.parametrize("layer", ["FIXTURE", "A-FIXT", "Sanitär", "sanitaire", "Saniteettikalusteet", "PLUMBING"])
def test_complete_anatomy_is_one_fixture_per_symbol(layer):
    ms = ezdxf.new().modelspace()
    sanitary_set(ms, layer)
    items = extract_fixtures(ms)
    assert counts(items) == {"sink": 1, "toilet": 1, "bathtub": 1, "shower": 1}
    assert all(i["conf"] == .5 for i in items)
    assert all(i["props"]["classification"] == "geometry" for i in items if i["kind"] != "other")


@pytest.mark.parametrize("scale,angle", [(1000, 37), (.001, 91), (1 / .3048, -128), (1, 180)])
def test_geometry_uses_ratios_after_unit_changes_and_block_rotation(scale, angle):
    doc = ezdxf.new()
    block = doc.blocks.new("anonymous-symbols")
    sanitary_set(block, "0")
    doc.modelspace().add_blockref(block.name, (12, -45), dxfattribs={"layer": "FIXTURE", "rotation": angle,
                                                                 "xscale": scale, "yscale": scale})
    assert counts(extract_fixtures(doc.modelspace())) == {"sink": 1, "toilet": 1, "bathtub": 1, "shower": 1}


@pytest.mark.parametrize("samples", [3, 5, 12, 24])
def test_bathtub_does_not_require_dataset_vertex_count(samples):
    ms = ezdxf.new().modelspace()
    tub(ms, 0, 0, vertices_per_corner=samples)
    assert counts(extract_fixtures(ms)) == {"bathtub": 1}


def test_kitchen_hob_and_cupboard_are_not_sinks():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, 2, .6)
    for x, y in [(.2, .2), (.45, .2), (.2, .45), (.45, .45)]:
        ms.add_circle((x, y), .08, dxfattribs={"layer": "FIXTURE"})
    rect(ms, 3, 0, .6, 1.8)
    items = extract_fixtures(ms)
    assert counts(items) == {}
    assert {i["props"]["classification"] for i in items} == {"kitchen_hob", "empty_outline"}
    assert all(i["props"]["role"] != "fixture" for i in items)


def test_smallest_container_prevents_counter_from_owning_basin():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, 3, 1)
    rect(ms, .1, .1, .6, .8)
    bowl(ms, .4, .5, .2, .3, drain=True)
    items = extract_fixtures(ms)
    assert counts(items) == {"sink": 1}
    sink = next(i for i in items if i["kind"] == "sink")
    assert min(p[0] for p in sink["polygon"]) == .1


def test_explicit_fixture_layer_does_not_count_its_nested_curves_again():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, .8, .8, "SHOWER")
    rect(ms, .05, .05, .7, .7, "SHOWER")
    ms.add_circle((.4, .4), .025, dxfattribs={"layer": "SHOWER"})
    items = extract_fixtures(ms)
    assert counts(items) == {"shower": 1}
    assert items[0]["conf"] == 1


@pytest.mark.parametrize("offset,drain", [(0, False), (.1, True)])
def test_ambiguous_bowl_stays_unknown(offset, drain):
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, .6, .8)
    bowl(ms, .3 - offset, .4, .15, .3, drain=drain)
    items = extract_fixtures(ms)
    assert counts(items) == {}
    assert len(items) == 1
    assert items[0]["props"]["classification"] == "unknown"
    assert items[0]["props"]["needs_review"]


def test_small_circle_outside_bowl_is_not_a_drain():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, .6, .8)
    bowl(ms, .3, .4, .15, .2)
    ms.add_circle((.3, .7), .02, dxfattribs={"layer": "FIXTURE"})
    assert counts(extract_fixtures(ms)) == {}


def test_unbounded_curves_are_retained_as_uncertain():
    ms = ezdxf.new().modelspace()
    bowl(ms, 0, 0, .3, .2)
    items = extract_fixtures(ms)
    assert len(items) == 1
    assert items[0]["kind"] == "other"
    assert items[0]["props"]["role"] == "fixture"
    assert items[0]["conf"] == .5


def test_crossed_box_without_drain_is_not_assumed_to_be_shower():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, 1, 1)
    for p in [[(0, 0), (1, 1)], [(0, 1), (1, 0)]]:
        ms.add_lwpolyline(p, dxfattribs={"layer": "FIXTURE"})
    item, = extract_fixtures(ms)
    assert item["kind"] == "other"
    assert item["props"]["classification"] == "unknown"


@pytest.mark.parametrize("layer,kind", [("A-DOOR", "door"), ("Türen", "door"), ("Dörrar", "door"),
                                       ("OVET", "door"), ("Fenster", "window"), ("Fönster", "window"),
                                       ("Ikkunat", "window")])
def test_closed_frame_and_swing_arcs_are_one_opening(layer, kind):
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, 1.8, .1, layer)
    for x in (0, 1.8):
        ms.add_arc((x, .1), .9, 0, 90, dxfattribs={"layer": layer})
        ms.add_line((x, .1), (x, 1), dxfattribs={"layer": layer})
    ms.add_lwpolyline([(3, 0), (4, 0)], dxfattribs={"layer": layer})
    assert len(extract_openings(ms, kind)) == 1


def test_fillet_arcs_and_open_five_point_paths_are_not_doors():
    ms = ezdxf.new().modelspace()
    ms.add_arc((0, 0), .2, 0, 90, dxfattribs={"layer": "DOOR"})
    ms.add_lwpolyline([(0, 0), (1, 0), (1, .1), (.5, .2), (0, .1)], dxfattribs={"layer": "DOOR"})
    assert extract_openings(ms, "door") == []


def test_repeated_endpoint_is_valid_door_frame():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, .9, .1, "DOOR", repeat=True)
    assert len(extract_openings(ms, "door")) == 1


@pytest.mark.parametrize("kind", ["door", "window"])
def test_common_block_frame_and_nested_outlines_are_one_opening(kind):
    doc = ezdxf.new()
    block = doc.blocks.new(kind + "-double")
    rect(block, 0, 0, 1.8, .1, "0")
    rect(block, .01, .01, .88, .08, "0")
    rect(block, .91, .01, .88, .08, "0")
    doc.modelspace().add_blockref(block.name, (1, 2), dxfattribs={"rotation": 37})
    assert len(extract_openings(doc.modelspace(), kind)) == 1


def test_distinct_source_instances_are_not_merged_by_position():
    ms = ezdxf.new().modelspace()
    rect(ms, 0, 0, .9, .1, "DOOR")
    rect(ms, 0, 0, .9, .1, "DOOR")
    rect(ms, 1, 0, .9, .1, "DOOR")
    assert len(extract_openings(ms, "door")) == 3


def test_missing_semantic_layers_are_left_for_existing_fallback():
    ms = ezdxf.new().modelspace()
    sanitary_set(ms, "0")
    rect(ms, 20, 0, .9, .1, "0")
    assert extract_fixtures(ms) == []
    assert extract_openings(ms, "door") == []


@pytest.mark.parametrize("name,kind", [("pesuallas", "sink"), ("tvättställ", "sink"), ("dusch", "shower"),
                                       ("toalett", "toilet"), ("kylpyamme", "bathtub"), ("badkar", "bathtub")])
def test_multilingual_fixture_semantics(name, kind):
    assert fixture_kind(name) == kind


def test_reader_neutral_hook_does_not_need_dxf_or_pdf_reader():
    frame = VectorShape([(0, 0), (1, 0), (1, 1), (0, 1)], closed=True)
    t = np.linspace(0, 2 * math.pi, 65)
    drain = VectorShape([(float(.5 + .03 * math.cos(a)), float(.5 + .03 * math.sin(a))) for a in t],
                        closed=True, primitive="circle", center=(.5, .5), radius=.03)
    item, = classify_fixture_shapes([frame, drain])
    assert item["kind"] == "shower"


def test_inferred_fixture_answer_has_proof_and_estimate_card(tmp_path):
    import json
    from pipeline.dxf_planmap import process
    from engine.solvers import solve
    from engine.reasoning import attach

    doc = ezdxf.new()
    doc.units = 6
    ms = doc.modelspace()
    rect(ms, 0, 0, .6, .8)
    bowl(ms, .3, .4, .20, .30, drain=True)
    art = tmp_path / "generated-for-demo"
    art.mkdir()
    (art / "pages.json").write_text(json.dumps({"source": "dxf", "pages": [{"w": 3000, "h": 3000}]}))
    src = art / "source.dxf"
    doc.saveas(src)
    process(art.name, art, src)
    result = attach(solve("How many sinks are drawn?", art.name, root=tmp_path), "How many sinks are drawn?", tmp_path)
    assert result["answer"]["value"] == 1
    assert result["answer"]["confidence"] == .5
    assert len(result["evidence"]["boxes"]) == 1
    assert result["citations"][0]["item_ids"] == ["sink-1"]
    assert result["reasoning"]["confidence"]["label"] == "Estimate"
    assert "CAD symbols" in result["reasoning"]["confidence"]["reason"]
    assert "fixture schedule" in result["reasoning"]["confidence"]["improve"]
    assert result["cost"]["usd_total"] == 0
