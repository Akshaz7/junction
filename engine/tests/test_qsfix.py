"""F-QSFIX: provenance names the real geometry source; wide / outdoor-facing 'windows' from an image model are flagged."""
import json

from engine.glazed_doors import attach, suspects
from engine.reasoning_parts.confidence import geometry_source
from engine.solvers.data import Doc, Item


def _pm(tmp_path, did, sources):
    d = tmp_path / did
    d.mkdir()
    (d / "planmap-1.json").write_text(json.dumps({"items": [{"item_id": f"x{i}", "kind": "door", "source": s} for i, s in enumerate(sources)]}))


def test_geometry_source_follows_items_not_extension(tmp_path):
    _pm(tmp_path, "dxf_read_by_vlm", ["vlm", "ocr"])      # a .dxf whose layers were empty
    _pm(tmp_path, "dxf_layers", ["dxf"])
    _pm(tmp_path, "pdfv", ["pdf_vector"])
    _pm(tmp_path, "scan", ["det", "seg", "ocr"])
    _pm(tmp_path, "mixed", ["dxf", "vlm"])
    assert geometry_source(tmp_path, ["dxf_read_by_vlm"]) == "vlm"
    assert geometry_source(tmp_path, ["dxf_layers"]) == "cad"
    assert geometry_source(tmp_path, ["pdfv"]) == "pdf_vector"
    assert geometry_source(tmp_path, ["scan"]) == "scan"
    assert geometry_source(tmp_path, ["mixed"]) == "vlm"
    assert geometry_source(tmp_path, ["missing"]) is None


def _doc(widths, source="vlm", room=None):
    its = [Item(f"window-{i}", "window", bbox_px=[100 * i, 0, 100 * i + w, 20], source=source, conf=.5) for i, w in enumerate(widths)]
    if room:
        its.append(Item("room-1", "room", label=room, bbox_px=[0, -10, 5000, 30], source=source))
    return Doc("d", "planmap", its, scale={"m_per_px": 0.005})


def _w(d):
    return [i for i in d.items if i.kind == "window"]


def test_wide_window_flagged():
    d = _doc([120, 130, 125, 400])
    assert [s.item_id for s in suspects(d, _w(d))] == ["window-3"]


def test_outdoor_room_flags_touching_windows():
    d = _doc([120, 130, 125], room="Patio")
    assert len(suspects(d, _w(d))) == 3


def test_exact_sources_never_flagged():
    d = _doc([120, 130, 125, 400], source="dxf")
    assert suspects(d, _w(d)) == []


def test_uniform_windows_not_flagged():
    d = _doc([120, 130, 125, 128])
    assert suspects(d, _w(d)) == []


def test_attach_adds_note_and_keeps_count(tmp_path, monkeypatch):
    d = _doc([120, 130, 125, 400])
    monkeypatch.setattr("engine.solvers.data.load_doc", lambda *a, **k: d)
    res = {"doc_ids": ["d"], "answer": {"text_md": "There are 4 windows.", "value": 4, "unit": "count"},
           "citations": [{"n": i + 1, "item_ids": [f"window-{i}"]} for i in range(4)]}
    attach(res, "How many windows are there?", tmp_path)
    assert res["answer"]["value"] == 4 and "1 of these 4 windows" in res["answer"]["text_md"] and "glazed door" in res["answer"]["text_md"]
    res2 = {"doc_ids": ["d"], "answer": {"text_md": "x", "value": 4, "unit": "count"}, "citations": []}
    attach(res2, "How many doors are there?", tmp_path)
    assert res2["answer"]["text_md"] == "x"
