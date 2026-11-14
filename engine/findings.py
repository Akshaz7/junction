"""E-15: plain-code checks over a document. Every finding cites a rule from engine/rules/*.yaml and at
least one item. Severity is "suggestion" unless the data clearly fails the rule ("fail"). No model calls."""
from __future__ import annotations

import re
from pathlib import Path

from engine import scene_cmds
from engine.exits import find_exits
from engine.rules import load_rules
from engine.solvers import ARTIFACTS
from engine.solvers.data import Doc, Item, load_doc

CORRIDOR = re.compile(r"flur|korridor|gang|corridor|hall|kaytava|käytävä", re.I)
LEVEL_TOL_M = 0.025


def _src(rule: dict) -> dict:
    return {"type": "rule", "ref": rule["id"], "title": f"{rule['source_title']}, {rule['section']}", "quote": rule["quote"],
            "url": rule.get("url"), "translation": rule.get("translation")}


def _f(rule: dict, severity: str, title: str, text: str, items: list[Item], tg: dict, storey: str | None = None, measured=None) -> dict:
    ids = [i.item_id for i in items]
    return {"finding_id": f"{rule['check_id']}:{storey or 'all'}:{severity}", "check_id": rule["check_id"], "rule_id": rule["id"],
            "severity": severity, "title": title[:80], "text": text, "item_ids": ids,
            "labels": {i: tg[i] for i in ids if i in tg}, "storey": storey, "measured": measured, "source": _src(rule)}


def _mm(m: float) -> int:
    return int(round(m * 1000))


def _by_storey(items: list[Item]) -> dict[str | None, list[Item]]:
    out: dict[str | None, list[Item]] = {}
    for i in items:
        out.setdefault(i.storey, []).append(i)
    return out


def check_door_clear_width(doc: Doc, rule: dict, tg: dict, exit_ids: set[str]) -> list[dict]:
    need = rule["params"]["min_mm"] / 1000
    out = []
    doors = [d for d in doc.items if d.kind == "door" and d.q.get("width_m") and d.item_id not in exit_ids]
    for st, ds in _by_storey(doors).items():
        fail = [d for d in ds if d.q["width_m"] < need]
        near = [d for d in ds if need <= d.q["width_m"] < need + 0.1]
        if fail:
            w = min(d.q["width_m"] for d in fail)
            out.append(_f(rule, "fail", f"{len(fail)} door{'s' if len(fail) != 1 else ''} below 850 mm on {st}",
                          f"The model gives these doors a frame width of {_mm(w)} mm or less. Clear width cannot be larger, so they miss the 850 mm minimum.", fail, tg, st, _mm(w)))
        if near:
            out.append(_f(rule, "suggestion", f"Check clear width of {len(near)} door{'s' if len(near) != 1 else ''} on {st}",
                          "The frame width is close to 850 mm. The clear width is smaller than the frame, so it could be under the minimum. Worth checking.", near, tg, st,
                          _mm(min(d.q["width_m"] for d in near))))
    return out


def check_exit_clear_width(doc: Doc, rule: dict, tg: dict, exits: dict[str, list[Item]]) -> list[dict]:
    mw, mh = rule["params"]["min_width_mm"] / 1000, rule["params"]["min_height_mm"] / 1000
    out = []
    for st, ds in exits.items():
        doors = [d for d in ds if d.kind == "door"]
        narrow = [d for d in doors if d.q.get("width_m") and d.q["width_m"] < mw]
        low = [d for d in doors if d.q.get("height_m") and d.q["height_m"] < mh]
        for bad, what, val in ((narrow, "width", "width_m"), (low, "height", "height_m")):
            if bad:
                m = min(d.q[val] for d in bad)
                out.append(_f(rule, "suggestion", f"Exit door {what} under the usual minimum on {st}",
                              f"{len(bad)} outer door{'s' if len(bad) != 1 else ''} measure {_mm(m)} mm. Exits normally need 1200 mm wide and 2100 mm high, "
                              "but the rule allows 900 mm in some cases. Please confirm.", bad, tg, st, _mm(m)))
    return out


def check_exits_per_storey(doc: Doc, rule: dict, tg: dict, exits: dict[str, list[Item]]) -> list[dict]:
    out = []
    for st, ex in exits.items():
        if len(ex) >= 2 or not ex:
            continue
        out.append(_f(rule, "suggestion", f"Only {len(ex)} exit found on {st}",
                      f"The model shows one outer door or stair on {st}. Two separate exits are usual, though small buildings can be an exception. "
                      "This is an inference from outer doors and stairs.", ex, tg, st, len(ex)))
    return out


def check_entrance_level(doc: Doc, rule: dict, tg: dict, exits: dict[str, list[Item]]) -> list[dict]:
    elev = {s["name"]: s.get("elevation_m", 0) for s in doc.storeys}
    has_ramp = any(i.kind == "ramp" or re.search(r"ramp|luiska", f"{i.name or ''} {i.type_name or ''}", re.I) for i in doc.items)
    out = []
    ground = min((s for s in doc.storeys if s.get("elevation_m", 0) >= 0), key=lambda s: s["elevation_m"], default=None)
    if not ground or has_ramp:
        return out
    bad = []
    for d in exits.get(ground["name"], []):
        if d.kind == "door" and d.bbox_m and d.bbox_m[0][1] - ground["elevation_m"] > LEVEL_TOL_M:
            bad.append(d)
    if bad:
        h = max(d.bbox_m[0][1] - ground["elevation_m"] for d in bad)
        out.append(_f(rule, "suggestion", "Entrance sits above floor level, no ramp in model",
                      f"{len(bad)} outer door{'s' if len(bad) != 1 else ''} on {ground['name']} sit {_mm(h)} mm above the floor and the model has no ramp or lift.",
                      bad, tg, ground["name"], _mm(h)))
    return out


def check_corridor_width(doc: Doc, rule: dict, tg: dict) -> list[dict]:
    below = rule["params"]["width_below_mm"] / 1000
    out = []
    rooms = [r for r in doc.items if r.kind == "room" and r.bbox_m and CORRIDOR.search(f"{r.name or ''} {r.type_name or ''} {r.props.get('room_type') or ''}")]
    for st, rs in _by_storey(rooms).items():
        narrow = []
        for r in rs:
            (x0, _, z0), (x1, _, z1) = r.bbox_m
            if min(x1 - x0, z1 - z0) < below:
                narrow.append(r)
        if narrow:
            out.append(_f(rule, "suggestion", f"Corridor under 1500 mm on {st}",
                          "A corridor narrower than 1500 mm needs a turning space of 1500 mm every 15 m. The rule applies to non-residential buildings and common areas.",
                          narrow, tg, st, None))
    return out


def run(doc_id: str, root: Path | None = None) -> list[dict]:
    doc = load_doc(doc_id, Path(root or ARTIFACTS))
    if doc is None:
        return []
    return run_doc(doc)


def exits_map(doc: Doc) -> dict[str, list[Item]]:
    """storey -> outer doors + stairs (an inference from geometry, see engine.exits)."""
    boxes = {i.item_id: i.bbox_m for i in doc.items if i.bbox_m}
    out: dict[str, list[Item]] = {}
    if boxes:
        for s in doc.storeys:
            r = find_exits(doc, s["name"], boxes)
            doors = r["named"] + [d for d in r["outer"] if d not in r["named"]]
            out[s["name"]] = doors + r["stairs"]
    return out


def run_doc(doc: Doc) -> list[dict]:
    rules = {r["check_id"]: r for r in load_rules()}
    tg = scene_cmds.tags(doc)
    exits = exits_map(doc)
    exit_ids = {i.item_id for v in exits.values() for i in v if i.kind == "door"}
    out: list[dict] = []
    if "door_clear_width" in rules:
        out += check_door_clear_width(doc, rules["door_clear_width"], tg, exit_ids)
    if exits:
        for cid, fn in (("exit_clear_width", check_exit_clear_width), ("exits_per_storey", check_exits_per_storey),
                        ("entrance_level_change_ramp", check_entrance_level)):
            if cid in rules:
                out += fn(doc, rules[cid], tg, exits)
    if "corridor_width" in rules:
        out += check_corridor_width(doc, rules["corridor_width"], tg)
    return [f for f in out if f["item_ids"] and f.get("source", {}).get("quote")]
