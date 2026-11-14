"""A vector PDF converted through pipeline.pdf_to_ifc behaves like an IFC upload: doc.json lists the derived model
(formats + files['ifc'], kind stays "pdf" for the 2D viewer), the engine loads it in IFC mode with storeys, and the
plan-map ids are the IFC GlobalIds so IFC answers still cite boxes on the PDF page."""
import json

import pytest

from server import ingest_job
from server.tests.test_ingest_pdf import _fake_process, pdf_doc  # noqa: F401  (fixture)


@pytest.fixture
def ingested(pdf_doc, monkeypatch):  # noqa: F811
    pytest.importorskip("ifcopenshell")
    from pipeline import pages, pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    monkeypatch.setattr(ingest_job, "_extrude", lambda *a, **k: pytest.fail("IFC route worked: no extrude"))
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready", st.stages
    assert any(s["stage"] == "ifc_from_pdf" and s["ok"] for s in st.stages)
    return doc_id, ddir


def test_doc_json_lists_the_derived_ifc(ingested):
    doc_id, ddir = ingested
    d = json.loads((ddir / "doc.json").read_text())
    assert d["kind"] == "pdf"                       # web viewer keeps the PDF page in 2D
    assert d["formats"] == ["pdf", "ifc"]           # type tag (formats[0]) stays PDF
    assert d["ifc_from"] == "pdf" and "pdf" in d["files"]
    from engine import library
    assert library._is_ifc(d)
    from engine.mistakes import _ifc_source
    assert _ifc_source(doc_id, ddir.parent) == (ddir / "model.ifc")


def test_engine_loads_ifc_mode_with_pdf_page_boxes(ingested):
    doc_id, ddir = ingested
    from engine.solvers.data import load_doc
    doc = load_doc(doc_id, ddir.parent)
    assert doc.mode == "ifc"
    assert [s["name"] for s in doc.storeys] == ["Floor 1"]
    by = {k: [i for i in doc.items if i.kind == k] for k in ("room", "door", "window", "wall")}
    assert len(by["door"]) == 1 and len(by["window"]) == 1 and by["wall"]
    room = next(r for r in by["room"] if r.props.get("long_name") == "Kitchen")   # label-only 'Bedroom' has no 3D box
    assert room.name == "0.01" and room.bbox_m
    assert room.q.get("area_m2") == pytest.approx(29.0, rel=0.05)   # printed area
    for it in by["door"] + by["window"] + [room]:
        assert it.storey == "Floor 1" and it.bbox_m and it.bbox_px and it.page == 1   # 3D + 2D citation
    sj = json.loads((ddir / "scene.json").read_text())
    assert sj["storeys"] and all(i.item_id in sj["items"] for i in by["door"] + by["window"])


def test_ifc_solvers_answer_on_converted_pdf(ingested, monkeypatch):
    doc_id, ddir = ingested
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    r = answer("How many doors are there?", [doc_id])
    assert r["route"] == "index" and r["answer"]["value"] == 1, r["answer"]
    assert r["evidence"]["scene"]["highlight_item_ids"]
    r = answer("What is the area of the Kitchen?", [doc_id])
    assert r["answer"]["value"] == pytest.approx(29.0, rel=0.05), r["answer"]


def test_failed_ifc_route_removes_marks(pdf_doc, monkeypatch):  # noqa: F811
    from pipeline import pages, pdf_planmap, pdf_to_ifc
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))

    def boom(*a, **k):
        raise RuntimeError("no ifc")
    monkeypatch.setattr(pdf_to_ifc, "build", boom)
    st = ingest_job.Status(ddir / "ingest.json")
    ingest_job._run(doc_id, st)
    d = json.loads((ddir / "doc.json").read_text())
    assert d["formats"] == ["pdf"] and "ifc" not in d["files"] and "ifc_from" not in d and d["kind"] == "pdf"


def test_mark_is_idempotent_and_reversible(tmp_path):
    (tmp_path / "doc.json").write_text(json.dumps({"kind": "pdf", "formats": ["pdf"], "files": {"pdf": "x.pdf"}}))
    (tmp_path / "model.ifc").write_text("ISO-10303-21;")
    ingest_job.mark_ifc_from_pdf(tmp_path, True)
    ingest_job.mark_ifc_from_pdf(tmp_path, True)
    d = json.loads((tmp_path / "doc.json").read_text())
    assert d["formats"] == ["pdf", "ifc"] and d["files"]["ifc"].endswith("model.ifc")
    ingest_job.mark_ifc_from_pdf(tmp_path, False)
    assert json.loads((tmp_path / "doc.json").read_text()) == {"kind": "pdf", "formats": ["pdf"], "files": {"pdf": "x.pdf"}}
