"""Findings (S-09): POST /api/findings/run, GET /api/findings.

Checks run in the engine: engine.findings.run(doc_id) -> list of {rule_id, item_ids, severity, message, detail?}
(E-15). Until it exists the run reports `no_checks`. Hard rule enforced here: a finding must cite a rule from
engine/rules/*.yaml and name at least one item, otherwise it is dropped.
"""
import asyncio
import importlib
import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db
from .live import publish

router = APIRouter(prefix="/api")
SEVERITIES = ("info", "suggestion", "violation")  # "suggestion" unless the rule clearly fails


class RunBody(BaseModel):
    doc_id: str


def _engine_run():
    try:
        return importlib.import_module("engine.findings").run
    except (ImportError, AttributeError):
        return None


def _library() -> dict[str, dict]:
    from engine.rules import load_rules
    return {r["id"]: r for r in load_rules()}


def clean_findings(raw, library: dict[str, dict]) -> list[dict]:
    out = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict) or f.get("rule_id") not in library:
            continue
        ids = [i for i in (f.get("item_ids") or []) if isinstance(i, str) and i]
        if not ids:
            continue
        sev = f.get("severity") if f.get("severity") in SEVERITIES else "suggestion"
        out.append({"rule_id": f["rule_id"], "item_ids": ids, "severity": sev,
                    "message": " ".join(str(f.get("message") or "").split())[:300],
                    "detail": f.get("detail") if isinstance(f.get("detail"), dict) else {}})
    return out


def rule_view(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "text", "source_title", "section", "url", "quote", "translation")}


async def _ensure_rules(conn, library: dict[str, dict]):
    for r in library.values():
        await conn.execute(
            "insert into rules (id, title, body, source) values ($1,$2,$3::jsonb,$4) "
            "on conflict (id) do update set title=excluded.title, body=excluded.body, source=excluded.source",
            r["id"], r["text"], json.dumps(r, ensure_ascii=False), r["url"])


def _row(r) -> dict:
    d = r["detail"] if isinstance(r["detail"], dict) else json.loads(r["detail"] or "{}")
    body = r["body"] if isinstance(r["body"], dict) else json.loads(r["body"] or "{}")
    return {"id": str(r["id"]), "doc_id": r["doc_id"], "rule_id": r["rule_id"], "item_ids": list(r["item_ids"]),
            "severity": r["severity"], "message": d.get("message", ""), "detail": d.get("detail", {}),
            "rule": rule_view(body), "created_at": r["created_at"].isoformat()}


@router.post("/findings/run")
async def run_findings(body: RunBody):
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    if await pool.fetchval("select 1 from documents where doc_id=$1", body.doc_id) is None:
        raise HTTPException(404, "document not found")
    fn = _engine_run()
    if fn is None:
        return {"status": "no_checks", "detail": "the checks are not available yet", "findings": []}
    try:
        library = _library()
        found = clean_findings(await asyncio.to_thread(fn, body.doc_id), library)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"checks failed: {type(e).__name__}")
    async with pool.acquire() as conn, conn.transaction():
        await _ensure_rules(conn, library)
        await conn.execute("delete from findings where doc_id=$1", body.doc_id)
        for f in found:
            await conn.execute(
                "insert into findings (id, doc_id, rule_id, item_ids, severity, detail) values ($1,$2,$3,$4,$5,$6::jsonb)",
                uuid.uuid4(), body.doc_id, f["rule_id"], f["item_ids"], f["severity"],
                json.dumps({"message": f["message"], "detail": f["detail"]}))
    await publish({"type": "findings.updated", "doc_id": body.doc_id, "count": len(found)})
    return {"status": "ok", "findings": (await _list(pool, body.doc_id, None, None))}


async def _list(pool, doc_id, rule_id, severity) -> list[dict]:
    q = ("select f.id, f.doc_id, f.rule_id, f.item_ids, f.severity, f.detail, f.created_at, r.body "
         "from findings f left join rules r on r.id = f.rule_id where true")
    args: list = []
    for col, v in (("f.doc_id", doc_id), ("f.rule_id", rule_id), ("f.severity", severity)):
        if v:
            args.append(v)
            q += f" and {col}=${len(args)}"
    return [_row(r) for r in await pool.fetch(q + " order by f.severity desc, f.created_at, f.id", *args)]


@router.get("/findings")
async def list_findings(doc_id: str | None = None, rule_id: str | None = None, severity: str | None = None):
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return {"findings": await _list(pool, doc_id, rule_id, severity)}
