"""Skills (saved prompts) and automations (a prompt on a schedule that writes a report) (S-09)."""
import asyncio
import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from . import db
from .live import publish
from .schema import validate_answer

router = APIRouter(prefix="/api")

STARTERS = [  # the four start-screen cards of the web app
    ("count-on-a-plan", "Count on a plan", "Count something on a plan", "How many windows are there?"),
    ("find-room-area", "Find a room's area", "Find a room's area", "What is the area of this room?"),
    ("locate-something", "Locate something", "Where is it on level N?", "Where is the stair core on level 2?"),
    ("read-a-drawing", "Read a drawing", "What does this drawing say about...", "What does this drawing say about the doors?"),
]
MAX_PROMPT = 2000


async def seed_skills(conn) -> None:
    for slug, name, desc, prompt in STARTERS:
        await conn.execute(
            "insert into skills (slug, name, description, prompt, builtin) values ($1,$2,$3,$4,true) "
            "on conflict (slug) do nothing", slug, name, desc, prompt)


async def _pool():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


def _uuid(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(404, "not found")


def _skill(r) -> dict:
    return {"id": str(r["id"]), "slug": r["slug"], "name": r["name"], "description": r["description"],
            "prompt": r["prompt"], "builtin": r["builtin"], "created_at": r["created_at"].isoformat()}


class NewSkill(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    description: str = Field(default="", max_length=200)


class RunBody(BaseModel):
    doc_ids: list[str] = Field(default_factory=list, max_length=20)


def _engine():
    from . import chats_routes  # the same engine the chat uses (ENGINE_IMPL)
    return chats_routes.ENGINE


async def _run_prompt(prompt: str, doc_ids: list[str]) -> dict:
    ans = await asyncio.to_thread(_engine(), prompt, doc_ids, lambda kind, payload: None)
    validate_answer(ans)
    return ans


async def _check_docs(pool, doc_ids: list[str]) -> None:
    if doc_ids:
        n = await pool.fetchval("select count(*) from documents where doc_id = any($1::text[])", doc_ids)
        if n != len(set(doc_ids)):
            raise HTTPException(404, "document not found")


@router.get("/skills")
async def list_skills():
    pool = await _pool()
    rows = await pool.fetch("select * from skills order by builtin desc, created_at, id")
    return {"skills": [_skill(r) for r in rows]}


@router.post("/skills", status_code=201)
async def create_skill(body: NewSkill):
    pool = await _pool()
    r = await pool.fetchrow("insert into skills (name, description, prompt) values ($1,$2,$3) returning *",
                            body.name.strip(), body.description.strip(), body.prompt.strip())
    return _skill(r)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str):
    pool = await _pool()
    r = await pool.fetchrow("select builtin from skills where id=$1", _uuid(skill_id))
    if r is None:
        raise HTTPException(404, "skill not found")
    if r["builtin"]:
        raise HTTPException(403, "starter skills cannot be deleted")
    await pool.execute("delete from skills where id=$1", _uuid(skill_id))
    return Response(status_code=204)


@router.post("/skills/{skill_id}/run")
async def run_skill(skill_id: str, body: RunBody):
    pool = await _pool()
    r = await pool.fetchrow("select * from skills where id=$1", _uuid(skill_id))
    if r is None:
        raise HTTPException(404, "skill not found")
    await _check_docs(pool, body.doc_ids)
    try:
        ans = await _run_prompt(r["prompt"], body.doc_ids)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"engine failed: {e}")
    return {"skill_id": str(r["id"]), "prompt": r["prompt"], "answer": ans}


# ---------------------------------------------------------------- automations

class NewAutomation(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    doc_ids: list[str] = Field(min_length=1, max_length=20)
    interval_minutes: int = Field(default=1440, ge=1, le=60 * 24 * 31)
    enabled: bool = True


class PatchAutomation(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    prompt: str | None = Field(default=None, min_length=1, max_length=MAX_PROMPT)
    interval_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 31)
    enabled: bool | None = None


def _auto(r) -> dict:
    rep = r["last_report"]
    rep = json.loads(rep) if isinstance(rep, str) else rep
    nxt = (r["last_run_at"] or r["created_at"]) + timedelta(minutes=r["interval_minutes"])
    return {"id": str(r["id"]), "name": r["name"], "prompt": r["prompt"], "doc_ids": list(r["doc_ids"]),
            "interval_minutes": r["interval_minutes"], "enabled": r["enabled"],
            "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None,
            "next_run_at": nxt.isoformat() if r["enabled"] else None,
            "last_report": rep, "created_at": r["created_at"].isoformat()}


def _cite_line(c: dict) -> str:
    what = c.get("label") or c.get("quote") or (f"{len(c['item_ids'])} item(s)" if c.get("item_ids") else "")
    return f"- {c.get('doc_id', '')} p.{c.get('page', '?')}" + (f": {what}" if what else "")


def report_markdown(name: str, prompt: str, ans: dict, ran_at: str) -> str:
    a = ans["answer"]
    lines = [f"# {name}", "", f"_Ran {ran_at}. Question: {prompt}_", "", a["text_md"], ""]
    if a.get("abstained"):
        lines += ["No verified answer was found.", ""]
    cites = ans.get("citations") or []
    if cites:
        lines += ["## Sources", ""] + [_cite_line(c) for c in cites] + [""]
    lines.append(f"Confidence {a.get('confidence', 0):.2f}, cost ${ans['cost']['usd_total']:.4f}.")
    return "\n".join(lines) + "\n"


async def run_automation(pool, row) -> dict:
    """Run one automation now and store its report (one report: the latest)."""
    ran_at = datetime.now(timezone.utc)
    try:
        ans = await _run_prompt(row["prompt"], list(row["doc_ids"]))
        report = {"report_id": uuid.uuid4().hex, "ran_at": ran_at.isoformat(), "ok": True,
                  "markdown": report_markdown(row["name"], row["prompt"], ans, ran_at.isoformat()), "answer": ans}
    except Exception as e:  # noqa: BLE001  a failed run is a report too, never a crash of the scheduler
        report = {"report_id": uuid.uuid4().hex, "ran_at": ran_at.isoformat(), "ok": False,
                  "markdown": f"# {row['name']}\n\nThe run failed: {type(e).__name__}: {str(e)[:200]}\n", "answer": None}
    r = await pool.fetchrow("update automations set last_run_at=$2, last_report=$3::jsonb where id=$1 returning *",
                            row["id"], ran_at, json.dumps(report))
    await publish({"type": "automation.report", "automation_id": str(row["id"]), "report_id": report["report_id"]})
    return _auto(r)


async def run_due(pool, now: datetime | None = None) -> int:
    """Run every enabled automation that is due. Returns how many ran."""
    now = now or datetime.now(timezone.utc)
    rows = await pool.fetch(
        "select * from automations where enabled and coalesce(last_run_at, created_at) + (interval_minutes * interval '1 minute') <= $1 "
        "order by coalesce(last_run_at, created_at)", now)
    n = 0
    for r in rows:
        # claim the row first (compare-and-set on last_run_at) so two API instances, or a restart overlapping a run,
        # never run the same automation twice
        got = await pool.fetchval("update automations set last_run_at=$2 where id=$1 and last_run_at is not distinct from $3 returning 1",
                                  r["id"], now, r["last_run_at"])
        if got:
            await run_automation(pool, r)
            n += 1
    return n


async def scheduler(period: float = 30.0, first: float = 5.0):
    """Background loop started by the app (AUTOMATIONS=0 turns it off). All state is in PostgreSQL (last_run_at), so a
    restart loses nothing: the first tick after `first` seconds catches up on every run that fell due while down."""
    delay = first
    while True:
        await asyncio.sleep(delay)
        delay = period
        with contextlib.suppress(Exception):
            pool = await db.get_pool()
            if pool is not None:
                await run_due(pool)


def scheduler_enabled() -> bool:
    return os.environ.get("AUTOMATIONS", "1") != "0"


@router.get("/automations")
async def list_automations():
    pool = await _pool()
    return {"automations": [_auto(r) for r in await pool.fetch("select * from automations order by created_at, id")]}


@router.post("/automations", status_code=201)
async def create_automation(body: NewAutomation):
    pool = await _pool()
    await _check_docs(pool, body.doc_ids)
    r = await pool.fetchrow(
        "insert into automations (name, prompt, doc_ids, interval_minutes, enabled) values ($1,$2,$3,$4,$5) returning *",
        body.name.strip(), body.prompt.strip(), body.doc_ids, body.interval_minutes, body.enabled)
    return _auto(r)


async def _get(pool, automation_id: str):
    r = await pool.fetchrow("select * from automations where id=$1", _uuid(automation_id))
    if r is None:
        raise HTTPException(404, "automation not found")
    return r


@router.get("/automations/{automation_id}")
async def get_automation(automation_id: str):
    return _auto(await _get(await _pool(), automation_id))


@router.patch("/automations/{automation_id}")
async def patch_automation(automation_id: str, body: PatchAutomation):
    pool = await _pool()
    await _get(pool, automation_id)
    for col, v in body.model_dump(exclude_none=True).items():
        await pool.execute(f"update automations set {col}=$2 where id=$1", _uuid(automation_id), v)  # col is a model field name
    return _auto(await _get(pool, automation_id))


@router.delete("/automations/{automation_id}", status_code=204)
async def delete_automation(automation_id: str):
    pool = await _pool()
    await _get(pool, automation_id)
    await pool.execute("delete from automations where id=$1", _uuid(automation_id))
    return Response(status_code=204)


@router.post("/automations/{automation_id}/run")
async def run_automation_now(automation_id: str):
    pool = await _pool()
    return await run_automation(pool, await _get(pool, automation_id))


@router.get("/automations/{automation_id}/report.pdf")
async def report_pdf(automation_id: str):
    a = _auto(await _get(await _pool(), automation_id))
    if not a["last_report"]:
        raise HTTPException(404, "no report yet")
    from .report_pdf import markdown_to_pdf
    return Response(markdown_to_pdf(a["last_report"]["markdown"], a["name"]), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="report.pdf"'})


@router.get("/automations/{automation_id}/report.md")
async def report_md(automation_id: str):
    a = _auto(await _get(await _pool(), automation_id))
    if not a["last_report"]:
        raise HTTPException(404, "no report yet")
    return Response(a["last_report"]["markdown"], media_type="text/markdown; charset=utf-8")
