"""S-10: scene edit layer (CONTRACT 5.11).

An edit is {op, item_ids, labels?} with op in highlight|hide|restore|reset|isolate. Edits are stored per chat
(table scene_edits) and folded in order into a state per doc:
  {"type":"scene.state","doc_id", "hidden":[...], "highlighted":[...], "labels":{...}, "isolated":[...]|null}
`isolated` is additive: after `isolate` only those items are meant to be visible (null otherwise).
Shared layer (chat + 3D Edit panel): two more ops, `move` {offset_m:[dx,dz]} (metres from the original spot, world
X/Z; [0,0] = back in place) and `material` {material: name|null}. They fold into optional state fields
`moved` {item_id:[dx,dz]} and `materials` {item_id:name}, sent only when non-empty. `reset` clears them too.
"""
import json
import math
import uuid

from .live_labels import clean_labels

OPS = ("highlight", "hide", "restore", "reset", "isolate", "move", "material")
MAX_IDS = 500
MAX_ID_LEN = 120
MAX_OFFSET_M = 1000.0


def clean_edit(msg: dict) -> dict | None:
    """Validate a client/engine edit. Returns {doc_id, op, item_ids, labels, edit_id, detail} or None."""
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
    if op in ("hide", "isolate", "move", "material") and not ids:
        return None
    detail: dict = {}
    if op == "move":
        off = msg.get("offset_m")
        if (not isinstance(off, list) or len(off) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                           and abs(v) <= MAX_OFFSET_M for v in off)):
            return None
        detail = {"offset_m": [round(float(v), 3) for v in off]}
    elif op == "material":
        m = msg.get("material")
        if m is not None and not (isinstance(m, str) and 0 < len(m.strip()) <= 40):
            return None
        detail = {"material": m.strip() if m else None}
    labels = clean_labels(msg.get("labels"), ids) if op in ("highlight", "isolate") else {}
    eid = msg.get("edit_id")
    if not (isinstance(eid, str) and 0 < len(eid) <= 64):
        eid = uuid.uuid4().hex
    return {"doc_id": doc_id, "op": op, "item_ids": ids, "labels": labels, "edit_id": eid, "detail": detail}


def empty_state(doc_id: str) -> dict:
    return {"type": "scene.state", "doc_id": doc_id, "hidden": [], "highlighted": [], "labels": {}, "isolated": None,
            "moved": {}, "materials": {}}


def apply(state: dict, op: str, ids: list[str], labels: dict, detail: dict | None = None) -> dict:
    hidden, hl, lab, iso = state["hidden"], state["highlighted"], state["labels"], state["isolated"]
    moved, mats = dict(state.get("moved") or {}), dict(state.get("materials") or {})
    drop = set(ids)
    detail = detail or {}
    if op == "reset":
        hidden, hl, lab, iso, moved, mats = [], [], {}, None, {}, {}
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
    elif op == "move":
        off = detail.get("offset_m") or [0, 0]
        for i in ids:
            if abs(off[0]) + abs(off[1]) > 1e-6:
                moved[i] = list(off)
            else:
                moved.pop(i, None)
    elif op == "material":
        for i in ids:
            if detail.get("material"):
                mats[i] = detail["material"]
            else:
                mats.pop(i, None)
    return {**state, "hidden": hidden, "highlighted": hl, "labels": lab, "isolated": iso, "moved": moved, "materials": mats}


def fold(edits: list[dict]) -> dict[str, dict]:
    """edits in order (each with doc_id, op, item_ids, labels, detail?) -> state per doc_id."""
    out: dict[str, dict] = {}
    for e in edits:
        s = out.get(e["doc_id"]) or empty_state(e["doc_id"])
        out[e["doc_id"]] = apply(s, e["op"], e["item_ids"], e["labels"], e.get("detail"))
    return out


def public_state(state: dict) -> dict:
    """scene.state on the wire: `moved` / `materials` only when non-empty (CONTRACT 5.11 optional fields)."""
    return {k: v for k, v in state.items() if k not in ("moved", "materials") or v}


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


def last_edit(edits: list[dict], doc_ids: list[str] | None = None) -> dict | None:
    """Newest hide / move / material edit still in effect: {"op", "item_ids"}. What "undo" or "put it back" reverts
    (a move or material goes back to the original, not to an intermediate step)."""
    edits = [e for e in edits if not doc_ids or e["doc_id"] in doc_ids]
    st = list(fold(edits).values())
    live = {"hide": {i for s in st for i in s["hidden"]},
            "move": {i for s in st for i in s.get("moved") or {}},
            "material": {i for s in st for i in s.get("materials") or {}}}
    for e in reversed(edits):
        if e["op"] == "reset":
            return None
        still = [i for i in e["item_ids"] if i in live.get(e["op"], ())]
        if still:
            return {"op": e["op"], "item_ids": still}
    return None


async def chat_context(pool, chat_id, doc_ids: list[str] | None = None) -> dict | None:
    """The shared edit layer as engine scene_state over the chat's docs:
    {hidden, last_hidden, moved?, materials?, last_edit?}, or None when nothing is hidden, moved or recoloured.
    Manual Edit-panel edits (sent over /ws with chat_id) and chat commands land in the same table, so both count."""
    states = [st for st in await scene_state(pool, chat_id) if not doc_ids or st.get("doc_id") in doc_ids]
    hidden = [i for st in states for i in st.get("hidden") or []]
    moved = {i: v for st in states for i, v in (st.get("moved") or {}).items()}
    mats = {i: v for st in states for i, v in (st.get("materials") or {}).items()}
    if not (hidden or moved or mats):
        return None
    edits = await load_edits(pool, chat_id)
    out: dict = {"hidden": hidden, "last_hidden": last_hidden(edits, doc_ids)}
    if moved:
        out["moved"] = moved
    if mats:
        out["materials"] = mats
    last = last_edit(edits, doc_ids)
    if last:
        out["last_edit"] = last
    return out


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def load_edits(pool, chat_id, doc_id: str | None = None) -> list[dict]:
    rows = await pool.fetch(
        "select edit_id, doc_id, op, item_ids, labels, detail from scene_edits where chat_id=$1"
        + (" and doc_id=$2" if doc_id else "") + " order by id",
        *([chat_id, doc_id] if doc_id else [chat_id]))
    return [{"edit_id": r["edit_id"], "doc_id": r["doc_id"], "op": r["op"],
             "item_ids": _j(r["item_ids"]), "labels": _j(r["labels"]), "detail": _j(r["detail"]) or {}} for r in rows]


async def scene_state(pool, chat_id, doc_id: str | None = None) -> list[dict]:
    states = fold(await load_edits(pool, chat_id, doc_id))
    if doc_id and doc_id not in states:
        states[doc_id] = empty_state(doc_id)
    return list(states.values())


async def store_edit(pool, chat_id, e: dict) -> bool:
    """Persist one edit. False if this edit_id was already stored (replays are idempotent)."""
    r = await pool.fetchval(
        "insert into scene_edits (edit_id, chat_id, doc_id, op, item_ids, labels, detail) "
        "values ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb) on conflict (edit_id) do nothing returning id",
        e["edit_id"], chat_id, e["doc_id"], e["op"], json.dumps(e["item_ids"]), json.dumps(e["labels"]),
        json.dumps(e.get("detail") or {}))
    return r is not None
