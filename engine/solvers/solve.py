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
    return [m.group(1).strip() for m in re.finditer(r"(?<![\w])'([^']+)'(?!\w)|\"([^\"]+)\"", q) for m in [re.match(r"(.*)", m.group(1) or m.group(2))]]


def _label_matches(it: Item, text: str) -> bool:
    t = text.casefold()
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
    cands = [it.label, it.name, it.type_name, it.props.get("room_type")]
    return any(c and c.casefold() == t for c in cands)


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


def solve(question: str, doc_id: str, parsed: Parsed | None = None, root: Path | str = ARTIFACTS,
          page: int | None = None) -> dict:
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
    if kind is None or kind in UNSUPPORTED_KINDS:
        return _abstain(question, doc_id, "I could not tell which elements the question is about, so I would rather not guess.",
                        trace, route, t0)

    items = [i for i in doc.items if i.kind == kind]
    if doc.mode == "planmap":
        if page:
            items = [i for i in items if i.page == page]
        low = [i for i in items if i.conf < MIN_CONF]
        items = [i for i in items if i.conf >= MIN_CONF]
        trace.append(_step("load", f"plan map: {len(items)} {kind} items (conf >= {MIN_CONF}; {len(low)} below ignored)"))
    else:
        trace.append(_step("load", f"{len(items)} {kind} elements of {len(doc.items)} in the model"))

    where = "on this floor plan" if doc.mode == "planmap" else "in this model"
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
    quoted = _quoted(question)
    if kind == "room" and (p.scope == "room" or quoted or _room_id(question)):
        rid = _room_id(question)
        sel = []
        if quoted:
            sel = [i for i in items if any(_label_matches(i, t) for t in quoted)]
        if not sel and rid:
            sel = [i for i in items if (i.name or "").casefold() == rid.casefold() or (i.label or "").casefold() == rid.casefold()
                   or i.item_id == rid]
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
        if n == 0:
            text = f"I found **no {_plural(kind, 2)}** {where}." if not subject else f"I found **no {_plural(kind, 2)}** matching {subject} {where}."
        else:
            verb = "is" if n == 1 else "are"
            text = f"There {verb} **{n} {_plural(kind, n)}** {where}. {marks}"
        return _answer_obj(question, [doc_id], text, n, "count", conf, False, boxes, cites, scene, trace, route, t0)

    vals = [(i, _qty(i, kind, p.type)) for i in items]
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
