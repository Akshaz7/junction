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


def _notes(question, doc_id, pts, t0):
    if re.search(r"\b(schedule|table|sheet [A-Z]-?\d)", question, re.I):   # schedule lookups belong to the schedule reader
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
    for fn in (_count_rows, _notes):
        res = fn(question, doc_ids[0], pts, t0)
        if res is not None:
            res["doc_ids"] = list(doc_ids)
            return res
    return None
