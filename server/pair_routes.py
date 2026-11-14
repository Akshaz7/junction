"""Device pairing: a pair code links a laptop and a phone so each knows the other's chats.

The code is a random secret the laptop shows as a QR code. Devices register the chats they create under their
codes; a paired device asks whether an unknown chat belongs to one of its codes. Postgres when available
(table created on first use), otherwise process memory. No accounts: the code is the only credential.
"""
import re

from fastapi import APIRouter, HTTPException

from . import db

router = APIRouter(prefix="/api/pair")
CODE = re.compile(r"^[A-Za-z0-9]{6,32}$")
_memory: dict[str, set[str]] = {}
_ready = False
MAX_PER_CODE = 500


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


@router.post("/{code}/chats/{chat_id}", status_code=204)
async def register(code: str, chat_id: str):
    code = _code(code)
    if not (0 < len(chat_id) <= 80):
        raise HTTPException(400, "invalid chat id")
    pool = await _pool()
    if pool is None:
        if len(_memory.setdefault(code, set())) < MAX_PER_CODE:
            _memory[code].add(chat_id)
        return
    await pool.execute("insert into pair_chats (code, chat_id) values ($1,$2) on conflict do nothing", code, chat_id)


@router.get("/{code}/chats/{chat_id}")
async def check(code: str, chat_id: str):
    code = _code(code)
    pool = await _pool()
    if pool is None:
        return {"paired": chat_id in _memory.get(code, set())}
    found = await pool.fetchval("select 1 from pair_chats where code=$1 and chat_id=$2", code, chat_id)
    return {"paired": bool(found)}
