"""Chat edit checks (FIX-4): "remove the front door" publishes advisor cards; a later chat undo / restore / reset
re-checks what is still hidden and ALWAYS publishes the result (an empty list too), so the answer card and the 3D
Edit panel (both follow live `advisor.cards`) drop the stale violation card."""
import asyncio
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import advise_routes, chats_routes
from server.tests.test_contract import DOC, dirs  # noqa: F401
from server.tests.test_live import recv_type

RULE = "fi-acc-door-clear-width"


def card(ids):
    return {"kind": "warning", "severity": "violation", "checked": [RULE], "title": "Entrance removed",
            "body": "The building has no entrance door.", "item_ids": list(ids),
            "source": {"type": "rule", "ref": RULE, "title": "Decree 241/2017, 4 §", "quote": "must be at least 850 millimetres"}}


@pytest.fixture
def fakes(monkeypatch):
    """Fake publish + advisor: a card only while the front door ("door") is hidden."""
    sent, seen = [], []

    async def fake_publish(ev):
        sent.append(ev)

    def fake_advise(doc_id, edit, chat_id=None, root=None):
        seen.append(edit)
        return [card(["door"])] if "door" in edit["item_ids"] else []

    monkeypatch.setattr(chats_routes, "publish", fake_publish)
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: fake_advise)
    return sent, seen


def _ans(*cmds, undo=False):
    trace = [{"step": "scene", "detail": "undo / current chat scene" if undo else "hide 1 item(s)", "ms": 0, "model": None, "cost_usd": 0}]
    return {"evidence": {"scene": {"doc_id": DOC, "commands": list(cmds)}}, "trace": trace}


def _run(ans, hidden, by_doc=None):
    asyncio.run(chats_routes._attach_advice(ans, [DOC], hidden, "chat-1", by_doc))


def test_hide_unchanged_cards_on_answer_and_published(fakes):
    sent, seen = fakes
    a = _ans({"op": "hide", "item_ids": ["door"]})
    _run(a, ["w1"])
    assert seen == [{"op": "hide", "item_ids": ["w1", "door"]}]
    assert a["advisor_cards"] and sent == [{"type": "advisor.cards", "doc_id": DOC, "chat_id": "chat-1", "cards": a["advisor_cards"]}]
    sent.clear()
    quiet = _ans({"op": "hide", "item_ids": ["w2"]})
    _run(quiet, [])
    assert "advisor_cards" not in quiet and sent == []          # a hide with no cards stays quiet, as before


def test_undo_of_the_only_hide_publishes_an_empty_list(fakes):
    sent, seen = fakes
    a = _ans({"op": "restore", "item_ids": ["door"]}, undo=True)
    _run(a, ["door"])
    assert seen == [] and sent == [{"type": "advisor.cards", "doc_id": DOC, "chat_id": "chat-1", "cards": []}]
    assert "advisor_cards" not in a


def test_restore_or_reset_always_publishes_even_with_nothing_hidden(fakes):
    sent, _ = fakes
    _run(_ans({"op": "reset", "item_ids": []}), [])                       # was: returned without publishing
    _run(_ans({"op": "restore", "item_ids": []}), [])
    _run(_ans(undo=True), [])                                             # "There is no scene edit to undo."
    assert [e["cards"] for e in sent] == [[], [], []]


def test_undo_folds_every_command_and_rechecks_what_stays_hidden(fakes):
    sent, seen = fakes
    # undo of an isolate is [reset, hide <old hidden>]: the door stays hidden, so its card is published again
    _run(_ans({"op": "reset", "item_ids": []}, {"op": "hide", "item_ids": ["door"]}, undo=True), ["door"])
    assert seen[-1] == {"op": "hide", "item_ids": ["door"]} and sent[-1]["cards"][0]["item_ids"] == ["door"]
    # restore of another item: recomputed on what is left (door still hidden)
    _run(_ans({"op": "restore", "item_ids": ["w1"]}), ["door", "w1"])
    assert seen[-1] == {"op": "hide", "item_ids": ["door"]} and len(sent[-1]["cards"]) == 1
    # restore the door, w1 stays hidden: no card, but still published
    _run(_ans({"op": "restore", "item_ids": ["door"]}), ["door", "w1"])
    assert seen[-1] == {"op": "hide", "item_ids": ["w1"]} and sent[-1]["cards"] == []


def test_recheck_uses_the_answer_docs_hidden_only(fakes):
    sent, seen = fakes
    _run(_ans({"op": "restore", "item_ids": ["w1"]}), ["w1", "door"], {DOC: ["w1"], "other": ["door"]})
    assert seen == [] and sent[-1]["cards"] == []        # the door hidden in another doc does not count here


def test_advisor_failure_never_breaks_the_chat(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: boom)
    _run(_ans({"op": "restore", "item_ids": ["door"]}), ["door", "w1"])


# --- end to end over the chat API and /ws (scripted engine, fake advisor) ---

def _scene_answer(question, doc_ids, cmds, detail):
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": "Done.", "value": None, "unit": None, "confidence": 1.0, "abstained": False},
        "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": doc_ids[0], "highlight_item_ids": [],
                                                              "camera_target_item_id": None, "commands": cmds}},
        "trace": [{"step": "scene", "detail": detail, "ms": 0, "model": None, "cost_usd": 0}],
        "route": "planmap", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": 0,
    }


def _scripted_engine(question, doc_ids, on_event):
    if question.startswith("remove"):
        return _scene_answer(question, doc_ids, [{"op": "hide", "item_ids": ["door"]}], "hide 1 item(s)")
    return _scene_answer(question, doc_ids, [{"op": "restore", "item_ids": ["door"]}], "undo / current chat scene")


@pytest.fixture
def client(schema_url, dirs, monkeypatch):  # noqa: F811
    from server import db
    from server.app import app
    from server.seed import seed_documents
    monkeypatch.setattr(chats_routes, "ENGINE", _scripted_engine)
    monkeypatch.setattr(advise_routes, "_engine_advise",
                        lambda: (lambda d, e, c=None: [card(["door"])] if "door" in e["item_ids"] else []))
    with TestClient(app) as c:
        async def seed():
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                await seed_documents(conn, [{"doc_id": DOC, "source": "cubicasa5k", "title": "t", "kind": "raster"}])
        c.portal.call(seed)
        yield c


def _ask(client, cid, q):
    import json
    r = client.post(f"/api/chats/{cid}/messages", json={"content": q})
    for block in r.text.replace("\r\n", "\n").split("\n\n"):
        if "event: answer" in block.splitlines():
            return json.loads(next(ln[5:].strip() for ln in block.splitlines() if ln.startswith("data:")))
    raise AssertionError(r.text[-500:])


def test_chat_hide_then_undo_publishes_cards_then_clears_them(client):
    cid = client.post("/api/chats", json={"doc_ids": [DOC]}).json()["id"]
    with client.websocket_connect("/ws") as ws:
        a = _ask(client, cid, "remove the front door")
        ev = recv_type(ws, "advisor.cards", 5)
        assert a["advisor_cards"] and ev["chat_id"] == cid and ev["doc_id"] == DOC and ev["cards"][0]["severity"] == "violation"
        _ask(client, cid, "undo")
        ev = recv_type(ws, "advisor.cards", 5)
        assert ev is not None and ev["chat_id"] == cid and ev["doc_id"] == DOC and ev["cards"] == []


# --- the real engine on the demo IFC (skipped without the artifact; REAL_ARTIFACTS points at another checkout) ---
REAL = Path(os.environ.get("REAL_ARTIFACTS") or Path(__file__).resolve().parents[2] / "artifacts")
DEMO = "ifc_bench__ac20-arc"


@pytest.fixture
def real_client(schema_url, dirs, monkeypatch):  # noqa: F811
    art, _ = dirs
    (art / DEMO).symlink_to(REAL / DEMO, target_is_directory=True)
    monkeypatch.setenv("MODELS_FAKE", "1")
    from server import db
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


@pytest.mark.skipif(not (REAL / DEMO).exists(), reason="artifact missing")
@pytest.mark.parametrize("undo", ["undo", "put it back", "reset the scene"])
def test_real_remove_front_door_then_undo_clears_the_violation(real_client, undo):
    cid = real_client.post("/api/chats", json={"doc_ids": [DEMO]}).json()["id"]
    with real_client.websocket_connect("/ws") as ws:
        a = _ask(real_client, cid, "remove the front door")
        assert any(c.get("severity") == "violation" for c in a.get("advisor_cards") or [])
        ev = recv_type(ws, "advisor.cards", 5)
        assert ev and ev["chat_id"] == cid and ev["cards"]
        b = _ask(real_client, cid, undo)
        assert b["evidence"]["scene"]["commands"]
        ev = recv_type(ws, "advisor.cards", 5)
        assert ev is not None and ev["chat_id"] == cid and ev["doc_id"] == DEMO and ev["cards"] == []
