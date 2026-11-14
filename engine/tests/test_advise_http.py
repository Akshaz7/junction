"""E-45: the 3D edit panel and AR call POST /api/advise; hiding the AC20 front door must give the same 848/2017 section 33 violation as chat."""
import pytest

DOC = "ifc_bench__ac20-arc"


class _Pool:
    async def fetchval(self, *a, **k):
        return 1


@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from engine.solvers import ARTIFACTS
    from pathlib import Path
    if not (Path(ARTIFACTS) / DOC).exists():
        pytest.skip("real artifacts not present")
    from server import advise_routes, db

    async def pool():
        return _Pool()

    async def no_publish(*a, **k):
        return None
    monkeypatch.setattr(db, "get_pool", pool)
    monkeypatch.setattr(advise_routes, "publish", no_publish)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(advise_routes.router)
    return TestClient(app)


def _front_door():
    from engine import scene_cmds
    from engine.solvers import ARTIFACTS
    from engine.solvers.data import load_doc
    doc = load_doc(DOC, ARTIFACTS)
    q = "remove the front door"
    a = scene_cmds.scene_answer(q, doc, scene_cmds.parse_scene(q))
    cmd = next(c for c in a["evidence"]["scene"]["commands"] if c.get("op") == "hide")
    return cmd["item_ids"]


def test_advise_route_front_door_gives_exit_violation_like_chat(client, monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    ids = _front_door()
    r = client.post("/api/advise", json={"doc_id": DOC, "edit": {"op": "hide", "item_ids": ids}})
    assert r.status_code == 200, r.text
    cards = r.json()["cards"]
    bad = [c for c in cards if c["severity"] == "violation"]
    assert bad and "Fewer than two exits" in bad[0]["title"], [(c["severity"], c["title"]) for c in cards]
    assert bad[0]["source"]["ref"] == "fi-fire-exits-per-storey" and bad[0]["item_ids"]
    from engine.answer import answer
    chat = answer("remove the front door", [DOC])
    assert bad[0]["title"] in chat["answer"]["text_md"]
