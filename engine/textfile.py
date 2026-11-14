"""Uploaded sheets with a text layer but no plan map: answer from the file's printed text, $0.

Ash's rule: if the file contains the data, answer it; say "not shown" only when the text really has no such note.
  door/window counts from schedule rows, slab / rebar / area / perimeter / finish notes quoted with boxes.
Returns None when unsure so the reader still gets the question."""
from __future__ import annotations

import re
import time

from engine import sheetqa

DOOR_ROW = re.compile(r"^\s*(?:[A-Z]\s+)?(\d{2,4}\.?[A-Z]\d?)\s+[A-Za-z]")
AREA_NUM = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:m²|m2|sq\.?\s?m|sq\.?\s?ft\.?|sf|s\.f\.)(?=\W|$)", re.I)
PERIM_NUM = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:m|mm|ft|')\b")
TOPICS = [  # (question regex, note regex, noun for the sentence)
    (r"\bslabs?\b", r"\bslabs?\b", "slab"),
    (r"\b(rebar|reinforc\w*|bars?)\b", r"\b(rebar|reinforc\w*|D\d{2}|#\d\b|\d\s?mm\s?bars?|@\s?\d{2,4})", "reinforcement"),
    (r"\bfinish\w*\b", r"\bfinish\w*\b", "finish"),
    (r"\b(perimeters?|circumference)\b", r"\bperimeters?\b", "perimeter"),
    (r"\bareas?\b|\bhow (big|large)\b|\bsquare (m|f)\w*\b", r"\bareas?\b", "area"),
    (r"\b(wall types?|partitions?)\b", r"\b(wall type|partition|stud)\w*", "wall"),
    (r"\bceilings?\b", r"\bceiling\b", "ceiling"),
]


def _segs(pts):
    return [(pt.page, s) for pt in pts for s in pt.segs if (s.get("text") or "").strip()]


def _count_rows(question, doc_id, pts, t0):
    m = re.search(r"\bhow many (doors?)\b", question, re.I)
    if not m:
        return None
    nums = []
    for pt in pts:
        for w in pt.words:
            t = str(w.get("text") or "")
            if re.fullmatch(r"\d{3}\.[A-Z]\d?", t) and t not in [n for n, _, _ in nums]:
                nums.append((t, pt.page, w["bbox_px"]))
    if not nums:
        return None
    n = len(nums)
    text = (f"The door schedule on this sheet lists **{n} doors**. It is counted from the printed schedule rows, "
            f"so it covers the doors on this sheet only. {{marks}}")
    return sheetqa._obj(question, doc_id, text, n, "doors", [(pg, bb, t) for t, pg, bb in nums[:12]],
                        "door numbers counted from the printed schedule", t0)


SF_ROW = re.compile(r"(?<![\d,.])(\d[\d,]*)\s?SF\s+(\d{3}[A-Z]?)\s+([A-Z][A-Z0-9 .&'/()-]*?)(?=\s+[A-Z]\d\b|\s+-\s|\s*$)")
M2_SF = 0.09290304
WETRX = re.compile(r"\b(restrooms?|toilets?|wcs?|bath\w*|shower\w*|lavator\w+|locker)\b", re.I)
WET_STRICT = re.compile(r"\b(restrooms?|toilets?|wcs?|bath\w*|shower\w*|lavator\w+)\b", re.I)
TILE_BOX_M2, TILE_EUR_M2 = 1.44, 35.0


def _room_rows(doc_id, root, pts):
    """room table rows 'AREA SF NUMBER NAME F1 B1 ...' -> [(number, name, m2, page, bbox)]"""
    import json
    from pathlib import Path
    try:
        t = json.loads((Path(root) / doc_id / "text.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    segs = [(pt.page, s) for pt in pts for s in pt.segs]
    rows, seen = [], set()
    for pg in t.get("pages") or []:
        for line in str(pg.get("text") or "").split("\n"):
            line = re.sub(r"^[A-Z]\s+(?=\d)", "", line.strip())
            m = SF_ROW.search(line)
            if not m:
                continue
            num, name = m.group(2), m.group(3).strip(" .-")
            if num in seen or len(name) < 3:
                continue
            seen.add(num)
            sf = float(m.group(1).replace(",", ""))
            hit = next(((p_, s["bbox_px"]) for p_, s in segs if re.match(rf"(?:[A-Z]\s+)?{int(sf)} SF\b(?!.*\bSF\b)|{int(sf)} SF$", s["text"].replace(",", "").strip())), (pg.get("page", 1), None))
            rows.append((num, name, round(sf * M2_SF, 1), sf, hit[0], hit[1]))
    return rows


def _mk(question, doc_id, text, value, unit, rows, step, t0):
    hits = [(pg, bb, f"{nm}: {int(sf):,} SF") for _, nm, _, sf, pg, bb in rows[:30] if bb]
    return sheetqa._obj(question, doc_id, text, value, unit, hits, step, t0, 0.85)


def _room_table(question, doc_id, pts, t0, rooms):
    if not rooms:
        return None
    q = question.lower()
    f = lambda v: f"{v:,.1f}"
    if re.search(r"\b(tiles?|tiling)\b", q):
        sel = [r for r in rooms if WET_STRICT.search(r[1])]
        if not sel:
            return None
        area = sum(r[2] for r in sel)
        wm = re.search(r"(\d+(?:[.,]\d+)?)\s*%", question)
        pct = float(wm.group(1).replace(",", ".")) if wm else 10.0
        need = area * (1 + pct / 100)
        boxes = int(-(-need // TILE_BOX_M2))
        text = (f"Order about **{f(need)} m²** of floor tiles, which is **{boxes} boxes**. That is {f(area)} m² of floor in the {len(sel)} "
                f"{'bathroom or WC' if len(sel) == 1 else 'bathrooms and WCs'} listed in the room table, plus {pct:g}% for cuts and breakage. {{marks}}\n\n"
                f"Assumptions, not from the drawing: {TILE_BOX_M2} m² per box (four 60 x 60 cm tiles) and about €{TILE_EUR_M2:.0f} per m², "
                f"so roughly **€{boxes * TILE_BOX_M2 * TILE_EUR_M2:,.0f}**. This is a rough guide, not a quote. The room table gives areas in square feet; converted to m².")
        return _mk(question, doc_id, text, round(need, 1), "m2", sel, "tile take-off from the room table", t0)
    if re.search(r"\bquantity take-?off\b|\btake-?off\b|\bquantities\b", q):
        lines = "\n".join(f"| {nm.title().replace("'S","'s")} ({num}) | {f(m2)} | m² |" for num, nm, m2, *_ in rooms[:30])
        doors = _doors(pts)
        text = ("**Quantity take-off from this sheet's room table.**\n\n| Room | Floor area | Unit |\n|---|---|---|\n" + lines
                + f"\n\nTotal of the {len(rooms)} rooms: **{f(sum(r[2] for r in rooms))} m²**." + (f" Doors in the schedule: **{len(doors)}**." if doors else "")
                + "\n\nBaseboard lengths, slab area by type and piping are not in this file. Areas are converted from square feet. {marks}")
        return _mk(question, doc_id, text, len(rooms), "rooms", rooms, "take-off from the room table", t0)
    if re.search(r"\b(areas?|how (big|large)|square|largest|biggest)\b", q):
        words = [w for w in re.findall(r"[a-z]{3,}", q) if w not in {"what", "the", "area", "areas", "room", "rooms", "total", "how", "big", "large", "square", "metres", "meters", "all", "are", "many", "and", "for", "this", "sheet"}]
        sel = [r for r in rooms if any(w.rstrip("s") in r[1].lower() for w in words)] if words else []
        if re.search(r"\b(largest|biggest)\b", q):
            sel = [max(rooms, key=lambda r: r[2])]
            text = f"The largest room is the **{sel[0][1].title().replace("'S","'s")}** at **{f(sel[0][2])} m²**. {{marks}}"
            return _mk(question, doc_id, text, sel[0][2], "m2", sel, "largest room from the room table", t0)
        if sel:
            tot = sum(r[2] for r in sel)
            parts = "; ".join(f"{r[1].title().replace("'S","'s")} ({r[0]}) {f(r[2])} m²" for r in sel[:8])
            text = (f"The area is **{f(tot)} m²**: {parts}. {{marks}}" if len(sel) > 1 else f"The area of the **{sel[0][1].title().replace("'S","'s")}** is **{f(tot)} m²**. {{marks}}")
            return _mk(question, doc_id, text, round(tot, 1), "m2", sel, "room areas from the room table", t0)
        tot = sum(r[2] for r in rooms)
        text = f"The room table lists **{len(rooms)} rooms** adding up to **{f(tot)} m²** (converted from square feet). {{marks}}"
        return _mk(question, doc_id, text, round(tot, 1), "m2", rooms, "room table total", t0)
    return None


def _doors(pts):
    nums = []
    for pt in pts:
        for w in pt.words:
            t = str(w.get("text") or "")
            if re.fullmatch(r"\d{3}\.[A-Z]\d?", t) and t not in [n for n, _, _ in nums]:
                nums.append((t, pt.page, w["bbox_px"]))
    return nums


def _takeoff(question, doc_id, pts, t0):
    """'quantity take-off' / 'floor tiles for the bathrooms' on a sheet with no room areas: say what the text has and what it lacks."""
    tile = re.search(r"\b(tiles?|tiling)\b", question, re.I)
    if not (tile or re.search(r"\bquantity take-?off\b|\btake-?off\b|\bbill of quantities\b|\bquantities\b", question, re.I)):
        return None
    areas = [(pg, s) for pg, s in _segs(pts) if AREA_NUM.search(s["text"])]
    if areas:
        return None   # the file has areas: the area handler quotes them
    doors = _doors(pts)
    if tile:
        text = ("**I can't size the tiles from this file.** Its printed text has no floor areas, so there is nothing to add up for the bathrooms. "
                "Upload the floor plan or the room table with areas and I will work out the area, 10% waste, boxes and a rough price.")
        return sheetqa._obj(question, doc_id, text, None, None, [], "no floor areas in the file text", t0, 0.6)
    lines = [f"- Doors: **{len(doors)}** in the door schedule {{marks}}"] if doors else []
    lines += ["- Floor areas: not in this file", "- Baseboard lengths: not in this file", "- Slab area by type: not in this file", "- Piping by system: not in this file"]
    text = "**Quantity take-off from this sheet's printed text.**\n" + "\n".join(lines) + \
           "\n\nThis sheet is a schedule, so it carries door data but no room areas. Upload the floor plan to get areas and baseboard."
    return sheetqa._obj(question, doc_id, text, len(doors) or None, "doors" if doors else None,
                        [(pg, bb, t) for t, pg, bb in doors[:12]], "take-off from printed text", t0, 0.7)


def _notes(question, doc_id, pts, t0):
    if re.search(r"\b(schedule|sheet [A-Z]-?\d)", question, re.I):   # schedule lookups belong to the schedule reader
        return None
    for qre, nre, noun in TOPICS:
        if not re.search(qre, question, re.I):
            continue
        # the question may also name a room or element: keep notes that mention it when some do
        extra = [w for w in re.findall(r"[a-z]{4,}", question.lower())
                 if w not in {"what", "which", "that", "this", "does", "have", "show", "shown", "many", "with", "from", "types", "type",
                              "slab", "slabs", "rebar", "area", "areas", "perimeter", "finish", "finishes", "there", "sheet", "drawing",
                              "note", "notes", "total", "rooms", "room", "reinforcement", "walls", "about", "tell", "list", "give", "are", "the"}]
        hits = [(pg, s) for pg, s in _segs(pts) if re.search(nre, s["text"], re.I) or (noun == "area" and AREA_NUM.search(s["text"]))]
        if noun == "area":
            hits = [h for h in hits if AREA_NUM.search(h[1]["text"])]
        if noun == "perimeter":
            hits = [h for h in hits if PERIM_NUM.search(h[1]["text"])]
        if extra:
            sub = [h for h in hits if any(w in h[1]["text"].lower() for w in extra)]
            hits = sub or hits
        if not hits:
            if re.search(r"(?<![\w])'[^']{2,}'(?!\w)|\"[^\"]{2,}\"", question):
                return None   # a named room or element ('ESIK (58-2)'): its own record may carry the value, so let the element path answer
            if noun in ("area", "perimeter"):
                what = "areas" if noun == "area" else "perimeters"
                text = (f"**This file does not show {what}.** Its printed text has no room table or note with {what}. "
                        f"Upload the plan with its room table, or ask about what the sheet does list.")
            else:
                text = (f"**Not shown in this file.** Its printed text has no {noun} note"
                        + (" or bar sizes" if noun == "reinforcement" else "") + ". "
                        "A structural sheet or an IFC model would carry it.")
            res = sheetqa._obj(question, doc_id, text, None, None, [], f"no {noun} text in the file", t0, 0.6)
            return res
        hits = hits[:5]
        quotes = "\n".join(f"- \"{s['text'][:140].strip()}\" [{i}]" for i, (_, s) in enumerate(hits, 1))
        lead = {"slab": "The sheet's slab notes", "reinforcement": "The sheet's reinforcement notes", "finish": "The sheet's finish notes",
                "perimeter": "The perimeters printed on the sheet", "area": "The areas printed on the sheet",
                "wall": "The wall notes on the sheet", "ceiling": "The ceiling notes on the sheet"}[noun]
        text = f"{lead} read:\n{quotes}"
        if noun == "slab" and not re.search(r"\b(rebar|reinforc\w*|D\d{2}|@\s?\d{2,4})", " ".join(s["text"] for _, s in hits), re.I) \
                and re.search(r"\b(rebar|reinforc\w*|bars?)\b", question, re.I):
            text += "\n\nNo bar sizes or spacing are printed next to it."
        return sheetqa._obj(question, doc_id, text, None, None, [(pg, s["bbox_px"], s["text"]) for pg, s in hits],
                            f"{noun} text quoted from the file", t0, 0.8)
    return None


def answer(question: str, doc_ids: list[str], root, t0=None):
    t0 = t0 or time.perf_counter()
    if len(doc_ids) != 1:
        return None
    try:
        pts = sheetqa._pages(doc_ids[0], root)
    except Exception:
        return None
    if not any(pt.words for pt in pts):
        return None
    rooms = _room_rows(doc_ids[0], root, pts)
    for fn in (_count_rows, lambda *a: _room_table(*a, rooms), _takeoff, _notes):
        res = fn(question, doc_ids[0], pts, t0)
        if res is not None:
            res["doc_ids"] = list(doc_ids)
            return res
    return None
