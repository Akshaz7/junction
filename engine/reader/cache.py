"""Bounded document snapshots shared only within one answer (including its worker threads).

No parsed models survive a request, so uploads/re-ingestion are fresh on the next
question and mutations cannot leak between chats. Outside an answer, loads are uncached.
"""
from contextvars import ContextVar
from functools import wraps
import os
from pathlib import Path
import threading


_documents = ContextVar("answer_documents", default=None)


class DocumentCache:
    def __init__(self):
        try:
            self.limit = max(0, int(os.environ.get("DOCUMENT_CACHE_BYTES", 32 * 1024 * 1024)))
        except ValueError:
            self.limit = 32 * 1024 * 1024
        self.entries = {}
        self.bytes = 0
        self.lock = threading.RLock()

    def load(self, loader, doc_id, root, prefer):
        folder = Path(root).absolute() / doc_id
        key = (str(folder), prefer)
        with self.lock:
            if key in self.entries:
                return self.entries[key][0]
            doc = loader(doc_id, root, prefer)
            if doc is None:
                return None  # ingestion may still be producing this document
            paths = [folder / "doc.json", *folder.glob("planmap-[0-9]*.json")]
            if doc.mode == "ifc":
                paths.append(folder / "elements.json")
            try:
                size = sum(p.stat().st_size for p in paths if p.is_file())
            except OSError:
                return doc
            # Keep early documents available for the final evidence pass. A
            # one-shot multi-document sweep must not evict them repeatedly.
            if self.bytes + size > self.limit or len(self.entries) >= 8 or not self.limit:
                return doc
            self.entries[key] = (doc, size)
            self.bytes += size
            return doc


def document_scope(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = _documents.set(DocumentCache())
        try:
            return fn(*args, **kwargs)
        finally:
            _documents.reset(token)
    return wrapped


def memoized_document(loader):
    @wraps(loader)
    def wrapped(doc_id, root, prefer=None):
        cache = _documents.get()
        return loader(doc_id, root, prefer) if cache is None else cache.load(loader, doc_id, root, prefer)
    return wrapped
