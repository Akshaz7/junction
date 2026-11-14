"""Panel-shaped edits use the same persisted chat layer as typed removals."""
from pathlib import Path
import json

import pytest

from server.tests.conftest import schema_url  # noqa: F401
from server.tests.test_contract import DOC, _sse, dirs  # noqa: F401
from server.tests.test_live import recv_type
from server.tests.test_scene_edits import chat, client  # noqa: F401


@pytest.fixture(autouse=True)
def scene_data(dirs):
    root, _ = dirs
    fixture = Path(__file__).parent / "fixtures" / DOC / "planmap-1.json"
    (root / DOC / "planmap-1.json").write_text(fixture.read_text())


@pytest.mark.parametrize("kind", ["window", "door"])
def test_panel_removal_persists_and_the_next_count_excludes_it(client, chat, dirs, monkeypatch, kind):  # noqa: F811
    from server import chats_routes

    root, _ = dirs
    fixture = Path(__file__).parent / "fixtures" / DOC / "planmap-1.json"
    plan = json.loads(fixture.read_text())
    if kind == "door":
        # Door variant generated for demo; positions are irrelevant to the count.
        plan["provenance"] = {"note": "Door variant generated for demo"}
        for item in plan["items"]:
            if item["kind"] == "window":
                item.update(kind="door", item_id=item["item_id"].replace("window-", "door-"))
    (root / DOC / "planmap-1.json").write_text(json.dumps(plan))
    removed = f"{kind}-001"
    expected = sum(item["kind"] == kind for item in plan["items"]) - 1
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    cid = chat["id"]
    with client.websocket_connect(f"/ws?chat_id={cid}") as socket:
        socket.send_json({"type": "scene.edit", "chat_id": cid, "doc_id": DOC,
                          "op": "hide", "item_ids": [removed], "edit_id": "panel-removal"})
        event = recv_type(socket, "scene.edit")
        assert event["chat_id"] == cid and event["item_ids"] == [removed]
        state = client.get(f"/api/chats/{cid}/scene-state").json()["states"][0]
        assert state["hidden"] == [removed]
        response = client.post(f"/api/chats/{cid}/messages", json={"content": f"How many {kind}s are there?", "doc_ids": [DOC]})
        assert response.status_code == 200
        result = next(data for kind, data in _sse(response.text) if kind == "answer")
        assert result["answer"]["value"] == expected
        assert "hidden" in result["answer"]["text_md"]


@pytest.mark.parametrize("last_op", ["hide", "restore", "reset", "isolate"])
def test_reloaded_chat_undo_uses_ordered_edits_even_when_nothing_is_hidden(client, chat, monkeypatch, last_op):
    from server import chats_routes

    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    cid = chat["id"]

    def ask(question):
        response = client.post(f"/api/chats/{cid}/messages", json={"content": question, "doc_ids": [DOC]})
        events = list(_sse(response.text))
        assert not any(kind == "error" for kind, _ in events), events
        return next(data for kind, data in events if kind == "answer")

    before = ask("How many windows are there?")["answer"]["value"]
    group = ["window-001", "window-002"]
    with client.websocket_connect(f"/ws?chat_id={cid}") as socket:
        for op, ids in [("hide", ["window-003"]), (last_op, group if last_op in ("hide", "isolate") else [])]:
            socket.send_json({"type": "scene.edit", "chat_id": cid, "doc_id": DOC, "op": op, "item_ids": ids})
            assert recv_type(socket, "scene.edit")["op"] == op
    # Rejoin like a reloaded tab, and ask with a previous count in the thread.
    with client.websocket_connect(f"/ws?chat_id={cid}") as reloaded:
        assert recv_type(reloaded, "scene.state") is not None
    result = ask("undo that")
    assert "Undid" in result["answer"]["text_md"]
    state = client.get(f"/api/chats/{cid}/scene-state").json()["states"][0]
    assert state["hidden"] == ["window-003"]
    assert state["isolated"] is None
    assert ask("How many windows are there?")["answer"]["value"] == before - 1


def test_compliance_followup_keeps_its_intent_and_current_edits(client, chat, monkeypatch):
    from server import chats_routes

    seen = []
    def advice(result, doc, hidden):
        seen.append(hidden)
        result["answer"]["text_md"] = "Current scene checked."
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    monkeypatch.setattr("engine.analytics.edit_advice", advice)
    cid = chat["id"]
    client.post(f"/api/chats/{cid}/messages", json={"content": "How many windows are there?", "doc_ids": [DOC]})
    with client.websocket_connect(f"/ws?chat_id={cid}") as socket:
        socket.send_json({"type": "scene.edit", "chat_id": cid, "doc_id": DOC, "op": "hide", "item_ids": ["window-001"]})
        assert recv_type(socket, "scene.edit") is not None
    response = client.post(f"/api/chats/{cid}/messages", json={"content": "Is it still compliant?", "doc_ids": [DOC]})
    result = next(data for kind, data in _sse(response.text) if kind == "answer")
    assert seen == [["window-001"]]
    assert "Current scene checked" in result["answer"]["text_md"]
