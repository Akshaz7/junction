"""Live sync (S-06): PostgreSQL LISTEN/NOTIFY -> WebSocket /ws.

Every event is a small JSON object {"type": ..., ...ids}; clients refetch. Writers call `publish()`
(pg_notify). One LISTEN connection per process fans events out to all sockets, and reconnects on drop.
If no listener connection is up (no DB) events are broadcast to local sockets directly.
"""
import asyncio
import contextlib
import json
import time
import uuid

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import config, db, scene_edits
from .live_labels import clean_labels  # noqa: F401  (re-exported)
from .ws_guard import InboundLimit, MAX_FRAME_BYTES, scene_target_error

CHANNEL = "hologram_events"


def channel() -> str:
    """Channel name. A non-public search_path (isolated test schemas) gets its own channel so
    parallel runs and the dev server sharing one database never see each other's events."""
    import re
    m = re.search(r"search_path(?:%3D|=)([A-Za-z0-9_]+)", config.database_url())
    return f"{CHANNEL}_{m.group(1)}" if m and m.group(1) != "public" else CHANNEL
INSTANCE = uuid.uuid4().hex  # tags our own NOTIFYs so _on_notify can skip them
PING_INTERVAL = 20.0  # seconds; keeps Aiven's proxy from cutting idle sockets
# Web viewer: highlight/edit/pong; iOS LiveSocket: highlight/pong.
# ping and scene.join are the existing keepalive and late-join requests.
CLIENT_EVENTS = frozenset({"ping", "pong", "scene.join", "scene.highlight", "scene.edit", "subscribe"})
MAX_SUBSCRIBED_CHATS = 50


def wants(scope: dict | None, event: dict) -> bool:
    """F-WSSCOPE: chat.* events go only to sockets that asked for that chat.

    scope None = a client that never sent `subscribe` (iOS, the 3D viewer, older web builds): it gets everything.
    A subscribed socket gets, for chat.* events: every event of its `chat_ids`, plus (when `summaries`) the
    one-per-message `chat.message` of any chat (overview list, Follow). doc.*, scene.*, pair.* stay global."""
    t = event.get("type")
    if scope is None or not isinstance(t, str) or not t.startswith("chat."):
        return True
    cid = event.get("chat_id")
    if cid is None:
        return True
    return str(cid) in scope["chat_ids"] or (scope["summaries"] and t == "chat.message")


class Hub:
    def __init__(self):
        self.sockets: set[WebSocket] = set()
        self.scopes: dict[WebSocket, dict] = {}  # only sockets that sent `subscribe`
        self.listening = asyncio.Event()  # recreated in start(): one hub, possibly several event loops (tests)
        self._task: asyncio.Task | None = None
        self._conn: asyncpg.Connection | None = None

    def start(self):
        if self._task is None:
            self.listening = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
            self._task = None
        self.listening.clear()

    async def _run(self):
        while True:
            conn = None
            try:
                conn = await asyncio.wait_for(asyncpg.connect(config.database_url()), timeout=3)
                await conn.add_listener(channel(), self._on_notify)
                self._conn = conn
                self.listening.set()
                while not conn.is_closed():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                self.listening.clear()
                self._conn = None
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.close(timeout=1)
            await asyncio.sleep(1)  # reconnect

    def _on_notify(self, _conn, _pid, _channel, payload):
        try:
            event = json.loads(payload)
        except ValueError:
            return
        if event.pop("_o", None) == INSTANCE:
            return  # this process already delivered it directly in publish()
        asyncio.get_running_loop().create_task(self.broadcast(event))

    async def broadcast(self, event: dict):
        text = json.dumps(event)
        for ws in list(self.sockets):
            if not wants(self.scopes.get(ws), event):
                continue
            try:
                await ws.send_text(text)
            except Exception:
                self.sockets.discard(ws)


hub = Hub()
router = APIRouter()


_outbox: "asyncio.Queue[str] | None" = None
_outbox_task: asyncio.Task | None = None
_outbox_loop = None


async def _pump(q: "asyncio.Queue[str]") -> None:
    """Send NOTIFYs in order, off the request path (cross-instance fan-out only)."""
    while True:
        payload = await q.get()
        try:
            pool = await db.get_pool()
            if pool is not None:
                await pool.execute("select pg_notify($1, $2)", channel(), payload)
        except Exception:
            pass


async def publish(event: dict) -> None:
    """Deliver to this instance's sockets immediately; NOTIFY the other instances in the background.

    Direct delivery avoids the NOTIFY round trip (app and Postgres sit in different clouds, ~1 s)."""
    global _outbox, _outbox_task, _outbox_loop
    await hub.broadcast(event)
    if not hub.listening.is_set():
        return
    loop = asyncio.get_running_loop()
    if _outbox is None or _outbox_loop is not loop or _outbox_task is None or _outbox_task.done():
        _outbox, _outbox_loop = asyncio.Queue(), loop
        _outbox_task = loop.create_task(_pump(_outbox))
    _outbox.put_nowait(json.dumps({**event, "_o": INSTANCE}))


def _chat_uuid(v):
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None


async def record_edit(msg: dict, chat_id=None) -> dict | None:
    """Validate, persist (when a chat is given) and publish one scene edit. Returns the event, or None
    when invalid or already seen (same edit_id)."""
    e = scene_edits.clean_edit(msg)
    if e is None:
        return None
    cid = _chat_uuid(chat_id if chat_id is not None else msg.get("chat_id"))
    if cid is not None:
        pool = await db.get_pool()
        if pool is not None:
            try:
                if not await scene_edits.store_edit(pool, cid, e):
                    return None
            except asyncpg.ForeignKeyViolationError:
                return None
    event = {"type": "scene.edit", "doc_id": e["doc_id"], "op": e["op"], "item_ids": e["item_ids"],
             "edit_id": e["edit_id"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if cid is not None:
        event["chat_id"] = str(cid)
    if e["labels"]:
        event["labels"] = e["labels"]
    event.update(e.get("detail") or {})  # move: offset_m, material: material (shared edit layer)
    await publish(event)
    return event


async def send_scene_state(ws: WebSocket, chat_id, doc_id: str | None = None) -> None:
    """Send the current edit layer of a chat to one socket (one scene.state per doc)."""
    cid = _chat_uuid(chat_id)
    pool = await db.get_pool() if cid else None
    if pool is None:
        return
    for st in await scene_edits.scene_state(pool, cid, doc_id):
        await ws.send_text(json.dumps({**scene_edits.public_state(st), "chat_id": str(cid)}))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(hub.listening.wait(), timeout=3)
    await ws.accept()
    hub.sockets.add(ws)
    inbound = InboundLimit()
    try:
        if ws.query_params.get("chat_id"):  # late joiner: current edit layer first
            await send_scene_state(ws, ws.query_params["chat_id"], ws.query_params.get("doc_id"))
        while True:
            try:
                frame = await asyncio.wait_for(ws.receive(), timeout=PING_INTERVAL)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
                continue
            if frame["type"] == "websocket.disconnect":
                break
            raw = frame.get("text")
            data = frame.get("bytes")
            if (len(raw.encode("utf-8")) if raw is not None else len(data or b"")) > MAX_FRAME_BYTES:
                await ws.close(code=1009)
                break
            allowed, notice = inbound.accept()
            if not allowed:
                if notice:
                    await ws.send_text(json.dumps({"type": "error", "code": "rate_limited"}))
                continue
            if raw is None:  # binary messages have no client event shape
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if not isinstance(t, str) or t not in CLIENT_EVENTS:
                continue
            if t in {"scene.highlight", "scene.edit"}:
                error = await scene_target_error(msg)
                if error:
                    await ws.send_text(json.dumps({"type": "scene.error", "detail": error}))
                    continue
            if t == "subscribe":
                ids = msg.get("chat_ids")
                ids = [str(i) for i in ids if isinstance(i, str) and i][:MAX_SUBSCRIBED_CHATS] if isinstance(ids, list) else []
                hub.scopes[ws] = {"chat_ids": set(ids), "summaries": msg.get("summaries") is True}
                await ws.send_text(json.dumps({"type": "subscribed", "chat_ids": sorted(hub.scopes[ws]["chat_ids"]),
                                               "summaries": hub.scopes[ws]["summaries"]}))
            elif t == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            elif t == "scene.join":
                await send_scene_state(ws, msg.get("chat_id"), msg.get("doc_id") if isinstance(msg.get("doc_id"), str) else None)
            elif t == "scene.edit":
                if await record_edit(msg) is None and scene_edits.clean_edit(msg) is None:
                    await ws.send_text(json.dumps({"type": "scene.error", "detail": "invalid scene.edit"}))
            elif t == "scene.highlight":
                ids = msg.get("item_ids", [])
                event = {"type": t, "doc_id": msg["doc_id"], "item_ids": ids}
                labels = clean_labels(msg.get("labels"), ids)
                if labels:
                    event["labels"] = labels
                await publish(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.sockets.discard(ws)
        hub.scopes.pop(ws, None)
