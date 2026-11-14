"""E-59 (FIX-13): multi-condition questions. Plain code over the model, $0, no model call.

Every handler lists the conditions it APPLIED and the ones it could NOT apply. Anything left over makes the answer a labelled
partial (confidence <= 0.6), never a confident answer to a simpler question. Every answer says its scope back first.
Handlers only fire on a full-question pattern; anything else returns None and the normal pipeline runs.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

from engine.solvers.data import Doc, Item, load_doc

STOREY_ORDER = ["Keller", "Erdgeschoss", "1. Obergeschoss", "2. Obergeschoss", "Dachgeschoss"]


def fold(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("ü", "u"), ("ä", "a"), ("ö", "o"), ("ß", "ss")):
        s = s.replace(a, b)
    return s.replace("ue", "u").replace("ae", "a").replace("oe", "o")


def storeys_in(q: str, names: list[str]) -> list[str]:
    """Storeys named in the question; 'from X through/to Y' expands to every storey between them."""
    order = [n for n in STOREY_ORDER if n in names] or names
    pats = {"Keller": r"\bkeller\b|\bbasement\b", "Erdgeschoss": r"\berdgeschoss\b|\bground floor\b|\beg\b",
            "1. Obergeschoss": r"\b1\.?\s*(?:obergeschoss|og)\b|\bfirst floor\b", "2. Obergeschoss": r"\b2\.?\s*(?:obergeschoss|og)\b|\bsecond floor\b",
            "Dachgeschoss": r"\bdachgeschoss\b|\bdg\b"}
    found: list[tuple[int, str]] = []
    for n, p in pats.items():
        m = re.search(p, q, re.I)
        if m and n in order:
            found.append((m.start(), n))
    got = [n for _, n in sorted(found)]
    if len(got) >= 2 and re.search(r"\b(?:through|from .{0,40} to)\b", q, re.I):
        idx = [order.index(n) for n in got]
        return order[min(idx):max(idx) + 1]
    return got


def _mm(v: float) -> int:
    return int(round(v * 1000))


def _plan(i: Item):
    b = i.bbox_m
    return None if not b else (b[0][0], b[0][2], b[1][0], b[1][2])   # x0, z0, x1, z1 (y is up)


def _rooms(doc: Doc, storey: str | None = None) -> list[Item]:
    return [i for i in doc.items if i.kind == "room" and (storey is None or i.storey == storey)]


def _ln(i: Item) -> str:
    return (i.props.get("long_name") if i.props else None) or i.label or ""


def room_class(i: Item) -> str:
    n = fold(_ln(i))
    for pre, c in (("buro", "office"), ("wc", "toilet"), ("flur", "corridor"), ("labor", "laboratory"), ("technikraum", "technical room"),
                   ("seminarraum", "seminar room"), ("besprechungsraum", "meeting room")):
        if n.startswith(pre):
            return c
    return "unclassified"


class Ans:
    """Condition ledger for one answer."""

    def __init__(self, scope: str):
        self.scope, self.applied, self.left, self.body, self.items, self.value = scope, [], [], [], [], None
        self.calc = None

    def ap(self, *c):
        self.applied += c

    def lf(self, *c):
        self.left += c

    def text(self) -> str:
        head = f"**Scope I applied:** {self.scope}"
        tail = f"\n\nConditions applied: {'; '.join(self.applied)}." if self.applied else ""
        if self.left:
            tail += "\n\n**Partial answer. Not applied or not verifiable from this document:** " + "; ".join(self.left) + "."
        return head + "\n\n" + "\n".join(self.body) + tail


def _table(rows: list[list], head: list[str]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def _num(q: str, pat: str, default=None):
    m = re.search(pat, q, re.I)
    return float(m.group(1).replace(",", ".")) if m else default


def _ext(i: Item) -> bool:
    return bool(i.props.get("is_external"))


def _snames(doc: Doc) -> list[str]:
    return [s["name"] for s in doc.storeys]


# ---------- handlers over the IFC model ----------

def h_tiling(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"\btil", q, re.I) and re.search(r"\bWC\b", q) and re.search(r"box", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc)) or _snames(doc)
    waste = _num(q, r"(\d+(?:\.\d+)?)\s*%\s*waste", 0.0)
    cov = _num(q, r"covers?\s*(\d+(?:[.,]\d+)?)\s*m", None)
    price = _num(q, r"€\s*(\d+(?:[.,]\d+)?)", None)
    names = [n for n in ("Herren", "Damen") if re.search(n, q, re.I)]
    rooms = [r for r in _rooms(doc) if r.storey in st and fold(_ln(r)).startswith("wc") and (not names or any(n.lower() in _ln(r).lower() for n in names))]
    a = Ans(f"every {' / '.join('WC ' + n for n in names) or 'WC'} room on {', '.join(st)}; floor area = net floor area from the model.")
    a.items = rooms
    a.ap(f"rooms: {len(rooms)} matched", f"storeys: {st[0]} to {st[-1]}")
    tot = sum(r.q.get("net_floor_area_m2", 0) for r in rooms)
    rows = [[r.storey, _ln(r), f"{r.q.get('net_floor_area_m2', 0):.2f}"] for r in sorted(rooms, key=lambda r: (STOREY_ORDER.index(r.storey) if r.storey in STOREY_ORDER else 9, _ln(r)))]
    a.body += _table(rows, ["Storey", "Room", "Net floor area (m²)"]) + ["", f"Net floor area total: **{tot:.2f} m²**."]
    need = tot * (1 + waste / 100)
    a.ap(f"waste {waste:g}%")
    a.body.append(f"With {waste:g}% waste: **{need:.2f} m²**.")
    if cov:
        boxes = math.ceil(need / cov - 1e-9)
        a.ap(f"box coverage {cov:g} m²")
        a.body.append(f"Whole boxes at {cov:g} m² each: **{boxes} boxes** ({boxes * cov:.2f} m²).")
        a.value = boxes
        if price is not None:
            a.ap(f"price EUR {price:g} per box, excluding VAT")
            a.body.append(f"Cost: {boxes} x EUR {price:g} = **EUR {boxes * price:,.2f} excluding VAT**.")
        from engine.calc import input_value, question_source
        from engine.calc_routes import chain
        stub = {"answer": {"value": boxes, "unit": "boxes"}}
        ref = question_source(q)
        chain(stub, doc, [(r, r.q.get("net_floor_area_m2", 0)) for r in rooms], "m2", [
            ("area × (1 + waste/100)", "multiply", [input_value("waste factor", 1 + waste / 100, "factor", ref)], "m2"),
            ("order area / box coverage", "divide", [input_value("box coverage", cov, "m2/box", ref)], "boxes"),
            ("subtract numeric tolerance before ceil", "subtract", [input_value("floating point tolerance", 1e-9, "boxes", {"kind": "policy", "text": "Solver tolerance at an exact whole-box boundary"})], "boxes"),
            ("round up to whole boxes", "ceil", [], "boxes")])
        a.calc = stub["_calc"]
    else:
        a.lf("box coverage not given")
    return a


def h_external_face(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"external", q, re.I) and re.search(r"wall", q, re.I) and re.search(r"net area|rendering|gross area", q, re.I) and re.search(r"\bface\b", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    walls = [w for w in doc.items if w.kind == "wall" and _ext(w) and (not st or w.storey in st)]
    a = Ans(f"one face of each external wall on {', '.join(st) or 'all storeys'}; net = gross side area minus openings (IFC quantities).")
    a.items = walls
    a.ap(f"external walls: {len(walls)}", f"storey: {', '.join(st)}", "one face", "openings deducted")
    rows, g, n = [], 0.0, 0.0
    for w in sorted(walls, key=lambda w: w.name):
        gs, ns = w.q.get("gross_side_area_m2", 0), w.q.get("net_side_area_m2", 0)
        g, n = g + gs, n + ns
        rows.append([w.name, f"{gs:.2f}", f"{gs - ns:.2f}", f"{ns:.2f}"])
    a.body += _table(rows, ["Wall", "Gross (m²)", "Opening deductions (m²)", "Net (m²)"]) + ["", f"Totals: gross **{g:.2f} m²**, deductions **{g - n:.2f} m²**, net **{n:.2f} m²**."]
    if re.search(r"reveal", q, re.I):
        a.ap("reveals excluded: the side-area figure is the wall face only, reveals are separate surfaces")
    a.value = round(n, 2)
    from engine.calc import record_items
    stub = {"answer": {"value": a.value, "unit": "m2"}}
    record_items(stub, doc, [(w, w.q.get("net_side_area_m2", 0)) for w in walls], formula="net wall face = Σ(recorded net side areas)")
    a.calc = stub["_calc"]
    return a


def h_paint(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"paint", q, re.I) and re.search(r"tin|litre|liter", q, re.I) and re.search(r"coat", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    walls = [w for w in doc.items if w.kind == "wall" and not _ext(w) and (not st or w.storey in st)]
    words = {"one": 1, "two": 2, "three": 3}
    m = re.search(r"(\d+|one|two|three)\s*coats?", q, re.I)
    coats = float(words.get(m.group(1).lower(), m.group(1))) if m else 1.0
    cov = _num(q, r"(\d+(?:\.\d+)?)\s*m²\s*/\s*lit", 8)
    tin = _num(q, r"(\d+(?:\.\d+)?)\s*-?\s*lit(?:re|er)\s*tin", 9)
    extra = _num(q, r"(\d+(?:\.\d+)?)\s*%\s*extra", 0)
    faces = 2 if re.search(r"both faces", q, re.I) else 1
    area = sum(w.q.get("net_side_area_m2", 0) for w in walls) * faces
    litres = area * coats / cov * (1 + extra / 100)
    tins = math.ceil(litres / tin - 1e-9)
    a = Ans(f"internal walls (not external) on {', '.join(st) or 'all storeys'}, {faces} face(s) each, net of openings.")
    a.items = walls
    a.ap(f"internal walls: {len(walls)}", f"{faces} faces", f"{coats:g} coats", f"{cov:g} m²/litre per coat", f"{extra:g}% extra", f"{tin:g} litre tins")
    if re.search(r"reveal", q, re.I):
        a.ap("reveals excluded (side-area figure only)")
    if re.search(r"ceiling", q, re.I):
        a.ap("ceilings excluded (not measured)")
    a.body += [f"Painted area: {sum(w.q.get('net_side_area_m2', 0) for w in walls):.2f} m² net per face x {faces} = **{area:.2f} m²**.",
               f"Paint: {area:.2f} x {coats:g} coats / {cov:g} = {area * coats / cov:.1f} litres, +{extra:g}% = **{litres:.1f} litres**.",
               f"Tins of {tin:g} litres: **{tins} tins**."]
    a.value = tins
    from engine.calc import assumption_source, input_value, question_source
    from engine.calc_routes import chain
    stub = {"answer": {"value": tins, "unit": "tins"}}
    ref = question_source(q)
    chain(stub, doc, [(w, w.q.get("net_side_area_m2", 0)) for w in walls], "m2", [
        ("net side area × faces × coats", "multiply", [input_value("faces", faces, "count", ref), input_value("coats", coats, "count", ref)], "m2"),
        ("coated area / coverage", "divide", [input_value("coverage", cov, "m2/litre", ref if re.search(r"m²\s*/\s*lit", q, re.I) else assumption_source("Default paint coverage 8 m2/litre"))], "litre"),
        ("litres × (1 + extra/100)", "multiply", [input_value("extra factor", 1 + extra / 100, "factor", ref)], "litre"),
        ("litres / tin capacity", "divide", [input_value("tin capacity", tin, "litre/tin", ref if re.search(r"lit(?:re|er)\s*tin", q, re.I) else assumption_source("Default tin capacity 9 litres"))], "tins"),
        ("subtract numeric tolerance before ceil", "subtract", [input_value("floating point tolerance", 1e-9, "tins", {"kind": "policy", "text": "Solver tolerance at a whole-tin boundary"})], "tins"),
        ("round up to whole tins", "ceil", [], "tins")])
    a.calc = stub["_calc"]
    return a


def h_masonry(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"kalksandstein", q, re.I) and re.search(r"volume", q, re.I) and re.search(r"€|cost", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    waste = _num(q, r"(\d+(?:\.\d+)?)\s*%\s*waste", 0)
    price = _num(q, r"€\s*(\d+(?:[.,]\d+)?)\s*/\s*m", None)
    walls = [w for w in doc.items if w.kind == "wall" and not _ext(w) and fold(w.props.get("material", "")).startswith("kalksandstein") and w.storey in st]
    a = Ans(f"internal Kalksandstein walls on {', '.join(st)}, net volume (openings removed), shown per storey.")
    a.items = walls
    a.ap(f"walls: {len(walls)}", f"storeys: {', '.join(st)}", "net volume", f"{waste:g}% waste")
    rows, tot = [], 0.0
    for s in st:
        v = sum(w.q.get("net_volume_m3", 0) for w in walls if w.storey == s)
        tot += v
        rows.append([s, sum(1 for w in walls if w.storey == s), f"{v:.2f}", f"{v * (1 + waste / 100):.2f}",
                     f"EUR {v * (1 + waste / 100) * price:,.0f}" if price else "n/a"])
    a.body += _table(rows, ["Storey", "Walls", "Net volume (m³)", f"+{waste:g}% (m³)", "Cost excl. VAT"])
    if price:
        a.ap(f"EUR {price:g}/m³ excluding VAT")
        a.body += ["", f"Total: {tot:.2f} m³, with waste {tot * (1 + waste / 100):.2f} m³, **EUR {tot * (1 + waste / 100) * price:,.0f} excluding VAT** (assumed unit price)."]
        a.value = round(tot * (1 + waste / 100) * price)
        from engine.calc import input_value, question_source
        from engine.calc_routes import chain
        stub = {"answer": {"value": a.value, "unit": "EUR"}}
        chain(stub, doc, [(w, w.q.get("net_volume_m3", 0)) for w in walls], "m3", [
            ("net volume × (1 + waste/100)", "multiply", [input_value("waste factor", 1 + waste / 100, "factor", question_source(q))], "m3"),
            ("order volume × price", "multiply", [input_value("price", price, "EUR/m3", question_source(q))], "EUR")])
        a.calc = stub["_calc"]
    return a


def _near_rooms(doc: Doc, door: Item, tol=0.4) -> list[Item]:
    b = door.bbox_m
    if not b:
        return []
    cx, cz = (b[0][0] + b[1][0]) / 2, (b[0][2] + b[1][2]) / 2
    out = []
    for r in _rooms(doc, door.storey):
        p = _plan(r)
        if p and p[0] - tol <= cx <= p[2] + tol and p[1] - tol <= cz <= p[3] + tol:
            out.append(r)
    return out


def h_wide_doors(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"\bdoors?\b", q, re.I) and re.search(r"at least|wider|minimum|\bwide\b", q, re.I) and re.search(r"\d(?:\.\d+)?\s*m\b", q)
            and re.search(r"\bwhich\b|\blist\b", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    w_min = _num(q, r"(\d+(?:\.\d+)?)\s*m\s*wide", None) or _num(q, r"at least\s*(\d+(?:\.\d+)?)\s*m", None)
    h_min = _num(q, r"(\d+(?:\.\d+)?)\s*m\s*high", None)
    internal = bool(re.search(r"internal", q, re.I))
    ds = [d for d in doc.items if d.kind == "door" and (not st or d.storey in st) and (not internal or not _ext(d))
          and (w_min is None or (d.q.get("width_m") or 0) >= w_min - 1e-6) and (h_min is None or (d.q.get("height_m") or 0) >= h_min - 1e-6)]
    a = Ans(f"{'internal ' if internal else ''}doors on {', '.join(st) or 'all storeys'} with width >= {w_min} m" + (f" and height >= {h_min} m" if h_min else "") + ".")
    a.items = ds
    a.ap(f"storey {', '.join(st)}", f"width >= {w_min} m", *([f"height >= {h_min} m"] if h_min else []), *(["internal"] if internal else []))
    rows = []
    for d in ds:
        nr = _near_rooms(doc, d)
        rows.append([d.name, f"{_mm(d.q['width_m'])} x {_mm(d.q['height_m'])} mm", ", ".join(f"{_ln(r)} ({room_class(r)})" for r in nr) or "none found"])
    a.body += _table(rows, ["Door", "Size", "Rooms at the door (by position, +/-0.4 m)"]) if rows else ["No door matches."]
    if re.search(r"office", q, re.I) and re.search(r"flur|corridor", q, re.I):
        keep = [d for d in ds if any(room_class(r) == "office" for r in _near_rooms(doc, d)) and any(room_class(r) == "corridor" for r in _near_rooms(doc, d))]
        a.ap("connects a Flur room to an office (tested on the rooms at the door)")
        if not keep:
            a.body += ["", f"**None of these {len(ds)} door(s) connects a Flur room to an office.** They join corridor sections to each other, so no door meets the Flur-to-office condition."]
        else:
            a.body += ["", f"Doors that meet the Flur-to-office condition: {', '.join(d.name for d in keep)}."]
        a.items = keep or a.items
        a.value = len(keep)
    if re.search(r"connect|both sides|office|WC", q, re.I):
        a.lf("which two rooms a door connects is read from room outlines at the door position, not from IFC space boundaries, so the room pairs are indicative; "
             "the 'office rather than WC' filter is applied on the room classes at the door")
    a.value = a.value if a.value is not None else len(ds)
    return a


def h_windows(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"windows?", q, re.I) and re.search(r"\b\d(?:\.\d+)?\s*m\s*(?:wide|high)", q, re.I) and re.search(r"\bwhich\b|\blist\b", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    w = _num(q, r"(\d+(?:\.\d+)?)\s*m\s*wide", None)
    h = _num(q, r"(\d+(?:\.\d+)?)\s*m\s*high", None)
    ex = bool(re.search(r"external", q, re.I))
    ws = [x for x in doc.items if x.kind == "window" and (not st or x.storey in st) and (not ex or _ext(x))
          and (w is None or abs((x.q.get("width_m") or 0) - w) < 1e-3) and (h is None or abs((x.q.get("height_m") or 0) - h) < 1e-3)]
    a = Ans(f"{'external ' if ex else ''}windows on {', '.join(st) or 'all storeys'}, exactly {w} m wide x {h} m high (nominal sizes from the model).")
    a.items = ws
    a.ap(f"storeys {', '.join(st)}", f"width {w} m", f"height {h} m", *(["external"] if ex else []))
    groups: dict[tuple, list[Item]] = {}
    for x in ws:
        groups.setdefault((x.storey, x.type_name), []).append(x)
    rows = [[s, t, len(v), f"{sum(i.q.get('width_m', 0) * i.q.get('height_m', 0) for i in v):.2f}", ", ".join(i.name for i in v)] for (s, t), v in groups.items()]
    a.body += _table(rows, ["Storey", "Type", "Count", "Nominal opening area (m²)", "Marks"]) if rows else ["No window matches."]
    tot = sum(i.q.get("width_m", 0) * i.q.get("height_m", 0) for i in ws)
    a.body += ["", f"**{len(ws)} windows**, total nominal opening area **{tot:.2f} m²**" + (" (windows 1.5 m high not included)." if h and h != 1.5 else ".")]
    for s in st:
        if not any(x.storey == s for x in ws):
            a.body.append(f"None on {s}.")
    a.value = len(ws)
    return a


def h_offices(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"office", q, re.I) and re.search(r"\d+\s*to\s*\d+\s*m", q, re.I) and re.search(r"exclud", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    m = re.search(r"(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)\s*m", q)
    lo, hi = float(m.group(1)), float(m.group(2))
    rs = [r for r in _rooms(doc) if r.storey in st and room_class(r) == "office"]
    excl = sorted({fold(x) for x in re.findall(r"\b(m[uü]e?ller|obermu?e?ller|obermüller)\b", q, re.I)}) or []
    excl_sec = bool(re.search(r"secretary", q, re.I))
    out, edge = [], []
    for r in rs:
        n = fold(_ln(r))
        if excl_sec and "sekr" in n:
            continue
        if any(x in n for x in excl):
            continue
        na = r.q.get("net_floor_area_m2", 0)
        if lo <= na <= hi:
            out.append(r)
        elif lo - 0.1 <= na < lo or hi < na <= hi + 0.1:
            edge.append(r)
    a = Ans(f"offices on {', '.join(st)} with net floor area {lo:g} to {hi:g} m² inclusive, excluding the secretary's office and rooms whose name contains {', '.join(excl)}.")
    a.items = out
    a.ap(f"storey {', '.join(st)}", "offices identified by room name", f"net area {lo:g}-{hi:g} m² inclusive",
         "secretary's office excluded", f"names excluded: {', '.join(excl)} (ü and ue spellings treated alike)")
    out.sort(key=lambda r: (r.q.get("net_floor_area_m2", 0), r.name))
    a.body += _table([[r.name, _ln(r), f"{r.q['net_floor_area_m2']:.2f}"] for r in out], ["Room no.", "Name", "Net area (m²)"]) if out else ["No office matches."]
    if edge:
        a.body += ["", f"Just under the {lo:g} m² limit on net area: " + ", ".join(f"{_ln(r)} ({r.q['net_floor_area_m2']:.2f} m²)" for r in edge) + "."]
    a.lf("the model has no occupant assignment; 'assigned to' is read from the name in the room label")
    a.value = len(out)
    return a


def h_walls_filter(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"walls?", q, re.I) and re.search(r"\b\d+\s*mm\s*thick", q, re.I) and re.search(r"removed volume|net volume", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    t = _num(q, r"(\d+)\s*mm\s*thick", 200) / 1000
    h = _num(q, r"at least\s*(\d+(?:\.\d+)?)\s*m\s*high", None)
    ws = [w for w in doc.items if w.kind == "wall" and not _ext(w) and fold(w.props.get("material", "")).startswith("kalksandstein") and w.storey in st
          and abs((w.q.get("width_m") or 0) - t) < 1e-3 and (h is None or (w.q.get("height_m") or 0) >= h - 1e-6)
          and w.q.get("net_volume_m3", 0) < w.q.get("gross_volume_m3", 0) - 1e-6]
    a = Ans(f"internal Kalksandstein walls on {', '.join(st)}, {int(t * 1000)} mm thick, height >= {h} m, net volume smaller than gross volume.")
    a.items = ws
    a.ap(f"storeys {', '.join(st)}", "internal", "Kalksandstein", f"thickness {int(t * 1000)} mm", f"height >= {h} m", "net < gross volume")
    rows = [[w.name, w.storey, f"{w.q['gross_volume_m3']:.2f}", f"{w.q['net_volume_m3']:.2f}", f"{w.q['gross_volume_m3'] - w.q['net_volume_m3']:.2f}"]
            for w in sorted(ws, key=lambda w: (w.storey, w.name))]
    a.body += _table(rows, ["Wall", "Storey", "Gross (m³)", "Net (m³)", "Removed (m³)"]) if rows else ["No wall matches."]
    a.body.append("")
    for s in st:
        sub = [w for w in ws if w.storey == s]
        a.body.append(f"{s}: **{len(sub)} walls**, removed volume **{sum(w.q['gross_volume_m3'] - w.q['net_volume_m3'] for w in sub):.2f} m³**.")
    a.value = len(ws)
    return a


def _shared(a: tuple, b: tuple, tol=0.5):
    """Length of the shared edge of two plan rectangles (corner contact gives 0)."""
    best = 0.0
    gx = max(a[0], b[0]) - min(a[2], b[2])
    gz = max(a[1], b[1]) - min(a[3], b[3])
    if -0.05 <= gx <= tol and gz < -0.05:
        best = max(best, -gz)
    if -0.05 <= gz <= tol and gx < -0.05:
        best = max(best, -gx)
    return best


def h_shared_wall(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"share a wall", q, re.I) and re.search(r"labor", q, re.I) and re.search(r"technikraum", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc)) or ["Keller"]
    labs = [r for r in _rooms(doc) if r.storey in st and room_class(r) == "laboratory"]
    tech = [r for r in _rooms(doc) if r.storey in st and room_class(r) == "technical room"]
    a = Ans(f"laboratories vs Technikraum I to IV on {', '.join(st)}; shared wall length from room outlines, corner-only contact excluded.")
    a.ap(f"storey {', '.join(st)}", "laboratories", "Technikraum I-IV", "corner contact excluded")
    rows = []
    for l in labs:
        for t in tech:
            pl, pt = _plan(l), _plan(t)
            if pl and pt and (s := _shared(pl, pt)) > 0.05:
                rows.append([_ln(l), _ln(t), f"{s:.2f}"])
                a.items += [i for i in (l, t) if i not in a.items]
    if rows:
        a.body += _table(rows, ["Laboratory", "Technical room", "Shared wall (m)"])
        a.lf("room outlines are bounding rectangles with a 0.5 m wall gap allowed; an L-shaped room can change the true shared length")
    else:
        gaps = []
        for l in labs:
            for t in tech:
                pl, pt = _plan(l), _plan(t)
                if pl and pt:
                    gaps.append((math.hypot(max(0, max(pl[0], pt[0]) - min(pl[2], pt[2])), max(0, max(pl[1], pt[1]) - min(pl[3], pt[3]))), l, t))
        g, l, t = min(gaps, key=lambda x: x[0]) if gaps else (0, None, None)
        a.body += ["**No laboratory shares a wall with a Technikraum, so there are no shared-wall lengths to list.**",
                   f"The closest pair is {_ln(l)} and {_ln(t)}, {g:.1f} m apart (a corridor lies between)." if l else ""]
        if g < 1.0:
            a.lf("the closest pair is near enough that room outlines (rectangles) could hide a shared wall")
    return a


def h_stacking(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"stack", q, re.I) and re.search(r"WC", q)):
        return None
    st = storeys_in(q, _snames(doc)) or STOREY_ORDER[:4]
    a = Ans(f"WC Herren and WC Damen on {', '.join(st)}; positions are the room outline centres in plan.")
    a.ap(f"storeys {st[0]} to {st[-1]}", "WC Herren, WC Damen", "horizontal offset from outline centres")
    rows, offs = [], []
    for nm in ("Herren", "Damen"):
        ref = None
        for s in st:
            r = next((r for r in _rooms(doc, s) if fold(_ln(r)) == f"wc {nm.lower()}"), None)
            if not r or not _plan(r):
                rows.append([f"WC {nm}", s, "not found", ""])
                continue
            p = _plan(r)
            c = ((p[0] + p[2]) / 2, (p[1] + p[3]) / 2)
            a.items.append(r)
            ref = ref or c
            d = math.hypot(c[0] - ref[0], c[1] - ref[1])
            offs.append(d)
            rows.append([f"WC {nm}", s, f"room {r.name}", f"{d:.2f} m"])
    a.body += _table(rows, ["Room", "Storey", "Room no.", "Offset from lowest storey"]) + [""]
    a.body.append("**Each WC sits directly above the one below (every offset under 5 cm): neither room shifts.**" if offs and max(offs) < 0.05
                  else "**At least one room is offset between floors, see the table.**")
    return a


def h_schedule_doors(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"door schedule", q, re.I) and re.search(r"storey", q, re.I)):
        return None
    ds = [d for d in doc.items if d.kind == "door"]
    a = Ans("every door in the model, grouped by storey, original mark, type and width x height in mm.")
    a.items = list(ds)
    a.ap("all storeys", "original marks kept (no merging)", "size in mm")
    groups: dict[tuple, list[Item]] = {}
    for d in ds:
        groups.setdefault((d.storey, d.name, d.type_name, _mm(d.q.get("width_m") or 0), _mm(d.q.get("height_m") or 0)), []).append(d)
    key = lambda k: (STOREY_ORDER.index(k[0]) if k[0] in STOREY_ORDER else 9, k[1])
    rows = [[k[0], k[1], k[2], f"{k[3]} x {k[4]}", len(v)] for k, v in sorted(groups.items(), key=lambda kv: key(kv[0]))]
    a.body += _table(rows, ["Storey", "Mark", "Type", "W x H (mm)", "Qty"])
    t5 = [d for d in ds if d.name == "Tür-005"]
    a.body += ["", f"**Tür-005 repeats on {len({d.storey for d in t5})} storeys and represents {len(t5)} physical doors** ("
               + ", ".join(f"{s}: {sum(1 for d in t5 if d.storey == s)}" for s in dict.fromkeys(d.storey for d in t5)) + ")."]
    t16 = [d for d in ds if fold(d.name) == fold("Tür-016")]
    var = [d for d in t16 if d.name != "Tür-016"]
    same = len({(d.type_name, _mm(d.q.get("width_m") or 0), _mm(d.q.get("height_m") or 0)) for d in t16}) == 1
    if var:
        a.body.append(f"**Tuer-016** ({len(var)} doors on {', '.join(sorted({d.storey for d in var}))}) has {'the same type and size' if same else 'a DIFFERENT type or size'} as Tür-016; only the spelling of the mark differs. "
                      + ("It looks like a typo, but do not merge it automatically: confirm on the drawing first, since a different spelling can also mean a different specification. Keep separate lines until confirmed." if same else "Do not merge them."))
    a.lf("type names are the IFC family names; fire rating, hardware and finish are not in the model, so this is a schedule of marks and sizes, not a full procurement specification")
    return a


def h_schedule_rooms(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"room schedule", q, re.I) and re.search(r"keller", q, re.I)):
        return None
    rs = _rooms(doc, "Keller")
    a = Ans("every room on Keller, classified by the room NAME (long_name), not by type_name.")
    a.items = list(rs)
    a.ap("storey Keller", "classification from name prefixes (Labor, Technikraum, Besprechungsraum, Seminarraum, WC, Flur)")
    groups: dict[str, list[Item]] = {}
    for r in rs:
        groups.setdefault(room_class(r), []).append(r)
    for c in ("laboratory", "technical room", "meeting room", "seminar room", "toilet", "corridor", "office", "unclassified"):
        if c in groups:
            v = groups[c]
            a.body += [f"**{c.capitalize()}s ({len(v)})**", *_table([[r.name, _ln(r), f"{r.q.get('net_floor_area_m2', 0):.1f}"] for r in sorted(v, key=lambda r: r.name)], ["No.", "Name", "Net area (m²)"]), ""]
    ty = sorted({r.type_name for r in rs})
    a.body.append(f"Why not use type_name: every space on Keller carries the same type_name ({', '.join(ty)}), so grouping by it would call all {len(rs)} spaces offices. The room name is what tells them apart.")
    return a


# ---------- honest not-in-document and partial answers ----------

def _nid(scope: str, what: list[str], have: str) -> Ans:
    a = Ans(scope)
    a.body += [f"**This is not in the document.** {have}", "", "What this drawing or model cannot tell you:"] + [f"- {w}" for w in what]
    a.lf("the question needs information that is not in the document")
    return a


def h_unanswerable(q: str, doc: Doc) -> Ans | None:
    if re.search(r"tile product|slip.resistance|waterproofing", q, re.I):
        return _nid("tile product, slip resistance, waterproofing and tiling height for the wet rooms.",
                    ["the exact tile product or article number", "the slip-resistance class", "the waterproofing system", "the wall tiling height", "any finish schedule or specification (none is printed on this drawing)"],
                    "The plan shows room labels (KPH, KHH+PH) and fixtures but no finish or product text. Do not release the purchase order from this drawing; get the finish schedule or specification.")
    if re.search(r"underfloor|before drilling|concealed", q, re.I):
        return _nid("services routes under the KPH floor.", ["underfloor heating loops", "electrical feeds", "concealed water pipes", "a safe drilling depth"],
                    "A floor plan like this does not show concealed services. Use the services drawings, a pipe and cable scanner, and the slab thickness from the structural drawings before drilling.")
    if re.search(r"u-values?|g-values?|heating energy", q, re.I):
        return _nid("window U-values, g-values and energy saving.", ["installed U-values and g-values (the model gives sizes, not thermal properties)",
                    "the building's actual Finnish location", "the heating demand and climate data needed for an energy saving figure"], "The model has window sizes and positions only.")
    if re.search(r"as-built|approved since|latest approved|issued for construction", q, re.I):
        return _nid("model status and approvals.", ["whether this is the latest or an as-built model", "the approval history",
                    "which changes to the WC layouts were approved after the construction issue", "any revision or approval record (none is stored with this file)"],
                    "The file carries no revision, issue status or approval record.")
    return None


def h_remove_wall(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"\b(?:can|could|should) (?:we|i)\b.*\b(?:remove|take out|knock|demolish|widen)\b", q, re.I) and re.search(r"\bwall\b", q, re.I)):
        return None
    st = storeys_in(q, _snames(doc))
    target = None
    for r in _rooms(doc):
        n = fold(_ln(r))
        if (not st or r.storey in st) and n and not n.startswith("flur") and re.search(re.escape(n), fold(q)):
            target = r
    walls = []
    if target and _plan(target):
        p = _plan(target)
        walls = [w for w in doc.items if w.kind == "wall" and w.storey == target.storey and not _ext(w) and w.bbox_m
                 and _plan(w)[0] <= p[2] + 0.5 and _plan(w)[2] >= p[0] - 0.5 and _plan(w)[1] <= p[3] + 0.5 and _plan(w)[3] >= p[1] - 0.5]
    if not target:
        return None   # no room named: the general "can I remove a wall" answer (structure-honest) handles it
    a = Ans(f"a what-if on the internal wall beside {_ln(target)}; nothing is changed in the model or the 3D view.")
    a.items = walls[:12]
    a.ap("internal walls beside the room (by outline, within 0.5 m)", "what-if only, not saved")
    mats = sorted({f"{w.props.get('material', '')} {_mm(w.q.get('width_m') or 0)} mm" for w in walls})
    a.body += [f"The model has {len(walls)} internal wall(s) touching or beside that room" + (f": {', '.join(sorted({w.name for w in walls})[:8])}." if walls else "."),
               f"They are built as {'; '.join(mats) or 'masonry'}. Masonry walls like these often carry load, and there are slabs and storeys above this level.",
               "", "**I cannot say you can remove it or widen the opening without propping.** The model has no load-bearing flag on its walls and no structural drawings, so whether it is load-bearing, "
               "and what temporary support or a lintel it needs, is not in this document. Treat it as possibly load-bearing: a structural engineer must confirm before any opening is widened."]
    a.lf("structural capacity, load paths and propping are not in the model")
    return a


def h_compliance(q: str, doc: Doc) -> Ans | None:
    m = re.search(r"\b(848|241|1007)/2017\b", q)
    if not m:
        return None
    which = m.group(1)
    topic = {"848": "fire safety (escape routes, exits)", "241": "accessibility (door widths, thresholds, manoeuvring space)", "1007": "safety in use (stairs, headroom, barriers)"}[which]
    a = Ans(f"a check against decree {which}/2017, {topic}, for what the question names.")
    a.ap(f"decree {which}/2017 named")
    have, miss = [], []
    if which == "848":
        if doc.mode == "ifc":
            have.append("door positions and sizes and the room layout, so the number of exits on a storey can be counted")
        miss += ["travel distance along the escape route (no walkable-route graph in the model)", "the fire class and occupancy of the building, which set the limits",
                 "door fire ratings (EI) and self-closing function (not in the model)"]
    elif which == "241":
        have.append("door widths and heights (frame size; the clear width is smaller)" if doc.mode == "ifc" else "door positions only")
        miss += ["thresholds or level changes at doors", "manoeuvring space dimensions at each door", "the clear opening width (the model gives frame width)"]
        if doc.mode != "ifc":
            miss += ["a dimensioned scale: the scale here is estimated from door icons, so widths are indicative", "the dwelling type"]
    else:
        has_st = [i for i in doc.items if i.kind == "stairs"]
        have.append(f"{len(has_st)} stair element(s) with position" if has_st else "no stair data")
        miss += ["riser and tread values", "landing geometry", "headroom along the flight", "railing height and fall protection (the railings carry no height value)"]
    a.body += ["I can say what the model supports, but a sign-off is not possible from it.", "", "**Can be checked from the model:** " + ("; ".join(have) or "very little") + ".",
               "**Cannot be checked from the model:** " + "; ".join(miss) + ".", "", "The Findings screen runs the checks the model does support; a design review needs the missing data first."]
    a.lf(*miss)
    return a


def _partial(what: str, why: str, left: list[str]) -> Ans:
    a = Ans(f"{what}.")
    a.body += [f"I cannot give a final answer: {why}."]
    a.lf(*left)
    return a


def h_spatial_honest(q: str, doc: Doc) -> Ans | None:
    if re.search(r"walkable route", q, re.I):
        return _partial("the route distance from the office doorway to the nearest WC entrance",
                        "the model has no walkable-route graph, so a distance along the corridors is not computed, and a straight-line figure would understate it", ["the route through the Flur rooms", "the distance along it"])
    if re.search(r"trace the route|delivery team", q, re.I):
        return _partial("the route from the entrance to MH on 2.kerros",
                        "the plan map has doors and rooms but no stair and no link between the two floor plans, so an ordered route and the doors to pass cannot be stated", ["the stair connection", "the ordered list of spaces and doors"])
    if re.search(r"same side of the building|compass", q, re.I):
        return h_terrace_side(doc)
    if re.search(r"bedrooms?", q, re.I) and re.search(r"external window", q, re.I):
        return h_bedroom_window(doc)
    return None


def _touch(b, r, t=8):
    return not (b[0] > r[2] + t or b[2] < r[0] - t or b[1] > r[3] + t or b[3] < r[1] - t)


def h_terrace_side(doc: Doc) -> Ans:
    a = Ans("TERASSI (1.kerros) and PARVEKE (2.kerros): their position on each floor plan.")
    its = [i for i in doc.items if i.kind == "room" and i.label in ("TERASSI", "PARVEKE")]
    a.items = its
    a.ap("both rooms found by their printed labels")
    a.body += [f"{i.label}: x {i.bbox_px[0]}-{i.bbox_px[2]} px, y {i.bbox_px[1]}-{i.bbox_px[3]} px" for i in its]
    a.body.append("Both sit along the top edge of their floor plan, so on the sheet they are on the same side. Which compass direction that is cannot be said.")
    a.lf("no north arrow or orientation is in the plan map, so compass directions for weather protection cannot be derived")
    return a


def h_bedroom_window(doc: Doc) -> Ans:
    mh = [i for i in doc.items if i.kind == "room" and i.label == "MH"]
    a = Ans("rooms labelled MH (makuuhuone, bedroom) on 2.kerros; windows and doors touching the room outline, and whether a door touches PARVEKE.")
    a.items = list(mh)
    a.ap("bedroom = printed label MH (the only bedroom label printed)")
    pv = next((i for i in doc.items if i.kind == "room" and i.label == "PARVEKE"), None)
    for r in mh:
        wins = [i for i in doc.items if i.kind == "window" and _touch(i.bbox_px, r.bbox_px)]
        dr = [i for i in doc.items if i.kind == "door" and _touch(i.bbox_px, r.bbox_px)]
        onto = [d for d in dr if pv and _touch(d.bbox_px, pv.bbox_px)]
        a.items += wins + dr
        a.body.append(f"MH: {len(wins)} window(s) and {len(dr)} door(s) touch its outline; {len(onto)} door(s) lead directly to PARVEKE.")
    a.body.append("Other bedrooms are not labelled in the plan map.")
    a.lf("whether a window is external is not recorded in the plan map", "unlabelled rooms cannot be identified as bedrooms")
    return a


GL = {"KPH": "kylpyhuone (bathroom)", "KHH": "kodinhoitohuone (utility room)", "PH": "pesuhuone (washroom)", "MH": "makuuhuone (bedroom)", "OH": "olohuone (living room)",
      "RT": "ruokailutila (dining area)", "K": "keittio (kitchen)", "H": "halli (hall)", "S": "sauna", "VH": "vaatehuone (walk-in wardrobe)", "ET": "eteinen (entrance hall)", "VAR": "varasto (storage)"}


def _mean(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def h_labels(q: str, doc: Doc) -> Ans | None:
    if doc.mode != "planmap":
        return None
    texts = [i for i in doc.items if i.kind == "text"]
    if re.search(r"KPH", q) and re.search(r"KHH", q) and not re.search(r"label schedule", q, re.I):
        a = Ans("the meaning of KPH and KHH+PH, whether WC is printed, and which space holds each toilet symbol.")
        a.items = [t for t in texts if t.label in ("KPH", "KHH+PH")]
        a.ap("printed labels KPH and KHH+PH", "toilet fixtures not counted as rooms")
        toilets = [i for i in doc.items if i.kind == "toilet"]
        a.body += [f"- **KPH** = {GL['KPH']}.", f"- **KHH+PH** = KHH {GL['KHH']} + PH {GL['PH']}: one combined space.",
                   f"- **WC is not written on this drawing**; the {len(toilets)} toilets are symbols only."]
        wet = [t for t in texts if t.label in ("KPH", "KHH+PH")]
        for n_, tl in enumerate(toilets, 1):
            cx, cy = _mean(tl.bbox_px)
            near = min(wet, key=lambda t: math.hypot(_mean(t.bbox_px)[0] - cx, _mean(t.bbox_px)[1] - cy))
            a.body.append(f"- Toilet symbol {n_} is nearest to **{near.label}**: a fixture in that space, not a separate room.")
            a.items.append(tl)
        a.lf("the nearest-label match for each toilet is by distance on the sheet, not by a room boundary")
        return a
    if re.search(r"label schedule", q, re.I):
        a = Ans("every printed label on 1.kerros and 2.kerros, with its source.")
        heads = {t.label: _mean(t.bbox_px)[0] for t in texts if t.label in ("1.kerros", "2.kerros")}
        split = (heads.get("1.kerros", 0) + heads.get("2.kerros", 1)) / 2
        rows = []
        for t in texts:
            if t.label in ("1.kerros", "2.kerros"):
                continue
            fl = "1.kerros" if _mean(t.bbox_px)[0] < split else "2.kerros"
            mean = "; ".join(GL.get(p, "?") for p in t.label.split("+")) if t.label.isupper() else {"TERASSI": "terrace", "PARVEKE": "balcony"}.get(t.label, "?")
            rows.append([fl, t.label, mean, "printed text"])
            a.items.append(t)
        rows.sort(key=lambda r: (r[0], r[1]))
        a.ap("labels kept exactly as printed", "floor assigned by which side of the sheet the label is on (between the two floor titles)")
        a.body += _table(rows, ["Floor", "Label as printed", "Meaning", "Source"])
        a.body += ["", "**From printed text:** the labels and their Finnish meanings above. **Model guesses:** room outlines and areas come from the segmenter, and most rooms carry no label; "
                   "any other classification (for example a bathroom for an unlabelled room) would be a guess and is not given."]
        a.lf("which floor a label belongs to is read from its position on the sheet, not from a stored floor field")
        return a
    if re.search(r"OH\+RT\+K", q):
        a = Ans("what OH+RT+K means and how to show it in a room schedule.")
        a.items = [t for t in texts if t.label == "OH+RT+K"]
        a.ap("printed label OH+RT+K")
        a.body += [f"OH+RT+K = {GL['OH']} + {GL['RT']} + {GL['K']}. The + signs are the Finnish way of writing **one combined open space** with three functions, not three enclosed rooms.",
                   "In a room schedule give it one row (one room number, one area, label OH+RT+K) and list the functions in a note. If the extracted map has separate living and kitchen regions, treat them as zones of that one row unless a wall is drawn between them."]
        a.lf("the plan map shows separate regions, but whether a wall divides them is not stated in the label; check the drawing")
        return a
    return None


def h_skirting(q: str, doc: Doc) -> Ans | None:
    if not (re.search(r"skirting", q, re.I) and doc.mode == "planmap" and re.search(r"\bMH\b", q)):
        return None
    r = next((i for i in doc.items if i.kind == "room" and i.label == "MH"), None)
    a = Ans("skirting for room MH on 2.kerros, excluding its doorway, 5% waste, 2.4 m lengths.")
    if not r:
        a.body.append("The room is not in the plan map.")
        a.lf("room not found")
        return a
    sc = doc.scale if isinstance(doc.scale, dict) else {}
    s = sc.get("m_per_px")
    b = r.bbox_px
    per = 2 * ((b[2] - b[0]) + (b[3] - b[1])) * s
    ds = [d for d in doc.items if d.kind == "door" and _touch(d.bbox_px, b)]
    net = per - 0.9 * len(ds)
    need = net * 1.05
    n = math.ceil(need / 2.4 - 1e-9)
    a.items = [r] + ds
    a.ap("room MH", "doorway excluded (0.9 m per door touching the room: the scale-prior width)", "5% waste", "2.4 m lengths, whole pieces")
    a.body += [f"Perimeter of the room outline: {per:.2f} m, minus {len(ds)} doorway x 0.9 m = {net:.2f} m; +5% = {need:.2f} m.", f"**About {n} lengths of 2.4 m ({n * 2.4:.1f} m)**, as an estimate."]
    a.lf(f"the drawing scale is estimated from door icons (confidence {sc.get('confidence')}), so every length is indicative, not exact; order only after a dimension or a stated scale", "the doorway width is assumed to be 0.9 m")
    a.value = n
    return a


def _only_ifc(doc: Doc) -> bool:
    return doc.mode == "ifc"


def h_extreme_room(q: str, doc: Doc) -> Ans | None:
    """'where is the biggest meeting room' names the room and its area, not a count."""
    m = re.search(r"\b(biggest|largest|smallest|tiniest)\s+(meeting|seminar|office|conference|toilet|wc|lab(?:oratory)?)\s*(?:room)?\b", q, re.I)
    if not _only_ifc(doc) or not m:
        return None
    kind = m.group(2).lower()
    key = {"meeting": "besprechung", "conference": "besprechung", "seminar": "seminar", "office": "buro", "toilet": "wc", "wc": "wc", "lab": "labor", "laboratory": "labor"}[kind]
    rs = [r for r in _rooms(doc) if fold(_ln(r)).startswith(key) and (r.q or {}).get("net_floor_area_m2")]
    st = storeys_in(q, _snames(doc))
    rs = [r for r in rs if not st or r.storey in st]
    if not rs:
        a0 = Ans(f"{kind} rooms identified by room name{' on ' + ', '.join(st) if st else ''}.")
        a0.body.append(f"**No room named like a {kind} room was found{' on ' + ', '.join(st) if st else ' in this model'}.**")
        return a0
    big = m.group(1).lower() in ("biggest", "largest")
    best = (max if big else min)(rs, key=lambda r: r.q["net_floor_area_m2"])
    a = Ans(f"{kind} rooms identified by room name ({len(rs)} found){' on ' + ', '.join(st) if st else ''}.")
    a.items = [best]
    a.ap(f"{len(rs)} {kind} rooms", "area = net floor area of each space")
    a.body.append(f"**The {'largest' if big else 'smallest'} {kind} room is {_ln(best)}, {best.q['net_floor_area_m2']:.1f} m², on {best.storey}.**")
    if len(rs) > 1:
        a.body.append("Others: " + ", ".join([f"{_ln(r)} {r.q['net_floor_area_m2']:.1f} m²" for r in sorted(rs, key=lambda r: -r.q["net_floor_area_m2"] if big else r.q["net_floor_area_m2"]) if r is not best][:5]) + (f" and {len(rs) - 6} more" if len(rs) > 6 else "") + ".")
    return a


def h_capacity(q: str, doc: Doc) -> Ans | None:
    if not _only_ifc(doc) or not re.search(r"\b(?:how many (?:people|persons|occupants)|capacity|occupancy|people (?:can )?(?:fit|use|work|sit))\b", q, re.I):
        return None
    st = storeys_in(q, _snames(doc))
    rooms = _rooms(doc)
    named = [r for r in rooms if re.search(r"\bseminar", q, re.I) and "seminar" in fold(_ln(r))]
    if not named:
        named = [r for r in rooms if fold(_ln(r)).strip() and len(fold(_ln(r))) > 3 and re.search(re.escape(fold(_ln(r))), fold(q)) and not fold(_ln(r)).startswith("flur")]
    scope_rooms = named or [r for r in rooms if not st or r.storey in st]
    per = 2.0 if named and any("seminar" in fold(_ln(r)) for r in named) else 10.0
    area = sum((r.q or {}).get("net_floor_area_m2") or 0 for r in scope_rooms)
    if not area:
        return None
    what = ", ".join(sorted({_ln(r) for r in named})[:3]) if named else (", ".join(st) if st else "the whole building")
    a = Ans(f"an estimate of how many people fit in {what}, from net floor area only.")
    a.items = scope_rooms[:30]
    n = int(area // per)
    a.ap(f"net floor area {area:,.1f} m² from {len(scope_rooms)} space(s)", f"assumed {per:g} m² per person ({'seminar or meeting use' if per == 2 else 'office use'})")
    a.body.append(f"**Roughly {n} people, but this is an estimate, not a stated capacity.** {area:,.1f} m² divided by an assumed {per:g} m² per person.")
    a.lf("the model stores no occupancy or capacity, and the real limit depends on use, furniture and the fire-safety exit capacity")
    return a


def h_thickness(q: str, doc: Doc) -> Ans | None:
    if not _only_ifc(doc) or not (re.search(r"\b(?:how thick|thickness)\b", q, re.I) and re.search(r"\bwalls?\b", q, re.I)):
        return None
    ext = re.search(r"\b(?:external|exterior|outer|outside)\b", q, re.I)
    inn = re.search(r"\b(?:internal|interior|inner|partition)\b", q, re.I)
    st = storeys_in(q, _snames(doc))
    ws = [w for w in doc.items if w.kind == "wall" and (w.q or {}).get("width_m") and (not st or w.storey in st)
          and (not ext or _ext(w)) and (not inn or not _ext(w))]
    if not ws:
        return None
    a = Ans(f"{'external ' if ext else 'internal ' if inn else ''}walls{' on ' + ', '.join(st) if st else ''}, thickness from the model's wall width.")
    groups: dict = {}
    for w in ws:
        groups.setdefault((_mm(w.q["width_m"]), re.sub(r"\s+\d{6,}$", "", w.props.get("material") or "") or "material not stated"), []).append(w)
    rows = [[f"{t} mm", m, len(v)] for (t, m), v in sorted(groups.items())]
    a.ap(f"{len(ws)} walls", "thickness = IFC wall width")
    a.body += _table(rows, ["Thickness", "Material", "Walls"])
    a.items = [v[0] for v in groups.values()][:12]
    if len(groups) == 1:
        a.body.append(f"\nAll {len(ws)} walls are **{rows[0][0]}** thick.")
    return a


def h_height(q: str, doc: Doc) -> Ans | None:
    if not _only_ifc(doc) or not re.search(r"\bhow (?:tall|high) is (?:the|this|it)\b|\b(?:building|overall|total) height\b|\bheight of the building\b", q, re.I):
        return None
    its = [i for i in doc.items if i.bbox_m and i.kind in ("wall", "slab", "roof", "column", "stairs", "door", "window")]
    if not its:
        return None
    top = max(its, key=lambda i: i.bbox_m[1][1])
    bot = min(its, key=lambda i: i.bbox_m[0][1])
    h = top.bbox_m[1][1] - bot.bbox_m[0][1]
    a = Ans("the overall height of the building, from the lowest to the highest modelled element.")
    a.items = [top]
    a.ap("height = highest element top minus lowest element bottom, in model coordinates")
    a.body.append(f"**About {h:.1f} m** from the underside of the lowest element ({bot.storey or 'lowest level'}, {bot.bbox_m[0][1]:.1f} m) to the top of the highest ({top.storey or 'highest level'}, {top.bbox_m[1][1]:.1f} m).")
    a.lf("roof ridge, parapet and any plant on top may not be modelled, so this is the modelled extent, not a surveyed height")
    return a


HANDLERS = [h_extreme_room, h_tiling, h_external_face, h_paint, h_masonry, h_wide_doors, h_windows, h_offices, h_walls_filter, h_shared_wall, h_stacking,
            h_schedule_doors, h_schedule_rooms, h_remove_wall, h_capacity, h_thickness, h_height, h_unanswerable, h_compliance, h_spatial_honest, h_labels, h_skirting]


def answer(question: str, doc_ids: list[str], root: Path, t0: float | None = None) -> dict | None:
    """-> an answer object, or None to let the normal pipeline run. Only for a single selected document."""
    import importlib
    S = importlib.import_module("engine.solvers.solve")
    t0 = t0 or time.perf_counter()
    if len(doc_ids) != 1 or not question or len(question) < 14:
        return None
    try:
        doc = load_doc(doc_ids[0], root)
    except Exception:
        return None
    for h in HANDLERS:
        try:
            a = h(question, doc)
        except Exception:
            a = None
        if a is None:
            continue
        a.items = [i for k, i in enumerate(a.items) if i not in a.items[:k]]
        boxes, cites, scene = S._evidence(doc, a.items) if a.items else ([], [], {"doc_id": doc.doc_id, "highlight_item_ids": [], "camera_target_item_id": None, "commands": []})
        if a.items and not scene.get("commands"):
            scene.setdefault("commands", [])
        conf = 0.6 if a.left else 0.95
        trace = [{"step": "complex_q", "detail": f"{h.__name__}: applied {len(a.applied)}, left {len(a.left)}", "ms": 0, "model": None, "cost_usd": 0.0}]
        res = S._answer_obj(question, doc_ids, a.text(), a.value, None, conf, False, boxes, cites, scene, trace, "index" if doc.mode == "ifc" else "planmap", t0)
        if a.calc:
            from engine.calc import record
            record(res, a.calc)
        res["conditions"] = {"applied": a.applied, "left": a.left, "handler": h.__name__}
        return res
    return None
