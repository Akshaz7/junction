"""E-16: advisor. After an edit, rerun the checks on an edited copy of the document and return up to 3
cards (CONTRACT 5.12). Every card carries a source from engine/rules (a verified rule) or a material
table; no source, no card. Nothing here is invented: no rule means no card. No model calls.

edit = {"op": "hide"|"resize"|"narrow"|..., "item_ids": [...], "detail": {"width_m"|"width_mm"|"scale": ...}}
"""
from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

from engine import entrance, findings, scene_cmds
from engine.rules import load_rules
from engine.solvers import ARTIFACTS
from engine.solvers.data import Doc, load_doc

MAX_CARDS, MAX_TITLE, MAX_BODY, MAX_QUOTE = 3, 60, 200, 200
SIZE_OPS = ("resize", "narrow", "scale", "set_width", "edit")


def _cut(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    t = s[:n].rsplit(" ", 1)[0]
    return t.rstrip(",;:. ")


def _quote(q: str) -> str:
    return q if len(q) <= MAX_QUOTE else _cut(q, MAX_QUOTE)    # a prefix stays verbatim


def _source(src: dict) -> dict | None:
    if not src or not src.get("ref") or not src.get("quote"):
        return None
    return {"type": src.get("type", "rule"), "ref": src["ref"], "title": src.get("title") or src["ref"], "quote": _quote(src["quote"])}


def _card(kind: str, title: str, body: str, ids: list[str], src: dict, key: str) -> dict | None:
    source = _source(src)
    if source is None or not ids:
        return None
    return {"card_id": f"adv:{key}", "kind": kind, "title": _cut(title, MAX_TITLE), "body": _cut(body, MAX_BODY),
            "item_ids": ids[:50], "source": source}


def _new_width(item, detail: dict) -> float | None:
    if not isinstance(detail, dict):
        return None
    try:
        if detail.get("width_m") is not None:
            return float(detail["width_m"])
        if detail.get("width_mm") is not None:
            return float(detail["width_mm"]) / 1000
        if detail.get("scale") is not None and item.q.get("width_m"):
            return float(item.q["width_m"]) * float(detail["scale"])
    except (TypeError, ValueError):
        return None
    return None


def _apply(doc: Doc, edit: dict) -> tuple[Doc, list]:
    """Edited copy of the doc and the touched items (read-only elsewhere)."""
    ids = set(edit.get("item_ids") or [])
    op = edit.get("op")
    touched = [i for i in doc.items if i.item_id in ids]
    if op == "hide":
        return dataclasses.replace(doc, items=[i for i in doc.items if i.item_id not in ids]), touched
    if op in SIZE_OPS:
        items = []
        for i in doc.items:
            if i.item_id in ids and i.kind in ("door", "window"):
                w = _new_width(i, edit.get("detail") or {})
                if w is not None and w > 0:
                    i = dataclasses.replace(i, q={**i.q, "width_m": w})
            items.append(i)
        return dataclasses.replace(doc, items=items), touched
    return doc, touched


def _from_finding(f: dict, ids: list[str]) -> dict | None:
    kind = "warning" if f["severity"] == "fail" else "option"
    return _card(kind, f["title"], f["text"], ids or f["item_ids"], f["source"], f"{f['finding_id']}:{','.join(sorted(ids))[:40]}")


def _room_doors(doc: Doc) -> dict[str, list[str]]:
    """room item_id -> ids of the doors that touch the room (door box grown by 0.3 m, plan x/z)."""
    m = 0.3
    out: dict[str, list[str]] = {}
    doors = [d for d in doc.items if d.kind == "door" and d.bbox_m]
    for r in doc.items:
        if r.kind != "room" or not r.bbox_m:
            continue
        (rx0, _, rz0), (rx1, _, rz1) = r.bbox_m
        for d in doors:
            if d.storey != r.storey:
                continue
            (x0, _, z0), (x1, _, z1) = d.bbox_m
            if x0 - m <= rx1 and x1 + m >= rx0 and z0 - m <= rz1 and z1 + m >= rz0:
                out.setdefault(r.item_id, []).append(d.item_id)
    return out


def _route_cards(doc: Doc, after_doc: Doc, edit: dict, touched: list, touched_ids: set[str]) -> list[dict]:
    """Removing or narrowing a door on an escape route: cites fi-fire-route-length (the route to an exit
    must stay passable) or, for an exit door, fi-fire-exits-per-storey. Rule library only, never invented."""
    rules = {r["id"]: r for r in load_rules()}
    tg = scene_cmds.tags(doc)
    hide = edit.get("op") == "hide"
    doors = [i for i in touched if i.kind == "door"]
    if not doors:
        return []
    out: list[dict] = []
    ex_ids = {i.item_id for v in findings.exits_map(doc).values() for i in v}
    after_map = findings.exits_map(after_doc) if hide else findings.exits_map(doc)
    after_ex = {i.item_id for v in after_map.values() for i in v}
    r_exit, r_route = rules.get("fi-fire-exits-per-storey"), rules.get("fi-fire-route-length")
    name = lambda i: tg.get(i.item_id, i.name or i.item_id)  # noqa: E731
    if r_exit:
        for d in doors:
            if d.item_id in ex_ids and (hide or (_new_width(d, edit.get("detail") or {}) or 9) < 0.9):
                left = len([i for i in after_map.get(d.storey, []) if i.item_id != d.item_id]) if hide else None
                body = (f"{name(d)} is an outer door of {d.storey}. " + (f"Hiding it leaves {left} other exit{'s' if left != 1 else ''} counted there. " if hide else "Narrowing it may cut the usable exit. ")
                        + "Each evacuation area needs the number of separate exits in Table 11.")
                c = _card("option", f"Exit door {name(d)} changed on {d.storey}", body, [d.item_id], findings._src(r_exit), f"exitdoor:{d.item_id}")
                out.append(c)
    if r_route and hide:
        rd = _room_doors(doc)
        for r in doc.items:
            ds = rd.get(r.item_id, [])
            if r.kind == "room" and len(ds) == 1 and ds[0] in touched_ids:
                d = next(i for i in doors if i.item_id == ds[0])
                out.append(_card("warning", f"{name(r)} loses its only door",
                                 f"{name(d)} appears to be the only door of {name(r)}. Without it no passable route leads from the room to an exit.",
                                 [d.item_id, r.item_id], findings._src(r_route), f"onlydoor:{r.item_id}"))
    return [c for c in out if c]


def advise(doc_id: str, edit: dict | None = None, chat_id: str | None = None, root: Path | None = None) -> list[dict]:
    doc = load_doc(doc_id, Path(root or os.environ.get("ARTIFACTS_DIR") or ARTIFACTS))
    if doc is None:
        return []
    return advise_doc(doc, edit)


def _short(rule: dict) -> str:
    m = re.search(r"\b(\d{2,4}/\d{4})\b", rule["source_title"])
    return f"{m.group(1) if m else rule['id']} §{str(rule['section']).replace(' §', '')}"


def card_rule_ref(card: dict) -> str:
    """'848/2017 §33' from a card's source title ('... 848/2017, 33 §'); never the garbled '33 §'."""
    t = (card.get("source") or {}).get("title") or ""
    d = re.search(r"\b(\d{2,4}/\d{4})\b", t)
    sec = re.search(r"(\d+)\s*§", t)
    if d and sec:
        return f"{d.group(1)} §{sec.group(1)}"
    return d.group(1) if d else ""


TOPIC = {"848/2017": "Fire safety", "241/2017": "Accessibility", "1007/2017": "Safety in use", "1008/2017": "Residential premises"}


def _plain(rule: dict) -> str:
    """'Fire safety 848/2017 §34 (exit width)': the rule in words a client can read."""
    ref = _short(rule)
    topic = TOPIC.get(ref.split(" ")[0], "")
    what = str(rule.get("check_id") or "").replace("_", " ").replace("clear ", "").strip()
    return " ".join(x for x in (topic, ref) if x) + (f" ({what})" if what else "")


def _checked_text(ids: list[str]) -> str:
    by = {r["id"]: r for r in load_rules()}
    seen: list[str] = []
    for i in ids:
        if i in by and _plain(by[i]) not in seen:
            seen.append(_plain(by[i]))
    return ", ".join(seen) if seen else "no rule"


def _severity(c: dict) -> str:
    return c.get("severity") or {"warning": "violation", "option": "suggestion"}.get(c["kind"], "info")


def _finish(cards: list[dict], checked: list[str]) -> list[dict]:
    for c in cards:
        c["severity"] = _severity(c)
        c["checked"] = list(checked)
    return cards


def _info(title: str, body: str, ids: list[str], rule_id: str, key: str) -> dict | None:
    rule = {r["id"]: r for r in load_rules()}.get(rule_id)
    return _card("info", title, body, ids, findings._src(rule), key) if rule else None


def _planmap_cards(doc: Doc, edit: dict, touched: list) -> list[dict]:
    """Raster / DXF plan maps have no measured exits. Detect entrance doors from the drawing; say plainly what was not checked."""
    ids = [i.item_id for i in touched]
    before = entrance.planmap_entrances(doc)
    gone = [d for d in touched if d.kind == "door" and any(d.item_id == e.item_id for e in before)]
    after_doc, _ = _apply(doc, edit)
    left = entrance.planmap_entrances(after_doc) if edit.get("op") == "hide" else before
    checked = ["fi-fire-exits-per-storey"] if before else []
    if edit.get("op") == "hide" and gone and not left:
        c = _card("warning", "No entrance door left on the drawing",
                  "Violation of 848/2017 §33: the entrance door detected on the drawing is gone, so no exit is left. Detected from the drawing, not measured; check against an IFC model.",
                  [d.item_id for d in gone], findings._src({r["id"]: r for r in load_rules()}["fi-fire-exits-per-storey"]), f"entrance:{gone[0].item_id}")
        if c:
            c["severity"] = "violation"
            return _finish([c], checked)
    if before and gone:
        c = _info(f"Entrance door removed, {len(left)} left", f"{len(gone)} detected entrance door{'s' if len(gone) != 1 else ''} removed, {len(left)} left. "
                  "Checked against: Fire safety 848/2017 §33 (entrance doors only). Widths, heights and stairs need an IFC model.", ids, "fi-fire-exits-per-storey", f"entrance:{ids[0]}")
    else:
        why = "No entrance door could be detected on this drawing." if not before else f"{len(before)} entrance door{'s' if len(before) != 1 else ''} detected and untouched."
        c = _info("Checks need an IFC model", f"{why} Door widths, exit counts and stairs are not measured on a drawing, so no rule was checked for this edit. "
                  "Upload the IFC model for the full check.", ids, "fi-fire-exits-per-storey", f"needifc:{ids[0]}")
        checked = []
    return _finish([c] if c else [], checked)


def advise_doc(doc: Doc, edit: dict | None = None) -> list[dict]:
    base = findings.run_doc(doc)
    cov = findings.coverage(doc)["checked"]
    if not edit:
        order = {"fail": 0, "suggestion": 1}
        cards = [_from_finding(f, []) for f in sorted(base, key=lambda f: order.get(f["severity"], 9))]
        return _finish([c for c in cards if c][:MAX_CARDS], cov)
    after_doc, touched = _apply(doc, edit)
    if not touched:
        return []
    touched_ids = {i.item_id for i in touched}
    editing = edit.get("op") in ("hide", *SIZE_OPS)
    if editing and doc.mode != "ifc":
        return _planmap_cards(doc, edit, touched)
    seen = {f["finding_id"] for f in base}
    cards: list[dict] = []
    # findings the edit caused: new, or a changed item set that includes an edited item
    old_items = {f["finding_id"]: set(f["item_ids"]) for f in base}
    for f in findings.run_doc(after_doc):
        hit = [i for i in f["item_ids"] if i in touched_ids]
        if f["finding_id"] in seen and not (set(f["item_ids"]) - old_items[f["finding_id"]]):
            continue
        if hit or f["finding_id"] not in seen:
            cards.append(_from_finding(f, hit))
    # an edit that removes an exit
    if edit.get("op") == "hide":
        rule = {r["check_id"]: r for r in load_rules()}.get("exits_per_storey")
        before, after = findings.exits_map(doc), findings.exits_map(after_doc)
        for st, ex in before.items():
            gone = [i for i in ex if i.item_id in touched_ids]
            if rule and gone and len(after.get(st, [])) < 2 <= len(ex):
                n = len(after.get(st, []))
                tg = scene_cmds.tags(doc)
                c = _card("warning", f"Fewer than two exits left on {st}",
                          f"Violation of 848/2017 §33: hiding {', '.join(tg.get(i.item_id, i.name or i.item_id) for i in gone[:3])} leaves {n} exit{'s' if n != 1 else ''} on {st}. "
                          "Two separate exits are required; small buildings can be an exception.",
                          [i.item_id for i in gone], findings._src(rule), f"exits:{st}:{n}")
                if c:
                    c["severity"] = "violation"
                    cards.append(c)
    if editing:
        cards += _route_cards(doc, after_doc, edit, touched, touched_ids)
    out, keys = [], set()
    for c in cards:
        if c and c["card_id"] not in keys:
            keys.add(c["card_id"])
            out.append(c)
    out.sort(key=lambda c: (_severity(c) != "violation", c["kind"] != "warning"))
    checked = findings.coverage(after_doc)["checked"]
    if not out and editing:
        c = _info("No rule broken by this edit", f"Checked against: {_checked_text(checked)}. Nothing in the edited model fails them. "
                  "Rules without data in the model were not checked.", [i.item_id for i in touched], "fi-fire-exits-per-storey", f"clear:{sorted(touched_ids)[0]}")
        out = [c] if c else []
    return _finish(out[:MAX_CARDS], checked)
