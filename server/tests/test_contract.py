"""S-03 contract tests for every tier-1 endpoint of CONTRACT 5.9 (DB ones skip without Postgres)."""
import json

import pytest
from fastapi.testclient import TestClient

from server import stub_engine
from server.schema import validate_answer

DOC = "cubicasa5k__colorful-11397"


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    art, res = tmp_path / "artifacts", tmp_path / "results"
    (art / DOC).mkdir(parents=True)
    (res / "bench").mkdir(parents=True)
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setenv("RESULTS_DIR", str(res))
    return art, res


@pytest.fixture
def client(schema_url, dirs):
    from server.app import app
    with TestClient(app) as c:
        from server import db
        from server.seed import seed_documents

        async def seed():
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                await seed_documents(conn, [{"doc_id": DOC, "source": "cubicasa5k", "title": "Colorful 11397",
                                             "kind": "raster", "formats": ["png"], "pages": 1, "files": {}}])
        c.portal.call(seed)  # seed the fixture document on the app's own loop
        yield c


def _sse(text: str):
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if ev:
            events.append((ev, json.loads(data)))
    return events


def test_stub_answer_is_contract_valid():
    a = stub_engine.answer("How many windows are there?", [DOC], None)
    validate_answer(a)
    assert a["answer"]["value"] == 13 and len(a["evidence"]["boxes"]) == 13
    assert all(t.get("stub") for t in a["trace"])
    b = stub_engine.answer("What colour is the sky?", [DOC], None)
    validate_answer(b)
    assert b["answer"]["abstained"] is True


def test_schema_rejects_bad_answer():
    import jsonschema
    a = stub_engine.answer("how many windows", [DOC], None)
    del a["evidence"]
    with pytest.raises(jsonschema.ValidationError):
        validate_answer(a)


def test_docs_endpoints(client):
    r = client.get("/api/docs")
    assert r.status_code == 200 and r.json()["total"] == 1
    assert client.get(f"/api/docs/{DOC}").json()["doc_id"] == DOC
    assert client.get("/api/docs/nope").status_code == 404


def test_page_planmap_scene_files(client, dirs):
    art, _ = dirs
    for url in (f"/api/docs/{DOC}/pages/1/image", f"/api/docs/{DOC}/planmap/1", f"/api/docs/{DOC}/scene",
                f"/api/docs/{DOC}/files/scene.glb"):
        r = client.get(url)
        assert r.status_code == 404 and r.json()["status"] == "not_built"
    (art / DOC / "page-1.png").write_bytes(b"\x89PNG fake")
    (art / DOC / "planmap-1.json").write_text('{"items": []}')
    (art / DOC / "scene.json").write_text('{"doc_id": "x"}')
    (art / DOC / "scene.glb").write_bytes(b"glb")
    r = client.get(f"/api/docs/{DOC}/pages/1/image")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get(f"/api/docs/{DOC}/planmap/1").json() == {"items": []}
    assert client.get(f"/api/docs/{DOC}/scene").json() == {"doc_id": "x"}
    assert client.get(f"/api/docs/{DOC}/files/scene.glb").content == b"glb"
    assert client.get(f"/api/docs/{DOC}/files/secret.txt").status_code == 404
    assert client.get("/api/docs/..%2Fetc/scene").status_code in (400, 404)


def test_upload(client, dirs, monkeypatch):
    art, _ = dirs
    monkeypatch.setenv("INGEST", "0")
    r = client.post("/api/upload", files={"file": ("My Plan.pdf", b"%PDF-1.4 fake")})
    assert r.status_code == 200
    doc_id = r.json()["doc_id"]
    assert r.json()["status"] == "stored"
    assert client.get(f"/api/docs/{doc_id}/ingest").json()["status"] == "none"
    assert doc_id.startswith("uploads__my-plan")
    assert any((art / "uploads").iterdir())
    d = client.get(f"/api/docs/{doc_id}").json()
    assert d["kind"] == "pdf" and d["source"] == "uploads"
    assert client.post("/api/upload", files={"file": ("x.exe", b"x")}).status_code == 415


def test_chats_and_streamed_question(client, monkeypatch):
    from server import chats_routes, stub_engine
    monkeypatch.setattr(chats_routes, "ENGINE", stub_engine.answer)  # stable numbers for the stream contract
    assert client.get("/api/chats").json() == {"chats": []}
    chat = client.post("/api/chats", json={"doc_ids": [DOC], "title": "t"}).json()
    assert chat["doc_id"] == DOC
    assert client.post("/api/chats", json={"doc_ids": ["nope"]}).status_code == 404
    assert [c["id"] for c in client.get("/api/chats").json()["chats"]] == [chat["id"]]

    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many windows are there?"})
    assert r.status_code == 200
    events = _sse(r.text)
    kinds = [k for k, _ in events]
    assert "status" in kinds and "trace" in kinds and kinds[-1] == "answer"
    assert kinds.index("status") < kinds.index("trace") < kinds.index("answer")
    ans = events[-1][1]
    validate_answer(ans)
    assert ans["answer"]["value"] == 13

    got = client.get(f"/api/chats/{chat['id']}").json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["answer"]["answer_id"] == ans["answer_id"]
    assert client.get("/api/chats/not-a-uuid").status_code == 404
    assert client.post("/api/chats/00000000-0000-0000-0000-000000000000/messages",
                       json={"content": "hi"}).status_code == 404


def test_real_engine_answer_through_api(client, monkeypatch):
    """Default engine is the real one: no stub marker, valid answer object, abstains without data."""
    from server import chats_routes
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    chat = client.post("/api/chats", json={"doc_ids": [DOC]}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many windows are there?"})
    events = _sse(r.text)
    assert events[-1][0] == "answer"
    ans = events[-1][1]
    validate_answer(ans)
    assert "stub" not in json.dumps(ans["trace"]).lower()


def test_changes_empty(client):
    body = client.get("/api/changes").json()
    assert body["changes"] == [] and body["groups"] == [] and body["checked_at"]
    assert client.get("/api/changes/00000000-0000-0000-0000-000000000000").status_code == 404


def test_bench_summaries_only_tag_and_list(client, dirs):
    import os
    _, res = dirs
    b = res / "bench"
    assert client.get("/api/bench").json() == {"benches": []}
    old = b / "fake200.json"
    old.write_text(json.dumps({"set": "sample200", "tag": "fake200", "fake": True, "totals": {"n": 200}, "cells": []}))
    new = b / "real50.json"
    new.write_text(json.dumps({"set": "sample50", "tag": "real50", "fake": False, "totals": {"n": 50}, "cells": []}))
    os.utime(old, (1_000_000, 1_000_000))
    (b / "real50.rows.jsonl").write_text('{"row": 1}\n')  # newest file, must be ignored
    r = client.get("/api/bench/latest").json()
    assert r["file"] == "real50.json" and r["tag"] == "real50" and r["data"]["totals"] == {"n": 50}
    one = client.get("/api/bench/latest", params={"tag": "fake200"}).json()
    assert one["data"]["set"] == "sample200" and one["data"]["fake"] is True
    assert client.get("/api/bench/latest", params={"tag": "nope"}).status_code == 404
    assert client.get("/api/bench/latest", params={"tag": "real50.rows"}).status_code == 404
    lst = client.get("/api/bench").json()["benches"]
    assert [x["tag"] for x in lst] == ["real50", "fake200"]
    assert lst[1]["set"] == "sample200" and lst[1]["fake"] is True and lst[0]["mtime"] > lst[1]["mtime"]


def test_bench_and_costs(client, dirs):
    _, res = dirs
    assert client.get("/api/bench/latest").status_code == 404
    (res / "bench" / "run1.json").write_text('{"accuracy": 0.9}')
    r = client.get("/api/bench/latest").json()
    assert r["file"] == "run1.json" and r["data"] == {"accuracy": 0.9}
    assert client.get("/api/costs").json()["total_usd"] == 0
    (res / "costs.jsonl").write_text(
        '{"provider":"gemini","task":"read_drawing","cost_usd":0.01}\n'
        '{"provider":"gemini","task":"verify_item","cost_usd":0.02}\n'
        '{"provider":"runware","task":"read_drawing","cost_usd":0.005}\n')
    c = client.get("/api/costs").json()
    assert c["calls"] == 3 and c["total_usd"] == 0.035
    assert c["by_provider"]["gemini"] == {"calls": 2, "usd": 0.03}
    assert c["by_task"]["read_drawing"]["calls"] == 2


def test_elements_planmap_page_via_files_route(client, dirs):
    art, _ = dirs
    for n in ("elements.json", "planmap-2.json", "page-2.png"):
        assert client.get(f"/api/docs/{DOC}/files/{n}").json()["status"] == "not_built"
    (art / DOC / "elements.json").write_text('{"elements": []}')
    (art / DOC / "planmap-2.json").write_text('{"items": []}')
    (art / DOC / "page-2.png").write_bytes(b"\x89PNG")
    assert client.get(f"/api/docs/{DOC}/files/elements.json").json() == {"elements": []}
    assert client.get(f"/api/docs/{DOC}/files/planmap-2.json").json() == {"items": []}
    assert client.get(f"/api/docs/{DOC}/files/page-2.png").content == b"\x89PNG"
    for bad in ("page-x.png", "planmap-1.json.bak", "..%2Felements.json", "elements.json%00"):
        assert client.get(f"/api/docs/{DOC}/files/{bad}").status_code in (400, 404, 422)
    assert client.get("/api/docs/..%2Fetc/files/elements.json").status_code in (400, 404)


def test_upload_starts_ingestion_when_available(client, dirs, monkeypatch):
    from server import files_routes
    started = []

    async def fake(doc_id):
        started.append(doc_id)
    monkeypatch.setattr(files_routes, "ingestion_available", lambda: True)
    monkeypatch.setattr(files_routes, "_ingest", fake)
    r = client.post("/api/upload", files={"file": ("p.png", b"\x89PNG")})
    assert r.json()["status"] == "ingesting"


def test_engine_impl_flag(monkeypatch):
    from server import chats_routes, stub_engine
    monkeypatch.setenv("ENGINE_IMPL", "stub")
    assert chats_routes._pick_engine() is stub_engine.answer
    monkeypatch.setenv("ENGINE_IMPL", "real")
    assert chats_routes._pick_engine() is chats_routes._real_engine
    monkeypatch.delenv("ENGINE_IMPL")
    assert chats_routes._pick_engine() is chats_routes._real_engine  # real is the default
    import engine.answer as ea
    assert callable(ea.answer)


AC20 = "ifc_bench__ac20-arc"


def test_s04_ac20_doors_api_equals_direct_engine(client, monkeypatch):
    """S-04 done test: the API answer is the direct engine answer (77 doors on ac20)."""
    pytest.importorskip("engine.answer")
    from engine.answer import answer as direct
    from server import chats_routes, db
    from server.seed import seed_documents
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ARTIFACTS_DIR", str(root / "artifacts"))  # engine needs the real scene data
    monkeypatch.setenv("RESULTS_DIR", str(root / "results"))
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    q = "How many doors are there?"
    want = direct(q, [AC20], None)

    async def seed():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            await seed_documents(conn, [{"doc_id": AC20, "source": "ifc_bench", "title": "AC20", "kind": "ifc",
                                         "formats": ["ifc"], "pages": 1, "files": {}}])
    client.portal.call(seed)
    chat = client.post("/api/chats", json={"doc_ids": [AC20]}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": q, "doc_ids": [AC20]})
    got = _sse(r.text)[-1][1]
    validate_answer(got)
    assert got["answer"] == want["answer"]
    assert [c for c in got["citations"]] == [c for c in want["citations"]]
    assert "77" in json.dumps(got["answer"])


def test_e12_linked_item_and_tag_lookup(client, monkeypatch):
    """E-12 done test: an ac20 door resolves by item id and by tag with storey, type and properties."""
    pytest.importorskip("engine.linked")
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ARTIFACTS_DIR", str(root / "artifacts"))
    from engine import linked
    from engine.solvers.data import load_doc
    doc = load_doc(AC20, root / "artifacts")
    door = next(i for i in doc.items if i.kind == "door" and i.type_name and i.storey)
    r = client.get(f"/api/docs/{AC20}/items/{door.item_id}")
    assert r.status_code == 200
    j = r.json()
    assert j["item_id"] == door.item_id and j["kind"] == "door" and j["storey"] == door.storey
    assert j["type_name"] == door.type_name and j["tag"] and isinstance(j["props"], dict) and j["props"]
    assert j["places"] and all(p["doc_id"] == AC20 and "bbox_px" in p and "page" in p for p in j["places"])
    t = client.get(f"/api/docs/{AC20}/tags/{j['tag']}")
    assert t.status_code == 200 and t.json()["item_id"] == door.item_id
    assert client.get(f"/api/docs/{AC20}/items/nope-123").status_code == 404
    assert client.get(f"/api/docs/{AC20}/items/{j['tag']}").status_code == 404  # tags are not item ids
    assert client.get(f"/api/docs/{AC20}/tags/ZZ999").status_code == 404
    assert client.get("/api/docs/no_such_doc/items/x").status_code == 404
