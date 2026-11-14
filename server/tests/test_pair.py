"""Device pairing routes: a chat registered under a code is paired for that code only."""
from fastapi.testclient import TestClient

from server import pair_routes
from server.app import app


def test_registered_chat_is_paired_only_for_its_code(monkeypatch):
    async def no_pool():
        return None
    monkeypatch.setattr(pair_routes, "_pool", no_pool)
    pair_routes._memory.clear()
    c = TestClient(app)
    assert c.get("/api/pair/ABCD1234/chats/chat-1").json() == {"paired": False}
    assert c.post("/api/pair/ABCD1234/chats/chat-1").status_code == 204
    assert c.get("/api/pair/ABCD1234/chats/chat-1").json() == {"paired": True}
    assert c.get("/api/pair/OTHER9999/chats/chat-1").json() == {"paired": False}
    assert c.get("/api/pair/ABCD1234/chats/chat-2").json() == {"paired": False}


def test_bad_codes_are_rejected():
    c = TestClient(app)
    assert c.get("/api/pair/x/chats/c").status_code == 400
    assert c.get("/api/pair/bad%20code%20here/chats/c").status_code == 400
