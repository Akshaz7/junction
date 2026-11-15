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
import datetime as dt

from pydantic import BaseModel, Field

from . import config, db
from .live import publish

router = APIRouter(prefix="/api")
SEVERITIES = ("info", "suggestion", "violation")  # "suggestion" unless the rule clearly fails


class RunBody(BaseModel):
    doc_id: str
    # Items the user removed in the viewer but has not saved. With them the checks run on that edited copy and the
    # result is returned only (never stored over the saved drawing's findings).
    hidden_item_ids: list[str] = Field(default_factory=list, max_length=5000)


WAITING = ("running", "queued", "pending", "ingesting")


def _count_items(doc_dir) -> tuple[int, int]:
    """(readable, total) items read from a document: plan-map items with geometry, indexed model elements."""
    readable = total = 0
    for f in sorted(doc_dir.glob("planmap-*.json")):
        try:
            items = json.loads(f.read_text()).get("items") or []
        except (OSError, ValueError, AttributeError):
            continue
        for it in items:
            if isinstance(it, dict):
                total += 1
                readable += bool(it.get("bbox_px") or it.get("polygon_px"))
    f = doc_dir / "elements.json"
    if f.is_file():
        try:
            els = json.loads(f.read_text()).get("elements") or []
        except (OSError, ValueError, AttributeError):
            els = []
        for el in els:
            if isinstance(el, dict):
                total += 1
                readable += bool(el.get("bbox_m") or el.get("quantities"))
    return readable, total


def readiness(doc_id: str) -> dict | None:
    """None when checks may run; otherwise a non-'ok' result saying why checks cannot be called complete.

    Only documents that went through ingestion (an ingest.json exists) are gated; seeded dataset documents
    have no ingest record and are left alone.
    """
    try:
        doc_dir = config.artifacts_dir() / doc_id
        state = json.loads((doc_dir / "ingest.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    if state.get("status") in WAITING:
        return {"status": "waiting", "detail": "Waiting for the drawing to finish processing", "findings": []}
    readable, total = _count_items(doc_dir)
    if readable == 0:
        return {"status": "not_enough_data", "readable_items": readable, "total_items": total,
                "detail": f"Not enough readable data ({readable} of {total} items)", "findings": []}
    return None


def run_coverage(doc_id: str) -> dict | None:
    """Which checks ran and which had no usable input, so 'no findings' is never read as 'all clear'."""
    try:
        from engine.findings import coverage
        from engine.solvers.data import load_doc
        doc = load_doc(doc_id, config.artifacts_dir())
        return coverage(doc) if doc is not None else None
    except Exception:  # noqa: BLE001 - coverage is extra detail; never fail the run for it
        return None


def _engine_run():
    try:
        return importlib.import_module("engine.findings").run
    except (ImportError, AttributeError):
        return None


def _engine_report():
    try:
        return importlib.import_module("engine.findings").report
    except (ImportError, AttributeError):
        return None


def _coverage(doc_id: str, hidden: list[str]) -> dict:
    """Which rules this run could check, and on how many items. Empty when the engine cannot say."""
    fn = _engine_report()
    try:
        r = fn(doc_id, hidden=hidden or None) if fn else None
    except Exception:  # noqa: BLE001 - coverage is a nice-to-have, never fails the run
        r = None
    if not isinstance(r, dict):
        return {}
    return {"checked": list(r.get("checked") or []), "not_checked": list(r.get("not_checked") or []),
            "items_checked": r.get("items_checked"), "mode": r.get("mode"), "hidden": r.get("hidden") or 0}


def _no_checks_detail(cov: dict) -> str:
    if cov.get("mode") and cov["mode"] != "ifc":
        return ("No rule can be checked on this drawing: door widths, exits and stairs are not measured on a drawing, "
                "and no entrance door could be read from it. Rule checks need an IFC model.")
    return "No rule could be checked: the model lacks the data the rules need."


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
        sev = "violation" if f.get("severity") == "fail" else f.get("severity")   # engine says "fail" for a clear miss
        sev = sev if sev in SEVERITIES else "suggestion"
        text = f.get("message") or f.get("text") or f.get("title") or ""
        extra = {k: f[k] for k in ("finding_id", "check_id", "title", "text", "labels", "storey", "measured", "source")
                 if f.get(k) not in (None, "", {})}
        out.append({"rule_id": f["rule_id"], "item_ids": ids, "severity": sev,
                    "message": " ".join(str(text).split())[:300],
                    "detail": f["detail"] if isinstance(f.get("detail"), dict) else extra})
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
    blocked = readiness(body.doc_id)
    if blocked is not None:  # never report "complete" for a drawing that is unread or still processing
        return blocked
    fn = _engine_run()
    if fn is None:
        return {"status": "no_checks", "detail": "the checks are not available yet", "findings": []}
    hidden = [h for h in body.hidden_item_ids if isinstance(h, str) and h]
    try:
        library = _library()
        raw = await asyncio.to_thread(fn, body.doc_id, hidden=hidden) if hidden else await asyncio.to_thread(fn, body.doc_id)
        found = clean_findings(raw, library)
        cov = await asyncio.to_thread(_coverage, body.doc_id, hidden)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"checks failed: {type(e).__name__}")
    now = dt.datetime.now(dt.timezone.utc)
    meta = {**cov, "checked_at": now.isoformat(), "edited": bool(hidden)}
    status = "no_checks" if not found and cov and not cov.get("checked") else "ok"
    if status == "no_checks":
        meta["detail"] = _no_checks_detail(cov)
    if hidden:   # unsaved edits: answer for the edited copy, keep the saved drawing's findings as they are
        out = [{"id": f"edit-{n}", "doc_id": body.doc_id, "rule_id": f["rule_id"], "item_ids": f["item_ids"],
                "severity": f["severity"], "message": f["message"], "detail": f["detail"],
                "rule": rule_view(library[f["rule_id"]]), "created_at": now.isoformat()} for n, f in enumerate(found)]
        return {"status": status, **meta, "findings": out}
    async with pool.acquire() as conn, conn.transaction():
        await _ensure_rules(conn, library)
        await conn.execute("delete from findings where doc_id=$1", body.doc_id)
        for f in found:
            await conn.execute(
                "insert into findings (id, doc_id, rule_id, item_ids, severity, detail) values ($1,$2,$3,$4,$5,$6::jsonb)",
                uuid.uuid4(), body.doc_id, f["rule_id"], f["item_ids"], f["severity"],
                json.dumps({"message": f["message"], "detail": f["detail"]}))
    await publish({"type": "findings.updated", "doc_id": body.doc_id, "count": len(found)})
    return {"status": status, **meta, "findings": (await _list(pool, body.doc_id, None, None)),
            "coverage": await asyncio.to_thread(run_coverage, body.doc_id)}


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
