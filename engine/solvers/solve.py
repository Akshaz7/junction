"""E-03 solvers: count / area / length / volume as plain code over elements.json
(IFC) or planmap-<n>.json. No model call; cost is 0. Builds the answer object (5.7).

solve(question, doc_id, parsed=None, root=ARTIFACTS, page=None) -> answer dict, or
raises SolverUnsupported when the question is not a count/area/length/volume one.
When data is missing or the scale is unknown the answer abstains in plain words.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from engine.router.parser import Parsed, parse

from .data import Doc, Item, load_doc

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
MIN_CONF = 0.5          # plan-map items below this are ignored
MAX_BOXES = 300
NUMERIC = ("count", "area", "length", "volume")
UNSUPPORTED_KINDS = {"apartment", "mep", "dimension", "text"}
NOUN = {"door": "door", "window": "window", "wall": "wall", "room": "room", "toilet": "toilet", "sink": "sink",
        "shower": "shower", "bathtub": "bathtub", "stairs": "staircase", "column": "column", "beam": "beam",
        "slab": "slab", "roof": "roof", "railing": "railing", "ceiling": "ceiling", "covering": "covering",
        "pipe": "pipe", "furniture": "furniture item", "storey": "storey"}
UNIT = {"area": "m²", "length": "m", "volume": "m³"}


# Plan-map room subtypes: the question's room noun -> model room_type values (props.room_type). Parentheses are ignored.
ROOM_SUBTYPES = [
    ("bedroom", r"\bbed ?rooms?\b", {"bedroom"}),
    ("kitchen", r"\bkitchen(?:ette)?s?\b", {"kitchen"}),
    ("WC room", r"\b(?:separate )?wc rooms?\b|\btoilet rooms?\b", {"wc"}),
    ("bathroom", r"\bbath ?rooms?\b|\bwash ?rooms?\b", {"bathroom"}),
    ("living room", r"\bliving rooms?\b", {"living"}),
    ("balcony", r"\bbalcon(?:y|ies)\b|\bterraces?\b", {"balcony", "terrace"}),
    ("garage", r"\bgarages?\b", {"garage"}),
    ("sauna", r"\bsaunas?\b", {"sauna"}),
]


def room_subtype(question: str):
    q = re.sub(r"\([^)]*\)", " ", question)
    q = re.sub(r",?\s*\b(?:not counting|excluding|without|except|other than|apart from)\b.*$", " ", q, flags=re.I)
    for name, rx, types in ROOM_SUBTYPES:
        if re.search(rx, q, re.I):
            return name, types
    return None


class SolverUnsupported(Exception):
    pass


def _plural(kind: str, n: int) -> str:
    w = NOUN.get(kind, kind)
    if n == 1:
        return w
    if w.endswith("y") and not w.endswith("ey"):
        return w[:-1] + "ies"
    if w.endswith(("s", "ch", "sh")):
        return w + "es"
    return w + "s"


# ------------------------------------------------------------- scope filters
_ORD = {"ground": 0, "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5}


def resolve_storey(q: str, storeys: list[dict]) -> str | None:
    ql = q.lower()
    names = [s["name"] for s in storeys]
    for n in sorted(names, key=len, reverse=True):
        if n.lower() in ql:
            return n
    if not storeys:
        return None
    srt = sorted(storeys, key=lambda s: s["elevation_m"])
    ground = next((i for i, s in enumerate(srt) if s["elevation_m"] >= -0.01), 0)
    m = re.search(r"\b(ground|first|1st|second|2nd|third|3rd|fourth|4th|fifth)\s+(?:floor|level|storey)", ql)
    if m:
        i = ground + _ORD[m.group(1)]
        return srt[i]["name"] if 0 <= i < len(srt) else None
    if re.search(r"\b(basement|underground|cellar)\b", ql):
        return srt[0]["name"] if srt[0]["elevation_m"] < 0 else None
    if re.search(r"\b(top|upper most|roof) (?:floor|level|storey)", ql):
        return srt[-1]["name"]
    return None


def _quoted(q: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?<![\w])'(.+?)'(?!\w)|\"([^\"]+)\"", q) for m in [re.match(r"(.*)", m.group(1) or m.group(2))]]


def _label_matches(it: Item, text: str) -> bool:
    def norm(x):
        return x.casefold().replace("\u2019", "'").replace("\u2018", "'").strip()
    t = norm(re.sub(r"\s*\([^)]*\)\s*$", "", text))
    cands = [it.label, it.name, it.type_name, it.props.get("room_type")]
    return any(c and norm(c) == t for c in cands)


def _room_id(q: str) -> str | None:
    m = re.search(r"\broom\s+([A-Za-z]?\d[\w.\-]*)", q)
    return m.group(1) if m else None


# ------------------------------------------------------------- answer pieces
def _step(step, detail, ms=0):
    return {"step": step, "detail": detail, "ms": ms, "model": None, "cost_usd": 0}


def _fmt(v: float, kind: str) -> str:
    if kind == "count":
        return str(int(v))
    return f"{v:,.1f}" if abs(v) >= 10 else f"{v:,.2f}"


def _reading_order(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (i.page, (i.bbox_px or [0, 0])[1] // 40, (i.bbox_px or [0, 0])[0], i.item_id))


def _evidence(doc: Doc, items: list[Item]):
    items = _reading_order(items)
    boxes, cites = [], []
    if doc.mode == "planmap":
        by_page: dict[int, list[Item]] = {}
        for i in items:
            by_page.setdefault(i.page, []).append(i)
        n = 0
        for pg, its in sorted(by_page.items()):
            n += 1
            xs = [i.bbox_px for i in its if i.bbox_px]
            union = [min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs)] if xs else None
            cites.append({"n": n, "doc_id": doc.doc_id, "page": pg, "kind": "region", "bbox_px": union,
                          "item_ids": [i.item_id for i in its], "quote": None})
        for k, i in enumerate(items[:MAX_BOXES], 1):
            if i.bbox_px:
                boxes.append({"item_id": i.item_id, "page": i.page, "bbox_px": i.bbox_px, "label": str(k)})
    else:
        cites.append({"n": 1, "doc_id": doc.doc_id, "page": 1, "kind": "element", "bbox_px": None,
                      "item_ids": [i.item_id for i in items], "quote": None})
    ids = [i.item_id for i in items]
    scene = {"doc_id": doc.doc_id, "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None}
    return boxes, cites, scene


def _cite_marks(cites) -> str:
    return "".join(f"[{c['n']}]" for c in cites)


def _answer_obj(question, doc_ids, text, value, unit, conf, abstained, boxes, cites, scene, trace, route, t0):
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": value, "unit": unit, "confidence": round(conf, 3), "abstained": abstained},
        "citations": cites, "evidence": {"boxes": boxes, "scene": scene}, "trace": trace, "route": route,
        "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


def _abstain(question, doc_id, why, trace, route, t0, scene_doc=None):
    trace.append(_step("abstain", why))
    return _answer_obj(question, [doc_id], why, None, None, 0.0, True, [], [],
                       {"doc_id": scene_doc or doc_id, "highlight_item_ids": [], "camera_target_item_id": None},
                       trace, route, t0)


# ------------------------------------------------------------- the solver
def _qty(it: Item, kind: str, t: str) -> float | None:
    q = it.q
    if t == "area":
        keys = ("net_floor_area_m2", "area_m2", "net_area_m2", "gross_area_m2") if kind == "room" else \
               ("area_m2", "net_area_m2", "gross_area_m2", "net_side_area_m2")
        for k in keys:
            if q.get(k) is not None:
                if kind == "room" and float(q[k]) < 0.05:
                    return None     # an IfcSpace with a near-zero area is a broken quantity, not a tiny room
                return float(q[k])
        if q.get("width_m") is not None and q.get("height_m") is not None:
            return float(q["width_m"]) * float(q["height_m"])
        return None
    if t == "length":
        v = q.get("length_m")
        return None if v is None else float(v)
    if t == "volume":
        for k in ("net_volume_m3", "volume_m3", "gross_volume_m3"):
            if q.get(k) is not None:
                return float(q[k])
    return None


OUTDOOR_RE = re.compile(r"balcon|balkon|terras|loggia|veranda|garden|outdoor|garten|sitzplatz", re.I)


def _pip(pt, poly) -> bool:
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _apartments(question, doc, p, trace, route, t0):
    """Swiss-dwellings DXF plan maps carry apartment outlines as items with props.role == 'unit' (label 'App. A').
    count = number of units; area of apartment X = sum of rooms whose centre lies in the unit, outdoor rooms left out."""
    units = [i for i in doc.items if i.props.get("role") == "unit" and i.conf >= MIN_CONF]
    if not units:
        return None
    trace.append(_step("load", f"{len(units)} apartment outlines (role=unit)"))
    doc_id = doc.doc_id
    if p.type == "count":
        n = len(units)
        boxes, cites, scene = _evidence(doc, units)
        text = f"There {'is' if n == 1 else 'are'} **{n} {'apartment' if n == 1 else 'apartments'}** on this floor plan. {_cite_marks(cites)}"
        return _answer_obj(question, [doc_id], text, n, "count", 0.9, False, boxes, cites, scene, trace, route, t0)
    m = re.search(r"\bapartment\s+([A-Za-z0-9]{1,3})\b", question)
    if not m:
        return None
    key = m.group(1).casefold()
    unit = next((u for u in units if (u.label or "").casefold().replace(".", " ").split()[-1:] == [key]), None)
    if unit is None:
        return _abstain(question, doc_id, f"I could not find apartment {m.group(1)} on this plan.", trace, route, t0)
    poly = [tuple(pt) for pt in (unit.polygon_px or [])]
    return None if not poly else _apt_area(question, doc, unit, poly, trace, route, t0)


def _apt_area(question, doc, unit, poly, trace, route, t0):
    rooms = []
    for r in doc.items:
        if r.kind != "room" or not r.bbox_px or r.conf < MIN_CONF:
            continue
        c = ((r.bbox_px[0] + r.bbox_px[2]) / 2, (r.bbox_px[1] + r.bbox_px[3]) / 2)
        if _pip(c, poly) and not OUTDOOR_RE.search(r.label or "") and r.q.get("area_m2") is not None:
            rooms.append(r)
    if not rooms:
        return _abstain(question, doc.doc_id, "I could not match rooms to that apartment.", trace, "planmap", t0)
    total = sum(r.q["area_m2"] for r in rooms)
    trace.append(_step("area", f"{len(rooms)} indoor rooms inside {unit.label} = {total:.2f} m2"))
    boxes, cites, scene = _evidence(doc, rooms)
    text = f"The net floor area of **{unit.label}** is **{_fmt(total, 'area')} m²** across {len(rooms)} indoor rooms. {_cite_marks(cites)}"
    return _answer_obj(question, [doc.doc_id], text, round(total, 4), "m²", 0.9, False, boxes, cites, scene, trace, "planmap", t0)


def solve(question: str, doc_id: str, parsed: Parsed | None = None, root: Path | str = ARTIFACTS,
          page: int | None = None, hidden: dict[str, str] | None = None) -> dict:
    """hidden: {item_id: tag} the chat has hidden in the scene; they are left out and the answer says so."""
    t0 = time.perf_counter()
    p = parsed or parse(question)
    if p.type not in NUMERIC:
        raise SolverUnsupported(f"type {p.type}")
    trace = [_step("route", f"{p.type} / {p.kind} / {p.scope or 'unscoped'} -> " + "code, no model")]
    doc = load_doc(doc_id, Path(root))
    if doc is None:
        return _abstain(question, doc_id, "I have no structured data for this document yet, so I cannot answer that reliably.",
                        trace, "index", t0)
    route = "index" if doc.mode == "ifc" else "planmap"
    kind = p.kind
    if kind == "apartment" and doc.mode == "planmap" and p.type in ("count", "area"):
        res = _apartments(question, doc, p, trace, route, t0)
        if res is not None:
            return res
    if kind is None or kind in UNSUPPORTED_KINDS:
        return _abstain(question, doc_id, "I could not tell which elements the question is about, so I would rather not guess.",
                        trace, route, t0)

    if doc.mode == "planmap" and kind == "storey" and p.type == "count" and not page:
        n = max(1, doc.pages)   # a plan-map page is one level; this is the number of pages read
        trace.append(_step("count", f"{n} storey(s) = {doc.pages} plan page(s)"))
        text = f"This drawing shows **{n} {'floor' if n == 1 else 'floors'}** (one per plan page)."
        return _answer_obj(question, [doc_id], text, n, "count", 0.6, False, [], [], {"doc_id": doc_id, "highlight_item_ids": [],
                           "camera_target_item_id": None}, trace, route, t0)

    kinds = {kind}
    if kind in ("shower", "bathtub") and re.search(r"\bshowers?\b", question, re.I) and re.search(r"\bbath ?tubs?\b", question, re.I):
        kinds = {"shower", "bathtub"}   # "showers and bathtubs in total"
    items = [i for i in doc.items if i.kind in kinds]
    if doc.mode == "planmap":
        if page:
            items = [i for i in items if i.page == page]
        low = [i for i in items if i.conf < MIN_CONF]
        items = [i for i in items if i.conf >= MIN_CONF]
        trace.append(_step("load", f"plan map: {len(items)} {kind} items (conf >= {MIN_CONF}; {len(low)} below ignored)"))
    else:
        trace.append(_step("load", f"{len(items)} {kind} elements of {len(doc.items)} in the model"))

    hid_note = ""
    if hidden:
        gone = [i for i in items if i.item_id in hidden]
        if gone:
            items = [i for i in items if i.item_id not in hidden]
            names = [hidden[i.item_id] for i in gone]
            hid_note = " (with " + (", ".join(names) if len(names) <= 5 else f"{len(names)} items") + " hidden)"
            trace.append(_step("scene", f"{len(gone)} hidden item(s) left out"))
    where = ("on this floor plan" if doc.mode == "planmap" else "in this model") + hid_note
    # --- storey scope (IFC only; a plan map page is one level)
    if doc.mode == "ifc":
        st = resolve_storey(question, doc.storeys)
        if st is None and p.scope == "storey":
            return _abstain(question, doc_id, "I could not tell which floor you mean. Name it as it is called in the model, for example "
                            + (f"\"{doc.storeys[0]['name']}\"." if doc.storeys else "\"Level 1\"."), trace, route, t0)
        if st:
            items = [i for i in items if i.storey == st]
            where = f"on **{st}**"
            trace.append(_step("scope", f"storey = {st}: {len(items)} left"))

    # --- room / label filters
    subject = None
    sub_name = None
    quoted = _quoted(question)
    if kind == "room" and doc.mode == "planmap" and re.search(r"\bnumbered\b.*\b(?:indoor|interior)\b|\b(?:indoor|interior)\b.*\bnumbered\b", question, re.I):
        out = re.compile(r"balcon|balkon|terras|loggia|veranda|garden|outdoor", re.I)
        items = [i for i in items if i.props.get("number") and not out.search(i.label or "")]
        subject = "numbered indoor rooms"
        trace.append(_step("filter", f"numbered indoor rooms: {len(items)}"))
    if kind == "room" and doc.mode == "planmap" and not quoted and not _room_id(question) and p.type in ("count", "area"):
        sub = room_subtype(question)
        if sub:
            name, types = sub
            if not any(i.props.get("room_type") for i in items):
                return _abstain(question, doc_id, f"The room types on this plan have not been read, so I cannot pick out the {name}s.", trace, route, t0)
            if name == "sauna":  # no room type for it in the model: only count rooms whose OCR label says so
                return _abstain(question, doc_id, "This plan reader has no sauna room type and the label is not reliably read, so I would rather not guess.", trace, route, t0)
            items = [i for i in items if i.props.get("room_type") in types]
            subject = f"{name}s"
            sub_name = name
            trace.append(_step("filter", f"room type {sorted(types)}: {len(items)} matched"))
    if kind == "room" and (p.scope == "room" or quoted or _room_id(question)):
        rid = _room_id(question)
        sel = []
        if rid:   # a room number is unique: it beats the (shared) room name
            sel = [i for i in items if str(i.props.get("number") or "").casefold() == rid.casefold()]
        if not sel and quoted:   # "'Kontor (Rum nr. 204)'": the bracket is the room's id; it beats the shared type name
            for t in quoted:
                m = re.search(r"\(([^)]+)\)\s*$", t)
                if m:
                    pid = m.group(1).strip().casefold()
                    tail = pid.split()[-1]
                    sel += [i for i in items if (i.name or "").casefold() in (pid, tail) or str(i.props.get("number") or "").casefold() == tail]
        if not sel and quoted:
            sel = [i for i in items if any(_label_matches(i, t) for t in quoted)]
        if not sel and rid:
            sel = [i for i in items if (i.name or "").casefold() == rid.casefold() or (i.label or "").casefold() == rid.casefold()
                   or i.item_id == rid or str(i.props.get("number") or "").casefold() == rid.casefold()]
        if not sel and (quoted or rid) and doc.mode == "planmap" and not any(i.label for i in items):
            return _abstain(question, doc_id, "The room names on this plan have not been read, so I cannot pick out that room.",
                            trace, route, t0)
        if not sel and p.type != "count":
            return _abstain(question, doc_id, f"I could not find {'room ' + rid if rid else 'that room'} in the data.", trace, route, t0)
        if sel or quoted:
            items = sel
            subject = f"room {rid}" if rid and not quoted else f"“{quoted[0]}”"
            trace.append(_step("filter", f"room {subject}: {len(items)} matched"))
    elif quoted and p.type == "count":
        sel = [i for i in items if any(_label_matches(i, t) for t in quoted)]
        items = sel
        trace.append(_step("filter", f"label {quoted}: {len(items)} matched"))

    # --- compute
    if p.type == "count":
        n = len(items)
        conf = (sum(i.conf for i in items) / n if n else 0.6) if doc.mode == "planmap" else 1.0
        conf = min(conf, 0.95) if doc.mode == "planmap" else 1.0
        trace.append(_step("count", f"{n} {kind}"))
        boxes, cites, scene = _evidence(doc, items)
        marks = _cite_marks(cites)
        if sub_name:
            noun = sub_name + ("" if n == 1 else "es" if sub_name.endswith("s") else "ies" if sub_name.endswith("y") else "s")
            noun = sub_name[:-1] + "ies" if (n != 1 and sub_name.endswith("y")) else noun
            text = (f"I found **no {sub_name}s** {where}." if n == 0 else
                    f"There {'is' if n == 1 else 'are'} **{n} {noun}** {where}. {marks}")
        elif n == 0:
            text = f"I found **no {_plural(kind, 2)}** {where}." if not subject else f"I found **no {_plural(kind, 2)}** matching {subject} {where}."
        else:
            verb = "is" if n == 1 else "are"
            text = f"There {verb} **{n} {_plural(kind, n)}** {where}. {marks}"
        return _answer_obj(question, [doc_id], text, n, "count", conf, False, boxes, cites, scene, trace, route, t0)

    vals = [(i, _qty(i, kind, p.type)) for i in items]
    if doc.mode == "ifc" and kind == "room" and p.type == "area" and len(items) <= 50 and any(v is None for _, v in vals):
        from engine.solvers.glbarea import room_floor_area_m2
        glb = Path(root) / doc_id / "scene.glb"
        if glb.exists():
            vals = [(i, v if v is not None else room_floor_area_m2(glb, i.item_id)) for i, v in vals]
            trace.append(_step("area", "room floor area measured from the scene mesh (no area quantity in the model)"))
    have = [(i, v) for i, v in vals if v is not None]
    unit = UNIT[p.type]
    scale_note = ""
    conf = 1.0
    if doc.mode == "planmap":
        sc = doc.scale or {}
        if p.type == "area" and kind == "room":
            if sc.get("method") in (None, "none"):
                return _abstain(question, doc_id, "This plan has no scale I can trust, so I cannot give areas in square metres.", trace, route, t0)
            conf = float(sc.get("confidence") or 0.3)
            if conf < 0.5:
                scale_note = " This is approximate: the scale is estimated from the size of the doors."
        else:
            return _abstain(question, doc_id, f"I do not measure {p.type} of {_plural(kind, 2)} from a plan reliably yet.", trace, route, t0)
        conf = min(conf, sum(i.conf for i, _ in have) / len(have)) if have else 0.0
    if not have:
        return _abstain(question, doc_id, f"The model has no {p.type} data for {_plural(kind, 2)}"
                        + (f" {subject}" if subject else "") + ", so I cannot give a figure.", trace, route, t0)
    total = sum(v for _, v in have)
    missing = len(items) - len(have)
    trace.append(_step(p.type, f"sum over {len(have)} {kind} = {total:.4f} {unit}" + (f" ({missing} without data)" if missing else "")))
    boxes, cites, scene = _evidence(doc, [i for i, _ in have])
    marks = _cite_marks(cites)
    num = f"**{_fmt(total, p.type)} {unit}**"
    if len(have) == 1:
        text = f"The {p.type} of {subject or _plural(kind, 1)} is {num}. {marks}"
    else:
        text = f"The total {p.type} of the **{len(have)} {_plural(kind, len(have))}** {where} is {num}. {marks}"
    if missing:
        text += f" {missing} of {len(items)} had no {p.type} recorded and are not included."
    text += scale_note
    return _answer_obj(question, [doc_id], text, round(total, 4), unit, conf, False, boxes, cites, scene, trace, route, t0)
