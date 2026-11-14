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


def test_upload(client, dirs):
    art, _ = dirs
    r = client.post("/api/upload", files={"file": ("My Plan.pdf", b"%PDF-1.4 fake")})
    assert r.status_code == 200
    doc_id = r.json()["doc_id"]
    assert doc_id.startswith("uploads__my-plan")
    assert any((art / "uploads").iterdir())
    d = client.get(f"/api/docs/{doc_id}").json()
    assert d["kind"] == "pdf" and d["source"] == "uploads"
    assert client.post("/api/upload", files={"file": ("x.exe", b"x")}).status_code == 415


def test_chats_and_streamed_question(client):
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


def test_changes_empty(client):
    assert client.get("/api/changes").json() == {"changes": []}
    assert client.get("/api/changes/00000000-0000-0000-0000-000000000000").status_code == 404


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
