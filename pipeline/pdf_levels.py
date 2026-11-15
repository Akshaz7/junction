"""Storeys, levels and the column grid of a vector PDF drawing set (what a native IFC carries and a plain plan misses).

    storey_info(page, region=None) -> {"name","number","elevation_m","height_m","source","elevation_source",
                                       "height_source","ceiling_m"}
        One page: storey name/number from the title block and level captions ('2ND FLOOR', 'Level 02',
        'FLOOR PLAN - SECOND FLOOR', '1. OG', '3. krs', 'Kerros 3', 'Erdgeschoss'), elevation from level marks
        ('+9.000', 'FFL 8.950', "EL. 100'-0\""), storey height from floor-to-floor notes, else ceiling heights
        ('h=2700', "CLG. 9'-0\"") + slab.
    level_table(page) -> [{"name","number","elevation_m"}]
        Level datums printed on a section/elevation sheet ('SECOND FLOOR' above "EL. 112'-0\""): used to give plan
        pages of the same set their elevation.
    grid(page) -> [{"tag","p0","p1"}]
        Column-grid axes: a long thin (often dash-dot) line ending in a bubble (small circle with a 1-3 character
        letter/number tag). Page pt, top-left origin, y down.
    storeys(pages, planmaps) -> [{"page_index","name","number","elevation_m","z_m","height_m","offset_pt":[dx,dy],
                                  "rotation_deg","offset_m":[dx,dy],"m_per_pt","source","align":{...}}]
        Plan pages of a set, ordered bottom to top, missing elevations inferred from storey heights, each page aligned
        into a common frame (the reference page's pt frame) by its column grid (matching tags), else its building
        footprint: p' = Rot(rotation_deg) @ p + offset_pt (pt, y down); offset_m = offset_pt * reference m_per_pt.
    storeys_from_planmaps(planmaps)  same, from plan maps only (their provenance.storey / provenance.grid).
    planmap_provenance(page, pm, s) -> {"storey": {...}, "grid": [...]}   the plan map's provenance keys.
Pure functions over pdf_vector.load_page dicts and plan-map dicts; numpy + shapely only.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

FT = 0.3048
IN = 0.0254
DEFAULT_STOREY_M = 3.0
SLAB_M = 0.35            # ceiling height + this = floor-to-floor when only ceiling heights are printed
MIN_STOREY_M, MAX_STOREY_M = 2.4, 8.0

ORD = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
       "eighth": 8, "ninth": 9, "tenth": 10, "basement": -1, "lower": -1, "cellar": -1, "mezzanine": 1.5, "entresol": 1.5, "zwischengeschoss": 1.5, "parvi": 1.5,
       "attic": None, "roof": None, "penthouse": None, "upper": None, "main": 0}
_ORD_WORDS = "|".join(k for k in ORD)
# (regex, how to read the number) - most specific first. Number = printed floor number (only used for ordering).
NAME_PATTERNS = [
    (re.compile(r"\b(\d{1,2})\s*\.?\s*(?:ST|ND|RD|TH)\s+(?:FLOOR|LEVEL|STOREY|STORY)\b", re.I), "num"),
    (re.compile(rf"\b({_ORD_WORDS})\s+(?:FLOOR|LEVEL|STOREY|STORY)\b", re.I), "word"),
    (re.compile(r"\b(?:LEVEL|FLOOR|STOREY|STORY|LVL)\s*[-#.]?\s*(\d{1,2}|[BPGM]\d?)\b", re.I), "num"),
    (re.compile(r"(?<![\w.])(\d{1,2})\s*\.\s*(OG|UG|KRS|KERROS|KELLARIKERROS|VÅN|VAN|ETAGE|ÉTAGE|OBERGESCHOSS|"
                r"UNTERGESCHOSS|STOCK|PLAN|KORRUS|SAL|ETASJE|ETG|VERDIEPING)\b", re.I), "num_suffix"),
    # named storeys (basement / ground / attic words) before the generic 'PLAN 02': 'PLAN 02 - KÆLDER' is the cellar
    (re.compile(r"\b(KÆLDER|KAELDER|KELDER|KELLERGESCHOSS|KELLER|UNTERGESCHOSS|SOUTERRAIN|KÄLLARE|KJELLER|"
                r"KELDRIKORRUS|UNDERETASJE|DACHGESCHOSS|TAGETAGE|PÖÖNING|STUEETAGE|BEGANE\s+GROND)\b", re.I), "token"),
    (re.compile(r"\b(?:KERROS|VÅNING|VANING|ETAGE|PLAN|PIANO)\s+(\d{1,2})\b", re.I), "num"),
    (re.compile(r"\b(\d{1,2})\s*(?:ER|E|ÈME|EME)\s+ÉTAGE\b", re.I), "num"),
    (re.compile(r"^\s*(?:GRUNDRISS\s+)?(EG|UG|KG|DG)\s*$|\bGRUNDRISS\s+(EG|UG|KG|DG)\b", re.I), "token"),
    (re.compile(r"\b(ERDGESCHOSS|KELLARI|POHJAKERROS|REZ-DE-CHAUSS[ÉE]E|PIANO TERRA|"
                r"BOTTENVÅNING|SOUS-SOL|ULLAKKO)\b", re.I), "token"),
    (re.compile(r"\b(ROOF)\s+(?:PLAN|LEVEL|DECK)\b", re.I), "word"),
    (re.compile(r"\b(?:FLOOR|LEVEL)\s+PLAN\s*[-:]?\s*(\d{1,2})\s*(ST|ND|RD|TH)\b", re.I), "num_rev"),
    (re.compile(rf"\b(?:FLOOR|LEVEL)\s+PLAN\s*[-:]?\s*({_ORD_WORDS})\b", re.I), "word_rev"),
    (re.compile(r"\b(MEZZANINE|ENTRESOL|ZWISCHENGESCHOSS|PARVI)\b", re.I), "word"),
]
TOKEN_NUM = {"kælder": -1, "kaelder": -1, "kelder": -1, "kellergeschoss": -1, "keller": -1, "untergeschoss": -1,
             "souterrain": -1, "källare": -1, "kjeller": -1, "keldrikorrus": -1, "underetasje": -1, "dachgeschoss": None,
             "tagetage": None, "pööning": None, "stueetage": 0, "begane grond": 0,
             "erdgeschoss": 0, "eg": 0, "ug": -1, "kg": -1, "dg": None, "kellari": -1, "pohjakerros": 0,
             "rez-de-chaussée": 0, "rez-de-chaussee": 0, "piano terra": 0, "bottenvåning": 0, "sous-sol": -1,
             "ullakko": None}
TOKEN_NAME = {"eg": "EG", "ug": "UG", "kg": "KG", "dg": "DG"}
# elevation marks. groups: value, optional sign
LEVEL_M = re.compile(r"^(?:FFL|FFE|FFB|FL|SSL|TOS|T\.O\.S\.|OKFF|OKRD|LVL|EL|ELEV|LP|KP|VP)?\s*[.:=]?\s*"
                     r"([+\-±]\s?\d{1,3}[.,]\d{2,3})(?:\s*m)?$", re.I)
LEVEL_PREFIXED = re.compile(r"\b(?:FFL|FFE|SSL|TOS|OKFF|OKRD|LP|EL\.?|ELEV\.?|ELEVATION|LEVEL)\s*[.:=]?\s*"
                            r"([+\-±]?\s?\d{1,3}[.,]\d{2,3})\b", re.I)
LEVEL_FT = re.compile(r"(?:\b(?:EL|ELEV|ELEVATION|FFE|FFL|T\.?O\.?\s*(?:SLAB|PLY|STL|CONC|FLR)?|FIN\.?\s*FLR\.?)"
                      r"\.?\s*[:=]?\s*)?([+\-]?\d{1,4})\s*['’]\s*-?\s*(\d{1,2}(?:\s+\d/\d+)?)?\s*(?:\"|”|'')?", re.I)
EL_WORD = re.compile(r"\b(EL|ELEV|ELEVATION|FFE|FFL|T\.?O\.?|FIN\.?\s*FLR|LEVEL|LVL|SSL|BRG)\b\.?", re.I)
CEIL_MM = re.compile(r"(?:^|\s)(?:h|kh|rh|lh|CH|RH|LH|KORKEUS|HÖHE|HOEHE)\s*=\s*(\d{4})(?:\s*mm)?\b", re.I)
CEIL_FT = re.compile(r"\b(?:CLG|CEILING|CLG\.?\s*HT|CEILING\s+HEIGHT|CH|PLATE(?:\s+HT)?|A\.?F\.?F\.?)\.?\s*[:=@]?\s*"
                     r"(\d{1,2})\s*['’]\s*-?\s*(\d{1,2})?\s*\"?", re.I)
CEIL_FT_AFTER = re.compile(r"(\d{1,2})\s*['’]\s*-?\s*(\d{1,2})?\s*\"?\s*(?:CLG|CEILING|A\.?F\.?F\.?|PLATE)\b", re.I)
F2F = re.compile(r"\b(?:FLOOR[\s-]+TO[\s-]+FLOOR|F\s*[-/]\s*F|STOREY\s+HEIGHT|STORY\s+HEIGHT|KERROSKORKEUS|"
                 r"GESCHOSSH(?:Ö|OE)HE|VÅNINGSHÖJD)\b\.?\s*[:=]?\s*(\d{1,2}[.,]\d{1,3}|\d{4}|\d{1,2}\s*['’]\s*-?\s*\d{0,2}\"?)",
                 re.I)
TAG = re.compile(r"^(?:[A-Z]{1,2}(?:\.\d{1,2})?['’]?|\d{1,2}(?:\.\d{1,2})?[a-z]?['’]?|[A-Z]-?\d{1,2})$")


def _c(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _lines(words, gap_h: float = 2.5):
    """Words -> text lines [(text, bbox, words)] for horizontal text; a sort-and-sweep (n log n) version of
    pdf_semantics.lines, which is quadratic and too slow for the title-block scan of a 10k-word sheet."""
    ws = sorted((w for w in words if w.get("bbox") and (w.get("text") or "").strip()), key=lambda w: _c(w["bbox"])[1])
    rows, cur, cy0, h0 = [], [], None, None
    for w in ws:
        h = max(w["bbox"][3] - w["bbox"][1], 0.5)
        cy = _c(w["bbox"])[1]
        if cur and abs(cy - cy0) <= 0.45 * h0:
            cur.append(w)
            continue
        if cur:
            rows.append(cur)
        cur, cy0, h0 = [w], cy, h
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        by_h = {}
        for w in row:  # words of very different heights on one baseline are separate lines (title vs note)
            h = max(w["bbox"][3] - w["bbox"][1], 0.5)
            by_h.setdefault(round(math.log(h) / 0.4), []).append(w)
        for grp in by_h.values():
            grp.sort(key=lambda w: w["bbox"][0])
            h = max(max(w["bbox"][3] - w["bbox"][1] for w in grp), 0.5)
            seg = [grp[0]]
            for w in grp[1:] + [None]:
                if w is not None and w["bbox"][0] - seg[-1]["bbox"][2] <= gap_h * h:
                    seg.append(w)
                    continue
                bb = [min(v["bbox"][0] for v in seg), min(v["bbox"][1] for v in seg),
                      max(v["bbox"][2] for v in seg), max(v["bbox"][3] for v in seg)]
                out.append((" ".join(v["text"].strip() for v in seg), bb, seg))
                if w is not None:
                    seg = [w]
    return out


def _ft(feet, inch=None) -> float:
    v = abs(int(feet)) * FT
    if inch:
        parts = str(inch).split()
        v += int(parts[0]) * IN
        if len(parts) > 1 and "/" in parts[1]:
            a, b = parts[1].split("/")
            v += int(a) / max(int(b), 1) * IN
    return -v if str(feet).strip().startswith("-") else v


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(",", ".").replace("±", ""))


def parse_name(text: str):
    """(name, number) of a storey caption in one text line, or None. number = printed floor number (US/FI count the
    ground floor as 1, DE/UK as 0: only the order matters here)."""
    for rx, how in NAME_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        g = next(x for x in m.groups() if x)
        if how == "num":
            if g[0].upper() in "BPGM" and not g.isdigit():
                num = {"B": -1, "G": 0, "M": None, "P": None}[g[0].upper()]
                if g[0].upper() == "B" and len(g) > 1:
                    num = -int(g[1:])
            else:
                num = int(g)
        elif how == "num_suffix":
            num = int(g)
            if m.group(2).upper() in ("UG", "UNTERGESCHOSS", "KELLARIKERROS"):
                num = -num
        elif how == "num_rev":  # 'FLOOR PLAN 1ST' -> '1ST FLOOR'
            return f"{int(g)}{m.group(2).upper()} FLOOR", int(g)
        elif how == "word_rev":
            return f"{g.upper()} FLOOR", ORD.get(g.lower())
        elif how == "word":
            num = ORD.get(g.lower())
        else:
            num = TOKEN_NUM.get(re.sub(r"\s+", " ", g.lower()))
            if g.lower() in TOKEN_NAME:
                if g != g.upper():
                    continue  # 'eg'/'ug' as lowercase words in a note are not storey codes
                return TOKEN_NAME[g.lower()], num
        return re.sub(r"\s+", " ", m.group(0).strip()).upper(), num
    return None


def parse_elevation(text: str):
    """Elevation in m from a level mark, or None. Metric marks need a sign or an FFL/EL prefix; imperial need EL/FFE
    or a feet-inches value with a level word in the same line."""
    t = text.strip()
    m = LEVEL_M.match(t)
    if m:
        return _num(m.group(1))
    m = LEVEL_PREFIXED.search(t)
    if m:
        v = _num(m.group(1))
        if abs(v) < 400:
            return v
    if EL_WORD.search(t):
        for m in LEVEL_FT.finditer(t):
            if m.group(0).strip() and ("'" in m.group(0) or "’" in m.group(0)):
                v = _ft(m.group(1), m.group(2))
                if abs(v) < 400:
                    return round(v, 3)
    return None


def parse_ceiling(text: str):
    """Ceiling height in m from 'h=2700', 'CLG 9'-0"', '9'-0" CLG', else None."""
    m = CEIL_MM.search(text)
    if m:
        v = int(m.group(1)) / 1000
        return v if 2.0 <= v <= 6.0 else None
    for rx in (CEIL_FT, CEIL_FT_AFTER):
        m = rx.search(text)
        if m:
            v = _ft(m.group(1), m.group(2))
            if 2.0 <= v <= 6.0:
                return round(v, 3)
    return None


def parse_f2f(text: str):
    m = F2F.search(text)
    if not m:
        return None
    g = m.group(1)
    if "'" in g or "’" in g:
        p = re.match(r"(\d{1,2})\s*['’]\s*-?\s*(\d{0,2})", g)
        v = _ft(p.group(1), p.group(2) or None)
    else:
        v = _num(g)
        v = v / 1000 if v > 100 else v
    return round(v, 3) if MIN_STOREY_M <= v <= MAX_STOREY_M else None


def storey_info(page: dict, region=None) -> dict:
    """Storey name/number, elevation, storey height of one page (see module doc). Empty fields are None."""
    words = page.get("words") or []
    ls = _lines(words)
    out = {"name": None, "number": None, "elevation_m": None, "height_m": None, "source": None,
           "elevation_source": None, "height_source": None, "ceiling_m": None}
    cands = []
    for t, bb, _ in ls:
        r = parse_name(t)
        if r:  # biggest lettering wins (sheet title over captions); 'PLAN' in the line breaks ties
            cands.append((round(bb[3] - bb[1], 0), "PLAN" in t.upper(), -bb[1], r, t))
    if cands:
        _, _, _, (name, num), line = max(cands, key=lambda c: (c[0], c[1], c[2]))
        out.update(name=name, number=num, source=f"title '{line.strip()[:60]}'")
    from shapely.geometry import Point
    inside = lambda bb: region is None or region.contains(Point(_c(bb)))
    lv, ceil, f2f = [], [], []
    for t, bb, seg in ls:
        if not inside(bb):
            continue
        v = parse_elevation(t)
        if v is None:  # a mark split from its prefix: try word by word
            for w in seg:
                v = parse_elevation(w["text"])
                if v is not None:
                    break
        if v is not None:
            lv.append(v)
        c = parse_ceiling(t)
        if c:
            ceil.append(c)
        h = parse_f2f(t)
        if h:
            f2f.append(h)
    if lv:
        val, n = Counter(lv).most_common(1)[0]
        lo = min(lv)
        if n >= 2 or len(lv) == 1:
            out["elevation_m"] = val
            out["elevation_source"] = f"level mark {val:+.3f} ({n} of {len(lv)} marks)"
        elif len(set(lv)) <= 3 and max(lv) - lo < 1.0:  # a few marks of one floor (step, threshold): the lowest
            out["elevation_m"] = lo
            out["elevation_source"] = f"level mark {lo:+.3f} (lowest of {len(lv)} marks)"
    if f2f:
        out["height_m"] = Counter(f2f).most_common(1)[0][0]
        out["height_source"] = "floor-to-floor note"
    elif ceil:
        c = Counter(ceil).most_common(1)[0][0]
        out["ceiling_m"] = c
        out["height_m"] = round(min(max(c + SLAB_M, MIN_STOREY_M), MAX_STOREY_M), 2)
        out["height_source"] = f"ceiling height {c:.2f} m + {SLAB_M} m slab"
    return out


BARE_FT = re.compile(r"^[+\-]?(\d{1,4})\s*['’]\s*-?\s*(\d{1,2}(?:\s+\d/\d+)?)\s*[\"”]?$")
TAIL_FT = re.compile(r"(?<![\d/])([+\-]?\d{1,4})\s*['’]\s*-?\s*(\d{1,2}(?:\s+\d/\d+)?)\s*[\"”]\s*$")


def _bare_ft(text: str, named: bool = False):
    """A level datum printed as a bare feet-inch value ('9' - 3"') next to a storey caption on a section/elevation
    sheet, or trailing the caption ('MEZZANINE 9' - 3"'). Scale notes (1/8" = 1'-0") and plan titles are skipped."""
    t = text.strip()
    if "=" in t or re.search(r"\b(SCALE|PLAN|MASSSTAB|MITTAKAAVA)\b", t, re.I):
        return None
    m = BARE_FT.match(t) or (TAIL_FT.search(t) if named else None)
    if not m:
        return None
    v = _ft(m.group(1), m.group(2))
    return round(v, 3) if abs(v) < 400 else None


def level_table(page: dict) -> list:
    """Level datums on a section/elevation sheet: a storey caption with an elevation in the same line or stacked
    right under/over it (within 3 line heights, overlapping in x)."""
    ls = _lines(page.get("words") or [])
    names, elevs = [], []
    for t, bb, _ in ls:
        r = parse_name(t)
        e = parse_elevation(t)
        if e is None:
            e = _bare_ft(t, named=bool(r))
        if r and e is not None:
            names.append((r, bb, e))
        elif r:
            names.append((r, bb, None))
        elif e is not None:
            elevs.append((e, bb))
    out = {}
    for (name, num), bb, e in names:
        if e is None:
            h = max(bb[3] - bb[1], 1.0)
            near = [(abs(_c(eb)[1] - _c(bb)[1]), ev) for ev, eb in elevs
                    if abs(_c(eb)[1] - _c(bb)[1]) <= 3 * h and eb[0] <= bb[2] + 2 * h and eb[2] >= bb[0] - 2 * h]
            if not near:
                continue
            e = min(near)[1]
        out.setdefault(name, {"name": name, "number": num, "elevation_m": e})
    return list(out.values())


# ---------------------------------------------------------------------------------------------------------------
# sheet classification (text only: the page's words, no vector read)
# ---------------------------------------------------------------------------------------------------------------
# One regex per sheet kind, checked per title line in this order (first hit names the line): a 'ROOF PLAN', 'SITE
# PLAN' or 'MECHANICAL FLOOR PLAN' line is not a floor plan although it says PLAN. Words in EN/DE/FI/SV/DA/NO/NL/FR/
# IT/ES/ET, plus ISO 13567 / AIA-style sheet numbers as weak evidence (_SHEET_NO).
SHEET_RX = [
    ("schedule", re.compile(r"\b(schedules?|legend|drawing\s+(?:list|index)|sheet\s+index|index\s+of\s+drawings|"
                            r"tabelle|liste|luettelo|förteckning|fortegnelse|ruumiprogramm|tableau|tabla)\b", re.I)),
    ("elevation", re.compile(r"\b(elevations?|ansicht(?:en)?|julkisivu(?:t)?|fasad(?:er)?|facade|façade|opstalt|"
                             r"aanzicht(?:en)?|vaade|prospetto|alzado)\b", re.I)),
    ("section", re.compile(r"\b(sections?|schnitt(?:e)?|leikkau(?:s|kset)|sektion|snit|snitt|doorsnede|coupe|"
                           r"lõige|sezione|secci[oó]n)\b", re.I)),
    ("detail", re.compile(r"\b(details?|detalj(?:er)?|detaljer|detalje|detail(?:s)?|yksityiskohdat|detailplan)\b", re.I)),
    ("cover", re.compile(r"\b(cover(?:\s+sheet)?|title\s+sheet|perspectives?|renderings?|3d\s+views?|axonometric|"
                         r"isometric|general\s+notes|abbreviations|deckblatt|kansilehti|visuali[sz]ation)\b|"
                         r"(?:^|\s)-\s*3D\b|\b3D\s*$", re.I)),
    ("site", re.compile(r"\b(site\s*plan|plot\s*plan|location\s*plan|lageplan|asemapiirros|situationsplan|"
                        r"situasjonsplan|situatie|plan\s+de\s+situation|planimetria|asendiplaan)\b", re.I)),
    ("rcp", re.compile(r"\b(reflected\s+ceiling|ceiling\s+plan|rcp|deckenspiegel|alakattopiirustus)\b", re.I)),
    ("structural", re.compile(r"\b(foundation|footing|framing|structural|tragwerk|fundament|perustus|rakenne|"
                              r"bewehrung|reinforcement)\b", re.I)),
    ("mep", re.compile(r"\b(mechanical|hvac|plumbing|electrical|lighting|power|ventilation|sprinkler|fire\s+alarm|"
                       r"lüftung|heizung|sanitär|elektro|ilmanvaihto|lvi|sähkö|ventilation|vvs|el-plan|ventilatsioon|"
                       r"küte|plomberie|électricité)\b", re.I)),
    ("roof", re.compile(r"\b(roof\s*(?:plan|top)?|dachaufsicht|dachdraufsicht|dachplan|vesikatto|takplan|tagplan|"
                        r"dakplan|katuseplaan|plan\s+de\s+toiture)\b", re.I)),
    ("demo", re.compile(r"\b(demo(?:lition)?|abbruch|rückbau|purku|rivning|nedrivning|sloop)\b", re.I)),
    ("plan", re.compile(r"\b(floor\s*plans?|plans?|grundriss(?:e)?|pohja(?:piirustus)?|plan(?:ritning|tegning)|"
                        r"plattegrond(?:en)?|planta|pianta|plaan|layout)\b", re.I)),
]
PLAN_LIKE = {"plan", "mep", "roof", "demo", "rcp", "structural", "site"}
# title-block lines naming the design team, not the sheet ('Mechanical', 'Plumbing Engineer:', 'X Electrical Inc.')
FIRM_RX = re.compile(r"@|www\.|\.(?:com|net|org|fi|de|dk|se|no|ee|ch|at|nl)\b|\b(engineers?|engineering|consultants?|"
                     r"contractor|inc|llc|ltd|gmbh|oy|ab|as|aps|a/s|corp|company|associates|architects?|tel|phone|fax|"
                     r"ingenieur\w*|insinööri\w*|rådgiv\w*)\b|\d{3}[.\-\s]\d{3}[.\-\s]\d{4}", re.I)
# MEP / structural words name a sheet only next to a drawing word ('MECHANICAL PLAN', 'FOUNDATION PLAN')
DRAW_RX = re.compile(r"\b(plans?|layout|framing|diagram|riser|schematic|grundriss|piirustus|plaan|plan\w*|"
                     r"duct\w*|piping|routing|level|floor|storey|geschoss|kerros|korrus|etage|etasje)\b", re.I)
_SHEET_NO = re.compile(r"^(A|AR|ARK|S|M|P|E|FP|H|I|K|R|V)[-.\s]?(\d)(\d{2})(?:\.\d{1,2})?$", re.I)
_SERIES = {"A": {"1": "plan", "2": "elevation", "3": "section", "5": "detail", "6": "schedule", "9": "cover"},
           "S": "structural", "M": "mep", "P": "mep", "E": "mep", "FP": "mep", "H": "mep", "V": "mep"}


def _line_kind(text: str):
    for kind, rx in SHEET_RX:
        if rx.search(text):
            return kind
    return None


def _line_kind_after(text: str, skip: str):
    """The next SHEET_RX kind after `skip` (an MEP/structural word without a drawing word is a team/notes line)."""
    names = [k for k, _ in SHEET_RX]
    for kind, rx in SHEET_RX[names.index(skip) + 1:]:
        if kind not in ("mep", "structural") and rx.search(text):
            return kind
    return None


def classify_sheet(words: list, W: float, H: float) -> dict:
    """What a sheet shows, from its words alone (cheap: no vector read): {"kind", "score", "title", "storey",
    "sheet_no", "evidence", "scores"}. kind: plan | mep | elevation | section | schedule | cover | detail | site |
    roof | demo | rcp | structural | other. Title lines = lines in the title-block corner (right 22% / bottom 12% of
    the sheet, weight 3) and lettering >= 1.6x the median text height (view titles, weight 1); the first SHEET_RX hit
    names each line. A storey caption in the corner ('FLOOR PLAN - 1ST', 'Erdgeschoss') counts for plan. The sheet
    number's series (A1xx plans, A2xx elevations, S structural, M/E/P MEP) adds 1. `words`: [{"text","bbox"}],
    bbox in the same unit as W/H, y down."""
    out = {"kind": "other", "score": 0.0, "title": None, "storey": None, "sheet_no": None, "evidence": "no title words",
           "scores": {}}
    try:
        ws = [w for w in words or [] if w.get("bbox") and (w.get("text") or "").strip()]
        if not ws or not W or not H:
            return out
        hs = sorted(max(w["bbox"][3] - w["bbox"][1], 0.0) for w in ws if w["bbox"][2] - w["bbox"][0] >= 0.5 *
                    (w["bbox"][3] - w["bbox"][1]))
        med = hs[len(hs) // 2] if hs else 1.0
        sc, best, why = Counter(), {}, []
        storey, sno = None, None
        cand = []
        for t, bb, _ in _lines(ws):
            tt = t.strip()
            if not tt or len(tt) > 90 or FIRM_RX.search(tt):
                continue
            h = bb[3] - bb[1]
            if bb[2] - bb[0] < 0.8 * h:  # vertical / rotated text: heights are not lettering sizes
                continue
            corner = (bb[0] > 0.78 * W and bb[1] > 0.4 * H) or (bb[1] > 0.88 * H and bb[0] > 0.45 * W)
            big = h >= 1.6 * med
            if corner or big:
                cand.append((tt, h, corner))
        # the sheet title is the biggest kind-naming lettering of the title block; small corner lines weigh less
        hmax = max([h for tt, h, c in cand if c and _line_kind(tt)] or [0.0])
        for tt, h, corner in cand:
            m = _SHEET_NO.match(tt.replace(" ", "")) if corner else None
            if m:
                ser = _SERIES.get(m.group(1).upper()[:2]) or _SERIES.get(m.group(1).upper()[:1])
                k = ser.get(m.group(2)) if isinstance(ser, dict) else ser
                sno = sno or tt
                if k:
                    sc[k] += 1.0
                    why.append(f"sheet no {tt} -> {k}")
                continue
            k = _line_kind(tt)
            if k in ("mep", "structural") and not DRAW_RX.search(SHEET_RX[[x for x, _ in SHEET_RX].index(k)][1]
                                                                 .sub(" ", tt)):
                k = _line_kind_after(tt, k)
            wgt = (3.0 if h >= 0.75 * hmax else 1.5) if corner else 1.0
            if k is None and corner:
                r = parse_name(tt)
                if r and not re.search(r"\d\s*['’]", tt) and sc["_storey"] < 1:  # a storey caption, once
                    k, wgt = "plan", 1.5
                    sc["_storey"] += 1
            if k is None:
                continue
            sc[k] += wgt
            if wgt > best.get(k, (0, ""))[0]:
                best[k] = (wgt, tt)
            if k in PLAN_LIKE and corner and storey is None:
                storey = parse_name(tt)
            why.append(f"{'title block' if corner else 'view title'} '{tt[:40]}' -> {k}")
        sc.pop("_storey", None)
        if not sc:
            out["sheet_no"] = sno
            return out
        kind, score = max(sc.items(), key=lambda kv: (kv[1], kv[0] == "plan"))
        out.update(kind=kind, score=round(score, 2), title=(best.get(kind) or (0, None))[1], storey=storey,
                   sheet_no=sno, evidence="; ".join(why[:8]), scores=dict(sc))
    except Exception as e:  # noqa: BLE001
        out["evidence"] = f"error {type(e).__name__}: {e}"[:160]
    return out


# ---------------------------------------------------------------------------------------------------------------
# column grid
# ---------------------------------------------------------------------------------------------------------------
BUBBLE_D = (6.0, 60.0)    # bubble diameter range, pt (2-21 mm on paper)
MIN_AXIS_D = 6.0          # an axis is at least this many bubble diameters long


def _flat(page, F=None):
    """pdf_vector._flat once per grid() call (it costs ~2 s on a dense sheet and is cached only inside walls())."""
    if F is not None:
        return F
    from pipeline import pdf_vector
    return pdf_vector._flat(page)


def _bubbles(page, F=None):
    """[(cx, cy, r, tag)] circles with a grid tag inside."""
    F = _flat(page, F)
    bb = F["bbox"]
    if not len(bb):
        return []
    # circles (Bezier or flattened), also hexagon/square tags: closed, square bbox; the long axis line decides later
    k = np.flatnonzero(F["closed"] | ((F["n_curves"] >= 2) & (F["npts"] >= 8)))
    if not len(k):
        return []
    dx, dy = bb[k, 2] - bb[k, 0], bb[k, 3] - bb[k, 1]
    ok = (BUBBLE_D[0] <= dx) & (dx <= BUBBLE_D[1]) & (np.abs(dx - dy) < 0.12 * dx)
    k, dx = k[ok], dx[ok]
    if not len(k):
        return []
    allw = [w for w in page.get("words") or [] if (w.get("text") or "").strip() and w.get("bbox")]
    words = [w for w in allw if TAG.match(w["text"].strip())]
    if not words:
        return []
    from scipy.spatial import cKDTree
    ac = cKDTree(np.array([_c(w["bbox"]) for w in allw]))
    wc = np.array([_c(w["bbox"]) for w in words])
    wt = cKDTree(wc)
    wh = np.array([w["bbox"][3] - w["bbox"][1] for w in words])
    ww = np.array([w["bbox"][2] - w["bbox"][0] for w in words])
    C = np.column_stack([(bb[k, 0] + bb[k, 2]) / 2, (bb[k, 1] + bb[k, 3]) / 2])
    dist, jj = wt.query(C, k=1)
    hit = dist <= 0.2 * dx  # tag centred in the shape
    out, seen = [], set()
    for i, d, j in zip(k[hit].tolist(), dx[hit].tolist(), jj[hit].tolist()):
        cx, cy, r = (bb[i, 0] + bb[i, 2]) / 2, (bb[i, 1] + bb[i, 3]) / 2, d / 2
        if wh[j] > 1.1 * d or ww[j] > 1.2 * d or wh[j] < 0.2 * d:
            continue
        if len(ac.query_ball_point((cx, cy), 0.85 * r)) > 1:
            continue  # two labels in one circle: a section/detail callout ('1' over 'A301'), not a grid bubble
        key = (round(cx / 2), round(cy / 2))
        if key in seen:  # concentric duplicate (fill + stroke)
            continue
        seen.add(key)
        out.append((cx, cy, r, words[j]["text"].strip().upper().replace("’", "'")))
    return out


def _straight(page, F=None):
    """Straight segments (x0,y0,x1,y1,len) of stroked, unfilled paths, merged where a polyline runs straight on."""
    F = _flat(page, F)
    S = F["seg"]
    if not len(S):
        return np.zeros((0, 5))
    sp = F["sp"]
    keep = ~np.isnan(F["grey"][sp]) & ~F["arc"][sp] & (F["n_curves"][sp] == 0)
    S = S[keep]
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    m = L > 1.0
    return np.column_stack([S[m], L[m]])


def grid(page: dict, F=None) -> list:
    """Column-grid axes [{"tag","p0","p1"}] in page pt (see module doc)."""
    if not page.get("paths"):
        return []
    F = _flat(page, F)
    B = _bubbles(page, F)
    if len(B) < 2:
        return []
    S = _straight(page, F)
    if not len(S):
        return []
    from scipy.spatial import cKDTree
    L = S[:, 4]
    ux, uy = (S[:, 2] - S[:, 0]) / L, (S[:, 3] - S[:, 1]) / L
    ang = np.degrees(np.arctan2(uy, ux)) % 180.0
    ends = cKDTree(np.vstack([S[:, :2], S[:, 2:4]]))
    n_s = len(S)
    BC = np.array([(b[0], b[1]) for b in B])
    BR = np.array([b[2] for b in B])
    BT = np.array([b[3] for b in B], dtype=object)
    axes = []
    for cx, cy, r, tag in B:
        # seed: a segment on a radial line through the bubble centre with an end near the circle
        cand = np.unique(np.array(ends.query_ball_point((cx, cy), 2.5 * r), dtype=np.int64) % n_s)
        if not len(cand):
            continue
        vx0, vy0 = S[cand, 0] - cx, S[cand, 1] - cy
        perp = np.abs(vx0 * -uy[cand] + vy0 * ux[cand])
        d0 = np.hypot(vx0, vy0)
        d1 = np.hypot(S[cand, 2] - cx, S[cand, 3] - cy)
        near = np.minimum(d0, d1)
        ok = (perp < 0.15 * r) & (near > 0.6 * r) & (near < 2.5 * r) & (np.maximum(d0, d1) > 1.6 * r)
        if not ok.any():
            continue
        si = np.flatnonzero(ok)[np.argmax(L[cand[ok]])]
        s, far_end = cand[si], d1[si] > d0[si]
        # direction pointing away from the bubble
        far = (S[s, 2], S[s, 3]) if far_end else (S[s, 0], S[s, 1])
        dx, dy = far[0] - cx, far[1] - cy
        n = math.hypot(dx, dy)
        dx, dy = dx / n, dy / n
        # all collinear segments along that ray (dash-dot pieces), chained with gaps up to 15 bubble diameters
        da = np.abs((ang - ang[s] + 90.0) % 180.0 - 90.0)
        sub = np.flatnonzero((da < 1.0) | (L < 2.0))
        a0 = (S[sub, 0] - cx) * dx + (S[sub, 1] - cy) * dy
        a1 = (S[sub, 2] - cx) * dx + (S[sub, 3] - cy) * dy
        p0 = np.abs((S[sub, 0] - cx) * -dy + (S[sub, 1] - cy) * dx)
        p1 = np.abs((S[sub, 2] - cx) * -dy + (S[sub, 3] - cy) * dx)
        col = np.flatnonzero((p0 < 0.12 * r + 0.3) & (p1 < 0.12 * r + 0.3) & (np.maximum(a0, a1) > 0.5 * r))
        if not len(col):
            continue
        lo, hi = np.minimum(a0[col], a1[col]), np.maximum(a0[col], a1[col])
        o = np.argsort(lo)
        lo, hi = lo[o], hi[o]
        start = max(float(lo[0]), r)
        if start > 2.5 * r:
            continue
        # the axis ends at the next bubble on its line (the far-end bubble of the same axis) if there is one
        ta = (BC[:, 0] - cx) * dx + (BC[:, 1] - cy) * dy
        pa = np.abs((BC[:, 0] - cx) * -dy + (BC[:, 1] - cy) * dx)
        stop = ta[(ta > 2 * r) & (pa < 0.5 * r) & (BT == tag)]  # only its own far-end bubble (a stray tag circle
        # sitting on the line, e.g. a level mark or a room tag, does not cut the axis short)
        stop_at = float(stop.min() - BR[0]) if len(stop) else math.inf
        end, gap = float(hi[0]), 30 * r
        for a, b in zip(lo[1:], hi[1:]):
            if a > end + gap or a > stop_at:
                break
            end = max(end, float(b))
        end = min(end, stop_at) if stop_at < math.inf else end
        if end - start < MIN_AXIS_D * 2 * r:
            continue
        # refine the line on the used pieces (the bubble centre sits only roughly on it): PCA of their end points
        used = sub[col][(np.minimum(a0[col], a1[col]) <= end + 1e-6)]
        E = np.vstack([S[used, :2], S[used, 2:4]])
        if len(E) >= 4:
            m = E.mean(0)
            _, _, vt = np.linalg.svd(E - m, full_matrices=False)
            ex, ey = vt[0]
            if ex * dx + ey * dy < 0:
                ex, ey = -ex, -ey
            if ex * dx + ey * dy > math.cos(math.radians(1.0)):
                t0 = (cx - m[0]) * ex + (cy - m[1]) * ey  # bubble centre projected onto the fitted line
                cx, cy, dx, dy = m[0] + t0 * ex, m[1] + t0 * ey, ex, ey
        axes.append({"tag": tag, "p0": [cx + dx * r, cy + dy * r], "p1": [cx + dx * end, cy + dy * end],
                     "_r": r, "_ang": math.degrees(math.atan2(dy, dx)) % 180.0})
    # one axis per tag (bubbles at both ends): merge along the line; then keep direction families of >= 2 axes
    by = {}
    for a in axes:
        by.setdefault(a["tag"], []).append(a)
    merged = []
    for tag, aa in by.items():
        aa.sort(key=lambda a: -math.dist(a["p0"], a["p1"]))
        best = aa[0]
        for b in aa[1:]:
            if abs((b["_ang"] - best["_ang"] + 90) % 180 - 90) < 1.0 and _perp(best, b["p0"]) < 2 * best["_r"]:
                pts = [best["p0"], best["p1"], b["p0"], b["p1"]]
                u = np.subtract(best["p1"], best["p0"]); u = u / np.linalg.norm(u)
                t = [float(np.dot(np.subtract(p, best["p0"]), u)) for p in pts]
                best = {**best, "p0": pts[int(np.argmin(t))], "p1": pts[int(np.argmax(t))]}
        merged.append(best)
    # a grid family: >= 2 parallel axes whose bubbles line up across the axes (same position along the axis);
    # tag circles with leader lines (wall/door tags) scatter and drop out
    fams = {}
    for a in merged:
        fams.setdefault(round(a["_ang"] / 3) % 60, []).append(a)
    keep = []
    for fa in fams.values():
        if len(fa) >= 3:  # one labelling scheme per family: a stray 'W6' wall tag among A, B, C drops out
            kinds = Counter(_kind(a["tag"]) for a in fa)
            fa = [a for a in fa if kinds[_kind(a["tag"])] >= max(2, 0.25 * len(fa))]
        if len(fa) < 2:
            continue
        th = math.radians(fa[0]["_ang"])
        u = (math.cos(th), math.sin(th))
        for a in fa:
            ta = [p[0] * u[0] + p[1] * u[1] for p in (a["p0"], a["p1"])]
            if any(b is not a and min(abs(x - p[0] * u[0] - p[1] * u[1]) for x in ta for p in (b["p0"], b["p1"]))
                   < 2.5 * a["_r"] for b in fa):
                keep.append(a)
    out = []
    for a in keep:
        out.append({"tag": a["tag"], "p0": [round(v, 2) for v in a["p0"]], "p1": [round(v, 2) for v in a["p1"]]})
    out.sort(key=lambda a: (not a["tag"][0].isalpha(), a["tag"]))
    return out


def _kind(tag: str) -> str:
    """Labelling scheme of a grid tag: letters ('A', 'B.1', "C'"), numbers ('1', '0.2', '3a'), prefixed ('U1', 'VA')."""
    t = tag.rstrip("'")
    if re.match(r"^[A-Z]{1,2}(?:\.\d+)?$", t):
        return "L" if len(t.split(".")[0]) == 1 or t[0] == t[1:2] else "P"
    if re.match(r"^\d", t):
        return "N"
    return "P"


def _perp(a, p):
    u = np.subtract(a["p1"], a["p0"])
    n = np.linalg.norm(u)
    if n == 0:
        return 1e9
    v = np.subtract(p, a["p0"])
    return abs(float(u[0] * v[1] - u[1] * v[0]) / n)


def _extend(ax: list) -> list:
    """Axes stretched to the full extent of their parallel family (a drawn axis often breaks off inside the
    building, short of the far rows, though its columns continue): copies, for intersection tests only."""
    out = []
    for a in ax:
        p = np.asarray(a["p0"], float)
        u = np.subtract(a["p1"], a["p0"])
        n = float(np.linalg.norm(u))
        if n == 0:
            out.append(a)
            continue
        u = u / n
        t = []
        for b in ax:
            v = np.subtract(b["p1"], b["p0"])
            m = float(np.linalg.norm(v))
            if m and abs(float(u[0] * v[1] - u[1] * v[0])) / m < 0.05:
                t += [float(np.dot(np.subtract(b["p0"], p), u)), float(np.dot(np.subtract(b["p1"], p), u))]
        out.append({**a, "p0": list(p + min(t + [0.0]) * u), "p1": list(p + max(t + [n]) * u)})
    return out


def _crossings(ax: list) -> dict:
    """_intersections of the axes as drawn, plus crossings of axes that break off short (_extend) where both belong
    to one grid system: each already crosses >= 2 axes parallel to the other (a second grid of a neighbouring
    building, drawn apart, never crosses this one's axes and stays out)."""
    if not ax:
        return {}
    X = _intersections(ax)
    E = _intersections(_extend(ax))
    hit = {}
    for a, b in X:
        hit.setdefault(a, set()).add(b)
        hit.setdefault(b, set()).add(a)
    by = {a["tag"]: a for a in ax}

    def par(t, s):
        u, v = np.subtract(by[t]["p1"], by[t]["p0"]), np.subtract(by[s]["p1"], by[s]["p0"])
        return abs(float(u[0] * v[1] - u[1] * v[0])) < 0.05 * float(np.linalg.norm(u) * np.linalg.norm(v))
    for (a, b), p in E.items():
        if (a, b) in X or a not in by or b not in by:
            continue
        pa, pb = (t[0] if _kind(t) == "P" and len(t) >= 2 else None for t in (a, b))
        if pa and pb and pa != pb:
            continue  # prefixed tags of two systems ('U4' x 'VB')
        if sum(par(c, b) for c in hit.get(a, ())) >= 2 and sum(par(d, a) for d in hit.get(b, ())) >= 2:
            X[(a, b)] = p
    return X


def _intersections(ax: list) -> dict:
    """{(tagU, tagV): (x, y)} where two non-parallel axes cross (extended by 10%)."""
    out = {}
    for i, a in enumerate(ax):
        for b in ax[i + 1:]:
            p, r = np.array(a["p0"], float), np.subtract(a["p1"], a["p0"])
            q, s = np.array(b["p0"], float), np.subtract(b["p1"], b["p0"])
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 0.2 * np.linalg.norm(r) * np.linalg.norm(s):  # < ~12 degrees apart: parallel family
                continue
            t = ((q - p)[0] * s[1] - (q - p)[1] * s[0]) / den
            u = ((q - p)[0] * r[1] - (q - p)[1] * r[0]) / den
            if -0.1 <= t <= 1.1 and -0.1 <= u <= 1.1:
                out[tuple(sorted((a["tag"], b["tag"])))] = tuple(p + t * r)
    return out


# ---------------------------------------------------------------------------------------------------------------
# multi-page alignment
# ---------------------------------------------------------------------------------------------------------------
def _rigid(A: np.ndarray, B: np.ndarray):
    """Rotation R, translation t minimising |R A + t - B| (2D Kabsch, no scale/reflection); RMS residual."""
    ca, cb = A.mean(0), B.mean(0)
    H = (A - ca).T @ (B - cb)
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[1] *= -1
        R = Vt.T @ U.T
    t = cb - R @ ca
    res = float(np.sqrt(np.mean(np.sum((A @ R.T + t - B) ** 2, 1))))
    return R, t, res


def _footprint_m(walls_m: list):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    ps = []
    for p in walls_m:
        try:
            g = Polygon(p)
            g = g if g.is_valid else g.buffer(0)
            if not g.is_empty:
                ps.append(g)
        except Exception:  # noqa: BLE001
            continue
    if not ps:
        return None
    u = unary_union([g.buffer(0.75) for g in ps])
    blobs = list(getattr(u, "geoms", [u]))
    big = max(b.area for b in blobs)
    keep = [b for b in blobs if b.area >= 0.15 * big]
    return unary_union(keep).buffer(-0.75 + 0.01).convex_hull if keep else None


def _align_footprint(fa, fb):
    """(R, t, residual_m) mapping footprint fa onto fb: centroids + the best of 4 quarter turns (IoU); residual =
    mean boundary distance."""
    from shapely import affinity
    best = None
    ca, cb = fa.centroid, fb.centroid
    for k in range(4):
        g = affinity.rotate(fa, 90 * k, origin=ca)
        g = affinity.translate(g, cb.x - ca.x, cb.y - ca.y)
        inter = g.intersection(fb).area
        iou = inter / max(g.union(fb).area, 1e-9)
        if best is None or iou > best[0] + 1e-6:
            best = (iou, k)
    iou, k = best
    iou0 = fa.intersection(fb).area / max(fa.union(fb).area, 1e-9)
    if iou0 >= 0.9 * iou:  # sheets of one CAD export usually share the viewport: keep them where they are
        ring = fa.exterior
        pts = [ring.interpolate(i / 40, normalized=True) for i in range(40)]
        return np.eye(2), np.zeros(2), float(np.mean([fb.exterior.distance(p) for p in pts])), iou0
    th = math.radians(90 * k)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    c = np.array([ca.x, ca.y])
    t = np.array([cb.x, cb.y]) - R @ c
    g = affinity.translate(affinity.rotate(fa, 90 * k, origin=ca), cb.x - ca.x, cb.y - ca.y)
    ring = g.exterior
    pts = [ring.interpolate(i / 40, normalized=True) for i in range(40)]
    res = float(np.mean([fb.exterior.distance(p) for p in pts]))
    return R, t, res, iou


def _entry(pm, page=None):
    """Per-page evidence: storey info, grid in metres (y down), wall polygons in metres, m_per_pt."""
    prov = (pm or {}).get("provenance") or {}
    sc = (pm or {}).get("scale") or {}
    mpt = sc.get("m_per_pt")
    mpx = sc.get("m_per_px")
    s = prov.get("px_per_pt") or ((mpt / mpx) if mpt and mpx else None)
    if page is not None:
        st = storey_info(page)
        g = grid(page)
        lt = level_table(page)
    else:
        st = dict(prov.get("storey") or {})
        g = prov.get("grid") or []
        lt = prov.get("level_table") or []
    sem = ((pm or {}).get("semantics") or {}).get("storey") or {}
    if st.get("elevation_m") is None and sem.get("elevation_m") is not None:
        st["elevation_m"] = sem["elevation_m"]
        st["elevation_source"] = sem.get("elevation_source")
    if not st.get("name") and sem.get("name"):
        st["name"], st["number"] = sem["name"], sem.get("number")
    gm = []
    if mpt:
        for a in g:
            gm.append({"tag": a["tag"], "p0": [v * mpt for v in a["p0"]], "p1": [v * mpt for v in a["p1"]]})
    walls_m = []
    if pm and mpx:
        for it in pm.get("items") or []:
            if it.get("kind") == "wall" and it.get("polygon_px"):
                walls_m.append([[x * mpx, y * mpx] for x, y in it["polygon_px"]])
    return {"storey": st, "grid_m": gm, "walls_m": walls_m, "m_per_pt": mpt, "levels": lt, "px_per_pt": s}


def _norm_name(name) -> str:
    return re.sub(r"\b(FLOOR|LEVEL|STOREY|STORY|PLAN)\b|[^\w]", "", str(name or "").upper())


def _table_row(table: dict, name, number):
    """The level datum row of a storey: same caption, else same caption without FLOOR/LEVEL ('MEZZANINE FLOOR' =
    'MEZZANINE'), else the one row with the same printed floor number."""
    if name in table:
        return table[name]
    k = _norm_name(name)
    rows = [r for r in table.values() if k and _norm_name(r["name"]) == k]
    if len(rows) == 1:
        return rows[0]
    if number is not None:
        rows = [r for r in table.values() if r.get("number") == number]
        if len(rows) == 1:
            return rows[0]
    return None


def storeys(pages: list, planmaps: list) -> list:
    """See module doc. `pages` and `planmaps` are parallel lists (page_index = position); a None plan map is a
    non-plan page (its level datums are still read); a None page means: use the plan map's provenance."""
    n = max(len(pages or []), len(planmaps or []))
    pages = list(pages or []) + [None] * (n - len(pages or []))
    planmaps = list(planmaps or []) + [None] * (n - len(planmaps or []))
    table = {}
    E = {}
    for i, (pg, pm) in enumerate(zip(pages, planmaps)):
        if pm is None:
            if pg is not None:
                for row in level_table(pg):
                    table.setdefault(row["name"], row)
            continue
        E[i] = _entry(pm, pg)
        for row in E[i]["levels"]:
            table.setdefault(row["name"], row)
    if not E:
        return []
    out = []
    for i, e in E.items():
        st = e["storey"]
        r = {"page_index": i, "page": int(planmaps[i].get("page") or i + 1), "name": st.get("name"), "number": st.get("number"), "elevation_m": st.get("elevation_m"),
             "height_m": st.get("height_m"), "source": st.get("source") or "page order",
             "elevation_source": st.get("elevation_source"), "height_source": st.get("height_source"),
             "m_per_pt": e["m_per_pt"]}
        if r["elevation_m"] is None and r["name"]:
            row = _table_row(table, r["name"], r["number"])
            if row is not None:
                r["elevation_m"] = row["elevation_m"]
                r["elevation_source"] = f"level datum of {row['name']} on another sheet"
        out.append(r)
    _order_and_fill(out)
    _align(out, E)
    return out


def _order_and_fill(out: list):
    """Sort bottom to top (elevation, else floor number, else page order); infer missing elevations/heights."""
    def key(r):
        return (r["number"] if r["number"] is not None else 99, r["page_index"])
    nums = [r for r in out if r["number"] is not None]
    if all(r["elevation_m"] is not None for r in out):
        out.sort(key=lambda r: (r["elevation_m"], r["page_index"]))
    else:
        out.sort(key=key)
    # dedupe level numbers: two pages of one storey (e.g. plan + RCP) keep their own entries, same level
    lv, last = [], None
    for r in out:
        k = r["number"] if r["number"] is not None else (r["name"] or ("p", r["page_index"]))
        if k != last:
            lv.append([])
            last = k
        lv[-1].append(r)
    # storey height: consecutive known elevations > notes > default
    known = [(j, g[0]["elevation_m"]) for j, g in enumerate(lv) if g[0]["elevation_m"] is not None]
    diffs = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(known, known[1:]) if b[0] > a[0]]
    diffs = [d for d in diffs if MIN_STOREY_M <= d <= MAX_STOREY_M]
    notes = [r["height_m"] for r in out if r["height_m"]]
    typical = round(float(np.median(diffs)), 3) if diffs else (Counter(notes).most_common(1)[0][0] if notes
                                                               else DEFAULT_STOREY_M)
    tsrc = "elevation step" if diffs else ("height note" if notes else f"default {DEFAULT_STOREY_M} m")
    # elevations: from the nearest known level, stepping by the level heights
    if not known:
        known = [(0, 0.0)]
        base_src = "lowest plan at 0.000 (no level mark)"
    else:
        base_src = None
    for j, g in enumerate(lv):
        if g[0]["elevation_m"] is None:
            kj, ke = min(known, key=lambda k: abs(k[0] - j))
            e = round(ke + (j - kj) * typical, 3)
            for r in g:
                r["elevation_m"] = e
                r["elevation_source"] = base_src if (j == kj and base_src) else \
                    f"inferred: {j - kj:+d} storeys x {typical:.2f} m ({tsrc}) from {ke:+.3f}"
    for j, g in enumerate(lv):
        nxt = lv[j + 1][0]["elevation_m"] if j + 1 < len(lv) else None
        for r in g:
            r["level_index"] = j
            if nxt is not None and MIN_STOREY_M <= nxt - r["elevation_m"] <= MAX_STOREY_M and \
                    not (r["height_source"] or "").startswith("floor-to-floor"):
                r["height_m"], r["height_source"] = round(nxt - r["elevation_m"], 3), "elevation step to the next level"
            elif not r["height_m"]:
                r["height_m"], r["height_source"] = typical, tsrc
            if not r["name"]:
                r["name"] = f"Level {j + 1:02d}" if len(lv) > 1 else "Floor 1"
    low = min(r["elevation_m"] for r in out)
    for r in out:
        r["z_m"] = round(r["elevation_m"] - low, 3)


def _align(out: list, E: dict):
    """offset/rotation of each page into the reference page's frame (grid tags, else footprint)."""
    ref = max(out, key=lambda r: (len(E[r["page_index"]]["grid_m"]), -out.index(r)))
    ri = ref["page_index"]
    ref_mpt = E[ri]["m_per_pt"] or 1.0
    Xref = _intersections(E[ri]["grid_m"])
    fref = None
    for r in out:
        i = r["page_index"]
        R, t, res, meth = np.eye(2), np.zeros(2), 0.0, "reference"
        extra = {}
        if i != ri:
            meth = "none"
            X = _intersections(E[i]["grid_m"])
            common = sorted(set(X) & set(Xref))
            done = False
            if len(common) >= 2:
                A = np.array([X[k] for k in common]); B = np.array([Xref[k] for k in common])
                R, t, res = _rigid(A, B)
                if res < 0.5:
                    meth, done = "grid", True
                    extra = {"points": len(common)}
            if not done and r.get("level_index") == ref.get("level_index"):
                # another sheet of the same storey (east/west half, other discipline) and no shared grid: centring
                # footprints would stack the halves; sheets of one set share the viewport, so keep them in place
                meth, done, res = "same_level", True, 0.0
            if not done:
                try:
                    if fref is None:
                        fref = _footprint_m(E[ri]["walls_m"])
                    fa = _footprint_m(E[i]["walls_m"])
                    if fa is not None and fref is not None:
                        R, t, res, iou = _align_footprint(fa, fref)
                        meth, extra = "footprint", {"iou": round(iou, 3)}
                except Exception as e:  # noqa: BLE001
                    extra = {"error": f"{type(e).__name__}: {e}"[:120]}
                    R, t, res = np.eye(2), np.zeros(2), 0.0
        rot = math.degrees(math.atan2(R[1, 0], R[0, 0]))
        r["rotation_deg"] = round(rot, 3)
        r["offset_m"] = [round(float(t[0]), 3), round(float(t[1]), 3)]
        r["offset_pt"] = [round(float(t[0]) / ref_mpt, 2), round(float(t[1]) / ref_mpt, 2)]
        r["align"] = {"method": meth, "residual_m": round(res, 3), "reference_page": ri, **extra}


def storeys_from_planmaps(planmaps: list) -> list:
    """storeys() from plan maps alone (page_index = position in the list)."""
    return storeys([None] * len(planmaps), planmaps)


def planmap_provenance(page: dict, pm: dict, s: float) -> dict:
    """{"storey": {...}, "grid": [...], "level_table": [...]} for the plan map's provenance (grid also in page px)."""
    st = storey_info(page)
    sem = (pm.get("semantics") or {}).get("storey") or {}
    if st.get("elevation_m") is None and sem.get("elevation_m") is not None:
        st["elevation_m"], st["elevation_source"] = sem["elevation_m"], sem.get("elevation_source")
    if sem.get("wall_height") and not st.get("height_m"):
        st["height_m"] = sem["wall_height"]
    wh = (pm.get("semantics") or {}).get("wall_height_m")
    if wh and not st.get("height_m"):
        st["height_m"], st["height_source"] = wh, "plan semantics wall height"
    src = "; ".join(x for x in (st.get("source"), st.get("elevation_source"), st.get("height_source")) if x) or None
    storey = {"name": st.get("name"), "number": st.get("number"), "elevation_m": st.get("elevation_m"),
              "height_m": st.get("height_m"), "source": src}
    F = _flat(page) if page.get("paths") else None
    g = grid(page, F)
    out = {"storey": storey, "grid": g, "level_table": level_table(page)}
    try:  # structural columns (hatched/filled squares on the grid); never breaks the provenance
        mpt = ((pm.get("scale") or {}).get("m_per_pt"))
        if F is not None and mpt:
            cols = columns(page, float(mpt), g, F, zone=_plan_zone(pm, s, float(mpt)))
            for c in cols:
                c["bbox_px"] = [round(v * s, 1) for v in c["bbox"]]
            out["columns"] = cols
    except Exception as e:  # noqa: BLE001
        out["columns_error"] = f"{type(e).__name__}: {e}"[:200]
    for a in g:
        a["p0_px"] = [round(v * s, 1) for v in a["p0"]]
        a["p1_px"] = [round(v * s, 1) for v in a["p1"]]
    return out


# ---------------------------------------------------------------------------------------------------------------
# structural columns
# ---------------------------------------------------------------------------------------------------------------
COL_M = (0.15, 0.8)       # column side / diameter range, m
COL_ASPECT = 2.5          # max long/short side
COL_TAG = re.compile(r"^(?:P|PI|PILARI|C|COL|K)\s?-?\d{1,3}$|\bHE[ABM]?\s?\d{3}\b|\b(?:RHS|SHS|CHS|VKR|KRP)\s?\d|"
                     r"^[Øø⌀D]\s?\d{3}$|^\d{3}\s?[x×]\s?\d{3}$", re.I)
SHAFT_WORD = re.compile(r"\b(HORMI|KUILU|SHAFT|LVI|IV|SK|HISSI|LIFT|RISER)\b", re.I)
COL_ON_AXIS_M = 0.3       # centre this close to a grid axis = on the grid


def _plan_zone(pm: dict, s: float, mpt: float):
    """The building in page pt: the plan map's wall and room polygons, grown by 0.4 m (None without any)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    gs = []
    for it in pm.get("items") or []:
        if it.get("kind") in ("wall", "room") and len(it.get("polygon_px") or []) >= 3:
            g = Polygon([(x / s, y / s) for x, y in it["polygon_px"]])
            if g.is_valid and g.area > 0:
                gs.append(g)
    return unary_union(gs).buffer(0.4 / mpt) if gs else None


def columns(page: dict, mpt: float, axes: list | None = None, F=None, zone=None) -> list:
    """Structural columns [{"bbox" (pt), "shape": "rect"|"circle", "w_m", "d_m", "grid": "A/3"|None, "evidence"}].
    A column is a small closed section (0.15-0.8 m) that is filled or hatched, sitting on a grid axis
    and (with a plan map zone) inside the building's walls/rooms; nothing off the grid counts."""
    F = _flat(page, F)
    bb = F["bbox"]
    if not len(bb) or not mpt:
        return []
    from scipy.spatial import cKDTree
    paths = page["paths"]
    dx, dy = (bb[:, 2] - bb[:, 0]) * mpt, (bb[:, 3] - bb[:, 1]) * mpt
    ok = ~np.isnan(dx) & F["closed"] & (F["npts"] >= 4) & (dx >= COL_M[0]) & (dx <= COL_M[1]) & \
        (dy >= COL_M[0]) & (dy <= COL_M[1]) & (np.maximum(dx, dy) <= COL_ASPECT * np.minimum(dx, dy))
    k = np.flatnonzero(ok)
    ax = [a for a in (axes or []) if a.get("p0") and a.get("p1")]
    if not len(k):
        return _pen_columns(page, F, mpt, ax, _crossings(ax), zone, [])
    circ = (F["n_curves"][k] >= 2) | (F["npts"][k] >= 12)
    rect = (F["npts"][k] <= 5) & (F["n_curves"][k] == 0)
    for n, i in enumerate(k.tolist()):  # a rectangle fills its box (an arrow or a triangle does not)
        if rect[n]:
            q = np.asarray(paths[i]["pts"], float).reshape(-1, 2)
            A = 0.5 * abs(float(np.dot(q[:, 0], np.roll(q[:, 1], 1)) - np.dot(q[:, 1], np.roll(q[:, 0], 1))))
            rect[n] = A >= 0.85 * (bb[i, 2] - bb[i, 0]) * (bb[i, 3] - bb[i, 1])
    k, circ = k[circ | rect], circ[circ | rect]
    if not len(k):
        return _pen_columns(page, F, mpt, ax, _crossings(ax), zone, [])
    C = np.column_stack([(bb[k, 0] + bb[k, 2]) / 2, (bb[k, 1] + bb[k, 3]) / 2])
    # hatching: >= 2 stroked segments lying wholly inside the section
    S = F["seg"]
    mid = (S[:, :2] + S[:, 2:4]) / 2
    stroked = ~np.isnan(F["grey"][F["sp"]])
    tree = cKDTree(mid) if len(mid) else None
    fill = F["fill"][k]
    dark = np.zeros(len(k), bool)
    for n, i in enumerate(k.tolist()):
        c = paths[i].get("fill")
        if c is not None and len(c) >= 3:
            dark[n] = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] < 0.5
    hatch = np.zeros(len(k), int)
    xmark = np.zeros(len(k), int)
    if tree is not None:
        for n, i in enumerate(k.tolist()):
            x0, y0, x1, y1 = bb[i]
            r = 0.5 * math.hypot(x1 - x0, y1 - y0)
            jj = np.array(tree.query_ball_point(C[n], r), dtype=np.int64)
            if not len(jj):
                continue
            jj = jj[stroked[jj] & (F["sp"][jj] != i)]
            e = 0.3  # strictly inside: the section's own outline (on its edge) does not count
            inside = (np.minimum(S[jj, 0], S[jj, 2]) >= x0 + e) & (np.maximum(S[jj, 0], S[jj, 2]) <= x1 - e) & \
                     (np.minimum(S[jj, 1], S[jj, 3]) >= y0 + e) & (np.maximum(S[jj, 1], S[jj, 3]) <= y1 - e)
            L = np.hypot(S[jj, 2] - S[jj, 0], S[jj, 3] - S[jj, 1])
            diag = np.abs(np.abs(S[jj, 2] - S[jj, 0]) - np.abs(S[jj, 3] - S[jj, 1])) < 0.6 * L
            hatch[n] = int(inside.sum())  # hatch pattern pieces (any length: CAD hatches come as many short strokes)
            xmark[n] = int((inside & diag & (L > 0.5 * min(x1 - x0, y1 - y0))).sum())
    lum = np.ones(len(k))
    for n, i in enumerate(k.tolist()):
        c = paths[i].get("fill")
        if c is not None and len(c) >= 3:
            lum[n] = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    filled = fill & (lum <= 0.85)                 # a real (non-white) fill
    section = filled | (hatch >= 3)               # solid, or hatched (>= 3 hatch lines; a bare X is a shaft mark)
    shaft = ~filled & (xmark >= 1) & (hatch <= 2)  # an unfilled box with a bare X or diagonal: shaft / void
    # position score (research-web-2 sec. 1): grid intersection +2, regular array +1, tag +1, shaft -2
    score = np.zeros(len(k), int)
    tag = [None] * len(k)
    side = np.maximum(dx[k], dy[k])
    X = _crossings(ax)
    if X:
        keys, P = list(X), np.array(list(X.values()))
        d, j = cKDTree(P).query(C)
        at = d * mpt <= np.maximum(COL_ON_AXIS_M, 0.5 * side)
        score[at] += 2
        for n in np.flatnonzero(at).tolist():
            tag[n] = "/".join(keys[j[n]])
    # regular array: >= 2 others of the same size (+-10 %) on the same row/column (+-0.1 m), 3-9 m apart
    rowtol = 0.1 / mpt
    for n in range(len(k)):
        same = (np.abs(side - side[n]) <= 0.1 * side[n]) & section
        same[n] = False
        dd = np.hypot(C[:, 0] - C[n, 0], C[:, 1] - C[n, 1]) * mpt
        line = (np.abs(C[:, 0] - C[n, 0]) <= rowtol) | (np.abs(C[:, 1] - C[n, 1]) <= rowtol)
        if int((same & line & (dd >= 3.0) & (dd <= 9.0)).sum()) >= 2:
            score[n] += 1
    words = [w for w in page.get("words") or [] if w.get("bbox") and (w.get("text") or "").strip()]
    if words:
        wc = np.array([_c(w["bbox"]) for w in words])
        wt = cKDTree(wc)
        for n in range(len(k)):
            for jw in wt.query_ball_point(C[n], 1.5 / mpt):
                t = words[jw]["text"].strip()
                if COL_TAG.search(t):
                    score[n] += 1
                    break
            for jw in wt.query_ball_point(C[n], 0.5 / mpt + 0.5 * side[n] / mpt):
                if SHAFT_WORD.search(words[jw]["text"]):
                    score[n] -= 2
                    break
    score[shaft] -= 2
    if zone is not None:  # in the building (walls/rooms of the plan), not on a neighbouring roof plan
        from shapely import points, contains
        inz = np.asarray(contains(zone, points(C)), bool)
    else:
        inz = np.ones(len(k), bool)
    keep = section & inz & (score >= 2)
    on = score >= 2
    out, seen = [], []
    for n in np.flatnonzero(keep).tolist():
        i = int(k[n])
        cx, cy = float(C[n, 0]), float(C[n, 1])
        if any(math.hypot(cx - a, cy - b) < 0.1 / mpt for a, b in seen):
            continue  # fill + outline of one column
        seen.append((cx, cy))
        out.append({"bbox": [round(float(v), 2) for v in bb[i]], "shape": "circle" if circ[n] else "rect",
                    "w_m": round(float(dx[i]), 3), "d_m": round(float(dy[i]), 3), "grid": tag[n],
                    "evidence": f"score {int(score[n])}, " + ("hatched" if hatch[n] >= 3 else "solid") + " section"})
    out += _pen_columns(page, F, mpt, ax, X, zone, out)
    return out


def _on_axis(ax: list, C: np.ndarray, tol: np.ndarray) -> list:
    """Per centre: the tag of the nearest axis whose line passes within tol (pt) of it, else None."""
    out = [None] * len(C)
    best = np.full(len(C), np.inf)
    for a in ax:
        p = np.asarray(a["p0"], float)
        u = np.subtract(a["p1"], a["p0"])
        n = float(np.linalg.norm(u))
        if n == 0:
            continue
        u = u / n
        v = C - p
        t = v @ u
        d = np.abs(v[:, 0] * u[1] - v[:, 1] * u[0])
        hit = (d <= tol) & (t >= -0.05 * n) & (t <= 1.05 * n) & (d < best)
        best[hit] = d[hit]
        for i in np.flatnonzero(hit).tolist():
            out[i] = a["tag"]
    return out


def _pen_columns(page: dict, F: dict, mpt: float, ax: list, X: dict, zone, have: list) -> list:
    """Columns drawn as plain outlines (no fill, no hatch) by a clean column pen (_column_pens). Score: clean pen
    +1, grid intersection +2, on one grid axis +1, regular array (>= 2 same-size others on its row/column 2-12 m
    apart) +1; kept at >= 2 inside the zone. So a column off the intersections still counts when it sits on an
    axis or in a row of its own kind; a lone box off every axis does not."""
    rects = _pen_rects(page, F, mpt)
    cp = _column_pens(page, F, rects)
    R = [r for r in rects if r["pen"] in cp]
    if not R:
        return []
    from scipy.spatial import cKDTree
    B = np.array([r["bbox"] for r in R])
    C = np.column_stack([(B[:, 0] + B[:, 2]) / 2, (B[:, 1] + B[:, 3]) / 2])
    side = np.maximum(B[:, 2] - B[:, 0], B[:, 3] - B[:, 1])
    score = np.ones(len(R), int)
    tag = [None] * len(R)
    if X:
        keys, P = list(X), np.array(list(X.values()))
        d, j = cKDTree(P).query(C)
        at = d * mpt <= np.maximum(COL_ON_AXIS_M, 0.5 * side * mpt)
        score[at] += 2
        for n in np.flatnonzero(at).tolist():
            tag[n] = "/".join(keys[j[n]])
    else:
        at = np.zeros(len(R), bool)
    on = _on_axis(ax, C, np.maximum(COL_ON_AXIS_M / mpt, 0.5 * side)) if ax else [None] * len(R)
    for n in range(len(R)):
        if not at[n] and on[n]:
            score[n] += 1
            tag[n] = on[n]
    rowtol = 0.1 / mpt
    for n in range(len(R)):
        same = np.abs(side - side[n]) <= 0.1 * side[n]
        same[n] = False
        dd = np.hypot(C[:, 0] - C[n, 0], C[:, 1] - C[n, 1]) * mpt
        line = (np.abs(C[:, 0] - C[n, 0]) <= rowtol) | (np.abs(C[:, 1] - C[n, 1]) <= rowtol)
        if int((same & line & (dd >= 2.0) & (dd <= 12.0)).sum()) >= 2:
            score[n] += 1
    if zone is not None:
        from shapely import points, contains
        inz = np.asarray(contains(zone, points(C)), bool)
    else:
        inz = np.ones(len(R), bool)
    seen = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in (c["bbox"] for c in have)]
    # the building's own grid: axes that carry a column inside the zone. A clean-pen box on a crossing of two such
    # axes is a column of this building even where the zone (walls/rooms read so far) has a hole
    own = {t for c in have for t in (c.get("grid") or "").split("/") if t}
    own |= {t for n in np.flatnonzero(inz & (score >= 2)).tolist() for t in (tag[n] or "").split("/") if t}
    grid_in = np.array([bool(tag[n]) and (bool(at[n]) or score[n] >= 3) and all(t in own for t in tag[n].split("/"))
                        for n in range(len(R))])  # a crossing of own axes, or an own axis + a regular row
    out = []
    for n in np.flatnonzero((inz | grid_in) & (score >= 2)).tolist():
        cx, cy = float(C[n, 0]), float(C[n, 1])
        if any(math.hypot(cx - a, cy - b) < max(0.1 / mpt, 0.5 * side[n]) for a, b in seen):
            continue  # the outline of a column already found as a filled/hatched section
        seen.append((cx, cy))
        b = B[n]
        out.append({"bbox": [round(float(v), 2) for v in b], "shape": "rect",
                    "w_m": round(float(b[2] - b[0]) * mpt, 3), "d_m": round(float(b[3] - b[1]) * mpt, 3),
                    "grid": tag[n], "evidence": f"score {int(score[n])}, outline in a column-only pen"})
    return out


def _pen_ids(F: dict) -> np.ndarray:
    """Integer pen id per path: (stroke grey to 0.01, width to 0.01, dashed); -1 for unstroked paths."""
    g = F["grey"]
    k = np.round(np.nan_to_num(g, nan=-1) * 100).astype(np.int64) * 100000 + \
        np.round(F["width"] * 100).astype(np.int64) * 2 + F["dashed"].astype(np.int64)
    k[np.isnan(g)] = -1
    return k


def _pen_rects(page: dict, F: dict, mpt: float) -> list:
    """Column-sized axis-parallel rectangles drawn by one pen, either as one closed 4-corner path or assembled
    from 4 separate straight strokes (CAD plots often explode a column outline into lines):
    [{"bbox": [x0,y0,x1,y1], "pen": id, "paths": [path indices]}] (pen id from _pen_ids)."""
    S, sp = F["seg"], F["sp"]
    if not len(S):
        return []
    lo, hi = COL_M[0] / mpt, COL_M[1] / mpt
    tol = max(0.02 / mpt, 0.3)
    dx, dy = S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
    L = np.hypot(dx, dy)
    pid = _pen_ids(F)[sp]
    ok = (pid >= 0) & ~F["arc"][sp] & (F["n_curves"][sp] == 0) & (L >= lo - tol) & (L <= hi + tol)
    H = np.flatnonzero(ok & (np.abs(dy) <= 0.02 * L))
    V = np.flatnonzero(ok & (np.abs(dx) <= 0.02 * L))
    if not len(H) or not len(V):
        return []
    from scipy.spatial import cKDTree
    hx0, hx1 = np.minimum(S[H, 0], S[H, 2]), np.maximum(S[H, 0], S[H, 2])
    hy = (S[H, 1] + S[H, 3]) / 2
    vy0, vy1 = np.minimum(S[V, 1], S[V, 3]), np.maximum(S[V, 1], S[V, 3])
    vx = (S[V, 0] + S[V, 2]) / 2
    pr = cKDTree(np.column_stack([hx0, hx1])).query_pairs(tol * 1.5, output_type="ndarray")
    if not len(pr):
        return []
    a, b = pr[:, 0], pr[:, 1]
    h = np.abs(hy[a] - hy[b])
    w = (hx1[a] + hx1[b] - hx0[a] - hx0[b]) / 2
    m = (pid[H[a]] == pid[H[b]]) & (h >= lo - tol) & (h <= hi + tol) & (np.abs(hx0[a] - hx0[b]) <= tol) & \
        (np.abs(hx1[a] - hx1[b]) <= tol) & (np.maximum(w, h) <= COL_ASPECT * np.minimum(w, h))
    a, b = a[m], b[m]
    if not len(a):
        return []
    vt = cKDTree(np.column_stack([vx, vy0, vy1]))
    out, seen = [], set()
    for ia, ib in zip(a.tolist(), b.tolist()):
        pk = pid[H[ia]]
        x0, x1 = (hx0[ia] + hx0[ib]) / 2, (hx1[ia] + hx1[ib]) / 2
        y0, y1 = min(hy[ia], hy[ib]), max(hy[ia], hy[ib])
        key = (round(x0 / tol), round(y0 / tol), round(x1 / tol), round(y1 / tol))
        if key in seen:
            continue
        sides = []
        for xs in (x0, x1):
            js = [j for j in vt.query_ball_point((xs, y0, y1), tol * 1.8)
                  if abs(vx[j] - xs) <= tol and abs(vy0[j] - y0) <= tol and abs(vy1[j] - y1) <= tol
                  and pid[V[j]] == pk]
            if not js:
                break
            sides.append(V[js[0]])
        if len(sides) < 2:
            continue
        seen.add(key)
        ps = sorted({int(sp[H[ia]]), int(sp[H[ib]]), int(sp[sides[0]]), int(sp[sides[1]])})
        out.append({"bbox": [float(x0), float(y0), float(x1), float(y1)], "pen": int(pk), "paths": ps})
    return out


def _column_pens(page: dict, F: dict, rects: list) -> set:
    """Pens that draw (almost) only column-sized rectangles: >= 3 rectangles and >= 60 % of the pen's paths in
    them (a clean structural-column pen; a general linework pen also draws small boxes but far more else)."""
    if not rects:
        return set()
    n_pen = Counter(_pen_ids(F).tolist())
    used, cnt = {}, Counter()
    for r in rects:
        used.setdefault(r["pen"], set()).update(r["paths"])
        cnt[r["pen"]] += 1
    return {k for k, u in used.items() if cnt[k] >= 3 and len(u) >= 0.6 * n_pen[k]}
