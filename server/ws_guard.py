"""Bounds and target validation for client-originated live events (S-29)."""
import asyncio
from collections import deque
from functools import lru_cache
import json
from pathlib import Path
import re
import time

from . import artifact_store, config, db, docmeta_store
from .changes_source import visible_doc_ids

MAX_FRAME_BYTES = 64 * 1024


class InboundLimit:
    """Rolling windows, bounded memory, one notice per uninterrupted throttled burst."""
    def __init__(self):
        self.seconds = deque()
        self.minutes = deque()
        self.notified = False

    def accept(self) -> tuple[bool, bool]:
        now = time.monotonic()
        for window, duration in ((self.seconds, 1), (self.minutes, 60)):
            while window and window[0] <= now - duration:
                window.popleft()
        if len(self.seconds) >= 20 or len(self.minutes) >= 200:
            notice = not self.notified
            self.notified = True
            return False, notice
        self.seconds.append(now)
        self.minutes.append(now)
        self.notified = False
        return True, False


def _manifest_ids(raw) -> frozenset[str]:
    scene = json.loads(raw)
    if not isinstance(scene, dict) or not isinstance(scene.get("items"), dict):
        raise ValueError("invalid scene manifest")
    return frozenset(scene["items"])


@lru_cache(maxsize=32)
def _local_ids(path: str, mtime_ns: int, size: int) -> frozenset[str]:
    return _manifest_ids(Path(path).read_bytes())


async def scene_target_error(msg: dict) -> str | None:
    """Fail closed on unlisted docs, malformed ids or unreadable existing manifests.

    With no database, registered local documents with usable data can still sync.
    A scene stored only in PostgreSQL is checked without restoring the model files.
    """
    doc_id = msg.get("doc_id")
    if (not isinstance(doc_id, str) or not 0 < len(doc_id) <= 200
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", doc_id) or doc_id in {".", ".."}):
        return "invalid doc_id"
    ids = msg.get("item_ids", [])
    if (not isinstance(ids, list) or len(ids) > 500
            or any(not isinstance(i, str) or not 0 < len(i) <= 120 for i in ids)):
        return "invalid item_ids"
    try:
        pool = await db.get_pool()
        if pool is not None:
            if doc_id not in await visible_doc_ids(pool):
                return "document not listed"
        elif not (docmeta_store.document_record(doc_id) and artifact_store.has_data_on_disk(doc_id)):
            return "document not listed"
        path = config.artifacts_dir() / doc_id / "scene.json"
        try:
            st = path.stat()
        except FileNotFoundError:
            raw = await pool.fetchval("select data from doc_artifacts where doc_id=$1 and name='scene.json'", doc_id) if pool else None
            known = _manifest_ids(raw) if raw is not None else None
        else:
            known = await asyncio.to_thread(_local_ids, str(path), st.st_mtime_ns, st.st_size)
        if known is not None and any(i not in known for i in ids):
            return "item_ids not in scene manifest"
    except Exception:
        return "scene target unavailable"
    return None
