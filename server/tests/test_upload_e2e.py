"""Uploads end to end: IFC, PNG and DXF go through POST /api/upload -> ingestion -> ready, then a question gets an answer
with citations and the 3D scene is available. Only the vision-language model is replaced (a canned plan); IFC geometry,
page rendering, plan-map geometry rules, extrusion, USDZ, text and the engine are the real code."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from server import vlm_planmap

RAW = {
    "is_plan": True,
    "items": [
        {"kind": "room", "box_2d": [100, 100, 500, 500], "label": "KITCHEN", "room_type": "kitchen"},
        {"kind": "room", "box_2d": [100, 500, 500, 900], "label": "Bedroom 1", "room_type": "bedroom"},
        {"kind": "room", "box_2d": [500, 100, 900, 900], "label": "Living", "room_type": "living"},
        {"kind": "door", "box_2d": [300, 495, 360, 505]},
        {"kind": "door", "box_2d": [100, 300, 110, 360]},
        {"kind": "door", "box_2d": [490, 700, 505, 760]},
        {"kind": "window", "box_2d": [95, 600, 105, 700]},
        {"kind": "window", "box_2d": [895, 300, 905, 400]},
    ],
    "dimensions": [],
}


@pytest.fixture
def fake_vlm(monkeypatch):
    def read_page(doc_id, page, image_path, out_dir):
        from PIL import Image
        W, H = Image.open(image_path).size
        pm = vlm_planmap.build(doc_id, page, W, H, RAW, "test-vlm", 1)
        assert vlm_planmap.validate(pm) == []
        (out_dir / f"planmap-{page}.json").write_text(json.dumps(pm))
        words = [{"text": i["label"], "bbox_px": i["bbox_px"]} for i in pm["items"] if i["label"] and i["kind"] == "room"]
        return {"planmap": pm, "is_plan": True, "cost_usd": 0.0, "model": "test-vlm", "ms": 1, "words": words}
    monkeypatch.setattr(vlm_planmap, "read_page", read_page)


@pytest.fixture
def client(schema_url, tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    art.mkdir()
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("ENGINE_IMPL", "real")
    monkeypatch.setenv("INGEST_MODE", "vlm")  # the deploy-image path: no torch, VLM plan map
    from server import config, files_routes
    monkeypatch.setattr(config, "REPO", tmp_path)  # doc.json "files" are relative to the repo root

    async def ingest(doc_id):  # same job as the subprocess, in-process so the fake VLM applies
        from server import ingest_job
        monkeypatch.setattr(ingest_job, "REPO", tmp_path)
        await asyncio.to_thread(ingest_job.run, doc_id)
        await files_routes._persist(doc_id)
    monkeypatch.setattr(files_routes, "_ingest", ingest)
    monkeypatch.setattr(files_routes, "ingestion_available", lambda: True)
    from server.app import app
    with TestClient(app) as c:
        c.art = art
        yield c


def _wait_ready(client, doc_id, timeout=180):
    t = time.time()
    while time.time() - t < timeout:
        st = client.get(f"/api/docs/{doc_id}/ingest").json()
        if st["status"] != "running":
            return st, time.time() - t
        time.sleep(0.5)
    raise AssertionError("ingestion did not finish")


def _png_bytes():
    import io

    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1000, 800), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([100, 80, 900, 720], outline="black", width=6)
    d.line([500, 80, 500, 400], fill="black", width=4)
    d.line([100, 400, 900, 400], fill="black", width=4)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _dxf_bytes():
    import io

    import ezdxf
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for layer in ("A-WALL", "A-DOOR"):  # layer names the Swiss Dwellings reader does not know: VLM fallback
        doc.layers.add(layer)
    msp.add_lwpolyline([(0, 0), (8000, 0), (8000, 6000), (0, 6000)], close=True, dxfattribs={"layer": "A-WALL"})
    msp.add_line((4000, 0), (4000, 3000), dxfattribs={"layer": "A-WALL"})
    msp.add_line((0, 3000), (8000, 3000), dxfattribs={"layer": "A-WALL"})
    msp.add_arc((4000, 1500), 900, 0, 90, dxfattribs={"layer": "A-DOOR"})
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode()


def _ifc_bytes(tmp_path):
    import ifcopenshell
    import ifcopenshell.api
    import numpy as np
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    proj = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Mini")
    ifcopenshell.api.run("unit.assign_unit", f)
    ctx = ifcopenshell.api.run("context.add_context", f, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", f, context_type="Model", context_identifier="Body",
                                target_view="MODEL_VIEW", parent=ctx)
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    bld = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    st = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 0")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=proj)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[bld], relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[st], relating_object=bld)

    def place(el, x, y):
        m = np.eye(4)
        m[0, 3], m[1, 3] = x, y
        ifcopenshell.api.run("geometry.edit_object_placement", f, product=el, matrix=m)
    walls = []
    for k, (x, y, rot) in enumerate([(0, 0, 0), (0, 5, 0), (0, 0, 90), (6, 0, 90)]):
        w = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name=f"Wall {k + 1}")
        rep = ifcopenshell.api.run("geometry.add_wall_representation", f, context=body, length=6 if rot == 0 else 5,
                                   height=2.7, thickness=0.2)
        ifcopenshell.api.run("geometry.assign_representation", f, product=w, representation=rep)
        m = np.eye(4)
        c, s_ = (1, 0) if rot == 0 else (0, 1)
        m[:2, :2] = [[c, -s_], [s_, c]]
        m[0, 3], m[1, 3] = x, y
        ifcopenshell.api.run("geometry.edit_object_placement", f, product=w, matrix=m)
        walls.append(w)
    for k in range(2):
        d = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcDoor", name=f"Door {k + 1}")
        d.OverallWidth, d.OverallHeight = 0.9, 2.1
        rep = ifcopenshell.api.run("geometry.add_wall_representation", f, context=body, length=0.9, height=2.1, thickness=0.1)
        ifcopenshell.api.run("geometry.assign_representation", f, product=d, representation=rep)
        place(d, 1 + 2 * k, 0.05)
        walls.append(d)
    ifcopenshell.api.run("spatial.assign_container", f, products=walls, relating_structure=st)
    p = tmp_path / "mini.ifc"
    f.write(str(p))
    return p.read_bytes()


def _check_ready(client, doc_id, question, expect_scene=True):
    st, secs = _wait_ready(client, doc_id)
    assert st["status"] == "ready", st
    sc = client.get(f"/api/docs/{doc_id}/scene")
    assert sc.status_code == 200 and sc.json()["items"], "scene.json missing or empty"
    assert client.get(f"/api/docs/{doc_id}/files/scene.glb").status_code == 200
    chat = client.post("/api/chats", json={"doc_ids": [doc_id]}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": question})
    assert r.status_code == 200, r.text
    ans = None
    for block in r.text.replace("\r\n", "\n").split("\n\n"):
        ev = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if ev == "answer":
            ans = json.loads(data)
    assert ans is not None, r.text[:500]
    return st, secs, ans, sc.json()


def _assert_persisted_and_restored(client, doc_id, names):
    """Everything the ingestion built is in PostgreSQL, and a fresh disk gets it back (container restart)."""
    import shutil

    from server import artifact_store, db

    async def stored():
        pool = await db.get_pool()
        return {r["name"] for r in await pool.fetch("select name from doc_artifacts where doc_id=$1", doc_id)}
    have = client.portal.call(stored)
    for n in names:
        assert n in have, (n, sorted(have))
    shutil.rmtree(client.art / doc_id)
    artifact_store._restored.discard(doc_id)
    client.portal.call(artifact_store.ensure_doc, doc_id)
    for n in names:
        assert (client.art / doc_id / n).is_file(), n
    assert client.get(f"/api/docs/{doc_id}/scene").status_code == 200


def test_png_upload_ready_answer_scene(client, fake_vlm):
    r = client.post("/api/upload", files={"file": ("my plan.png", _png_bytes())})
    doc_id = r.json()["doc_id"]
    st, secs, ans, scene = _check_ready(client, doc_id, "How many doors are there?")
    assert ans["answer"]["value"] == 3 and ans["citations"] and ans["evidence"]["boxes"]
    assert scene["publishable"] if "publishable" in scene else True
    print(f"PNG ready in {secs:.1f}s")
    _assert_persisted_and_restored(client, doc_id, ("scene.glb", "scene.json", "planmap-1.json", "page-1.png"))


def test_dxf_upload_ready_answer_scene(client, fake_vlm):
    r = client.post("/api/upload", files={"file": ("floor.dxf", _dxf_bytes())})
    doc_id = r.json()["doc_id"]
    st, secs, ans, scene = _check_ready(client, doc_id, "How many windows are there?")
    assert ans["answer"]["value"] == 2 and ans["citations"]
    print(f"DXF ready in {secs:.1f}s")


def test_ifc_upload_ready_answer_scene_usdz(client, tmp_path):
    pytest.importorskip("ifcopenshell")
    r = client.post("/api/upload", files={"file": ("mini.ifc", _ifc_bytes(tmp_path))})
    doc_id = r.json()["doc_id"]
    st, secs, ans, scene = _check_ready(client, doc_id, "How many doors are there?")
    assert ans["answer"]["value"] == 2 and ans["citations"]
    assert (client.art / doc_id / "elements.json").is_file()
    assert any(k.startswith("IfcDoor") or v["kind"] == "door" for k, v in scene["items"].items())
    pxr = pytest.importorskip("pxr")  # noqa: F841
    assert client.get(f"/api/docs/{doc_id}/files/scene.usdz").status_code == 200
    print(f"IFC ready in {secs:.1f}s")
    _assert_persisted_and_restored(client, doc_id, ("scene.glb", "scene.usdz", "scene.json", "elements.json", "planmap-1.json"))
