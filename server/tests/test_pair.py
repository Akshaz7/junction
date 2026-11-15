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


def test_register_answers_from_memory_and_persists_in_background(monkeypatch):
    import asyncio

    writes = []

    class Pool:
        async def execute(self, sql, *args):
            await asyncio.sleep(0.05)
            writes.append(args)

        async def fetchval(self, sql, *args):
            raise AssertionError("a set hit must not touch the DB")

    async def pool():
        return Pool()
    monkeypatch.setattr(pair_routes, "_pool", pool)
    pair_routes._memory.clear()

    async def run():
        await pair_routes.register("ABCD1234", "chat-9")
        assert writes == []  # DB write is in the background
        assert await pair_routes.check("ABCD1234", "chat-9") == {"paired": True}
        await asyncio.gather(*list(pair_routes._tasks))
    asyncio.run(run())
    assert writes == [("ABCD1234", "chat-9")]


def test_check_falls_back_to_db_and_caches_hit(monkeypatch):
    import asyncio

    calls = []

    class Pool:
        async def fetchval(self, sql, *args):
            calls.append(args)
            return 1

    async def pool():
        return Pool()
    monkeypatch.setattr(pair_routes, "_pool", pool)
    pair_routes._memory.clear()

    async def run():
        assert await pair_routes.check("ABCD1234", "other-instance") == {"paired": True}
        assert await pair_routes.check("ABCD1234", "other-instance") == {"paired": True}
    asyncio.run(run())
    assert len(calls) == 1


def test_db_write_failure_does_not_fail_register(monkeypatch):
    import asyncio

    class Pool:
        async def execute(self, sql, *args):
            raise RuntimeError("db down")

    async def pool():
        return Pool()
    monkeypatch.setattr(pair_routes, "_pool", pool)
    pair_routes._memory.clear()

    async def run():
        await pair_routes.register("ABCD1234", "chat-x")
        await asyncio.gather(*list(pair_routes._tasks))
        assert await pair_routes.check("ABCD1234", "chat-x") == {"paired": True}
    asyncio.run(run())


def test_register_publishes_a_proof_not_the_code(monkeypatch):
    import asyncio
    import json

    sent = []

    async def publish(event):
        sent.append(event)

    async def no_pool():
        return None
    monkeypatch.setattr(pair_routes.live, "publish", publish)
    monkeypatch.setattr(pair_routes, "_pool", no_pool)
    pair_routes._memory.clear()
    asyncio.run(pair_routes.register("ABCD1234", "chat-7"))
    assert sent == [{"type": "pair.chat", "chat_id": "chat-7", "proof": pair_routes.proof("ABCD1234", "chat-7")}]
    assert "ABCD1234" not in json.dumps(sent)
    assert pair_routes.proof("OTHER9999", "chat-7") != sent[0]["proof"]


def test_join_publishes_a_proof_not_the_code(monkeypatch):
    sent = []

    async def fake_publish(event):
        sent.append(event)
    monkeypatch.setattr(pair_routes.live, "publish", fake_publish)
    c = TestClient(app)
    assert c.post("/api/pair/ABCD1234/join").status_code == 204
    assert sent == [{"type": "pair.joined", "proof": pair_routes.join_proof("ABCD1234")}]
    assert "ABCD1234" not in str(sent) and c.post("/api/pair/x/join").status_code == 400
