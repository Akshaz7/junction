"""GET /api/docs, GET /api/docs/{doc_id} (CONTRACT 5.9)."""
from fastapi import APIRouter, HTTPException

from . import db

router = APIRouter(prefix="/api")

COLS = "doc_id, source, title, kind, formats, pages, licence, credit, heldout, files"


async def _pool_or_503():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


def _row(r) -> dict:
    d = dict(r)
    if isinstance(d.get("files"), str):
        import json
        d["files"] = json.loads(d["files"])
    return d


@router.get("/docs")
async def list_docs():
    pool = await _pool_or_503()
    rows = await pool.fetch(f"select {COLS} from documents order by source, title, doc_id")
    sources: dict[str, list] = {}
    for r in rows:
        d = _row(r)
        sources.setdefault(d["source"], []).append(d)
    return {"total": len(rows),
            "sources": [{"source": s, "count": len(v), "docs": v} for s, v in sources.items()]}


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str):
    pool = await _pool_or_503()
    r = await pool.fetchrow(f"select {COLS} from documents where doc_id=$1", doc_id)
    if r is None:
        raise HTTPException(404, "document not found")
    return _row(r)
