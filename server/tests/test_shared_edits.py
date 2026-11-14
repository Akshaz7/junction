"""One shared edit layer per chat: manual Edit-panel edits (sent over /ws with chat_id) and chat scene commands
fold into the same scene_edits state, so either side can undo the other; advice is computed on that state.
Real engine (code-only scene path, fake models) on the demo IFC doc ac20."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import scene_edits as se
from server.advise_routes import effective_edit
from server.tests.test_contract import dirs  # noqa: F401
from server.tests.test_live import recv_type

REAL = Path(__file__).resolve().parents[2] / "artifacts"
DEMO = "ifc_bench__ac20-arc"
DOOR = "3qloCPnZDEQBom1ZjBlwJP"          # Keller, 1.0 m interior door


def e(op, ids=(), doc="d"):
    return {"doc_id": doc, "op": op, "item_ids": list(ids), "labels": {}}


def test_last_hidden_is_the_newest_removal_still_in_effect():
    assert se.last_hidden([e("hide", ["a"]), e("hide", ["b", "c"])]) == ["b", "c"]
    assert se.last_hidden([e("hide", ["a"]), e("hide", ["b"]), e("restore", ["b"])]) == ["a"]
    assert se.last_hidden([e("hide", ["a"]), e("reset")]) == []
    assert se.last_hidden([e("hide", ["a"]), e("hide", ["b"], doc="x")], ["d"]) == ["a"]


def test_effective_edit_folds_the_shared_layer():
    assert effective_edit([], {"op": "hide", "item_ids": ["a"]}) == {"op": "hide", "item_ids": ["a"]}
    assert effective_edit(["a"], {"op": "hide", "item_ids": ["b"]}) == {"op": "hide", "item_ids": ["a", "b"]}
    assert effective_edit(["a", "b"], {"op": "hide", "item_ids": ["b"]})["item_ids"] == ["a", "b"]   # /ws edit landed first
    assert effective_edit(["a", "b"], {"op": "restore", "item_ids": ["a"]}) == {"op": "hide", "item_ids": ["b"]}
    assert effective_edit(["a"], {"op": "restore", "item_ids": ["a"]}) == {"op": "restore", "item_ids": ["a"]}
    assert effective_edit(["a"], {"op": "reset", "item_ids": []})["op"] == "reset"
    assert effective_edit(["a"], {"op": "move", "item_ids": ["a"]}) == {"op": "move", "item_ids": ["a"]}


pytestmark_demo = pytest.mark.skipif(not (REAL / DEMO).exists(), reason="artifact missing")


@pytest.fixture
def client(schema_url, dirs, monkeypatch):  # noqa: F811
    art, _ = dirs
    (art / DEMO).symlink_to(REAL / DEMO, target_is_directory=True)
    monkeypatch.setenv("MODELS_FAKE", "1")
    from server import chats_routes, db
    from server.app import app
    from server.seed import seed_documents
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    with TestClient(app) as c:
        async def seed():
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                await seed_documents(conn, [{"doc_id": DEMO, "source": "ifc_bench", "title": "AC20", "kind": "ifc"}])
        c.portal.call(seed)
        yield c


@pytest.fixture
def chat(client):
    return client.post("/api/chats", json={"doc_ids": [DEMO]}).json()["id"]


def _manual(client, cid, op, ids):
    """What the 3D viewer sends for an Edit-panel Remove / Restore / Undo inside a chat."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "scene.edit", "doc_id": DEMO, "chat_id": cid, "op": op, "item_ids": ids})
        assert recv_type(ws, "scene.edit", 5)["chat_id"] == cid


def _ask(client, cid, q):
    r = client.post(f"/api/chats/{cid}/messages", json={"content": q})
    for block in r.text.replace("\r\n", "\n").split("\n\n"):
        if "event: answer" in block.splitlines():
            return json.loads(next(ln[5:].strip() for ln in block.splitlines() if ln.startswith("data:")))
    raise AssertionError(r.text[-500:])


def _hidden(client, cid):
    st = client.get(f"/api/chats/{cid}/scene-state?doc_id={DEMO}").json()["states"]
    return st[0]["hidden"] if st else []


@pytestmark_demo
def test_manual_remove_then_chat_puts_the_door_back(client, chat):
    _manual(client, chat, "hide", [DOOR])
    assert _hidden(client, chat) == [DOOR]
    a = _ask(client, chat, "put the door back")
    cmd = a["evidence"]["scene"]["commands"][0]
    assert cmd["op"] == "restore" and cmd["item_ids"] == [DOOR]
    assert _hidden(client, chat) == []


@pytestmark_demo
def test_manual_remove_then_chat_undo(client, chat):
    _manual(client, chat, "hide", [DOOR])
    a = _ask(client, chat, "undo my edit")
    assert a["evidence"]["scene"]["commands"][0] == {**a["evidence"]["scene"]["commands"][0], "op": "restore", "item_ids": [DOOR]}
    assert _hidden(client, chat) == []


@pytestmark_demo
def test_chat_remove_then_manual_restore_clears_chat_state(client, chat):
    a = _ask(client, chat, "remove the front door")
    gone = a["evidence"]["scene"]["commands"][0]["item_ids"]
    assert len(gone) == 1 and _hidden(client, chat) == gone
    _manual(client, chat, "restore", gone)          # Edit panel: Undo / Restore by hand
    assert _hidden(client, chat) == []
    # and the chat sees it: nothing left to undo
    assert _ask(client, chat, "undo")["evidence"]["scene"]["commands"] == []


@pytestmark_demo
def test_advise_uses_the_shared_state(client, chat):
    from engine import advisor
    from server.advise_routes import clean_cards
    a = _ask(client, chat, "remove the front door")
    front = a["evidence"]["scene"]["commands"][0]["item_ids"]
    # manual Remove of another door: advice is on the model with both removed, the same as the chat would give
    got = client.post("/api/advise", json={"doc_id": DEMO, "chat_id": chat, "edit": {"op": "hide", "item_ids": [DOOR]}}).json()["cards"]
    want = clean_cards(advisor.advise(DEMO, {"op": "hide", "item_ids": [*front, DOOR]}), DEMO)
    assert got and [c["card_id"] for c in got] == [c["card_id"] for c in want]
    _manual(client, chat, "hide", [DOOR])
    # restoring the front door by hand: advice for what stays hidden (DOOR), whether or not /ws landed first
    got = client.post("/api/advise", json={"doc_id": DEMO, "chat_id": chat, "edit": {"op": "restore", "item_ids": front}}).json()["cards"]
    want = clean_cards(advisor.advise(DEMO, {"op": "hide", "item_ids": [DOOR]}), DEMO)
    assert [c["card_id"] for c in got] == [c["card_id"] for c in want]
    # chat "put the door back" restores DOOR (front still hidden) and pushes cards for the new state
    with client.websocket_connect("/ws") as ws:
        a = _ask(client, chat, "put the door back")
        assert a["evidence"]["scene"]["commands"][0]["item_ids"] == [DOOR]
        ev = recv_type(ws, "advisor.cards", 5)
    want = clean_cards(advisor.advise(DEMO, {"op": "hide", "item_ids": front}), DEMO)
    assert ev and ev["chat_id"] == chat and [c["card_id"] for c in ev["cards"]] == [c["card_id"] for c in want]
    assert _hidden(client, chat) == front
    # Reset edits in the panel is accepted by /api/advise (was 422)
    assert client.post("/api/advise", json={"doc_id": DEMO, "chat_id": chat, "edit": {"op": "reset", "item_ids": front}}).status_code == 200
