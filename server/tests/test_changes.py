"""Changes feed built from REAL version series (artifacts/series) + PDF diff caches; no synthetic revisions."""
import json

import pytest
from fastapi.testclient import TestClient

SID = "proj--sheet-a1b2c3"
DOCS = [f"opening_design__proj-transfer-2019010{n}-a501" for n in (1, 2, 3)]
SERIES = {"series_id": SID, "title": "A501 Wall Sections", "project": "Proj", "discipline": "Architecture", "sheet": "A501",
          "versions": [{"doc_id": d, "date": f"2019-01-0{n}", "size_bytes": 1000 * n, "label": f"Version {n} · 2019-01-0{n}", "pages": 1}
                       for n, d in enumerate(DOCS, 1)]}
DIFF = {"doc_a": DOCS[0], "doc_b": DOCS[1], "source": "pdf-diff", "generated_for_demo": False, "note": "n", "series_id": SID,
        "pages": [{"page_a": 1, "page_b": 1, "image": {"w": 100, "h": 80}, "image_v1": {"w": 100, "h": 80}, "n_changes": 2}],
        "changes": [{"change_id": "c1", "type": "modified", "kind": "region", "description": "Text changed from 'A' to 'B'.",
                     "bbox_px_v1": [1, 2, 3, 4], "bbox_px_v2": [1, 2, 3, 4], "text_old": "A", "text_new": "B", "page": 1,
                     "page_v1": 1, "page_v2": 1},
                    {"change_id": "c2", "type": "added", "kind": "region", "description": "Content added in this region (no text change).",
                     "bbox_px_v1": None, "bbox_px_v2": [5, 6, 7, 8], "page": 1, "page_v1": 1, "page_v2": 1}]}


@pytest.fixture
def client(schema_url, tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    (art / "series" / "diffs").mkdir(parents=True)
    (art / "series" / f"{SID}.json").write_text(json.dumps(SERIES))
    (art / "series" / "diffs" / f"{SID}--1-2.json").write_text(json.dumps(DIFF))
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    from server import docmeta_store
    docmeta_store._cache.clear()
    from server.app import app
    with TestClient(app) as c:
        yield c


def test_feed_has_series_entries_checked_at_and_groups(client):
    body = client.get("/api/changes").json()
    feed = body["changes"]
    assert [e["id"] for e in feed] == [f"ser:{SID}:2", f"ser:{SID}:1"]  # newest first
    e = feed[1]
    assert e["type"] == "new_version" and e["doc_a"] == DOCS[0] and e["doc_b"] == DOCS[1]
    assert e["summary"]["n_changes"] == 2 and e["summary"]["source"] == "pdf-diff" and e["summary"]["generated_for_demo"] is False
    assert e["summary"]["headline"].startswith("2 changes: Text changed")
    assert feed[0]["summary"]["n_changes"] is None  # no diff cache for pair 2 -> honest "not computed"
    assert e["group"] == "earlier" and body["groups"] == [{"key": "earlier", "label": "Earlier", "ids": [f["id"] for f in feed]}]
    assert body["checked_at"].startswith("20")


def test_detail_comparison_and_page_param(client):
    d = client.get(f"/api/changes/ser:{SID}:1").json()
    assert d["source"] == "pdf-diff" and d["generated_for_demo"] is False and d["image"] == {"w": 100, "h": 80}
    assert d["v1"]["page_image"] == f"/api/docs/{DOCS[0]}/pages/1/image" and d["v2"]["label"].startswith("Version 2")
    ch = d["changes"]
    assert [c["n"] for c in ch] == [1, 2] and ch[0]["v1"]["bbox_px"] == [1, 2, 3, 4] and ch[1]["v1"] is None
    assert d["pages"] == [{"page": 1, "page_v1": 1, "page_v2": 1, "n_changes": 2}]
    assert client.get(f"/api/changes/ser:{SID}:1?page=9").json()["page"] == 1  # unknown page falls back
    nb = client.get(f"/api/changes/ser:{SID}:2").json()
    assert nb["status"] == "not_built" and nb["changes"] == []
    assert client.get(f"/api/changes/ser:{SID}:7").status_code == 404
    assert client.get("/api/changes/00000000-0000-0000-0000-000000000000").status_code == 404


def test_refresh_restamps_checked_at_and_rescans(client, tmp_path):
    t1 = client.get("/api/changes").json()["checked_at"]
    art = tmp_path / "artifacts" / "series"
    extra = dict(SERIES, series_id="other-series-1")
    (art / "other-series-1.json").write_text(json.dumps(extra))
    r = client.post("/api/changes/refresh").json()
    assert len(r["changes"]) == 4 and r["checked_at"] >= t1


def test_synthetic_revision_rows_are_purged_and_route_gone(schema_url, tmp_path, monkeypatch):
    import asyncio
    import asyncpg
    from server import config
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    from server.app import app
    with TestClient(app) as c:
        async def put():
            conn = await asyncpg.connect(config.database_url())
            await conn.execute("insert into changes (doc_a, doc_b, summary) values ('x@v1','x@v2','{}'::jsonb)")
            await conn.close()
        asyncio.run(put())
    with TestClient(app) as c:  # restart purges
        assert c.get("/api/changes").json()["changes"] == []
        assert c.get("/api/docs/x/revisions/v1/page-1.png").status_code == 404


def test_uploads_matching_a_series_become_new_versions(client, monkeypatch):
    monkeypatch.setenv("INGEST", "0")
    r = client.post("/api/upload", files={"file": ("A501 Wall Sections.png", b"\x89PNG")})
    doc = r.json()["doc_id"]
    feed = client.get("/api/changes").json()["changes"]
    top = feed[0]
    assert top["id"] == f"upl:{doc}" and top["type"] == "new_version" and top["doc_a"] == DOCS[-1] and top["doc_b"] == doc
    assert top["group"] == "today"
    assert client.get(f"/api/changes/{top['id']}").json()["type"] == "new_version"


def test_unmatched_upload_is_new_document(client, monkeypatch):
    monkeypatch.setenv("INGEST", "0")
    doc = client.post("/api/upload", files={"file": ("zzz plan.png", b"\x89PNG")}).json()["doc_id"]
    top = client.get("/api/changes").json()["changes"][0]
    assert top["type"] == "new_document" and top["doc_b"] == doc
