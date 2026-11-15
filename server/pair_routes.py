"""Device pairing: a pair code links a laptop and a phone so each knows the other's chats.

The code is a random secret the laptop shows as a QR code. Devices register the chats they create under their
codes; a paired device asks whether an unknown chat belongs to one of its codes. Postgres when available
(table created on first use), otherwise process memory. No accounts: the code is the only credential.
"""
import asyncio
import hashlib
import logging
import re

from fastapi import APIRouter, HTTPException

from . import db, live

router = APIRouter(prefix="/api/pair")
CODE = re.compile(r"^[A-Za-z0-9]{6,32}$")
_memory: dict[str, set[str]] = {}
_ready = False
MAX_PER_CODE = 500
_tasks: set[asyncio.Task] = set()
log = logging.getLogger(__name__)


def _code(code: str) -> str:
    if not CODE.match(code):
        raise HTTPException(400, "invalid pair code")
    return code


async def _pool():
    global _ready
    pool = await db.get_pool()
    if pool is not None and not _ready:
        await pool.execute("create table if not exists pair_chats (code text not null, chat_id text not null, "
                           "created_at timestamptz not null default now(), primary key (code, chat_id))")
        _ready = True
    return pool


def _remember(code: str, chat_id: str) -> None:
    """In-process (code, chat_id) set: answers checks in microseconds on this instance; the DB covers other instances."""
    known = _memory.setdefault(code, set())
    if chat_id in known or len(known) < MAX_PER_CODE:
        known.add(chat_id)


async def _persist(code: str, chat_id: str) -> None:
    try:
        pool = await _pool()
        if pool is not None:
            await pool.execute("insert into pair_chats (code, chat_id) values ($1,$2) on conflict do nothing", code, chat_id)
    except Exception:  # the in-process set still serves this instance
        log.warning("pair register: DB write failed", exc_info=True)


def proof(code: str, chat_id: str) -> str:
    """Lets a paired device recognise the chat from a live event without the code being broadcast."""
    return hashlib.sha256(f"{code}:{chat_id}".encode()).hexdigest()[:16]


def join_proof(code: str) -> str:
    """Lets the laptop that shows `code` recognise "a phone joined" from a live event without the code being broadcast."""
    return hashlib.sha256(f"join:{code}".encode()).hexdigest()[:16]


@router.post("/{code}/join", status_code=204)
async def join(code: str):
    """The phone that scanned `code` says so: the hosting laptop switches from 'Waiting for phone' to 'Paired'."""
    code = _code(code)
    try:
        await live.publish({"type": "pair.joined", "proof": join_proof(code)})
    except Exception:
        log.warning("pair join: live publish failed", exc_info=True)


@router.post("/{code}/chats/{chat_id}", status_code=204)
async def register(code: str, chat_id: str):
    code = _code(code)
    if not (0 < len(chat_id) <= 80):
        raise HTTPException(400, "invalid chat id")
    _remember(code, chat_id)
    try:  # instant path: paired sockets learn the chat belongs to them before its first message event
        await live.publish({"type": "pair.chat", "chat_id": chat_id, "proof": proof(code, chat_id)})
    except Exception:
        log.warning("pair register: live publish failed", exc_info=True)
    task = asyncio.create_task(_persist(code, chat_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@router.get("/{code}/chats/{chat_id}")
async def check(code: str, chat_id: str):
    code = _code(code)
    if chat_id in _memory.get(code, set()):
        return {"paired": True}
    pool = await _pool()
    if pool is None:
        return {"paired": False}
    found = await pool.fetchval("select 1 from pair_chats where code=$1 and chat_id=$2", code, chat_id)
    if found:
        _remember(code, chat_id)
    return {"paired": bool(found)}
