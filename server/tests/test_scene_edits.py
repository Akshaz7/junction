"""S-10: scene edit layer: fold rules, /ws relay, replay to late joiners, GET scene-state, answer commands."""
import time

import pytest
from fastapi.testclient import TestClient

from server import scene_edits as se
from server.tests.test_contract import DOC, dirs  # noqa: F401
from server.tests.test_live import recv, recv_type


def e(op, ids=(), labels=None, doc="d"):
    return {"doc_id": doc, "op": op, "item_ids": list(ids), "labels": labels or {}}


def test_fold_hide_restore_reset_isolate():
    s = se.fold([e("highlight", ["w1", "w2", "w3"], {"w1": "W1", "w2": "W2"}), e("hide", ["w2"])])["d"]
    assert s["hidden"] == ["w2"] and s["highlighted"] == ["w1", "w3"] and s["labels"] == {"w1": "W1"}
    s = se.fold([e("hide", ["a", "b"]), e("restore", ["a"])])["d"]
    assert s["hidden"] == ["b"]
    s = se.fold([e("hide", ["a", "b"]), e("restore")])["d"]
    assert s["hidden"] == []
    s = se.fold([e("hide", ["a"]), e("highlight", ["b"], {"b": "B1"}), e("reset")])["d"]
    assert (s["hidden"], s["highlighted"], s["labels"], s["isolated"]) == ([], [], {}, None)
    s = se.fold([e("hide", ["a"]), e("isolate", ["a", "b"], {"a": "D1"})])["d"]
    assert s["isolated"] == ["a", "b"] and s["hidden"] == [] and s["highlighted"] == ["a", "b"]
    two = se.fold([e("hide", ["a"], doc="x"), e("hide", ["b"], doc="y")])
    assert two["x"]["hidden"] == ["a"] and two["y"]["hidden"] == ["b"]


def test_clean_edit_validation():
    assert se.clean_edit({"doc_id": "d", "op": "bogus", "item_ids": ["a"]}) is None
    assert se.clean_edit({"doc_id": "", "op": "hide", "item_ids": ["a"]}) is None
    assert se.clean_edit({"doc_id": "d", "op": "hide", "item_ids": []}) is None
    assert se.clean_edit({"doc_id": "d", "op": "hide", "item_ids": "a"}) is None
    r = se.clean_edit({"doc_id": "d", "op": "highlight", "item_ids": ["a", "a", 5, "b"], "labels": {"a": "W1", "z": "Q"}})
    assert r["item_ids"] == ["a", "b"] and r["labels"] == {"a": "W1"} and r["edit_id"]
    assert se.clean_edit({"doc_id": "d", "op": "reset"})["item_ids"] == []
    assert se.clean_edit({"doc_id": "d", "op": "hide", "item_ids": ["a"], "labels": {"a": "x"}})["labels"] == {}
    assert se.clean_edit({"doc_id": "d", "op": "highlight", "item_ids": [], "labels": {"a": "W1"}})["labels"] == {}


@pytest.fixture
def client(schema_url, dirs):  # noqa: F811
    from server.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def chat(client):
    from server import db
    from server.seed import seed_documents

    async def seed():
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            await seed_documents(conn, [{"doc_id": DOC, "source": "cubicasa5k", "title": "t", "kind": "raster"}])
    client.portal.call(seed)
    return client.post("/api/chats", json={"doc_ids": [DOC]}).json()


def test_hide_reaches_other_client_and_late_joiner_gets_state(client, chat):
    cid = chat["id"]
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        t0 = time.monotonic()
        a.send_json({"type": "scene.edit", "doc_id": DOC, "chat_id": cid, "op": "highlight",
                     "item_ids": ["window-001", "window-002"], "labels": {"window-001": "W1", "window-002": "W2"}})
        a.send_json({"type": "scene.edit", "doc_id": DOC, "chat_id": cid, "op": "hide", "item_ids": ["window-002"],
                     "edit_id": "e-hide-1"})
        m = recv_type(b, "scene.edit")
        assert m["op"] == "highlight" and m["labels"] == {"window-001": "W1", "window-002": "W2"} and m["chat_id"] == cid
        m = recv_type(b, "scene.edit")
        assert m["op"] == "hide" and m["item_ids"] == ["window-002"] and m["edit_id"] == "e-hide-1" and m["ts"]
        assert time.monotonic() - t0 < 2
    # late joiner via query string
    with client.websocket_connect(f"/ws?chat_id={cid}") as c:
        st = recv_type(c, "scene.state")
        assert st["doc_id"] == DOC and st["hidden"] == ["window-002"]
        assert st["highlighted"] == ["window-001"] and st["labels"] == {"window-001": "W1"}
        # or by message
        c.send_json({"type": "scene.join", "chat_id": cid, "doc_id": DOC})
        assert recv_type(c, "scene.state")["hidden"] == ["window-002"]
    got = client.get(f"/api/chats/{cid}/scene-state").json()
    assert got["chat_id"] == cid and got["states"][0]["hidden"] == ["window-002"]
    assert client.get(f"/api/chats/{cid}/scene-state?doc_id=other").json()["states"][0]["hidden"] == []
    # reset clears the stored layer
    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "scene.edit", "doc_id": DOC, "chat_id": cid, "op": "reset"})
        assert recv_type(a, "scene.edit")["op"] == "reset"
    assert client.get(f"/api/chats/{cid}/scene-state").json()["states"][0]["hidden"] == []


def test_duplicate_edit_id_is_applied_once_and_invalid_is_rejected(client, chat):
    cid = chat["id"]
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        msg = {"type": "scene.edit", "doc_id": DOC, "chat_id": cid, "op": "hide", "item_ids": ["w1"], "edit_id": "dup"}
        a.send_json(msg)
        a.send_json(msg)
        assert recv_type(b, "scene.edit") is not None
        assert recv_type(b, "scene.edit", 0.6) is None
        a.send_json({"type": "scene.edit", "doc_id": DOC, "op": "explode", "item_ids": ["w1"]})
        assert recv_type(a, "scene.error") is not None


def test_edit_without_chat_is_relayed_not_stored(client, chat):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"type": "scene.edit", "doc_id": DOC, "op": "hide", "item_ids": ["w1"]})
        m = recv_type(b, "scene.edit")
        assert m["item_ids"] == ["w1"] and "chat_id" not in m
    assert client.get(f"/api/chats/{chat['id']}/scene-state").json()["states"] == []
    assert client.get("/api/chats/00000000-0000-0000-0000-000000000000/scene-state").status_code == 404


def test_answer_commands_become_persisted_edits(client, chat, monkeypatch):
    from server import chats_routes, stub_engine

    def engine(q, doc_ids, on_event):
        a = stub_engine.answer(q, doc_ids, on_event)
        a["evidence"]["scene"]["commands"] = [{"op": "highlight", "item_ids": ["window-001"], "labels": {"window-001": "W1"}},
                                              {"op": "hide", "item_ids": ["window-002"]}]
        return a
    monkeypatch.setattr(chats_routes, "ENGINE", engine)
    cid = chat["id"]
    with client.websocket_connect("/ws") as w:
        client.post(f"/api/chats/{cid}/messages", json={"content": "How many windows are there?"})
        ops = []
        while len(ops) < 2 and (m := recv_type(w, "scene.edit", 5)):  # NOTIFY fan-out can lag under load
            ops.append(m["op"])
        assert ops == ["highlight", "hide"]
    st = client.get(f"/api/chats/{cid}/scene-state").json()["states"][0]
    assert st["hidden"] == ["window-002"] and st["labels"] == {"window-001": "W1"}


def test_run_engine_passes_hidden_items_to_real_engine(monkeypatch):
    """E-20: later answers in a chat see the chat's hidden items."""
    from server import chats_routes
    seen = {}

    def fake_real(q, d, cb, scene_state=None, history=None):
        seen["s"] = scene_state
        return {}
    monkeypatch.setattr(chats_routes, "_real_engine", fake_real)
    monkeypatch.setattr(chats_routes, "ENGINE", fake_real)
    chats_routes._run_engine("How many windows?", ["d"], None, {"hidden": ["w7"]})
    assert seen["s"] == {"hidden": ["w7"]}


def test_clear_highlights_persists_without_restoring_or_exiting_isolation(client, chat):
    cid = chat["id"]
    with client.websocket_connect(f"/ws?chat_id={cid}") as socket:
        for op, ids in (("hide", ["removed"]), ("isolate", ["selected"]), ("highlight", [])):
            socket.send_json({"type": "scene.edit", "chat_id": cid, "doc_id": DOC,
                              "op": op, "item_ids": ids})
            event = recv_type(socket, "scene.edit")
            assert event and event["op"] == op
    with client.websocket_connect(f"/ws?chat_id={cid}") as reloaded:
        state = recv_type(reloaded, "scene.state")
        assert state["hidden"] == ["removed"]
        assert state["isolated"] == ["selected"]
        assert state["highlighted"] == [] and state["labels"] == {}
