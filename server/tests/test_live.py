"""S-06 live sync tests: two WebSocket clients, API write -> chat.message, DB trigger -> changes.new."""
import concurrent.futures
import json
import time

import asyncpg
import pytest
from fastapi.testclient import TestClient

from server import config, live
from server.tests.test_contract import DOC, dirs  # noqa: F401  (fixture reuse)

POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8)


def recv(ws, timeout=2.0):
    """receive_json with a deadline; returns None on timeout."""
    fut = POOL.submit(ws.receive_json)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None


def recv_type(ws, typ, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = recv(ws, max(0.05, end - time.monotonic()))
        if m and m.get("type") == typ:
            return m
    return None


@pytest.fixture
def client(schema_url, dirs):  # noqa: F811
    from server.app import app
    with TestClient(app) as c:
        yield c


def test_scene_highlight_keeps_valid_labels_only(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["w1", "w2"],
                     "labels": {"w1": "1", "w2": 2, "w3": "9", "w2x": "x", "w9": "ok"}})
        m = recv_type(b, "scene.highlight")
        assert m["labels"] == {"w1": "1", "w2": "2"}
        a.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["w1"],
                     "labels": {"w1": "123456789"}})  # too long
        assert "labels" not in recv_type(b, "scene.highlight")
        a.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["w1"], "labels": "nope"})
        assert "labels" not in recv_type(b, "scene.highlight")


def test_scene_highlight_reaches_other_client(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        t0 = time.monotonic()
        a.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["window-001", "window-002"]})
        m = recv_type(b, "scene.highlight")
        assert m == {"type": "scene.highlight", "doc_id": DOC, "item_ids": ["window-001", "window-002"]}
        assert time.monotonic() - t0 < 2


def test_chat_message_event_from_api(client):
    from server import db
    from server.seed import seed_documents

    async def seed():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            await seed_documents(conn, [{"doc_id": DOC, "source": "cubicasa5k", "title": "t", "kind": "raster"}])
    client.portal.call(seed)
    chat = client.post("/api/chats", json={"doc_ids": [DOC]}).json()
    with client.websocket_connect("/ws") as w:
        t0 = time.monotonic()
        client.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many windows are there?"})
        seen = []
        end = time.monotonic() + 2
        while time.monotonic() < end and not {"chat.message", "chat.status"} <= {m["type"] for m in seen}:
            m = recv(w, 0.5)
            if m:
                seen.append(m)
        types = [m["type"] for m in seen]
        assert "chat.message" in types and "chat.status" in types
        msg = next(m for m in seen if m["type"] == "chat.message")
        assert msg["chat_id"] == chat["id"] and msg["role"] in ("user", "assistant")
        assert time.monotonic() - t0 < 2.5


def test_changes_trigger_and_doc_new(client):
    import asyncio
    with client.websocket_connect("/ws") as w:
        async def insert():
            conn = await asyncpg.connect(config.database_url())
            await conn.execute("insert into changes (doc_a, doc_b) values ('a','b')")
            await conn.close()
        asyncio.run(insert())
        assert recv_type(w, "changes.new") is not None
        client.post("/api/upload", files={"file": ("p.pdf", b"%PDF")})
        m = recv_type(w, "doc.new")
        assert m and m["doc_id"].startswith("uploads__p")


def test_ping_pong_and_keepalive(client, monkeypatch):
    monkeypatch.setattr(live, "PING_INTERVAL", 0.3)
    with client.websocket_connect("/ws") as w:
        assert recv_type(w, "ping", 2) is not None  # server keepalive
        w.send_json({"type": "ping"})
        assert recv_type(w, "pong", 2) is not None


def test_unknown_client_event_ignored(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"type": "chat.message", "chat_id": "x"})  # clients may only send scene.highlight
        assert recv_type(b, "chat.message", 0.7) is None  # relay would deliver it; keepalives are not relays


def test_ws_without_db_broadcasts_locally(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@127.0.0.1:1/none")
    from server import db
    monkeypatch.setattr(db, "_pool", None)
    from server.app import app
    with TestClient(app) as c, c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
        a.send_json({"type": "scene.highlight", "doc_id": "d", "item_ids": ["i"]})
        assert recv_type(b, "scene.highlight", 2) is not None
