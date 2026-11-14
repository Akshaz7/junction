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

CHANNEL = "hologram_events"


def channel() -> str:
    """Channel name. A non-public search_path (isolated test schemas) gets its own channel so
    parallel runs and the dev server sharing one database never see each other's events."""
    import re
    m = re.search(r"search_path(?:%3D|=)([A-Za-z0-9_]+)", config.database_url())
    return f"{CHANNEL}_{m.group(1)}" if m and m.group(1) != "public" else CHANNEL
PING_INTERVAL = 20.0  # seconds; keeps Aiven's proxy from cutting idle sockets
CLIENT_EVENTS = {"scene.highlight", "scene.edit"}  # event types clients may send


class Hub:
    def __init__(self):
        self.sockets: set[WebSocket] = set()
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
        asyncio.get_running_loop().create_task(self.broadcast(event))

    async def broadcast(self, event: dict):
        text = json.dumps(event)
        for ws in list(self.sockets):
            try:
                await ws.send_text(text)
            except Exception:
                self.sockets.discard(ws)


hub = Hub()
router = APIRouter()


async def publish(event: dict) -> None:
    """Send an event to every connected client on every server instance."""
    if hub.listening.is_set():
        pool = await db.get_pool()
        if pool is not None:
            try:
                await pool.execute("select pg_notify($1, $2)", channel(), json.dumps(event))
                return
            except Exception:
                pass
    await hub.broadcast(event)


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
    await publish(event)
    return event


async def send_scene_state(ws: WebSocket, chat_id, doc_id: str | None = None) -> None:
    """Send the current edit layer of a chat to one socket (one scene.state per doc)."""
    cid = _chat_uuid(chat_id)
    pool = await db.get_pool() if cid else None
    if pool is None:
        return
    for st in await scene_edits.scene_state(pool, cid, doc_id):
        await ws.send_text(json.dumps({**st, "chat_id": str(cid)}))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(hub.listening.wait(), timeout=3)
    await ws.accept()
    hub.sockets.add(ws)
    try:
        if ws.query_params.get("chat_id"):  # late joiner: current edit layer first
            await send_scene_state(ws, ws.query_params["chat_id"], ws.query_params.get("doc_id"))
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=PING_INTERVAL)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if t == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            elif t == "scene.join":
                await send_scene_state(ws, msg.get("chat_id"), msg.get("doc_id") if isinstance(msg.get("doc_id"), str) else None)
            elif t == "scene.edit":
                if await record_edit(msg) is None and scene_edits.clean_edit(msg) is None:
                    await ws.send_text(json.dumps({"type": "scene.error", "detail": "invalid scene.edit"}))
            elif t in CLIENT_EVENTS:
                if t == "scene.highlight":
                    ids = [str(i) for i in (msg.get("item_ids") or [])][:500]
                    event = {"type": t, "doc_id": str(msg.get("doc_id", "")), "item_ids": ids}
                    labels = clean_labels(msg.get("labels"), ids)
                    if labels:
                        event["labels"] = labels
                await publish(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.sockets.discard(ws)
