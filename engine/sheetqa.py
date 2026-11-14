"""FIX-14: engineering sheets (piping, foundation, HVAC, dormitory plans), answered from their own text at $0.

These are not apartment plans: the answers live in tags (FP-1..FP-5), tables (SF), notes (trench lengths, D16 @ 300) and
mixed units (1/4" = 1'-0", 26,562 SF). So they must not go down the CubiCasa plan-map path.

  is_sheet(doc)          sheet id prefix M-/S-/P-/E-/C- in the title block or name, or a tag-heavy / SF-table page
  tag_count              "how many fuel pumps": unique FP-n tags, each boxed
  scale_answer           "what scale": 1/4" = 1'-0" -> 1:48, 1:50, with conversion
  area_total             "second floor area in m2": the TOTAL ... SF cell, converted, column arithmetic checked
  share_of_total         "what share of the floor is circulation"
  note_sum               "total trench length": the numbers of the note, summed
  rebar_of               "reinforcement of the 150 mm slab": D16 @ 300 style notation next to the slab
  cross_sheet            "where is the pipe penetration detail": 'see M-303', and M-303 is not uploaded
Every handler returns None when unsure so the reader (model) still gets the question."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from engine.reader.text import load_page_text

SHEET_ID = re.compile(r"\b([A-Z]{1,2})[-.\s]?(\d{3})([A-Z]?)\b")
NON_PLAN_PREFIX = {"M", "S", "P", "E", "C", "FP", "MP", "PL", "EL", "ST"}
TAG = re.compile(r"^([A-Z]{1,4})-?(\d{1,3})$")
M2_PER_SF = 0.09290304

# noun -> tag prefixes used on the sheets (the initials rule covers the rest, only when the prefix really occurs)
NOUN_PREFIX = {
    "fuel pump": ["FP"], "pump": ["P", "FP", "CP"], "check valve": ["CV"], "filter separator": ["FSR", "FSI", "FS"],
    "filter separator vessel": ["FSR", "FSI", "FS"], "pipe support": ["PS"], "exhaust fan": ["EXF", "EF"],
    "return air grille": ["RAG"], "supply air grille": ["SAG"], "return grille": ["RAG"], "supply grille": ["SAG"],
    "control valve": ["FSCV", "CV"], "water closet": ["WC"], "toilet": ["WC"], "lavatory": ["LAV"], "shower": ["SH"],
    "kitchen sink": ["KS"], "sink": ["KS", "S"], "floor drain": ["FD"], "cleanout": ["CO"], "roof vent": ["VTR"], "vent through roof": ["VTR"],
    "vent": ["VTR", "V"], "fire damper": ["FD"], "damper": ["CD", "FD", "VD"], "sump": ["SP"],
}


def _norm_noun(s: str) -> str:
    s = re.sub(r"[^a-z ]", " ", s.lower())
    words = []
    for w in s.split():
        if w in ("the", "of", "are", "is", "there", "in", "this", "on", "all", "a", "sheet", "drawing", "plan", "total", "many", "how"):
            continue
        if w.endswith("ies"):
            w = w[:-3] + "y"
        elif w.endswith("es") and w[:-2].endswith(("ss", "sh", "ch", "x")):
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def _pages(doc_id: str, root) -> list:
    d = Path(root) / doc_id
    try:
        n = len(json.loads((d / "pages.json").read_text())["pages"])
    except (OSError, ValueError, KeyError):
        n = 1
    return [load_page_text(doc_id, p, root) for p in range(1, min(n, 6) + 1)]


def _title(doc_id: str, root) -> str:
    try:
        return json.loads((Path(root) / doc_id / "doc.json").read_text()).get("title") or doc_id
    except (OSError, ValueError):
        return doc_id


def sheet_ids(doc_id: str, root, pts=None) -> set[str]:
    """Sheet ids named in the title or title block ('M-101A', 'S-100F', 'A-2')."""
    out = set()
    for m in SHEET_ID.finditer(_title(doc_id, root).upper().replace("SHEET", " ")):
        out.add(f"{m.group(1)}-{m.group(2)}{m.group(3)}")
    return out


def is_sheet(doc_id: str, root, pts=None) -> bool:
    """True for an engineering sheet: a non-architectural sheet id in the title, or a page full of tags / SF figures."""
    ids = sheet_ids(doc_id, root)
    if any(i.split("-")[0] in NON_PLAN_PREFIX for i in ids):
        return True
    try:  # title-block sheet id from the text layer (VISION-FT's reader)
        from vision.sheet_text import read_sheet
        tp = Path(root) / doc_id / "text-1.json"
        sid = (read_sheet(str(tp)).get("sheet") or {}).get("id") if tp.exists() else None
        if sid and re.match(r"^([A-Z]{1,2})[-.]?\d", sid) and re.match(r"^([A-Z]{1,2})", sid).group(1) in NON_PLAN_PREFIX:
            return True
    except Exception:
        pass
    pts = pts if pts is not None else _pages(doc_id, root)
    words = [str(w.get("text") or "") for pt in pts for w in pt.words]
    tags = {w for w in words if TAG.match(w) and "-" in w}
    sf = sum(1 for w in words if w.upper() in ("SF", "S.F.", "SQ.FT.", "SQFT"))
    return len(tags) >= 8 or sf >= 3


# ---------------------------------------------------------------- answer object
def _obj(question, doc_id, text, value, unit, hits, step, t0, conf=0.9):
    """hits: [(page, bbox, quote)] -> numbered boxes and text citations."""
    cites, boxes = [], []
    for n, (pg, bb, q) in enumerate(hits, 1):
        cites.append({"n": n, "doc_id": doc_id, "page": pg, "kind": "text", "bbox_px": bb, "item_ids": [], "quote": q})
        boxes.append({"item_id": f"text-{pg}-{n}", "page": pg, "bbox_px": bb, "label": str(n)})
    ms = int((time.perf_counter() - t0) * 1000)
    return {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc_id],
            "answer": {"text_md": text.replace("{marks}", "".join(f"[{c['n']}]" for c in cites)), "value": value, "unit": unit,
                       "confidence": conf, "abstained": False},
            "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": doc_id, "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": [{"step": "sheet_text", "detail": step, "ms": ms, "model": None, "cost_usd": 0}], "route": "index",
            "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": ms}


def _union(bs):
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


# ---------------------------------------------------------------- units
FT_IN = re.compile(r"(\d+)\s*'\s*-?\s*(?:(\d+)(?:\s+(\d+)/(\d+))?\s*(?:\"|”|″))?")


def feet_inches_to_m(s: str) -> float | None:
    m = FT_IN.search(s)
    if not m:
        return None
    ft = int(m.group(1))
    inch = int(m.group(2) or 0) + (int(m.group(3)) / int(m.group(4)) if m.group(3) else 0)
    return round((ft * 12 + inch) * 0.0254, 3)


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


IMPERIAL_SCALE = re.compile(r"(\d+(?:\s+\d+)?(?:/\d+)?)\s*(?:\"|”|″)\s*=\s*(\d+)\s*'\s*-?\s*(\d+)?\s*(?:\"|”|″)?")
METRIC_SCALE = re.compile(r"(?<![\d:])1\s*:\s*(\d{1,4})(?!\d)")


def parse_scale(text: str) -> tuple[str, float] | None:
    """(printed text, ratio N for 1:N)."""
    m = IMPERIAL_SCALE.search(text)
    if m:
        a = m.group(1).split()
        inch = sum(int(x.split("/")[0]) / int(x.split("/")[1]) if "/" in x else float(x) for x in a)
        feet = int(m.group(2)) + (int(m.group(3) or 0) / 12)
        if inch > 0:
            return m.group(0).strip(), round(feet * 12 / inch, 2)
    m = METRIC_SCALE.search(text)
    if m:
        return m.group(0).replace(" ", ""), float(m.group(1))
    return None


def scale_answer(question, doc_id, pts, t0):
    if not re.search(r"\bscale\b", question, re.I):
        return None
    for pt in pts:
        segs = [s for s in pt.segs if re.search(r"scale", s["text"], re.I) or IMPERIAL_SCALE.search(s["text"]) or METRIC_SCALE.search(s["text"])]
        for s in segs:
            p = parse_scale(s["text"])
            if p:
                shown, ratio = p
                kind = "imperial" if "'" in shown or '"' in shown else "metric"
                extra = f" That is 1:{ratio:g}, so 1 m on the ground is {1000 / ratio:.1f} mm on the sheet." if kind == "imperial" else \
                    f" So 1 m on the ground is {1000 / ratio:g} mm on the sheet."
                text = f"The scale is **{shown}**.{extra} {{marks}}"
                return _obj(question, doc_id, text, shown, None, [(pt.page, s["bbox_px"], s["text"])], "scale printed on the sheet, converted to a ratio", t0)
    return None


# ---------------------------------------------------------------- tags
def _tag_words(pts):
    """[(tag, page, bbox)] for every PREFIX-n word; 'FP 1' written apart is joined."""
    out = []
    for pt in pts:
        ws = [w for w in pt.words if w.get("bbox_px")]
        for i, w in enumerate(ws):
            t = str(w.get("text") or "").strip(".,;:()")
            m = TAG.match(t)
            if m and ("-" in t or len(m.group(1)) >= 2):
                out.append((f"{m.group(1)}-{m.group(2)}", pt.page, w["bbox_px"]))
    return out


def _legend_prefixes(noun, pts, present):
    """Prefixes whose legend / abbreviation line (e.g. 'SH - SHOWER') contains the noun."""
    out = []
    for pt in pts:
        for sg in pt.segs:
            m = re.match(r"^([A-Z]{1,4})\s*[-=:.]\s*([A-Za-z][A-Za-z /&]+)$", sg["text"].strip())
            if m and m.group(1) in present and _norm_noun(m.group(2)) and noun and (noun in _norm_noun(m.group(2)) or _norm_noun(m.group(2)) in noun):
                out.append(m.group(1))
    return out


def _pipe_label_count(question, noun, explicit, pts):
    """'how many 3 inch roof vents (VTR)': count pipe labels such as 3"VTR; None when the question names no pipe size."""
    sz = re.search(r"(\d+(?:[- ]\d/\d)?)\s*(?:inch|in\b|\"|”)", question, re.I)
    key = explicit[0] if explicit else ("VTR" if "roof vent" in noun or noun == "vent" else None)
    if not sz or not key:
        return None
    want = re.sub(r"[- ]", " ", sz.group(1))
    hits = []
    for pt in pts:
        for sg in pt.segs:
            for m in re.finditer(r"(\d+(?:[- ]\d/\d)?)\s*(?:\"|”|″)\s*" + key + r"\b", sg["text"]):
                if re.sub(r"[- ]", " ", m.group(1)) == want:
                    hits.append((pt.page, sg["bbox_px"], m.group(0)))
    if not hits:
        return None
    n = len(hits)
    return (f"There are **{n}** {sz.group(1)}\" {key} labels on the sheet. {{marks}}", n, hits, f"pipe labels {sz.group(1)}\" {key}: {n}")


def tag_count(question, doc_id, pts, t0):
    m = re.search(r"\bhow many\s+(.+?)(?:\s+(?:are|is|do|does|on|in|does|can)\b.*)?[?.!]*$", question.strip(), re.I)
    if not m:
        return None
    noun = _norm_noun(m.group(1))
    if not noun or noun in ("room", "door", "window", "wall", "stair", "column", "dorm room", "dorm"):
        return None
    tags = _tag_words(pts)
    explicit = re.findall(r"\(([A-Z]{2,4})\)", question)
    vt = _pipe_label_count(question, noun, explicit, pts)
    if vt is not None:
        return _obj(question, doc_id, vt[0].replace("{marks}", "{marks}"), vt[1], "count", vt[2], vt[3], t0)
    if not tags:
        return None
    prefixes = []
    for k, v in NOUN_PREFIX.items():
        if noun == k or noun.endswith(" " + k) or noun == k + " vessel":
            prefixes = v
            break
    present = {t.split("-")[0] for t, _p, _b in tags}
    if not prefixes:
        prefixes = [e for e in explicit if e in present] or _legend_prefixes(noun, pts, present)
    if prefixes:
        prefixes = [p for p in prefixes if p in present]
    if not prefixes:
        ini = "".join(w[0] for w in noun.split()).upper()
        if len(ini) >= 2 and ini in present:
            prefixes = [ini]
    if not prefixes:
        return None
    mine = [(t, p, b) for t, p, b in tags if t.split("-")[0] in prefixes]
    uniq = sorted({t for t, _p, _b in mine}, key=lambda t: (t.split("-")[0], int(t.split("-")[1])))
    first = {}
    for t, p, b in mine:
        first.setdefault(t, (p, b))
    n_inst = len(mine)
    if len(uniq) == 1 and n_inst > 1:
        value, how = n_inst, f"**{n_inst}** (tag **{uniq[0]}** appears {n_inst} times on the sheet; one tag, several locations)"
    else:
        value, how = len(uniq), f"**{len(uniq)}** ({', '.join(uniq)})"
    text = f"There are {how}, counted from the unique tags on the sheet. {{marks}}"
    hits = [(first[t][0], first[t][1], t) for t in uniq] if value == len(uniq) else [(p, b, t) for t, p, b in mine]
    return _obj(question, doc_id, text, value, "count", hits, f"unique tags {'/'.join(prefixes)}-n in the text layer: {len(uniq)} unique, {n_inst} marks", t0)


# ---------------------------------------------------------------- tables and notes
SF_NUM = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d{3,6}$")


def _row_numbers(pt, seg):
    return [(_num(str(w["text"])), w["bbox_px"]) for w in pt.words
            if w.get("bbox_px") and SF_NUM.match(str(w["text"]).strip()) and abs((w["bbox_px"][1] + w["bbox_px"][3]) / 2 - (seg["bbox_px"][1] + seg["bbox_px"][3]) / 2) <= (seg["bbox_px"][3] - seg["bbox_px"][1]) * 0.7
            and w["bbox_px"][0] >= seg["bbox_px"][0] - 5]


def room_area(question, doc_id, pts, t0):
    """'area of the dining room': the matching table row ('DINING 164 SF'), never the total."""
    m = re.search(r"\b(?:area|size)\s+of\s+(?:the\s+)?(.+?)(?:\s+in\s+(?:square\s+)?(?:m|metres?|meters?|m2|m²|sf|feet).*)?[?.!]*$", question, re.I)
    if not m or re.search(r"\b(total|floor|building|gross|whole|second|first|level)\b", m.group(1), re.I):
        return None
    keys = [k for k in re.findall(r"[a-z]{3,}", m.group(1).lower()) if k not in ("room", "the", "square", "metres", "meters", "feet", "area")]
    if not keys:
        return None
    for pt in pts:
        for sg in pt.segs:
            if all(re.search(re.escape(k), sg["text"], re.I) for k in keys) and not re.search(r"\btotal\b", sg["text"], re.I):
                tm = re.findall(r"(\d{1,3}(?:,\d{3})+|\d{2,6})\s*(?:SF|S\.F\.)", sg["text"], re.I)
                val = _num(tm[0]) if tm else None
                if val is None:  # the figure is its own word followed by an SF word on the same row, to the right of the room name
                    cy = (sg["bbox_px"][1] + sg["bbox_px"][3]) / 2
                    row = sorted((w for w in pt.words if w.get("bbox_px") and abs((w["bbox_px"][1] + w["bbox_px"][3]) / 2 - cy) < (sg["bbox_px"][3] - sg["bbox_px"][1]) * 0.8
                                  and w["bbox_px"][0] >= sg["bbox_px"][0]), key=lambda w: w["bbox_px"][0])
                    for a, b in zip(row, row[1:]):
                        if SF_NUM.match(str(a["text"]).strip()) and str(b["text"]).upper().strip(".") in ("SF", "SQFT"):
                            val = _num(str(a["text"]))
                            break
                if val:
                    text = f"The area of **{m.group(1)}** is **{val:,.0f} SF = {val * M2_PER_SF:,.1f} m²** (1 SF = 0.0929 m²), from the table row \"{sg['text'][:80]}\". {{marks}}"
                    return _obj(question, doc_id, text, round(val * M2_PER_SF, 1), "m2", [(pt.page, sg["bbox_px"], sg["text"])], "table row for the named room", t0)
    return None


def schedule_rows(question, doc_id, pts, t0):
    """'how many rooms in the schedule': rows of the table that carry an area figure, TOTAL excluded."""
    if not re.search(r"\bhow many\b.*\b(rooms?|spaces?|rows?|entries)\b.*\b(schedule|table|list)\b", question, re.I):
        return None
    rows = []
    for pt in pts:
        for sg in pt.segs:
            t = sg["text"]
            if re.search(r"\btotal\b", t, re.I) or not re.search(r"[A-Za-z]{3}", t):
                continue
            if re.search(r"(\d{1,3}(?:,\d{3})+|\d{2,6})\s*(?:SF|S\.F\.)\b", t, re.I):
                rows.append((pt.page, sg["bbox_px"], t))
    if len(rows) < 2:
        return None
    return _obj(question, doc_id, f"The schedule lists **{len(rows)}** rows with an area (the total row is not counted). {{marks}}", len(rows), "count", rows, "table rows with an SF figure", t0, 0.7)


BY_EACH = re.compile(r"\b(?:each|every|per|by|all)\s+(?:the\s+)?(?:room|area|space|slab|floor|use|zone)s?(?:\s+(?:type|types|use|name))?\b|\b(?:areas?|sizes?)\s+by\s+(?:room\s+|area\s+|space\s+)?(?:type|use|room|name)\b|\blist\b.*\b(?:rooms?|areas?|spaces?)\b", re.I)


def area_by_type(question, doc_id, pts, t0):
    """'floor area of each room type / list the rooms with areas': every table row with an SF figure, TOTAL excluded."""
    if not re.search(r"\b(area|areas|size|sizes|sf|square|m2|m²)\b", question, re.I) or not BY_EACH.search(question) \
            or re.search(r"\b(slabs?|base ?boards?|skirting|pipes?|piping|doors?|windows?)\b", question, re.I):
        return None
    rows, seen = [], set()
    for pt in pts:
        for sg in pt.segs:
            t = sg["text"]
            if re.search(r"\btotal\b", t, re.I):
                continue
            tm = re.findall(r"(\d{1,3}(?:,\d{3})+|\d{2,6})\s*(?:SF|S\.F\.)\b", t, re.I)
            if not tm:
                continue
            name = re.sub(r"[\d,]+\s*(?:SF|S\.F\.)\b.*$", "", t, flags=re.I).strip(" -:.")
            if len(name) < 3:  # the figure is its own cell: take the nearest text cell to its left on the same row
                cy, h = (sg["bbox_px"][1] + sg["bbox_px"][3]) / 2, sg["bbox_px"][3] - sg["bbox_px"][1]
                left = [o for o in pt.segs if o is not sg and o["bbox_px"][2] <= sg["bbox_px"][0] + 5 and re.search(r"[A-Za-z]{3}", o["text"])
                        and not re.search(r"\bSF\b|\btotal\b", o["text"], re.I) and abs((o["bbox_px"][1] + o["bbox_px"][3]) / 2 - cy) < h * 0.8
                        and sg["bbox_px"][0] - o["bbox_px"][2] < 900]
                if left:
                    o = max(left, key=lambda o: o["bbox_px"][2])
                    name, t = o["text"].strip(" -:."), o["text"] + " " + t
            key = (name.lower(), tm[0])
            if len(re.findall(r"[A-Za-z]", name)) < 4 or key in seen:
                continue
            seen.add(key)
            rows.append((name, _num(tm[0]), pt.page, sg["bbox_px"], t))
    if rows:  # one table: the page that carries most rows
        best = max({r[2] for r in rows}, key=lambda p: sum(1 for r in rows if r[2] == p))
        rows = [r for r in rows if r[2] == best]
    if len(rows) < 4:
        return None
    rows = rows[:25]
    lines = [f"- {n[:40]}: {v:,.0f} SF = {v * M2_PER_SF:,.1f} m² {{{i}}}" for i, (n, v, _p, _b, _t) in enumerate(rows, 1)]
    text = f"The sheet's table lists **{len(rows)}** areas (TOTAL row excluded; 1 SF = 0.0929 m²):\n" + "\n".join(lines)
    text = re.sub(r"\{(\d+)\}", r"[\1]", text)
    return _obj(question, doc_id, text, len(rows), "rows", [(p, b, t) for _n, _v, p, b, t in rows], "table rows with an SF figure", t0, 0.8)


def takeoff_sheet(question, doc_id, pts, t0):
    """quantity take-off on a PDF sheet: the table's room areas; everything a PDF cannot give is 'not in this file'."""
    from engine.quantity_takeoff import TAKEOFF_Q, NIF
    if not TAKEOFF_Q.search(question):
        return None
    r = area_by_type("area of each room", doc_id, pts, t0)
    if r is None:
        return None
    rows = [f"| Floor area - {m.group(1)} | {m.group(2)} | m2 | [{m.group(3)}] |"
            for m in re.finditer(r"^- (.+?): [\d,]+ SF = ([\d,.]+) m² \[(\d+)\]", r["answer"]["text_md"], re.M)]
    miss = [f"| {k} | {NIF} |  |  |" for k in ("Baseboard", "Doors", "Windows", "Slab area by type", "Piping by system")]
    r["answer"]["text_md"] = ("**Quantity take-off** from the sheet's own table, no model call. A PDF sheet gives no wall, door or window geometry.\n\n"
                              "| Item | Quantity | Unit | Source |\n|---|---|---|---|\n" + "\n".join(rows + miss))
    r["answer"]["unit"] = "rooms"
    return r


def area_total(question, doc_id, pts, t0):
    """TOTAL ... SF on a square-footage table, in m2, with the column arithmetic checked."""
    nm = re.search(r"\b(?:area|size)\s+of\s+(?:the\s+)?(.+?)[?.!]*$", question, re.I)
    if nm and not re.search(r"\b(total|floor|building|gross|whole|second|first|level|storey|story)\b", nm.group(1), re.I):
        return None  # a named room: never answer with the table total
    if BY_EACH.search(question):
        return None
    if not re.search(r"\b(area|square|floor space|m2|m²|sf|gross)\b", question, re.I) or re.search(r"\b(share|percent|%|proportion)\b", question, re.I):
        return None
    for pt in pts:
        for s in pt.segs:
            if not re.search(r"\btotal\b", s["text"], re.I):
                continue
            nums = _row_numbers(pt, s)
            if not nums:
                continue
            val, bb = nums[-1]
            word_after = any(str(w["text"]).upper().strip(".") in ("SF", "SQFT", "SQ", "S.F.") for w in pt.words if w.get("bbox_px")
                             and abs((w["bbox_px"][1] + w["bbox_px"][3]) / 2 - (bb[1] + bb[3]) / 2) < (bb[3] - bb[1]))
            if not word_after and not re.search(r"\bsf\b|sq", s["text"], re.I):
                continue
            col = [(_num(str(w["text"])), w["bbox_px"]) for w in pt.words if w.get("bbox_px") and SF_NUM.match(str(w["text"]).strip())
                   and abs((w["bbox_px"][0] + w["bbox_px"][2]) / 2 - (bb[0] + bb[2]) / 2) <= (bb[2] - bb[0]) * 0.8 and w["bbox_px"][3] < bb[1]]
            col.sort(key=lambda t: t[1][1])
            above = [v for v, _b in col]
            check = ""
            if above:
                sm = sum(above)
                check = (f" Check: the {len(above)} figures above add to {sm:,.0f} SF" +
                         (", matching the total." if abs(sm - val) < 0.5 else f"; the total differs by {val - sm:+,.0f} SF (the column may include sub-rows such as circulation, or omit rows such as exterior stairs), so check the table."))
            m2 = val * M2_PER_SF
            text = f"The area is **{val:,.0f} SF = {m2:,.1f} m²** (1 SF = 0.0929 m²).{check} {{marks}}"
            hits = [(pt.page, s["bbox_px"], s["text"]), (pt.page, bb, f"{val:,.0f}")]
            return _obj(question, doc_id, text, round(m2, 1), "m2", hits, f"table total {val:,.0f} SF -> m2; column sum {sum(above):,.0f}", t0)
    return None


def share_of_total(question, doc_id, pts, t0):
    m = re.search(r"\b(?:share|percent(?:age)?|proportion|fraction)\b.*?\b(?:of the (?:floor|building|area)\s+(?:is|that is)?\s*|is\s+)?(\w[\w ]*?)(?:[?.!]*$)", question, re.I)
    if not m or not re.search(r"\b(share|percent|proportion|fraction|%)", question, re.I):
        return None
    key = None
    for cand in re.findall(r"[a-z]{4,}", question.lower()):
        if cand in ("share", "floor", "building", "percentage", "percent", "proportion", "fraction", "what", "which", "total", "area"):
            continue
        key = cand
    if not key:
        return None
    for pt in pts:
        rowseg = next((s for s in pt.segs if re.search(key, s["text"], re.I) and _row_numbers(pt, s)), None)
        totseg = next((s for s in pt.segs if re.search(r"\btotal\b", s["text"], re.I) and _row_numbers(pt, s)), None)
        if rowseg and totseg:
            part, pb = _row_numbers(pt, rowseg)[-1]
            tot, tb = _row_numbers(pt, totseg)[-1]
            if tot and part and part <= tot:
                text = f"{key.capitalize()} is **{part:,.0f} of {tot:,.0f} SF = {part / tot * 100:.1f}%** of the total. {{marks}}"
                return _obj(question, doc_id, text, round(part / tot * 100, 1), "%", [(pt.page, rowseg["bbox_px"], rowseg["text"]), (pt.page, totseg["bbox_px"], totseg["text"])],
                            f"table row {key} / table total", t0)
    return None


def note_sum(question, doc_id, pts, t0):
    """'total trench length': the lengths listed in the note that names the thing, summed."""
    if not re.search(r"\btotal\b|\bsum\b|\baltogether\b|\bcombined\b", question, re.I):
        return None
    words = [w for w in re.findall(r"[a-z]{4,}", question.lower()) if w not in ("total", "length", "lengths", "what", "much", "sheet", "combined", "altogether", "drawing", "there")]
    for key in words:
        for pt in pts:
            for s in pt.segs:
                if not re.search(key, s["text"], re.I):
                    continue
                body = s["text"]
                # a note may continue on the next lines: take the segments right below, up to the next numbered note
                nums = re.findall(r"(?<![\d.@])(\d{3,5})(?:\s*(?:mm|m)\b)?(?![\d.])", body)
                if len(nums) >= 2:
                    vals = [int(n) for n in nums]
                    unit = "mm" if re.search(r"\bmm\b", body) or max(vals) > 100 else "m"
                    tot = sum(vals)
                    tail = f" = {tot / 1000:g} m" if unit == "mm" else ""
                    text = f"The total is **{' + '.join(f'{v:,}' for v in vals)} = {tot:,} {unit}**{tail}, from the note. {{marks}}"
                    return _obj(question, doc_id, text, tot, unit, [(pt.page, s["bbox_px"], s["text"])], f"sum of {len(vals)} lengths in the note naming '{key}'", t0)
    return None


SIZE = re.compile(r"\d{2,4}\s*[xX×]\s*\d{2,4}(?:\s*[xX×]\s*\d{2,4})?(?:\s*(?:mm|DEEP))?|\b\d{1,3}(?:[-\s]\d/\d)?\s*(?:\"|”|″|IN\b|INCH)", re.I)


def size_of(question, doc_id, pts, t0):
    """'suction header size', 'sump size': the dimension printed in the segment that names the thing."""
    if not re.search(r"\b(size|diameter|dimension|dimensions|how (?:big|large|wide|deep))\b", question, re.I):
        return None
    stop = {"size", "what", "diameter", "dimension", "dimensions", "this", "drawing", "sheet", "the", "of", "is", "how", "big", "large", "wide", "deep"}
    keys = [w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in stop]
    if not keys:
        return None
    best = None
    pfx = []
    phrase = _norm_noun(" ".join(keys))
    for k, v in NOUN_PREFIX.items():
        if k in phrase and k not in ("vent", "pump", "sink"):
            pfx += v
    if pfx:
        keys = [w for w in keys if w not in ("vent", "drain", "pipe", "waste", "line", "from")] or keys
    for pt in pts:
        for sg in pt.segs:
            t = sg["text"]
            tag_hit = any(re.search(rf"\b{p}-?\d", t) for p in pfx)
            if (all(re.search(re.escape(k.rstrip("s")), t, re.I) for k in keys) or (pfx and tag_hit)) and SIZE.search(t):
                best = (pt, sg)
                break
        if best:
            break
    if not best:
        return None
    pt, sg = best
    m = SIZE.search(sg["text"]).group(0).strip()
    text = f"The size is **{m}** (printed: \"{sg['text'][:120]}\"). {{marks}}"
    return _obj(question, doc_id, text, m, None, [(pt.page, sg["bbox_px"], sg["text"])], "dimension printed in the label naming the thing", t0, 0.8)


def room_count(question, doc_id, pts, t0):
    """'how many dorm rooms on this floor': unique room numbers (one 3-digit series, e.g. 201..248) printed on the plan."""
    if not re.search(r"\bhow many\b.*\b(rooms?|units?|suites?)\b", question, re.I):
        return None
    if re.search(r"\b(bath|toilet|restroom|stair|exit|door)\w*\b", question, re.I):
        return None
    hits = {}
    for pt in pts:
        for w in pt.words:
            t = str(w.get("text") or "").strip(".,;:()")
            if re.fullmatch(r"[1-9]\d{2}[A-Z]?", t) and w.get("bbox_px"):
                hits.setdefault(t, (pt.page, w["bbox_px"]))
    if len(hits) < 8:
        return None
    from collections import Counter
    series = Counter(k[0] for k in hits)
    lead, n = series.most_common(1)[0]
    if n < 8 or n < 0.7 * len(hits):
        return None
    keys = sorted(k for k in hits if k[0] == lead)
    text = (f"There are **{n}** numbered rooms on this floor ({keys[0]} to {keys[-1]}), counted from the room numbers printed on the plan. "
            f"I cannot tell from the numbers alone how many are dorm rooms versus other room types, and one floor only: "
            f"other floors are not on this sheet. {{marks}}")
    return _obj(question, doc_id, text, n, "count", [(hits[k][0], hits[k][1], k) for k in keys], f"unique room numbers in series {lead}xx", t0, 0.6)


def overall_width(question, doc_id, pts, t0):
    """'width of the north wing': the largest feet-inch (or mm) dimension string on the sheet, when the question names a wing/building."""
    if not re.search(r"\bwidth\b", question, re.I) or not re.search(r"\b(wing|building|block|overall)\b", question, re.I):
        return None
    best = None
    for pt in pts:
        for sg in pt.segs:
            for m in re.finditer(r"\b\d{1,3}'\s*-\s*\d{1,2}(?:\s+\d/\d)?\s*(?:\"|”|″)?", sg["text"]):
                v = feet_inches_to_m(m.group(0))
                if v and (best is None or v > best[0]):
                    best = (v, m.group(0).strip(), pt, sg)
    if not best:
        return None
    v, shown, pt, sg = best
    text = (f"The largest overall dimension printed on the sheet is **{shown}** ({v:.2f} m). This is the overall plan dimension; "
            f"I cannot confirm it is that particular wing's width. {{marks}}")
    return _obj(question, doc_id, text, shown, None, [(pt.page, sg["bbox_px"], sg["text"])], "largest feet-inch dimension string", t0, 0.5)


REBAR = re.compile(r"(?:D|Ø|ø|T|Y|#)\s?\d{1,2}\s*@\s*\d{2,4}(?:\s*(?:O\.?C\.?|EW|E\.?W\.?|mm))?|\d+\s*[Øø]\s*\d+\s*@\s*\d+", re.I)


def rebar_of(question, doc_id, pts, t0):
    if not re.search(r"\b(reinforc\w*|rebar|bars?)\b", question, re.I):
        return None
    th = re.search(r"\b(\d{2,3})\s?mm\b", question)
    for pt in pts:
        for s in pt.segs:
            if not REBAR.search(s["text"]):
                continue
            if th and not re.search(rf"\b{th.group(1)}\b", s["text"]):
                continue
            if not th and not re.search(r"slab|footing|wall|beam", s["text"], re.I):
                continue
            r = REBAR.search(s["text"]).group(0).strip()
            what = f"the {th.group(1)} mm slab" if th else "it"
            text = f"The reinforcement of {what} is **{r}** (as noted: \"{s['text'][:120]}\"). {{marks}}"
            return _obj(question, doc_id, text, r, None, [(pt.page, s["bbox_px"], s["text"])], "rebar notation next to the slab thickness", t0)
    return None


def cross_sheet(question, doc_id, pts, root, t0, other_docs=()):
    """'where is the pipe penetration detail' -> 'see M-303', not uploaded."""
    if not re.search(r"\b(where|which sheet|what sheet|detail|see)\b", question, re.I):
        return None
    words = [w for w in re.findall(r"[a-z]{4,}", question.lower()) if w not in ("where", "which", "sheet", "what", "detail", "details", "there", "this", "drawing", "located", "shown", "found")]
    have = set(sheet_ids(doc_id, root))
    for d in other_docs:
        have |= sheet_ids(d, root)
    for pt in pts:
        for s in pt.segs:
            txt = s["text"]
            if not any(re.search(w, txt, re.I) for w in words):
                continue
            refs = re.findall(r"\b(?:SEE|SHEET|DETAIL|DWG)\b[^.]{0,40}?\b([A-Z]{1,2}-\d{3}[A-Z]?)\b|\b([MSAPEC]-\d{3}[A-Z]?)\b", txt, re.I)
            ids = [a or b for a, b in refs]
            ids = [i.upper() for i in ids if i.upper() not in have]
            if ids:
                i = ids[0]
                text = (f"The detail is on sheet **{i}** (\"{txt[:120]}\"), which is **not part of this upload**, so I cannot show or read it. "
                        f"Upload {i} to see the detail. {{marks}}")
                return _obj(question, doc_id, text, i, None, [(pt.page, s["bbox_px"], txt)], f"cross-sheet reference to {i}, not among the uploaded sheets", t0, 0.85)
    return None


def _read(doc_id, root):
    try:
        from vision.sheet_text import read_sheet
        tp = Path(root) / doc_id / "text-1.json"
        return read_sheet(str(tp)) if tp.exists() else None
    except Exception:
        return None


def sheet_identity(question, doc_id, pts, t0, root=None):
    """'what is this drawing / which sheet number / sheet title': the title block, with its boxes."""
    if not re.search(r"\b(what (?:is|sheet is) (?:this|the)\s*(?:drawing|sheet|plan|page)|which sheet|what sheet|sheet (?:number|no\.?|id|title|name)|title of (?:this|the) (?:sheet|drawing)|what does this (?:sheet|drawing) show)\b", question, re.I):
        return None
    r = _read(doc_id, root) if root is not None else None
    sh = (r or {}).get("sheet") or {}
    sid, title = sh.get("id"), (sh.get("title") or "").strip()
    if not sid or not re.match(r"^[A-Z]{1,2}[-.]?\d", sid) or len(title) > 70 or len(title) < 4 or (sh.get("confidence") or 0) < 0.6:
        return None
    hits = [(1, sh[k], q) for k, q in (("id_box", sid), ("title_box", title)) if sh.get(k)]
    if not hits:
        return None
    return _obj(question, doc_id, f"This is sheet **{sid}**, **{title.title()}**. {{marks}}", sid, None, hits, "title block", t0, 0.9)


def pipe_sizes(question, doc_id, pts, t0, root=None):
    """'what are the pipe sizes': the labelled sizes on the sheet with counts."""
    if not re.search(r"\bpipe\s+sizes?\b|\bsizes? of (?:the )?pipes?\b|\bwhat (?:size|sizes) .*\bpipes?\b", question, re.I):
        return None
    r = _read(doc_id, root) if root is not None else None
    ps = ((r or {}).get("tags") or {}).get("pipe_size") or {}
    if not ps:
        return None
    items = sorted(ps.items(), key=lambda kv: -kv[1]["count"])[:8]
    hits = [(1, kv[1]["boxes"][0], kv[0]) for kv in items if kv[1].get("boxes")]
    lst = "; ".join(f"{k} x{v['count']}" for k, v in items)
    return _obj(question, doc_id, f"Pipe sizes labelled on this sheet: {lst}. {{marks}}", len(items), "sizes", hits, "pipe size labels", t0, 0.85)


def answer(question: str, doc_ids: list[str], root, t0=None, other_docs=()):
    """First handler that recognises the question wins; None sends it to the reader."""
    t0 = t0 or time.perf_counter()
    if not doc_ids:
        return None
    doc_id = doc_ids[0]
    pts = _pages(doc_id, root)
    if not any(pt.words for pt in pts):
        return None
    for fn in (sheet_identity, pipe_sizes):
        res = fn(question, doc_id, pts, t0, root)
        if res is not None:
            res["doc_ids"] = list(doc_ids)
            return res
    for fn in (tag_count, scale_answer, share_of_total, room_area, schedule_rows, takeoff_sheet, area_by_type, area_total, note_sum, rebar_of, size_of, room_count, overall_width):
        res = fn(question, doc_id, pts, t0)
        if res is not None:
            res["doc_ids"] = list(doc_ids)
            return res
    res = cross_sheet(question, doc_id, pts, root, t0, other_docs or doc_ids[1:])
    if res is not None:
        res["doc_ids"] = list(doc_ids)
    return res
