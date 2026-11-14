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
    assert first == ["001_init.sql"] and second == []
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
