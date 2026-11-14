"""Durable storage for uploaded documents: files under artifacts/<doc_id>/ are mirrored to PostgreSQL
(table doc_artifacts, bytea) and restored to disk when the container starts fresh.

Aiven Runtime disk is ephemeral, so after a redeploy/restart an upload exists only in the database. Per document we keep
at most MAX_DOC_BYTES (page images dominate); thumbnails, plan maps, text, scene and the original go first.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from . import config

MAX_DOC_BYTES = int(os.environ.get("MAX_DOC_BYTES", 60 * 1024 * 1024))
ORIGINAL = "__original__/"
SKIP = {"ingest.json.tmp"}
_restored: set[str] = set()


def _priority(name: str) -> int:
    if name.startswith(ORIGINAL):
        return 0
    if name in ("doc.json", "ingest.json", "text.json", "scene.json", "pages.json") or name.startswith("planmap-"):
        return 1
    if name.endswith(".thumb.png") or name.startswith("text-"):
        return 2
    if name.startswith("scene."):
        return 3
    return 4  # page images


def doc_files(doc_id: str) -> list[tuple[str, Path]]:
    """(stored name, path) for everything worth keeping, most important first, within the size cap."""
    art = config.artifacts_dir()
    d = art / doc_id
    out: list[tuple[str, Path]] = []
    if d.is_dir():
        for f in d.rglob("*"):
            if f.is_file() and f.name not in SKIP and "tmp" not in f.relative_to(d).parts and not f.name.startswith(".done"):
                out.append((str(f.relative_to(d)), f))
    doc = d / "doc.json"
    if doc.is_file():
        import json
        for rel in (json.loads(doc.read_text()).get("files") or {}).values():
            p = config.REPO / rel
            if p.is_file():
                out.append((ORIGINAL + p.name, p))
    out.sort(key=lambda x: (_priority(x[0]), x[1].stat().st_size))
    kept, total = [], 0
    for name, p in out:
        sz = p.stat().st_size
        if total + sz > MAX_DOC_BYTES and _priority(name) > 1:
            continue
        total += sz
        kept.append((name, p))
    return kept


async def save_doc(pool, doc_id: str) -> int:
    """Upsert every file of the document. Returns bytes stored."""
    n = 0
    for name, p in doc_files(doc_id):
        data = p.read_bytes()
        ct = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        await pool.execute(
            "insert into doc_artifacts (doc_id, name, content_type, data, size) values ($1,$2,$3,$4,$5) "
            "on conflict (doc_id, name) do update set data=excluded.data, content_type=excluded.content_type, "
            "size=excluded.size, created_at=now()", doc_id, name, ct, data, len(data))
        n += len(data)
    return n


async def restore_doc(pool, doc_id: str) -> int:
    """Write the stored files of a document back to disk (skips files that exist). Returns files written."""
    art = config.artifacts_dir()
    written = 0
    names = [r["name"] for r in await pool.fetch("select name from doc_artifacts where doc_id=$1", doc_id)]
    for name in names:
        dest = (art / "uploads" / name[len(ORIGINAL):]) if name.startswith(ORIGINAL) else art / doc_id / name
        if dest.exists():
            continue
        row = await pool.fetchrow("select data from doc_artifacts where doc_id=$1 and name=$2", doc_id, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes(row["data"]))
        written += 1
    return written


async def ensure_doc(doc_id: str) -> None:
    """Make sure an uploaded document's files are on disk (cheap no-op for dataset docs and after the first call)."""
    if not doc_id.startswith("uploads__") or doc_id in _restored:
        return
    if (config.artifacts_dir() / doc_id / "doc.json").is_file() and (config.artifacts_dir() / doc_id / "ingest.json").is_file():
        _restored.add(doc_id)
        return
    from . import db
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        await restore_doc(pool, doc_id)
        _restored.add(doc_id)
    except Exception as e:  # noqa: BLE001 - never break a request over a cache restore
        print("restore failed:", doc_id, repr(e)[:200])


async def restore_all() -> int:
    """Startup: pull every uploaded document back to disk, newest first."""
    from . import db
    pool = await db.get_pool()
    if pool is None:
        return 0
    n = 0
    for r in await pool.fetch("select distinct doc_id from doc_artifacts order by doc_id"):
        await ensure_doc(r["doc_id"])
        n += 1
    return n
