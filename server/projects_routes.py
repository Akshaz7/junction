"""Projects: saved workspaces of many documents of one building site (handoff/F-PROJECTS-CONTRACT.md).

Roles and levels are classified by engine.projects.classify when a document is added (role_source 'auto') and are
refreshed while the document is still being read; a user edit (role_source 'user') is never overwritten.
"""
import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from . import config, db

router = APIRouter(prefix="/api")

ROLES = ("model", "plan", "section", "elevation", "detail", "schedule", "scan", "photo", "spec", "revision", "other")
MAX_DOCS = 500
_CLASS_CACHE: dict = {}


class NewProject(BaseModel):
    name: str
    doc_ids: list[str] = []


class RenameProject(BaseModel):
    name: str


class AddDocs(BaseModel):
    doc_ids: list[str]


class DocEdit(BaseModel):
    role: str | None = None
    level: str | None = None


async def _pool():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


def _uuid(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(404, "project not found")


def _clean_name(name: str) -> str:
    n = " ".join((name or "").split())
    if not n:
        raise HTTPException(422, "A project needs a name.")
    return n[:120]


def _classify_sync(doc_id: str) -> dict:
    """{role, level} for a document, cached until its files change. Never raises."""
    try:
        from engine.projects import classify
        from engine.projects.combine import doc_dict
        from engine.projects.overview import _stamp
        root = Path(config.artifacts_dir())
        key = (doc_id, _stamp(doc_id, root))
        hit = _CLASS_CACHE.get(key)
        if hit is None:
            hit = classify(doc_dict(doc_id, root), root)
            _CLASS_CACHE[key] = hit
            while len(_CLASS_CACHE) > 2000:
                _CLASS_CACHE.pop(next(iter(_CLASS_CACHE)))
        return hit
    except Exception:  # noqa: BLE001  a file we cannot read is "other", not an error
        return {"role": "other", "level": None, "confidence": 0.0}


async def _classify(doc_ids: list[str]) -> dict:
    from . import artifact_store
    out = {}
    for d in doc_ids:
        try:
            await artifact_store.ensure_doc(d)
        except Exception:  # noqa: BLE001
            pass
        out[d] = await asyncio.to_thread(_classify_sync, d)
    return out


async def _refresh(pool, pid, rows) -> list:
    """Re-read roles of auto-classified documents (a document that was still ingesting when it was added gets its real role once readable)."""
    auto = [r["doc_id"] for r in rows if r["role_source"] == "auto"]
    if not auto:
        return rows
    new = await _classify(auto)
    changed = {}
    for r in rows:
        n = new.get(r["doc_id"])
        if n and (n["role"] != r["role"] or (n.get("level") or None) != r["level"]):
            changed[r["doc_id"]] = n
    for d, n in changed.items():
        await pool.execute("update project_docs set role=$3, level=$4 where project_id=$1 and doc_id=$2 and role_source='auto'",
                           pid, d, n["role"], n.get("level"))
    if not changed:
        return rows
    return await _doc_rows(pool, pid)


async def _doc_rows(pool, pid) -> list:
    return await pool.fetch(
        "select p.doc_id, p.role, p.level, p.role_source, d.title, d.kind, d.formats from project_docs p "
        "left join documents d on d.doc_id = p.doc_id where p.project_id=$1 order by p.added_at, p.doc_id", pid)


def _doc_obj(r) -> dict:
    return {"doc_id": r["doc_id"], "title": r["title"] or r["doc_id"], "kind": r["kind"] or "", "formats": list(r["formats"] or []),
            "role": r["role"], "level": r["level"], "role_source": r["role_source"],
            "thumb_url": f"/api/docs/{r['doc_id']}/pages/1.png"}


async def _project(pool, pid, refresh: bool = True, visible_only: bool = True) -> dict:
    p = await pool.fetchrow("select id, name, demo, created_at from projects where id=$1", pid)
    if p is None:
        raise HTTPException(404, "project not found")
    rows = await _doc_rows(pool, pid)
    skipped: list[str] = []
    if visible_only:   # a stale or hidden document (not listed by /api/docs) is skipped with a note, never fatal
        from .changes_source import visible_doc_ids
        listed = await visible_doc_ids(pool)
        skipped = [r["doc_id"] for r in rows if r["doc_id"] not in listed]
        rows = [r for r in rows if r["doc_id"] in listed]
    if refresh:
        rows = await _refresh(pool, pid, rows)
    out = {"id": str(p["id"]), "name": p["name"], "demo": p["demo"], "created_at": p["created_at"].isoformat(),
           "docs": [_doc_obj(r) for r in rows]}
    if skipped:
        out["skipped_doc_ids"] = skipped
    return out


async def _attach(pool, pid, doc_ids: list[str]) -> None:
    ids = list(dict.fromkeys(d for d in doc_ids if isinstance(d, str) and d))
    if not ids:
        return
    known = {r["doc_id"] for r in await pool.fetch("select doc_id from documents where doc_id = any($1::text[])", ids)}
    missing = [d for d in ids if d not in known]
    if missing:
        raise HTTPException(404, f"document not found: {missing[0]}")
    have = await pool.fetchval("select count(*) from project_docs where project_id=$1", pid)
    if have + len(ids) > MAX_DOCS:
        raise HTTPException(413, f"A project holds at most {MAX_DOCS} documents.")
    roles = await _classify(ids)
    for d in ids:
        n = roles[d]
        await pool.execute(
            "insert into project_docs (project_id, doc_id, role, level, role_source) values ($1,$2,$3,$4,'auto') on conflict do nothing",
            pid, d, n["role"] if n["role"] in ROLES else "other", n.get("level"))


@router.get("/projects")
async def list_projects():
    pool = await _pool()
    rows = await pool.fetch(
        "select p.id, p.name, p.demo, p.created_at, (select count(*) from project_docs d where d.project_id=p.id) as n "
        "from projects p order by p.demo desc, p.created_at desc")
    return {"projects": [{"id": str(r["id"]), "name": r["name"], "doc_count": int(r["n"]), "created_at": r["created_at"].isoformat(),
                          "demo": r["demo"]} for r in rows]}


@router.post("/projects")
async def create_project(body: NewProject):
    pool = await _pool()
    name = _clean_name(body.name)
    pid = await pool.fetchval("insert into projects (name) values ($1) returning id", name)
    try:
        await _attach(pool, pid, body.doc_ids)
    except HTTPException:
        await pool.execute("delete from projects where id=$1", pid)
        raise
    return await _project(pool, pid, refresh=False)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    pool = await _pool()
    return await _project(pool, _uuid(project_id))


@router.patch("/projects/{project_id}")
async def rename_project(project_id: str, body: RenameProject):
    pool = await _pool()
    pid = _uuid(project_id)
    if await pool.fetchval("update projects set name=$2 where id=$1 returning 1", pid, _clean_name(body.name)) is None:
        raise HTTPException(404, "project not found")
    return await _project(pool, pid, refresh=False)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    pool = await _pool()
    pid = _uuid(project_id)
    demo = await pool.fetchval("select demo from projects where id=$1", pid)
    if demo is None:
        raise HTTPException(404, "project not found")
    await pool.execute("delete from projects where id=$1", pid)
    return {"deleted": str(pid)}


@router.post("/projects/{project_id}/docs")
async def add_docs(project_id: str, body: AddDocs):
    pool = await _pool()
    pid = _uuid(project_id)
    if await pool.fetchval("select 1 from projects where id=$1", pid) is None:
        raise HTTPException(404, "project not found")
    await _attach(pool, pid, body.doc_ids)
    return await _project(pool, pid, refresh=False)


@router.post("/projects/{project_id}/upload")
async def upload_into_project(project_id: str, file: UploadFile = File(...)):
    """Same limits and ingest as the library upload (files_routes.upload), then the new document joins the project."""
    from .files_routes import upload
    pool = await _pool()
    pid = _uuid(project_id)
    if await pool.fetchval("select 1 from projects where id=$1", pid) is None:
        raise HTTPException(404, "project not found")
    res = await upload(file)
    await _attach(pool, pid, [res["doc_id"]])
    return {**res, "project": await _project(pool, pid, refresh=False)}


@router.patch("/projects/{project_id}/docs/{doc_id}")
async def edit_doc(project_id: str, doc_id: str, body: DocEdit):
    pool = await _pool()
    pid = _uuid(project_id)
    if await pool.fetchval("select 1 from project_docs where project_id=$1 and doc_id=$2", pid, doc_id) is None:
        raise HTTPException(404, "document is not in this project")
    sent = body.model_fields_set
    if "role" in sent:
        if body.role not in ROLES:
            raise HTTPException(422, f"role must be one of: {', '.join(ROLES)}")
        await pool.execute("update project_docs set role=$3, role_source='user' where project_id=$1 and doc_id=$2", pid, doc_id, body.role)
    if "level" in sent:
        lv = " ".join((body.level or "").split())[:80] or None
        await pool.execute("update project_docs set level=$3, role_source='user' where project_id=$1 and doc_id=$2", pid, doc_id, lv)
    return await _project(pool, pid, refresh=False)


@router.delete("/projects/{project_id}/docs/{doc_id}")
async def remove_doc(project_id: str, doc_id: str):
    pool = await _pool()
    pid = _uuid(project_id)
    if await pool.fetchval("select 1 from projects where id=$1", pid) is None:
        raise HTTPException(404, "project not found")
    await pool.execute("delete from project_docs where project_id=$1 and doc_id=$2", pid, doc_id)
    return await _project(pool, pid, refresh=False)


@router.get("/projects/{project_id}/overview")
async def project_overview(project_id: str):
    from engine.projects import overview
    pool = await _pool()
    project = await _project(pool, _uuid(project_id))
    return await asyncio.to_thread(overview, project, Path(config.artifacts_dir()))


async def project_doc_ids(pool, project_id) -> list[str] | None:
    """Documents of a project, in the order they were added (None when the project does not exist)."""
    try:
        pid = uuid.UUID(str(project_id))
    except ValueError:
        return None
    if await pool.fetchval("select 1 from projects where id=$1", pid) is None:
        return None
    return [r["doc_id"] for r in await pool.fetch("select doc_id from project_docs where project_id=$1 order by added_at, doc_id", pid)]


# ------------------------------------------------------------------------------------------------ demo projects
# Real multi-document buildings that exist in the library. Nothing is invented: a family is every library document whose
# id belongs to the building, and a family with fewer than two documents is not seeded.
DEMO_FAMILIES = ()   # retired for judging: the curated projects are built from real uploads and kept by hand


async def seed_demo_projects(pool) -> dict:
    """Idempotent: creates each demo project once and adds any family document that is not in it yet. Returns {name: docs added}."""
    from .changes_source import visible_doc_ids
    listed = await visible_doc_ids(pool)   # hidden documents never enter a demo project
    ids = sorted(listed)
    out = {}
    for name, belongs in DEMO_FAMILIES:
        fam = [d for d in ids if belongs(d.lower())]
        if len(fam) < 2:
            continue
        pid = await pool.fetchval("select id from projects where demo and name=$1", name)
        if pid is None:
            pid = await pool.fetchval("insert into projects (name, demo) values ($1, true) on conflict do nothing returning id", name)
            if pid is None:
                pid = await pool.fetchval("select id from projects where demo and name=$1", name)
        have = {r["doc_id"] for r in await pool.fetch("select doc_id from project_docs where project_id=$1", pid)}
        new = [d for d in fam if d not in have]
        await _attach(pool, pid, new)
        out[name] = len(new)
    return out
