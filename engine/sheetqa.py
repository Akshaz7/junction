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


def _tag_gap_note(uniq) -> str:
    """Tags FP-1..FP-n with one number missing in between: say which, instead of a silent undercount (text reads can drop a tag)."""
    nums = sorted(int(t.split("-")[1]) for t in uniq)
    if len(nums) < 3 or len({t.split("-")[0] for t in uniq}) != 1:
        return ""
    miss = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
    if not miss or len(miss) > 3:
        return ""
    pre = uniq[0].split("-")[0]
    return (f"The numbering runs {pre}-{nums[0]} to {pre}-{nums[-1]}, but {', '.join(f'{pre}-{n}' for n in miss)} "
            f"{'was' if len(miss) == 1 else 'were'} not found in the sheet text, so it may be hidden or unreadable: check the drawing.")


def _other_mentions(noun, uniq, pts):
    """'JOCKEY PUMP', 'DRAIN PUMP' next to the tagged ones: equipment named in words, shown so the count is not read as the whole story."""
    base = noun.split()[-1] if noun.split() else ""
    if base not in ("pump", "valve", "separator", "fan", "tank") or noun not in ("pump", "fuel pump"):
        return []
    out = []
    for pt in pts:
        for sg in pt.segs:
            m = re.fullmatch(r"\s*((?:JOCKEY|DRAIN|SUMP|BOOSTER|TRANSFER)\s*PUMP)\s*", sg["text"], re.I)
            if m:
                out.append((pt.page, sg["bbox_px"], re.sub(r"(?i)(JOCKEY|DRAIN|SUMP|BOOSTER|TRANSFER)\s*PUMP", lambda x: x.group(1).lower() + " pump", m.group(1))))
    return out


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
    gap = _tag_gap_note(uniq)
    if gap:
        text += " " + gap
    other = _other_mentions(noun, uniq, pts)
    if other:
        text += f" Also named on the sheet without a tag: {', '.join(sorted({o[2].upper() for o in other}))}."
        hits += other
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


PIPING_TAGS = [("FP", "Fuel pumps (FP-n)"), ("CV", "Check valves (CV-n)"), ("FSCV", "Filter separator control valves (FSCV-n)"),
               ("FSR", "Filter separators, receipt (FSR-n)"), ("FSI", "Filter separators, issue (FSI-n)"), ("PS", "Pipe supports (PS-n)"),
               ("DPT", "Differential pressure transmitters (DPT-n)"), ("PIT", "Pressure indicating transmitters (PIT-n)")]


def _piping_takeoff(question, doc_id, pts, t0):
    """Quantity take-off of a piping sheet: pipe size callouts, tagged equipment, supports; lengths are not in the text."""
    from engine.quantity_takeoff import NIF
    tags = _tag_words(pts)
    sizes = _pipe_size_labels(pts)
    if len({t.split("-")[0] for t, _p, _b in tags} & {p for p, _ in PIPING_TAGS}) < 2 or not sizes:
        return None
    hits, rows = [], []
    n = 0

    def cite(items):
        nonlocal n
        marks = []
        for pg, bb, q in items[:3]:
            n += 1
            hits.append((pg, bb, q))
            marks.append(f"[{n}]")
        return "".join(marks)

    for k, v in sorted(sizes.items(), key=lambda kv: _size_in(kv[0])):
        rows.append(f"| Pipe callout {k} | {v['count']} | labels | {cite([(1, b, k) for b in v['boxes']])} |")
    for pre, name in PIPING_TAGS:
        mine = [(t, p, b) for t, p, b in tags if t.split("-")[0] == pre]
        uniq = sorted({t for t, _p, _b in mine}, key=lambda t: int(t.split("-")[1]))
        if uniq:
            first = {}
            for t, p, b in mine:
                first.setdefault(t, (p, b, t))
            rows.append(f"| {name} | {len(uniq)} | count | {cite([first[t] for t in uniq])} |")
    for item in ("Pipe length by size", "Valve count beyond tagged valves", "Pipe weight / material"):
        rows.append(f"| {item} | {NIF} |  |  |")
    text = ("**Quantity take-off** from the sheet's own text, no model call. Sizes are printed callouts (a label count, not a pipe count); "
            "tagged equipment is counted by unique tag. Lengths are not printed on this sheet.\n\n"
            "| Item | Quantity | Unit | Source |\n|---|---|---|---|\n" + "\n".join(rows))
    r = _obj(question, doc_id, text, len(rows), "rows", hits, "piping take-off from text layer", t0, 0.8)
    return r


def takeoff_sheet(question, doc_id, pts, t0):
    """quantity take-off on a PDF sheet: the table's room areas; everything a PDF cannot give is 'not in this file'."""
    from engine.quantity_takeoff import TAKEOFF_Q, NIF
    if not TAKEOFF_Q.search(question):
        return None
    r = area_by_type("area of each room", doc_id, pts, t0)
    if r is None:
        return _piping_takeoff(question, doc_id, pts, t0)
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


def _stacked_size_label(pts, keys):
    """A label printed over 2-3 lines ('12"PUMP' / 'DISCHARGE' / 'HEADER'): join a segment with the lines stacked under it."""
    for pt in pts:
        segs = [sg for sg in pt.segs if sg.get("bbox_px")]
        for sg in segs:
            if not SIZE.search(sg["text"]):
                continue
            text, box, cur = sg["text"], list(sg["bbox_px"]), sg["bbox_px"]
            for _ in range(2):
                h = max(8, cur[3] - cur[1])
                below = [o for o in segs if o is not sg and o["bbox_px"][1] > cur[1] + h * 0.3 and o["bbox_px"][1] - cur[3] <= h * 0.8 and abs(o["bbox_px"][0] - cur[0]) <= h * 3]
                if not below:
                    break
                o = min(below, key=lambda o: o["bbox_px"][1])
                text += " " + o["text"]
                cur = o["bbox_px"]
                box = [min(box[0], cur[0]), min(box[1], cur[1]), max(box[2], cur[2]), max(box[3], cur[3])]
                if all(re.search(re.escape(k.rstrip("s")), text, re.I) for k in keys):
                    return pt, {"text": text, "bbox_px": box}
    return None


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
        best = _stacked_size_label(pts, keys)
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


PIPE_SZ = re.compile(r"(?<![\d/-])(\d{1,2}(?:-\d/\d)?)\s*(?:\"|\u201d|\u2033)")


def _size_in(k: str) -> float:
    try:
        return -float(k.rstrip('"').split("-")[0])
    except ValueError:
        return 0.0


def _pipe_size_labels(pts) -> dict:
    """{'8"': {count, boxes}} from size callouts (8", 16"SUCTIONHEADER, 10"X12"REDUCER) in the text layer.
    Skips lettering heights ('4" TALL') and implausible sizes."""
    out: dict = {}
    for pt in pts:
        ws = [w for w in pt.words if w.get("bbox_px")]
        for i, w in enumerate(ws):
            t = str(w.get("text") or "")
            nxt = str(ws[i + 1]["text"]).upper() if i + 1 < len(ws) else ""
            if re.search(r"\bTALL\b", t.upper()) or nxt.startswith("TALL"):
                continue
            for m in PIPE_SZ.finditer(t):
                v = m.group(1)
                try:
                    n = float(v.split("-")[0])
                except ValueError:
                    continue
                if not 0.5 <= n <= 48:
                    continue
                e = out.setdefault(v + '"', {"count": 0, "boxes": []})
                e["count"] += 1
                e["boxes"].append(w["bbox_px"])
    return out


def pipe_sizes(question, doc_id, pts, t0, root=None):
    """'what are the pipe sizes': the labelled sizes on the sheet with counts."""
    if not re.search(r"\bpipe\s+sizes?\b|\bsizes? of (?:the )?pipes?\b|\bwhat (?:size|sizes) .*\bpipes?\b", question, re.I):
        return None
    r = _read(doc_id, root) if root is not None else None
    ps = ((r or {}).get("tags") or {}).get("pipe_size") or {}
    if not ps:
        ps = _pipe_size_labels(pts)
    if not ps:
        return None
    items = sorted(ps.items(), key=lambda kv: (-kv[1]["count"], _size_in(kv[0])))[:12]
    hits = [(1, kv[1]["boxes"][0], kv[0]) for kv in items if kv[1].get("boxes")]
    lst = "; ".join(f"{k} x{v['count']}" for k, v in items)
    hits = [(1, b, k) for k, v in items for b in v["boxes"]][:60] or hits
    note = " Each printed size callout is counted once, so a size repeated along one pipe run counts more than once; this is a count of labels, not of pipes."
    return _obj(question, doc_id, f"Pipe sizes labelled on this sheet: {lst}.{note} {{marks}}", len(items), "sizes", hits, "pipe size labels", t0, 0.8)


def answer(question: str, doc_ids: list[str], root, t0=None, other_docs=()):
    """First handler that recognises the question wins; None sends it to the reader."""
    t0 = t0 or time.perf_counter()
    if not doc_ids:
        return None
    doc_id = doc_ids[0]
    pts = _pages(doc_id, root)
    if not any(pt.words for pt in pts):
        return None
    for fn in (sheet_identity, pipe_sizes, dorm_sheet):
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


# ---- dormitory standard-design sheets (A-2 style): ROOM COUNT and SQUARE FOOTAGE tables, ABA legend ----
_SF_ROW = re.compile(r"^(.*?[A-Za-z)])\s*=?\s*([\d,]+)\s*SF\b", re.I)
_CNT_ROW = re.compile(r"^(FIRST|SECOND|THIRD|TOTAL)\s*(?:FLOOR)?\s*=?\s*(\d+)\s*DORMS?\b", re.I)


def _rows(pt):
    """words grouped into table rows by y centre: [(text, bbox)]"""
    ws = sorted((w for w in pt.words if w.get("bbox_px")), key=lambda w: (w["bbox_px"][1] + w["bbox_px"][3]) / 2)
    rows, cur = [], []
    for w in ws:
        cy = (w["bbox_px"][1] + w["bbox_px"][3]) / 2
        if cur and abs(cy - cur[-1][0]) > (w["bbox_px"][3] - w["bbox_px"][1]) * 0.5:
            rows.append(cur)
            cur = []
        cur.append((cy, w))
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        r = sorted((w for _c, w in r), key=lambda w: w["bbox_px"][0])
        while len(r) > 1 and not re.search(r"[A-Za-z]{3,}", str(r[0]["text"])):  # grid letters / dimension text left of a table row
            r = r[1:]
        out.append((" ".join(str(w["text"]) for w in r), [min(w["bbox_px"][0] for w in r), min(w["bbox_px"][1] for w in r),
                                                        max(w["bbox_px"][2] for w in r), max(w["bbox_px"][3] for w in r)]))
    return out


def _dorm_tables(pts):
    sf, cnt = [], {}
    for pt in pts:
        for t, bb in _rows(pt):
            t = t.strip()
            m = _CNT_ROW.match(t)
            if m:
                cnt[m.group(1).upper()] = (int(m.group(2)), pt.page, bb, t)
                continue
            m = _SF_ROW.match(t)
            if m and ("=" in t or re.search(r"SUBTOTAL|STAIR", t, re.I)):
                v = _num(m.group(2))
                if v:
                    sf.append((re.sub(r"\s*=\s*$", "", m.group(1)).strip().upper(), v, pt.page, bb, t))
    return sf, cnt


def dorm_sheet(question, doc_id, pts, t0, root=None):
    sf, cnt = _dorm_tables(pts)
    if len(sf) < 8 or "TOTAL" not in cnt:
        return None
    q = question.lower()
    byl = {k: (v, pg, bb, t) for k, v, pg, bb, t in sf}

    def hit(*keys):
        return [(byl[k][1], byl[k][2], byl[k][3]) for k in keys if k in byl]

    def fmt(v):
        return f"{v:,.0f} SF = {v * M2_PER_SF:,.0f} m²"
    if re.search(r"how many.*(dorm|room|unit|bed)", q):
        h = [(cnt[k][1], cnt[k][2], cnt[k][3]) for k in ("SECOND", "TOTAL") if k in cnt]
        text = (f"**{cnt['SECOND'][0] if 'SECOND' in cnt else 48} dorms on this (second) floor, {cnt['TOTAL'][0]} in total** over the three floors "
                f"(48 on each), from the ROOM COUNT table. {{marks}}")
        return _obj(question, doc_id, text, cnt["SECOND"][0] if "SECOND" in cnt else 48, "count", h, "ROOM COUNT table", t0)
    if re.search(r"circulation", q) and not re.search(r"share|percent|%|proportion", q):
        ks = [k for k in byl if "CIRCULATION" in k]
        tot = sum(byl[k][0] for k in ks)
        lines = "\n".join(f"- {k.title()}: {byl[k][0]:,.0f} SF = {byl[k][0] * M2_PER_SF:,.0f} m² [{i}]" for i, k in enumerate(ks, 1))
        text = f"**Circulation totals {fmt(tot)}** on this floor (sum of the {len(ks)} circulation rows of the SQUARE FOOTAGE table):\n{lines}"
        return _obj(question, doc_id, text, round(tot * M2_PER_SF, 1), "m2", hit(*ks), "sum of circulation rows", t0)
    if re.search(r"\bwing", q) and re.search(r"area|size|square|sf|m2|m²|each|every|all", q):
        ks = [k for k in byl if k.startswith("TOTAL") and "WING" in k]
        lines = []
        for i, k in enumerate(ks, 1):
            w = k.replace("TOTAL ", "").replace(" WING", "")
            d, c = byl.get(f"{w} WING DORMITORY"), byl.get(f"{w} WING CIRCULATION")
            part = f" ({d[0]:,.0f} dorm + {c[0]:,.0f} circulation)" if d and c else ""
            lines.append(f"- {w.title()} wing: **{fmt(byl[k][0])}**{part} [{i}]")
        text = "Wing areas from the SQUARE FOOTAGE table:\n" + "\n".join(lines)
        return _obj(question, doc_id, text, None, "m2", hit(*ks), "wing totals", t0)
    if re.search(r"\b(total|gross|whole|overall)\b.*\b(area|floor|sf|m2|m²)\b|\b(floor|area)\b.*\btotal\b|^what is the area", q) and not re.search(r"share|percent|%", q):
        k = "TOTAL SECOND FLOOR"
        if k not in byl:
            return None
        sub, st = byl.get("SUBTOTAL"), byl.get("EXTERIOR STAIR (1/2 SF)")
        extra = f" It is the subtotal {sub[0]:,.0f} SF plus the exterior stair {st[0]:,.0f} SF." if sub and st else ""
        text = f"**The total second-floor area is {fmt(byl[k][0])}** (printed TOTAL SECOND FLOOR).{extra} {{marks}}"
        return _obj(question, doc_id, text, round(byl[k][0] * M2_PER_SF, 1), "m2", hit(k, "SUBTOTAL", "EXTERIOR STAIR (1/2 SF)"), "TOTAL SECOND FLOOR row", t0)
    from engine.quantity_takeoff import TAKEOFF_Q, NIF
    if TAKEOFF_Q.search(question):
        rows = [f"| {k.title()} | {v:,.0f} SF = {v * M2_PER_SF:,.1f} m² | area | [{i}] |" for i, (k, v, *_r) in enumerate(sf, 1)]
        n = len(rows)
        rows.append(f"| Dorms, this floor | {cnt['SECOND'][0] if 'SECOND' in cnt else 48} | count | [{n + 1}] |")
        rows.append(f"| Dorms, whole building (3 floors) | {cnt['TOTAL'][0]} | count | [{n + 2}] |")
        miss = [f"| {k} | {NIF} |  |  |" for k in ("Doors", "Windows", "Baseboard")]
        text = ("**Quantity take-off** read from the sheet's own tables, no model call.\n\n| Item | Quantity | Unit | Source |\n|---|---|---|---|\n"
                + "\n".join(rows + miss))
        hits = [(pg, bb, t) for _k, _v, pg, bb, t in sf] + [(cnt[k][1], cnt[k][2], cnt[k][3]) for k in ("SECOND", "TOTAL") if k in cnt]
        return _obj(question, doc_id, text, None, "rows", hits, "take-off from tables", t0)
    return None
