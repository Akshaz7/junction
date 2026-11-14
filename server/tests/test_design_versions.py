"""Saving 3D edits as a new design version, and comparing it with the original (and earlier versions) via /api/changes."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from server import config

DOC = "ifc_bench__ac20-arc"
RASTER = "cubicasa5k__colorful-11397"
DOOR = "0YIVuBlyXF3PI_fXw2b_vJ"      # Tür-015, tag D30 (page 2)
WINDOW = "0$6TgsobP9PPnqNXqQeskc"    # Fenster-005, tag W81 (page 2)
REAL = config.REPO / "artifacts"


@pytest.fixture
def client(schema_url, tmp_path, monkeypatch):
    if not (REAL / DOC / "planmap-2.json").is_file():
        pytest.skip("ac20 artifacts unavailable")
    art = tmp_path / "artifacts"
    art.mkdir()
    for d in (DOC, RASTER):
        if (REAL / d).is_dir():
            (art / d).symlink_to((REAL / d).resolve())  # read-only use; versions live in the DB
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setenv("HIDE_EMPTY_DOCS", "0")
    from server import docmeta_store
    docmeta_store._cache.clear()
    from server.app import app
    with TestClient(app) as c:
        from server import db
        from server.seed import seed_documents

        async def seed():
            pool = await db.get_pool()
            await seed_documents(pool, [{"doc_id": DOC, "source": "ifc_bench", "title": "AC20", "kind": "ifc"},
                                        {"doc_id": RASTER, "source": "cubicasa5k", "title": "Plan 11397", "kind": "raster"}])
        c.portal.call(seed)
        yield c


def _save(c, doc=DOC, **body):
    return c.post(f"/api/docs/{doc}/versions", json=body)


def test_save_creates_linked_version_and_original_is_kept(client):
    planmap = (REAL / DOC / "planmap-2.json").read_bytes()
    r = _save(client, removed=[DOOR], moved={WINDOW: [1.0, 0.0]}, materials={}, chat_id="c-1")
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["n"] == 1 and v["parent"] == 0 and v["created"] and v["edited"] and "generated" in v["generated"]
    assert v["label"].startswith("Edited version 1") and v["change_id"] == f"dv:{DOC}:0-1"
    assert v["counts"] == {"removed": 1, "added": 0, "moved": 1, "material": 0}
    # same snapshot again: no duplicate version
    again = _save(client, removed=[DOOR], moved={WINDOW: [1.0, 0.0]}, materials={}).json()
    assert again["n"] == 1 and not again["created"]
    # a second save made from version 1 links to it
    v2 = _save(client, removed=[], moved={WINDOW: [1.0, 0.0]}, materials={}, parent=1).json()
    assert v2["n"] == 2 and v2["parent"] == 1 and v2["counts"]["added"] == 1
    assert v2["change_id"] == f"dv:{DOC}:1-2" and v2["compare_url"] == f"#/compare?change=dv:{DOC}:0-2"  # link: vs the original
    listed = client.get(f"/api/docs/{DOC}/versions").json()["versions"]
    assert [x["n"] for x in listed] == [0, 1, 2] and listed[0]["label"] == "Original" and listed[2]["parent"] == 1
    assert (REAL / DOC / "planmap-2.json").read_bytes() == planmap  # the original is never overwritten
    # empty / unknown edits are refused
    assert _save(client, removed=[], moved={}).status_code == 400
    assert _save(client, removed=["not-an-item"]).status_code == 400
    assert client.post(f"/api/docs/{DOC}/versions", json={"moved": {"x": "bad"}}).status_code == 400


def test_compare_with_original_lists_removed_and_moved_items(client):
    _save(client, removed=[DOOR], moved={WINDOW: [1.0, 0.0]})
    feed = client.get("/api/changes").json()["changes"]
    e = next(x for x in feed if x["id"] == f"dv:{DOC}:0-1")
    s = e["summary"]
    assert e["type"] == "new_version" and e["doc_a"] == e["doc_b"] == DOC and s["series_id"] == f"design:{DOC}"
    assert s["n_changes"] == 2 and s["version_a"] == "Original" and s["index_a"] == 0 and s["index_b"] == 1
    assert s["pair_prefix"] == f"dv:{DOC}:" and s["edited"] and "generated_for_demo" not in s
    assert s["headline"].endswith("1 removed, 1 moved.")

    d = client.get(f"/api/changes/dv:{DOC}:0-1").json()
    assert d["source"] == "edit-diff" and d["page"] == 2 and d["image"] == {"w": 2400, "h": 1046}
    assert d["counts"] == {"removed": 1, "added": 0, "moved": 1, "material": 0} and set(d["item_ids"]) == {DOOR, WINDOW}
    door, win = d["changes"]
    assert door["type"] == "removed" and door["item_id"] == DOOR and door["tag"] == "D30" and door["v2"] is None
    assert door["v1"] == {"item_id": DOOR, "bbox_px": [802.3, 416.4, 857.5, 422.0]}
    assert win["action"] == "moved" and win["type"] == "modified" and win["v2"]["bbox_px"][0] > win["v1"]["bbox_px"][0]
    assert d["v1"]["page_image"] == f"/api/docs/{DOC}/pages/2/image" and d["v1"]["label"] == "Original"
    assert d["v2"]["page_image"] == f"/api/docs/{DOC}/versions/1/pages/2/image" and d["v2"]["edited"]
    # the edited page renders: same size as the original, pixels differ where the door was
    from PIL import Image
    img = client.get(d["v2"]["page_image"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    new = Image.open(io.BytesIO(img.content)).convert("RGB")
    old = Image.open(REAL / DOC / "page-2.png").convert("RGB")
    assert new.size == old.size and new.tobytes() != old.tobytes()
    # reverse and unknown pairs
    rev = client.get(f"/api/changes/dv:{DOC}:1-0").json()
    assert [c["type"] for c in rev["changes"]] == ["added", "modified"]
    assert client.get(f"/api/changes/dv:{DOC}:0-9").status_code == 404
    assert client.get(f"/api/changes/dv:{DOC}:1-1").status_code == 404


def test_any_two_versions_and_raster_doc(client):
    _save(client, removed=[DOOR])
    _save(client, removed=[DOOR], moved={WINDOW: [0.0, -0.5]}, parent=1)
    d = client.get(f"/api/changes/dv:{DOC}:1-2").json()
    assert [(c["action"], c["item_id"]) for c in d["changes"]] == [("moved", WINDOW)]
    assert "0.5 m north" in d["changes"][0]["sentence"]
    d = client.get(f"/api/changes/dv:{DOC}:0-2").json()
    assert {c["action"] for c in d["changes"]} == {"removed", "moved"}
    if not (REAL / RASTER).is_dir():
        pytest.skip("raster artifacts unavailable")
    r = _save(client, doc=RASTER, removed=["door-001"]).json()
    d = client.get(f"/api/changes/{r['change_id']}").json()
    scene = json.loads((REAL / RASTER / "scene.json").read_text()) if (REAL / RASTER / "scene.json").is_file() else {}
    plan = json.loads((REAL / RASTER / "planmap-1.json").read_text())
    door = next(it for it in plan["items"] if it["item_id"] == "door-001")
    tag = scene.get("items", {}).get("door-001", {}).get("tag") or door.get("props", {}).get("tag")
    assert [(c["item_id"], c["tag"], c["type"]) for c in d["changes"]] == [("door-001", tag, "removed")]
    assert json.dumps(d).count("generated_for_demo") == 0
