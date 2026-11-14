"""E-17 watch webhook and E-18 PDF report."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from engine import watch as W
from server import findings_routes, skills_routes
from server.report_pdf import markdown_to_pdf
from server.tests.test_contract import DOC, dirs  # noqa: F401
from server.tests.test_skills_findings import fake_answer

SECRET = "whsec_test"


@pytest.fixture
def client(schema_url, dirs, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("AUTOMATIONS", "0")
    monkeypatch.setenv("WATCH_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(findings_routes, "_engine_run", lambda: (lambda doc_id: []))
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


def event(url):
    return {"event": "change.detected", "id": "evt_1", "created_at": "2026-11-14T10:00:00Z",
            "data": {"change": {"id": "chg_1", "monitor_id": "mon_1", "url": url, "title": "Page changed",
                                "summary": "The visible text changed.", "importance": "high"}}}


def test_webhook_creates_feed_entry(client):
    url = next(iter(W.rule_sources()))
    raw = json.dumps(event(url)).encode()
    assert client.post("/api/watch/webhook", content=raw).status_code == 401
    bad = {"X-Context-Signature": W.sign(raw, "wrong")}
    assert client.post("/api/watch/webhook", content=raw, headers=bad).status_code == 401
    hdr = {"X-Context-Signature": W.sign(raw, SECRET), "X-Context-Id": "evt_1"}
    r = client.post("/api/watch/webhook", content=raw, headers=hdr)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["findings_rerun_docs"] == 1
    feed = client.get("/api/changes").json()["changes"]
    e = next(x for x in feed if x["type"] == "rule_change")
    assert e["summary"]["kind"] == "rule_change" and e["summary"]["url"] == url and e["summary"]["rule_ids"]
    assert client.post("/api/watch/webhook", content=raw, headers=hdr).json()["status"] == "duplicate"
    # shared-secret fallback
    raw2 = json.dumps({**event(url), "id": "evt_2"}).encode()
    assert client.post(f"/api/watch/webhook?secret={SECRET}", content=raw2).json()["status"] == "ok"
    assert client.post("/api/watch/webhook?secret=nope", content=raw2).status_code == 401


def test_signature_window():
    raw = b"{}"
    assert W.verify_signature(raw, W.sign(raw, "s", 1000), "s", now=1100)
    assert not W.verify_signature(raw, W.sign(raw, "s", 1000), "s", now=2000)
    assert not W.verify_signature(raw, "garbage", "s")


def test_findings_keep_engine_text(client, monkeypatch):
    rule = "fi-acc-door-clear-width"
    raw = [{"rule_id": rule, "item_ids": ["door-001"], "severity": "violation", "title": "Narrow door",
            "text": "Door 700 mm wide.", "storey": "1", "source": {"type": "rule"}}]
    monkeypatch.setattr(findings_routes, "_engine_run", lambda: (lambda doc_id: raw))
    f = client.post("/api/findings/run", json={"doc_id": DOC}).json()["findings"][0]
    assert f["message"] == "Door 700 mm wide." and f["detail"]["title"] == "Narrow door"


def test_report_pdf(client, monkeypatch):
    from server import chats_routes
    monkeypatch.setattr(chats_routes, "ENGINE", fake_answer)
    monkeypatch.setattr(skills_routes, "validate_answer", lambda a: None)
    aid = client.post("/api/automations", json={"name": "Door report", "prompt": "How many doors?",
                                                "doc_ids": [DOC]}).json()["id"]
    assert client.get(f"/api/automations/{aid}/report.pdf").status_code == 404
    client.post(f"/api/automations/{aid}/run")
    r = client.get(f"/api/automations/{aid}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    from pdfminer.high_level import extract_text
    text = extract_text(io.BytesIO(r.content))
    assert "Door report" in text and "Echo: How many doors?" in text


def test_pdf_many_pages_and_odd_chars():
    pdf = markdown_to_pdf("# T\n" + "\n".join(f"line (x) \\ é ✓ {i}" for i in range(200)))
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page ") >= 3
