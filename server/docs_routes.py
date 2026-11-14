"""GET /api/docs, GET /api/docs/{doc_id}, GET /api/folders, GET /api/docs/{doc_id}/source (CONTRACT 5.9 + parity items)."""
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from . import db, docmeta_store

router = APIRouter(prefix="/api")

COLS = "doc_id, source, title, kind, formats, pages, licence, credit, heldout, files, created_at"


async def _pool_or_503():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


def _row(r, stored=None, by_doc=None) -> dict:
    d = dict(r)
    if isinstance(d.get("files"), str):
        d["files"] = json.loads(d["files"])
    created = d.pop("created_at", None)
    d.update(docmeta_store.enrich(d, created, by_doc, stored))
    return d


async def _document(doc_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", doc_id) or doc_id in {".", ".."}:
        raise HTTPException(400, "bad doc_id")
    pool = await db.get_pool()
    r = await pool.fetchrow(f"select {COLS} from documents where doc_id=$1", doc_id) if pool is not None else None
    if r is None:
        # Images are served from artifacts independently of the documents table.
        # A partial DB seed must not make those revisions' detail/source URLs 404.
        r = docmeta_store.document_record(doc_id)
    if r is None:
        if pool is None:
            raise HTTPException(503, "database unavailable")
        raise HTTPException(404, "document not found")
    return dict(r)


@router.get("/docs")
async def list_docs():
    pool = await _pool_or_503()
    rows = await pool.fetch(f"select {COLS} from documents order by source, title, doc_id")
    stored, by_doc = docmeta_store.docmeta_file(), docmeta_store.series_by_doc()
    sources: dict[str, list] = {}
    for r in rows:
        d = _row(r, stored, by_doc)
        sources.setdefault(d["source"], []).append(d)
    return {"total": len(rows),
            "sources": [{"source": s, "count": len(v), "docs": v} for s, v in sources.items()]}


@router.get("/folders")
async def folders():
    """Folder tree Project > Discipline [> Sub-discipline] with document counts."""
    pool = await _pool_or_503()
    rows = await pool.fetch("select doc_id, source, title, kind, files from documents")
    recs = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("files"), str):
            d["files"] = json.loads(d["files"])
        recs.append(d)
    return docmeta_store.tree(recs)


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str):
    return _row(await _document(doc_id))


@router.get("/docs/{doc_id}/pages/{n}.png")
async def page_png(doc_id: str, n: int):
    """PNG alias for the contract's /pages/{n}/image URL, including old issues."""
    from . import artifact_store
    from .files_routes import page_image

    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", doc_id) or doc_id in {".", ".."}:
        raise HTTPException(400, "bad doc_id")
    await artifact_store.ensure_doc(doc_id)
    return await page_image(doc_id, n)


@router.get("/docs/{doc_id}/source")
async def doc_source(doc_id: str):
    """Download the original file (pdf, ifc, dxf, ...). 404 not_built when the container does not hold it."""
    rec = await _document(doc_id)
    if isinstance(rec.get("files"), str):
        rec["files"] = json.loads(rec["files"])
    p = docmeta_store.source_file(rec)
    if p is None:
        return JSONResponse({"status": "not_built", "detail": "original file is not available on this server"}, status_code=404)
    return FileResponse(p, filename=p.name)
