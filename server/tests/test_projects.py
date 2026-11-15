"""F-PROJ-ENGINE: projects API, roles, overview, project chats, demo seeding (needs local Postgres and the real artifacts)."""
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import chats_routes, config
from server.tests.test_contract import _sse

AC = "ifc_bench__ac20-arc"
VAR = "ifc_models__kit-institute-ac20-institute-var-2"
PLAN = VAR + "-plan-03-1-obergeschoss"
ELEV = VAR + "-elevation-east"
FZK = "ifc_bench__fzk-house-arc"
REGISTRY = Path(__file__).resolve().parents[2] / "artifacts" / "registry.jsonl"
NEEDED = (AC, VAR, PLAN, ELEV, FZK, "ifc_models__kit-fzk-haus-ac20-fzk-haus")


def _rows():
    if not REGISTRY.exists():
        pytest.skip("no artifacts/registry.jsonl")
    want = set(NEEDED) | {json.loads(l)["doc_id"] for l in REGISTRY.read_text().splitlines()
                          if l.strip() and ("institute" in l.lower() or "fzk" in l.lower())}
    rows = [json.loads(l) for l in REGISTRY.read_text().splitlines() if l.strip()]
    got = [r for r in rows if r["doc_id"] in want]
    if not {AC, VAR} <= {r["doc_id"] for r in got}:
        pytest.skip("demo documents not in the registry")
    return got


@pytest.fixture
def client(schema_url, monkeypatch):
    monkeypatch.setenv("INGEST", "0")
    monkeypatch.setenv("SEED_PROJECTS", "0")
    monkeypatch.setenv("RATE_LIMIT", "0")
    from server.app import app
    with TestClient(app) as c:
        from server import db
        from server.seed import seed_documents
        rows = _rows()

        async def seed():
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                await seed_documents(conn, rows)
        c.portal.call(seed)
        yield c


def roles(p):
    return {d["doc_id"]: d for d in p["docs"]}


def test_project_crud_and_roles(client):
    r = client.post("/api/projects", json={"name": "  Site   A ", "doc_ids": [AC, VAR, PLAN, ELEV]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "Site A" and p["demo"] is False
    d = roles(p)
    assert d[AC]["role"] == "model" and d[VAR]["role"] == "model"
    assert d[PLAN]["role"] == "plan" and d[PLAN]["level"]
    assert d[ELEV]["role"] == "elevation" and d[ELEV]["level"] is None
    assert all(x["role_source"] == "auto" and x["thumb_url"] for x in p["docs"])
    pid = p["id"]
    assert client.get("/api/projects").json()["projects"][0]["doc_count"] == 4
    assert client.patch(f"/api/projects/{pid}", json={"name": "Site B"}).json()["name"] == "Site B"
    p = client.patch(f"/api/projects/{pid}/docs/{ELEV}", json={"role": "detail"}).json()
    assert roles(p)[ELEV]["role"] == "detail" and roles(p)[ELEV]["role_source"] == "user"
    assert client.patch(f"/api/projects/{pid}/docs/{ELEV}", json={"role": "nonsense"}).status_code == 422
    assert client.patch(f"/api/projects/{pid}/docs/nope", json={"role": "plan"}).status_code == 404
    # a user's role survives re-reading the project
    assert roles(client.get(f"/api/projects/{pid}").json())[ELEV]["role"] == "detail"
    p = client.delete(f"/api/projects/{pid}/docs/{ELEV}").json()
    assert ELEV not in roles(p)
    p = client.post(f"/api/projects/{pid}/docs", json={"doc_ids": [FZK]}).json()
    assert roles(p)[FZK]["role"] == "model"
    assert client.post(f"/api/projects/{pid}/docs", json={"doc_ids": ["no__such-doc"]}).status_code == 404
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.get("/api/projects/not-a-uuid").status_code == 404
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422


def test_overview_matches_engine_and_is_cached(client):
    pid = client.post("/api/projects", json={"name": "AC", "doc_ids": [AC, VAR, PLAN, ELEV]}).json()["id"]
    o = client.get(f"/api/projects/{pid}/overview").json()
    assert o["project_id"] == pid
    t = o["totals"]
    assert (t["storeys"], t["rooms"], t["doors"], t["windows"]) == (5, 82, 77, 206)   # the variant model and the sheet are NOT added again
    assert t["floor_area_m2"] == pytest.approx(1939.38, abs=0.01)
    assert {l["level"] for l in o["levels"]} >= {"Erdgeschoss", "1. Obergeschoss"}
    assert {c["doc_id"] for c in o["coverage"]} == {AC, VAR, PLAN, ELEV}
    assert all(c["confidence_label"] in ("Verified", "Cross-checked", "Estimate", "Partial", "Processing", "Not readable") for c in o["coverage"])
    assert isinstance(o["agreements"], list) and isinstance(o["mistakes"], list)
    again = client.get(f"/api/projects/{pid}/overview").json()
    assert again == o


@pytest.mark.skip(reason="auto demo projects retired for judging; curated projects are kept by hand")
def test_demo_seed_idempotent_and_protected(client):
    from server import db
    from server.projects_routes import seed_demo_projects

    async def run():
        return await seed_demo_projects(await db.get_pool())
    first = client.portal.call(run)
    assert first.get("AC20 Institute (demo project)", 0) >= 2
    assert all(v == 0 for v in client.portal.call(run).values())
    ps = client.get("/api/projects").json()["projects"]
    demos = [p for p in ps if p["demo"]]
    assert len({p["name"] for p in demos}) == len(demos) and any(p["name"].startswith("AC20 Institute") for p in demos)
    d = next(p for p in demos if p["name"].startswith("AC20 Institute"))
    assert client.delete(f"/api/projects/{d['id']}").status_code == 409
    full = client.get(f"/api/projects/{d['id']}").json()
    assert AC in roles(full) and VAR in roles(full)


def test_project_chat_uses_all_project_docs(client, monkeypatch):
    seen = {}

    def engine(question, doc_ids, on_event, **kw):
        from server import stub_engine
        seen["doc_ids"] = list(doc_ids)
        return stub_engine.answer(question, doc_ids, on_event)
    monkeypatch.setattr(chats_routes, "ENGINE", engine)
    monkeypatch.setattr(chats_routes, "_real_engine", engine)
    pid = client.post("/api/projects", json={"name": "Chat", "doc_ids": [AC, FZK]}).json()["id"]
    chat = client.post("/api/chats", json={"project_id": pid, "title": "t"}).json()
    assert chat["project_id"] == pid
    assert client.post("/api/chats", json={"project_id": str(uuid.uuid4())}).status_code == 404
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors in total?"})
    assert r.status_code == 200 and any(e == "answer" for e, _ in _sse(r.text))
    assert seen["doc_ids"] == [AC, FZK]
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors?", "doc_ids": [FZK]})
    assert seen["doc_ids"] == [FZK]            # an explicit selection wins
    assert client.get(f"/api/chats/{chat['id']}").json()["project_id"] == pid
    plain = client.post("/api/chats", json={}).json()
    assert "project_id" not in plain


def test_upload_into_project(client):
    pid = client.post("/api/projects", json={"name": "Up"}).json()["id"]
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    r = client.post(f"/api/projects/{pid}/upload", files={"file": ("site photo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_id"].startswith("uploads__") and body["doc_id"] in roles(body["project"])
    assert client.post(f"/api/projects/{pid}/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post(f"/api/projects/{uuid.uuid4()}/upload", files={"file": ("a.png", buf.getvalue(), "image/png")}).status_code == 404


def test_hidden_doc_is_skipped_not_404(client, monkeypatch):
    """F-PROJVISIBLE: a project doc that /api/docs hides is skipped with a note; project chat still answers."""
    from server import changes_source
    seen = {}

    def engine(question, doc_ids, on_event, **kw):
        from server import stub_engine
        seen["doc_ids"] = list(doc_ids)
        return stub_engine.answer(question, doc_ids, on_event)
    monkeypatch.setattr(chats_routes, "ENGINE", engine)
    monkeypatch.setattr(chats_routes, "_real_engine", engine)
    pid = client.post("/api/projects", json={"name": "Hidden", "doc_ids": [AC, FZK]}).json()["id"]
    real = changes_source.visible_doc_ids

    async def hide_fzk(pool):
        return {d for d in await real(pool) if d != FZK}
    monkeypatch.setattr(changes_source, "visible_doc_ids", hide_fzk)
    proj = client.get(f"/api/projects/{pid}").json()
    assert [d["doc_id"] for d in proj["docs"]] == [AC] and proj["skipped_doc_ids"] == [FZK]
    chat = client.post("/api/chats", json={"project_id": pid, "title": "t"}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors in total?"})
    assert r.status_code == 200 and any(e == "answer" for e, _ in _sse(r.text))
    assert seen["doc_ids"] == [AC]
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors?", "doc_ids": [AC, FZK]})
    assert r.status_code == 200 and seen["doc_ids"] == [AC]
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors?", "doc_ids": [FZK]})
    assert r.status_code == 404
