"""Request-local progress retained when the answer deadline expires."""
import copy
import math
import os
import time
import uuid

from .schema import validate_answer

NOTE = "Still checking; ask again for the full answer."


def partial_deadline():
    def seconds(name, default):
        try:
            n = float(os.environ.get(name) or default)
            return n if math.isfinite(n) and n > 0 else default
        except ValueError:
            return default
    # Ash: an answer takes as long as it needs and streams as it goes. A partial cut-off only if ANSWER_PARTIAL_AFTER_S is set;
    # otherwise wait until just before the engine's own hung-call guard (ANSWER_TIMEOUT_S, default 300 s).
    guard = max(0.01, seconds("ANSWER_TIMEOUT_S", 300.0) - 1.0)
    return min(seconds("ANSWER_PARTIAL_AFTER_S", guard), guard)


class AnswerProgress:
    def __init__(self, question, doc_ids):
        self.question = question
        self.doc_ids = list(doc_ids)
        self.started = time.monotonic()
        self.snapshot = None
        self.text = ""
        self.trace = []

    def update(self, kind, payload):
        if not isinstance(payload, dict):
            return
        if kind == "answer.partial":
            try:
                validate_answer(payload)
            except Exception:
                return
            self.snapshot = copy.deepcopy(payload)
        elif kind == "answer.delta":
            text = str(payload.get("text") or "").strip()
            if text and not text.startswith(("_Reading", "_Thinking")):
                self.text = text
        elif kind == "trace" and all(k in payload for k in ("step", "detail", "ms", "model", "cost_usd")):
            self.trace.append(copy.deepcopy(payload))

    def partial(self):
        ans = copy.deepcopy(self.snapshot) if self.snapshot else {
            "answer_id": uuid.uuid4().hex, "question": self.question, "doc_ids": self.doc_ids,
            "answer": {"text_md": self.text or "No verified findings are available yet.", "value": None, "unit": None,
                       "confidence": 0.0, "abstained": True},
            "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": self.doc_ids[0] if self.doc_ids else "",
                "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": self.trace, "route": "hybrid", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": 0,
        }
        ans["answer"]["text_md"] = "**Partial answer — still checking.**\n\n" + ans["answer"]["text_md"] + "\n\n" + NOTE
        # A provisional observation must never become a verified total or a persisted scene edit.
        ans["answer"]["value"] = None
        ans["answer"]["confidence"] = min(ans["answer"]["confidence"], 0.5)
        ans["evidence"]["scene"].pop("commands", None)
        ans.pop("advisor_cards", None)
        ans["latency_ms"] = int((time.monotonic() - self.started) * 1000)
        ans["trace"].append({"step": "partial", "detail": "Answer deadline reached; retained available findings and citations",
                             "ms": ans["latency_ms"], "model": None, "cost_usd": 0})
        return ans
