"""Live sync (S-06): PostgreSQL LISTEN/NOTIFY -> WebSocket /ws.

Every event is a small JSON object {"type": ..., ...ids}; clients refetch. Writers call `publish()`
(pg_notify). One LISTEN connection per process fans events out to all sockets, and reconnects on drop.
If no listener connection is up (no DB) events are broadcast to local sockets directly.
"""
import asyncio
import contextlib
import json

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import config, db

CHANNEL = "hologram_events"
PING_INTERVAL = 20.0  # seconds; keeps Aiven's proxy from cutting idle sockets
CLIENT_EVENTS = {"scene.highlight"}  # event types clients may send


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
                await conn.add_listener(CHANNEL, self._on_notify)
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
                await pool.execute("select pg_notify($1, $2)", CHANNEL, json.dumps(event))
                return
            except Exception:
                pass
    await hub.broadcast(event)


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(hub.listening.wait(), timeout=3)
    await ws.accept()
    hub.sockets.add(ws)
    try:
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
            elif t in CLIENT_EVENTS:
                if t == "scene.highlight":
                    event = {"type": t, "doc_id": str(msg.get("doc_id", "")),
                             "item_ids": [str(i) for i in (msg.get("item_ids") or [])][:500]}
                await publish(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.sockets.discard(ws)
