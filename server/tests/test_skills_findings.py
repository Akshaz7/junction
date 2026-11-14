"""S-09: findings, skills, automations."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from server import findings_routes, skills_routes
from server.tests.test_contract import DOC, dirs  # noqa: F401
from server.tests.test_live import recv_type  # noqa: F401

RULE = "fi-acc-door-clear-width"


@pytest.fixture
def client(schema_url, dirs, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AUTOMATIONS", "0")
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


def test_findings_without_checks(client, monkeypatch):
    monkeypatch.setattr(findings_routes, "_engine_run", lambda: None)
    r = client.post("/api/findings/run", json={"doc_id": DOC})
    assert r.status_code == 200 and r.json()["status"] == "no_checks" and r.json()["findings"] == []
    assert client.post("/api/findings/run", json={"doc_id": "nope"}).status_code == 404
    assert client.get("/api/findings").json() == {"findings": []}


def test_findings_need_a_known_rule_and_items(client, monkeypatch):
    raw = [
        {"rule_id": RULE, "item_ids": ["door-001"], "severity": "violation", "message": "Door 700 mm"},
        {"rule_id": "fi-made-up", "item_ids": ["door-002"], "severity": "violation", "message": "x"},
        {"rule_id": RULE, "item_ids": [], "severity": "violation", "message": "no items"},
        {"rule_id": RULE, "item_ids": ["door-003"], "severity": "catastrophe", "message": "odd severity"},
    ]
    monkeypatch.setattr(findings_routes, "_engine_run", lambda: (lambda doc_id: raw))
    r = client.post("/api/findings/run", json={"doc_id": DOC}).json()
    assert r["status"] == "ok" and len(r["findings"]) == 2
    sev = sorted(f["severity"] for f in r["findings"])
    assert sev == ["suggestion", "violation"]
    f = next(f for f in r["findings"] if f["severity"] == "violation")
    assert f["rule"]["url"] and f["rule"]["quote"] and f["message"] == "Door 700 mm"
    assert len(client.get("/api/findings", params={"doc_id": DOC}).json()["findings"]) == 2
    assert len(client.get("/api/findings", params={"severity": "violation"}).json()["findings"]) == 1
    # a rerun replaces, never duplicates
    client.post("/api/findings/run", json={"doc_id": DOC})
    assert len(client.get("/api/findings").json()["findings"]) == 2


def test_starter_skills_and_custom(client):
    skills = client.get("/api/skills").json()["skills"]
    assert len(skills) == 4 and all(s["builtin"] for s in skills)
    r = client.post("/api/skills", json={"name": "Door count", "prompt": "How many doors are there?"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert len(client.get("/api/skills").json()["skills"]) == 5
    assert client.delete(f"/api/skills/{skills[0]['id']}").status_code == 403
    assert client.delete(f"/api/skills/{sid}").status_code == 204
    assert client.delete(f"/api/skills/{sid}").status_code == 404
    assert client.post("/api/skills", json={"name": "", "prompt": "x"}).status_code == 422
    assert client.delete("/api/skills/not-a-uuid").status_code == 404


def fake_answer(prompt, doc_ids, on_event):
    return {"answer": {"text_md": f"Echo: {prompt}", "confidence": 0.9, "abstained": False},
            "citations": [], "evidence": {}, "cost": {"usd_total": 0.0}}


def test_run_skill_and_automation(client, monkeypatch):
    from server import chats_routes
    monkeypatch.setattr(chats_routes, "ENGINE", fake_answer)
    monkeypatch.setattr(skills_routes, "validate_answer", lambda a: None)
    sid = client.get("/api/skills").json()["skills"][0]["id"]
    r = client.post(f"/api/skills/{sid}/run", json={"doc_ids": [DOC]})
    assert r.status_code == 200 and r.json()["answer"]["answer"]["text_md"].startswith("Echo:")
    assert client.post(f"/api/skills/{sid}/run", json={"doc_ids": ["nope"]}).status_code == 404

    a = client.post("/api/automations", json={"name": "Doors", "prompt": "How many doors?", "doc_ids": [DOC],
                                              "interval_minutes": 60})
    assert a.status_code == 201
    aid = a.json()["id"]
    assert a.json()["last_report"] is None and a.json()["next_run_at"]
    assert client.get(f"/api/automations/{aid}/report.md").status_code == 404
    ran = client.post(f"/api/automations/{aid}/run").json()
    assert ran["last_report"]["ok"] and "Echo: How many doors?" in ran["last_report"]["markdown"]
    md = client.get(f"/api/automations/{aid}/report.md")
    assert md.status_code == 200 and md.text.startswith("# Doors")
    assert client.patch(f"/api/automations/{aid}", json={"enabled": False}).json()["next_run_at"] is None
    assert client.post("/api/automations", json={"name": "x", "prompt": "y", "doc_ids": ["nope"]}).status_code == 404
    assert client.delete(f"/api/automations/{aid}").status_code == 204
    assert client.get(f"/api/automations/{aid}").status_code == 404


def test_scheduler_runs_only_due_and_survives_failures(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from server import chats_routes, db
    monkeypatch.setattr(skills_routes, "validate_answer", lambda a: None)
    a = client.post("/api/automations", json={"name": "A", "prompt": "q", "doc_ids": [DOC], "interval_minutes": 10}).json()

    def boom(*a, **k):
        raise RuntimeError("engine down")
    monkeypatch.setattr(chats_routes, "ENGINE", boom)

    async def go():
        pool = await db.get_pool()
        assert await skills_routes.run_due(pool) == 0  # not due yet
        later = datetime.now(timezone.utc) + timedelta(minutes=11)
        assert await skills_routes.run_due(pool, later) == 1
        assert await skills_routes.run_due(pool, datetime.now(timezone.utc) + timedelta(minutes=5)) == 0  # just ran
    client.portal.call(go)
    rep = client.get(f"/api/automations/{a['id']}").json()["last_report"]
    assert rep["ok"] is False and "failed" in rep["markdown"]


def test_findings_message_falls_back_to_text_and_title(client, monkeypatch):
    """Regression: engine findings carry `text`/`title` instead of `message`; the API must never return an empty message."""
    raw = [{"rule_id": RULE, "item_ids": ["d1"], "severity": "suggestion", "text": "Only one exit found."},
           {"rule_id": RULE, "item_ids": ["d2"], "severity": "suggestion", "title": "Narrow door"}]
    monkeypatch.setattr(findings_routes, "_engine_run", lambda: (lambda doc_id: raw))
    fs = client.post("/api/findings/run", json={"doc_id": DOC}).json()["findings"]
    assert sorted(f["message"] for f in fs) == ["Narrow door", "Only one exit found."]
    assert all(f["message"] for f in client.get("/api/findings").json()["findings"])


def test_report_pdf_download(client, monkeypatch):
    from server import chats_routes
    monkeypatch.setattr(chats_routes, "ENGINE", fake_answer)
    monkeypatch.setattr(skills_routes, "validate_answer", lambda a: None)
    a = client.post("/api/automations", json={"name": "Doors", "prompt": "How many doors?", "doc_ids": [DOC]}).json()
    assert client.get(f"/api/automations/{a['id']}/report.pdf").status_code == 404  # no report yet
    client.post(f"/api/automations/{a['id']}/run")
    r = client.get(f"/api/automations/{a['id']}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    from pdfminer.high_level import extract_text
    import io
    assert "Echo: How many doors?" in extract_text(io.BytesIO(r.content))


def test_scheduler_catches_up_after_restart_and_never_double_runs(client, monkeypatch):
    """State lives in PostgreSQL: a fresh scheduler (new container) runs what fell due while down, once."""
    from datetime import datetime, timedelta, timezone
    from server import chats_routes, db
    monkeypatch.setattr(chats_routes, "ENGINE", fake_answer)
    monkeypatch.setattr(skills_routes, "validate_answer", lambda a: None)
    a = client.post("/api/automations", json={"name": "A", "prompt": "q", "doc_ids": [DOC], "interval_minutes": 1}).json()

    async def go():
        pool = await db.get_pool()
        await pool.execute("update automations set created_at = now() - interval '2 hours' where id=$1::uuid", a["id"])
        t = asyncio.create_task(skills_routes.scheduler(period=0.2, first=0.05))  # the "restarted" scheduler
        await asyncio.sleep(1.0)
        t.cancel()
        # two concurrent due-checks: the claim lets exactly one of them run it
        await pool.execute("update automations set last_run_at = now() - interval '2 hours' where id=$1::uuid", a["id"])
        later = datetime.now(timezone.utc)
        res = await asyncio.gather(skills_routes.run_due(pool, later), skills_routes.run_due(pool, later))
        return sorted(res)
    assert client.portal.call(go) == [0, 1]
    got = client.get(f"/api/automations/{a['id']}").json()
    assert got["last_report"]["ok"] and got["last_run_at"]
