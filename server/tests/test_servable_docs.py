"""Docs without data are hidden (HIDE_EMPTY_DOCS=1); dataset docs stored in PostgreSQL are restored lazily;
questions on a document with nothing to answer from are refused at once, $0, with no model call."""
import asyncio
import json
import time

import asyncpg
import pytest
from fastapi.testclient import TestClient

from server import artifact_store, config
from server.migrate import apply_migrations


@pytest.fixture
def env(schema_url, tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    art.mkdir()
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("HIDE_EMPTY_DOCS", "1")
    monkeypatch.setenv("ENGINE_IMPL", "real")
    monkeypatch.setattr(artifact_store, "_servable_cache", (0.0, set()))
    monkeypatch.setattr(artifact_store, "_restored", set())

    async def prep():
        c = await asyncpg.connect(config.database_url())
        await apply_migrations(c)
        for did, src in [("src_a__full", "src_a"), ("src_a__empty", "src_a"), ("src_a__baked", "src_a")]:
            await c.execute("insert into documents (doc_id, source, title, kind, formats, pages, licence, credit, heldout, files) "
                            "values ($1,$2,$3,'raster','{png}',1,'x','x',false,'{}'::jsonb)", did, src, did)
        await c.close()
    asyncio.run(prep())
    return art


def _png():
    import io

    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(b, "PNG")
    return b.getvalue()


PM = {"doc_id": "src_a__full", "page": 1, "image": {"w": 40, "h": 30}, "scale": {"m_per_px": 0.05},
      "items": [{"item_id": "door-001", "kind": "door", "label": None, "bbox_px": [1, 1, 5, 9], "props": {}, "conf": 0.9}]}


def test_hidden_listing_lazy_restore_and_fast_refusal(env, monkeypatch):
    art = env
    baked = art / "src_a__baked"
    baked.mkdir()
    (baked / "page-1.png").write_bytes(_png())
    (baked / "planmap-1.json").write_text(json.dumps(PM))
    (art / "src_a__empty").mkdir()
    (art / "src_a__empty" / "page-1.png").write_bytes(_png())  # preview but nothing to answer from

    async def store():  # src_a__full lives only in PostgreSQL
        c = await asyncpg.connect(config.database_url())
        for n, d in [("page-1.png", _png()), ("planmap-1.json", json.dumps(PM).encode()),
                     ("source.pdf", b"%PDF-1.4 original")]:
            await c.execute("insert into doc_artifacts (doc_id, name, content_type, data, size) values ($1,$2,'x',$3,$4)",
                            "src_a__full", n, d, len(d))
        await c.close()
    asyncio.run(store())

    from server.app import app
    with TestClient(app) as c:
        body = c.get("/api/docs").json()
        ids = {d["doc_id"] for s in body["sources"] for d in s["docs"]}
        assert ids == {"src_a__full", "src_a__baked"} and body["total"] == 2
        assert "src_a__empty" not in ids
        # lazy restore of a dataset doc stored in PostgreSQL
        assert c.get("/api/docs/src_a__full/pages/1.png").status_code == 200
        assert (art / "src_a__full" / "planmap-1.json").is_file()
        # "open original": the source file is served from PostgreSQL when the container does not hold it
        r = c.get("/api/docs/src_a__full/source")
        assert r.status_code == 200 and r.content == b"%PDF-1.4 original"
        assert c.get("/api/docs/src_a__baked/source").status_code == 404  # nothing stored: honest 404
        # Hidden documents cannot be selected for a question.
        chat = c.post("/api/chats", json={"doc_ids": ["src_a__empty"]}).json()
        assert c.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors?"}).status_code == 404
        # With empty documents listed locally, the fast, free refusal still applies.
        monkeypatch.setenv("HIDE_EMPTY_DOCS", "0")
        t = time.time()
        r = c.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors are there?"})
        assert time.time() - t < 1.0
        ans = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:") and '"answer_id"' in line][-1]
        assert ans["answer"]["abstained"] is True
        assert ans["cost"]["usd_total"] == 0
        assert "no readable drawing data" in ans["answer"]["text_md"]
        # and a doc with data still answers from the plan map
        chat = c.post("/api/chats", json={"doc_ids": ["src_a__baked"]}).json()
        r = c.post(f"/api/chats/{chat['id']}/messages", json={"content": "How many doors are there?"})
        assert "1 door" in r.text


def test_restored_docs_are_evicted_least_recently_used_first(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    for i, name in enumerate(["a__old", "a__mid", "a__new", "a__baked"]):
        d = tmp_path / name
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x" * 1000)
        if name != "a__baked":  # baked docs carry no .restored marker
            (d / ".restored").touch()
            os.utime(d / ".restored", (1000 + i, 1000 + i))
    gone = artifact_store.evict_restored(keep="a__new", cap=2500)
    assert gone == ["a__old"]  # 3 restored docs (3 KB + markers) -> drop only the oldest to get under 2.5 KB
    assert (tmp_path / "a__baked").is_dir() and (tmp_path / "a__new").is_dir() and not (tmp_path / "a__old").exists()
    assert artifact_store.evict_restored(keep="a__new", cap=0) == ["a__mid"]  # keep= and baked docs always survive
    assert (tmp_path / "a__new").is_dir() and (tmp_path / "a__baked").is_dir()
