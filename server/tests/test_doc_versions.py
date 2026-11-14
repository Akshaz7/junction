"""S-16: real series remain addressable when only their latest issues are seeded."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import config, db, docmeta_store, docs_routes, files_routes
from server.migrate import apply_migrations
from server.seed import seed_documents


# The three real sheets shipped by deploy/build_demo_artifacts.py (CC-BY-SA).
SERIES_IDS = (
    "vacation-rental--s400-9872c2",
    "vacation-rental--s401-9b69ee",
    "vacation-rental--a100-8f1f68",
)


def client_for_routes():
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await db.close_pool()

    app = FastAPI(lifespan=lifespan)
    app.include_router(docs_routes.router)
    app.include_router(files_routes.router)
    return TestClient(app)


@pytest.fixture
def real_series():
    art = config.REPO / "artifacts"
    series, records = [], {}
    for sid in SERIES_IDS:
        path = art / "series" / f"{sid}.json"
        if not path.is_file():
            pytest.skip(f"real series artifacts unavailable: {sid}")
        s = json.loads(path.read_text())
        series.append(s)
        for v in s["versions"]:
            doc_id = v["doc_id"]
            manifest = art / doc_id / "doc.json"
            page = manifest.parent / "page-1.png"
            if not manifest.is_file() or not page.is_file():
                pytest.skip(f"real revision artifacts unavailable: {doc_id}")
            rec = json.loads(manifest.read_text())
            source = docmeta_store.source_file(rec)
            if source is None:
                pytest.skip(f"real revision original unavailable: {doc_id}")
            records[doc_id] = (rec, page, source)
    return series, records


@pytest.mark.parametrize("metadata_source", ["manifests", "registry"])
def test_every_version_of_three_real_series(schema_url, real_series, tmp_path, monkeypatch, metadata_source):
    series, records = real_series
    art = tmp_path / "artifacts"
    (art / "series").mkdir(parents=True)
    for s in series:
        (art / "series" / f"{s['series_id']}.json").write_text(json.dumps(s))
    for doc_id, (rec, page, _) in records.items():
        d = art / doc_id
        d.mkdir()
        (d / "page-1.png").symlink_to(page)
        if metadata_source == "manifests":
            (d / "doc.json").write_text(json.dumps(rec))
    if metadata_source == "registry":
        (art / "registry.jsonl").write_text("\n".join(json.dumps(r[0]) for r in records.values()))
    # Deliberately omit docmeta.json too: issue date/size must fall back to the
    # matching version entry, never the newest issue or the DB insertion time.
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))

    async def prep():
        conn = await asyncpg.connect(config.database_url())
        try:
            await apply_migrations(conn)
            latest = [records[s["versions"][-1]["doc_id"]][0] for s in series]
            await seed_documents(conn, latest)
            assert await conn.fetchval("select count(*) from documents") == 3
        finally:
            await conn.close()

    asyncio.run(prep())
    with client_for_routes() as client:
        for s in series:
            for index, version in enumerate(s["versions"], 1):
                doc_id = version["doc_id"]
                rec, page, original = records[doc_id]
                url = f"/api/docs/{doc_id}"
                response = client.get(url)
                assert response.status_code == 200, (doc_id, response.text)
                doc = response.json()
                for field in ("doc_id", "title", "files", "pages", "licence", "credit"):
                    assert doc[field] == rec[field]
                assert doc["series_id"] == s["series_id"]
                assert doc["version_index"] == index
                assert doc["version_count"] == len(s["versions"])
                assert doc["size"] == version["size_bytes"] == original.stat().st_size
                assert doc["date"] == doc["updated_at"] == version["date"]
                assert [v["doc_id"] for v in doc["versions"]] == [v["doc_id"] for v in s["versions"]]
                for path in ("pages/1/image", "pages/1.png", "files/page-1.png"):
                    image = client.get(f"{url}/{path}")
                    assert image.status_code == 200, (doc_id, path)
                    assert image.content == page.read_bytes()
                source = client.get(f"{url}/source")
                assert source.status_code == 200, doc_id
                assert source.content == original.read_bytes()
        assert client.get("/api/docs/unknown-revision").status_code == 404
        assert client.get("/api/docs/unknown-revision/source").status_code == 404


def test_manifest_without_database_and_missing_original(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=None))
    doc_id = "generated__demo-revision"
    d = tmp_path / doc_id
    d.mkdir()
    rec = {"doc_id": doc_id, "title": "Revision generated for demo", "source": "generated", "files": {}}
    (d / "doc.json").write_text(json.dumps(rec))
    with client_for_routes() as client:
        assert client.get(f"/api/docs/{doc_id}").json()["title"] == rec["title"]
        response = client.get(f"/api/docs/{doc_id}/source")
        assert response.status_code == 404
        assert response.json()["status"] == "not_built"
        assert client.get("/api/docs/no-record").status_code == 503


def test_database_row_wins_over_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    doc_id = "generated__demo-revision"
    rec = {"doc_id": doc_id, "title": "Database generated for demo", "source": "generated", "files": "{}"}
    pool = SimpleNamespace(fetchrow=AsyncMock(return_value=rec))
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=pool))
    d = tmp_path / doc_id
    d.mkdir()
    (d / "doc.json").write_text(json.dumps(dict(rec, title="Stale generated for demo", files={})))
    with client_for_routes() as client:
        assert client.get(f"/api/docs/{doc_id}").json()["title"] == rec["title"]


def test_registry_reload_and_mismatched_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(db, "get_pool", AsyncMock(return_value=SimpleNamespace(fetchrow=AsyncMock(return_value=None))))
    doc_id = "generated__demo-revision"
    rec = {"doc_id": doc_id, "title": "Registry generated for demo", "source": "generated", "files": {}}
    d = tmp_path / doc_id
    d.mkdir()
    (d / "doc.json").write_text(json.dumps(dict(rec, doc_id="another-document")))
    registry = tmp_path / "registry.jsonl"
    registry.write_text(json.dumps(rec))
    with client_for_routes() as client:
        assert client.get(f"/api/docs/{doc_id}").json()["title"] == rec["title"]
        rec["title"] = "Changed registry generated for demo"
        registry.write_text(json.dumps(rec))
        assert client.get(f"/api/docs/{doc_id}").json()["title"] == rec["title"]
        assert client.get("/api/docs/%2E%2E").status_code == 400
