"""Document files, upload, bench and costs (CONTRACT 5.9)."""
import json
import re
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
    return {"doc_id": doc_id, "status": "stored", "detail": "ingestion not started (S-04)"}


@router.get("/changes")
async def changes():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    rows = await pool.fetch("select id, doc_a, doc_b, summary, created_at from changes order by created_at desc")
    return {"changes": [_change(r) for r in rows]}


def _change(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat()
    if isinstance(d.get("summary"), str):
        d["summary"] = json.loads(d["summary"])
    return d


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
    return _change(r)


@router.get("/bench/latest")
async def bench_latest():
    d = config.results_dir() / "bench"
    files = [f for f in d.glob("*") if f.is_file() and f.suffix in (".json", ".jsonl")] if d.is_dir() else []
    if not files:
        return JSONResponse({"status": "no_bench", "detail": "no bench results yet"}, status_code=404)
    f = max(files, key=lambda p: p.stat().st_mtime)
    text = f.read_text()
    body = ([json.loads(l) for l in text.splitlines() if l.strip()] if f.suffix == ".jsonl" else json.loads(text))
    return {"file": f.name, "data": body}


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
