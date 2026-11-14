"""Stub engine (S-03). Same signature the real engine.answer will have (E-04).

answer(question, doc_ids, on_event) -> answer dict (CONTRACT 5.7).
on_event(kind, payload) is called with kind in {"status", "trace"}.
Everything it returns is fake: trace steps carry "stub": true.
"""
import re
import time
import uuid
from typing import Callable

FIXTURE_DOC = "cubicasa5k__colorful-11397"
FIXTURE_WINDOWS = 13


def _step(step, detail, ms=1):
    return {"step": step, "detail": detail, "ms": ms, "model": None, "cost_usd": 0, "stub": True}


def answer(question: str, doc_ids: list[str], on_event: Callable | None = None) -> dict:
    emit = on_event or (lambda kind, payload: None)
    t0 = time.perf_counter()
    doc_id = doc_ids[0] if doc_ids else ""
    emit("status", {"text": "Thinking…"})
    emit("status", {"text": f"Exploring document: {doc_id or 'none'}"})
    trace = [_step("route", "stub engine: no real routing")]
    emit("trace", trace[-1])

    asks_windows = re.search(r"how many\s+windows|number of windows|count.*windows", question, re.I)
    if doc_id == FIXTURE_DOC and asks_windows:
        n = FIXTURE_WINDOWS
        ids = [f"window-{i:03d}" for i in range(1, n + 1)]
        boxes = [{"item_id": iid, "page": 1,
                  "bbox_px": [40 + 60 * ((i - 1) % 5), 40 + 50 * ((i - 1) // 5), 90 + 60 * ((i - 1) % 5), 56 + 50 * ((i - 1) // 5)],
                  "label": str(i)} for i, iid in enumerate(ids, 1)]
        trace.append(_step("count", f"stub: {n} windows (fake boxes)"))
        emit("trace", trace[-1])
        ans = {"text_md": f"There are **{n} windows** on this floor plan. [1]", "value": n, "unit": "count",
               "confidence": 0.5, "abstained": False}
        citations = [{"n": 1, "doc_id": doc_id, "page": 1, "kind": "element", "bbox_px": None,
                      "item_ids": ids, "quote": None}]
        scene = {"doc_id": doc_id, "highlight_item_ids": ids, "camera_target_item_id": ids[0]}
    else:
        trace.append(_step("abstain", "stub engine only answers the fixture question"))
        emit("trace", trace[-1])
        ans = {"text_md": "The documents do not hold an answer to this question that I can verify yet.",
               "value": None, "unit": None, "confidence": 0.0, "abstained": True}
        citations, boxes = [], []
        scene = {"doc_id": doc_id, "highlight_item_ids": [], "camera_target_item_id": None}

    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": ans, "citations": citations,
        "evidence": {"boxes": boxes, "scene": scene},
        "trace": trace, "route": "planmap", "cost": {"usd_total": 0.0, "calls": []},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
