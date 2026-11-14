"""S-29: client traffic is bounded and scoped; server-originated live sync remains free."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from server import db, live, ws_guard

DOC = "generated__demo"


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ws_guard, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    d = tmp_path / DOC
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"doc_id": DOC, "title": "generated for demo"}))
    (d / "page-1.png").write_bytes(b"preview")
    (d / "planmap-1.json").write_text('{"items": []}')
    (d / "scene.json").write_text(json.dumps({"doc_id": DOC, "items": {"w1": {}, "d1": {}}}))

    async def no_pool():
        return None

    monkeypatch.setattr(db, "get_pool", no_pool)
    ready = asyncio.Event()
    ready.set()
    monkeypatch.setattr(live.hub, "listening", ready)
    app = FastAPI()
    app.include_router(live.router)
    with TestClient(app) as c:
        yield c, d


def test_rolling_limits_and_one_notice_per_burst(clock):
    limit = ws_guard.InboundLimit()
    assert all(limit.accept() == (True, False) for _ in range(20))
    assert limit.accept() == (False, True)
    assert all(limit.accept() == (False, False) for _ in range(1000))
    assert len(limit.seconds) == len(limit.minutes) == 20
    for second in range(1, 10):
        clock[0] = 100.0 + second
        assert all(limit.accept() == (True, False) for _ in range(20))
    clock[0] = 110.0
    assert limit.accept() == (False, True)  # minute cap, even after second window drains
    assert limit.accept() == (False, False)
    clock[0] = 160.0
    assert limit.accept() == (True, False)  # oldest 20 expire exactly at the boundary


def test_ws_throttles_per_connection(client, clock):
    c, _ = client
    with c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
        for _ in range(20):
            a.send_json({"type": "ping"})
            assert a.receive_json() == {"type": "pong"}
        a.send_json({"type": "ping"})
        assert a.receive_json() == {"type": "error", "code": "rate_limited"}
        b.send_json({"type": "ping"})
        assert b.receive_json() == {"type": "pong"}
        clock[0] += 1
        a.send_json({"type": "ping"})
        assert a.receive_json() == {"type": "pong"}


def test_ws_minute_limit(client, clock):
    c, _ = client
    with c.websocket_connect("/ws") as ws:
        for _ in range(10):
            for _ in range(20):
                ws.send_json({"type": "ping"})
                assert ws.receive_json() == {"type": "pong"}
            clock[0] += 1
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "error", "code": "rate_limited"}
        clock[0] += 60
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize("binary", [False, True])
def test_oversize_frames_close_with_1009(client, binary):
    c, _ = client
    with c.websocket_connect("/ws") as ws:
        if binary:
            ws.send_bytes(b"x" * (64 * 1024 + 1))
        else:
            ws.send_text("é" * (32 * 1024 + 1))  # UTF-8 bytes, not characters
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1009


def test_size_boundary_and_allowlist(client):
    c, _ = client
    with c.websocket_connect("/ws") as ws:
        ping = json.dumps({"type": "ping"})
        ws.send_text(ping + " " * (64 * 1024 - len(ping)))
        assert ws.receive_json() == {"type": "pong"}
        for event in ("chat.message", "chat.status", "advisor.cards", "doc.new", "scene.state", "scene.command", "unknown", [], {}):
            ws.send_json({"type": event, "doc_id": DOC, "item_ids": ["w1"]})
        ws.send_text("invalid JSON")
        ws.send_json([])
        ws.send_json({"type": "pong"})
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}  # no unknown event was echoed


@pytest.mark.parametrize("event", ["scene.highlight", "scene.edit"])
@pytest.mark.parametrize("doc_id", ["unlisted__doc", "../escape", "..", None, [DOC]])
def test_bad_doc_id_is_rejected(client, event, doc_id):
    c, _ = client
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"type": event, "doc_id": doc_id, "op": "hide", "item_ids": ["w1"]})
        assert ws.receive_json()["type"] == "scene.error"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize("op", ["highlight", "hide", "restore", "reset", "isolate"])
def test_commands_validate_manifest_and_keep_event_shape(client, op):
    c, _ = client
    with c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
        a.send_json({"type": "scene.edit", "doc_id": DOC, "op": op, "item_ids": ["foreign"]})
        assert a.receive_json()["type"] == "scene.error"
        a.send_json({"type": "scene.edit", "doc_id": DOC, "op": op, "item_ids": ["w1"], "edit_id": "demo-edit"})
        event = b.receive_json()
        assert event == {"type": "scene.edit", "doc_id": DOC, "op": op, "item_ids": ["w1"], "edit_id": "demo-edit", "ts": event["ts"]}


def test_highlight_labels_missing_manifest_and_empty_reset(client):
    c, d = client
    with c.websocket_connect("/ws") as ws:
        for ids in (["w1", "foreign"], "w1", [1], ["w1"] * 501):
            ws.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ids})
            assert ws.receive_json()["type"] == "scene.error"
        ws.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["w1"], "labels": {"w1": "W1", "foreign": "X"}})
        assert ws.receive_json() == {"type": "scene.highlight", "doc_id": DOC, "item_ids": ["w1"], "labels": {"w1": "W1"}}
        ws.send_json({"type": "scene.edit", "doc_id": DOC, "op": "reset"})
        assert ws.receive_json()["item_ids"] == []
        (d / "scene.json").unlink()
        ws.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["not-yet-extruded"]})
        assert ws.receive_json()["item_ids"] == ["not-yet-extruded"]


def test_existing_unreadable_manifest_is_rejected(client):
    c, d = client
    (d / "scene.json").write_text("broken")
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["w1"]})
        assert ws.receive_json()["type"] == "scene.error"


def test_listed_docs_and_database_only_manifest(client, monkeypatch):
    c, d = client
    (d / "scene.json").unlink()

    class Pool:
        async def fetch(self, query):
            if "from documents" in query:
                return [{"doc_id": DOC}, {"doc_id": "empty__doc"}]
            return [{"doc_id": DOC}, {"doc_id": "unlisted__doc"}]

        async def fetchval(self, query, doc_id):
            return json.dumps({"items": {"d1": {}}}).encode()

    async def pool():
        return Pool()

    monkeypatch.setattr(db, "get_pool", pool)
    monkeypatch.setenv("HIDE_EMPTY_DOCS", "1")
    from server import artifact_store
    monkeypatch.setattr(artifact_store, "_servable_cache", (0.0, set()))
    with c.websocket_connect("/ws") as ws:
        for doc_id, ids in ((DOC, ["w1"]), ("empty__doc", []), ("unlisted__doc", [])):
            ws.send_json({"type": "scene.highlight", "doc_id": doc_id, "item_ids": ids})
            assert ws.receive_json()["type"] == "scene.error"
        ws.send_json({"type": "scene.highlight", "doc_id": DOC, "item_ids": ["d1"]})
        assert ws.receive_json()["item_ids"] == ["d1"]
