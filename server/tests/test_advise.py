"""CONTRACT 5.12: /api/advise. The hard rule is enforced by the server on whatever the engine returns."""
import pytest
from fastapi.testclient import TestClient

from server import advise_routes
from server.tests.test_contract import DOC, dirs  # noqa: F401
from server.tests.test_live import recv_type

RULE = "fi-acc-door-clear-width"
QUOTE = "must be at least 850 millimetres"


def card(**kw):
    c = {"kind": "warning", "title": "Door too narrow", "body": "This door is below the 850 mm minimum.",
         "item_ids": ["door-001"],
         "source": {"type": "rule", "ref": RULE, "title": "Decree 241/2017, 4 §", "quote": QUOTE}}
    c.update(kw)
    return c


@pytest.fixture
def client(schema_url, dirs):  # noqa: F811
    from server import db
    from server.app import app
    from server.seed import seed_documents
    with TestClient(app) as c:
        async def seed():
            pool = await db.get_pool()
            async with pool.acquire() as conn:
                await seed_documents(conn, [{"doc_id": DOC, "source": "cubicasa5k", "title": "t", "kind": "raster"}])
        c.portal.call(seed)
        yield c


def test_no_advisor_means_no_cards(client, monkeypatch):
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: None)
    r = client.post("/api/advise", json={"doc_id": DOC})
    assert r.status_code == 200 and r.json() == {"cards": []}


def test_cards_need_a_verifiable_source(client, monkeypatch):
    good = card()
    no_source = card(source=None)
    empty_quote = card(source={"type": "rule", "ref": RULE, "title": "t", "quote": ""})
    invented_rule = card(source={"type": "rule", "ref": "fi-made-up", "title": "t", "quote": QUOTE})
    wrong_quote = card(source={"type": "rule", "ref": RULE, "title": "t", "quote": "doors must be 900 millimetres wide"})
    bad_kind = card(kind="idea")
    doc_card = card(source={"type": "document", "ref": f"{DOC}#p1", "title": "Plan", "quote": "WC 1"})
    long_quote = card(source={"type": "document", "ref": DOC, "title": "Plan", "quote": "x" * 1201})
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: (
        lambda doc_id, edit, chat_id: [no_source, empty_quote, invented_rule, wrong_quote, bad_kind, long_quote, good, doc_card]))
    cards = client.post("/api/advise", json={"doc_id": DOC}).json()["cards"]
    assert [c["source"]["type"] for c in cards] == ["rule", "document"]
    assert cards[0]["card_id"] and cards[0]["item_ids"] == ["door-001"]


def test_limits_and_edit_passthrough(client, monkeypatch):
    seen = {}

    def advise(doc_id, edit, chat_id):
        seen.update(doc_id=doc_id, edit=edit, chat_id=chat_id)
        return [card(title="T" * 100, body="B" * 300)] * 5
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: advise)
    chat = client.post("/api/chats", json={"doc_ids": [DOC]}).json()
    cards = client.post("/api/advise", json={"doc_id": DOC, "chat_id": chat["id"],
                                             "edit": {"op": "hide", "item_ids": ["door-001"]}}).json()["cards"]
    assert len(cards) == 3 and len(cards[0]["title"]) <= 60 and len(cards[0]["body"]) <= 200
    assert seen == {"doc_id": DOC, "edit": {"op": "hide", "item_ids": ["door-001"]}, "chat_id": chat["id"]}


def test_errors_and_engine_failure(client, monkeypatch):
    assert client.post("/api/advise", json={"doc_id": "nope"}).status_code == 404
    assert client.post("/api/advise", json={"doc_id": DOC, "chat_id": "x"}).status_code == 404
    assert client.post("/api/advise", json={"doc_id": DOC, "chat_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert client.post("/api/advise", json={"doc_id": DOC, "edit": {"op": "explode"}}).status_code == 422

    def boom(*a):
        raise RuntimeError("model down")
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: boom)
    assert client.post("/api/advise", json={"doc_id": DOC}).json() == {"cards": []}


def test_cards_pushed_over_ws(client, monkeypatch):
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: (lambda d, e, c: [card()]))
    with client.websocket_connect("/ws") as w:
        client.post("/api/advise", json={"doc_id": DOC})
        m = recv_type(w, "advisor.cards")
        assert m["doc_id"] == DOC and m["chat_id"] is None and len(m["cards"]) == 1


@pytest.mark.parametrize("op,detail", [
    ("hide", None), ("restore", None),
    ("move", {"delta_m": [0.5, 0, 0]}), ("move", {"position_m": [1.0, 2.0, 0.0]}),
    ("material", {"material": "glass"}),
    ("undo", {"op": "move", "delta_m": [-0.5, 0, 0]}),
])
def test_advise_edit_ops_pass_detail_and_are_not_persisted(client, monkeypatch, op, detail):
    seen = {}

    def advise(doc_id, edit, chat_id):
        seen["edit"] = edit
        return [card()]
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: advise)
    chat = client.post("/api/chats", json={"doc_ids": [DOC]}).json()
    edit = {"op": op, "item_ids": ["door-001"]}
    if detail is not None:
        edit["detail"] = detail
    r = client.post("/api/advise", json={"doc_id": DOC, "chat_id": chat["id"], "edit": edit})
    assert r.status_code == 200 and len(r.json()["cards"]) == 1
    assert seen["edit"] == edit
    assert client.get(f"/api/chats/{chat['id']}/scene-state").json()["states"] == []  # what-ifs are never stored


def test_advise_rejects_unknown_ops_and_bad_detail(client):
    bad = [{"op": "explode", "item_ids": ["a"]}, {"op": "move", "item_ids": [""]},
           {"op": "move", "item_ids": ["a"], "detail": "x"},
           {"op": "move", "item_ids": ["a"], "detail": {"k": "x" * 5000}}]
    for e in bad:
        assert client.post("/api/advise", json={"doc_id": DOC, "edit": e}).status_code == 422


def test_size_edits_reach_the_advisor(client, monkeypatch):
    """E-16: a 'narrow' edit is a valid advise request (the engine's door-width rule needs it)."""
    from server import advise_routes
    seen = {}
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: (lambda d, e, c=None: seen.setdefault("e", e) and []))
    r = client.post("/api/advise", json={"doc_id": DOC, "edit": {"op": "narrow", "item_ids": ["x"], "detail": {"width_m": 0.7}}})
    assert r.status_code == 200
    assert seen["e"]["op"] == "narrow"


def test_clean_cards_keeps_severity_and_checked():
    c = card(severity="violation", checked=["fi-acc-door-clear-width"])
    out = advise_routes.clean_cards([c], DOC)
    assert out[0]["severity"] == "violation" and out[0]["checked"] == ["fi-acc-door-clear-width"]
    assert advise_routes.clean_cards([card()], DOC)[0]["severity"] == "violation"      # derived from kind when absent


def test_chat_hide_attaches_advisor_cards_and_publishes(monkeypatch):
    import asyncio

    from server import chats_routes
    sent = []

    async def fake_publish(ev):
        sent.append(ev)

    seen = {}

    def fake_advise(doc_id, edit, chat_id=None, root=None):
        seen.update(doc_id=doc_id, edit=edit)
        return [card(severity="violation", checked=[RULE])]

    monkeypatch.setattr(chats_routes, "publish", fake_publish)
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: fake_advise)
    ans = {"evidence": {"scene": {"doc_id": DOC, "commands": [{"op": "hide", "item_ids": ["b"]}]}}}
    asyncio.run(chats_routes._attach_advice(ans, [DOC], ["a"], "chat-1"))
    assert seen["edit"] == {"op": "hide", "item_ids": ["a", "b"]}      # everything hidden in this chat so far plus this command
    assert ans["advisor_cards"][0]["severity"] == "violation"
    assert sent and sent[0]["type"] == "advisor.cards" and sent[0]["cards"] == ans["advisor_cards"]
    plain = {"evidence": {"scene": {"doc_id": DOC, "commands": [{"op": "highlight", "item_ids": ["b"]}]}}}
    asyncio.run(chats_routes._attach_advice(plain, [DOC], [], "chat-1"))
    assert "advisor_cards" not in plain


def test_remote_reset_clears_then_rederives_cards_for_every_client(client, monkeypatch):
    """F11: a scene reset sent by one client clears the advisor cards on all clients and re-derives them."""
    seen = []
    monkeypatch.setattr(advise_routes, "_engine_advise", lambda: (lambda d, e, c: seen.append(e) or [card()]))
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"type": "scene.edit", "doc_id": DOC, "op": "reset", "item_ids": [], "edit_id": "r1"})
        for w in (a, b):
            recv_type(w, "scene.edit")
            cleared = recv_type(w, "advisor.cards")
            assert cleared["cards"] == [] and cleared["cleared"] is True and cleared["after_edit"] == "r1"
            fresh = recv_type(w, "advisor.cards")
            assert len(fresh["cards"]) == 1 and fresh["scene_version"] > cleared["scene_version"]
    assert seen and seen[0]["op"] == "reset"
