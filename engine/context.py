"""Thread memory: turn a follow-up into a standalone question plus a document selection, before any route runs.

  resolve(question, doc_ids, history) -> Resolved(question, doc_ids, rewritten, info)

"this one" with a document attached -> "Draft a construction claim ... for <document>"; "and doors?" -> "How many doors are there?"
on the document the last answer used; "and on level 2?" -> the last question with the level changed.

Cheap heuristic first: no history, or a question that already stands alone, is returned untouched (no model call). Otherwise one
small call("context_rewrite") (Haiku) returns {question, doc}; doc is "current" (the attached document), "last" (the document of the
previous turns) or "none". A model failure falls back to a rule: a bare deictic follow-up repeats the previous user question.
Never raises. history = [{role, content, doc_ids?}] oldest first (engine.assistant.MAX_HISTORY turns are used).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_TURNS = 10
CLIP = 700   # characters kept per history turn in the rewrite prompt

ELLIPSIS_START = re.compile(r"^\s*(and|also|what about|how about|now|then|but|same|ditto|more|why|what else|ok(ay)?[, ]|so)\b", re.I)
DEICTIC = re.compile(r"\b(this one|that one|these ones|those ones|this (doc|document|drawing|plan|sheet|model|file|one)|that (doc|document|drawing|plan|"
                     r"sheet|model|file)|it|its|them|those|these|same|again|instead|too|there|the other|the first|the second|the last|previous|"
                     r"above)\b", re.I)
STRONG = re.compile(r"\b(this one|that one|same|the other|again|instead|the (first|second|last) one)\b", re.I)
DOC_ID = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)*__[A-Za-z0-9][\w.\-]*[A-Za-z0-9_]", re.I)

SCHEMA = {"type": "object", "required": ["question", "doc"], "additionalProperties": False,
          "properties": {"question": {"type": "string"}, "doc": {"type": "string", "enum": ["current", "last", "none"]}}}

PROMPT = """You rewrite the user's latest message in a chat about construction drawings and BIM models into ONE standalone question, \
using the earlier turns. Resolve "this one", "it", "that", "same for doors", "and on level 2?" and similar follow-ups.
Rules:
- Keep the user's intent and wording as far as possible. Change only what the earlier turns make explicit. Never add facts.
- If the latest message is a bare reference to a task ("this one", "do it", "for this document"), restate the earlier task for the document.
- If the user names the document, keep its name. When a document is attached, you may name it in the question.
- Reply JSON {{"question": "<standalone question, English>", "doc": "current" | "last" | "none"}}.
  doc = "current" when the message refers to the attached document; "last" when it continues on the document used in the earlier turns \
(and none is attached now); "none" when the question is general or about the whole project.

Attached document now: {current}
Document used in the earlier turns: {last}

Earlier turns (oldest first):
{turns}

Latest message: {q}"""


@dataclass
class Resolved:
    question: str
    doc_ids: list[str]
    rewritten: bool = False
    info: dict = field(default_factory=dict)   # {source: "model"|"rule"|"none", original, model, cost_usd, latency_ms}


def _turns(history) -> list[dict]:
    out = []
    for h in (history or [])[-MAX_TURNS:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and str(h.get("content") or "").strip():
            out.append(h)
    return out


def last_docs(history) -> list[str]:
    """Documents of the most recent turn that carried any (explicit doc_ids, else a document id named in the text)."""
    for h in reversed(_turns(history)):
        ids = [d for d in (h.get("doc_ids") or []) if isinstance(d, str) and d]
        if not ids:
            ids = list(dict.fromkeys(DOC_ID.findall(str(h.get("content") or ""))))
        if ids:
            return ids[:3]
    return []


def needs_rewrite(question: str, doc_ids: list[str], history) -> bool:
    """True when the question depends on the thread. False = it already stands alone (no model call)."""
    q = (question or "").strip()
    if not q or not _turns(history):
        return False
    words = len(q.split())
    if ELLIPSIS_START.match(q) or STRONG.search(q):
        return True
    if words >= 12:
        return False
    return words <= 3 or bool(DEICTIC.search(q))


def title_of(doc_id: str, root: Path | None) -> str:
    try:
        return json.loads((Path(root) / doc_id / "doc.json").read_text()).get("title") or doc_id
    except (OSError, ValueError, TypeError):
        return doc_id


def _label(ids: list[str], root) -> str:
    return ", ".join(f"{title_of(d, root)} ({d})" for d in ids) if ids else "none"


def _rule(question: str, doc_ids: list[str], history, root) -> tuple[str, list[str]] | None:
    """Fallback when the model is unreachable: a bare deictic follow-up repeats the previous user question for the attached document."""
    q = (question or "").strip().rstrip("?.! ")
    bare = re.fullmatch(r"(?i)(do )?(this|that|it|this one|that one|the same|same|this document|this drawing|for this( one| document| drawing)?)", q)
    if not bare:
        return None
    prev = next((str(h["content"]) for h in reversed(_turns(history)) if h["role"] == "user"), "")
    if not prev or prev.strip().lower() == q.lower():
        return None
    ids = doc_ids or last_docs(history)
    if ids:
        return f"{prev.strip().rstrip('.')} Focus on the document \"{title_of(ids[0], root)}\".", ids
    return prev.strip(), ids


def resolve(question: str, doc_ids: list[str] | None, history=None, root: Path | None = None) -> Resolved:
    doc_ids = list(doc_ids or [])
    out = Resolved(question, doc_ids, False, {"source": "none", "original": question})
    try:
        if os.environ.get("CONTEXT_REWRITE", "1") == "0" or not needs_rewrite(question, doc_ids, history):
            return out
        last = last_docs(history)
        turns = "\n".join(f"{h['role']}: {str(h['content'])[:CLIP]}" for h in _turns(history))
        new_q, new_docs, info = None, doc_ids, {"source": "rule", "original": question}
        try:
            from engine import models as M
            r = M.call("context_rewrite", [{"role": "user", "content": PROMPT.format(
                current=_label(doc_ids, root), last=_label(last, root), turns=turns, q=question)}], schema=SCHEMA)
            j = r.json if isinstance(r.json, dict) else {}
            cand = str(j.get("question") or "").strip()
            if cand and not cand.startswith("fake:") and len(cand) <= 1500:
                new_q = cand
                pick = j.get("doc")
                new_docs = doc_ids or (last if pick in ("last", "current") else [])
                info = {"source": "model", "original": question, "model": r.model, "cost_usd": r.cost_usd, "latency_ms": r.latency_ms,
                        "task": "context_rewrite", "provider": r.provider}
        except Exception:  # noqa: BLE001 — every provider failed: use the rule
            pass
        if new_q is None:
            got = _rule(question, doc_ids, history, root)
            if got is None:
                return out
            new_q, new_docs = got
        # a document the user attached always wins; a remembered one is only added when nothing is attached
        out = Resolved(new_q, new_docs, new_q.strip() != (question or "").strip() or new_docs != doc_ids, info)
    except Exception:  # noqa: BLE001
        return Resolved(question, doc_ids, False, {"source": "none", "original": question})
    return out
