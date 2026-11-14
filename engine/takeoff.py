"""Multi-step take-off questions, e.g. "How many square metres of tiling should I order for the toilets?"

Steps (all code, cost 0): parse material + room class -> pick the matching rooms from the plan map / IFC (room names in
several languages) -> sum their areas -> apply a typical waste allowance, labelled as general guidance -> answer object with
one numbered citation per room (same numbers in 2D, 3D, AR).

  parse_takeoff(question) -> Takeoff | None
  takeoff_answer(question, docs: list[Doc], tk, t0) -> answer object
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass

from engine.solvers.data import Doc, Item

ROOM_CLASSES = {
    "toilet": (r"toilets?|wcs?|lavator\w+|restrooms?|washrooms?|water closets?|cloakrooms?|powder rooms?|aborte?s?|vessa|"
               r"toiletten?|toilettes?|wc-?tila|servizi|aseo|bagno di servizio|sanit[aä]r"),
    "bathroom": (r"bath(room)?s?|bad(ezimmer)?|b[aä]d|bain|bagno|ba[nñ]o|kylpyhuone|pesuhuone|washing room|shower rooms?|"
                 r"suihku|dusche|nasszelle|salle de bains?|sdb"),
    "kitchen": r"kitchens?|k[uü]che|cuisine|keitti[oö]|cucina|kitchenette|\bkk\b",
    "bedroom": r"bed ?rooms?|schlafzimmer|chambre|makuuhuone|\bmh\b|camera da letto|dormitorio",
    "living": r"living( room)?|wohnzimmer|s[eé]jour|olohuone|\boh\b|soggiorno|salon",
    "hall": r"halls?|corridors?|korridor|couloir|corridoio|k[aä]yt[aä]v[aä]|\bet\b|entry|entrance|gang",
    "balcony": r"balcon(y|ies)|balkon|balcon|parveke|loggia|terrace",
    "office": r"offices?|b[uü]ro|kontor|toimisto|working space",
    "storage": r"storage|stor(age)? rooms?|abstellraum|reduit|varasto|\bvar\b|closets?|wardrobes?",
    "garage": r"garages?|autotalli|carport",
    "sauna": r"saunas?",
}
CLASS_Q = {  # words in the question -> class
    "toilet": r"\b(toilets?|wcs?|lavator\w+|restrooms?|washrooms?|water closets?)\b",
    "bathroom": r"\b(bath ?rooms?|bathrooms?|shower rooms?|wet rooms?)\b",
    "kitchen": r"\bkitchens?\b", "bedroom": r"\bbed ?rooms?\b", "living": r"\bliving ?rooms?\b",
    "hall": r"\b(halls?|hallways?|corridors?)\b", "balcony": r"\b(balcon(y|ies)|terraces?)\b", "office": r"\boffices?\b",
    "storage": r"\b(storage|store ?rooms?)\b", "garage": r"\bgarages?\b", "sauna": r"\bsaunas?\b",
}
# material -> (label, waste fraction, note). Allowances are general trade guidance, never project facts.
MATERIALS = {
    "tile": ("floor tiles", 0.10, "10% waste is a common allowance for cuts and breakage (15% for diagonal or large-format layouts)"),
    "flooring": ("flooring", 0.07, "5-10% waste is a common allowance for cuts"),
    "carpet": ("carpet", 0.10, "about 10% waste is a common allowance for roll widths and pattern matching"),
    "screed": ("screed (floor area)", 0.05, "about 5% extra is a common allowance for uneven slabs"),
    "paint": ("ceiling paint coverage", 0.0, "assumes two coats at about 10 m2 per litre; check the product data sheet"),
}
MATERIAL_Q = [("tile", r"\b(tiles?|tiling|tiled|ceramic)\b"), ("carpet", r"\bcarpet\w*\b"),
              ("flooring", r"\b(flooring|laminate|vinyl|parquet|floor finish|floor covering)\b"), ("screed", r"\bscreed\b"),
              ("paint", r"\b(ceiling paint|paint(ing)?)\b")]
ASK = re.compile(r"\b(how (many|much)|what|total|estimate|calculate|need|order|buy|quantity|take-?off|amount)\b", re.I)
UNIT = re.compile(r"square met(re|er)s?|sq\.? ?m|m2|m²|area|floor space|surface", re.I)


@dataclass
class Takeoff:
    material: str | None     # key of MATERIALS, None = plain area sum
    room_class: str
    rx: re.Pattern
    wall: bool = False


def parse_takeoff(question: str) -> Takeoff | None:
    q = (question or "").casefold()
    cls = next((c for c, rx in CLASS_Q.items() if re.search(rx, q)), None)
    if cls is None or not ASK.search(q):
        return None
    mat = next((m for m, rx in MATERIAL_Q if re.search(rx, q)), None)
    if mat is None and not (UNIT.search(q) and re.search(r"\b(total|combined|all|sum)\b", q) and "how many rooms" not in q):
        return None
    if mat is None and re.search(r"\b(how many (toilets?|rooms?|bathrooms?)|number of)\b", q):
        return None
    wall = bool(re.search(r"\bwalls?\b", q)) and mat in ("tile", "paint")
    return Takeoff(mat, cls, re.compile(ROOM_CLASSES[cls], re.I), wall)


def _room_name(i: Item) -> str:
    p = i.props or {}
    return str(i.label or p.get("long_name") or p.get("room_type") or i.type_name or i.name or "").strip()


def _matches(i: Item, tk: Takeoff) -> bool:
    names = [i.label, (i.props or {}).get("long_name"), (i.props or {}).get("room_type"), i.type_name]
    for n in names:
        if n and re.fullmatch(rf"(?:{tk.rx.pattern})", str(n).strip(), re.I):
            return True
    for n in names:
        if n and len(str(n)) > 3 and re.search(rf"\b(?:{tk.rx.pattern})\b", str(n), re.I):
            return True
    return False


def _area(i: Item) -> float | None:
    for k in ("net_floor_area_m2", "area_m2"):
        v = (i.q or {}).get(k)
        if v is not None and float(v) > 0.3:      # near-zero IfcSpace areas are broken quantities
            return float(v)
    return None


def _tag_inside(room: Item, tags: list[Item]) -> Item | None:
    rb = room.bbox_px
    if not rb:
        return None
    for t in tags:
        if t.page == room.page and t.bbox_px:
            cx, cy = (t.bbox_px[0] + t.bbox_px[2]) / 2, (t.bbox_px[1] + t.bbox_px[3]) / 2
            if rb[0] <= cx <= rb[2] and rb[1] <= cy <= rb[3]:
                return t
    return None


def plan_geom(doc_id: str, root) -> dict:
    """IFC docs: room areas measured from the generated plan-map polygons x scale (exact geometry, not a guess)."""
    import json
    from pathlib import Path
    out = {}
    if root is None:
        return out
    for pf in sorted(Path(root, doc_id).glob("planmap-[0-9]*.json")):
        try:
            pm = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sc = pm.get("scale") or {}
        mpp = sc.get("m_per_px")
        if not mpp or (sc.get("confidence") or 0) < 0.8:
            continue
        for x in pm.get("items") or []:
            poly = x.get("polygon_px")
            if x.get("kind") == "room" and poly and len(poly) >= 3:
                a = abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2
                out[x["item_id"]] = (round(a * mpp * mpp, 2), pm.get("page", 1), x.get("bbox_px"))
    return out


def rooms_of(doc: Doc, tk: Takeoff) -> list[tuple[Item, float | None]]:
    """Rooms named like the class; on plan maps also unlabelled rooms that contain a matching printed text label (e.g. 'WC')."""
    tags = [i for i in doc.items if i.kind in ("text", "other") and i.label and re.search(rf"(?<![a-zäöüé])(?:{tk.rx.pattern})(?![a-zäöüé])", i.label.strip(), re.I)] \
        if doc.mode == "planmap" else []
    out = []
    for i in doc.items:
        if i.kind != "room":
            continue
        if _matches(i, tk):
            out.append((i, _area(i)))
        elif tags:
            t = _tag_inside(i, tags)
            if t is not None:
                if not i.label:
                    i.label = t.label.strip()
                out.append((i, _area(i)))
    return out


def _f(v: float) -> str:
    return f"{v:,.1f}"


def takeoff_answer(question: str, docs: list[Doc], tk: Takeoff, t0: float | None = None, title_of=None, root=None) -> dict:
    t0 = t0 or time.perf_counter()
    title_of = title_of or (lambda d: d.title or d.doc_id)
    mat = MATERIALS.get(tk.material or "")
    cls = tk.room_class
    trace = [{"step": "takeoff", "detail": f"{tk.material or 'area'} for {cls} rooms across {len(docs)} document(s)", "ms": 0,
              "model": None, "cost_usd": 0}]
    cites, boxes, lines, ids_by_doc = [], [], [], {}
    calc_rows = []
    total, n_rooms, missing, low_conf, geom_used = 0.0, 0, 0, False, False
    doc_lines = []
    for doc in docs:
        found = rooms_of(doc, tk)
        if not found:
            continue
        sub, parts = 0.0, []
        scale_conf = (doc.scale or {}).get("confidence") if doc.mode == "planmap" else None
        if scale_conf is not None and scale_conf < 0.5 and any(a for _, a in found if a is not None):
            low_conf = True
        geom = plan_geom(doc.doc_id, root) if doc.mode == "ifc" and any(a is None for _, a in found) else {}
        for it, a in sorted(found, key=lambda t: (t[0].storey or "", _room_name(t[0]))):
            page_, bbox_ = it.page, it.bbox_px
            if a is None and it.item_id in geom:
                a, page_, bbox_ = geom[it.item_id]
                geom_used = True
            if a is None:
                missing += 1
                continue
            n = len(cites) + 1
            nm = _room_name(it) or it.item_id
            if len(cites) < 30:
                if bbox_:
                    cites.append({"n": n, "doc_id": doc.doc_id, "page": page_, "kind": "region", "bbox_px": bbox_,
                                  "item_ids": [it.item_id], "quote": f"{nm}: {_f(a)} m2"})
                    boxes.append({"item_id": it.item_id, "page": page_, "bbox_px": bbox_, "label": str(n)})
                else:
                    cites.append({"n": n, "doc_id": doc.doc_id, "page": 1, "kind": "element", "bbox_px": None,
                                  "item_ids": [it.item_id], "quote": f"{nm}: {_f(a)} m2"})
            else:
                n = None
            sub += a
            from engine.calc import row
            calc_rows.append(row(doc, it, a, "m2"))
            n_rooms += 1
            ids_by_doc.setdefault(doc.doc_id, []).append(it.item_id)
            parts.append(f"{nm}{' (' + it.storey + ')' if it.storey else ''} {_f(a)} m² " + (f"[{n}]" if n else ""))
        if parts:
            total += sub
            doc_lines.append((doc, sub, parts))
    if n_rooms == 0:
        names = ", ".join(title_of(d) for d in docs[:3])
        why = "none of the rooms named like that has an area in the drawing data" if missing else "no room is named like that"
        trace.append({"step": "abstain", "detail": why, "ms": 0, "model": None, "cost_usd": 0})
        text = (f"I looked for {cls} rooms in {names} and {why}, so I cannot work out a quantity. "
                "If the rooms are unlabelled, select the drawing and point me at them.")
        return _out(question, docs[:1], text, None, "m2", 0.0, [], [], trace, t0, abstained=True, ids=[])
    label = (mat[0] if mat else "floor area")
    formula = f"{_f(total)} m² of {cls} floor"
    if mat:
        waste = mat[1]
        if tk.material == "paint":
            need = total * 2 / 10
            value, unit = round(need, 1), "litre"
            head = f"**About {_f(need)} litres of ceiling paint** for the {cls} rooms (floor area {_f(total)} m²) [{1}]"
            calc = f"Formula: ceiling area ≈ floor area × coats ÷ coverage = {_f(total)} × 2 ÷ 10 = {_f(need)} litres."
        else:
            need = total * (1 + waste)
            value, unit = round(need, 1), "m2"
            head = f"**Order about {_f(need)} m² of {mat[0]}** for the {cls} rooms [1]"
            calc = (f"Formula: floor area × (1 + waste) = {_f(total)} × {1 + waste:.2f} = {_f(need)} m². "
                    f"The {waste * 100:.0f}% waste is general guidance, not a project fact: {mat[2]}.")
        if tk.wall:
            calc += (" Wall tiling is not included: it needs room perimeters and the tiled height, which the drawing data "
                     "does not give reliably. Tell me the tiled height and I can add it.")
    else:
        value, unit = round(total, 1), "m2"
        head = f"**The {cls} rooms add up to {_f(total)} m²** [1]"
        calc = "Formula: sum of the room areas listed below."
    head = head.replace("[1]", "".join(f"[{c['n']}]" for c in cites[:8]))
    body = [f"{len(doc_lines)} document(s), {n_rooms} room(s) counted, {_f(total)} m² net floor area:"]
    for doc, sub, parts in doc_lines:
        body.append(f"- **{title_of(doc)}** ({_f(sub)} m²): " + "; ".join(parts))
    notes = []
    if missing:
        notes.append(f"{missing} matching room(s) have no area in the data and are left out.")
    if low_conf:
        notes.append("The drawing scale is estimated (no printed dimensions), so treat the areas as approximate.")
    if geom_used:
        notes.append("The model stores no room areas, so these are measured from the room outlines on the generated plan.")
    if len({d.doc_id for d, _, _ in doc_lines}) > 1:
        notes.append("Several documents matched; each room is counted once per document.")
    text = head + "\n\n" + calc + "\n\n" + "\n".join(body) + ("\n\n" + " ".join(notes) if notes else "")
    ids = [i for v in ids_by_doc.values() for i in v]
    main_doc = doc_lines[0][0]
    res = _out(question, [d for d, _, _ in doc_lines], text, value, unit, 0.55 if low_conf else 0.85, cites, boxes, trace, t0,
               ids=ids_by_doc.get(main_doc.doc_id, []))
    from engine.calc import assumption_source
    from engine.calc_routes import allowance
    return allowance(res, calc_rows, mat[1] * 100 if mat else 0,
                     assumption_source(mat[2] if mat else "No waste allowance applied"), paint=tk.material == "paint")


def _out(question, docs, text, value, unit, conf, cites, boxes, trace, t0, abstained=False, ids=()):
    d0 = docs[0].doc_id if docs else ""
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [d.doc_id for d in docs],
        "answer": {"text_md": text, "value": value, "unit": unit, "confidence": conf, "abstained": abstained},
        "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": d0, "highlight_item_ids": list(ids)[:400],
                                                                   "camera_target_item_id": (list(ids)[0] if ids else None)}},
        "trace": trace, "route": "planmap" if (docs and docs[0].mode == "planmap") else "index",
        "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
