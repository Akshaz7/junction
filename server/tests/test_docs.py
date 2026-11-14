"""S-02 tests: migrations, seed, /api/docs. Need local Postgres (make db-up); skipped if absent."""
import asyncio
import json

import asyncpg
import pytest
from fastapi.testclient import TestClient

from server import config, db
from server.migrate import apply_migrations
from server.seed import read_registry, seed_documents

FAKE = [
    {"doc_id": "src_a__one", "source": "src_a", "title": "One", "kind": "ifc", "formats": ["ifc"],
     "pages": 1, "licence": "CC0", "credit": "x", "heldout": False, "files": {"ifc": "data/src_a/one.ifc"}},
    {"doc_id": "src_a__two", "source": "src_a", "title": "Two", "kind": "pdf", "formats": ["pdf"],
     "pages": 3, "licence": None, "credit": None, "heldout": True, "files": {}},
    {"doc_id": "src_b__three", "source": "src_b", "title": "Three", "kind": "raster", "formats": ["png"],
     "pages": 1, "licence": None, "credit": None, "heldout": False, "files": {}},
]
TABLES = {"documents", "chats", "messages", "answers", "changes", "model_calls", "bench_runs", "rules", "findings"}


def test_migrations_seed_and_docs(schema_url, tmp_path):
    reg = tmp_path / "registry.jsonl"
    reg.write_text("\n".join(json.dumps(d) for d in FAKE) + "\n")

    async def prep():
        c = await asyncpg.connect(config.database_url())
        first = await apply_migrations(c)
        second = await apply_migrations(c)
        tables = {r["tablename"] for r in await c.fetch(
            "select tablename from pg_tables where schemaname=$1", schema_url)}
        n = await seed_documents(c, read_registry(reg))
        n2 = await seed_documents(c, read_registry(reg))  # idempotent
        await c.close()
        return first, second, tables, n, n2
    first, second, tables, n, n2 = asyncio.run(prep())
    assert first == ["001_init.sql", "002_notify.sql", "003_scene_edits.sql", "004_skills_automations.sql", "005_doc_artifacts.sql", "006_design_versions.sql", "007_projects.sql"] and second == []
    assert TABLES <= tables
    assert n == n2 == 3

    from server.app import app
    with TestClient(app) as c:
        r = c.get("/api/docs")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert [s["source"] for s in body["sources"]] == ["src_a", "src_b"]
        assert [s["count"] for s in body["sources"]] == [2, 1]
        assert body["sources"][0]["docs"][0]["files"] == {"ifc": "data/src_a/one.ifc"}
        d = c.get("/api/docs/src_a__two").json()
        assert d["pages"] == 3 and d["heldout"] is True
        assert c.get("/api/docs/nope").status_code == 404


def test_docs_metadata_folders_and_source(schema_url, tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    (art / "series").mkdir(parents=True)
    pdf = tmp_path / "data" / "opening_design" / "Proj" / "20190102 Issue" / "A501 Sections.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 x")
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setattr("server.config.REPO", tmp_path)
    rec = {"doc_id": "opening_design__proj-a501", "source": "opening_design", "title": "A501 Sections", "kind": "pdf",
           "formats": ["pdf"], "pages": 1, "licence": None, "credit": None, "heldout": False,
           "files": {"pdf": "data/opening_design/Proj/20190102 Issue/A501 Sections.pdf"}}
    other = dict(rec, doc_id="opening_design__proj-a501-v1", files={"pdf": "data/opening_design/Proj/20190101 Issue/A501 Sections.pdf"})
    (art / "series" / "s1.json").write_text(json.dumps({"series_id": "s1", "title": "A501", "versions": [
        {"doc_id": "opening_design__proj-a501-v1", "date": "2019-01-01", "size_bytes": 5, "label": "Version 1 · 2019-01-01"},
        {"doc_id": "opening_design__proj-a501", "date": "2019-01-02", "size_bytes": 10, "label": "Version 2 · 2019-01-02"}]}))
    (art / "docmeta.json").write_text(json.dumps({"opening_design__proj-a501": {"size_bytes": 10, "updated_at": "2019-01-02"}}))
    reg = tmp_path / "registry.jsonl"
    reg.write_text("\n".join(json.dumps(d) for d in (rec, other)) + "\n")

    async def prep():
        c = await asyncpg.connect(config.database_url())
        await apply_migrations(c)
        await seed_documents(c, read_registry(reg))
        await c.close()
    asyncio.run(prep())
    from server.app import app
    with TestClient(app) as c:
        d = c.get("/api/docs/opening_design__proj-a501").json()
        assert d["size"] == 10 and d["updated_at"] == "2019-01-02" and d["discipline"] == "Architecture"
        assert d["folder"] == "Proj/Architecture" and d["series_id"] == "s1" and d["version_index"] == 2 and d["version_count"] == 2
        assert [v["doc_id"] for v in d["versions"]] == ["opening_design__proj-a501-v1", "opening_design__proj-a501"]
        listed = c.get("/api/docs").json()["sources"][0]["docs"]
        assert all("folder" in x and "versions" in x for x in listed)
        tree = c.get("/api/folders").json()
        assert tree["total"] == 2 and tree["folders"][0]["name"] == "Proj" and tree["folders"][0]["children"][0]["name"] == "Architecture"
        assert tree["folders"][0]["children"][0]["count"] == 2
        r = c.get("/api/docs/opening_design__proj-a501/source")
        assert r.status_code == 200 and r.content == b"%PDF-1.4 x"
        assert c.get("/api/docs/nope/source").status_code == 404
