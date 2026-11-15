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
SOURCE_CHUNKS = "__source_chunks__/"
SOURCE_CHUNK_BYTES = 4 * 1024 * 1024
SKIP = {"ingest.json.tmp", ".restored"}
RESTORE_CAP = int(float(os.environ.get("RESTORE_CAP_MB", "400")) * 1024 * 1024)  # disk for docs restored from PostgreSQL
_restored: set[str] = set()


def _priority(name: str) -> int:
    if name.startswith(ORIGINAL) or name.startswith("source."):
        return 0
    if name in ("doc.json", "ingest.json", "text.json", "scene.json", "pages.json", "elements.json", "piping.json", "ifc-quantities.json", "wallgeom.json", "ifc-accuracy.json") or name.startswith("planmap-"):
        return 1
    if name.endswith(".thumb.png") or name.startswith("text-"):
        return 2
    if name.startswith("scene."):
        return 3
    return 4  # page images


def doc_files(doc_id: str, originals: bool = True) -> list[tuple[str, Path]]:
    """(stored name, path) for everything worth keeping, most important first, within the size cap."""
    art = config.artifacts_dir()
    d = art / doc_id
    out: list[tuple[str, Path]] = []
    if d.is_dir():
        for f in d.rglob("*"):
            if f.is_file() and f.name not in SKIP and "tmp" not in f.relative_to(d).parts and not f.name.startswith(".done"):
                out.append((str(f.relative_to(d)), f))
    doc = d / "doc.json"
    if originals and doc.is_file():
        import json
        meta = json.loads(doc.read_text())
        for rel in {**(meta.get("files") or {}), **(meta.get("original_files") or {})}.values():
            p = config.REPO / rel
            if p.is_file():
                out.append((ORIGINAL + p.name, p))
    out.sort(key=lambda x: (_priority(x[0]), x[1].stat().st_size))
    kept, total = [], 0
    for name, p in out:
        sz = p.stat().st_size
        if total + sz > MAX_DOC_BYTES and _priority(name) > 1:
            continue
        if _priority(name) > 0:  # the original (ifc/pdf) has its own place and must not crowd out previews and 3D
            total += sz
        kept.append((name, p))
    return kept


async def save_doc(pool, doc_id: str, originals: bool = True) -> int:
    """Upsert every file of the document. Returns bytes stored. originals=False leaves the source file (ifc/pdf) out."""
    import hashlib
    import json

    async def store(name, data, ct):
        await pool.execute(
            "insert into doc_artifacts (doc_id, name, content_type, data, size) values ($1,$2,$3,$4,$5) "
            "on conflict (doc_id, name) do update set data=excluded.data, content_type=excluded.content_type, "
            "size=excluded.size, created_at=now()", doc_id, name, ct, data, len(data))

    n = 0
    for name, p in doc_files(doc_id, originals):
        ct = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if name.startswith(ORIGINAL) and p.stat().st_size > SOURCE_CHUNK_BYTES:
            prefix = SOURCE_CHUNKS + p.name + "/"
            digest, count, size = hashlib.sha256(), 0, 0
            with p.open("rb") as source:
                while chunk := source.read(SOURCE_CHUNK_BYTES):
                    await store(prefix + f"{count:06d}", chunk, ct)
                    digest.update(chunk)
                    count += 1
                    size += len(chunk)
            # Publish the manifest last so an interrupted save is never restored
            # as a complete original. Each DB parameter stays at most 4 MiB.
            manifest = {"name": p.name, "chunks": count, "size": size, "sha256": digest.hexdigest()}
            await store(prefix + "manifest.json", json.dumps(manifest).encode(), "application/json")
            n += size
        else:
            data = p.read_bytes()
            await store(name, data, ct)
            n += len(data)
    return n


async def restore_doc(pool, doc_id: str) -> int:
    """Write the stored files of a document back to disk (skips files that exist). Returns files written."""
    art = config.artifacts_dir()
    written = 0
    names = [r["name"] for r in await pool.fetch("select name from doc_artifacts where doc_id=$1", doc_id)]
    for name in names:
        if name.startswith(SOURCE_CHUNKS):
            continue
        dest = (art / "uploads" / name[len(ORIGINAL):]) if name.startswith(ORIGINAL) else art / doc_id / name
        if dest.exists():
            continue
        row = await pool.fetchrow("select data from doc_artifacts where doc_id=$1 and name=$2", doc_id, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes(row["data"]))
        written += 1
    import hashlib
    import json
    for name in names:
        if not (name.startswith(SOURCE_CHUNKS) and name.endswith("/manifest.json")):
            continue
        row = await pool.fetchrow("select data from doc_artifacts where doc_id=$1 and name=$2", doc_id, name)
        manifest = json.loads(bytes(row["data"]))
        source_name = manifest["name"]
        if Path(source_name).name != source_name:
            raise ValueError("Invalid original filename in storage")
        dest = art / "uploads" / source_name
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".restore.tmp")
        digest, size = hashlib.sha256(), 0
        try:
            with tmp.open("wb") as target:
                for i in range(manifest["chunks"]):
                    part = await pool.fetchrow("select data from doc_artifacts where doc_id=$1 and name=$2",
                                               doc_id, name.rsplit("/", 1)[0] + f"/{i:06d}")
                    if part is None:
                        raise ValueError("The stored original is incomplete. Upload it again.")
                    chunk = bytes(part["data"])
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
                raise ValueError("The stored original failed its integrity check. Upload it again.")
            tmp.replace(dest)
            written += 1
        finally:
            tmp.unlink(missing_ok=True)
    return written


async def fetch_source(pool, doc_id: str) -> bool:
    """Restore only the original file (source.*) of a dataset doc, e.g. when its pages were baked into the image."""
    row = await pool.fetchrow("select name, data from doc_artifacts where doc_id=$1 and name like 'source.%' limit 1", doc_id)
    if not row:
        return False
    dest = config.artifacts_dir() / doc_id / row["name"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(row["data"]))
    return True


def _on_disk(doc_id: str) -> bool:
    d = config.artifacts_dir() / doc_id
    if doc_id.startswith("uploads__"):
        return (d / "doc.json").is_file() and (d / "ingest.json").is_file()
    return (d / "page-1.png").is_file()  # dataset docs: baked into the image, or restored from PostgreSQL earlier


def _touch(doc_id: str) -> None:
    m = config.artifacts_dir() / doc_id / ".restored"
    if m.is_file():
        try:
            os.utime(m)
        except OSError:
            pass


def evict_restored(keep: str | None = None, cap: int | None = None) -> list[str]:
    """Keep restored dataset docs under the disk cap: delete the least recently used ones. Docs baked into the image
    (no .restored marker) and uploads are never touched. Returns the evicted doc ids."""
    import shutil
    cap = RESTORE_CAP if cap is None else cap
    art = config.artifacts_dir()
    rows = []
    for m in art.glob("*__*/.restored"):
        d = m.parent
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        rows.append((m.stat().st_mtime, d.name, size))
    total = sum(r[2] for r in rows)
    out = []
    for _, name, size in sorted(rows):
        if total <= cap:
            break
        if name == keep or name.startswith("uploads__"):
            continue
        shutil.rmtree(art / name, ignore_errors=True)
        _restored.discard(name)
        total -= size
        out.append(name)
    return out


TOPUP = ("wallgeom.json", "ifc-quantities.json", "ifc-accuracy.json")  # small sidecars added after a doc was first stored


async def _topup(doc_id: str) -> None:
    """A doc already on disk (baked image or earlier restore) still gets sidecars that were backfilled to PostgreSQL later."""
    d = config.artifacts_dir() / doc_id
    missing = [n for n in TOPUP if not (d / n).exists()]
    if not missing or not d.is_dir():
        return
    from . import db
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        for n in missing:
            row = await pool.fetchrow("select data from doc_artifacts where doc_id=$1 and name=$2", doc_id, n)
            if row is not None:
                (d / n).write_bytes(bytes(row["data"]))
    except Exception as e:  # noqa: BLE001 - optional sidecars never break a request
        print("topup failed:", doc_id, repr(e)[:200])


async def ensure_doc(doc_id: str) -> None:
    """Make sure a document's files are on disk. Uploads and dataset docs both live in PostgreSQL (doc_artifacts) when
    they are not baked into the image; they are pulled back lazily on first use (cheap no-op afterwards)."""
    if doc_id in _restored:
        _touch(doc_id)
        return
    if _on_disk(doc_id):
        _restored.add(doc_id)
        _touch(doc_id)
        await _topup(doc_id)
        return
    from . import db
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        n = await restore_doc(pool, doc_id)
        if n or doc_id.startswith("uploads__"):
            _restored.add(doc_id)
        if n and not doc_id.startswith("uploads__"):
            (config.artifacts_dir() / doc_id / ".restored").touch()
            evict_restored(keep=doc_id)
    except Exception as e:  # noqa: BLE001 - never break a request over a cache restore
        print("restore failed:", doc_id, repr(e)[:200])


_SERVABLE_SQL = ("select doc_id from doc_artifacts group by doc_id having bool_or(name='page-1.png') and "
                 "bool_or(name='elements.json' or name like 'planmap-%' or name like 'text%')")
_servable_cache: tuple[float, set[str]] = (0.0, set())


def has_data_on_disk(doc_id: str) -> bool:
    """A preview image plus something to answer from (IFC elements, plan map or PDF text)."""
    d = config.artifacts_dir() / doc_id
    return (d / "page-1.png").is_file() and ((d / "elements.json").is_file() or any(d.glob("planmap-*.json"))
                                              or any(d.glob("text*.json")))


async def servable_ids(pool) -> set[str]:
    """Doc ids that can really be served from this server: baked on disk or stored in PostgreSQL (cached 60 s)."""
    import time
    global _servable_cache
    if time.monotonic() - _servable_cache[0] < 60 and _servable_cache[1]:
        return _servable_cache[1]
    ids = {r["doc_id"] for r in await pool.fetch(_SERVABLE_SQL)}
    d = config.artifacts_dir()
    if d.is_dir():
        ids |= {p.name for p in d.iterdir() if p.is_dir() and "__" in p.name and has_data_on_disk(p.name)}
    _servable_cache = (time.monotonic(), ids)
    return ids


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
