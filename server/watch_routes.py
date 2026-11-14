"""Watch loop (E-17): POST /api/watch/webhook, GET /api/watch/monitors, POST /api/watch/sync.

A verified Context.dev `change.detected` event inserts a `changes` row (summary.kind = "rule_change", feed type
`rule_change`; the DB trigger fires `changes.new`) and reruns the engine findings for every document.
Fallback when the signature scheme cannot be used: set WATCH_WEBHOOK_SECRET and send it as `?secret=` (or
header X-Watch-Secret). With no secret known the webhook answers 503 (never accepts unsigned events).
"""
import asyncio
import hmac
import json
import os

from fastapi import APIRouter, HTTPException, Request

from engine import watch as W

from . import db

router = APIRouter(prefix="/api/watch")


def _authorised(request: Request, raw: bytes, monitor_id: str | None) -> bool:
    sig = request.headers.get("x-context-signature")
    if sig:
        secrets = [W.webhook_secret(monitor_id)] if monitor_id else []
        secrets += list(W._load(W.secrets_file(), {}).values()) + [os.environ.get("WATCH_WEBHOOK_SECRET")]
        return any(s and W.verify_signature(raw, sig, s) for s in secrets)
    shared = os.environ.get("WATCH_WEBHOOK_SECRET")
    given = request.query_params.get("secret") or request.headers.get("x-watch-secret") or ""
    return bool(shared) and hmac.compare_digest(shared, given)


async def rerun_findings(pool) -> int:
    from .findings_routes import run_findings, RunBody
    n = 0
    for r in await pool.fetch("select doc_id from documents"):
        try:
            await run_findings(RunBody(doc_id=r["doc_id"]))
            n += 1
        except Exception:  # noqa: BLE001  one bad document never blocks the rest
            continue
    return n


@router.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "invalid JSON")
    mon = ((payload.get("data") or {}).get("change") or {}).get("monitor_id") if isinstance(payload, dict) else None
    if not (os.environ.get("WATCH_WEBHOOK_SECRET") or W._load(W.secrets_file(), {})):
        raise HTTPException(503, "no webhook secret configured")
    if not _authorised(request, raw, mon):
        raise HTTPException(401, "invalid webhook signature")
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    ev = W.parse_event(payload)
    if ev is None:
        return {"status": "ignored"}
    eid = request.headers.get("x-context-id") or ev["event_id"]
    if eid and await pool.fetchval("select 1 from changes where summary->>'event_id'=$1", eid):
        return {"status": "duplicate"}
    summary = {"kind": "rule_change", "source": "context.dev", "event_id": eid, "monitor_id": ev["monitor_id"],
               "url": ev["url"], "rule_ids": ev["rule_ids"], "title": ev["title"], "summary": ev["summary"],
               "importance": ev["importance"], "detected_at": ev["detected_at"],
               "headline": ev["title"] + (f": {ev['summary']}" if ev["summary"] else "")}
    cid = await pool.fetchval("insert into changes (doc_a, doc_b, summary) values (null, null, $1::jsonb) returning id",
                              json.dumps(summary))
    n = await rerun_findings(pool)
    return {"status": "ok", "change_id": str(cid), "findings_rerun_docs": n}


@router.get("/monitors")
async def monitors():
    d = W._load(W.monitors_file(), {"status": "none", "monitors": []})
    return {**d, "rule_urls": list(W.rule_sources())}


@router.post("/sync")
async def sync():
    return await asyncio.to_thread(W.sync_monitors, os.environ.get("WATCH_WEBHOOK_URL"))
