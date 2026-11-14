"""Chats and streamed questions (CONTRACT 5.9)."""
import asyncio
import json
import os
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import db, stub_engine
from . import scene_edits
from .live import publish, record_edit
from .schema import validate_answer

router = APIRouter(prefix="/api")

def _real_engine(question, doc_ids, on_event, scene_state=None, history=None):
    from engine.answer import answer  # the function, not the engine.answer module
    return answer(question, doc_ids, on_event, scene_state=scene_state, history=history)


def _run_engine(question, doc_ids, on_event, scene_state=None, history=None):
    # E-20: hidden items from this chat's scene edits shape later answers ("how many windows" after "remove W7").
    # history: earlier turns of this chat, for plain conversation without a document.
    if ENGINE is _real_engine:
        return ENGINE(question, doc_ids, on_event, scene_state=scene_state, history=history)
    return ENGINE(question, doc_ids, on_event)


def _pick_engine():
    # ENGINE_IMPL=stub|real. Default is real; the stub is only for an explicit ENGINE_IMPL=stub
    # (or if engine.answer cannot be imported at all).
    impl = os.environ.get("ENGINE_IMPL", "").strip().lower()
    if impl == "stub":
        return stub_engine.answer
    if impl == "real":
        return _real_engine
    try:
        import engine.answer  # noqa: F401
        return _real_engine
    except Exception:  # noqa: BLE001
        return stub_engine.answer


ENGINE = _pick_engine()

# In-flight questions per chat (this process): lets a device that joins mid-answer catch up on the
# status lines and trace steps so far. Events on /ws carry only small payloads (NOTIFY limit 8 KB).
ACTIVE: dict[str, dict] = {}
MAX_TRACE_EVENTS = 60


def _small(v, n):
    return v[:n] if isinstance(v, str) else v


def _trace_event(chat_id: str, step: dict) -> dict:
    """Trace step trimmed to fit comfortably in a NOTIFY payload."""
    slim = {k: _small(v, 600) for k, v in step.items() if isinstance(v, (str, int, float, bool)) or v is None}
    return {"type": "chat.trace", "chat_id": chat_id, "step": slim}


class NewChat(BaseModel):
    doc_ids: list[str] = []
    title: str | None = None


class NewMessage(BaseModel):
    content: str
    doc_ids: list[str] | None = None


async def _pool():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


def _uuid(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(404, "chat not found")


def _chat(r) -> dict:
    return {"id": str(r["id"]), "doc_id": r["doc_id"], "title": r["title"], "created_at": r["created_at"].isoformat()}


@router.get("/chats")
async def list_chats():
    pool = await _pool()
    rows = await pool.fetch("select id, doc_id, title, created_at from chats order by created_at desc")
    return {"chats": [_chat(r) for r in rows]}


@router.post("/chats")
async def create_chat(body: NewChat):
    pool = await _pool()
    doc_id = body.doc_ids[0] if body.doc_ids else None
    if doc_id and not await pool.fetchval("select 1 from documents where doc_id=$1", doc_id):
        raise HTTPException(404, "document not found")
    r = await pool.fetchrow("insert into chats (doc_id, title) values ($1,$2) returning id, doc_id, title, created_at",
                            doc_id, body.title)
    return _chat(r)


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str):
    pool = await _pool()
    cid = _uuid(chat_id)
    c = await pool.fetchrow("select id, doc_id, title, created_at from chats where id=$1", cid)
    if c is None:
        raise HTTPException(404, "chat not found")
    msgs = await pool.fetch(
        "select m.id, m.role, m.content, m.created_at, a.answer from messages m "
        "left join answers a on a.message_id = m.id where m.chat_id=$1 order by m.created_at, m.id", cid)
    out = []
    for m in msgs:
        a = m["answer"]
        out.append({"id": str(m["id"]), "role": m["role"], "content": m["content"],
                    "created_at": m["created_at"].isoformat(),
                    "answer": json.loads(a) if isinstance(a, str) else a})
    active = ACTIVE.get(str(cid))
    return {**_chat(c), "messages": out, **({"active": active} if active else {})}


@router.get("/chats/{chat_id}/scene-state")
async def get_scene_state(chat_id: str, doc_id: str | None = None):
    """Current scene edit layer of a chat: one state per doc that has edits (CONTRACT 5.11)."""
    pool = await _pool()
    cid = _uuid(chat_id)
    if await pool.fetchval("select 1 from chats where id=$1", cid) is None:
        raise HTTPException(404, "chat not found")
    states = await scene_edits.scene_state(pool, cid, doc_id)
    return {"chat_id": str(cid), "states": [{k: v for k, v in s.items() if k != "type"} for s in states]}


async def _attach_advice(ans: dict, doc_ids: list[str], hidden: list[str], cid) -> None:
    """FIX-4: a hide/remove command in chat runs the advisor on the edited model (everything hidden in this chat so far
    plus this command). The cards go on the answer (`advisor_cards`) and out over /ws. Never blocks the answer."""
    try:
        from .advise_routes import _engine_advise, clean_cards
        fn = _engine_advise()
        scene = ans.get("evidence", {}).get("scene") or {}
        doc_id = scene.get("doc_id") or (doc_ids[0] if doc_ids else None)
        cmd = next((c for c in scene.get("commands") or [] if isinstance(c, dict) and c.get("op") == "hide" and c.get("item_ids")), None)
        if fn is None or not doc_id or cmd is None:
            return
        ids = list(dict.fromkeys([*hidden, *cmd["item_ids"]]))
        cards = clean_cards(await asyncio.to_thread(fn, doc_id, {"op": "hide", "item_ids": ids}, str(cid)), doc_id)
        if cards:
            ans["advisor_cards"] = cards
            await publish({"type": "advisor.cards", "doc_id": doc_id, "chat_id": str(cid), "cards": cards})
    except Exception:  # noqa: BLE001  the advisor never takes the chat down
        return


@router.post("/chats/{chat_id}/messages")
async def ask(chat_id: str, body: NewMessage):
    pool = await _pool()
    cid = _uuid(chat_id)
    c = await pool.fetchrow("select id, doc_id from chats where id=$1", cid)
    if c is None:
        raise HTTPException(404, "chat not found")
    doc_ids = body.doc_ids or ([c["doc_id"]] if c["doc_id"] else [])
    from . import artifact_store
    for _d in doc_ids:  # uploaded docs: files may only be in PostgreSQL after a container restart
        await artifact_store.ensure_doc(_d)
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(await pool.fetch(
        "select role, content from messages where chat_id=$1 order by created_at desc limit 10", cid))]
    umid = await pool.fetchval(
        "insert into messages (chat_id, role, content) values ($1,'user',$2) returning id", cid, body.content)
    ACTIVE[str(cid)] = {"question": body.content, "statuses": ["Thinking…"], "traces": []}
    await publish({"type": "chat.message", "chat_id": str(cid), "message_id": str(umid), "role": "user",
                   "text": body.content[:300]})

    hidden: list[str] = []
    try:
        for st in await scene_edits.scene_state(pool, cid):
            if not doc_ids or st.get("doc_id") in doc_ids:
                hidden.extend(st.get("hidden") or [])
    except Exception:  # noqa: BLE001 — scene state is optional context, never block the answer
        hidden = []
    sstate = {"hidden": hidden} if hidden else None

    async def stream():
        try:
            async for ev in _stream():
                yield ev
        finally:
            if ACTIVE.pop(str(cid), None) is not None:  # failed or abandoned: tell watchers to resync
                await publish({"type": "chat.done", "chat_id": str(cid)})

    async def _stream():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def on_event(kind, payload):
            loop.call_soon_threadsafe(q.put_nowait, (kind, payload))

        task = asyncio.create_task(asyncio.to_thread(_run_engine, body.content, doc_ids, on_event, sstate, history))
        task.add_done_callback(lambda _: loop.call_soon_threadsafe(q.put_nowait, None))
        while (item := await q.get()) is not None:
            act = ACTIVE.get(str(cid))
            if item[0] == "status":
                text = item[1].get("text", "")
                if act is not None and act["statuses"][-1:] != [text]:
                    act["statuses"] = (act["statuses"] + [text])[-20:]
                await publish({"type": "chat.status", "chat_id": str(cid), "text": text})
            elif item[0] == "trace" and isinstance(item[1], dict):
                ev = _trace_event(str(cid), item[1])
                if act is not None and len(act["traces"]) < MAX_TRACE_EVENTS:
                    act["traces"].append(ev["step"])
                    await publish(ev)
            yield {"event": item[0], "data": json.dumps(item[1])}
        try:
            ans = task.result()
            validate_answer(ans)
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"detail": f"engine failed: {e}"})}
            return
        await _attach_advice(ans, doc_ids, hidden, cid)
        mid = await pool.fetchval(
            "insert into messages (chat_id, role, content) values ($1,'assistant',$2) returning id",
            cid, ans["answer"]["text_md"])
        await pool.execute("insert into answers (message_id, chat_id, doc_id, answer) values ($1,$2,$3,$4::jsonb)",
                           mid, cid, doc_ids[0] if doc_ids else None, json.dumps(ans))
        ACTIVE.pop(str(cid), None)  # before the notification, so the resync snapshot shows no live job
        await publish({"type": "chat.message", "chat_id": str(cid), "message_id": str(mid), "role": "assistant"})
        scene = ans["evidence"]["scene"]
        for n, cmd in enumerate(scene.get("commands") or []):  # answer commands become persisted, relayed edits
            if isinstance(cmd, dict):
                await record_edit({**cmd, "doc_id": scene.get("doc_id") or (doc_ids[0] if doc_ids else ""),
                                   "edit_id": f"{ans['answer_id']}-{n}"}, chat_id=cid)
        yield {"event": "answer", "data": json.dumps(ans)}

    return EventSourceResponse(stream())
