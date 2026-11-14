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
ROOM_TYPE_MIN_CONF = 0.85   # unlabelled model-typed rooms below this are not counted as bedroom/kitchen/bathroom (clean calib set: 63% -> 74%)
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
_ORD = {"ground": 0, "grund": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}


def resolve_storey(q: str, storeys: list[dict]) -> str | None:
    from .filters import fold
    ql = fold(q)
    names = [s["name"] for s in storeys]
    for n in sorted(names, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(fold(n))}(?!\w)", ql):
            return n
    if not storeys:
        return None
    srt = sorted(storeys, key=lambda s: s["elevation_m"])
    ground = next((i for i, s in enumerate(srt) if s["elevation_m"] >= -0.5), 0)   # a ground floor at -0.15 m (finished floor below the site datum) is still ground
    # German storey abbreviations and English numeric ordinals share the same level.
    m = re.search(r"\b(\d+)\s+(?:og|obergeschoss)\b", ql)
    if m:
        n = next((n for n in names if re.match(rf"^{m.group(1)}\s+(?:og|obergeschoss)\b", fold(n))), None)
        if n:
            return n
    m = re.search(r"\b(ground|grund|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+(?:floor|level|storey|story)\b|\b(?:floor|level|storey|story)\s+(\d+)\b", ql)
    if m:
        token = m.group(1) or m.group(2)
        ordinal = _ORD[token] if token in _ORD else int(re.match(r"\d+", token).group())
        i = ground + ordinal
        return srt[i]["name"] if 0 <= i < len(srt) else None
    if re.search(r"\b(eg|erdgeschoss)\b", ql):
        return srt[ground]["name"]
    if re.search(r"\b(basement|underground|cellar|keller)\b", ql):
        return srt[0]["name"] if srt[0]["elevation_m"] < 0 else None
    if re.search(r"\b(top|upper most|uppermost|roof) (?:floor|level|storey)|\b(dg|dachgeschoss)\b", ql):
        return srt[-1]["name"]
    return None


def _quoted(q: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?<![\w])'(.+?)'(?!\w)|\"([^\"]+)\"", q) for m in [re.match(r"(.*)", m.group(1) or m.group(2))]]


def _label_matches(it: Item, text: str) -> bool:
    from .filters import fold
    def norm(x):
        return x.casefold().replace("\u2019", "'").replace("\u2018", "'").strip()
    t = norm(re.sub(r"\s*\([^)]*\)\s*$", "", text))
    cands = [it.label, it.name, it.type_name, it.props.get("room_type"), it.props.get("long_name")]
    return any(c and (norm(c) == t or (it.kind == "room" and re.search(rf"(?<!\w){re.escape(fold(t))}(?!\w)", fold(c)))) for c in cands)


def _pt_in_poly(pt, poly) -> bool:
    x, y = pt
    c = False
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _rooms_holding_text(doc, rooms, sel, quoted, page, hidden) -> list:
    """Rooms (not yet selected) with a text item matching a quoted label whose centre lies inside the room outline."""
    have = {id(i) for i in sel}
    txt = [t for t in doc.items if t.kind == "text" and t.bbox_px and t.conf >= MIN_CONF and (not page or t.page == page)
           and any(_label_matches(t, q) for q in quoted)]
    out = []
    for r in rooms:
        if id(r) in have or not r.polygon_px or len(r.polygon_px) < 3 or (r.q.get("area_m2") or r.props.get("area_m2_geom") or 0) < 1:
            continue
        if hidden and r.item_id in hidden:
            continue
        for t in txt:
            if t.page == r.page and _pt_in_poly(((t.bbox_px[0] + t.bbox_px[2]) / 2, (t.bbox_px[1] + t.bbox_px[3]) / 2), r.polygon_px):
                out.append(r)
                break
    return out


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


_SING = {"stairs": "staircase", "furniture": "furniture item"}
_PL = {"stairs": "stairs", "furniture": "furniture items", "space": "rooms", "room": "rooms"}


def _cite_label(doc: Doc, its: list[Item], page: int) -> str:
    """'Erdgeschoss · 16 doors, 44 windows' (IFC) or 'Page 2 · 11 doors' (plan map): what a citation points at, in words."""
    counts: dict[str, int] = {}
    for i in its:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    parts = []
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1])[:3]:
        w = _PL.get(k) or (k if n == 1 else k[:-1] + "ies" if k.endswith("y") and k[-2:-1] not in "aeiou" else k + ("es" if k.endswith(("s", "sh", "ch")) else "s"))
        parts.append(f"{n} {w if n != 1 else _SING.get(k, k)}")
    if len(counts) > 3:
        parts.append(f"{sum(counts.values()) - sum(n for _k, n in sorted(counts.items(), key=lambda kv: -kv[1])[:3])} more")
    what = ", ".join(parts)
    if doc.mode == "planmap":
        head = f"Page {page}" if (doc.pages or 1) > 1 else "Floor plan"
    else:
        st = sorted({i.storey for i in its if i.storey})
        head = ("All floors" if len(st) > 2 else " / ".join(st)) if st else f"Page {page}"
    return f"{head} · {what}" if what else head


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
                          "item_ids": [i.item_id for i in its], "quote": None, "label": _cite_label(doc, its, pg)})
        for k, i in enumerate(items[:MAX_BOXES], 1):
            if i.bbox_px:
                boxes.append({"item_id": i.item_id, "page": i.page, "bbox_px": i.bbox_px, "label": str(k)})
    else:
        # IFC: one citation per storey page that has a 2D plan (boxes numbered like the 3D/AR highlights); the rest on page 1.
        placed = [i for i in items if i.bbox_px]
        rest = [i for i in items if not i.bbox_px]
        by_page: dict[int, list[Item]] = {}
        for i in placed:
            by_page.setdefault(i.page, []).append(i)
        for pg, its in sorted(by_page.items()):
            cites.append({"n": len(cites) + 1, "doc_id": doc.doc_id, "page": pg, "kind": "element",
                          "bbox_px": [min(i.bbox_px[0] for i in its), min(i.bbox_px[1] for i in its),
                                      max(i.bbox_px[2] for i in its), max(i.bbox_px[3] for i in its)],
                          "item_ids": [i.item_id for i in its], "quote": None, "label": _cite_label(doc, its, pg)})
        if rest or not cites:
            cites.append({"n": len(cites) + 1, "doc_id": doc.doc_id, "page": 1, "kind": "element", "bbox_px": None,
                          "item_ids": [i.item_id for i in rest], "quote": None, "label": _cite_label(doc, rest, 1)})
        for k, i in enumerate(items[:MAX_BOXES], 1):
            if i.bbox_px:
                boxes.append({"item_id": i.item_id, "page": i.page, "bbox_px": i.bbox_px, "label": str(k), "kind": i.kind})
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
            if q.get(k) is not None and float(q[k]) > 1e-6:   # an exact zero is a missing quantity, not an empty element
                return float(q[k])
    return None


EXT_RE = re.compile(r"\b(exterior|external|outer|outside|outdoor|interior|internal|inner|inside|perimeter)\b", re.I)
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


FIXTURE_RX = {
    "toilet": re.compile(r"\b(wcs?|toilet\w*|lavator\w+|urinal\w*|aborte?|water closet)\b|toilet", re.I),
    "sink": re.compile(r"\b(sink|basin|wash ?basin|waschbecken|waschtisch|lavabo|spüle|spuele)\b|waschbecken|waschtisch", re.I),
    "shower": re.compile(r"\b(shower|dusche)\w*", re.I),
    "bathtub": re.compile(r"\b(bath ?tub|badewanne|wanne)\b", re.I),
}
FIXTURE_CLASSES = {"terminal", "sanitary", "furniture", "equipment", "proxy", "mep_other", "other"}
ROOM_FIXTURE = {"toilet": re.compile(r"\b(wcs?|toilet\w*|lavator\w+|aborte?|restrooms?|washrooms?|water closet)\b|toilet", re.I)}


def _room_text(i: Item) -> str:
    return " ".join(str(x) for x in (i.props.get("long_name"), i.type_name, i.name) if x)


def ifc_fixtures(doc: Doc, kind: str):
    """Sanitary fixtures in an IFC model, found generically: fixture elements first (IfcSanitaryTerminal and other
    terminals/furnishings whose name or type says so, any language), else the rooms named like a WC (long name or type)."""
    rx = FIXTURE_RX[kind]
    fx = [i for i in doc.items if i.kind in FIXTURE_CLASSES and i.kind != "room" and rx.search(" ".join(str(x) for x in (i.name, i.type_name) if x))]
    if kind == "toilet":
        fx = [i for i in fx if not re.search(r"sink|basin|waschbecken|waschtisch|shower|dusche", " ".join(str(x) for x in (i.name, i.type_name) if x), re.I)]
    if fx:
        return fx, ""
    rrx = ROOM_FIXTURE.get(kind)
    if rrx is not None:
        rooms = [i for i in doc.items if i.kind == "room" and rrx.search(_room_text(i))
                 and not re.search(r"bathroom|bad\b|badezimmer|dusche", _room_text(i), re.I)]
        if rooms:
            return rooms, "toilet rooms"
    return [], ""


def _solve_multi(question, doc_id, p: Parsed, root, page, hidden, t0) -> dict:
    """'how many windows and doors': one single-kind solve per kind (same filters, still $0), merged into one answer.
    Boxes are numbered 1..N across kinds; every box and citation carries its kind, and scene.item_kinds maps
    item_id -> kind, so the views can colour by kind."""
    from dataclasses import replace
    subs = [(k, solve(question, doc_id, replace(p, kind=k, kinds=[k], reason="how-many"), root, page, hidden)) for k in p.kinds]
    trace = [_step("route", f"count / {' + '.join(p.kinds)} / {p.scope or 'unscoped'} -> code, no model (one count per kind)")]
    for k, r in subs:
        if r["answer"]["abstained"]:
            trace += [dict(t) for t in r["trace"][1:]]
            return _answer_obj(question, [doc_id], r["answer"]["text_md"], None, None, 0.0, True, [], [],
                               {"doc_id": doc_id, "highlight_item_ids": [], "camera_target_item_id": None}, trace, r["route"], t0)
    boxes, cites, ids, item_kinds, counts, parts, confs = [], [], [], {}, {}, [], []
    offset = 0
    for k, r in subs:
        n = int(r["answer"]["value"])
        counts[k] = n
        confs.append(r["answer"]["confidence"])
        trace += [dict(t, detail=f"[{k}] {t['detail']}") for t in r["trace"][1:]]
        for b in r["evidence"]["boxes"]:
            boxes.append({**b, "label": str(int(b["label"]) + offset), "kind": k})
        for c in r["citations"]:
            cites.append({**c, "n": len(cites) + 1, "item_kind": k})
        sc_ids = r["evidence"]["scene"]["highlight_item_ids"]
        ids += sc_ids
        item_kinds.update({i: k for i in sc_ids})
        offset += len(r["evidence"]["boxes"])
        parts.append(f"**{n} {_plural(k, n)}**")
    where = "on this floor plan" if subs[0][1]["route"] == "planmap" else "in this model"
    sm = re.search(r"\bon \*\*([^*]+)\*\*\.", subs[0][1]["answer"]["text_md"])   # the single-kind answer already scoped to a storey
    if sm:
        where = f"on **{sm.group(1)}**" + (" (ground floor)" if sm.group(1).strip().lower() == "erdgeschoss" else "")
    text = f"There {'is' if sum(counts.values()) == 1 else 'are'} " + (", ".join(parts[:-1]) + " and " + parts[-1]) + f" {where}. " + _cite_marks(cites)
    scene = {"doc_id": doc_id, "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None, "item_kinds": item_kinds}
    return _answer_obj(question, [doc_id], text, counts, "count", min(confs), False, boxes, cites, scene, trace, subs[0][1]["route"], t0)


def solve(question: str, doc_id: str, parsed: Parsed | None = None, root: Path | str = ARTIFACTS,
          page: int | None = None, hidden: dict[str, str] | None = None) -> dict:
    """hidden: {item_id: tag} the chat has hidden in the scene; they are left out and the answer says so."""
    t0 = time.perf_counter()
    p = parsed or parse(question)
    if p.type not in NUMERIC:
        raise SolverUnsupported(f"type {p.type}")
    if p.type == "count" and len(p.kinds or []) > 1:
        return _solve_multi(question, doc_id, p, root, page, hidden, t0)
    trace = [_step("route", f"{p.type} / {p.kind} / {p.scope or 'unscoped'} -> " + "code, no model")]
    doc = load_doc(doc_id, Path(root))
    if doc is None:
        from .data import load_sheet_parent
        doc = load_sheet_parent(doc_id, Path(root), whole=bool(re.search(r"\b(?:in|of|across) the (?:whole |entire )?model\b", question, re.I)))
    if doc is None:
        return _abstain(question, doc_id, "I have no structured data for this document yet, so I cannot answer that reliably.",
                        trace, "index", t0)
    route = "index" if doc.mode == "ifc" else "planmap"
    if doc.mode == "ifc":
        from engine.analytics import filtered_question
        from dataclasses import replace
        filtered_doc = replace(doc, items=[i for i in doc.items if i.item_id not in hidden]) if hidden else doc
        filtered = filtered_question(question, filtered_doc, t0)
        if filtered is not None:
            if hidden:
                filtered["answer"]["text_md"] += " (with " + ", ".join(hidden.values()) + " hidden)"
            return filtered
    kind = p.kind
    if kind == "apartment" and doc.mode == "planmap" and p.type in ("count", "area"):
        res = _apartments(question, doc, p, trace, route, t0)
        if res is not None:
            return res
    if kind is None or kind in UNSUPPORTED_KINDS:
        return _abstain(question, doc_id, "I could not tell which elements the question is about, so I would rather not guess.",
                        trace, route, t0)

    if doc.mode == "planmap" and kind == "storey" and p.type == "count" and not page:
        from engine import storeys as _storeys   # E-60: several floor plans can share one sheet
        found = [_storeys.count_storeys([i for i in doc.items if i.page == pg]) for pg in range(1, max(1, doc.pages) + 1)]
        n = max(1, sum(f["n"] for f in found))
        how = {"layout": "separate floor plans on the sheet", "labels": "floor names printed on the sheet"}
        trace.append(_step("count", f"{n} storey(s): {doc.pages} plan page(s); " + ", ".join(f"{f['n']} by {how[f['basis']]}" for f in found)))
        extra = n > max(1, doc.pages)
        text = (f"This drawing shows **{n} {'floor' if n == 1 else 'floors'}** "
                + ("(separate floor plans drawn on the sheet)." if extra else "(one per plan page)."))
        return _answer_obj(question, [doc_id], text, n, "count", 0.6, False, [], [], {"doc_id": doc_id, "highlight_item_ids": [],
                           "camera_target_item_id": None}, trace, route, t0)

    if doc.mode == "ifc" and kind == "storey" and p.type == "count" and not page:
        sts = sorted(doc.storeys, key=lambda s: s.get("elevation_m", 0))
        n = len(sts)
        trace.append(_step("count", f"{n} storey(s) declared in the model"))
        if not n:
            return _answer_obj(question, [doc_id], "This model does not declare any storeys (no IfcBuildingStorey), so I cannot give a floor count from it.",
                               None, None, 0.0, True, [], [], {"doc_id": doc_id, "highlight_item_ids": [], "camera_target_item_id": None},
                               trace, route, t0)
        rep = []   # one element per storey (its first slab, else first element) so the citation points at something visible
        for s_ in sts:
            its = [i for i in doc.items if i.storey == s_["name"]]
            its.sort(key=lambda i: (i.kind != "slab", i.kind != "wall", i.item_id))
            if its:
                rep.append(its[0])
        listing = ", ".join(f"{s_['name']} ({s_.get('elevation_m', 0):+.1f} m)" for s_ in sts)
        _, cites, scene = _evidence(doc, rep)
        text = f"The model has **{n} {'storey' if n == 1 else 'storeys'}**, from lowest to highest: {listing}. {_cite_marks(cites)}"
        return _answer_obj(question, [doc_id], text, n, "count", 1.0, False, [], cites, scene, trace, route, t0)

    kinds = {kind}
    kind_note = ""
    if kind in ("shower", "bathtub") and re.search(r"\bshowers?\b", question, re.I) and re.search(r"\bbath ?tubs?\b", question, re.I):
        kinds = {"shower", "bathtub"}   # "showers and bathtubs in total"
    if doc.mode == "planmap" and kind in FIXTURE_RX and p.type == "count":
        unknown = [i for i in doc.items if i.source == "dxf" and i.kind == "other"
                   and i.props.get("role") == "fixture" and i.conf >= MIN_CONF
                   and (not page or i.page == page) and i.item_id not in (hidden or {})]
        if unknown:
            trace.append(_step("load", f"{len(unknown)} DXF fixture symbols have no fixture type"))
            return _abstain(question, doc_id,
                            f"The DXF contains unclassified fixture symbols, so I cannot give a reliable {_plural(kind, 1)} count.",
                            trace, route, t0)
    items = [i for i in doc.items if i.kind in kinds]
    if kind == "stairs" and doc.mode == "ifc" and any(i.props.get("ifc_class") == "IfcStair" for i in items):
        items = [i for i in items if i.props.get("ifc_class") != "IfcStairFlight"]   # flights are parts of a stair
    if doc.mode == "ifc" and kind in FIXTURE_RX and not items:
        items, how = ifc_fixtures(doc, kind)
        if how:
            kind_note = how
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
        from .filters import storey_requested
        if st is None and (p.scope == "storey" or storey_requested(question)):
            return _abstain(question, doc_id, "No matching floor was found. Storeys present: "
                            + ", ".join(s["name"] for s in doc.storeys) + ".", trace, route, t0)
        if st:
            items = [i for i in items if i.storey == st]
            where = f"on **{st}**"
            trace.append(_step("scope", f"storey = {st}: {len(items)} left"))

    # --- exterior / interior (IFC only): IsExternal property, else EXTERNAL space boundaries (flag set by pipeline.ifc_props)
    if doc.mode == "ifc" and kind in ("wall", "door", "window"):
        m = EXT_RE.search(question)
        if m:
            want_ext = m.group(1).lower() in ("exterior", "external", "outer", "outside", "outdoor", "perimeter")
            flagged = [i for i in items if i.props.get("is_external") is not None]
            if not flagged:
                return _abstain(question, doc_id, f"The model does not say which {_plural(kind, 2)} are exterior or interior, so I cannot separate them.",
                                trace, route, t0)
            items = [i for i in flagged if bool(i.props["is_external"]) == want_ext]
            lab = "exterior" if want_ext else "interior"
            how = " (from the model's space boundaries)" if any(i.props.get("is_external_source") == "space_boundary" for i in items) else ""
            where = f"{where}, {lab} only{how}"
            trace.append(_step("scope", f"{lab} {kind}s: {len(items)} left"))

    # --- room / label filters
    subject = None
    sub_name = None
    if kind == "room" and doc.mode == "ifc":
        from .filters import room_filter, missing_room_text
        selected = room_filter(question, items)
        if selected:
            subject, items = selected
            if not items:
                return _abstain(question, doc_id, missing_room_text(subject, [i for i in doc.items if i.kind == "room"]), trace, route, t0)
            trace.append(_step("filter", f"room {subject}: {len(items)} matched"))
    quoted = _quoted(question)
    # a quoted name that is the model's / sheet's title or a storey is the scope, not an element label
    _scope_names = {str(x).casefold().strip() for x in [doc.title, doc.meta.get("project"), doc.meta.get("building"),
                    *[st_["name"] for st_ in doc.storeys]] if x}
    _scope_names |= {t.split(" - Floor plan")[0].strip().casefold() for t in [doc.title] if t}
    quoted = [t for t in quoted if t.casefold().strip() not in _scope_names and not (doc.title and t.casefold().strip() in doc.title.casefold() and len(t) > 6)]
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
            if p.type == "count":   # a type read only by the segmentation head (no OCR label) must be confident; labelled rooms always count
                weak = [i for i in items if i.source == "det" and not i.props.get("label_room_type") and i.conf < ROOM_TYPE_MIN_CONF]
                if weak:
                    items = [i for i in items if i not in weak]
                    trace.append(_step("filter", f"{len(weak)} unlabelled room(s) typed by the model below conf {ROOM_TYPE_MIN_CONF} left out"))
            subject = f"{name}s"
            sub_name = name
            trace.append(_step("filter", f"room type {sorted(types)}: {len(items)} matched"))
    if kind == "room" and subject is None and (p.scope == "room" or quoted or _room_id(question)):
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
                    cand = [i for i in items if (i.name or "").casefold() in (pid, tail) or str(i.props.get("number") or "").casefold() == tail]
                    base = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip().casefold()
                    if len(cand) > 1 and base:   # the same number in several rooms: the name before the bracket tells them apart
                        nar = [i for i in cand if base in _room_text(i).casefold() or base == (i.label or "").casefold()]
                        cand = nar or cand
                    sel += cand
        if not sel and quoted:
            sel = [i for i in items if any(_label_matches(i, t) for t in quoted)]
        if not sel and rid:
            sel = [i for i in items if (i.name or "").casefold() == rid.casefold() or (i.label or "").casefold() == rid.casefold()
                   or i.item_id == rid or str(i.props.get("number") or "").casefold() == rid.casefold()]
        _room_text_counted = False
        if (doc.mode == "planmap" and p.type == "count" and quoted and not rid and not hidden
                and re.search(r"\brooms?\s+label(?:led|ed)\b", question, re.I)):
            # ROOM_TEXT is an explicit source label, independent of whether its insertion point falls
            # inside the room outline. Do not silently lose labels when polygon attribution fails.
            labels = [i for i in doc.items if i.kind == "text" and i.source == "dxf" and i.conf >= MIN_CONF
                      and i.props.get("dxf_layer", "ROOM_TEXT") == "ROOM_TEXT" and (not page or i.page == page)
                      and any(_label_matches(i, t) for t in quoted)]
            if len(labels) > len(sel):
                _room_text_counted = True
                sel = labels
                trace.append(_step("filter", "counted explicit DXF ROOM_TEXT labels; room polygon attribution is incomplete"))
        if doc.mode == "planmap" and quoted and not rid and sel and not _room_text_counted:
            # a room whose own label was taken by another tag ("Whg. A" over "Zimmer") still holds the printed word
            extra = _rooms_holding_text(doc, items, sel, quoted, page, hidden)
            if extra:
                sel = sel + extra
                trace.append(_step("filter", f"{len(extra)} room(s) carry the label as printed text inside their outline although another tag names them"))
        if not sel and (quoted or rid) and doc.mode == "planmap" and not any(i.label for i in items):
            return _abstain(question, doc_id, "The room names on this plan have not been read, so I cannot pick out that room.",
                            trace, route, t0)
        if not sel and p.type == "area" and not quoted and not rid:
            sel = list(items)        # no room named: answer for all rooms, with a per-room breakdown (never refuse)
            trace.append(_step("filter", "no room named: all rooms with a breakdown"))
        if not sel and p.type != "count":
            return _abstain(question, doc_id, f"I could not find {'room ' + rid if rid else 'that room'} in the data.", trace, route, t0)
        if (sel or quoted) and not (len(sel) == len(items) > 1 and not quoted and not rid):
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
            def _rn(k):
                return sub_name if k == 1 else (sub_name + "es" if sub_name.endswith(("s", "sh", "ch")) else sub_name[:-1] + "ies" if sub_name.endswith("y") and sub_name[-2:-1] not in "aeiou" else sub_name + "s")
            noun = _rn(n)
            text = (f"There are no {_rn(2)} {where}." if n == 0 else
                    f"There {'is' if n == 1 else 'are'} **{n} {noun}** {where}. {marks}")
            if n == 0:
                types = sorted({str(i.props.get("room_type")) for i in doc.items if i.kind == "room" and i.props.get("room_type")})
                text += (f" I checked all {len([i for i in doc.items if i.kind == 'room'])} rooms and none is labelled that way, "
                         "so the drawing may simply not name it.")
                conf = min(conf, 0.5)
        elif kind_note and n:
            text = f"There {'is' if n == 1 else 'are'} **{n} {kind_note[:-1] if n == 1 else kind_note}** (spaces named as a WC or toilet) {where}. {marks}"
        elif n == 0:
            text = f"I found **no {_plural(kind, 2)}** {where}." if not subject else f"I found **no {_plural(kind, 2)}** matching {subject} {where}."
            seen = sorted({i.kind for i in doc.items})
            text += (f" I searched {len(doc.items)} modelled elements ({', '.join(seen[:12])}); a zero here means none of those is a "
                     f"{kind}, not that the building has none, since it may not be modelled or drawn.")
            conf = min(conf, 0.5)
        else:
            verb = "is" if n == 1 else "are"
            text = f"There {verb} **{n} {_plural(kind, n)}** {where}. {marks}"
        return _answer_obj(question, [doc_id], text, n, "count", conf, False, boxes, cites, scene, trace, route, t0)

    vals = [(i, _qty(i, kind, p.type)) for i in items]
    if doc.mode == "ifc" and kind == "room" and p.type == "area" and len(items) <= 400 and any(v is None for _, v in vals):
        from engine.solvers.glbarea import room_floor_area_m2
        glb = Path(root) / (doc.meta.get("sheet_of") or doc_id) / "scene.glb"
        if glb.exists():
            vals = [(i, v if v is not None else room_floor_area_m2(glb, i.item_id)) for i, v in vals]
            trace.append(_step("area", "room floor area measured from the scene mesh (no area quantity in the model)"))
    if doc.mode == "ifc" and p.type == "volume" and len(items) <= 400 and any(v is None for _, v in vals):
        from engine.solvers.glbarea import element_volume_m3
        glb = Path(root) / (doc.meta.get("sheet_of") or doc_id) / "scene.glb"
        if glb.exists():
            vals = [(i, v if v is not None else element_volume_m3(glb, i.item_id)) for i, v in vals]
            trace.append(_step("volume", "volume measured from the scene mesh (no volume quantity in the model)"))
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
                scale_note = " Areas are estimated from door sizes because no printed scale was found, so treat them as approximate."
            elif sc.get("method") in ("scalebar", "ratio-dpi", "ratio-sheet"):
                scale_note = " Sized from the scale printed on the drawing."
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
    if kind == "room" and p.type == "area" and len(have) > 1 and not subject and not re.search(r"\b(total|sum|all|combined|together|overall)\b", question, re.I):
        top = sorted(have, key=lambda iv: -iv[1])[:10]
        text += " Per room: " + "; ".join(f"{(i.label or i.name or i.item_id)}{' (' + i.storey + ')' if i.storey else ''} {_fmt(v, 'area')} m²" for i, v in top) \
            + (f"; and {len(have) - len(top)} more" if len(have) > len(top) else "") + "."
    text += scale_note
    return _answer_obj(question, [doc_id], text, round(total, 4), unit, conf, False, boxes, cites, scene, trace, route, t0)
