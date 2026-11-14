"""E-15: plain-code checks over a document. Every finding cites a rule from engine/rules/*.yaml and at
least one item. Severity is "suggestion" unless the data clearly fails the rule ("fail"). No model calls."""
from __future__ import annotations

import os
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
            "url": rule.get("url"), "finnish_url": rule.get("finnish_url") if rule.get("finnish_url") != rule.get("url") else None,
            "translation": rule.get("translation")}


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



# ---- 1007/2017 safety in use ------------------------------------------------------------------------------

EMERGENCY = re.compile(r"varatie|emergency|notausstieg|notausgang|rettung|escape", re.I)
HEADROOM_SOFT_M = 2.0     # 1007/2017 §14 lets a door opening be a little lower than 2 100 mm (frames, thresholds)


def _stair_flights(doc: Doc) -> list[Item]:
    return [i for i in doc.items if i.kind == "stairs" and i.bbox_m and i.props.get("ifc_class") == "IfcStairFlight"]


def _barriers(doc: Doc) -> list[Item]:
    """Railings that are barriers: a handrail is not one."""
    return [i for i in doc.items if i.kind == "railing" and i.bbox_m and str(i.props.get("predefined_type") or "").upper() != "HANDRAIL"]


def _stair_vals(i: Item) -> tuple[float | None, float | None]:
    r = i.q.get("riser_height_m") or i.props.get("riser_height_m")
    t = i.q.get("tread_length_m") or i.props.get("tread_length_m")
    return (float(r) if r else None, float(t) if t else None)


def _emergency_windows(doc: Doc) -> list[Item]:
    return [w for w in doc.items if w.kind == "window" and w.q.get("width_m") and w.q.get("height_m")
            and EMERGENCY.search(f"{w.name or ''} {w.type_name or ''}")]


def check_stair_width(doc: Doc, rule: dict, tg: dict) -> list[dict]:
    need = rule["params"]["min_width_m"]
    out = []
    for st, fl in _by_storey(_stair_flights(doc)).items():
        bad = []
        for i in fl:
            (x0, _, z0), (x1, _, z1) = i.bbox_m
            if min(x1 - x0, z1 - z0) < need:
                bad.append(i)
        if bad:
            w = min(min(i.bbox_m[1][0] - i.bbox_m[0][0], i.bbox_m[1][2] - i.bbox_m[0][2]) for i in bad)
            out.append(_f(rule, "fail", f"Stair under 850 mm wide on {st}",
                          f"{len(bad)} stair flight{'s' if len(bad) != 1 else ''} measure about {_mm(w)} mm across in the model, below the 850 mm minimum.", bad, tg, st, _mm(w)))
    return out


def check_stair_riser_tread(doc: Doc, rule: dict, tg: dict) -> list[dict]:
    """The model cannot say whether a stair is inside a dwelling or in an exit. The dwelling limits (190/250) are the
    looser ones, so missing them is a fail anywhere; missing only the exit limits (180/270) is a suggestion."""
    mr, mt = rule["params"]["max_riser_mm"] / 1000, rule["params"]["min_tread_mm"] / 1000
    dwelling = rule["check_id"].endswith("dwelling")
    loose = {r["check_id"]: r for r in load_rules()}.get("stair_riser_tread_dwelling", rule)["params"]
    out = []
    for i in doc.items:
        if i.kind != "stairs":
            continue
        r, t = _stair_vals(i)
        if r is None and t is None:
            continue
        bad = (r is not None and r > mr + 1e-6) or (t is not None and t < mt - 1e-6)
        if not bad:
            continue
        text = f"Riser {_mm(r) if r else '?'} mm, tread {_mm(t) if t else '?'} mm. The limit is riser {_mm(mr)} mm at most, tread {_mm(mt)} mm at least."
        if dwelling:
            out.append(_f(rule, "fail", f"Stair steps outside the limit on {i.storey}", text, [i], tg, i.storey, None))
        elif not ((r is not None and r > loose["max_riser_mm"] / 1000 + 1e-6) or (t is not None and t < loose["min_tread_mm"] / 1000 - 1e-6)):
            out.append(_f(rule, "suggestion", f"Stair may miss the exit limit on {i.storey}", text + " This applies if the stair is part of an exit.", [i], tg, i.storey, None))
    return out


def check_barrier_height(doc: Doc, rule: dict, tg: dict) -> list[dict]:
    need = rule["params"]["min_height_m"]
    out = []
    for st, bs in _by_storey(_barriers(doc)).items():
        low = [b for b in bs if (b.bbox_m[1][1] - b.bbox_m[0][1]) < need - 1e-6]
        if low:
            h = min(b.bbox_m[1][1] - b.bbox_m[0][1] for b in low)
            out.append(_f(rule, "suggestion", f"Barrier under 1.0 m on {st}",
                          f"{len(low)} barrier{'s' if len(low) != 1 else ''} stand {_mm(h)} mm high. One metre is needed where the drop is large; the model has no drop height, so please confirm.",
                          low, tg, st, _mm(h)))
    return out


def check_headroom(doc: Doc, rule: dict, tg: dict) -> list[dict]:
    out = []
    doors = [d for d in doc.items if d.kind == "door" and d.q.get("height_m")]
    for st, ds in _by_storey(doors).items():
        low = [d for d in ds if d.q["height_m"] < HEADROOM_SOFT_M - 1e-6]
        if low:
            h = min(d.q["height_m"] for d in low)
            out.append(_f(rule, "suggestion", f"Door opening under 2.0 m on {st}",
                          f"{len(low)} door{'s' if len(low) != 1 else ''} are {_mm(h)} mm high. A passageway needs 2 100 mm; the rule lets a door opening be a little lower, but not this low.",
                          low, tg, st, _mm(h)))
    return out


def check_emergency_window(doc: Doc, rule: dict, tg: dict) -> list[dict]:
    p = rule["params"]
    bad = [w for w in _emergency_windows(doc)
           if w.q["height_m"] * 1000 < p["min_height_mm"] or w.q["width_m"] * 1000 < p["min_width_mm"]
           or (w.q["height_m"] + w.q["width_m"]) * 1000 < p["min_sum_mm"]]
    return [_f(rule, "suggestion", f"Emergency-exit window too small on {st}",
               "The frame is smaller than 600 mm by 500 mm or the two sizes add up to under 1 500 mm, so the free opening is too.", ws, tg, st, None)
            for st, ws in _by_storey(bad).items()]


def coverage(doc: Doc) -> dict:
    """Which rules the data lets us check on this doc, and which not (with the reason). Said on every advisor result."""
    rules = {r["check_id"]: r for r in load_rules()}
    ifc = doc.mode == "ifc"
    ex = exits_map(doc) if ifc else {}
    has = {
        "door_clear_width": any(d.kind == "door" and d.q.get("width_m") for d in doc.items),
        "exit_clear_width": bool(ex),
        "exits_per_storey": bool(ex),
        "entrance_level_change_ramp": bool(ex),
        "corridor_width": any(r.kind == "room" and r.bbox_m for r in doc.items),
        "stair_width": bool(_stair_flights(doc)),
        "stair_riser_tread_dwelling": any(i.kind == "stairs" and any(_stair_vals(i)) for i in doc.items),
        "stair_riser_tread_exit": any(i.kind == "stairs" and any(_stair_vals(i)) for i in doc.items),
        "barrier_height": bool(_barriers(doc)),
        "headroom": any(d.kind == "door" and d.q.get("height_m") for d in doc.items),
        "emergency_window": bool(_emergency_windows(doc)),
        "door_landing": False,
    }
    why = {"door_landing": "the model has no landing geometry", "stair_width": "no stair flight with a footprint in the model",
           "stair_riser_tread_dwelling": "the stairs carry no riser or tread values", "stair_riser_tread_exit": "the stairs carry no riser or tread values",
           "barrier_height": "no barrier (guard rail) in the model", "emergency_window": "no window marked as an emergency exit",
           "headroom": "no door heights in the model", "door_clear_width": "no door widths in the model"}
    stairs = [i for i in doc.items if i.kind == "stairs"]
    if stairs and not _stair_flights(doc):
        why["stair_width"] = f"{len(stairs)} stair{'s' if len(stairs) != 1 else ''} in the model, each one a single IfcStair volume, so the width of a flight cannot be measured"
    if stairs:
        why["stair_riser_tread_dwelling"] = why["stair_riser_tread_exit"] = f"{len(stairs)} stair{'s' if len(stairs) != 1 else ''} in the model, but none carries riser or tread values"
    rails = [i for i in doc.items if i.kind == "railing"]
    if rails and not _barriers(doc):
        why["barrier_height"] = f"{len(rails)} railing{'s' if len(rails) != 1 else ''} in the model, all handrails (a handrail is not a barrier)"
    checked, skipped = [], []
    for cid, r in rules.items():
        if has.get(cid):
            checked.append(r["id"])
        else:
            reason = why.get(cid) if cid in has else "no automatic check for this rule yet"
            skipped.append({"rule_id": r["id"], "reason": reason or ("needs an IFC model" if not ifc else "the model lacks the data")})
    return {"checked": checked, "not_checked": skipped}


def run(doc_id: str, root: Path | None = None) -> list[dict]:
    doc = load_doc(doc_id, Path(root or os.environ.get("ARTIFACTS_DIR") or ARTIFACTS))
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
    for cid, fn in (("stair_width", check_stair_width), ("stair_riser_tread_dwelling", check_stair_riser_tread),
                    ("stair_riser_tread_exit", check_stair_riser_tread), ("barrier_height", check_barrier_height),
                    ("headroom", check_headroom), ("emergency_window", check_emergency_window)):
        if cid in rules:
            out += fn(doc, rules[cid], tg)
    return [f for f in out if f["item_ids"] and f.get("source", {}).get("quote")]
