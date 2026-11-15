"""Ingest of a vector PDF: exact plan map from the PDF geometry -> extrude(raster_walls=False) -> scene; any failure
falls back to today's VLM path; other formats keep raster_walls=True."""
import json

import pytest

from pipeline.tests.test_pdf_planmap import OPENS, PAGE, ROOMS, SC, WALLS, synth_pdf
from server import ingest_job


@pytest.fixture
def pdf_doc(tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    doc_id = "uploads__plan-1"
    (art / doc_id).mkdir(parents=True)
    pdf = synth_pdf(tmp_path / "plan.pdf")
    (art / doc_id / "doc.json").write_text(json.dumps(
        {"doc_id": doc_id, "source": "uploads", "formats": ["pdf"], "files": {"pdf": str(pdf)}, "kind": "pdf", "title": "t"}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setenv("INGEST_MODE", "vlm")
    monkeypatch.setenv("MODELS_FAKE", "1")
    return doc_id, art / doc_id


def _fake_process(calls):
    from pipeline import pdf_planmap

    def process(doc_id, ddir, pdf_path, page_index=0, write=True):
        calls.append(page_index)
        meta = json.loads((ddir / "pages.json").read_text())["pages"][page_index]
        page = dict(PAGE, W_pt=meta["w"] / 2, H_pt=meta["h"] / 2)  # rendered at 144 dpi in this test
        pm = pdf_planmap.build(doc_id, page_index + 1, meta["w"], meta["h"], page, WALLS, ROOMS, OPENS, SC)
        (ddir / f"planmap-{page_index + 1}.json").write_text(json.dumps(pm))
        return pm
    return process


def test_vector_pdf_gets_scene_without_raster_walls(pdf_doc, monkeypatch):
    from pipeline import extrude, pages, pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setenv("PDF_VIA_IFC", "0")
    calls, seen = [], []
    monkeypatch.setattr(pdf_planmap, "process", _fake_process(calls))
    monkeypatch.setattr(ingest_job, "_vlm_pages", lambda *a: pytest.fail("VLM path must not run when the vector plan map is usable"))
    real = extrude.process
    monkeypatch.setattr(extrude, "process", lambda *a, **k: (seen.append(k.get("raster_walls")), real(*a, **k))[1])
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready"
    assert calls == [0] and seen == [False]
    assert (ddir / "planmap-1.json").is_file() and (ddir / "scene.glb").is_file() and (ddir / "scene.json").is_file()
    sc = json.loads((ddir / "scene.json").read_text())
    kinds = {v["kind"] for v in sc["items"].values()}
    assert {"wall", "room", "door", "window"} <= kinds
    assert any(s["stage"] == "planmap_pdf_vector" and s["ok"] for s in st.stages)


@pytest.mark.parametrize("mode", ["raises", "none"])
def test_pdf_falls_back_to_vlm(pdf_doc, monkeypatch, mode):
    from pipeline import pdf_planmap
    doc_id, ddir = pdf_doc

    def process(*a, **k):
        if mode == "raises":
            raise RuntimeError("odd page")
        return None
    monkeypatch.setattr(pdf_planmap, "process", process)
    vlm = []
    monkeypatch.setattr(ingest_job, "_vlm_pages", lambda *a: (vlm.append(1), [])[1])
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready"
    assert vlm == [1] and not list(ddir.glob("planmap-*.json")) and not (ddir / "scene.glb").exists()


def test_vector_switch_off_is_todays_path(pdf_doc, monkeypatch):
    from pipeline import pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setenv("PDF_VECTOR", "0")
    monkeypatch.setattr(pdf_planmap, "process", lambda *a, **k: pytest.fail("switched off"))
    monkeypatch.setattr(ingest_job, "_vlm_pages", lambda *a: [])
    assert ingest_job._run(doc_id, ingest_job.Status(ddir / "ingest.json")) == "ready"


def test_extrude_default_keeps_raster_walls(tmp_path, monkeypatch):
    from pipeline import extrude
    seen = []
    (tmp_path / "planmap-1.json").write_text(json.dumps({"scale": {"m_per_px": 0.01}, "items": []}))
    monkeypatch.setattr(extrude, "process", lambda *a, **k: seen.append(k.get("raster_walls")))
    ingest_job._extrude("d", tmp_path, 1)
    ingest_job._extrude("d", tmp_path, 1, raster_walls=False)
    assert seen == [True, False]


def test_page_cap(pdf_doc, monkeypatch):
    from pipeline import pdf_planmap
    doc_id, ddir = pdf_doc
    (ddir / "pages.json").write_text(json.dumps({"pages": [{"page": i, "w": 10, "h": 10} for i in range(1, 9)]}))
    calls = []

    def process(doc_id, ddir, pdf, i, write=True):
        calls.append(i)
        (ddir / f"planmap-{i + 1}.json").write_text("{}")
        return {}
    monkeypatch.setattr(pdf_planmap, "process", process)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._pdf_vector_pages(doc_id, ddir, st, ddir / "x.pdf") == [1, 2, 3, 4] and calls == [0, 1, 2, 3]


def test_vector_extrude_failure_falls_back_to_vlm(pdf_doc, monkeypatch):
    from pipeline import pages, pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setenv("PDF_VIA_IFC", "0")
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    seen, vlm = [], []

    def extrude(doc_id, ddir, page, raster_walls=True):
        seen.append(raster_walls)
        if not raster_walls:
            raise RuntimeError("bad vector walls")
    monkeypatch.setattr(ingest_job, "_extrude", extrude)
    monkeypatch.setattr(ingest_job, "_usdz", lambda *a: None)

    def vlm_pages(doc_id, ddir, st, cost):
        vlm.append(sorted(f.name for f in ddir.glob("planmap-*.json")))
        return [1]
    monkeypatch.setattr(ingest_job, "_vlm_pages", vlm_pages)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready"
    assert seen == [False, True] and vlm == [[]]
    assert any(s["stage"] == "extrude_pdf_vector" for s in st.stages)


def test_ifc_route_failure_falls_back_to_extrude(pdf_doc, monkeypatch):
    from pipeline import pages, pdf_planmap, pdf_to_ifc
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    monkeypatch.setattr(ingest_job, "_vlm_pages", lambda *a: pytest.fail("no VLM"))

    def boom(*a, **k):
        (ddir / "model.ifc").write_text("half")  # a partial file must not survive
        raise RuntimeError("ifc export failed")
    monkeypatch.setattr(pdf_to_ifc, "build", boom)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready"
    stg = {s["stage"]: s for s in st.stages}
    assert stg["ifc_from_pdf"]["ok"] and "fell back" in stg["ifc_from_pdf"]["note"] and stg["extrude"]["ok"]
    assert not (ddir / "model.ifc").exists() and not (ddir / "elements.json").exists() and (ddir / "scene.glb").is_file()
    pm = json.loads((ddir / "planmap-1.json").read_text())
    assert any(i["item_id"] == "room-001" for i in pm["items"])  # ids not relinked on failure


def test_ifc_route_success(pdf_doc, monkeypatch):
    pytest.importorskip("ifcopenshell")
    from pipeline import pages, pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    monkeypatch.setattr(ingest_job, "_extrude", lambda *a, **k: pytest.fail("IFC route worked: no extrude"))
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready", st.stages
    assert (ddir / "model.ifc").is_file() and (ddir / "elements.json").is_file() and (ddir / "scene.glb").is_file()
    assert (ddir / "planmap-1.json").is_file() and (ddir / "page-1.png").is_file()


def test_label_only_rooms_get_no_floor_but_stay_in_planmap(tmp_path, monkeypatch):
    from pipeline import extrude
    pm = {"scale": {"m_per_px": 0.01}, "items": [
        {"item_id": "room-001", "kind": "room", "polygon_px": [[0, 0], [10, 0], [10, 10]], "bbox_px": [0, 0, 10, 10]},
        {"item_id": "room-002", "kind": "room", "polygon_px": None, "bbox_px": [20, 20, 30, 25]}]}
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    seen = []
    monkeypatch.setattr(extrude, "process", lambda d, art, page, **k: seen.append(
        [i["item_id"] for i in json.loads((art / "planmap-1.json").read_text())["items"]]))
    ingest_job._extrude("d", tmp_path, 1, raster_walls=False)
    assert seen == [["room-001"]]
    assert json.loads((tmp_path / "planmap-1.json").read_text()) == pm
