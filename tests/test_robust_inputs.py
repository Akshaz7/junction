"""Small generated unit fixtures; real-file coverage is scripts/robust_check.py."""
import json

import ezdxf
import numpy as np
import pytest
from PIL import Image

from pipeline import dxf_planmap, pages
from pipeline.raster_input import read_raster


def test_exif_rotation_matches_displayed_page(tmp_path):
    p = tmp_path / "phone.jpeg"
    im = Image.new("RGB", (80, 40), "white")
    im.paste("black", (0, 0, 40, 40))
    exif = Image.Exif()
    exif[274] = 6
    im.save(p, exif=exif)
    out = read_raster(p, 100)
    assert out.size == (40, 80)
    assert out.getpixel((20, 10))[0] < 10
    assert out.getpixel((20, 70))[0] > 245
    assert out.getexif().get(274) is None


def test_16bit_png_retains_tones(tmp_path):
    p = tmp_path / "scan.png"
    Image.fromarray(np.array([[0, 32768, 65535]], dtype=np.uint16)).save(p)
    out = read_raster(p, 100)
    assert [out.getpixel((x, 0))[0] for x in range(3)] == [0, 127, 255]


def test_palette_colour_and_transparent_index_zero(tmp_path):
    p = tmp_path / "palette.png"
    im = Image.new("P", (100, 50))
    im.putpalette([0, 0, 0, 255, 0, 0] + [0] * (768 - 6))
    im.paste(1, (50, 0, 100, 50))
    im.save(p, transparency=0)
    out = read_raster(p, 50)
    assert out.size == (50, 25)
    assert out.getpixel((5, 10)) == (255, 255, 255)
    assert out.getpixel((45, 10)) == (255, 0, 0)


@pytest.mark.parametrize("mode", ["L", "RGB", "RGBA", "LA"])
def test_raster_is_capped_before_reader(tmp_path, mode):
    p = tmp_path / "large.png"
    Image.new(mode, (500, 300)).save(p)
    assert read_raster(p, 100).size == (100, 60)


def test_corrupt_image_has_actionable_message(tmp_path):
    p = tmp_path / "broken.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="corrupt or incomplete"):
        read_raster(p, 100)


def test_decompression_limit_checks_before_load(tmp_path, monkeypatch):
    from pipeline import raster_input
    p = tmp_path / "big.png"
    Image.new("L", (20, 20)).save(p)
    monkeypatch.setattr(raster_input, "MAX_PIXELS", 300)
    with pytest.raises(ValueError, match="lower resolution"):
        read_raster(p, 100)


def test_decode_byte_budget_counts_colour_channels(tmp_path, monkeypatch):
    from pipeline import raster_input
    monkeypatch.setattr(raster_input, "MAX_DECODE_BYTES", 1000)
    for mode in ("RGB", "L"):
        p = tmp_path / f"scan-{mode}.png"
        Image.new(mode, (20, 20)).save(p)
        if mode == "RGB":
            with pytest.raises(ValueError, match="lower resolution or as JPEG"):
                read_raster(p, 10)
        else:
            assert read_raster(p, 10).size == (10, 10)


def test_16bit_scan_is_shrunk_before_tone_conversion(tmp_path):
    p = tmp_path / "16bit.png"
    Image.fromarray(np.full((300, 500), 32768, dtype=np.uint16)).save(p)
    out = read_raster(p, 100)
    assert out.size == (100, 60) and out.getpixel((50, 30))[0] == 127


def test_jpeg_draft_size_follows_image_aspect_ratio(tmp_path, monkeypatch):
    from pipeline import raster_input
    monkeypatch.setattr(raster_input, "MAX_DECODE_BYTES", 600_000)
    p = tmp_path / "scan.jpeg"
    Image.new("RGB", (1000, 700)).save(p)
    assert read_raster(p, 400).size == (400, 280)


@pytest.mark.parametrize("source", ["dxf", "ifc-storeys", "ifc-overview"])
def test_derived_geometry_previews_do_not_start_ocr_models(tmp_path, monkeypatch, source):
    from unittest.mock import Mock
    from engine.reader import text
    d = tmp_path / "doc"
    d.mkdir()
    Image.new("RGB", (100, 100), "white").save(d / "page-1.png")
    (d / "pages.json").write_text(json.dumps({"source": source, "pages": [{"page": 1}]}))
    ocr = Mock(return_value=[])
    monkeypatch.setattr(text, "ocr_words", ocr)
    assert text.load_page_text("doc", 1, tmp_path).words == []
    ocr.assert_not_called()


@pytest.mark.parametrize("version", ["R12", "R2000", "R2018"])
def test_dxf_blocks_and_versions(tmp_path, version):
    doc = ezdxf.new(version)
    block = doc.blocks.new("FRAME")
    block.add_line((0, 0), (4, 3))
    doc.modelspace().add_blockref("FRAME", (10, 20))
    src = tmp_path / "blocks.dxf"
    doc.saveas(src)
    meta = pages.do_dxf(src, tmp_path, px=400)[0]
    assert meta["w"] <= 400 and meta["h"] <= 400


def test_dxf_paperspace_fallback(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layout().add_line((0, 0), (20, 10))
    src = tmp_path / "paper.dxf"
    doc.saveas(src)
    meta = pages.do_dxf(src, tmp_path, px=300)[0]
    assert meta["layout"] != "Model" and meta["metres_per_unit"] is None


@pytest.mark.parametrize("lines", [[], [[(1, 1), (1, 1)]]])
def test_empty_and_zero_length_dxf_are_explained(lines):
    with pytest.raises(ValueError, match="geometry"):
        pages.dxf_frame(lines)


@pytest.mark.parametrize("unit,factor", [(0, None), (1, 0.0254), (2, 0.3048), (4, 0.001), (6, 1.0)])
def test_dxf_unit_detection_and_missing_units(tmp_path, unit, factor):
    doc = ezdxf.new("R2018")
    doc.units = unit
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True,
                                     dxfattribs={"layer": "ROOM_OUTLINE"})
    src = tmp_path / "units.dxf"
    doc.saveas(src)
    meta = pages.do_dxf(src, tmp_path)[0]
    (tmp_path / "pages.json").write_text(json.dumps({"source": "dxf", "pages": [meta]}))
    dxf_planmap.process("test", tmp_path, src)
    pm = json.loads((tmp_path / "planmap-1.json").read_text())
    if factor:
        assert pm["scale"]["m_per_px"] == pytest.approx(factor / meta["px_per_unit"], abs=1e-9)
        assert pm["items"][0]["props"]["area_m2_geom"] == pytest.approx(round(5000 * factor ** 2, 2))
    else:
        assert pm["scale"]["m_per_px"] is None and pm["scale"]["confidence"] == 0
        assert pm["items"][0]["props"]["area_m2_geom"] is None


def test_external_references_have_visible_warning(tmp_path):
    from ezdxf import xref
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (2, 3))
    xref.attach(doc, block_name="LINK", filename="missing.dxf", insert=(0, 0))
    src = tmp_path / "xref.dxf"
    doc.saveas(src)
    assert any("Linked files are not loaded" in w for w in pages.do_dxf(src, tmp_path)[0]["warnings"])


def test_nested_scene_transforms_and_recentring_boxes():
    from pygltflib import GLTF2, Accessor, Attributes, Mesh, Node, Primitive
    from pipeline.ifc_scene import node_boxes
    g = GLTF2(nodes=[Node(translation=[1e6, 10, 2e6], children=[1]),
                     Node(mesh=0, translation=[2, 3, 4], scale=[2, 1, 3])],
              meshes=[Mesh(primitives=[Primitive(attributes=Attributes(POSITION=0))])],
              accessors=[Accessor(min=[0, 0, 0], max=[1, 1, 1])])
    lo, hi = node_boxes(g)[1]
    assert lo == pytest.approx([1e6 + 2, 13, 2e6 + 4])
    assert hi - lo == pytest.approx([2, 1, 3])


def test_scene_cycle_fails_clearly():
    from pygltflib import GLTF2, Node
    from pipeline.ifc_scene import node_matrices
    with pytest.raises(ValueError, match="circular"):
        node_matrices(GLTF2(nodes=[Node(children=[1]), Node(children=[0])]))


@pytest.mark.parametrize("name,value", [("doc.json", "{"), ("elements.json", '{"elements": [{}]}'),
                                       ("planmap-1.json", '{"items": [{}]}'), ("planmap-1.json", "[]")])
def test_incomplete_index_never_crashes_or_becomes_zero(tmp_path, name, value):
    from engine.solvers.data import load_doc
    d = tmp_path / "doc"
    d.mkdir()
    (d / name).write_text(value)
    assert load_doc("doc", tmp_path) is None


def test_png_header_read_handles_truncated_input(tmp_path):
    from engine.reader.text import png_size
    from engine.readdraw import png_size as other_size
    p = tmp_path / "page.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert png_size(p) is None and other_size(p) is None


def test_far_origin_transform_preserves_shared_local_points():
    import ifcopenshell
    from scripts.robust_check import _translate_roots
    f = ifcopenshell.file(schema="IFC4")
    point = f.createIfcCartesianPoint((1.0, 2.0, 3.0))
    axes = f.createIfcAxis2Placement3D(point)
    roots = [f.createIfcLocalPlacement(None, axes) for _ in range(2)]
    child = f.createIfcLocalPlacement(roots[0], axes)
    _translate_roots(f, 100.0, 200.0)
    assert point.Coordinates == (1.0, 2.0, 3.0)
    assert child.RelativePlacement.Location.Coordinates == point.Coordinates
    assert all(p.RelativePlacement.Location.Coordinates == (101.0, 202.0, 3.0) for p in roots)


def test_corrupt_dxf_has_actionable_message(tmp_path):
    p = tmp_path / "broken.dxf"
    p.write_text("0\nSECTION\n2\nENTITIES\n0\n")
    with pytest.raises(ValueError, match="Export it again as DXF or IFC"):
        pages.do_dxf(p, tmp_path)


@pytest.mark.parametrize("version", ["R12", "R2018"])
def test_legacy_polyline_rooms_preserve_counts_without_declared_units(tmp_path, version):
    doc = ezdxf.new(version)
    doc.modelspace().add_polyline2d([(0, 0), (10, 0), (10, 5), (0, 5)], close=True,
                                    dxfattribs={"layer": "ROOM_OUTLINE"})
    src = tmp_path / "legacy.dxf"
    doc.saveas(src)
    meta = pages.do_dxf(src, tmp_path)[0]
    (tmp_path / "pages.json").write_text(json.dumps({"source": "dxf", "pages": [meta]}))
    dxf_planmap.process("test", tmp_path, src)
    pm = json.loads((tmp_path / "planmap-1.json").read_text())
    assert [i["kind"] for i in pm["items"]] == ["room"]
    if version == "R12":
        assert pm["items"][0]["props"]["area_m2_geom"] is None


def test_ifc_quantity_units_are_independent_and_can_override_project():
    import ifcopenshell
    import ifcopenshell.api
    from pipeline.ifc_scene import quantities_of
    f = ifcopenshell.file(schema="IFC4")
    project = f.createIfcProject(ifcopenshell.guid.new())
    mm = f.createIfcSIUnit(None, "LENGTHUNIT", "MILLI", "METRE")
    sqm = f.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE")
    cbm = f.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE")
    project.UnitsInContext = f.createIfcUnitAssignment([mm, sqm, cbm])
    foot = ifcopenshell.api.run("unit.add_conversion_based_unit", f, name="foot")
    el = f.createIfcWall(ifcopenshell.guid.new())
    qs = [f.createIfcQuantityLength("Length", None, None, 3000.0),
          f.createIfcQuantityLength("Width", None, foot, 3.0),
          f.createIfcQuantityArea("NetArea", None, None, 25.0),
          f.createIfcQuantityVolume("NetVolume", None, None, 6.0)]
    qto = f.createIfcElementQuantity(ifcopenshell.guid.new(), None, "Qto_WallBaseQuantities", None, None, qs)
    f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), None, None, None, [el], qto)
    q = quantities_of(el, 0.001)
    assert q["length_m"] == 3.0 and q["width_m"] == pytest.approx(0.9144)
    assert q["area_m2"] == 25.0 and q["volume_m3"] == 6.0
    project.UnitsInContext = None
    f.units.clear()  # emulate a new file with no project unit assignment
    assert quantities_of(el, 1) == {"width_m": pytest.approx(0.9144)}


@pytest.mark.parametrize("kind", ["door", "window", "wall"])
def test_missing_ifc_types_are_unknown_with_evidence_not_zero(tmp_path, monkeypatch, kind):
    from unittest.mock import Mock
    from engine.answer import answer
    from engine import forced
    d = tmp_path / "generated__unknown-types"
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"kind": "ifc", "title": "generated for demo test fixture"}))
    (d / "elements.json").write_text(json.dumps({"elements": [
        {"item_id": f"shape-{n}", "kind": "proxy", "ifc_class": "IfcBuildingElementProxy",
         "bbox_m": [[n, 0, 0], [n + 1, 1, 1]]} for n in range(3)]}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("FORCE_ANSWER", "1")
    fallback = Mock()
    monkeypatch.setattr(forced, "forced_answer", fallback)
    a = answer(f"How many {kind}s are there?", [d.name])
    assert a["answer"]["value"] is None and a["answer"]["abstained"]
    assert "shapes without object types" in a["answer"]["text_md"]
    assert a["citations"][0]["item_ids"] == [f"shape-{n}" for n in range(3)]
    assert a["evidence"]["scene"]["highlight_item_ids"] == a["citations"][0]["item_ids"]
    assert a["reasoning"]["steps"][0]["title"] == "Missing object types"
    assert a["cost"]["usd_total"] == 0
    fallback.assert_not_called()
