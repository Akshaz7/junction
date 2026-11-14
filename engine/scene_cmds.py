"""E-20: scene commands (CONTRACT v3 5.11). Code only, cost 0, no model.

  tags(doc) -> {item_id: tag}        IFC mark when present, else kind letter + number in reading order
  parse_scene(question) -> SceneIntent | None
  scene_answer(question, doc, intent, state=None, t0=...) -> answer object with evidence.scene.commands

Verb-led only (hide, show only, isolate, highlight, bring back, reset), so "how many ..." never lands here.
`state` is the per-chat scene state ({hidden, last_hidden?}) the server may pass; it is read-only here. It is shared:
manual Edit-panel removals in the 3D viewer are stored in the same chat layer, so "put the door back" restores them too.
Edits never change source data; this module only names which items an edit touches.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from engine.router.parser import parse
from engine.solvers.data import Doc, Item
from engine.solvers.solve import _reading_order, resolve_storey

LETTER = {"window": "W", "door": "D", "room": "R", "wall": "WL", "toilet": "WC", "sink": "S", "shower": "SH", "bathtub": "B"}
MARK_KEYS = ("Mark", "mark", "Tag", "tag", "Reference")
TAG_RE = re.compile(r"\b(WL|WC|SH|[WDRSB])\s?-?(\d{1,4})\b", re.I)
MAX_LABELS = 500

_RESET = re.compile(r"\b(reset|undo (?:all|everything)|show (?:me )?(?:everything|all of it|the whole (?:model|building|thing))|"
                    r"restore (?:everything|all)|bring (?:everything|it all) back|clear (?:the )?(?:view|highlights?))\b", re.I)
_ISOLATE = re.compile(r"\b(?:show|display|keep)\s+(?:me\s+)?only\b|\bonly\s+(?:show|display|keep)\b|\bisolate\b|\bfocus on\b", re.I)
_HIDE = re.compile(r"\b(hide|remove|take away|take out|get rid of|make\b.*\binvisible|fade out|turn off|vanish|disappear|"
                   r"out of the (?:picture|view|scene|way)|delete)\b", re.I)
_MEASURE = re.compile(r"\b(area|size|length|volume|height|width|depth|thickness|how|much|many|total|sum|average|percent|ratio|compare|difference)\b", re.I)
_UNDO = re.compile(r"^\W*(?:please\s+|can you\s+|could you\s+)?(undo|undo (?:that|it|the last (?:one|change|edit|removal))|go back|revert|put (?:it|that) back|"
                   r"(?:undo|revert|reverse) (?:my|the|your|that|this) (?:last |latest |previous |manual )?(?:edit|change|removal|remove)|"
                   r"(?:undo|revert|reverse) what (?:i|you) (?:did|removed|just did|just removed))\W*$", re.I)
_CLEAR = re.compile(r"^\W*(?:please\s+)?clear\s+(?:all\s+|the\s+)?highlights?\W*$", re.I)
_CHECK_EDIT = re.compile(r"^\W*(?:is|does)\s+(?:it|this|that|the (?:building|model|scene|edit))\s+(?:(?:still|now)\s+)?(?:compliant|comply|meet (?:the )?(?:rules|code))\s*(?:now|after (?:this|that)(?: edit)?)?\W*$", re.I)
_SHOW = re.compile(r"^\W*(?:please\s+)?(?:show|display|give)\s+(?:me\s+)?(?:all\s+)?(?:of\s+)?(?:the\s+|all\s+)?", re.I)
_RESTORE = re.compile(r"\b(unhide|bring (?:back|.* back)|show .* again|restore|put .* back|turn .* back on)\b", re.I)
_HIGHLIGHT = re.compile(r"\b(highlight|light up|glow|label|mark|point out|point to|flag|tag)\b", re.I)


@dataclass
class SceneIntent:
    op: str
    kind: str | None = None
    tags: list[str] = field(default_factory=list)
    scope: str | None = None


def _mark(it: Item) -> str | None:
    for k in MARK_KEYS:
        v = it.props.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def tags(doc: Doc) -> dict[str, str]:
    """Unique per doc. Marks win; others are letter + running number in reading order
    (plan maps: page, then top-to-bottom bands, then left-to-right; IFC: storey elevation, then name, then id)."""
    elev = {s["name"]: s.get("elevation_m", 0) for s in doc.storeys}
    out: dict[str, str] = {}
    used: set[str] = set()
    for it in doc.items:
        m = _mark(it) if doc.mode == "ifc" else None
        if m and m not in used:
            out[it.item_id] = m
            used.add(m)
    by_kind: dict[str, list[Item]] = {}
    for it in doc.items:
        if it.item_id not in out and it.kind in LETTER:
            by_kind.setdefault(it.kind, []).append(it)
    for kind, its in by_kind.items():
        if doc.mode == "ifc":
            its = sorted(its, key=lambda i: (elev.get(i.storey, 0), i.name or "", i.item_id))
        else:
            its = _reading_order(its)
        n = 0
        for it in its:
            n += 1
            while f"{LETTER[kind]}{n}" in used:
                n += 1
            out[it.item_id] = f"{LETTER[kind]}{n}"
            used.add(out[it.item_id])
    return out


_WHATIF = re.compile(r"^\W*(?:what(?:'s| is| would| will)? (?:happen(?:s)? )?if|suppose|imagine|if)\s+(?:we|i|you|they|someone)?\s*(?:were to\s+|was to\s+|would\s+|will\s+)?(?=(?:remove|delete|hide|take out|get rid of|drop)\b)", re.I)


_QUESTIONY = re.compile(r"\s*(?:can we|could we|can i|could i|should we|should i|would it|would we|is it possible|prepare|produce|build|create|draft|generate|compile|give me a|provide|do we|will it|trace)\b", re.I)


def parse_scene(question: str) -> SceneIntent | None:
    q = question.strip()
    if _CLEAR.match(q):
        return SceneIntent("highlight")
    if _CHECK_EDIT.match(q):
        return SceneIntent("check")
    # "what if we remove the main entrance?" / "what happens if I delete the front door" is the edit itself, asked as a what-if
    q = _WHATIF.sub("", q, count=1) if _WHATIF.match(q) else q
    if re.match(r"\s*(how many|what|which|where|why|how (?:much|long|big|large)|count|list|is |are |does |do |can you tell)", q, re.I):
        return None
    # E-59: a question or a document request is never a scene edit ("Can we remove...?", "Prepare a schedule...", "..., which doors...?")
    if _QUESTIONY.match(q) or (q.rstrip().endswith("?") and re.search(r"\b(?:which|what|how many|how much|why)\b", q, re.I)
                               and not re.match(r"\s*(?:please\s+|can you\s+|could you\s+)?(?:show|hide|remove|reset|highlight|isolate|restore)\b", q, re.I)):
        return None
    if _UNDO.match(q):
        return SceneIntent("undo")
    if _RESET.search(q) and not _ISOLATE.search(q) and not _HIDE.search(q):
        return SceneIntent("reset")
    if _ISOLATE.search(q):
        op = "isolate"
    elif _RESTORE.search(q) and not re.search(r"\bhide\b", q, re.I):
        op = "restore"
    elif _HIDE.search(q):
        op = "hide"
    elif _HIGHLIGHT.search(q) or (_SHOW.match(q) and not _MEASURE.search(q)):
        op = "highlight"
    else:
        return None
    p = parse(q)
    if op == "highlight" and p.type in ("area", "length", "volume"):
        return None
    tg = [f"{m.group(1).upper()}{int(m.group(2))}" for m in TAG_RE.finditer(q)]
    kind = p.kind
    if not kind and not tg:
        from engine import entrance      # lazy: advisor imports this module
        if entrance.is_entrance_phrase(q):   # "remove the main entrance" names no door word but means the entrance door
            kind = "door"
    if not kind and not tg:
        return SceneIntent(op, None, [], None) if op == "restore" else None
    return SceneIntent(op, kind, tg, p.scope)


_ODD = re.compile(r"^\W*(?:please\s+|can you\s+|could you\s+|would you\s+|i(?:'d| would) like (?:to )?|i want (?:to )?|let'?s\s+|just\s+)?"
                  r"(make|get|put|turn|take|drop|kill|clear|switch|set|bring|throw|dim|ghost|fade|pull|keep|leave|zap|strip|lose|cut)\b", re.I)
SCENE_SCHEMA = {"type": "object", "properties": {
    "op": {"type": "string", "enum": ["highlight", "hide", "restore", "reset", "isolate", "undo", "none"]},
    "kind": {"type": ["string", "null"]}, "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["op"]}


def parse_scene_model(question: str) -> tuple[SceneIntent | None, float, str | None]:
    """Odd phrasing the rules missed: a small model (task `scene_intent`, Nemotron first) maps it to an op.
    Only tried for imperative-looking text that names a kind or a tag. -> (intent|None, usd, provider)"""
    q = question.strip()
    if not _ODD.match(q) or len(q) > 200:
        return None, 0.0, None
    p = parse(q)
    tg = [f"{m.group(1).upper()}{int(m.group(2))}" for m in TAG_RE.finditer(q)]
    if not p.kind and not tg:
        return None, 0.0, None
    try:
        from engine.models import call
        r = call("scene_intent", [{"role": "user", "content": (
            "A user is controlling a 3D building viewer. Map the request to one op: highlight (show/point out), hide (remove from view), "
            "restore (bring back), isolate (show only these), reset (show everything again), undo, or none if it is not a viewer command. "
            "Reply JSON {\"op\":..., \"kind\": window|door|room|wall|toilet|sink|shower|bathtub|null, \"tags\": [e.g. \"W7\"]}.\n"
            f"Request: {q}")}], schema=SCENE_SCHEMA)
        j = r.json if isinstance(r.json, dict) else {}
        op = j.get("op")
        if op in (None, "none"):
            return None, r.cost_usd, r.provider
        if op in ("reset", "undo"):
            return SceneIntent(op), r.cost_usd, r.provider
        kind = j.get("kind") if j.get("kind") in LETTER else p.kind
        return (SceneIntent(op, kind, tg or [str(t).upper() for t in j.get("tags", []) if TAG_RE.fullmatch(str(t))], p.scope)
                if kind or tg else None), r.cost_usd, r.provider
    except Exception:
        return None, 0.0, None


def _select(doc: Doc, intent: SceneIntent, question: str, tg: dict[str, str]) -> list[Item]:
    by_tag = {v.upper(): k for k, v in tg.items()}
    if intent.tags:
        ids = [by_tag[t] for t in intent.tags if t in by_tag]
        found = {i.item_id: i for i in doc.items}
        return [found[i] for i in ids]
    its = [i for i in doc.items if i.kind == intent.kind]
    if intent.kind == "door":
        from engine import entrance      # lazy: advisor imports this module
        if entrance.is_entrance_phrase(question):
            ent = entrance.entrance_doors(doc)
            s = resolve_storey(question, doc.storeys) if doc.mode == "ifc" else None
            if s:
                ent = [i for i in ent if i.storey == s]
            if ent and entrance.wants_single(question):
                ent = ent[:1]
            return ent
    if intent.kind == "stairs" and re.search(r"\b(?:main|principal|primary)\s+(?:stair\w*|staircase|stairway)\b", question, re.I) and its:
        # "the main staircase" is ONE stair: the ground-floor one with the biggest footprint (else the biggest anywhere)
        def _foot(i):
            b = getattr(i, "bbox_m", None)
            return (b[1][0] - b[0][0]) * (b[1][2] - b[0][2]) if b else 0.0
        ground = [i for i in its if (i.storey or "").lower() in ("erdgeschoss", "ground floor", "ground")] or its
        return [max(ground, key=_foot)]
    if intent.kind == "room":      # "show me the bathroom": only rooms whose drawn name matches the named kind
        from engine import analytics
        ql = question.lower()
        for a, base in list(analytics.WALIAS.items()) + [(k, k) for k in analytics.WSYN]:
            if re.search(rf"\b{re.escape(a)}\b", ql):
                rx = re.compile(analytics.WSYN.get(base, base), re.I)
                its = [i for i in its if rx.search(analytics._room_label(i))]
                break
    if doc.mode == "ifc":
        s = resolve_storey(question, doc.storeys)
        if s:
            its = [i for i in its if i.storey == s]
    return its


def _noun(kind: str | None, n: int) -> str:
    k = kind or "item"
    if k.endswith("s") and k not in ("glass",):
        return k   # stairs
    return k if n == 1 else (k + "es" if k.endswith(("s", "x", "sh")) else k + "s")


def undo_commands(doc: Doc, state: dict) -> list[dict]:
    """Invert the last persisted visibility edit. Highlighting does not consume Undo.

    The server can supply ordered `edits` (including when hidden is empty). Older
    callers supply only ordered hidden IDs: restore the last one, never all of them.
    """
    edits = state.get("edits")
    if not isinstance(edits, list):
        hidden = list(state.get("hidden") or [])
        return [{"op": "restore", "item_ids": hidden[-1:]}] if hidden else []
    hidden: set[str] = set()
    isolated: list[str] | None = None
    highlighted: list[str] = []
    labels: dict = {}
    before = None
    last = None
    for edit in edits:
        if not isinstance(edit, dict) or edit.get("doc_id", doc.doc_id) != doc.doc_id:
            continue
        op = edit.get("op")
        ids = list(dict.fromkeys(edit.get("item_ids") or []))
        previous = (set(hidden), isolated[:] if isolated is not None else None, highlighted[:], dict(labels))
        if op == "hide":
            hidden.update(ids)
            highlighted = [i for i in highlighted if i not in ids]
            labels = {k: v for k, v in labels.items() if k not in ids}
            if isolated is not None:
                isolated = [i for i in isolated if i not in ids]
        elif op == "restore":
            hidden.difference_update(ids) if ids else hidden.clear()
        elif op == "reset":
            hidden, isolated, highlighted, labels = set(), None, [], {}
        elif op == "isolate":
            isolated, highlighted, labels = ids[:], ids[:], dict(edit.get("labels") or {})
            hidden.difference_update(ids)
        elif op == "highlight":
            highlighted, labels = ids[:], dict(edit.get("labels") or {})
        else:
            continue
        if op != "highlight" and previous != (hidden, isolated, highlighted, labels):
            before, last = previous, op
    if before is None:
        return []
    old_hidden, old_isolated, old_highlighted, old_labels = before
    # Single hide/restore is the common case: keep other edits and selections intact.
    if last in ("hide", "restore") and old_isolated == isolated:
        out = []
        if hidden - old_hidden:
            out.append({"op": "restore", "item_ids": sorted(hidden - old_hidden)})
        if old_hidden - hidden:
            out.append({"op": "hide", "item_ids": sorted(old_hidden - hidden)})
        return out
    out = [{"op": "reset", "item_ids": []}]
    if old_hidden:
        out.append({"op": "hide", "item_ids": sorted(old_hidden)})
    if old_isolated is not None:
        out.append({"op": "isolate", "item_ids": old_isolated, "labels": old_labels})
    if old_highlighted != (old_isolated or []):
        out.append({"op": "highlight", "item_ids": old_highlighted, "labels": old_labels})
    return out


def scene_answer(question: str, doc: Doc, intent: SceneIntent, state: dict | None = None, t0: float | None = None) -> dict:
    t0 = t0 or time.perf_counter()
    tg = tags(doc)
    state = state or {}
    op = intent.op
    hidden_now = list(state.get("hidden") or [])
    undo_ids: list[str] = []
    if op in ("undo", "check") and (op == "check" or isinstance(state.get("edits"), list)):
        res = scene_answer(question, doc, SceneIntent("reset"), state, t0)
        commands = undo_commands(doc, state) if op == "undo" else []
        res["evidence"]["scene"]["commands"] = commands
        res["answer"]["text_md"] = ("**Undid the last scene edit.**" if commands else "There is no scene edit to undo.") if op == "undo" else "For the current scene:"
        res["trace"][0]["detail"] = f"{op} / current chat scene"
        if op == "check":
            from engine.analytics import edit_advice
            edit_advice(res, doc, list(state.get("hidden") or []))
            if res["answer"]["text_md"] == "For the current scene:":
                res["answer"]["text_md"] = "I cannot check compliance from the available model data."
        return res
    clearing = op == "highlight" and not intent.kind and not intent.tags
    if op == "undo":  # restore the latest removal still in effect (chat or manual edit); else all hidden; with no state, reset
        undo_ids = [i for i in (state.get("last_hidden") or []) if i in hidden_now]
        intent = SceneIntent("restore" if hidden_now else "reset", None, [], None)
        op = intent.op
    sel = [] if op == "reset" else _select(doc, intent, question, tg) if (intent.kind or intent.tags) else []
    if op == "restore" and sel and not intent.tags and hidden_now:
        # "put the door back": the hidden door(s), not every door. The shared state holds manual edits too.
        gone = [i for i in sel if i.item_id in set(hidden_now)]
        if len(gone) > 1 and intent.kind and not re.search(rf"\b(?:all|every|both|{re.escape(_noun(intent.kind, 2))})\b", question, re.I):
            # singular ("the door"): the latest removal of that kind
            last = set(state.get("last_hidden") or [])
            gone = [i for i in gone if i.item_id in last] or [max(gone, key=lambda i: hidden_now.index(i.item_id))]
        sel = gone or sel
    ids = [i.item_id for i in sel]
    if op == "restore" and not intent.kind and not intent.tags:
        ids = undo_ids or hidden_now
    trace = [{"step": "scene", "detail": f"{op} {len(ids)} item(s)", "ms": 0, "model": None, "cost_usd": 0}]
    scene = {"doc_id": doc.doc_id, "highlight_item_ids": ids if intent.op in ("highlight", "isolate") else [],
             "camera_target_item_id": ids[0] if ids and intent.op in ("highlight", "isolate") else None}
    cmd: dict = {"op": intent.op, "item_ids": ids}
    if 0 < len(ids) <= MAX_LABELS:
        cmd["labels"] = {i: tg[i] for i in ids if i in tg}
    scene["commands"] = [cmd]
    abstained, conf = False, 1.0
    if clearing:
        text = "**Highlights cleared.**"
    elif intent.op == "reset":
        text = "Done. **Everything is visible again**, with no highlights."
    elif not ids and intent.op == "restore" and not intent.kind and not intent.tags:
        text = "Done. **Everything hidden is visible again.**"
        cmd["item_ids"] = []
    elif intent.op == "restore" and not intent.kind and not intent.tags:
        named = [tg[i] for i in ids if i in tg]
        left = len([i for i in hidden_now if i not in set(ids)])
        text = (f"Done. **{', '.join(named)} {'is' if len(ids) == 1 else 'are'} visible again.**" if named and len(named) == len(ids) <= 6
                else f"Done. **{len(ids)} hidden item(s) are visible again.**")
        if left:
            text += f" {left} other hidden item(s) stay hidden."
    elif not ids:
        what = ", ".join(intent.tags) if intent.tags else _noun(intent.kind, 2)
        text, abstained, conf = f"I could not find any {what} in this document, so nothing changed.", True, 0.0
    else:
        n = len(ids)
        who = ", ".join(tg[i] for i in ids if i in tg) if n <= 6 and intent.tags else \
            (f"1 {'staircase' if intent.kind == 'stairs' else intent.kind or 'item'}" if n == 1 else f"{n} {_noun(intent.kind, n)}")
        verb = {"hide": "Hidden", "restore": "Restored", "isolate": "Showing only", "highlight": "Highlighted"}[intent.op]
        text = (f"{verb} {who} on the drawing." if intent.op == "highlight" and not intent.tags else f"{verb} **{who}**.")
        kinds = {i.kind for i in sel}
        if intent.op in ("hide", "restore") and len(kinds) == 1:
            k = next(iter(kinds))
            total = sum(1 for i in doc.items if i.kind == k)
            hidden = set(state.get("hidden") or [])
            hidden = hidden | set(ids) if intent.op == "hide" else hidden - set(ids)
            vis = total - sum(1 for i in doc.items if i.kind == k and i.item_id in hidden)
            one = text
            if n == 1 and (ids[0] in tg or k == "stairs"):
                # name the item the user meant ("the front door (D34)") and its storey
                m_ = re.search(r"\b(front|main|street)\s+door\b|\b(main\s+entrance|entrance(?:\s+door)?)\b", question, re.I)
                nm = f"the {re.sub(r'\\s+', ' ', m_.group(0).lower())}" if m_ else k.capitalize()
                if not m_ and k == "stairs":
                    nm = "The main staircase" if re.search(r"\bmain\b", question, re.I) else "The staircase"
                if m_ and "door" not in nm and k == "door":
                    nm += " door"
                nm = nm[0].upper() + nm[1:]
                st_ = f" on {sel[0].storey}" if sel[0].storey else ""
                tg_ = f" ({tg[ids[0]]})" if ids[0] in tg else ""
                one = f"{nm}{tg_}{st_} is hidden." if intent.op == "hide" else f"{nm}{tg_}{st_} is visible again."
            text = f"{one} {vis} of {total} {_noun(k, total)} remain visible." if intent.op == "hide" else f"{one} {vis} of {total} {_noun(k, total)} are visible."
    boxes = []
    if doc.mode == "planmap" and intent.op in ("highlight", "isolate"):
        for k, it in enumerate(_reading_order(sel)[:MAX_LABELS], 1):
            if it.bbox_px:
                boxes.append({"item_id": it.item_id, "page": it.page, "bbox_px": it.bbox_px, "label": tg.get(it.item_id, str(k))})
    cmd["op"] = op if op in ("highlight", "hide", "restore", "reset", "isolate") else intent.op
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc.doc_id],
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": conf, "abstained": abstained},
        "citations": [], "evidence": {"boxes": boxes, "scene": scene}, "trace": trace, "route": "index" if doc.mode == "ifc" else "planmap",
        "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
