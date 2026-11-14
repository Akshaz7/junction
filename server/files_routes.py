"""Document files, upload, bench and costs (CONTRACT 5.9)."""
import asyncio
import importlib.util
import json
from datetime import datetime, timezone
import re
import sys
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import config, db
from .live import publish

router = APIRouter(prefix="/api")

SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")
FILE_NAMES = {"scene.glb", "scene.usdz", "scene.json", "elements.json"}
THUMB = re.compile(r"^(page-\d+\.thumb\.png|page-\d+\.png|planmap-\d+\.json)$")
UPLOAD_EXT = {".ifc": "ifc", ".dxf": "dxf", ".dwg": "dwg", ".pdf": "pdf", ".svg": "svg",
              ".png": "raster", ".jpg": "raster", ".jpeg": "raster", ".tif": "raster", ".tiff": "raster"}
MAX_UPLOAD = 100 * 1024 * 1024


def _doc_dir(doc_id: str):
    if not SAFE_ID.match(doc_id):
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


@router.get("/docs/{doc_id}/planmap/{n}")
async def planmap(doc_id: str, n: int):
    f = _doc_dir(doc_id) / f"planmap-{n}.json"
    if not f.is_file():
        return _not_built(f"plan map {n}")
    return FileResponse(f, media_type="application/json")


@router.get("/docs/{doc_id}/scene")
async def scene(doc_id: str):
    # S-04 will trigger extrusion here when no scene exists.
    f = _doc_dir(doc_id) / "scene.json"
    if not f.is_file():
        return _not_built("scene")
    return FileResponse(f, media_type="application/json")


@router.get("/docs/{doc_id}/files/{name}")
async def doc_file(doc_id: str, name: str):
    if name not in FILE_NAMES and not THUMB.match(name):
        raise HTTPException(404, "unknown file")
    f = _doc_dir(doc_id) / name
    if not f.is_file():
        return _not_built(name)
    return FileResponse(f)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "upload"


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    from pathlib import Path
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_EXT:
        raise HTTPException(415, f"unsupported file type {ext or '(none)'}")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    doc_id = f"uploads__{_slug(Path(name).stem)}-{uuid.uuid4().hex[:6]}"
    updir = config.artifacts_dir() / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    stored = updir / f"{doc_id}{ext}"
    stored.write_bytes(data)
    fmt = ext.lstrip(".")
    kind = UPLOAD_EXT[ext]
    rel = f"artifacts/uploads/{stored.name}"
    doc = {"doc_id": doc_id, "source": "uploads", "formats": [fmt], "kind": kind,
           "title": Path(name).stem, "pages": 1, "licence": None, "credit": "uploaded by user",
           "heldout": False, "files": {fmt: rel}}
    d = config.artifacts_dir() / doc_id
    d.mkdir(exist_ok=True)
    (d / "doc.json").write_text(json.dumps(doc, indent=1))
    await pool.execute(
        "insert into documents (doc_id, source, title, kind, formats, pages, credit, files) "
        "values ($1,'uploads',$2,$3,$4,1,$5,$6::jsonb)",
        doc_id, doc["title"], kind, [fmt], doc["credit"], json.dumps(doc["files"]))
    await publish({"type": "doc.new", "doc_id": doc_id})
    if ingestion_available():
        (d / "ingest.json").write_text(json.dumps({"status": "running", "stages": [], "detail": "queued"}))
        asyncio.create_task(_ingest(doc_id))
        return {"doc_id": doc_id, "status": "ingesting",
                "detail": "poll GET /api/docs/{doc_id}/ingest until status is not running; doc.new fires again when it ends"}
    return {"doc_id": doc_id, "status": "stored", "detail": "ingestion is not available on this server"}


_INGEST_LOCK = asyncio.Lock()  # heavy: one ingestion at a time


def ingestion_available() -> bool:
    import os
    return os.environ.get("INGEST", "1") != "0" and importlib.util.find_spec("pipeline") is not None


async def _ingest(doc_id: str):
    async with _INGEST_LOCK:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "server.ingest_job", doc_id, cwd=str(config.REPO),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
    f = config.artifacts_dir() / doc_id / "ingest.json"
    if not f.is_file() and proc.returncode:
        f.write_text(json.dumps({"status": "failed", "stages": [], "detail": f"job exited {proc.returncode}"}))
    await publish({"type": "doc.new", "doc_id": doc_id})


@router.get("/docs/{doc_id}/ingest")
async def ingest_status(doc_id: str):
    f = _doc_dir(doc_id) / "ingest.json"
    if not f.is_file():
        return {"status": "none", "stages": [], "detail": "no ingestion has run for this document"}
    return json.loads(f.read_text())


REV_VERSION = re.compile(r"^v\d+$")
REV_FILE = re.compile(r"^(page-\d+(\.thumb)?\.png|planmap-\d+\.json)$")


@router.get("/docs/{doc_id}/revisions/{version}/{name}")
async def revision_file(doc_id: str, version: str, name: str):
    """Page images and plan maps of a revision (artifacts/revisions/<doc_id>/<vN>/)."""
    if not SAFE_ID.match(doc_id) or not REV_VERSION.match(version) or not REV_FILE.match(name):
        raise HTTPException(404, "unknown file")
    f = config.artifacts_dir() / "revisions" / doc_id / version / name
    if not f.is_file():
        return _not_built(f"{version}/{name}")
    return FileResponse(f)


def _change(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat()
    if isinstance(d.get("summary"), str):
        d["summary"] = json.loads(d["summary"])
    d["type"] = "new_version"
    return d


@router.get("/changes")
async def changes():
    """Feed, newest first: new versions (`changes` rows) and new documents (uploads)."""
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    rows = await pool.fetch("select id, doc_a, doc_b, summary, created_at from changes")
    docs = await pool.fetch("select doc_id, title, kind, created_at from documents where source='uploads'")
    feed = [_change(r) for r in rows]
    feed += [{"id": f"doc:{r['doc_id']}", "type": "new_document", "doc_a": None, "doc_b": r["doc_id"],
              "summary": {"doc_id": r["doc_id"], "title": r["title"], "kind": r["kind"],
                          "headline": f"New document: {r['title']}"},
              "created_at": r["created_at"].isoformat()} for r in docs]
    feed.sort(key=lambda e: e["created_at"], reverse=True)
    return {"changes": feed}


@router.get("/changes/{change_id}")
async def change(change_id: str):
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    try:
        cid = uuid.UUID(change_id)
    except ValueError:
        raise HTTPException(404, "change not found")
    r = await pool.fetchrow("select id, doc_a, doc_b, summary, created_at from changes where id=$1", cid)
    if r is None:
        raise HTTPException(404, "change not found")
    out = _change(r)
    from . import changes_source
    doc_id = (out["doc_a"] or "").split("@")[0]
    if doc_id and SAFE_ID.match(doc_id) and doc_id in changes_source.revision_docs():
        try:
            out.update(changes_source.comparison(doc_id))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"comparison failed: {type(e).__name__}")
        out["id"] = str(r["id"])
    return out


def _bench_summaries() -> list[dict]:
    """Bench summaries (results/bench/<tag>.json), newest first. *.rows.jsonl row dumps are ignored."""
    d = config.results_dir() / "bench"
    out = []
    for f in d.glob("*.json") if d.is_dir() else []:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append({"path": f, "file": f.name, "tag": str(data.get("tag") or f.stem), "stem": f.stem,
                        "set": data.get("set"), "fake": data.get("fake"), "mtime": f.stat().st_mtime, "data": data})
    return sorted(out, key=lambda r: r["mtime"], reverse=True)


@router.get("/bench")
async def bench_list():
    return {"benches": [{"tag": r["tag"], "set": r["set"], "fake": r["fake"], "file": r["file"],
                         "mtime": datetime.fromtimestamp(r["mtime"], timezone.utc).isoformat()}
                        for r in _bench_summaries()]}


@router.get("/bench/latest")
async def bench_latest(tag: str | None = None):
    found = _bench_summaries()
    if tag is not None:
        found = [r for r in found if tag in (r["tag"], r["stem"])]
    if not found:
        detail = f"no bench results for tag {tag!r}" if tag is not None else "no bench results yet"
        return JSONResponse({"status": "no_bench", "detail": detail}, status_code=404)
    r = found[0]
    return {"file": r["file"], "tag": r["tag"], "data": r["data"]}


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
