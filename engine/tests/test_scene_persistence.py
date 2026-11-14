"""Panel-shaped edits use the same persisted chat layer as typed removals."""
from pathlib import Path
import json

import pytest

from server.tests.conftest import schema_url  # noqa: F401
from server.tests.test_contract import DOC, _sse, dirs  # noqa: F401
from server.tests.test_live import recv_type
from server.tests.test_scene_edits import chat, client  # noqa: F401


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
