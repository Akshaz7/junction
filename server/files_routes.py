"""Document files, upload, bench and costs (CONTRACT 5.9)."""
import asyncio
import importlib.util
import json
import os
from datetime import datetime, timezone
import re
import signal
import sys
import tempfile
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import artifact_store, config, db
from .live import publish
from .upload_validation import UPLOAD_EXT, extension_error, validate_header


async def _restore(request: Request):
    """Uploaded docs live in PostgreSQL too: bring their files back to disk after a container restart."""
    d = request.path_params.get("doc_id")
    if d and SAFE_ID.match(d):
        await artifact_store.ensure_doc(d)
        pool = await db.get_pool()
        if pool is not None:
            from .taught_store import restore_materialized
            await restore_materialized(pool, d)


router = APIRouter(prefix="/api", dependencies=[Depends(_restore)])

SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")
FILE_NAMES = {"scene.glb", "scene.usdz", "scene.json", "elements.json", "text.json", "ingest.json"}
THUMB = re.compile(r"^(page-\d+\.thumb\.png|page-\d+\.png|planmap-\d+\.json|text-\d+\.json)$")
MAX_UPLOAD = 100 * 1024 * 1024
INGEST_TIMEOUT = 5 * 60


def _doc_dir(doc_id: str):
    if not SAFE_ID.fullmatch(doc_id) or doc_id in {".", ".."}:
        raise HTTPException(400, "bad doc_id")
    return config.artifacts_dir() / doc_id


def _not_built(what: str, status_code=404):
    return JSONResponse({"status": "not_built", "detail": f"{what} not available"}, status_code=status_code)


@router.get("/docs/{doc_id}/pages/{n}/image")
async def page_image(doc_id: str, n: int):
    f = _doc_dir(doc_id) / f"page-{n}.png"
    if not f.is_file():
        return _not_built(f"page {n} image")
    return FileResponse(f, media_type="image/png")


@router.get("/docs/{doc_id}/evidence/{name}")
async def scale_evidence(doc_id: str, name: str):
    from .scale_evidence import crop_path
    _doc_dir(doc_id)  # same document-id validation as other file endpoints
    path = crop_path(config.artifacts_dir(), doc_id, name)
    if path is None:
        return _not_built("scale evidence")
    return FileResponse(path, media_type="image/png")


@router.get("/docs/{doc_id}/planmap/{n}")
async def planmap(doc_id: str, n: int):
    f = _doc_dir(doc_id) / f"planmap-{n}.json"
    if not f.is_file():
        return _not_built(f"plan map {n}")
    return FileResponse(f, media_type="application/json")


@router.get("/docs/{doc_id}/scene")
async def scene(doc_id: str):
    await _taught_scene(doc_id)
    # S-04 will trigger extrusion here when no scene exists.
    f = _doc_dir(doc_id) / "scene.json"
    if not f.is_file():
        return _not_built("scene")
    return FileResponse(f, media_type="application/json", headers={'Cache-Control': 'no-store'})


async def _taught_scene(doc_id):
    from .taught_scene import ensure
    try:
        await ensure(doc_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get('/docs/{doc_id}/knowledge-graph')
async def knowledge_graph(doc_id: str):
    _doc_dir(doc_id)
    from engine.kg import build
    return await asyncio.to_thread(build, doc_id, config.artifacts_dir())


@router.get("/docs/{doc_id}/files/{name}")
async def doc_file(doc_id: str, name: str):
    if name not in FILE_NAMES and not THUMB.match(name):
        raise HTTPException(404, "unknown file")
    if name.startswith('scene.'):
        await _taught_scene(doc_id)
        if name == 'scene.usdz':
            manifest = _doc_dir(doc_id) / 'scene.json'
            if manifest.is_file() and not json.loads(manifest.read_text()).get('usdz'):
                return _not_built('Updated AR model')
    f = _doc_dir(doc_id) / name
    if not f.is_file():
        if name == "elements.json" or re.match(r"^text-\d+\.json$", name):
            # Optional sidecars the viewer probes for every document: an empty payload, not a console-visible 404.
            return JSONResponse({"status": "not_built", "elements": [], "words": []})
        return _not_built(name)
    return FileResponse(f, headers={'Cache-Control': 'no-store'})


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "upload"


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    from pathlib import Path
    name = Path((file.filename or "upload").replace("\\", "/")).name
    ext = Path(name).suffix.lower()
    if error := extension_error(ext):
        raise HTTPException(415, error)
    # UploadFile already spools multipart data. Copy in bounded chunks, avoiding a
    # second upload-sized allocation in a 512 MB API container.
    import hashlib
    digest = hashlib.sha256()
    updir = config.artifacts_dir() / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=updir, prefix=".upload-", suffix=".tmp", delete=False) as tmp:
        pending = Path(tmp.name)
        size = 0
        header = b""
        try:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, f"File too large. Maximum upload size is {MAX_UPLOAD // (1024 * 1024)} MiB ({MAX_UPLOAD} bytes). Export a smaller file or split the model.")
                if len(header) < 65536:
                    header += chunk[:65536 - len(header)]
                digest.update(chunk)
                tmp.write(chunk)
            if not size:
                raise HTTPException(400, "File is empty. Upload a non-empty pdf, png, jpg, dxf or ifc file.")
            try:
                validate_header(ext, header)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
    pool = await db.get_pool()
    if pool is None:
        pending.unlink(missing_ok=True)
        raise HTTPException(503, "database unavailable")
    doc_id = f"uploads__{_slug(Path(name).stem)[:100]}-{uuid.uuid4().hex[:12]}"
    stored = updir / f"{doc_id}{ext}"
    pending.replace(stored)
    fmt = ext.lstrip(".")
    kind = UPLOAD_EXT[ext]
    rel = str(stored.relative_to(config.REPO)) if stored.is_relative_to(config.REPO) else str(stored)
    doc = {"doc_id": doc_id, "source": "uploads", "formats": [fmt], "kind": kind,
           "title": Path(name).stem, "pages": 1, "licence": None, "credit": "uploaded by user",
           "heldout": False, "files": {fmt: rel}, "content_sha256": digest.hexdigest(), "size_bytes": size}
    d = config.artifacts_dir() / doc_id
    d.mkdir(exist_ok=True)
    (d / "doc.json").write_text(json.dumps(doc, indent=1))
    await pool.execute(
        "insert into documents (doc_id, source, title, kind, formats, pages, credit, files) "
        "values ($1,'uploads',$2,$3,$4,1,$5,$6::jsonb)",
        doc_id, doc["title"], kind, [fmt], doc["credit"], json.dumps(doc["files"]))
    await publish({"type": "doc.new", "doc_id": doc_id})
    try:  # keep the original now: the container disk is ephemeral
        await artifact_store.save_doc(pool, doc_id)
    except Exception as e:  # noqa: BLE001
        print("artifact save failed:", repr(e)[:200])
    if ingestion_available():
        (d / "ingest.json").write_text(json.dumps({"status": "running", "stages": [], "detail": "queued",
                                                  "step": "queued", "progress": 0, "started_at": time.time()}))
        asyncio.create_task(_ingest(doc_id))
        return {"doc_id": doc_id, "status": "ingesting",
                "detail": "poll GET /api/docs/{doc_id}/ingest until status is not running; doc.new fires again when it ends"}
    return {"doc_id": doc_id, "status": "stored", "detail": "ingestion is not available on this server"}


_INGEST_LOCK = asyncio.Lock()  # heavy: one ingestion at a time


def ingestion_available() -> bool:
    import os
    return os.environ.get("INGEST", "1") != "0" and importlib.util.find_spec("pipeline") is not None


async def _ingest(doc_id: str):
    f = config.artifacts_dir() / doc_id / "ingest.json"
    proc = None
    failure = None
    try:
        # Includes time waiting for the single heavy-job slot: queued uploads cannot hang forever either.
        async with asyncio.timeout(INGEST_TIMEOUT):
            async with _INGEST_LOCK:
                heavy = config.REPO / "scripts" / "heavy.sh"
                prefix = [str(heavy)] if heavy.is_file() and os.environ.get("HEAVY_SLOT_HELD") != "1" else []
                proc = await asyncio.create_subprocess_exec(
                    *prefix, sys.executable, "-m", "server.ingest_job", doc_id, cwd=str(config.REPO),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    env={**os.environ, "INGEST_MANAGED_JOB": "1",
                         "HEAVY_SLOT_HELD": "1" if prefix or os.environ.get("HEAVY_SLOT_HELD") == "1" else "0"},
                    start_new_session=True)
                await proc.wait()
        state = _read_ingest(f)
        if proc.returncode or state.get("status") not in {"ready", "partial", "failed"}:
            detail = f"Ingestion job exited with code {proc.returncode} without completing."
            if proc.returncode in (-9, 137):
                detail += " The server may have run out of memory."
            _fail_ingest(f, state.get("reason") or detail)
    except TimeoutError:
        failure = "Ingestion timed out after 5 minutes. Try a smaller file."
    except asyncio.CancelledError:
        failure = "Ingestion was interrupted. Please upload the file again."
        raise
    except Exception as e:  # noqa: BLE001
        failure = f"Ingestion could not complete: {str(e)[:300] or type(e).__name__}"
    finally:
        if proc is not None and proc.returncode is None:
            # Also stop converter grandchildren, which otherwise outlive the Python job.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
        if failure:
            _fail_ingest(f, failure)
    await _persist(doc_id)
    try:  # searchable project-wide at once (never raises; returns bool)
        from engine.project_index import upsert_doc
        await asyncio.to_thread(upsert_doc, doc_id)
    except Exception as e:  # noqa: BLE001
        print("index upsert failed:", doc_id, repr(e)[:200])
    await publish({"type": "doc.new", "doc_id": doc_id})


async def _persist(doc_id: str):
    """After ingestion: sync document metadata and mirror derived files to PostgreSQL."""
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        d = config.artifacts_dir() / doc_id
        meta = json.loads((d / "doc.json").read_text())
        # formats describes the source upload: JPEG can have a derived PNG in files.
        # Older sidecars without formats still have explicit format keys in files.
        formats = meta.get("formats") or list(meta["files"])
        await pool.execute("update documents set pages=$2, files=$3::jsonb, formats=$4 where doc_id=$1",
                           doc_id, int(meta.get("pages") or 1), json.dumps(meta["files"]), formats)
        await artifact_store.save_doc(pool, doc_id)
    except Exception as e:  # noqa: BLE001
        print("persist failed:", doc_id, repr(e)[:200])


@router.get("/docs/{doc_id}/ingest")
async def ingest_status(doc_id: str):
    f = _doc_dir(doc_id) / "ingest.json"
    if not f.is_file():
        return {"status": "none", "step": "none", "progress": 0, "stages": [],
                "detail": "no ingestion has run for this document"}
    state = _read_ingest(f)
    # Also recover stale statuses restored from a previous container/process.
    if state["status"] == "running" and time.time() - state.get("started_at", f.stat().st_mtime) >= INGEST_TIMEOUT:
        state = _fail_ingest(f, "Ingestion timed out after 5 minutes. Try a smaller file.")
        await _persist(doc_id)
    return state


def _read_ingest(f):
    try:
        state = json.loads(f.read_text())
        if not isinstance(state, dict) or "status" not in state:
            raise ValueError("invalid ingestion status")
    except (OSError, ValueError):
        state = {"status": "failed", "detail": "Ingestion stopped without a readable status. Please upload the file again."}
    stages = state.get("stages") or []
    state.setdefault("step", stages[-1]["stage"] if stages else state.get("detail") or state["status"])
    # Completed-stage fraction; the current stage remains pending until a terminal status.
    state["progress"] = 1 if state["status"] == "ready" else len(stages) / (len(stages) + 1)
    if state["status"] == "failed":
        state["reason"] = state.get("reason") or state.get("detail") or "Ingestion failed. Please upload the file again."
    return state


def _fail_ingest(f, reason):
    state = _read_ingest(f)
    state.update(status="failed", detail=reason, reason=reason)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(f)
    return state


def _change(r) -> dict:
    """A `changes` table row (rule changes from the watch webhook)."""
    d = dict(r)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat()
    if isinstance(d.get("summary"), str):
        d["summary"] = json.loads(d["summary"])
    s = d.get("summary") if isinstance(d.get("summary"), dict) else {}
    d["type"] = "rule_change" if s.get("kind") == "rule_change" else "new_version"
    return d


async def _upload_rows(pool) -> list[dict]:
    rows = await pool.fetch("select doc_id, title, kind, files, created_at from documents where source='uploads'")
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("files"), str):
            d["files"] = json.loads(d["files"])
        out.append(d)
    return out


async def _feed(pool) -> dict:
    from . import changes_source as cs
    rows = await pool.fetch("select id, doc_a, doc_b, summary, created_at from changes where doc_a is null or doc_a not like '%@v%'")
    ups = await _upload_rows(pool)
    feed = [_change(r) for r in rows]
    feed += cs.series_entries()
    matched = cs.upload_entries(ups)
    feed += matched
    done = {e["doc_b"] for e in matched}
    from . import design_versions
    feed += await design_versions.feed_entries(pool)  # 3D edits saved as new versions (dv:<doc>:<a>-<b>)
    feed += [{"id": f"doc:{r['doc_id']}", "type": "new_document", "doc_a": None, "doc_b": r["doc_id"],
              "summary": {"doc_id": r["doc_id"], "title": r["title"], "kind": r["kind"],
                          "headline": f"New document: {r['title']}"},
              "created_at": r["created_at"].isoformat()} for r in ups if r["doc_id"] not in done]
    feed = await cs.visible_feed(pool, feed)
    feed.sort(key=lambda e: e["created_at"], reverse=True)
    groups = cs.grouped(feed)
    return {"changes": feed, "checked_at": cs.checked_at(), "groups": groups}


@router.get("/changes")
async def changes():
    """Feed, newest first: real new versions (version series + matching uploads), rule changes, new documents."""
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return await _feed(pool)


@router.post("/changes/refresh")
async def changes_refresh():
    """Rescan: reload series, diff uploads that match a series, stamp checked_at, return the feed."""
    import asyncio
    from . import changes_source as cs, docmeta_store
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    docmeta_store._cache.clear()
    for r in await _upload_rows(pool):
        if cs.match_series(r):
            await asyncio.to_thread(cs.compute_for_row, r)
    cs.mark_checked()
    return await _feed(pool)


@router.post("/changes/compare")
async def compare_versions(request: Request):
    """Compare any two listed versions, including freshly ingested uploads."""
    from engine.revision_compare import compare_documents
    from . import changes_source as cs
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Choose version A and version B.")
    if not isinstance(body, dict):
        raise HTTPException(400, "Choose version A and version B.")
    a, b = body.get("doc_a"), body.get("doc_b")
    if any(not isinstance(d, str) or not SAFE_ID.fullmatch(d) or d in (".", "..") for d in (a, b)):
        raise HTTPException(400, "Choose valid documents for version A and version B.")
    if a == b:
        raise HTTPException(400, "Choose two different versions.")
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    if not await cs.visible_pair(pool, a, b):
        raise HTTPException(404, "One of these versions is not available.")
    await artifact_store.ensure_doc(a)
    await artifact_store.ensure_doc(b)
    return await asyncio.to_thread(compare_documents, a, b, config.artifacts_dir())


@router.get("/changes/{change_id}")
async def change(change_id: str, page: int | None = None):
    from . import changes_source as cs
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    if change_id.startswith("upl:"):
        doc_id = change_id[4:]
        for r in await _upload_rows(pool):
            s = cs.match_series(r) if r["doc_id"] == doc_id else None
            if s:
                if not await cs.visible_pair(pool, s["versions"][-1]["doc_id"], doc_id):
                    raise HTTPException(404, "change not found")
                diff = cs.compute_for_row(r)
                return cs.comparison(change_id, page, diff, s, len(s["versions"]) - 1, doc_id) | {"type": "new_version"}
        raise HTTPException(404, "change not found")
    if change_id.startswith("dv:"):
        from . import design_versions
        out = await design_versions.comparison(pool, change_id, page)
        if out is None or not await cs.visible_pair(pool, out["doc_id"], out["doc_id"]):
            raise HTTPException(404, "change not found")
        return out
    if change_id.startswith("ser:"):
        out = cs.comparison(change_id, page)
        if out is None or not await cs.visible_pair(pool, out["v1"]["doc_id"], out["v2"]["doc_id"]):
            raise HTTPException(404, "change not found")
        return out | {"type": "new_version", "created_at": next((e["created_at"] for e in cs.series_entries() if e["id"] == change_id), None)}
    try:
        cid = uuid.UUID(change_id)
    except ValueError:
        raise HTTPException(404, "change not found")
    r = await pool.fetchrow("select id, doc_a, doc_b, summary, created_at from changes where id=$1", cid)
    if r is None:
        raise HTTPException(404, "change not found")
    out = _change(r)
    if not await cs.visible_feed(pool, [out]):
        raise HTTPException(404, "change not found")
    return out


def _bench_summaries() -> list[dict]:
    from .bench_routes import summaries
    return summaries()


@router.get("/bench")
async def bench_list():
    return {"benches": [{"tag": r["tag"], "set": r["set"], "fake": r["fake"], "file": r["file"],
                         "mtime": datetime.fromtimestamp(r["mtime"], timezone.utc).isoformat()}
                        for r in _bench_summaries()]}


@router.get("/bench/latest")
async def bench_latest(tag: str | None = None):
    from .bench_routes import latest_bench
    return latest_bench(tag)


@router.get("/costs")
async def costs():
    f = config.results_dir() / "costs.jsonl"
    by_provider: dict = {}
    by_task: dict = {}
    total = 0.0
    n = 0
    if f.is_file():
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            c = float(r.get("cost_usd") or 0)
            total += c
            n += 1
            for table, key in ((by_provider, r.get("provider") or "unknown"),
                               (by_task, r.get("task") or r.get("row") or "unknown")):
                e = table.setdefault(key, {"calls": 0, "usd": 0.0})
                e["calls"] += 1
                e["usd"] = round(e["usd"] + c, 6)
    return {"total_usd": round(total, 6), "calls": n, "by_provider": by_provider, "by_task": by_task}
