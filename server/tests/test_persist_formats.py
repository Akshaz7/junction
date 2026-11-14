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
