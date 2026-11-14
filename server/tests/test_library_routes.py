import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine import project_index as PI
from engine.tests.test_library_catalogue import record
from server import artifact_store, chats_routes, docs_routes, scene_edits
from server.schema import validate_answer
from server.tests.test_contract import _sse


@pytest.fixture
def library_client(tmp_path, monkeypatch):
    records = [record(n) for n in range(384)]
    records += [record("smoke", title="smoke-test-plan"), record("stress", title="stress-load-run")]
    state = {"docs": records, "answers": []}
    cid = uuid.uuid4()

    class Pool:
        async def fetchrow(self, sql, *args):
            return {"id": cid, "doc_id": None}

        async def fetch(self, sql, *args):
            return state["docs"] if "from documents" in sql else []

        async def fetchval(self, sql, *args):
            return uuid.uuid4()

        async def execute(self, sql, *args):
            state["answers"].append(json.loads(args[-1]))

    pool = Pool()

    async def get_pool():
        return pool

    async def publish(event):
        pass

    async def scene_state(pool, cid):
        return []

    async def ensure(doc_id):
        pass

    def unexpected_engine(*args, **kwargs):
        raise AssertionError("A library answer or missing selection must not call the document engine")

    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("HIDE_EMPTY_DOCS", "0")
    monkeypatch.setattr(chats_routes, "ENGINE", unexpected_engine)
    monkeypatch.setattr(chats_routes, "_real_engine", unexpected_engine)
    monkeypatch.setattr(chats_routes, "_pool", get_pool)
    monkeypatch.setattr(docs_routes, "_pool_or_503", get_pool)
    monkeypatch.setattr(chats_routes, "publish", publish)
    monkeypatch.setattr(scene_edits, "scene_state", scene_state)
    monkeypatch.setattr(artifact_store, "ensure_doc", ensure)
    PI._CACHE.clear()
    app = FastAPI()
    app.include_router(chats_routes.router)
    app.include_router(docs_routes.router)
    with TestClient(app) as client:
        yield client, state, f"/api/chats/{cid}/messages", tmp_path


def ask(client, url, question):
    response = client.post(url, json={"content": question, "doc_ids": []})
    assert response.status_code == 200
    events = _sse(response.text)
    assert events[-1][0] == "answer", events
    a = events[-1][1]
    validate_answer(a)
    return a


def test_library_count_equals_data_and_excludes_noise(library_client):
    client, state, url, _ = library_client
    data = client.get("/api/docs").json()
    assert data["total"] == 384
    answer = ask(client, url, "How many drawings are in the library?")
    assert answer["answer"]["value"] == data["total"]
    assert state["answers"] == [answer]


def test_no_document_always_asks_for_selection(library_client):
    client, state, url, _ = library_client
    state["docs"] = [state["docs"][0]]  # Even a library of one drawing does not authorize choosing it.
    answer = ask(client, url, "How many windows are there?")
    assert answer["doc_ids"] == [] and answer["answer"]["value"] is None
    assert "Which drawing" in answer["answer"]["text_md"]


def test_library_ifc_and_named_sheet_count(library_client):
    client, state, url, _ = library_client
    state["docs"] = [record(1, title="Cedar College", formats=["ifc"]),
                     record(2, title="River House pricing set", kind="pdf", pages=11)]
    answer = ask(client, url, "Which projects have IFC models?")
    assert answer["answer"]["value"] == 1 and "Cedar College" in answer["answer"]["text_md"]
    answer = ask(client, url, "How many sheets are in the River House pricing set?")
    assert answer["answer"]["value"] == 11


def test_library_search_filters_existing_index(library_client):
    client, state, url, root = library_client
    state["docs"] = [record(1, title="Public sauna plan"), record(2, title="qa-room-test")]
    for meta in state["docs"]:
        folder = root / meta["doc_id"]
        folder.mkdir()
        (folder / "doc.json").write_text(json.dumps(meta))
        (folder / "text-1.json").write_text(json.dumps({"text": "Sauna", "page": 1}))
    PI.build_all(root)
    answer = ask(client, url, "Find floor plans with a sauna.")
    assert answer["doc_ids"] == [state["docs"][0]["doc_id"]]
    assert "qa-room-test" not in answer["answer"]["text_md"]
