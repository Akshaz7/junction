"""E-39 regressions. Every drawing here is generated for demo, never a held-out drawing."""
import json

import ezdxf
import pytest

from engine.solvers import solve
from pipeline.dxf_planmap import assign_room_texts, fixture_kind, process, room_texts


def rectangle(ms, layer, x, y, w, h):
    return ms.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                             close=True, dxfattribs={"layer": layer})


def convert(tmp_path, doc):
    doc_id = "generated-for-demo"
    art = tmp_path / doc_id
    art.mkdir()
    (art / "pages.json").write_text(json.dumps({"source": "dxf", "pages": [{"w": 3000, "h": 3000}]}))
    path = art / "input.dxf"
    doc.saveas(path)
    process(doc_id, art, path)
    return doc_id, json.loads((art / "planmap-1.json").read_text())


@pytest.mark.parametrize("name,kind", [("FIXTURE_BATHTUB", "bathtub"), ("sanitary-washbasin", "sink"),
                                       ("WC", "toilet"), ("fixture_douche", "shower"),
                                       ("FIXTURE", None), ("toilet_sink", None)])
def test_explicit_fixture_semantics(name, kind):
    assert fixture_kind(name) == kind


def test_text_placement_ignores_unused_alignment_point():
    ms = ezdxf.new().modelspace()
    ms.add_text("Zimmer", dxfattribs={"layer": "ROOM_TEXT", "insert": (4, 5), "align_point": (0, 0)})
    ms.add_text("Wohnen", dxfattribs={"layer": "ROOM_TEXT", "insert": (0, 0),
                                    "align_point": (7, 8), "halign": 1})
    ms.add_mtext("Schlafzimmer", dxfattribs={"layer": "ROOM_TEXT", "insert": (9, 10)})
    assert room_texts(ms) == [("Zimmer", 4, 5), ("Wohnen", 7, 8), ("Schlafzimmer", 9, 10)]


def test_boundary_and_nested_room_labels():
    outer = [(0, 0), (20, 0), (20, 20), (0, 20)]
    inner = [(2, 2), (8, 2), (8, 8), (2, 8)]
    assigned = assign_room_texts([outer, inner], [("Zimmer", 2, 5), ("App. A", 4, 4), ("Wohnen", 15, 15)])
    assert assigned == {0: [("Wohnen", 15, 15)], 1: [("Zimmer", 2, 5)]}


def test_generated_room_labels_and_square_mm_area(tmp_path):
    doc = ezdxf.new()
    doc.units = 4  # millimetres
    ms = doc.modelspace()
    rectangle(ms, "ROOM_OUTLINE", 1000, 1000, 4000, 3000)
    ms.add_text("Zimmer", dxfattribs={"layer": "ROOM_TEXT", "insert": (2000, 2000), "align_point": (0, 0)})
    ms.add_text("1.01", dxfattribs={"layer": "ROOM_TEXT", "insert": (2000, 1800)})
    doc_id, pm = convert(tmp_path, doc)
    room = next(i for i in pm["items"] if i["kind"] == "room")
    assert room["label"] == "Zimmer"
    assert room["props"]["area_m2_geom"] == 12
    count = solve("How many rooms labelled 'Zimmer' are there?", doc_id, root=tmp_path)
    area = solve("What is the net floor area of room 1.01 ('Zimmer') in m²?", doc_id, root=tmp_path)
    assert count["answer"]["value"] == 1
    assert area["answer"]["value"] == 12
    assert area["cost"]["usd_total"] == 0


@pytest.mark.parametrize("block_name,question", [("bathtub", "How many bathtubs are drawn on this floor plan?"),
                                                ("WC", "How many toilets are drawn on this floor plan?")])
def test_nested_fixture_block_counts_once(tmp_path, block_name, question):
    doc = ezdxf.new()
    block = doc.blocks.new(block_name)
    rectangle(block, "0", 0, 0, 2, 1)
    rectangle(block, "0", .1, .1, 1.8, .8)
    doc.modelspace().add_blockref(block_name, (3, 5), dxfattribs={"layer": "FIXTURE"})
    doc_id, pm = convert(tmp_path, doc)
    fixtures = [i for i in pm["items"] if i["props"].get("role") == "fixture"]
    assert len(fixtures) == 1
    answer = solve(question, doc_id, root=tmp_path)
    assert answer["answer"]["value"] == 1
    assert len(answer["evidence"]["boxes"]) == 1
    assert answer["cost"]["usd_total"] == 0


def test_unknown_fixture_is_preserved_and_not_reported_as_zero(tmp_path):
    doc = ezdxf.new()
    doc.modelspace().add_ellipse((3, 3), major_axis=(1, 0), ratio=.5, dxfattribs={"layer": "FIXTURE"})
    doc_id, pm = convert(tmp_path, doc)
    assert pm["items"][0]["props"]["classification"] == "unknown"
    answer = solve("How many toilets are drawn on this floor plan?", doc_id, root=tmp_path)
    assert answer["answer"]["abstained"]
    assert answer["answer"]["value"] is None
    assert "unclassified fixture" in answer["answer"]["text_md"]


def test_room_label_count_survives_labels_outside_polygons(tmp_path):
    doc = ezdxf.new()
    ms = doc.modelspace()
    rectangle(ms, "ROOM_OUTLINE", 0, 0, 4, 4)
    rectangle(ms, "ROOM_OUTLINE", 5, 0, 4, 4)
    # Label positions need not be contained by their room's footprint.
    for x, y in [(2, 2), (7, 5)]:
        ms.add_text("Zimmer", dxfattribs={"layer": "ROOM_TEXT", "insert": (x, y)})
    ms.add_text("Zimmer", dxfattribs={"layer": "LEGEND", "insert": (15, 5)})
    doc_id, _ = convert(tmp_path, doc)
    result = solve("How many rooms labelled 'Zimmer' are there on this floor?", doc_id, root=tmp_path)
    assert result["answer"]["value"] == 2
    assert len(result["evidence"]["boxes"]) == 2
    assert all(b["item_id"].startswith("text-") for b in result["evidence"]["boxes"])
    assert any("ROOM_TEXT" in s["detail"] for s in result["trace"])
