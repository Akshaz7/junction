"""S-32: first bytes must reach the client before ask setup can finish."""
import asyncio
import json
import threading
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import artifact_store, changes_source, chats_routes, scene_edits, stub_engine
from server.ratelimit import RateLimitMiddleware
from server.schema import validate_answer
from server.tests.test_contract import DOC, _sse

CHAT_ID = str(uuid.uuid4())
URL = f"/api/chats/{CHAT_ID}/messages"
QUESTION = "How many windows are there?"


@pytest.fixture
def stream_setup(monkeypatch):
    state = {"calls": [], "messages": [], "answers": [], "notifications": [],
             "slow_stage": None, "slow_finished": False, "missing_chat": False}

    async def stage(name):
        state["calls"].append(name)
        if state["slow_stage"] == name:
            await asyncio.sleep(1)
            state["slow_finished"] = True

    class Pool:
        async def fetchrow(self, sql, *args):
            assert sql.startswith("select id, doc_id from chats")
            await stage("chat lookup")
            return None if state["missing_chat"] else {"id": uuid.UUID(CHAT_ID), "doc_id": DOC}

        async def fetch(self, sql, *args):
            assert "from messages" in sql
            await stage("history")
            return []

        async def fetchval(self, sql, cid, content=None):
            if "project_id" in sql:
                return None
            assert sql.startswith("insert into messages")
            role = "user" if "'user'" in sql else "assistant"
            await stage(f"create {role} message")
            mid = uuid.uuid4()
            state["messages"].append({"id": mid, "role": role, "content": content})
            return mid

        async def execute(self, sql, *args):
            assert sql.startswith("insert into answers")
            state["answers"].append(json.loads(args[-1]))

    pool = Pool()

    async def get_pool():
        await stage("pool")
        return pool

    async def visible_docs(pool):
        await stage("document lookup")
        return {DOC}

    async def ensure_doc(doc_id):
        assert doc_id == DOC
        await stage("document restoration")

    async def scene_state(pool, cid):
        await stage("scene state")
        return []

    async def load_edits(pool, cid):
        await stage("scene state")
        return []

    async def publish(event):
        await stage("publish")
        state["notifications"].append(event)

    monkeypatch.setattr(chats_routes, "_pool", get_pool)
    monkeypatch.setattr(chats_routes, "ENGINE", stub_engine.answer)
    monkeypatch.setattr(chats_routes, "publish", publish)
    monkeypatch.setattr(chats_routes, "ACTIVE", {})
    monkeypatch.setattr(changes_source, "visible_doc_ids", visible_docs)
    monkeypatch.setattr(artifact_store, "ensure_doc", ensure_doc)
    monkeypatch.setattr(scene_edits, "scene_state", scene_state)
    monkeypatch.setattr(scene_edits, "load_edits", load_edits)
    app = FastAPI()
    app.include_router(chats_routes.router)
    app.add_middleware(RateLimitMiddleware)
    with TestClient(app) as client:
        yield client, state


@pytest.mark.parametrize("slow_stage", ["history", "create user message", "document restoration", "scene state"])
def test_first_sse_status_precedes_slow_chat_setup(stream_setup, slow_stage):
    client, state = stream_setup
    state["slow_stage"] = slow_stage
    started = time.monotonic()
    with client.stream("POST", URL, json={"content": QUESTION}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        lines = response.iter_lines()
        first = []
        for line in lines:
            if not line:
                break
            first.append(line)
        assert _sse("\n".join(first)) == [("status", {"text": "Thinking…"})]
        assert time.monotonic() - started < 0.150
        assert not state["slow_finished"]
        remaining = _sse("\n".join(lines))

    assert state["slow_finished"]
    assert remaining[-1][0] == "answer"
    validate_answer(remaining[-1][1])
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert state["answers"] == [remaining[-1][1]]
    assert CHAT_ID not in chats_routes.ACTIVE


@pytest.mark.parametrize("failure", ["missing_chat", "missing_document", "database_unavailable"])
def test_validation_errors_before_first_status(stream_setup, monkeypatch, failure):
    client, state = stream_setup
    payload = {"content": QUESTION}
    expected = "chat not found"
    status = 404
    if failure == "missing_chat":
        state["missing_chat"] = True
    elif failure == "missing_document":
        payload["doc_ids"] = ["unknown"]
        expected = "document not found"
    elif failure == "database_unavailable":
        async def unavailable():
            raise chats_routes.HTTPException(503, "database unavailable")
        monkeypatch.setattr(chats_routes, "_pool", unavailable)
        expected = "database unavailable"
        status = 503

    response = client.post(URL, json=payload)
    assert response.status_code == status
    assert response.json() == {"detail": expected}
    assert not state["messages"] and not state["answers"]
    assert not state["notifications"]
    assert "document restoration" not in state["calls"]
    assert CHAT_ID not in chats_routes.ACTIVE


@pytest.mark.parametrize("failure", ["document_restoration", "engine"])
def test_sse_errors_after_first_status(stream_setup, monkeypatch, failure):
    client, state = stream_setup
    if failure == "document_restoration":
        async def broken_restore(doc_id):
            raise RuntimeError("test document restoration failure")
        monkeypatch.setattr(artifact_store, "ensure_doc", broken_restore)
        expected = "request failed: test document restoration failure"
    else:
        def broken_engine(*args):
            raise RuntimeError("test engine failure")
        monkeypatch.setattr(chats_routes, "ENGINE", broken_engine)
        expected = "engine failed: test engine failure"

    response = client.post(URL, json={"content": QUESTION})
    assert response.status_code == 200
    events = _sse(response.text)
    assert events[0] == ("status", {"text": "Thinking…"})
    assert events[-1] == ("error", {"detail": expected})
    assert not state["answers"]
    if failure != "engine":
        assert not state["messages"]
    else:
        assert state["notifications"][-1] == {"type": "chat.done", "chat_id": CHAT_ID}
    assert CHAT_ID not in chats_routes.ACTIVE


def test_first_sse_keeps_cheap_validation_before_stream(stream_setup):
    client, state = stream_setup
    assert client.post(URL, json={"content": "x" * 8001}).status_code == 413
    assert client.post("/api/chats/not-a-uuid/messages", json={"content": QUESTION}).status_code == 404
    assert client.post(URL, json={}).status_code == 422
    assert client.post(URL, json={"content": QUESTION, "doc_ids": "invalid"}).status_code == 422
    assert not state["calls"]


def test_first_sse_disconnect_during_setup_clears_active(stream_setup, monkeypatch):
    client, state = stream_setup
    publishing_user = threading.Event()

    async def slow_publish(event):
        # ACTIVE is populated just before the user-message notification.
        state["notifications"].append(event)
        if event["type"] == "chat.message":
            publishing_user.set()
            await asyncio.sleep(1)

    monkeypatch.setattr(chats_routes, "publish", slow_publish)
    with client.stream("POST", URL, json={"content": QUESTION}) as response:
        lines = response.iter_lines()
        assert next(lines) == "event: status"
        assert publishing_user.wait(timeout=1)
        assert CHAT_ID in chats_routes.ACTIVE

    assert CHAT_ID not in chats_routes.ACTIVE


def test_invalid_engine_answer_falls_back_to_plain_abstention(stream_setup, monkeypatch):
    client, state = stream_setup

    def bad_engine(question, doc_ids, *args, **kw):
        ans = stub_engine.answer(question, doc_ids)
        ans["route"] = "not-a-route"
        return ans
    monkeypatch.setattr(chats_routes, "ENGINE", bad_engine)
    response = client.post(URL, json={"content": "Which level has the largest floor area?"})
    events = _sse(response.text)
    assert not [e for e in events if e[0] == "error"]
    final = [d for n, d in events if n == "answer"][-1]
    text = final["answer"]["text_md"]
    assert final["answer"]["abstained"] and "couldn't compute that reliably" in text
    assert "schema" not in response.text.lower() and "enum" not in response.text.lower()
