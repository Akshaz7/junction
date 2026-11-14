"""JUDGE-QA: harder question shapes that are still plain code over the plan map / IFC elements ($0, no model).

  storey_compare   "which floor has the most doors", "which storey has the largest room area", "windows per floor"
  total_and_storey "how many windows in total and how many on the 2nd floor"
  cond_count       "how many doors are wider than 1 m / at least 900 mm"
  takeoff          "how many m2 of tiles for all the WCs including 10% waste" (area of the named rooms x (1 + waste))
  named_rooms      "how many offices", "area of the kitchens", "how many Zimmer rooms and their total area"
  compliance       "does the corridor meet the accessibility width", "is the building still compliant" (findings + advisor)

Every handler returns None when it is not sure the question is its shape, so the existing route runs unchanged."""
from __future__ import annotations

import re
import time

from engine.router.parser import _kind
from engine.solvers.data import Doc, Item
from engine.solvers.solve import MIN_CONF, _answer_obj, _evidence, _qty, _step, resolve_storey

MORE = re.compile(r"\b(most|greatest|largest|biggest|highest|maximum|max)\b", re.I)
LESS = re.compile(r"\b(fewest|least|smallest|lowest|minimum|min)\b", re.I)
AREAQ = re.compile(r"\b(area|areas|m2|m²|square met(?:er|re)s|sq\.? ?m|floor space|size)\b", re.I)
PLURAL = {"door": "doors", "window": "windows", "room": "rooms", "wall": "walls", "stairs": "stairs", "column": "columns",
          "slab": "slabs", "railing": "railings", "furniture": "furniture items", "toilet": "toilets", "sink": "sinks"}


def _noun(kind: str, n: int = 2) -> str:
    base = PLURAL.get(kind, kind + "s")
    return base if n != 1 else (base[:-1] if base.endswith("s") and kind != "stairs" else base)


def _of_kind(doc: Doc, kind: str) -> list[Item]:
    its = [i for i in doc.items if i.kind == kind]
    if doc.mode == "planmap":
        its = [i for i in its if i.conf >= MIN_CONF]
    return [i for i in its if i.props.get("ifc_class") != "IfcStairFlight"]


def _fmt(v: float) -> str:
    return f"{v:,.1f}" if abs(v) >= 10 else f"{v:,.2f}"


def _done(question, doc, text, value, unit, items, trace, route="analytics", t0=None):
    boxes, cites, scene = _evidence(doc, items)
    route = "index" if doc.mode == "ifc" else "planmap"  # answer.schema.json route enum has no "analytics"
    marks = "".join(f"[{c['n']}]" for c in cites)
    return _answer_obj(question, [doc.doc_id], text.replace("{marks}", marks), value, unit, 1.0 if doc.mode == "ifc" else 0.85, False,
                       boxes, cites, scene, trace, route, t0 or time.perf_counter())


# ------------------------------------------------------------------ storey comparisons
def storey_compare(question: str, doc: Doc, t0) -> dict | None:
    if doc.mode != "ifc" or len(doc.storeys) < 2:
        return None
    m = re.search(r"\b(?:which|what)\s+(?:floor|storey|story|level)\b", question, re.I)
    per = re.search(r"\b(?:per|on each|for each|by|every)\s+(?:floor|storey|story|level)\b|\beach (?:floor|storey|level)\b", question, re.I)
    if not (m or per) or not re.search(r"\bhow many\b|\bnumber of\b|" + MORE.pattern + "|" + LESS.pattern, question, re.I):
        return None
    area = bool(AREAQ.search(question))
    kind = _kind(re.sub(r"\b(?:floors?|storeys?|stories|levels?)\b", " ", question.lower())) or ("room" if area else None)
    if kind is None or kind == "storey":
        return None
    items = _of_kind(doc, kind)
    by: dict[str, list[Item]] = {}
    for s in doc.storeys:
        by[s["name"]] = []
    for i in items:
        if i.storey in by:
            by[i.storey].append(i)
    if area:
        score = {k: round(sum(v for v in (_qty(i, kind, "area") for i in its) if v), 2) for k, its in by.items()}
    else:
        score = {k: len(its) for k, its in by.items()}
    if not any(score.values()):
        return None
    order = [s["name"] for s in sorted(doc.storeys, key=lambda s: s.get("elevation_m", 0))]
    unit = "m²" if area else ""
    parts = ", ".join(f"{k} {_fmt(score[k]) if area else score[k]}{(' ' + unit) if unit else ''}" for k in order if k in score)
    what = f"total {kind} area" if area else _noun(kind)
    trace = [_step("route", f"storey comparison / {kind} / {'area' if area else 'count'} -> code, no model"),
             _step("count", parts)]
    if m:
        pick = min(score, key=score.get) if LESS.search(question) and not MORE.search(question) else max(score, key=score.get)
        best = score[pick]
        ties = [k for k in order if score[k] == best]
        word = "fewest" if LESS.search(question) and not MORE.search(question) else "most"
        lead = (f"**{pick}** has the {word} {what if not area else what}: **{_fmt(best) + ' m²' if area else best}**."
                if len(ties) == 1 else f"**{' and '.join(ties)}** tie for the {word} {what}: **{_fmt(best) + ' m²' if area else best}** each.")
        text = f"{lead} Per floor: {parts}. {{marks}}"
        return _done(question, doc, text, best, "m2" if area else "count", by[pick] if len(ties) == 1 else [i for k in ties for i in by[k]], trace, t0=t0)
    text = f"{_noun(kind).capitalize()} per floor{' (area)' if area else ''}: {parts}. {{marks}}"
    return _done(question, doc, text, sum(score.values()), "m2" if area else "count", items, trace, t0=t0)


def total_and_storey(question: str, doc: Doc, t0) -> dict | None:
    if doc.mode != "ifc" or not re.search(r"\bhow many\b", question, re.I):
        return None
    if not re.search(r"\b(?:in total|overall|altogether|in the (?:whole )?building|in the model|total)\b", question, re.I):
        return None
    if not re.search(r"\band (?:how many|the number)\b|\band (?:on|in)\b", question, re.I):
        return None
    st = resolve_storey(question, doc.storeys)
    kind = _kind(question.lower())
    if not st or not kind:
        return None
    items = _of_kind(doc, kind)
    on = [i for i in items if i.storey == st]
    trace = [_step("route", f"count / {kind} / total + storey -> code, no model"), _step("count", f"{len(items)} total, {len(on)} on {st}")]
    text = f"There are **{len(items)} {_noun(kind, len(items))}** in total in this model and **{len(on)}** on **{st}**. {{marks}}"
    return _done(question, doc, text, len(items), "count", on or items, trace, t0=t0)



# ------------------------------------------------------------------ named storey pairs, kind pairs, exact sizes
ORD_RE = re.compile(r"\b(ground|first|1st|second|2nd|third|3rd|fourth|4th|fifth)\b(?=[^.?]*\b(?:floors?|levels?|storeys?|stories)\b)|\b(basement|cellar|top floor)\b", re.I)
CMP = re.compile(r"\b(compare|comparison|versus|vs\.?|difference|differ|more|fewer|less|than|against|between)\b", re.I)


def _storeys_named(question: str, doc: Doc) -> list[str]:
    found: list[tuple[int, str]] = []
    ql = question.lower()
    for s in doc.storeys:
        i = ql.find(s["name"].lower())
        if i >= 0:
            found.append((i, s["name"]))
    for m in ORD_RE.finditer(question):
        txt = m.group(0).lower()
        nm = resolve_storey(txt if " " in txt else txt + " floor", doc.storeys)
        if nm:
            found.append((m.start(), nm))
    out: list[str] = []
    for _, nm in sorted(found):
        if nm not in out:
            out.append(nm)
    return out


def storey_pair(question: str, doc: Doc, t0) -> dict | None:
    """"compare doors on the 1st vs 2nd floor": one count per named storey, with the difference."""
    if doc.mode != "ifc" or len(doc.storeys) < 2 or not CMP.search(question):
        return None
    names = _storeys_named(question, doc)
    if len(names) < 2:
        return None
    area = bool(AREAQ.search(question))
    kind = _kind(re.sub(r"\b(?:floors?|storeys?|stories|levels?)\b", " ", question.lower())) or ("room" if area else None)
    if kind is None or kind == "storey":
        return None
    items = [i for i in _of_kind(doc, kind) if i.storey in names]
    score = {n: (round(sum(v for v in (_qty(i, kind, "area") for i in items if i.storey == n) if v), 2) if area
                 else sum(1 for i in items if i.storey == n)) for n in names}
    u = " m²" if area else ""
    fmt = (lambda v: _fmt(v)) if area else (lambda v: str(v))
    parts = "; ".join(f"**{n}**: {fmt(score[n])}{u}" for n in names)
    hi = max(score, key=score.get)
    lo = min(score, key=score.get)
    if score[hi] == score[lo]:
        verdict = "They are equal."
    else:
        verdict = f"**{hi}** has more ({fmt(score[hi])}{u} vs {fmt(score[lo])}{u}, a difference of {fmt(round(score[hi] - score[lo], 2))}{u})."
    what = f"{kind} area" if area else _noun(kind)
    trace = [_step("route", f"storey pair / {kind} / {'area' if area else 'count'} -> code, no model"), _step("count", parts)]
    text = f"Total {what} per floor: {parts}. {verdict} {{marks}}"
    return _done(question, doc, text, score[hi] - score[lo], "m2" if area else "count", items, trace, t0=t0)


KIND_SPLIT = re.compile(r"\s+(?:or|than|vs\.?|versus|and)\s+", re.I)


def kind_compare(question: str, doc: Doc, t0) -> dict | None:
    """"are there more windows or doors": count both kinds, say which is more."""
    ql = question.lower()
    if not re.search(r"\b(more|fewer|less|compare|comparison|versus|vs)\b", ql) or re.search(r"\b(floor|storey|level)s?\b", ql):
        return None
    if re.search(r"\bhow many\b.*\band\b", ql) and not re.search(r"\bmore|fewer|less\b", ql):
        return None
    body = re.sub(r"\b(are there|is there|there are|which|what|has|have|does|do|the|this|plan|floor|building|model|drawing|compare|comparison|of|more|fewer|less|many|between|number)\b", " ", ql)
    sides = [x for x in KIND_SPLIT.split(body) if x.strip()]
    kinds: list[str] = []
    for side in sides:
        k = _kind(side)
        if k and k not in kinds and k != "storey":
            kinds.append(k)
    if len(kinds) != 2:
        return None
    counts = {k: _of_kind(doc, k) for k in kinds}
    a, b = kinds
    na, nb = len(counts[a]), len(counts[b])
    if not (na or nb):
        return None
    if na == nb:
        verdict = f"There are equally many: **{na}** of each."
    else:
        hi, lo = (a, b) if na > nb else (b, a)
        verdict = f"There are more **{_noun(hi)}**: **{max(na, nb)}** {_noun(hi)} vs **{min(na, nb)}** {_noun(lo)}."
    trace = [_step("route", f"kind comparison / {a} vs {b} -> code, no model"), _step("count", f"{na} {_noun(a)}, {nb} {_noun(b)}")]
    return _done(question, doc, f"{verdict} {{marks}}", abs(na - nb), "count", counts[a] + counts[b], trace, t0=t0)


EXACT = re.compile(r"\bhow many\s+(?:of the\s+)?(?:\w+\s+)?(doors?|windows?)\b.*?\b(?:are|is|have|with|measuring|measure)?\s*(?:a\s+)?(?:width|height|clear width)?\s*(?:of\s+)?(?:exactly\s+|about\s+|around\s+)?(\d+(?:[.,]\d+)?)\s*(mm|cm|m|metres?|meters?)\s*(wide|high|tall|in width|in height)\b", re.I)


def exact_size(question: str, doc: Doc, t0) -> dict | None:
    """"how many doors are 1.8 m wide": equality within 2.5 cm (a bare size is a match, not a threshold)."""
    m = EXACT.search(question)
    if not m or COND.search(question):
        return None
    kind = "door" if m.group(1).lower().startswith("door") else "window"
    val = float(m.group(2).replace(",", "."))
    unit = m.group(3).lower()
    metres = val / 1000 if unit == "mm" else val / 100 if unit == "cm" else val
    height = m.group(4).lower() in ("high", "tall", "in height")
    key = "height_m" if height else "width_m"
    items = _of_kind(doc, kind)
    st = resolve_storey(question, doc.storeys) if doc.mode == "ifc" else None
    if st:
        items = [i for i in items if i.storey == st]
    known = [(i, i.q.get(key)) for i in items if i.q.get(key) is not None]
    if not known:
        return None
    tol = 0.025
    hit = [i for i, v in known if abs(float(v) - metres) <= tol]
    vals = sorted({round(float(v), 2) for _, v in known})
    where = f"on **{st}**" if st else ("in this model" if doc.mode == "ifc" else "on this floor plan")
    skipped = len(items) - len(known)
    note = f" ({skipped} {_noun(kind, skipped)} have no {'height' if height else 'width'} in the data.)" if skipped else ""
    dist = (" Sizes in the model: " + ", ".join(f"{v:g} m" for v in vals) + ".") if 1 < len(vals) <= 8 else ""
    trace = [_step("route", f"count / {kind} / exactly {val:g}{unit} {'high' if height else 'wide'} -> code, no model"), _step("filter", f"{len(hit)} of {len(known)}")]
    text = f"**{len(hit)} {_noun(kind, len(hit))}** {where} {'is' if len(hit) == 1 else 'are'} **{val:g} {unit}** {'high' if height else 'wide'} (within 2.5 cm).{dist}{note} {{marks}}"
    return _done(question, doc, text, len(hit), "count", hit, trace, t0=t0)


# ------------------------------------------------------------------ conditional counts
COND = re.compile(
    r"\bhow many\s+(?:of the\s+)?(?:\w+\s+)?(doors?|windows?)\b.*?\b"
    r"(wider|larger|bigger|taller|higher|narrower|smaller|shorter|lower|more than|less than|at least|at most|over|under|above|below|exceed(?:ing|s)?|greater than|bigger than|wider than|narrower than)"
    r"\s*(?:than\s+)?(?:a\s+)?(?:width|height|clear width)?\s*(?:of\s+)?(\d+(?:[.,]\d+)?)\s*(mm|cm|m|metres?|meters?)\b", re.I)


def cond_count(question: str, doc: Doc, t0) -> dict | None:
    m = COND.search(question)
    if not m:
        return None
    kind = "door" if m.group(1).lower().startswith("door") else "window"
    op = m.group(2).lower()
    val = float(m.group(3).replace(",", "."))
    unit = m.group(4).lower()
    metres = val / 1000 if unit == "mm" else val / 100 if unit == "cm" else val
    height = bool(re.search(r"\b(taller|higher|shorter|lower|height|high|tall)\b", question, re.I)) and not re.search(r"\bwid", question, re.I)
    if op in ("lower", "shorter") and not height:
        height = True
    gt = op in ("wider", "larger", "bigger", "taller", "higher", "more than", "over", "above", "greater than", "bigger than", "wider than", "exceeding", "exceeds", "exceed") or op.startswith("exceed")
    ge = op == "at least"
    le = op == "at most"
    key = "height_m" if height else "width_m"
    items = _of_kind(doc, kind)
    st = resolve_storey(question, doc.storeys) if doc.mode == "ifc" else None
    if st:
        items = [i for i in items if i.storey == st]

    def meas(i: Item):
        v = i.q.get(key)
        if v is None and doc.mode == "planmap" and key == "width_m":
            v = i.props.get("leaf_len_m") or i.props.get("width_m")
        return None if v is None else float(v)
    have = [(i, meas(i)) for i in items]
    known = [(i, v) for i, v in have if v is not None]
    if not known:
        return None
    eps = 1e-6
    hit = [i for i, v in known if (v > metres + eps if gt else v >= metres - eps if ge else v <= metres + eps if le else v < metres - eps)]
    opw = {True: "wider than" if not height else "taller than"}.get(gt) or ("at least" if ge else "at most" if le else "narrower than" if not height else "lower than")
    where = f"on **{st}**" if st else ("in this model" if doc.mode == "ifc" else "on this floor plan")
    skipped = len(have) - len(known)
    note = f" ({skipped} {_noun(kind, skipped)} have no {'height' if height else 'width'} in the data and are not counted.)" if skipped else ""
    dist = ""
    vals = sorted({round(v, 2) for _, v in known})
    if doc.mode == "ifc" and 1 < len(vals) <= 6:
        dist = " Widths in the model: " + ", ".join(f"{v:g} m" for v in vals) + "." if not height else ""
    trace = [_step("route", f"count / {kind} / condition {opw} {val:g}{unit} -> code, no model"), _step("filter", f"{len(hit)} of {len(known)} {kind}s {opw} {metres:g} m")]
    src = " (door swing length as the width)" if doc.mode == "planmap" and not any(i.q.get(key) for i in items) else ""
    text = (f"**{len(hit)} of {len(known)} {_noun(kind)}** {where} are {opw} **{val:g} {unit}**{src}.{dist}{note} {{marks}}")
    return _done(question, doc, text, len(hit), "count", hit, trace, t0=t0)


# ------------------------------------------------------------------ rooms by name (synonyms, other languages)
SYN = {
    "office": r"b[uü]e?ro|office|toimisto|arbeits",
    "kitchen": r"k[uü]e?che|kitchen|keitti",
    "storage": r"lager|storage|varasto|abstell|reduit",
    "corridor": r"flur|korridor|corridor|k[aä]yt[aä]v",
    "bathroom": r"bad\b|bath|kylpy|wc|toilet",
}
SYN_ALIAS = {"offices": "office", "kitchens": "kitchen", "corridors": "corridor", "hallways": "corridor", "storerooms": "storage"}


def _room_label(r: Item) -> str:
    return f"{r.props.get('long_name') or ''} {r.label or ''} {r.name or ''} {r.props.get('room_type') or ''}".strip()


def named_rooms(question: str, doc: Doc, t0) -> dict | None:
    ql = question.lower()
    howmany = re.search(r"\bhow many\b|\bnumber of\b", ql)
    wants_area = AREAQ.search(ql)
    if not howmany and not wants_area:
        return None
    word = None
    rx = None
    for a, base in list(SYN_ALIAS.items()) + [(k, k) for k in SYN]:
        if re.search(rf"\b{a}\b", ql):
            word, rx = base, re.compile(SYN[base], re.I)
            break
    if word is None:
        m = re.search(r"\b(?:how many|number of|area of|areas of)\s+(?:the\s+|all\s+|all the\s+)?([a-zäöüß][\wäöüß.\-]{2,})\s+(?:rooms?|spaces?|areas?)\b", question, re.I)
        if not m or _kind(m.group(1).lower()) or m.group(1).lower() in ("total", "many", "much", "these", "those", "different"):
            return None
        word = m.group(1)
        rx = re.compile(re.escape(word), re.I)
    others = re.findall(r"\b(living|bedrooms?|bathrooms?|toilets?|wc|balcon\w+|terrace|hall|entry)\b", ql)
    if others and not re.search(rx.pattern, " ".join(others), re.I) and re.search(r"\band\b|,", ql):
        return None   # "the living room and kitchen": a mix the room solver handles
    rooms = _of_kind(doc, "room")
    st = resolve_storey(question, doc.storeys) if doc.mode == "ifc" else None
    if st:
        rooms = [r for r in rooms if r.storey == st]
    hit = [r for r in rooms if rx.search(_room_label(r))]
    if not hit:
        return None
    vals = [_qty(r, "room", "area") for r in hit]
    tot = round(sum(v for v in vals if v), 2)
    where = f"on **{st}**" if st else ("in this model" if doc.mode == "ifc" else "on this floor plan")
    trace = [_step("route", f"count / room / named '{word}' -> code, no model"), _step("filter", f"{len(hit)} rooms match {word}")]
    plural = word + ("s" if not word.endswith("s") else "")
    noun = {"office": "offices", "kitchen": "kitchens", "storage": "storage rooms", "corridor": "corridors", "bathroom": "bathrooms/WCs"}.get(word, f"{word} rooms")
    if wants_area and (not howmany or re.search(r"\b(total|combined|sum)\b", ql)) or (wants_area and howmany):
        per = "; ".join(f"{(r.props.get('long_name') or r.label or r.name or r.item_id)} {_fmt(v)} m²" for r, v in sorted(zip(hit, vals), key=lambda t: -(t[1] or 0))[:8] if v)
        lead = f"There {'is' if len(hit) == 1 else 'are'} **{len(hit)} {noun}** {where} with a total area of **{_fmt(tot)} m²**." if howmany else \
               f"The total area of the **{len(hit)} {noun}** {where} is **{_fmt(tot)} m²**."
        text = f"{lead}" + (f" Largest: {per}." if len(hit) > 1 else "") + " {marks}"
        return _done(question, doc, text, tot if not howmany else len(hit), "m2" if not howmany else "count", hit, trace, t0=t0)
    text = f"There {'is' if len(hit) == 1 else 'are'} **{len(hit)} {noun}** {where}. {{marks}}"
    return _done(question, doc, text, len(hit), "count", hit, trace, t0=t0)


# ------------------------------------------------------------------ "where is the kitchen" on plan maps (labels from the drawing)
WHERE = re.compile(r"^\W*(?:please\s+)?(?:where(?:'s| is| are| can i find)?|find|locate|show(?: me)?|point (?:to|out))\b", re.I)
WSYN = {**SYN, "bedroom": r"zimmer|schlaf|bedroom|makuu|\bmh\b|\bsh\b|\bk\d?\b", "living room": r"wohn|living|oleskelu|\bol\b|stube",
        "balcony": r"balkon|balcon|parveke|loggia", "terrace": r"terrass|terassi|terrace", "hall": r"entr[eé]e|\bhall\b|eteinen|\bet\b|diele"}
WALIAS = {"bathrooms": "bathroom", "toilets": "bathroom", "toilet": "bathroom", "wcs": "bathroom", "wc": "bathroom", "bedrooms": "bedroom",
          "kitchens": "kitchen", "offices": "office", "balconies": "balcony", "terraces": "terrace", "corridors": "corridor",
          "hallway": "corridor", "hallways": "corridor", "living": "living room"}


def where_rooms(question: str, doc: Doc, t0) -> dict | None:
    """"where is the kitchen / are the bathrooms" on a plan map: rooms whose drawn label matches. None when nothing is labelled that way."""
    if doc.mode != "planmap" or not WHERE.search(question) or re.search(r"\bhow many\b", question, re.I):
        return None
    ql = question.lower()
    word = None
    for a, base in list(WALIAS.items()) + [(k, k) for k in WSYN]:
        if re.search(rf"\b{re.escape(a)}\b", ql):
            word = base
            break
    if word is None:
        return None
    rx = re.compile(WSYN[word], re.I)
    hit = [r for r in _of_kind(doc, "room") if r.bbox_px and rx.search(_room_label(r))]
    if not hit:
        return None
    vals = [_qty(r, "room", "area") for r in hit]
    noun = {"bathroom": "bathroom/WC", "living room": "living room"}.get(word, word)
    labels = sorted({(r.props.get("long_name") or r.label or "").strip() for r in hit if (r.props.get("long_name") or r.label)})
    where = f" (drawn as {', '.join(labels[:4])})" if labels else ""
    area = [v for v in vals if v]
    extra = f" Total area **{_fmt(sum(area))} m²**." if area else ""
    trace = [_step("route", f"locate / room / '{word}' from drawn labels -> code, no model"), _step("filter", f"{len(hit)} rooms match {word}")]
    text = f"**{len(hit)} {noun}{'s' if len(hit) != 1 else ''}** on this floor plan{where}, numbered on the drawing.{extra} {{marks}}"
    return _done(question, doc, text, len(hit), "count", hit, trace, t0=t0)


# ------------------------------------------------------------------ material take-off with waste
TAKEOFF = re.compile(r"\b(?:how (?:many|much)|calculate|work out|estimate)\b.*\b(?:m2|m²|sq\.? ?m|square met(?:er|re)s)\b|\bhow much\b.*\b(?:tiles?|flooring|floor covering|paint|carpet|laminate|parquet|screed|plaster)\b", re.I)
WASTE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent)\s*(?:extra|waste|wastage|overage|spare|allowance|margin|buffer|more|on top|added)?|(?:waste|wastage|overage|allowance|margin)\s*(?:of)?\s*(\d+(?:[.,]\d+)?)\s*(?:%|percent)", re.I)


def takeoff(question: str, doc: Doc, t0, solve_fn) -> dict | None:
    if not TAKEOFF.search(question) or not re.search(r"\bfor\b", question, re.I):
        return None
    wm = WASTE.search(question)
    pct = float((wm.group(1) or wm.group(2)).replace(",", ".")) if wm else 0.0
    mm = re.search(r"\bfor\s+(?:all\s+(?:of\s+)?)?(?:the\s+)?(.+?)\s*(?:,|\.|\?|$|\b(?:including|incl\.?|with|plus|and|allowing|add|adding|\+)\s*(?:an?\s+)?(?:\d|extra|waste|wastage))", question, re.I)
    if not mm:
        return None
    target = mm.group(1).strip(" ?.")
    if not target or len(target) > 60:
        return None
    parts = [x.strip() for x in re.split(r"\s*(?:,|\band\b|&)\s*", target) if x.strip()]
    parts = [re.sub(r"^(?:the|all|all the)\s+", "", x, flags=re.I) for x in parts]
    base, total = None, 0.0
    for part in parts or [target]:
        try:
            r = solve_fn(f"What is the total floor area of the {part}?")
        except Exception:
            return None
        if r is None or r["answer"].get("abstained") or not isinstance(r["answer"].get("value"), (int, float)):
            return None
        total += float(r["answer"]["value"])
        if base is None:
            base = r
        else:
            base["citations"] = (base.get("citations") or []) + [dict(c, n=len(base.get("citations") or []) + 1) for c in r.get("citations") or []]
            base["evidence"]["boxes"] = (base["evidence"].get("boxes") or []) + (r["evidence"].get("boxes") or [])
            base["trace"] = base["trace"] + r["trace"]
            sc, sr = base["evidence"]["scene"], r["evidence"]["scene"]
            sc["highlight_item_ids"] = list(dict.fromkeys((sc.get("highlight_item_ids") or []) + (sr.get("highlight_item_ids") or [])))
    area = total
    need = area * (1 + pct / 100)
    trace = base["trace"] + [_step("compute", f"{area:.2f} m2 x (1 + {pct:g}%) = {need:.2f} m2")]
    txt = (f"You need about **{_fmt(need)} m²**: the {target} cover **{_fmt(area)} m²**" +
           (f", plus **{pct:g}%** waste ({_fmt(need - area)} m²)." if pct else "."))
    marks = "".join(f"[{c['n']}]" for c in base.get("citations") or [])
    base["answer"].update({"text_md": f"{txt} {marks}", "value": round(need, 2), "unit": "m2"})
    base["trace"] = trace
    return base


# ------------------------------------------------------------------ rules and compliance
COMPLY = re.compile(r"\b(?:(?:wide|high|tall|big|large|long|steep|safe|accessible) enough|adequate|sufficient|required|requirements?|meet|meets|comply|complies|compliant|compliance|satisf(?:y|ies)|conform(?:s)?|pass(?:es)?|up to code|legal|allowed by|according to (?:the )?(?:rules|code))\b", re.I)
TOPIC = [
    ("fi-fire-", re.compile(r"\b(?:fire|exits?|escape|evacuat\w+|egress|848)\b", re.I), "fire safety (848/2017)"),
    ("fi-acc-", re.compile(r"\b(?:accessib\w+|wheelchair|barrier[- ]free|ramp|corridor|turning|clear width|241|disab\w+|entrance)\b", re.I), "accessibility (241/2017)"),
    ("fi-use-", re.compile(r"\b(?:stairs?|staircase|railing|barrier|guard|headroom|riser|tread|landing|1007|safety in use)\b", re.I), "safety in use (1007/2017)"),
]


SPECIFIC = [
    (r"\bstairs?\b.*\b(?:wide|width)\b|\b(?:wide|width)\b.*\bstairs?\b", ("fi-use-stair-width",)),
    (r"\b(?:riser|tread)s?\b", ("fi-use-stair-dwelling-riser-tread", "fi-use-stair-exit-riser-tread")),
    (r"\bheadroom\b|\bclear height\b", ("fi-use-headroom",)),
    (r"\blandings?\b", ("fi-use-door-landing",)),
    (r"\b(?:barriers?|railings?|guards?)\b", ("fi-use-barrier-height",)),
    (r"\bemergency[- ](?:exit )?(?:window|hatch)", ("fi-use-emergency-window",)),
]


def wants_compliance(question: str) -> bool:
    if re.search(r"\bstill\b.*\b(?:exits?|escape|way out|egress|route|compliant|ok|okay|allowed|legal|safe|accessible)\b", question, re.I):
        return True
    return bool(COMPLY.search(question) or re.search(r"\b(?:still )?(?:ok|okay|fine|safe|legal|valid)\b", question, re.I) and re.search(r"\b(?:rules?|code|regulation|fire|exit|accessib)\w*", question, re.I))


def compliance(question: str, doc: Doc, t0) -> dict | None:
    if not COMPLY.search(question):
        return None
    pick = [(p, label) for p, rx, label in TOPIC if rx.search(question)]
    if not pick:
        return None
    if doc.mode != "ifc":
        # raster / DXF plans carry widths only: say what cannot be checked instead of a silent pass
        trace = [_step("route", "rule check / plan map -> no automatic check")]
        text = ("**Checks need an IFC model.** This is a plan map: it has door and room positions and widths but no heights, stair or exit data, "
                f"so I cannot check {' and '.join(l for _, l in pick)} on it. Upload or open the IFC model for a rule check.")
        res = _done(question, doc, text, None, None, [], trace, t0=t0)
        res["answer"]["confidence"] = 0.6
        return res
    from engine import advisor, findings
    from engine.rules import load_rules
    prefixes = tuple(p for p, _ in pick)
    labels = " and ".join(l for _, l in pick)
    narrow = [ids for rx, ids in SPECIFIC if re.search(rx, question, re.I)]
    narrow_ids = tuple(i for ids in narrow for i in ids)
    if narrow_ids:
        prefixes = narrow_ids
    st = resolve_storey(question, doc.storeys)
    fs = [f for f in findings.run_doc(doc) if f["rule_id"].startswith(prefixes) and (not st or f.get("storey") in (None, st))]
    cov = findings.coverage(doc)
    checked = [r for r in cov["checked"] if r.startswith(prefixes)]
    skipped = [s for s in cov["not_checked"] if s["rule_id"].startswith(prefixes)]
    by = {r["id"]: r for r in load_rules()}
    if narrow_ids and not checked and skipped:
        why = "; ".join(dict.fromkeys(f"{advisor._short(by[s['rule_id']])}: {s['reason']}" for s in skipped if s["rule_id"] in by))
        trace = [_step("route", f"rule check / {labels} -> cannot be checked on this model")]
        text = f"**Cannot be checked on this model.** {why}. No pass is implied; add the missing data (or check by hand against {advisor._checked_text([s['rule_id'] for s in skipped])})."
        res = _done(question, doc, text, None, None, [], trace, t0=t0)
        res["answer"]["confidence"] = 0.6
        return res
    ck = advisor._checked_text(checked)
    items = [i for i in doc.items if any(i.item_id in f["item_ids"] for f in fs)]
    trace = [_step("route", f"rule check / {labels} -> code over the model, no model"), _step("findings", f"{len(fs)} findings from {len(checked)} checks")]
    if fs:
        top = fs[:4]
        lines = "; ".join(f"{f['title']} ({advisor._short(by[f['rule_id']]) if f['rule_id'] in by else f['rule_id']}, {f['severity']})" for f in top)
        text = (f"**Not clearly compliant on {labels}.** {len(fs)} finding{'s' if len(fs) != 1 else ''}: {lines}. Checked: {ck}. "
                + (f"Not checkable with this model: {len(skipped)} rule{'s' if len(skipped) != 1 else ''}. " if skipped else "") + "{marks}")
        val = len(fs)
    else:
        text = (f"**No violation found** for {labels} by the checks that can run on this model (checked: {ck}). "
                + (f"{len(skipped)} rule{'s' if len(skipped) != 1 else ''} could not be checked automatically, so this is not a full compliance statement. " if skipped else "")
                + "{marks}")
        val = 0
    res = _done(question, doc, text, val, "count", items, trace, t0=t0)
    res["answer"]["confidence"] = 0.7
    res["advisor_cards"] = advisor.advise_doc(doc, None)[:6] if fs else []
    return res


SUPER = re.compile(r"\b(largest|biggest|smallest|tiniest)\b", re.I)


def superlative_room(question: str, doc: Doc, t0) -> dict | None:
    """"what is the biggest room in this plan": plan maps only (IFC goes through the index route)."""
    ql = question.lower()
    if doc.mode != "planmap" or not SUPER.search(ql) or not re.search(r"\b(room|space)s?\b", ql) or re.search(r"\bhow many\b|\bwindow|\bdoor", ql):
        return None
    outdoor = re.compile(r"terrace|terrassi|balcon|parveke|outdoor|patio|garden|yard|deck|porch|veranda", re.I)
    rooms = [(r, _qty(r, "room", "area")) for r in _of_kind(doc, "room")
             if not outdoor.search(f"{r.label or ''} {r.props.get('room_type') or ''}") or re.search(r"\boutdoor|terrace|balcon", ql)]
    rooms = sorted([(r, v) for r, v in rooms if v], key=lambda t: -t[1])
    if not rooms:
        return None
    small = re.search(r"smallest|tiniest", ql) is not None
    if small:
        rooms.reverse()
    r, v = rooms[0]
    rt = r.props.get("room_type") or "room"
    nm = r.label or f"{rt} room"
    nxt = "; ".join(f"{(x.label or (str(x.props.get('room_type') or 'room') + ' room'))} {_fmt(y)} m²" for x, y in rooms[1:4])
    sc = doc.scale or {}
    est = " The scale is estimated from door sizes, so areas are approximate." if (sc.get("confidence") or 1) < 0.5 else ""
    trace = [_step("route", "largest room / plan map -> code, no model"), _step("compare", f"{len(rooms)} rooms ranked by area")]
    text = f"The {'smallest' if small else 'largest'} room is **{nm}**{'' if not r.label else ' (' + rt + ')'} at **{_fmt(v)} m²**. Next: {nxt}.{est} {{marks}}"
    return _done(question, doc, text, v, "m2", [r], trace, t0=t0)


def run(question: str, doc: Doc, t0, solve_fn=None) -> dict | None:
    """First handler that recognises the shape wins; every handler may return None."""
    for fn in (storey_pair, storey_compare, total_and_storey, cond_count, exact_size, kind_compare, compliance, superlative_room, where_rooms):
        res = fn(question, doc, t0)
        if res is not None:
            return res
    if solve_fn is not None:
        res = takeoff(question, doc, t0, solve_fn)
        if res is not None:
            return res
    return named_rooms(question, doc, t0)


def edit_advice(res: dict, doc: Doc, hidden_ids: list[str]) -> None:
    """"remove the front door, is it still compliant": run the advisor on the edited model and put the verdict in the answer text."""
    from engine import advisor
    cards = advisor.advise_doc(doc, {"op": "hide", "item_ids": hidden_ids})
    if not cards:
        return
    res["advisor_cards"] = cards
    bad = [c for c in cards if c.get("severity") == "violation"]
    sug = [c for c in cards if c.get("severity") == "suggestion"]
    def line(c):
        s = c.get("source") or {}
        return f"{c['title']} ({(s.get('title') or '').split(',')[-1].strip() or s.get('ref', '')})"
    if bad:
        verdict = "**Not compliant after this edit:** " + "; ".join(line(c) for c in bad[:3]) + "."
    elif sug:
        verdict = "**Possible problem after this edit:** " + "; ".join(line(c) for c in sug[:3]) + "."
    else:
        verdict = "**No rule broken by this edit** in the checks that can run on this model" + (f" (checked: {cards[0].get('checked') and advisor._checked_text(cards[0]['checked'])})." if cards[0].get("checked") else ".")
    res["answer"]["text_md"] = f"{res['answer']['text_md']} {verdict}"
