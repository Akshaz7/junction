"""S-10: scene edit layer (CONTRACT 5.11).

An edit is {op, item_ids, labels?} with op in highlight|hide|restore|reset|isolate. Edits are stored per chat
(table scene_edits) and folded in order into a state per doc:
  {"type":"scene.state","doc_id", "hidden":[...], "highlighted":[...], "labels":{...}, "isolated":[...]|null}
`isolated` is additive: after `isolate` only those items are meant to be visible (null otherwise).
"""
import json
import uuid

from .live_labels import clean_labels

OPS = ("highlight", "hide", "restore", "reset", "isolate")
MAX_IDS = 500
MAX_ID_LEN = 120


def clean_edit(msg: dict) -> dict | None:
    """Validate a client/engine edit. Returns {doc_id, op, item_ids, labels, edit_id} or None."""
    if not isinstance(msg, dict):
        return None
    op, doc_id = msg.get("op"), msg.get("doc_id")
    if op not in OPS or not isinstance(doc_id, str) or not doc_id or len(doc_id) > 200:
        return None
    raw = msg.get("item_ids", [])
    if not isinstance(raw, list):
        return None
    ids: list[str] = []
    for i in raw[:MAX_IDS]:
        if isinstance(i, str) and 0 < len(i) <= MAX_ID_LEN and i not in ids:
            ids.append(i)
    if op in ("hide", "highlight", "isolate") and not ids:
        return None
    labels = clean_labels(msg.get("labels"), ids) if op in ("highlight", "isolate") else {}
    eid = msg.get("edit_id")
    if not (isinstance(eid, str) and 0 < len(eid) <= 64):
        eid = uuid.uuid4().hex
    return {"doc_id": doc_id, "op": op, "item_ids": ids, "labels": labels, "edit_id": eid}


def empty_state(doc_id: str) -> dict:
    return {"type": "scene.state", "doc_id": doc_id, "hidden": [], "highlighted": [], "labels": {}, "isolated": None}


def apply(state: dict, op: str, ids: list[str], labels: dict) -> dict:
    hidden, hl, lab, iso = state["hidden"], state["highlighted"], state["labels"], state["isolated"]
    drop = set(ids)
    if op == "reset":
        hidden, hl, lab, iso = [], [], {}, None
    elif op == "highlight":
        hl, lab = list(ids), dict(labels)
    elif op == "hide":
        hidden = hidden + [i for i in ids if i not in hidden]
        hl = [i for i in hl if i not in drop]
        lab = {k: v for k, v in lab.items() if k not in drop}
        iso = None if iso is None else [i for i in iso if i not in drop]
    elif op == "restore":
        hidden = [] if not ids else [i for i in hidden if i not in drop]
    elif op == "isolate":
        iso, hl, lab = list(ids), list(ids), dict(labels)
        hidden = [i for i in hidden if i not in drop]
    return {**state, "hidden": hidden, "highlighted": hl, "labels": lab, "isolated": iso}


def fold(edits: list[dict]) -> dict[str, dict]:
    """edits in order (each with doc_id, op, item_ids, labels) -> state per doc_id."""
    out: dict[str, dict] = {}
    for e in edits:
        s = out.get(e["doc_id"]) or empty_state(e["doc_id"])
        out[e["doc_id"]] = apply(s, e["op"], e["item_ids"], e["labels"])
    return out


def last_hidden(edits: list[dict], doc_ids: list[str] | None = None) -> list[str]:
    """Ids of the newest hide edit (chat or manual) that is still at least partly in effect: what "undo" brings back."""
    edits = [e for e in edits if not doc_ids or e["doc_id"] in doc_ids]
    hidden = {i for s in fold(edits).values() for i in s["hidden"]}
    for e in reversed(edits):
        if e["op"] == "reset":
            return []
        if e["op"] == "hide":
            still = [i for i in e["item_ids"] if i in hidden]
            if still:
                return still
    return []


async def chat_context(pool, chat_id, doc_ids: list[str] | None = None) -> dict | None:
    """The shared edit layer as engine scene_state: {hidden, last_hidden} over the chat's docs, or None when nothing is hidden.
    Manual Edit-panel removals (sent over /ws with chat_id) and chat commands land in the same table, so both count."""
    hidden = [i for st in await scene_state(pool, chat_id) if not doc_ids or st.get("doc_id") in doc_ids for i in st.get("hidden") or []]
    if not hidden:
        return None
    return {"hidden": hidden, "last_hidden": last_hidden(await load_edits(pool, chat_id), doc_ids)}


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def load_edits(pool, chat_id, doc_id: str | None = None) -> list[dict]:
    rows = await pool.fetch(
        "select edit_id, doc_id, op, item_ids, labels from scene_edits where chat_id=$1"
        + (" and doc_id=$2" if doc_id else "") + " order by id",
        *([chat_id, doc_id] if doc_id else [chat_id]))
    return [{"edit_id": r["edit_id"], "doc_id": r["doc_id"], "op": r["op"],
             "item_ids": _j(r["item_ids"]), "labels": _j(r["labels"])} for r in rows]


async def scene_state(pool, chat_id, doc_id: str | None = None) -> list[dict]:
    states = fold(await load_edits(pool, chat_id, doc_id))
    if doc_id and doc_id not in states:
        states[doc_id] = empty_state(doc_id)
    return list(states.values())


async def store_edit(pool, chat_id, e: dict) -> bool:
    """Persist one edit. False if this edit_id was already stored (replays are idempotent)."""
    r = await pool.fetchval(
        "insert into scene_edits (edit_id, chat_id, doc_id, op, item_ids, labels) values ($1,$2,$3,$4,$5::jsonb,$6::jsonb) "
        "on conflict (edit_id) do nothing returning id",
        e["edit_id"], chat_id, e["doc_id"], e["op"], json.dumps(e["item_ids"]), json.dumps(e["labels"]))
    return r is not None
