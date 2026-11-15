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


# ---------------------------------------------------------------- whole-ingest budget, multi-storey, MEP hook

@pytest.fixture
def budget(monkeypatch):
    """A tiny ingest budget with forked, time-bounded heavy steps (as run() sets it), reset after the test."""
    def set_(seconds, **consts):
        for k, v in consts.items():
            monkeypatch.setattr(ingest_job, k, v)
        monkeypatch.setenv("INGEST_BUDGET_S", str(seconds))
        ingest_job._set_deadline(None)
    yield set_
    ingest_job._DEADLINE[0] = None


def test_bounded_child_timeout_and_errors(budget):
    import time
    budget(100)
    assert ingest_job._bounded(lambda: 41 + 1, 10) == ("ok", 42)
    res, val = ingest_job._bounded(lambda: 1 / 0, 10)
    assert res == "error" and "ZeroDivisionError" in val
    t = time.time()
    assert ingest_job._bounded(lambda: time.sleep(30), 0.5) == ("timeout", None)
    assert time.time() - t < 10
    ingest_job._DEADLINE[0] = None  # no budget: inline
    assert ingest_job._bounded(lambda: 7, 0.001) == ("ok", 7)


def test_budget_drops_slow_vector_page_keeps_first(pdf_doc, monkeypatch, budget):
    import time
    from pipeline import pdf_planmap
    doc_id, ddir = pdf_doc
    (ddir / "pages.json").write_text(json.dumps({"pages": [{"page": i, "w": 10, "h": 10} for i in (1, 2)]}))

    def process(doc_id, ddir, pdf, i, write=True):
        if i == 1:
            time.sleep(60)  # a dense sheet: would run past the ingest deadline
        (ddir / f"planmap-{i + 1}.json").write_text("{}")
        return {}
    monkeypatch.setattr(pdf_planmap, "process", process)
    budget(4, VECTOR_RESERVE_S=1.0, VECTOR_MIN_PAGE_S=0.5)
    st = ingest_job.Status(ddir / "ingest.json")
    t = time.time()
    assert ingest_job._pdf_vector_pages(doc_id, ddir, st, ddir / "x.pdf") == [1]
    assert time.time() - t < 20
    assert not (ddir / "planmap-2.json").exists() and "budget" in st.stages[-1]["note"]


def test_budget_no_time_for_vector_falls_back(pdf_doc, monkeypatch, budget):
    from pipeline import pdf_planmap
    doc_id, ddir = pdf_doc
    (ddir / "pages.json").write_text(json.dumps({"pages": [{"page": 1, "w": 10, "h": 10}]}))
    monkeypatch.setattr(pdf_planmap, "process", lambda *a, **k: pytest.fail("no time left: page not started"))
    budget(10, VECTOR_RESERVE_S=100.0)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._pdf_vector_pages(doc_id, ddir, st, ddir / "x.pdf") == []


def test_ifc_route_timeout_falls_back_to_extrude(pdf_doc, monkeypatch, budget):
    import time
    from pipeline import pages, pdf_planmap, pdf_to_ifc
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    monkeypatch.setattr(ingest_job, "_vlm_pages", lambda *a: pytest.fail("no VLM"))

    def slow(*a, **k):
        (ddir / "model.ifc").write_text("half")
        time.sleep(60)
    monkeypatch.setattr(pdf_to_ifc, "build", slow)
    budget(60, IFC_RESERVE_S=58.0, VECTOR_RESERVE_S=1.0, VECTOR_MIN_PAGE_S=0.5)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready", st.stages
    stg = {s["stage"]: s for s in st.stages}
    assert "fell back" in stg["ifc_from_pdf"]["note"] and "budget" in stg["ifc_from_pdf"]["note"]
    assert stg["extrude"]["ok"] and (ddir / "scene.glb").is_file() and not (ddir / "model.ifc").exists()
    assert "ifc" not in json.loads((ddir / "doc.json").read_text()).get("formats", [])


def test_storeys_fallback_and_stacking(monkeypatch):
    import sys
    import types
    import pipeline
    pms = [{"provenance": {}}, {"provenance": {"storey": {"name": "Level 2", "elevation_m": 3.4}}}, {"provenance": {}}]

    def levels(fn):
        m = types.SimpleNamespace(storeys_from_planmaps=fn)
        monkeypatch.setitem(sys.modules, "pipeline.pdf_levels", m)
        monkeypatch.setattr(pipeline, "pdf_levels", m, raising=False)
    levels(lambda p: (_ for _ in ()).throw(RuntimeError("levels down")))
    assert ingest_job._storeys(pms) == [("Floor 1", 0.0), ("Level 2", 3.4), ("Floor 3", 6.0)]
    levels(lambda p: [{"page_index": 0, "name": "Ground floor", "elevation_m": 0.0},
                      {"page_index": 2, "name": "Ground floor", "elevation_m": 0.0}])
    names = ingest_job._storeys(pms)
    assert names == [("Ground floor", 0.0), ("Level 2", 3.4), ("Ground floor", 0.0)]
    assert ingest_job._stack_pages(pms, names) == [0, 1]  # second sheet of the ground floor is not stacked


def test_two_plan_pages_become_two_storeys(pdf_doc, monkeypatch):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell
    from pipeline import pages, pdf_planmap, pdf_to_ifc
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    fake = _fake_process([])
    (ddir / "pages.json").exists()

    def process(doc_id, ddir, pdf, i, write=True):
        return fake(doc_id, ddir, pdf, 0) if i == 0 else None
    monkeypatch.setattr(pdf_planmap, "process", process)
    monkeypatch.setattr(ingest_job, "_extrude", lambda *a, **k: pytest.fail("IFC route worked: no extrude"))
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready"
    # second plan page = a copy of the first one, one storey up
    pm = json.loads((ddir / "planmap-1.json").read_text())
    (ddir / "planmap-2.json").write_text(json.dumps({**pm, "page": 2}))
    (ddir / "planmap-1.json").write_text(json.dumps(fake(doc_id, ddir, None, 0)))
    seen = []
    real = pdf_to_ifc.build_many
    monkeypatch.setattr(pdf_to_ifc, "build_many", lambda p, *a, **k: (seen.append([(n, z) for _, n, z in p]),
                                                                       real(p, *a, **k))[1])
    notes = []
    ingest_job._pdf_via_ifc(doc_id, ddir, json.loads((ddir / "doc.json").read_text()), [1, 2], notes)
    assert len(seen) == 1 and len(seen[0]) == 2 and seen[0][0][1] < seen[0][1][1]
    f = ifcopenshell.open(str(ddir / "model.ifc"))
    assert len(f.by_type("IfcBuildingStorey")) == 2
    ids = [{i["item_id"] for i in json.loads((ddir / f"planmap-{n}.json").read_text())["items"] if i["kind"] == "wall"}
           for n in (1, 2)]
    assert ids[0] and ids[1] and not ids[0] & ids[1]  # both pages relinked to their own GlobalIds
    assert any(n.startswith("storeys") for n in notes)


@pytest.mark.parametrize("mode", ["ok", "raises", "not_mep"])
def test_mep_hook_guarded(pdf_doc, monkeypatch, mode):
    pytest.importorskip("ifcopenshell")
    import sys
    import types
    from pipeline import pages, pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    calls = []

    def enrich_ifc(ifc_path, pdf_path, page_index, planmap):
        calls.append((str(ifc_path), page_index, bool(planmap.get("items"))))
        if mode == "raises":
            raise RuntimeError("duct trace failed")
        return {"ok": True, "ducts": 3, "terminals": 2}
    monkeypatch.setitem(sys.modules, "pipeline.pdf_mep", types.SimpleNamespace(
        is_mep_sheet=lambda pdf, i=0: mode != "not_mep", enrich_ifc=enrich_ifc))
    import pipeline
    monkeypatch.setattr(pipeline, "pdf_mep", sys.modules["pipeline.pdf_mep"], raising=False)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready", st.stages
    assert (ddir / "model.ifc").is_file() and (ddir / "scene.glb").is_file()
    stg = {s["stage"]: s for s in st.stages}
    assert stg["ifc_from_pdf"]["ok"] and "fell back" not in stg["ifc_from_pdf"].get("note", "")
    if mode == "not_mep":
        assert calls == []
    else:
        assert calls == [(str(ddir / "model.ifc"), 0, True)]
        assert ("ducts=3" if mode == "ok" else "mep skipped") in stg["ifc_from_pdf"]["note"]


@pytest.mark.parametrize("mode", ["combined", "combine_raises"])
def test_mep_on_architect_model(pdf_doc, monkeypatch, mode):
    """An MEP page whose architect plan is already ingested goes through pdf_mep.combine onto that IFC; a failing
    combine falls back to the sheet's own enrich_ifc."""
    pytest.importorskip("ifcopenshell")
    import shutil
    import sys
    import types
    from pipeline import pages, pdf_planmap
    doc_id, ddir = pdf_doc
    monkeypatch.setattr(pages, "DPI", 144)
    monkeypatch.setattr(pdf_planmap, "process", _fake_process([]))
    calls = []

    def combine(ark_pdf, mep_pdf, ark_ifc, out_ifc, mep_page_index=0, **kw):
        calls.append("combine")
        if mode == "combine_raises":
            raise RuntimeError("align failed")
        shutil.copy(ark_ifc, out_ifc)
        return {"ducts": 7, "terminals": 1, "fittings": 2, "clusters": []}

    def enrich_ifc(ifc_path, pdf_path, page_index, planmap):
        calls.append("enrich")
        return {"ok": True, "ducts": 3, "terminals": 2}
    monkeypatch.setitem(sys.modules, "pipeline.pdf_mep", types.SimpleNamespace(
        is_mep_sheet=lambda pdf, i=0: True, enrich_ifc=enrich_ifc, combine=combine))
    import pipeline
    monkeypatch.setattr(pipeline, "pdf_mep", sys.modules["pipeline.pdf_mep"], raising=False)
    holder = {}

    def arch(pdf, i, me):
        ifc = ddir.parent / "ark.ifc"
        if not ifc.exists():
            shutil.copy(ddir / "model.ifc", ifc)
        holder["ifc"] = ifc
        return {"doc_id": "ark", "pdf": pdf, "ifc": ifc, "matches": 9, "rms_pt": 0.5}
    monkeypatch.setattr(ingest_job, "_mep_architect", arch)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._run(doc_id, st) == "ready", st.stages
    note = {s["stage"]: s for s in st.stages}["ifc_from_pdf"].get("note", "")
    if mode == "combined":
        assert calls == ["combine"] and "ducts=7" in note and "on architect ark (9 anchors)" in note
    else:
        assert calls == ["combine", "enrich"] and "ducts=3" in note
    assert (ddir / "scene.glb").is_file() and not list(ddir.glob("*.combined.tmp.ifc"))


def test_refine_text_stops_at_budget(tmp_path, budget):
    d = tmp_path
    (d / "doc.json").write_text(json.dumps({"files": {"pdf": str(tmp_path / "x.pdf")}}))
    t = {"page": 1, "image": {"w": 10, "h": 10}, "extractor": "pdfium", "words": [{"text": "A", "bbox_px": [0, 0, 1, 1]}]}
    (d / "text-1.json").write_text(json.dumps(t))
    budget(1)
    ingest_job._DEADLINE[0] -= 100  # past the deadline: nothing starts
    assert ingest_job.refine_text("d", d) == 0
    assert json.loads((d / "text-1.json").read_text()) == t


def test_lean_pdf_words_match_pdfminer(tmp_path):
    from pipeline import pages
    pdf = synth_pdf(tmp_path / "plan.pdf")
    assert ingest_job._lean_pdf_words(pdf, 0) == pages.pdf_words(pdf, 0, 1, 1, 1)


def test_budget_soft_limit_returns_partial_plan_map(pdf_doc, monkeypatch, budget):
    """A stage that would run past the page's share (here openings) is cut in the child: the page keeps its plan map,
    flagged in provenance.budget and in the stage note."""
    import time
    from pipeline import pdf_openings, pdf_planmap
    doc_id, ddir = pdf_doc
    (ddir / "pages.json").write_text(json.dumps({"pages": [{"page": 1, "w": 10, "h": 10}]}))
    monkeypatch.setattr(pdf_openings, "openings", lambda page, walls: (time.sleep(60), ["never"])[1])

    def process(doc_id, ddir, pdf, i, write=True):
        opens = pdf_openings.openings({}, [])
        pm = {"items": [], "opens": opens, "provenance": {}}
        (ddir / f"planmap-{i + 1}.json").write_text(json.dumps(pm))
        return pm
    monkeypatch.setattr(pdf_planmap, "process", process)
    budget(12, VECTOR_RESERVE_S=1.0, VECTOR_MIN_PAGE_S=0.5)
    st = ingest_job.Status(ddir / "ingest.json")
    t = time.time()
    assert ingest_job._pdf_vector_pages(doc_id, ddir, st, ddir / "x.pdf") == [1]
    assert time.time() - t < 15
    pm = json.loads((ddir / "planmap-1.json").read_text())
    assert pm["opens"] == [] and pm["provenance"]["budget"]["cut"] == ["openings"]
    assert "partial" in st.stages[-1]["note"]
    assert pdf_openings.openings.__name__ == "<lambda>"  # parent's functions untouched


def test_parallel_openings_same_result(pdf_doc, monkeypatch, budget):
    """In the budgeted child, openings runs in a grandchild while rooms runs: same result, page keys it leaves
    (e.g. _arc_polylines) come back, the two overlap in time."""
    import time
    from pipeline import pdf_openings, pdf_planmap, pdf_rooms
    doc_id, ddir = pdf_doc
    (ddir / "pages.json").write_text(json.dumps({"pages": [{"page": 1, "w": 10, "h": 10}]}))
    monkeypatch.setattr(pdf_rooms, "rooms", lambda page, walls: (time.sleep(1.5), ["r"])[1])

    def openings(page, walls):
        time.sleep(1.5)
        page["_arc_polylines"] = [[[0, 0], [1, 1], [2, 0]]]
        return [{"kind": "door", "n": len(walls)}]
    monkeypatch.setattr(pdf_openings, "openings", openings)

    def process(doc_id, ddir, pdf, i, write=True):
        page, walls = {"W_pt": 1}, [1, 2, 3]
        t = time.time()
        r = pdf_rooms.rooms(page, walls)
        o = pdf_openings.openings(page, walls)
        pm = {"items": [], "r": r, "o": o, "arcs": page.get("_arc_polylines"), "dt": time.time() - t, "provenance": {}}
        (ddir / f"planmap-{i + 1}.json").write_text(json.dumps(pm))
        return pm
    monkeypatch.setattr(pdf_planmap, "process", process)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    budget(60, VECTOR_RESERVE_S=1.0, VECTOR_MIN_PAGE_S=0.5)
    st = ingest_job.Status(ddir / "ingest.json")
    assert ingest_job._pdf_vector_pages(doc_id, ddir, st, ddir / "x.pdf") == [1]
    pm = json.loads((ddir / "planmap-1.json").read_text())
    assert pm["r"] == ["r"] and pm["o"] == [{"kind": "door", "n": 3}] and pm["arcs"] == [[[0, 0], [1, 1], [2, 0]]]
    assert pm["dt"] < 2.8  # overlapped (sequential would be 3 s)
    assert "budget" not in pm["provenance"]


def test_fork_call_and_mep_openings_cap(pdf_doc, monkeypatch, budget):
    """os.fork bounded call (usable inside a daemon child); an MEP sheet caps openings at MEP_OPENINGS_CAP_S and
    skips the add-ons while rooms keep their time."""
    import time
    from pipeline import pdf_openings, pdf_planmap, pdf_rooms
    assert ingest_job._fork_call(lambda: {"a": 1}, 10) == ("ok", {"a": 1})
    assert ingest_job._fork_call(lambda: time.sleep(30), 0.5) == ("timeout", None)
    assert ingest_job._fork_call(lambda: 1 / 0, 10)[0] == "error"
    doc_id, ddir = pdf_doc
    (ddir / "pages.json").write_text(json.dumps({"pages": [{"page": 1, "w": 10, "h": 10}]}))
    monkeypatch.setattr(ingest_job, "_mep_hint", lambda pdf, i: True)
    monkeypatch.setattr(pdf_rooms, "rooms", lambda page, walls: (time.sleep(2.0), ["r"])[1])
    monkeypatch.setattr(pdf_openings, "openings", lambda page, walls: (time.sleep(60), ["never"])[1])

    def process(doc_id, ddir, pdf, i, write=True):
        page, walls = {}, []
        pm = {"items": [], "r": pdf_rooms.rooms(page, walls), "o": pdf_openings.openings(page, walls), "provenance": {}}
        (ddir / f"planmap-{i + 1}.json").write_text(json.dumps(pm))
        return pm
    monkeypatch.setattr(pdf_planmap, "process", process)
    budget(80, MEP_RESERVE_S=1.0, VECTOR_MIN_PAGE_S=0.5, MEP_OPENINGS_CAP_S=1.0)
    st = ingest_job.Status(ddir / "ingest.json")
    t = time.time()
    assert ingest_job._pdf_vector_pages(doc_id, ddir, st, ddir / "x.pdf") == [1]
    assert time.time() - t < 20
    pm = json.loads((ddir / "planmap-1.json").read_text())
    assert pm["r"] == ["r"] and pm["o"] == [] and "MEP sheet" in st.stages[-1]["note"]


def test_status_rerun_resets_old_started_at(tmp_path):
    import time
    f = tmp_path / "ingest.json"
    f.write_text(json.dumps({"status": "ready", "started_at": time.time() - 3600}))
    assert time.time() - ingest_job.Status(f).started_at < 5   # stale: a re-run starts its own clock
    f.write_text(json.dumps({"status": "running", "started_at": time.time() - 30}))
    assert 25 < time.time() - ingest_job.Status(f).started_at < 40  # queued 30 s ago: queue time still counts
