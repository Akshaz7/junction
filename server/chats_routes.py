"""Chats and streamed questions (CONTRACT 5.9)."""
import asyncio
import json
import os
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import config, db, stub_engine
from . import scene_edits
from .live import publish, record_edit
from .schema import validate_answer

router = APIRouter(prefix="/api")

def _real_engine(question, doc_ids, on_event, scene_state=None, history=None):
    from engine.answer import answer  # the function, not the engine.answer module
    return answer(question, doc_ids, on_event, scene_state=scene_state, history=history)


def _no_data_answer(question, doc_ids, on_event=None):
    """Selected documents that have nothing to answer from (no IFC elements, plan map or PDF text): refuse at once,
    $0, before any model call. Returns an answer object or None."""
    # Only real dataset/upload ids ("source__name"); ids without "__" are never refused here.
    if not doc_ids or ENGINE is not _real_engine or os.environ.get("FAST_REFUSE", "1") == "0" \
            or any("__" not in d for d in doc_ids):
        return None
    try:
        from pathlib import Path

        from engine.solvers.data import load_doc, load_sheet_parent
        from engine.solvers.solve import _abstain, _step
        root = Path(config.artifacts_dir())
        for d in doc_ids:
            dd = root / d
            if load_doc(d, root) or load_sheet_parent(d, root) or any(dd.glob("text*.json")) or any(dd.glob("page-*.png")):   # a page image: the drawing reader can still answer
                return None
        running = any(json.loads((root / d / "ingest.json").read_text()).get("status") == "running"
                      for d in doc_ids if (root / d / "ingest.json").is_file())
        why = ("This document is still being processed, so there is nothing to answer from yet. Try again in a moment."
               if running else "This document has no readable drawing data on this server (no plan map, model or text), "
               "so I cannot answer questions about it.")
        t0 = time.perf_counter()
        if on_event:
            on_event("status", {"text": "Checking the document\u2026"})
        return _abstain(question, doc_ids[0], why, [_step("route", "no data for the selected document -> refused, no model call")],
                        "index", t0)
    except Exception:  # noqa: BLE001  the check only ever saves time; the engine decides otherwise
        return None


def _run_engine(question, doc_ids, on_event, scene_state=None, history=None, catalogue=None):
    if ENGINE is _real_engine:
        from engine.library import CATALOGUE, drawing_selection_answer, library_answer, library_search_answer, sheet_count_answer
        token = CATALOGUE.set(catalogue)
        try:
            root = config.artifacts_dir()
            quick = library_answer(question, root) or sheet_count_answer(question, doc_ids, root)
            if quick is None and not doc_ids:
                quick = library_search_answer(question, root) or drawing_selection_answer(question, root, history)
            if quick is not None:
                for step in quick.get("trace", []):
                    on_event("trace", step)
                return quick
            return _selected_engine(question, doc_ids, on_event, scene_state, history)
        finally:
            CATALOGUE.reset(token)
    return _selected_engine(question, doc_ids, on_event, scene_state, history)


def _selected_engine(question, doc_ids, on_event, scene_state=None, history=None):
    quick = _no_data_answer(question, doc_ids, on_event)
    if quick is not None:
        return quick
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
DELTA_INTERVAL = 0.125  # at most ~8 text updates per second on /ws and SSE
MAX_DELTA_CHARS = 6000  # cumulative text per event; keeps NOTIFY under 8 KB


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
async def list_chats(limit: int | None = None):
    """Newest first. `limit` (1-1000) caps the rows; without it every chat is returned (older clients)."""
    pool = await _pool()
    q = "select id, doc_id, title, created_at from chats order by created_at desc"
    if limit is not None:
        rows = await pool.fetch(q + " limit $1", max(1, min(int(limit), 1000)))
    else:
        rows = await pool.fetch(q)
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
    """FIX-4: a hide/remove command in chat runs the advisor on the edited model (everything hidden in this chat so far,
    manual edits included, plus this command). The cards go on the answer (`advisor_cards`) and out over /ws.
    A restore/reset re-checks what stays hidden and pushes those cards (or none) so the Edit panel matches. Never blocks."""
    try:
        from .advise_routes import _engine_advise, clean_cards, effective_edit
        fn = _engine_advise()
        scene = ans.get("evidence", {}).get("scene") or {}
        doc_id = scene.get("doc_id") or (doc_ids[0] if doc_ids else None)
        cmd = next((c for c in scene.get("commands") or [] if isinstance(c, dict) and c.get("op") in ("hide", "restore", "reset")
                    and (c.get("item_ids") or c.get("op") != "hide")), None)
        if fn is None or not doc_id or cmd is None or (cmd["op"] != "hide" and not hidden):
            return
        edit = effective_edit(hidden, {"op": cmd["op"], "item_ids": list(cmd.get("item_ids") or [])})
        if edit["op"] != "hide":   # nothing left hidden: no cards, and the panel clears
            await publish({"type": "advisor.cards", "doc_id": doc_id, "chat_id": str(cid), "cards": []})
            return
        cards = clean_cards(await asyncio.to_thread(fn, doc_id, edit, str(cid)), doc_id)
        if cmd["op"] != "hide":
            await publish({"type": "advisor.cards", "doc_id": doc_id, "chat_id": str(cid), "cards": cards})
        elif cards:
            ans["advisor_cards"] = cards
            await publish({"type": "advisor.cards", "doc_id": doc_id, "chat_id": str(cid), "cards": cards})
    except Exception:  # noqa: BLE001  the advisor never takes the chat down
        return


@router.post("/chats/{chat_id}/messages")
async def ask(chat_id: str, body: NewMessage):
    if len(body.content) > 8000:
        raise HTTPException(413, "Message content exceeds 8,000 characters")
    cid = _uuid(chat_id)
    # Refusals must be HTTP errors, before SSE commits the response headers.
    pool = await _pool()
    c = await pool.fetchrow("select id, doc_id from chats where id=$1", cid)
    if c is None:
        raise HTTPException(404, "chat not found")
    doc_ids = body.doc_ids if body.doc_ids is not None else ([c["doc_id"]] if c["doc_id"] else [])
    if doc_ids:
        from .changes_source import visible_doc_ids
        listed = await visible_doc_ids(pool)
        if any(d not in listed for d in doc_ids):
            raise HTTPException(404, "document not found")

    async def stream():
        try:
            # Flush before restoring documents, loading history or writing the user turn.
            yield {"event": "status", "data": json.dumps({"text": "Thinking…"})}
            async for ev in _stream():
                yield ev
        except HTTPException as e:
            # Headers are already sent; retain the usual detail in the SSE error envelope.
            yield {"event": "error", "data": json.dumps({"detail": e.detail})}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"detail": f"request failed: {e}"})}
        finally:
            if ACTIVE.pop(str(cid), None) is not None:  # failed or abandoned: tell watchers to resync
                await publish({"type": "chat.done", "chat_id": str(cid)})

    async def _stream():
        from . import artifact_store
        for _d in doc_ids:  # uploaded docs: files may only be in PostgreSQL after a container restart
            await artifact_store.ensure_doc(_d)
        def _ids(v):   # answers.answer->'doc_ids' (jsonb text) of an assistant turn: thread memory resolves "this one" / "and doors?" with it
            try:
                v = json.loads(v) if isinstance(v, str) else v
                return [d for d in v if isinstance(d, str)] if isinstance(v, list) else []
            except ValueError:
                return []
        history = [{"role": r["role"], "content": r["content"], "doc_ids": _ids(r["doc_ids"])} for r in reversed(await pool.fetch(
            "select m.role, m.content, (select a.answer->'doc_ids' from answers a where a.message_id=m.id limit 1) as doc_ids "
            "from messages m where m.chat_id=$1 order by m.created_at desc limit 10", cid))]
        umid = await pool.fetchval(
            "insert into messages (chat_id, role, content) values ($1,'user',$2) returning id", cid, body.content)
        ACTIVE[str(cid)] = {"question": body.content, "statuses": ["Thinking…"], "traces": []}
        await publish({"type": "chat.message", "chat_id": str(cid), "message_id": str(umid), "role": "user",
                       "text": body.content[:300]})

        try:  # shared edit layer: chat commands and manual Edit-panel removals of this chat
            sstate = await scene_edits.chat_context(pool, cid, doc_ids)
        except Exception:  # noqa: BLE001 — scene state is optional context, never block the answer
            sstate = None
        hidden: list[str] = list((sstate or {}).get("hidden") or [])

        catalogue = None
        if ENGINE is _real_engine:
            from engine.library import wants_library, _SHEETS
            if not doc_ids or wants_library(body.content) or _SHEETS.search(body.content):
                from .docs_routes import library_catalogue
                catalogue = await library_catalogue(pool)

        from .answer_progress import AnswerProgress, partial_deadline
        progress = AnswerProgress(body.content, doc_ids)
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        accepting = True

        def on_event(kind, payload):
            if accepting:
                try:
                    loop.call_soon_threadsafe(q.put_nowait, (kind, payload))
                except RuntimeError:  # a disconnected request's loop may already be closed
                    pass

        task = asyncio.create_task(asyncio.to_thread(_run_engine, body.content, doc_ids, on_event, sstate, history, catalogue))
        task.add_done_callback(lambda _: q.put_nowait(None) if accepting else None)
        deadline = time.monotonic() + partial_deadline()
        last_delta = 0.0
        # Kept inside this request so delta throttling and ACTIVE always belong to this chat.
        async def relay(item):
            nonlocal last_delta
            act = ACTIVE.get(str(cid))
            if item[0] == "status":
                text = item[1].get("text", "")
                if act is not None and act["statuses"][-1:] != [text]:
                    act["statuses"] = (act["statuses"] + [text])[-20:]
                await publish({"type": "chat.status", "chat_id": str(cid), "text": text})
            elif item[0] == "answer.delta":
                txt = str(item[1].get("text", ""))[:MAX_DELTA_CHARS]
                if act is not None:
                    act["text"] = txt
                now = time.monotonic()
                if now - last_delta >= DELTA_INTERVAL:
                    last_delta = now
                    await publish({"type": "chat.delta", "chat_id": str(cid), "text": txt})
                    yield {"event": "delta", "data": json.dumps({"text": txt})}
                return
            elif item[0] == "answer.partial":
                # Snapshots include citations and are persisted if the deadline expires.
                # Existing clients see ordinary delta text while the engine keeps checking.
                txt = str(progress.snapshot["answer"].get("text_md") or "") if progress.snapshot else ""
                if act is not None and txt:
                    act["text"] = txt[:MAX_DELTA_CHARS]
                if txt:
                    await publish({"type": "chat.delta", "chat_id": str(cid), "text": txt[:MAX_DELTA_CHARS]})
                    yield {"event": "delta", "data": json.dumps({"text": txt})}
                return
            elif item[0] == "trace" and isinstance(item[1], dict):
                ev = _trace_event(str(cid), item[1])
                if act is not None and len(act["traces"]) < MAX_TRACE_EVENTS:
                    act["traces"].append(ev["step"])
                    await publish(ev)
            yield {"event": item[0], "data": json.dumps(item[1])}

        ans = None
        try:
            while True:
                left = deadline - time.monotonic()
                if left <= 0 and not task.done():
                    while not q.empty():
                        pending = q.get_nowait()
                        if pending is not None:
                            progress.update(*pending)
                    ans = progress.partial()
                    break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=max(0.001, left))
                except asyncio.TimeoutError:
                    if not task.done():
                        ans = progress.partial()
                    break
                if item is None:
                    break
                progress.update(*item)
                async for event in relay(item):
                    yield event
        finally:
            accepting = False
            if not task.done():
                task.cancel()  # suppress late events/results; Python cannot interrupt a provider's running thread
        try:
            ans = ans if ans is not None else task.result()
            validate_answer(ans)
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"detail": f"engine failed: {e}"})}
            return
        await _attach_advice(ans, doc_ids, hidden, cid)
        mid = await pool.fetchval(
            "insert into messages (chat_id, role, content) values ($1,'assistant',$2) returning id",
            cid, ans["answer"]["text_md"])
        answer_docs = ans.get("doc_ids") or doc_ids
        await pool.execute("insert into answers (message_id, chat_id, doc_id, answer) values ($1,$2,$3,$4::jsonb)",
                           mid, cid, answer_docs[0] if answer_docs else None, json.dumps(ans))
        ACTIVE.pop(str(cid), None)  # before the notification, so the resync snapshot shows no live job
        await publish({"type": "chat.message", "chat_id": str(cid), "message_id": str(mid), "role": "assistant"})
        scene = ans["evidence"]["scene"]
        for n, cmd in enumerate(scene.get("commands") or []):
            if isinstance(cmd, dict):
                await record_edit({**cmd, "doc_id": scene.get("doc_id") or (doc_ids[0] if doc_ids else ""),
                                   "edit_id": f"{ans['answer_id']}-{n}"}, chat_id=cid)
        yield {"event": "answer", "data": json.dumps(ans)}


    return EventSourceResponse(stream())
