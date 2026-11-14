"""Advisor cards (CONTRACT 5.12): POST /api/advise.

The cards come from engine.advisor.advise(doc_id, edit, chat_id) once E-16 exists (until then: no cards).
The server enforces the hard rule on whatever the engine returns: no source, no card. A card citing a
library rule must name an existing rule id and quote text that is really in that rule. Over-long
fields are dropped (quotes) or cut (title, body); at most 3 cards survive.
"""
import asyncio
import importlib
import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db
from .live import publish

router = APIRouter(prefix="/api")

KINDS = ("warning", "option", "info")
SOURCE_TYPES = ("rule", "material_table", "document")
MAX_CARDS, MAX_TITLE, MAX_BODY, MAX_QUOTE = 3, 60, 200, 200


ADVISE_OPS = ("hide", "restore", "reset", "move", "material", "undo", "resize", "narrow", "scale", "set_width")  # move/material are local what-ifs, never persisted
MAX_ITEMS, MAX_DETAIL_BYTES = 200, 4000


class Edit(BaseModel):
    op: str
    item_ids: list[str] = []
    detail: dict | None = None  # move: delta_m / position_m; material: material; undo: the inverse edit


class AdviseBody(BaseModel):
    doc_id: str
    chat_id: str | None = None
    edit: Edit | None = None


def effective_edit(hidden: list[str], edit: dict | None) -> dict | None:
    """The edit as the advisor must see it on a chat's shared edit layer (chat commands + manual edits):
    a hide checks everything hidden so far plus this edit; a restore/reset checks what is still hidden after it.
    Order-independent, so it does not matter whether the /ws scene.edit or this call lands first."""
    if not edit or not hidden or edit.get("op") not in ("hide", "restore", "reset"):
        return edit
    ids = list(edit.get("item_ids") or [])
    if edit["op"] == "hide":
        return {**edit, "item_ids": list(dict.fromkeys([*hidden, *ids]))}
    drop = set(ids)
    rest = [] if edit["op"] == "reset" or not ids else [i for i in hidden if i not in drop]
    return {"op": "hide", "item_ids": rest} if rest else edit


async def chat_hidden(pool, chat_id, doc_id: str) -> list[str]:
    from . import scene_edits
    try:
        ctx = await scene_edits.chat_context(pool, uuid.UUID(str(chat_id)), [doc_id])
    except Exception:  # noqa: BLE001  shared state is context; never fail the advice on it
        return []
    return list((ctx or {}).get("hidden") or [])


def _engine_advise():
    """engine.advisor.advise, or None while E-16 does not exist."""
    try:
        return importlib.import_module("engine.advisor").advise
    except (ImportError, AttributeError):
        return None


def _rule_texts() -> dict[str, list[str]]:
    from engine.rules import load_rules
    return {r["id"]: [r.get(k) for k in ("quote", "quote_en", "finnish_quote") if r.get(k)] for r in load_rules()}


def _cut(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def clean_cards(raw, doc_id: str) -> list[dict]:
    """Keep only well-formed cards that carry a verifiable source."""
    if not isinstance(raw, list):
        return []
    rules = None
    out: list[dict] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        src = c.get("source")
        if not isinstance(src, dict) or src.get("type") not in SOURCE_TYPES:
            continue
        ref, title, quote = (str(src.get(k) or "").strip() for k in ("ref", "title", "quote"))
        if not (ref and title and quote) or len(quote) > MAX_QUOTE:
            continue
        if src["type"] == "rule":
            try:
                rules = rules if rules is not None else _rule_texts()
            except Exception:  # noqa: BLE001  rule library unavailable: cannot verify, so no card
                continue
            ws = " ".join(quote.split())
            if ref not in rules or not any(ws in " ".join(t.split()) for t in rules[ref]):
                continue
        ctitle, body = str(c.get("title") or "").strip(), str(c.get("body") or "").strip()
        if c.get("kind") not in KINDS or not ctitle or not body:
            continue
        ids = [i for i in (c.get("item_ids") or []) if isinstance(i, str)] if isinstance(c.get("item_ids") or [], list) else []
        card = {"card_id": str(c.get("card_id") or uuid.uuid4().hex), "kind": c["kind"],
                "title": _cut(ctitle, MAX_TITLE), "body": _cut(body, MAX_BODY), "item_ids": ids,
                "source": {"type": src["type"], "ref": ref, "title": title, "quote": quote}}
        sev = c.get("severity")
        card["severity"] = sev if sev in ("violation", "suggestion", "info") else {"warning": "violation", "option": "suggestion"}.get(c["kind"], "info")
        chk = c.get("checked")
        if isinstance(chk, list):
            card["checked"] = [str(x)[:80] for x in chk[:40]]
        out.append(card)
        if len(out) >= MAX_CARDS:
            break
    return out


@router.post("/advise")
async def advise(body: AdviseBody):
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    if await pool.fetchval("select 1 from documents where doc_id=$1", body.doc_id) is None:
        raise HTTPException(404, "document not found")
    chat_id = None
    if body.chat_id is not None:
        try:
            chat_id = str(uuid.UUID(body.chat_id))
        except ValueError:
            raise HTTPException(404, "chat not found")
        if await pool.fetchval("select 1 from chats where id=$1", uuid.UUID(chat_id)) is None:
            raise HTTPException(404, "chat not found")
    edit = None
    if body.edit is not None:
        e = body.edit
        if e.op not in ADVISE_OPS or len(e.item_ids) > MAX_ITEMS or not all(i.strip() and len(i) <= 200 for i in e.item_ids):
            raise HTTPException(422, "invalid edit")
        if e.detail is not None and len(json.dumps(e.detail, default=str)) > MAX_DETAIL_BYTES:
            raise HTTPException(422, "invalid edit")
        edit = {"op": e.op, "item_ids": list(e.item_ids)}
        if e.detail is not None:
            edit["detail"] = e.detail
    if chat_id is not None and edit is not None:
        edit = effective_edit(await chat_hidden(pool, chat_id, body.doc_id), edit)
    fn = _engine_advise()
    cards: list[dict] = []
    if fn is not None:
        try:
            cards = clean_cards(await asyncio.to_thread(fn, body.doc_id, edit, chat_id), body.doc_id)
        except Exception:  # noqa: BLE001  the advisor never takes the app down; no answer means no cards
            cards = []
    await publish({"type": "advisor.cards", "doc_id": body.doc_id, "chat_id": chat_id, "cards": cards})
    return {"cards": cards}
