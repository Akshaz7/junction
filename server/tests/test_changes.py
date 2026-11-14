"""S-07: change feed and one comparison, backed by synthetic revisions (source: truth)."""
import json

import pytest
from fastapi.testclient import TestClient

DOC = "swiss_dwellings__site1-b1-f1"
TRUTH = {"doc_id": DOC, "generated_for_demo": True, "note": "n", "image": {"w": 100, "h": 200}, "changes": [
    {"change_id": "c1", "type": "removed", "kind": "wall", "description": "wall gone", "v1_item": "wall-14", "v2_item": None,
     "bbox_px_v1": [1, 2, 3, 4], "bbox_px_v2": None, "size_m": [0.24, 3.07]},
    {"change_id": "c2", "type": "added", "kind": "door", "description": "door", "v1_item": None, "v2_item": "door-37",
     "bbox_px_v1": None, "bbox_px_v2": [5, 6, 7, 8], "width_m": 0.9},
    {"change_id": "c3", "type": "modified", "kind": "room", "description": "label", "v1_item": "room-1", "v2_item": "room-1",
     "bbox_px_v1": [1, 1, 2, 2], "bbox_px_v2": [1, 1, 2, 2], "field": "label", "old": "Pièce", "new": "Bureau"},
    {"change_id": "c4", "type": "modified", "kind": "room", "description": "area", "v1_item": "room-205", "v2_item": "room-205",
     "bbox_px_v1": [1, 1, 2, 2], "bbox_px_v2": [1, 1, 2, 2], "field": "area", "old": 23.5, "new": 47.0}]}


@pytest.fixture
def client(schema_url, tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    rev = art / "revisions" / DOC
    for v in ("v1", "v2"):
        (rev / v).mkdir(parents=True)
        (rev / v / "page-1.png").write_bytes(b"\x89PNG" + v.encode())
        (rev / v / "planmap-1.json").write_text('{"items": []}')
    (rev / "truth_changes.json").write_text(json.dumps(TRUTH))
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setenv("CHANGE_SOURCE", "truth")
    from server.app import app
    with TestClient(app) as c:
        yield c


def test_feed_is_seeded_and_detail_has_sentences(client):
    feed = client.get("/api/changes").json()["changes"]
    assert len(feed) == 1 and feed[0]["type"] == "new_version"
    assert feed[0]["doc_a"] == f"{DOC}@v1" and feed[0]["summary"]["n_changes"] == 4
    assert feed[0]["summary"]["source"] == "truth"
    d = client.get(f"/api/changes/{feed[0]['id']}").json()
    assert d["source"] == "truth" and d["generated_for_demo"] is True and d["image"] == {"w": 100, "h": 200}
    assert d["v1"]["page_image"] == f"/api/docs/{DOC}/revisions/v1/page-1.png"
    ch = d["changes"]
    assert [c["n"] for c in ch] == [1, 2, 3, 4]
    assert ch[0]["sentence"] == "Wall 14 (3.1 m long) reads absent where it read present."
    assert ch[0]["v1"]["bbox_px"] == [1, 2, 3, 4] and ch[0]["v2"] is None
    assert ch[1]["sentence"] == "Door 37 (0.9 m wide) reads present where it read absent." and ch[1]["v1"] is None
    assert ch[2]["sentence"] == "The label of room 1 reads 'Bureau' where it read 'Pièce'."
    assert ch[3]["sentence"] == "The area of room 205 reads 47.0 m2 where it read 23.5 m2."


def test_seed_is_idempotent_across_restarts(client):
    from server import changes_source, db

    async def again():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            return await changes_source.seed_changes(conn)
    assert client.portal.call(again) == 0
    assert len(client.get("/api/changes").json()["changes"]) == 1


def test_revision_files_allow_list(client):
    r = client.get(f"/api/docs/{DOC}/revisions/v1/page-1.png")
    assert r.status_code == 200 and r.content == b"\x89PNGv1"
    assert client.get(f"/api/docs/{DOC}/revisions/v2/planmap-1.json").json() == {"items": []}
    assert client.get(f"/api/docs/{DOC}/revisions/v3/page-1.png").json()["status"] == "not_built"
    for bad in ("truth_changes.json", "plan.dxf", "doc.json", "page-1.png.bak"):
        assert client.get(f"/api/docs/{DOC}/revisions/v1/{bad}").status_code == 404
    assert client.get(f"/api/docs/{DOC}/revisions/..%2F/page-1.png").status_code in (404, 422)
    assert client.get(f"/api/docs/..%2Fx/revisions/v1/page-1.png").status_code in (404, 422)


def test_engine_source_is_pluggable(client, monkeypatch):
    import sys
    import types
    mod = types.ModuleType("engine.changes")
    mod.compare = lambda doc_id, d: {"image": {"w": 1, "h": 1}, "changes": [
        {"type": "modified", "kind": "room", "v1_item": "room-9", "v2_item": "room-9", "bbox_px_v1": [0, 0, 1, 1],
         "bbox_px_v2": [0, 0, 1, 1], "field": "area", "old": 10.0, "new": 12.0}]}
    monkeypatch.setitem(sys.modules, "engine.changes", mod)
    monkeypatch.setenv("CHANGE_SOURCE", "engine")
    cid = client.get("/api/changes").json()["changes"][0]["id"]
    d = client.get(f"/api/changes/{cid}").json()
    assert d["source"] == "engine" and d["changes"][0]["sentence"] == "The area of room 9 reads 12.0 m2 where it read 10.0 m2."


def test_uploads_appear_in_feed_as_new_documents(client, monkeypatch):
    monkeypatch.setenv("INGEST", "0")
    doc = client.post("/api/upload", files={"file": ("p.png", b"\x89PNG")}).json()["doc_id"]
    feed = client.get("/api/changes").json()["changes"]
    assert {e["type"] for e in feed} == {"new_version", "new_document"}
    assert feed[0]["type"] == "new_document" and feed[0]["doc_b"] == doc
