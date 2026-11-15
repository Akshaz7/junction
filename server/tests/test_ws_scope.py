"""F-WSSCOPE: chat.* live events reach only sockets subscribed to that chat; doc.* stay global."""
import asyncio
import json

from server import live
from server.tests.test_contract import dirs  # noqa: F401


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


def _hub(**scopes):
    hub = live.Hub()
    socks = {name: FakeWS() for name in (*scopes, "legacy")}
    hub.sockets = set(socks.values())
    for name, scope in scopes.items():
        hub.scopes[socks[name]] = scope
    return hub, socks


def scope(ids=(), summaries=False):
    return {"chat_ids": set(ids), "summaries": summaries}


def test_wants_rules():
    delta = {"type": "chat.delta", "chat_id": "A", "text": "x"}
    assert live.wants(None, delta)                                        # legacy client: everything
    assert live.wants(scope(["A"]), delta) and not live.wants(scope(["B"]), delta)
    msg = {"type": "chat.message", "chat_id": "A", "role": "user"}
    assert live.wants(scope([], True), msg) and not live.wants(scope([], True), delta)
    assert not live.wants(scope(), msg)
    for e in ({"type": "doc.new", "doc_id": "d"}, {"type": "scene.edit", "doc_id": "d"}, {"type": "pair.joined", "proof": "p"}):
        assert live.wants(scope(), e)


def test_broadcast_filters_per_socket():
    async def run():
        hub, s = _hub(mine=scope(["A"]), other=scope(["B"]), overview=scope([], True), nothing=scope())
        await hub.broadcast({"type": "chat.delta", "chat_id": "A", "text": "hi"})
        await hub.broadcast({"type": "chat.message", "chat_id": "A", "role": "assistant", "message_id": "m"})
        await hub.broadcast({"type": "doc.new", "doc_id": "d"})
        return {k: [e["type"] for e in v.sent] for k, v in s.items()}
    got = asyncio.run(run())
    assert got["mine"] == ["chat.delta", "chat.message", "doc.new"]
    assert got["other"] == ["doc.new"] and got["nothing"] == ["doc.new"]
    assert got["overview"] == ["chat.message", "doc.new"]
    assert got["legacy"] == ["chat.delta", "chat.message", "doc.new"]


def test_notify_from_another_worker_is_scoped_too():
    async def run():
        hub, s = _hub(mine=scope(["A"]), other=scope(["B"]))
        hub._on_notify(None, 0, "c", json.dumps({"type": "chat.done", "chat_id": "B", "_o": "other-instance"}))
        await asyncio.sleep(0.05)
        return {k: [e["type"] for e in v.sent] for k, v in s.items()}
    got = asyncio.run(run())
    assert got["other"] == ["chat.done"] and got["mine"] == [] and got["legacy"] == ["chat.done"]


def test_subscribe_over_a_real_socket(schema_url, dirs):  # noqa: F811
    from fastapi.testclient import TestClient

    from server.app import app
    from server.tests.test_live import recv, recv_type
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as mine, c.websocket_connect("/ws") as other, c.websocket_connect("/ws") as old:
            mine.send_text(json.dumps({"type": "subscribe", "chat_ids": ["A"]}))
            other.send_text(json.dumps({"type": "subscribe", "chat_ids": ["B"]}))
            assert recv_type(mine, "subscribed")["chat_ids"] == ["A"]
            assert recv_type(other, "subscribed")["chat_ids"] == ["B"]
            c.portal.call(live.publish, {"type": "chat.delta", "chat_id": "A", "text": "hi"})
            c.portal.call(live.publish, {"type": "doc.new", "doc_id": "d"})
            assert recv_type(mine, "chat.delta")["text"] == "hi"
            assert recv_type(old, "chat.delta") is not None           # unsubscribed client keeps the old behaviour
            msgs = [recv(other) for _ in range(2)]   # doc.new arrives; the A chat.delta never does
            assert [m["type"] for m in msgs if m] == ["doc.new"]
