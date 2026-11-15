"""Upload metadata must survive ingestion, independently of generated file formats."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server import files_routes as routes


@pytest.mark.parametrize("fmt", [ext.lstrip(".") for ext in routes.UPLOAD_EXT])
def test_persist_all_upload_formats(tmp_path, monkeypatch, fmt):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    pool = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(routes.db, "get_pool", AsyncMock(return_value=pool))
    save = AsyncMock()
    monkeypatch.setattr(routes.artifact_store, "save_doc", save)
    doc_id = "uploads__format-test"
    art = tmp_path / doc_id
    art.mkdir()
    # Raster normalization can replace files while retaining the original format.
    derived = "png" if fmt in ("jpg", "jpeg") else fmt
    files = {derived: "artifacts/uploads/input." + derived}
    (art / "doc.json").write_text(json.dumps({"formats": [fmt], "files": files, "pages": 3}))
    asyncio.run(routes._persist(doc_id))
    sql, *args = pool.execute.await_args.args
    assert "formats=$4" in sql
    assert args == [doc_id, 3, json.dumps(files), [fmt]]
    save.assert_awaited_once_with(pool, doc_id)


@pytest.mark.parametrize("formats", [None, [], ["dxf", "pdf"]])
def test_legacy_and_multiformat_sidecars(tmp_path, monkeypatch, formats):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    pool = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(routes.db, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(routes.artifact_store, "save_doc", AsyncMock())
    art = tmp_path / "uploads__legacy"
    art.mkdir()
    meta = {"files": {"dxf": "input.dxf", "pdf": "input.pdf"}}
    if formats is not None:
        meta["formats"] = formats
    (art / "doc.json").write_text(json.dumps(meta))
    asyncio.run(routes._persist(art.name))
    assert pool.execute.await_args.args[2] == 1
    assert pool.execute.await_args.args[4] == ["dxf", "pdf"]


@pytest.mark.parametrize("fmt", [ext.lstrip(".") for ext in routes.UPLOAD_EXT])
def test_postgres_round_trip_replaces_stale_formats(schema_url, tmp_path, monkeypatch, fmt):
    import asyncpg
    from server import config

    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    save = AsyncMock()
    monkeypatch.setattr(routes.artifact_store, "save_doc", save)
    art = tmp_path / "uploads__roundtrip"
    art.mkdir()
    files = {"png" if fmt in ("jpg", "jpeg") else fmt: "input"}
    (art / "doc.json").write_text(json.dumps({"formats": [fmt], "files": files, "pages": 2}))

    async def run():
        conn = await asyncpg.connect(config.database_url())
        try:
            await conn.execute("create temporary table documents "
                               "(doc_id text primary key, pages int, files jsonb, formats text[])")
            await conn.execute("insert into documents values ($1, 1, '{}'::jsonb, array['stale'])", art.name)
            monkeypatch.setattr(routes.db, "get_pool", AsyncMock(return_value=conn))
            await routes._persist(art.name)
            row = await conn.fetchrow("select pages, files, formats from documents where doc_id=$1", art.name)
            assert row["formats"] == [fmt]
            assert row["pages"] == 2 and json.loads(row["files"]) == files
            save.assert_awaited_once_with(conn, art.name)
        finally:
            await conn.close()

    asyncio.run(run())
