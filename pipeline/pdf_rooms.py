"""Rooms and scale from a vector (CAD-exported) PDF page, measured from exact PDF point coordinates (rooms role).

Coordinates: page points, top-left origin, y down (the `page` dict from `pipeline.pdf_vector.load_page`).

rooms(page, walls) -> [{"polygon": [[x, y], ...] | None, "label", "number", "area_printed_m2", "label_bbox",
                        "label_xy", "pts_area", "split"}]
    Free space bounded by the wall polygons (door gaps up to ~1.2 m closed by buffering, then grown back),
    keeping the regions that hold a text-layer room label. `pts_area` is the shoelace area of `polygon` in pt².
    A label that no region holds still yields a room (polygon None) with its printed area.

scale(page, rooms) -> {"m_per_pt", "method", "confidence", "ratio", "check": {...}}
    The LEAD's ladder: printed 1:N (+ sheet size) > scale bar > printed room areas fit (also cross-checks the
    printed 1:N, flagged when they differ by more than 5%) > dimension strings > door-swing guess (approximate).
    m_per_pt = 0.00035278 * N.
"""
from __future__ import annotations

import math
import os
import re
from statistics import median

PT_M = 25.4 / 72 / 1000  # metres of paper per pt (0.00035278)
STD_RATIOS = (10, 20, 25, 50, 75, 100, 125, 200, 250, 500, 1000, 2000,      # metric
              12, 16, 24, 32, 48, 64, 96, 128, 192, 384)                    # imperial (1"=1'-0" ... 1/32"=1'-0")
FT2_M2 = 0.09290304
FT_M = 0.3048

_NUM = r"(\d{1,3}(?:[ ,']\d{3})+(?:[.,]\d{1,2})?|\d{1,5}(?:[.,]\d{1,3})?)"
_M2 = r"(?:m\s?²|m\s?2|m\^2|㎡|qm|sq\.?\s?m(?:eters?|etres?)?|m\s?\?)"
_FT2 = r"(?:ft\s?²|ft\s?2|sq\.?\s?f(?:ee)?t\.?|s\.?\s?f\.?|sf)"
AREA_RE = re.compile(_NUM + r"\s*(" + _M2 + "|" + _FT2 + r")(?![a-z])", re.I)
ROOM_NO_RE = re.compile(r"^(?:[A-Z]{0,2}[-.]?)?\d{1,4}(?:[.,]\d{1,3})?[A-Za-z]?(?:[-/]\d{1,2}[A-Z]?)?$")  # '53-1', 'K131/1'
ROOM_WORDS = re.compile(
    r"\b(bed(?:room)?s?|br|bath(?:room)?s?|ba|kitchen|kit|living|liv|dining|din|family|great room|den|study|office|"
    r"closet|clo|clos|w\.?i\.?c|wic|pantry|laundry|lndry|utility|mech(?:anical)?|storage|stor|store|hall(?:way)?|"
    r"corridor|corr|foyer|entry|lobby|vestibule|vest|stair(?:s|well)?|elev(?:ator)?|toilet|wc|restroom|rr|"
    r"powder|shower|garage|porch|patio|deck|balc|balcony|terrace|loggia|mudroom|bedroom|master|room|conference|"
    r"meeting|break|lounge|reception|waiting|copy|server|janitor|jan|elec|gym|fitness|locker|"
    r"zimmer|küche|kuche|kueche|bad|dusche|wohnen|essen|schlafen|kind|flur|diele|gang|korridor|reduit|abstell|"
    r"keller|balkon|loggia|terrasse|entrée|entree|wohnzimmer|schlafzimmer|arbeiten|büro|buero|treppenhaus|"
    r"chambre|cuisine|séjour|sejour|salon|salle|bain|douche|couloir|dégagement|degagement|cave|réduit|"
    r"camera|cucina|soggiorno|bagno|corridoio|ripostiglio|room)\b", re.I)
SKIP_LABEL = re.compile(r"[:@/\\|]|\b(see|engineer|engineering|design|inc|llc|ltd|street|ave|avenue|road|scale|maßstab|massstab|echelle|échelle|sheet|drawing|project|date|rev(?:ision)?|"
                        r"north|plan|level|floor|grundriss|geschoss|etage|title|key|note|typ\.?|similar)\b", re.I)


# ---------------------------------------------------------------- geometry helpers (exact pt maths)

def shoelace(poly) -> float:
    """Polygon area in pt² (absolute), exact on the point coordinates."""
    a = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def _inside(pt, poly) -> bool:
    x, y = pt
    c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def _cx(b):
    return (b[0] + b[2]) / 2


def _cy(b):
    return (b[1] + b[3]) / 2


def m_per_pt_from_ratio(n: float) -> float:
    return PT_M * n


# ---------------------------------------------------------------- text: phrases, printed areas, labels

def _phrases(words):
    """Words joined into one-line phrases (same baseline, small gaps). [{text, bbox, h}]"""
    ws = [w for w in words if w.get("text") and w.get("bbox") and str(w["text"]).strip()]
    ws.sort(key=lambda w: _cy(w["bbox"]))
    lines = []  # [cy, h, [words]]
    for w in ws:
        b = w["bbox"]
        h = max(0.5, b[3] - b[1])
        if lines and abs(lines[-1][0] - _cy(b)) < 0.35 * max(h, lines[-1][1]):
            lines[-1][2].append(w)
        else:
            lines.append([_cy(b), h, [w]])
    rows = []
    for _, _, lw in lines:
        lw.sort(key=lambda w: w["bbox"][0])
        cur = None
        for w in lw:
            b = w["bbox"]
            h = max(0.5, b[3] - b[1])
            if cur and 0.4 < h / cur["h"] < 2.6 and -0.3 * h <= b[0] - cur["bbox"][2] < 0.9 * max(h, cur["h"]):
                cur["text"] += " " + str(w["text"]).strip()
                cur["bbox"] = [cur["bbox"][0], min(cur["bbox"][1], b[1]), max(cur["bbox"][2], b[2]), max(cur["bbox"][3], b[3])]
                cur["h"] = max(cur["h"], h)
            else:
                if cur:
                    rows.append(cur)
                cur = {"text": str(w["text"]).strip(), "bbox": list(b), "h": h}
        if cur:
            rows.append(cur)
    return rows


def parse_area(text: str):
    """Printed area in m² from '15.61 m²', '15,6 m2', '150 SF', '1,250 sq ft' ... or None."""
    m = AREA_RE.search(text)
    if not m:
        return None
    num, unit = m.group(1), m.group(2).lower().replace(" ", "")
    feet = unit.startswith(("ft", "sq.f", "sqf", "s.f", "sf", "s.f."))
    if re.fullmatch(r"\d{1,3}(?:[ ,']\d{3})+(?:[.,]\d{1,2})?", num) and (feet or re.search(r"[ ']", num)):
        num = re.sub(r"[ ,'](?=\d{3})", "", num)
    num = num.replace(",", ".") if num.count(",") == 1 and "." not in num else num.replace(",", "")
    try:
        v = float(num)
    except ValueError:
        return None
    if feet:
        v *= FT2_M2
    return v if 0.3 <= v <= 5000 else None


def label_blocks(words):
    """Room labels from the text layer: [{label, number, area_printed_m2, bbox, xy}] in pt.
    A block is a printed area with the name/number above it, or a room-name phrase (with a nearby number).
    Vertical room tags (text turned 90 deg counter-clockwise, as many CAD sheets letter narrow rooms) are read in
    a turned frame and mapped back. When the sheet prints areas for its rooms (>= 5 area tags), a name without an
    area must be a known room word with a room number (otherwise it is an annotation: 'MOVABLE LOCKERS')."""
    hz, vt = [], []
    for w in words:
        b, t = w.get("bbox"), str(w.get("text") or "").strip()
        (vt if b and len(t) >= 2 and (b[3] - b[1]) > 1.1 * (b[2] - b[0]) else hz).append(w)
    out = _label_blocks(hz)
    if len(vt) >= 3:
        hm = max(w["bbox"][3] for w in vt) + 1.0
        rot = [{"text": w["text"], "bbox": [hm - w["bbox"][3], w["bbox"][0], hm - w["bbox"][1], w["bbox"][2]]}
               for w in vt]
        for b in _label_blocks(rot):
            a0, a1, a2, a3 = b["bbox"]
            b["bbox"] = [a1, hm - a2, a3, hm - a0]
            b["xy"] = [_cx(b["bbox"]), _cy(b["bbox"])]
            b["vertical"] = True
            if not any(_overlap(b["bbox"], o["bbox"]) for o in out if o["area_printed_m2"] is not None):
                out.append(b)
    # room numbers follow one scheme per sheet ('K105', 'K104a'); with >= 5 numbered area tags, a 'number' of
    # another shape is a dimension or a tag ('240', 'EI30') picked up nearby
    sig = [_num_sig(b["number"]) for b in out if b["area_printed_m2"] is not None and b.get("number")]
    if len(sig) >= 5:
        from collections import Counter
        top, c = Counter(sig).most_common(1)[0]
        if c >= 0.6 * len(sig):
            for b in out:
                if b.get("number") and _num_sig(b["number"]) != top:
                    b["number"] = None
    if sum(1 for b in out if b["area_printed_m2"] is not None) >= 5:
        out = [b for b in out if b["area_printed_m2"] is not None or (
            b.get("number") and ROOM_WORDS.search(b.get("label") or "") and not _is_unit_tag(b))]
    return out


def _num_sig(t):
    """Shape of a room number: letters -> A, digits -> 9, trailing letter suffix dropped ('K104a' -> 'A999')."""
    return re.sub(r"(?<=9)A+$", "", re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "A", (t or "").replace(" ", ""))))


def _label_blocks(words):
    ph = _phrases(words)
    used = set()
    blocks = []
    for i, p in enumerate(ph):
        a = parse_area(p["text"])
        if a is None:
            continue
        m = AREA_RE.search(p["text"])
        rest = (p["text"][:m.start()] + " " + p["text"][m.end():]).strip()
        blocks.append({"label": None, "number": None, "area_printed_m2": round(a, 3), "bbox": list(p["bbox"]),
                       "h": p["h"], "_rest": rest, "_i": i})
        used.add(i)
    # name-only labels (US style tags: BEDROOM / 201)
    for i, p in enumerate(ph):
        if i in used:
            continue
        t = p["text"]
        plain = len(t) <= 28 and len(t.split()) <= 3 and sum(ch.isalpha() for ch in t) >= 2 \
            and sum(ch.isdigit() for ch in t) <= 4 and not SKIP_LABEL.search(t.replace("/", " "))
        letters = sum(ch.isalpha() for ch in t)
        tagged = plain and letters >= 0.8 * len(t.replace(" ", "")) and "=" not in t and any(
            _room_no(q["text"]) and 0.3 * p["h"] < _cy(q["bbox"]) - _cy(p["bbox"])
                               < 2.6 * p["h"] and abs(_cx(q["bbox"]) - _cx(p["bbox"])) < 1.5 * p["h"] + (p["bbox"][2] - p["bbox"][0]) / 2
                               for q in ph)   # a name line with a room number directly below it ("Stanza" / "1.02")
        if plain and (ROOM_WORDS.search(t) or tagged):
            # skip when it sits right above/inside an area block (it will be that block's name)
            near = [b for b in blocks if b["area_printed_m2"] is not None and _near_above(p, b)]
            if near:
                continue
            blocks.append({"label": None, "number": None, "area_printed_m2": None, "bbox": list(p["bbox"]),
                           "h": p["h"], "_rest": t, "_i": i})
            used.add(i)
    # attach names and numbers from phrases around each block
    for b in blocks:
        h = b["h"]
        names, nums = [], []
        if b["_rest"]:
            if ROOM_NO_RE.match(b["_rest"]):
                nums.append((0, b["_rest"], None))
            elif sum(ch.isalpha() for ch in b["_rest"]) >= 2:
                names.append((0, b["_rest"], None))
        for j, p in enumerate(ph):
            if j in used or j == b["_i"]:
                continue
            pb = p["bbox"]
            dx = abs(_cx(pb) - _cx(b["bbox"]))
            if dx > 2.5 * h + (pb[2] - pb[0]) / 2 + (b["bbox"][2] - b["bbox"][0]) / 2:
                continue
            dy = _cy(b["bbox"]) - _cy(pb)  # >0: phrase above the block
            # numbers may sit two short lines above (number / name / area stacks): a little more reach for them
            if -2.6 * h <= dy <= 4.2 * h and abs(dy) > 0.3 * h:
                t = p["text"]
                d = abs(dy) / h + dx / (4 * h)
                # a number phrase may carry a joined neighbour word ('A12 2190': a dimension on the same line)
                tn = t if _room_no(t) else next((q for q in t.split()[:1] if len(t.split()) == 2 and _room_no(q)
                                                 and re.search(r"[A-Za-z]", q) and re.fullmatch(r"\d{3,}", t.split()[1])),
                                                None)
                if tn and dy > 3.6 * h and UNIT_TAG.search(tn):
                    continue   # a unit / apartment tag further up is not this room's number
                if tn:   # (a far number does not grow the block's box: it must not reach a neighbouring tag)
                    nums.append((d, tn.replace(" ", ""), pb if dy <= 3.6 * h else None))
                elif dy > 3.6 * h:
                    continue
                elif dy > 0 and sum(ch.isalpha() for ch in t) >= 2 and not AREA_RE.search(t) and len(t) <= 40 \
                        and not SKIP_LABEL.search(t.replace("/", " ").replace("-", "")):   # 'MEETING-ROOM'
                    names.append((d, t, pb))
        if names:
            names.sort(key=lambda x: x[0])
            b["label"] = names[0][1]
            if names[0][2]:
                bb = names[0][2]
                b["bbox"] = [min(b["bbox"][0], bb[0]), min(b["bbox"][1], bb[1]), max(b["bbox"][2], bb[2]),
                             max(b["bbox"][3], bb[3])]
        if nums:
            nums.sort(key=lambda x: x[0])
            b["number"] = nums[0][1]
            if nums[0][2]:
                bb = nums[0][2]
                b["bbox"] = [min(b["bbox"][0], bb[0]), min(b["bbox"][1], bb[1]), max(b["bbox"][2], bb[2]),
                             max(b["bbox"][3], bb[3])]
        b["xy"] = [_cx(b["bbox"]), _cy(b["bbox"])]
    for b in blocks:
        for k in ("_rest", "_i", "h"):
            b.pop(k, None)
    # the same block found twice (name phrase + area phrase): keep the one with an area
    out = []
    for b in sorted(blocks, key=lambda b: b["area_printed_m2"] is None):
        if any(_overlap(b["bbox"], o["bbox"]) for o in out):
            continue
        out.append(b)
    return out


UNIT_TAG = re.compile(r"\b(type|unit|apt|apartment|whg|wohnung|logement|appartement|suite)\b|^U\d", re.I)


def _room_no(t):
    """A room number ('1.02', 'K124', '201', 'T408'), not a dimension in mm ('2040', '6000')."""
    t = t.replace(" ", "")
    return bool(ROOM_NO_RE.match(t)) and not re.fullmatch(r"\d{4,}", t)


def _is_unit_tag(b):
    return bool(UNIT_TAG.search(b.get("label") or "") or UNIT_TAG.search(b.get("number") or ""))


def _near_above(p, b):
    h = max(p["h"], 1.0)
    return abs(_cx(p["bbox"]) - _cx(b["bbox"])) < 3 * h + (p["bbox"][2] - p["bbox"][0]) / 2 and \
        -0.5 * h <= _cy(b["bbox"]) - _cy(p["bbox"]) <= 3.6 * h


def _overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[1], b[1]) > 0


# ---------------------------------------------------------------- scale rungs

def _ratio(page):
    from engine import scale_text
    ratio, sheet = scale_text.ratio_and_sheet([{**w, "bbox_px": w.get("bbox_px") or w.get("bbox")} for w in page.get("words") or []])
    return ratio, sheet


_SB_LABEL = re.compile(r"^(\d{1,3}(?:[.,]\d)?)\s*('|’|′|ft|feet|m)?$", re.I)


def _scalebar_irregular(page):
    """Graphic scale '0 4' 8' 16'' or '0 1 2 5 m': labels on one row starting at 0, positions linear in value
    (steps may differ), with a unit mark. Returns m per pt or None."""
    ws = []
    for w in page.get("words") or []:
        m = _SB_LABEL.match(str(w.get("text") or "").strip())
        if m and w.get("bbox"):
            ws.append((float(m.group(1).replace(",", ".")), (m.group(2) or "").lower(), w["bbox"]))
    best = None
    for v0, u0, b0 in ws:
        if v0 != 0:
            continue
        h = max(0.5, b0[3] - b0[1])
        row = sorted([(v, u, b) for v, u, b in ws if abs(_cy(b) - _cy(b0)) < 0.5 * h and 0 <= _cx(b) - _cx(b0) < 60 * h],
                     key=lambda t: _cx(t[2]))
        vals = [v for v, _, _ in row]
        if len(row) < 3 or vals[0] != 0 or any(b <= a for a, b in zip(vals, vals[1:])):
            continue
        xs = [_cx(b) for _, _, b in row]
        span = xs[-1] - xs[0]
        if span < 20:
            continue
        k = span / vals[-1]  # pt per unit
        if any(abs(xs[0] + v * k - x) > 0.04 * span for v, x in zip(vals, xs)):
            continue
        units = {u for _, u, _ in row if u}
        near = [str(w.get("text") or "").strip().lower() for w in page.get("words") or [] if w.get("bbox")
                and abs(_cy(w["bbox"]) - _cy(b0)) < 1.2 * h and -2 * h < w["bbox"][0] - xs[-1] < 8 * h]
        if units & {"'", "’", "′", "ft", "feet"} or any(t in ("ft", "feet", "'") for t in near):
            mpu = FT_M
        elif "m" in units or any(t in ("m", "meter", "meters", "metre", "metres") for t in near):
            mpu = 1.0
        else:
            continue
        m_per_pt = mpu / k
        if _plausible(m_per_pt) and (best is None or len(row) > best[0]):
            best = (len(row), m_per_pt)
    return best[1] if best else None


def _scalebar(page):
    irr = _scalebar_irregular(page)
    if irr:
        return irr
    from engine import scale_text
    ws = [{"text": w["text"], "bbox_px": w["bbox"]} for w in page.get("words") or [] if w.get("bbox")]
    sb = scale_text.scalebar(ws)
    m = sb["m_per_px"] if sb else None  # bbox in pt, so m per "px" is m per pt
    return m if m and _plausible(m) else None


def _plausible(m_per_pt):
    """Building drawings sit between 1:10 and 1:2000."""
    return PT_M * 10 <= m_per_pt <= PT_M * 2000


def _bbox_area(b):
    return (b[2] - b[0]) * (b[3] - b[1]) if b and len(b) == 4 else 0.0


def _area_fit(rooms_):
    """Least squares printed_m2 = k * pts_area (k = m_per_pt²), robust to a few mismatched labels."""
    pairs = [(r["pts_area"], r["area_printed_m2"]) for r in rooms_
             if r.get("polygon") and r.get("pts_area") and r.get("area_printed_m2") and not r.get("split")
             and r["pts_area"] >= 3 * _bbox_area(r.get("label_bbox"))]   # a room is much bigger than its tag
    if len(pairs) < 2:
        return None
    ks = [p / a for a, p in pairs]
    k0 = median(ks)
    keep = [(a, p) for a, p in pairs if abs(p / a / k0 - 1) < 0.25]
    if len(keep) < 2:
        return None
    k = sum(a * p for a, p in keep) / sum(a * a for a, p in keep)
    rel = [abs(k * a - p) / p for a, p in keep]
    return {"m_per_pt": math.sqrt(k), "n": len(keep), "n_pairs": len(pairs), "printed_areas_rel_err": median(rel),
            "max_rel_err": max(rel)}


_DIM_FTIN = re.compile(r"^(\d{1,3})'\s*-?\s*(\d{1,2})?(?:\s+(\d{1,2})/(\d{1,2}))?\"?$")
_DIM_M = re.compile(r"^\d{1,2}[.,]\d{2,3}$|^\d{3,5}$")


def _dims(page):
    """Dimension strings against the nearest parallel line of matching extent: median m/pt of agreeing candidates."""
    segs = []
    for p in page.get("paths") or []:
        pts = p.get("pts") or []
        if len(pts) == 2 and not p.get("closed"):
            (x0, y0), (x1, y1) = pts
            L = math.hypot(x1 - x0, y1 - y0)
            if L > 5 and (abs(x1 - x0) < 0.01 * L or abs(y1 - y0) < 0.01 * L):
                segs.append((x0, y0, x1, y1, L))
    if not segs or len(segs) > 60000:
        return None
    cands = []
    for ph in _phrases(page.get("words") or []):
        t = ph["text"].replace("’", "'").replace("”", '"')
        m = _DIM_FTIN.match(t)
        if m:
            v = (int(m.group(1)) + int(m.group(2) or 0) / 12 + (int(m.group(3)) / int(m.group(4)) / 12 if m.group(3) else 0)) * FT_M
        elif _DIM_M.match(t):
            v = float(t.replace(",", "."))
            if v >= 100:
                v /= 1000  # mm
        else:
            continue
        if not 0.3 <= v <= 60:
            continue
        b = ph["bbox"]
        cx, cy, h = _cx(b), _cy(b), ph["h"]
        horiz = (b[2] - b[0]) >= (b[3] - b[1])
        best = None
        for x0, y0, x1, y1, L in segs:
            if horiz and abs(y1 - y0) < 0.01 * L and min(x0, x1) <= cx <= max(x0, x1):
                d = abs(cy - y0)
            elif not horiz and abs(x1 - x0) < 0.01 * L and min(y0, y1) <= cy <= max(y0, y1):
                d = abs(cx - x0)
            else:
                continue
            if d < 1.5 * h and L > (b[2] - b[0] if horiz else b[3] - b[1]) and (best is None or d < best[0]):
                best = (d, L)
        if best:
            cands.append(v / best[1])
    if len(cands) < 3:
        return None
    cands.sort()
    # largest cluster within 3%
    bestc = []
    for c in cands:
        cl = [x for x in cands if abs(x / c - 1) < 0.03]
        if len(cl) > len(bestc):
            bestc = cl
    if len(bestc) < 3 or len(bestc) < 0.3 * len(cands) or not _plausible(median(bestc)):
        return None
    return {"m_per_pt": median(bestc), "n": len(bestc), "n_cands": len(cands)}


def _door_guess(page):
    """Quarter-circle door swings: radius ~ 0.85 m. Approximate only."""
    rs = []
    for p in page.get("paths") or []:
        if not (p.get("is_arc") or p.get("n_curves")):
            continue
        xs = [q[0] for q in p["pts"]]; ys = [q[1] for q in p["pts"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        r = max(w, h)
        # a swing is an open quarter arc (chord ~ r*1.41, or ~ r with the leaf in the same path); closed or full
        # circles are fixtures / air terminals / column marks, not doors
        if p.get("closed") or len(p["pts"]) < 2 or math.dist(p["pts"][0], p["pts"][-1]) < 0.3 * r:
            continue
        if w > 3 and h > 3 and 0.7 < w / h < 1.4:
            rs.append(r)
    if len(rs) < 2 or not _plausible(0.85 / median(rs)):
        return None
    return {"m_per_pt": 0.85 / median(rs), "n": len(rs)}


def _wall_guess(walls):
    """m/pt from the median wall thickness (~0.2 m), only to size the door-gap closing before the scale is known."""
    th = [w.get("thickness_pt") for w in walls or [] if w.get("thickness_pt")]
    th = [t for t in th if t > 0]
    return 0.2 / median(th) if th else None


def prelim_m_per_pt(page, walls=None):
    ratio, _ = _ratio(page)
    if ratio:
        return PT_M * ratio
    sb = _scalebar(page)
    if sb:
        return sb
    dm = _dims(page)
    if dm:
        return dm["m_per_pt"]
    dg = _door_guess(page)
    if dg:
        return dg["m_per_pt"]
    g = _wall_guess(walls)
    if g and 0.002 < g < 0.5:
        return g
    return PT_M * 100


def scale(page: dict, rooms_: list) -> dict:
    """The addendum's ladder. Returns {m_per_pt, method, confidence, ratio, check}."""
    check = {}
    ratio, sheet = _ratio(page)
    fit = _area_fit(rooms_ or [])
    if fit:
        check.update({"printed_areas_rel_err": round(fit["printed_areas_rel_err"], 4), "fit_m_per_pt": fit["m_per_pt"],
                      "fit_n": fit["n"]})
    if ratio:
        m = PT_M * ratio
        out = {"m_per_pt": m, "method": f"printed 1:{ratio}", "confidence": 0.95, "ratio": f"1:{ratio}", "check": check}
        if sheet:
            check["sheet"] = sheet
        if fit:
            lin = fit["m_per_pt"] / m - 1
            check["fit_vs_printed_rel"] = round(lin, 4)          # linear (m per pt)
            check["fit_vs_printed_area_rel"] = round((1 + lin) ** 2 - 1, 4)
            check["agree_2pct"] = abs(lin) <= 0.02
            if abs(lin) > 0.05 and fit["n"] >= 3:
                check["flag"] = f"printed 1:{ratio} and the printed room areas disagree by {abs(lin) * 100:.1f}%"
                out["confidence"] = 0.6
                # a wrong 1:N (detail scale, other viewport) is far off; trust many consistent printed areas then
                if abs(lin) > 0.25 and fit["n"] >= 3 and fit["printed_areas_rel_err"] < 0.05:
                    return {"m_per_pt": fit["m_per_pt"], "method": "printed areas fit", "confidence": 0.75,
                            "ratio": f"1:{ratio}", "check": check}
            else:
                out["confidence"] = 0.98
        return out
    sb = _scalebar(page)
    if sb:
        if fit:
            check["fit_vs_scalebar_rel"] = round(fit["m_per_pt"] / sb - 1, 4)
        return {"m_per_pt": sb, "method": "scale bar", "confidence": 0.8, "ratio": f"1:{round(sb / PT_M)}", "check": check}
    dm = _dims(page)
    if dm:
        check["dims_m_per_pt"] = dm["m_per_pt"]
        check["dims_n"] = dm["n"]
    # the area fit outranks dimensions unless its own residuals say the room polygons are poor (>5%)
    if fit and (fit["printed_areas_rel_err"] <= 0.05 or not dm):
        conf = 0.85 if fit["n"] >= 4 and fit["printed_areas_rel_err"] < 0.03 else 0.65
        if dm:
            check["fit_vs_dims_rel"] = round(fit["m_per_pt"] / dm["m_per_pt"] - 1, 4)
        m, method = fit["m_per_pt"], "printed areas fit"
        n_fit = m / PT_M
        std = min(STD_RATIOS, key=lambda n: abs(n_fit / n - 1))
        if abs(n_fit / std - 1) <= 0.03 and fit["n"] >= 3:   # drawings use standard scales: snap a close fit
            check["fit_ratio"] = round(n_fit, 2)
            m, method = PT_M * std, f"printed areas fit (snapped to 1:{std})"
        return {"m_per_pt": m, "method": method, "confidence": conf,
                "ratio": f"1:{round(m / PT_M)}", "check": check}
    if dm:
        if fit:
            check["fit_vs_dims_rel"] = round(fit["m_per_pt"] / dm["m_per_pt"] - 1, 4)
        return {"m_per_pt": dm["m_per_pt"], "method": "dimensions", "confidence": 0.6,
                "ratio": f"1:{round(dm['m_per_pt'] / PT_M)}", "check": check}
    dg = _door_guess(page)
    if dg:
        check["doors_n"] = dg["n"]
        check["approximate"] = True
        return {"m_per_pt": dg["m_per_pt"], "method": "door guess", "confidence": 0.3,
                "ratio": f"1:{round(dg['m_per_pt'] / PT_M)}", "check": check}
    return {"m_per_pt": None, "method": None, "confidence": 0.0, "ratio": None, "check": check}


# ---------------------------------------------------------------- rooms

def simple_walls(page):
    """Dev/fallback wall polygons: dark-filled closed paths of some size (the draft's rule). pt, y down."""
    out = []
    for p in page.get("paths") or []:
        pts = p.get("pts") or []
        f = p.get("fill")
        if len(pts) >= 3 and f is not None and sum(f) / 3 < 0.35:
            if shoelace(pts) >= 1.0:
                out.append({"polygon": [list(q) for q in pts], "thickness_pt": None, "style": "fill"})
    return out


def _poly_list(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon"]


LEGEND_RE = re.compile(r"^(legend[ae]?|légende|legende|key|symbols?|zeichenerklärung|progetto|projekt|project|projet|"
                       r"title|drawing|plan-?nr\.?|massstab|maßstab|scala|échelle|echelle|scale|sheet|date|datum|data)\b", re.I)


def _excluded_box(page):
    """Boxes (pt) holding the legend / title block: from the drawing frame of pdf_vector (if available) and from
    anchor words ('Legend', 'Project', 'Scale' ...) near the bottom/right edge, cut at the nearest long divider."""
    W, H = page.get("W_pt") or 0, page.get("H_pt") or 0
    if not W or not H:
        return []
    hl, vl = [], []
    for p in page.get("paths") or []:
        pts = p.get("pts") or []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if abs(y0 - y1) < 0.5 and abs(x1 - x0) > 0.3 * W:
                hl.append((y0 + y1) / 2)
            elif abs(x0 - x1) < 0.5 and abs(y1 - y0) > 0.3 * H:
                vl.append((x0 + x1) / 2)
    boxes = []
    for w in page.get("words") or []:
        b = w.get("bbox")
        if not b or not LEGEND_RE.match(str(w.get("text") or "").strip()):
            continue
        h = max(1.0, b[3] - b[1])
        if _cy(b) > 0.65 * H:
            cut = [y for y in hl if y < b[1] and y > 0.5 * H]
            boxes.append([0, max(cut) if cut else b[1] - 2 * h, W, H])
        elif _cx(b) > 0.7 * W:
            cut = [x for x in vl if x < b[0] and x > 0.5 * W]
            boxes.append([max(cut) if cut else b[0] - 2 * h, 0, W, H])
    return boxes


def rooms(page: dict, walls: list) -> list:
    ex = _excluded_box(page)
    words = [w for w in page.get("words") or [] if not (w.get("bbox") and any(
        bx[0] <= _cx(w["bbox"]) <= bx[2] and bx[1] <= _cy(w["bbox"]) <= bx[3] for bx in ex))]
    blocks = label_blocks(words)
    comps = _components(page, walls)
    if comps is None:   # no walls to read regions from: label-only rooms
        return [_room(None, [b]) for b in blocks]
    polys, mpp = comps
    from shapely.geometry import Point
    owner = {}
    lone = []
    for i, b in enumerate(blocks):
        pt = Point(*b["xy"])
        hit = [k for k, g in enumerate(polys) if g.covers(pt)]
        if not hit:
            near = [(g.distance(pt), k) for k, g in enumerate(polys)]
            near = [x for x in near if x[0] < 0.5 / mpp]
            hit = [min(near)[1]] if near else []
        if hit:
            owner.setdefault(min(hit, key=lambda k: polys[k].area), []).append(i)
        else:
            lone.append(i)
    out = []
    # the main plan region: hull of the labelled regions; unlabelled regions outside it (neighbouring roofs,
    # site context) are not rooms
    from shapely.ops import unary_union
    lab_g = [polys[k] for k in owner]
    main = unary_union(lab_g).convex_hull.buffer(0.5 / mpp) if lab_g else None
    spare = []   # unlabelled scraps inside the plan: may still complete a room cut short (see _printed_merge)
    for k, g in enumerate(polys):
        bl = [blocks[i] for i in owner.get(k, [])]
        if not bl and (g.area * mpp * mpp < 2.0 or main is None or not main.contains(g.representative_point())):
            if main is not None and main.contains(g.representative_point()):
                spare.append(g)
            continue   # unlabelled scraps (shafts, wall cavities) or outside the plan
        if not bl:
            try:
                if _void_region(page, words, g):
                    continue   # a shaft / void / floor opening drawn with its mark: not a room
            except Exception:  # noqa: BLE001
                pass
        real = [b for b in bl if not _is_unit_tag(b)]
        groups = _group_labels(real, mpp)
        if len(groups) >= 2 and _RASTER.get("ids"):
            try:   # several room labels in one region: partition it between them, one room per label
                parts, groups = _split_groups(page, groups, _RASTER["ids"][k], mpp)
                out += [_room(q, grp, divided=True) for q, grp in zip(parts, groups)]
                continue
            except Exception:  # noqa: BLE001 - keep the merged room
                pass
        out.append(_room(_coords(g), bl))
    out += [_room(None, [blocks[i]]) for i in lone]
    if os.environ.get("PDF_ROOMS_PRINTED_MERGE", "1") != "0":
        try:
            out = _printed_merge(page, out, spare, mpp)
        except Exception:  # noqa: BLE001 - keep the rooms as cut
            pass
    return out


def _printed_merge(page, out, spare, mpp, gap_m=0.3, under=0.88, over=1.08):
    """A room whose polygon is clearly smaller than its printed area was cut short by linework inside it (stair
    flights split by a handrail, a guardrail, benches, equipment drawn as thin walls): unlabelled neighbouring
    pieces across a thin barrier (<= `gap_m`) join it while that brings the measured area closer to the printed
    one without passing it by more than `over`. Needs a known scale (printed 1:N / scale bar / dimensions, else a
    fit of the printed areas over the rooms that already agree). Labelled rooms are never merged with each other."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    ratio, _ = _ratio(page)
    m = PT_M * ratio if ratio else (_scalebar(page) or (_dims(page) or {}).get("m_per_pt"))
    if not m:
        fit = _area_fit(out)
        m = fit["m_per_pt"] if fit and fit["n"] >= 3 and fit["printed_areas_rel_err"] < 0.08 else None
    if not m:
        return out
    out, spare = _relabel_oversized(out, spare, m, page)
    pool = [g for g in spare if g.area > 0]
    pool += [Polygon(r["polygon"]).buffer(0) for r in out if r["polygon"] and not r["labels"]]
    keep_unl = [r for r in out if r["polygon"] and not r["labels"]]
    pool_r = [None] * (len(pool) - len(keep_unl)) + keep_unl     # room dict of each pool piece (None = scrap)
    tg = [i for i, r in enumerate(out) if r["polygon"] and r["area_printed_m2"] and r["labels"]
          and r["pts_area"] * m * m < under * r["area_printed_m2"]]
    if not tg or not pool:
        return out
    gap = gap_m / m
    geo = {i: Polygon(out[i]["polygon"]).buffer(0) for i in tg}
    used, gone, bad = set(), set(), set()
    changed = True
    while changed:
        changed = False
        best = None
        for i in tg:
            P_ = out[i]["area_printed_m2"]
            M = geo[i].area * m * m
            if M >= under * P_:
                continue
            for j, u in enumerate(pool):
                if j in used or (i, j) in bad:
                    continue
                d = geo[i].distance(u)
                if d > gap:
                    continue
                M2 = M + u.area * m * m
                if M2 > over * P_ or abs(M2 - P_) >= abs(M - P_):
                    continue
                gain = abs(M - P_) - abs(M2 - P_)
                if best is None or gain > best[0]:
                    best = (gain, i, j, d)
        if best:
            _, i, j, d = best
            h = d / 2 + 0.05 / m
            g = unary_union([geo[i].buffer(h, join_style=2), pool[j].buffer(h, join_style=2)]).buffer(-h, join_style=2)
            g = max(_poly_list(g), key=lambda q: q.area, default=None)
            if g is None or g.area < 0.97 * (geo[i].area + pool[j].area):
                bad.add((i, j))   # this pair does not join into one piece; the piece stays free for other rooms
                changed = True
                continue
            used.add(j)
            geo[i] = g
            if pool_r[j] is not None:
                gone.add(id(pool_r[j]))
            changed = True
    for i in tg:
        if geo[i].area > Polygon(out[i]["polygon"]).buffer(0).area * 1.001:
            out[i]["polygon"] = _coords(geo[i])
            out[i]["pts_area"] = round(shoelace(out[i]["polygon"]), 3)
            out[i]["completed"] = True
    return [r for r in out if id(r) not in gone]



def _relabel_oversized(out, spare, m, page=None, over=2.0, slack_m2=2.0, reach_m=1.5, tol=0.3):
    """A small room's tag is often printed just outside the room (below a WC cubicle, in the lobby in front of its
    door): the tag then names the lobby, which measures far more than the printed area, while the cubicle itself
    is left unlabelled. A single-tag room measuring over `over` x its printed area (and > `slack_m2` more) whose
    tag lies within `reach_m` of an unlabelled piece measuring the printed area (+-`tol`) gives its tag to that
    piece; the lobby becomes an unlabelled piece (free for _printed_merge to join to the room it belongs to)."""
    from shapely.geometry import Point, Polygon
    cand = [("s", k, g) for k, g in enumerate(spare) if g.area > 0]
    cand += [("r", k, Polygon(r["polygon"]).buffer(0)) for k, r in enumerate(out) if r["polygon"] and not r["labels"]]
    if not cand:
        return out, spare
    taken, drop_s = set(), set()
    new_rooms = []
    for r in out:
        P_ = r.get("area_printed_m2")
        if not (r["polygon"] and P_ and len(r["labels"]) == 1 and r.get("label_xy")):
            continue
        M = (r.get("pts_area") or 0) * m * m
        if M <= over * P_ or M - P_ <= slack_m2:
            continue
        pt = Point(*r["label_xy"])
        best = None
        for c in cand:
            if (c[0], c[1]) in taken:
                continue
            a = c[2].area * m * m
            if abs(a - P_) > tol * P_:
                continue
            d = c[2].distance(pt) * m
            if d <= reach_m and (best is None or d < best[0]):
                best = (d, c)
        if best is None:   # the room itself joined through its door to the space the tag sits in: cut at the neck
            g0 = Polygon(r["polygon"]).buffer(0)
            cut = _neck_split(g0, P_, pt, m, reach_m, tol, drawn=_drawn_near(page, g0))
            if cut:
                tagged = {**r, "polygon": _coords(cut[0]), "pts_area": round(cut[0].area, 3), "relabelled": True}
                new_rooms.append((r, tagged, {**_room(_coords(cut[1]), []), "labels": []}))
            continue
        kind, k, g = best[1]
        taken.add((kind, k))
        lobby = {**_room(r["polygon"], []), "labels": []}
        tagged = {**r, "polygon": _coords(g), "pts_area": round(g.area, 3), "relabelled": True}
        if kind == "s":
            drop_s.add(k)
        else:
            out[k]["_gone"] = True
        new_rooms.append((r, tagged, lobby))
    if not new_rooms:
        return out, spare
    swap = {id(r): (t, lb) for r, t, lb in new_rooms}
    res = []
    for r in out:
        if r.get("_gone"):
            continue
        if id(r) in swap:
            res += list(swap[id(r)])
        else:
            res.append(r)
    return res, [g for k, g in enumerate(spare) if k not in drop_s]


def _neck_split(g, P_, pt, m, reach_m, tol, radii_m=(0.42, 0.36, 0.3), drawn=None):
    """(room part, rest) of polygon `g` cut at a door-wide neck: a morphological opening by r (necks narrower
    than 2r part) leaves a piece measuring the printed area `P_` (+-`tol`) within `reach_m` of the tag `pt`; the
    rest keeps the remaining area. None when no such piece."""
    for r_m in radii_m:
        r = r_m / m
        op = g.buffer(-r, join_style=2).buffer(r, join_style=2)
        parts = _poly_list(op)
        if len(parts) < 2:
            continue
        best = None
        for q in parts:
            a = q.area * m * m
            d = q.distance(pt) * m
            if abs(a - P_) <= tol * P_ and d <= reach_m and (best is None or d < best[0]):
                best = (d, q)
        if best is None:
            continue
        room = best[1].buffer(0.02 / m, join_style=2).intersection(g)
        room = max(_poly_list(room), key=lambda q: q.area, default=None)
        rest = max(_poly_list(g.difference(room.buffer(0.01 / m, join_style=2))), key=lambda q: q.area, default=None) \
            if room is not None else None
        if room is None or rest is None or rest.area * m * m < 0.5 or not _cut_drawn(room, rest, drawn, m):
            continue
        return room, rest
    return _area_cut(g, P_, pt, m, tol, drawn=drawn)


def _area_cut(g, P_, pt, m, tol, max_cut_m=2.2, step_m=0.05, drawn=None):
    """(room part, rest) of `g` cut by one straight line (along the polygon's main axes) where the part holding
    the tag `pt` measures the printed area `P_` (+-`tol`): a wall of the room not read (a cubicle front drawn as a
    thin line) leaves it joined to the lobby; the shortest such cut (<= `max_cut_m`) is taken. None otherwise."""
    from shapely import affinity
    from shapely.geometry import box
    try:
        rr = g.minimum_rotated_rectangle
        cs = list(rr.exterior.coords)
        ang = math.degrees(math.atan2(cs[1][1] - cs[0][1], cs[1][0] - cs[0][0]))
    except Exception:  # noqa: BLE001
        ang = 0.0
    best = None
    for a in {0.0, round(ang % 90.0, 3)}:
        q = affinity.rotate(g, -a, origin=pt)
        x0, y0, x1, y1 = q.bounds
        for axis in (0, 1):
            lo, hi = (x0, x1) if axis == 0 else (y0, y1)
            c = lo + step_m / m
            while c < hi:
                for side in (0, 1):
                    if axis == 0:
                        hb = box(x0 - 1, y0 - 1, c, y1 + 1) if side == 0 else box(c, y0 - 1, x1 + 1, y1 + 1)
                    else:
                        hb = box(x0 - 1, y0 - 1, x1 + 1, c) if side == 0 else box(x0 - 1, c, x1 + 1, y1 + 1)
                    if not hb.covers(pt):
                        continue
                    part = next((p_ for p_ in _poly_list(q.intersection(hb)) if p_.buffer(1e-6).covers(pt)), None)
                    if part is None:
                        continue
                    ar = part.area * m * m
                    if abs(ar - P_) > tol * P_:
                        continue
                    ln = part.length
                    edge = (box(c - 1e-3, y0 - 1, c + 1e-3, y1 + 1) if axis == 0 else
                            box(x0 - 1, c - 1e-3, x1 + 1, c + 1e-3)).intersection(part.boundary).length * m
                    if edge > max_cut_m:
                        continue
                    if not _line_drawn(axis, c, part, drawn, a, pt, m):
                        continue   # the cut must run along drawn linework (a partition / cubicle front)
                    key = (round(edge, 1), abs(ar - P_))
                    if best is None or key < best[0]:
                        best = (key, a, part)
                c += step_m / m
    if best is None:
        return None
    room = affinity.rotate(best[2], best[1], origin=pt)
    rest = max(_poly_list(g.difference(room.buffer(0.01 / m, join_style=2))), key=lambda q: q.area, default=None)
    if rest is None or rest.area * m * m < 0.5:
        return None
    return room, rest


def _drawn_near(page, g, pad_m=0.5, m=None):
    """Drawn stroke linework (shapely MultiLineString, pt) around polygon g, or None."""
    if not page:
        return None
    from shapely.geometry import LineString, MultiLineString, box
    x0, y0, x1, y1 = g.bounds
    pad = max(x1 - x0, y1 - y0) * 0.05 + 2.0
    bb = box(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    ls = []
    for p in page.get("paths") or []:
        if p.get("stroke") is None:
            continue
        pts = p.get("pts") or []
        if len(pts) < 2:
            continue
        xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
        if max(xs) < bb.bounds[0] or min(xs) > bb.bounds[2] or max(ys) < bb.bounds[1] or min(ys) > bb.bounds[3]:
            continue
        seq = list(pts) + ([pts[0]] if p.get("closed") else [])
        ls.append(LineString(seq))
    return MultiLineString(ls) if ls else None


def _along(cut, drawn, m, tol_m=0.04):
    """Fraction of the cut line covered by drawn lines running along it (crossing strokes do not count)."""
    if drawn is None or cut.length <= 0:
        return 0.0
    tol = tol_m / m
    hit = drawn.intersection(cut.buffer(tol, cap_style=2))
    pieces = [q for q in getattr(hit, "geoms", [hit]) if not q.is_empty and q.length > 4 * tol]
    from shapely.ops import unary_union
    if not pieces:
        return 0.0
    cov = unary_union([q.buffer(tol, cap_style=2) for q in pieces]).intersection(cut).length
    return cov / cut.length


def _line_drawn(axis, c, part, drawn, ang, pt, m, need=0.4):
    """The straight cut at c (rotated frame by `ang` about pt) of `part` runs along drawn linework (>= `need`)."""
    from shapely import affinity
    from shapely.geometry import LineString
    x0, y0, x1, y1 = part.bounds
    ln = LineString([(c, y0 - 1), (c, y1 + 1)]) if axis == 0 else LineString([(x0 - 1, c), (x1 + 1, c)])
    ln = ln.intersection(part.buffer(1e-3))
    if ln.is_empty or ln.length <= 0:
        return False
    ln = affinity.rotate(ln, ang, origin=pt)
    return _along(ln, drawn, m) >= need


def _cut_drawn(room, rest, drawn, m, need=0.4):
    """The boundary between room and rest (a cut inside one region) runs along drawn linework (>= `need`)."""
    sh = room.boundary.intersection(rest.buffer(0.05 / m))
    if sh.is_empty or sh.length <= 0:
        return False
    return _along(sh, drawn, m) >= need


VOID_RX = re.compile(r"\b(opening|void|shaft|ouverture|vide|öffnung|offnung|aussparung|schacht|luftraum|aukko|"
                     r"kuilu|hormi|apertura|vano|cavedio|hueco|patinillo)\b", re.I)


def _void_region(page, words, g, frac=0.6):
    """An unlabelled region that is a shaft, void or floor opening: a word such as OPENING / VOID / SHAFT printed
    inside it, or the void mark (two diagonals crossing it corner to corner, each >= `frac` of its diagonal)."""
    from shapely.geometry import LineString, Point
    for w in words or []:
        b = w.get("bbox")
        if b and VOID_RX.search(str(w.get("text") or "")) and g.covers(Point((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)):
            return True
    x0, y0, x1, y1 = g.bounds
    diag = math.hypot(x1 - x0, y1 - y0)
    if diag <= 0:
        return False
    slopes = set()
    for p in page.get("paths") or []:
        pts = p.get("pts") or []
        if p.get("stroke") is None or len(pts) < 2:
            continue
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if max(ax, bx) < x0 or min(ax, bx) > x1 or max(ay, by) < y0 or min(ay, by) > y1:
                continue
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < frac * diag or min(abs(dx), abs(dy)) < 0.25 * L:
                continue   # short, or not diagonal
            if LineString([(ax, ay), (bx, by)]).intersection(g.buffer(0.02 * diag)).length >= frac * diag:
                slopes.add(dx * dy > 0)
        if len(slopes) == 2:
            return True
    return False

def _room(poly, bl, divided=False):
    """One room dict; several labels in one region are kept together (not split). Unit/apartment tags
    (TYPE B / T412 / Whg. A, or an area covering the others) are dropped when real room labels share the region."""
    if len(bl) > 1:
        pr = [b["area_printed_m2"] for b in bl if b["area_printed_m2"]]
        keep = [b for b in bl if not _is_unit_tag(b) and not (len(pr) >= 3 and b["area_printed_m2"]
                                                              and b["area_printed_m2"] >= 0.45 * sum(pr))]
        bl = keep or bl
    # one name and one number per room (IfcSpace LongName / Name): from the main tag (largest printed area, else
    # the first with a name); every tag stays in `labels`
    main = sorted(bl, key=lambda b: (-(b["area_printed_m2"] or 0), not b["label"], not b["number"]))
    lab = next((b["label"] for b in main if b["label"]), None)
    num = next((b["number"] for b in main if b["number"]), None)
    pr = [b["area_printed_m2"] for b in bl]
    ap = round(sum(pr), 3) if pr and all(v is not None for v in pr) else None
    b0 = bl[0] if bl else None
    if b0:
        bb = [min(b["bbox"][0] for b in bl), min(b["bbox"][1] for b in bl), max(b["bbox"][2] for b in bl),
              max(b["bbox"][3] for b in bl)]
    return {"polygon": poly, "label": lab, "number": num, "area_printed_m2": ap, "unlabelled": not bl,
            "label_bbox": [round(v, 3) for v in bb] if b0 else None,
            "label_xy": [round(v, 3) for v in b0["xy"]] if b0 else None,
            "labels": [{"label": b["label"], "number": b["number"], "area_printed_m2": b["area_printed_m2"]} for b in bl],
            "pts_area": round(shoelace(poly), 3) if poly else None, "split": False, "merged": len(bl) > 1,
            "divided": divided}



def _double_lines(page, box, mpp, smin_m=0.03, smax_m=0.22, lmin_m=0.6, gap_m=0.05):
    """Light partitions drawn as two parallel thin lines (gypsum / glass walls the wall reader leaves out):
    pairs of solid dark axis-aligned strokes 3-22 cm apart overlapping >= 0.6 m. Returns [[x0, y0, x1, y1]] strips (pt)."""
    import numpy as np
    bx0, by0, bx1, by1 = box
    tol = 0.25
    seg_min = 0.25 / mpp   # stroked text glyphs and hatch dashes are shorter; they must not chain into runs
    hz, vt = {}, {}
    for p in page.get("paths") or []:
        st = p.get("stroke")
        if p.get("dashed") or st is None or p.get("pattern") or sum(st) / max(1, len(st)) > 0.55:
            continue   # grey linework: grid axes, ceiling and hidden lines (partitions are drawn dark)
        pts = p.get("pts") or []
        if len(pts) < 2 or len(pts) > 16:
            continue
        seq = list(zip(pts, pts[1:] + (pts[:1] if p.get("closed") else [])))
        for (ax, ay), (bx, by) in seq:
            if not (bx0 <= ax <= bx1 and by0 <= ay <= by1):
                continue
            if abs(ay - by) <= 0.05 and abs(ax - bx) > seg_min:
                hz.setdefault(round((ay + by) / 2 / tol), []).append((min(ax, bx), max(ax, bx)))
            elif abs(ax - bx) <= 0.05 and abs(ay - by) > seg_min:
                vt.setdefault(round((ax + bx) / 2 / tol), []).append((min(ay, by), max(ay, by)))
    gap, lmin = gap_m / mpp, lmin_m / mpp
    smin, smax = smin_m / mpp, smax_m / mpp
    out = []
    for key, runs in ((0, hz), (1, vt)):
        rr = []
        for c, iv in runs.items():
            iv.sort()
            a0, a1 = iv[0]
            for b0, b1 in iv[1:] + [(math.inf, math.inf)]:
                if b0 - a1 <= gap:
                    a1 = max(a1, b1)
                    continue
                if a1 - a0 >= lmin:
                    rr.append((c * tol, a0, a1))
                a0, a1 = b0, b1
        if len(rr) < 2:
            continue
        rr.sort()
        cs = [r[0] for r in rr]
        import bisect
        for i, (c0, a0, a1) in enumerate(rr):
            lo = bisect.bisect_left(cs, c0 + smin, i + 1)
            best = None
            for j in range(lo, len(rr)):
                c1, b0, b1 = rr[j]
                if c1 > c0 + smax:
                    break
                o0, o1 = max(a0, b0), min(a1, b1)
                if o1 - o0 >= lmin:
                    best = (o0, o1, c1)
                    break   # the nearest partner line
            if best:
                o0, o1, c1 = best
                out.append([o0, c0, o1, c1] if key == 0 else [c0, o0, c1, o1])
    return out




def _draw_strips(mask, strips, x0, y0, k, mpp, reach_m=0.2, rounds=4, both=False):
    """Draw partition strips with an end (`both`: both ends) on a wall or an already drawn strip (chains and
    T-junctions over a few rounds); loose pairs in the open (furniture, dimension lines) are left out."""
    import numpy as np
    import cv2
    if not strips:
        return 0
    S = (np.array(strips, float) - [x0, y0, x0, y0]) * k
    S = np.round(S).astype(int)
    Hp, Wp = mask.shape
    S[:, [0, 2]] = np.clip(S[:, [0, 2]], 0, Wp - 1)
    S[:, [1, 3]] = np.clip(S[:, [1, 3]], 0, Hp - 1)
    horiz = (S[:, 2] - S[:, 0]) >= (S[:, 3] - S[:, 1])
    my, mx = (S[:, 1] + S[:, 3]) // 2, (S[:, 0] + S[:, 2]) // 2
    # end points just beyond each short end
    e1x = np.where(horiz, S[:, 0] - 1, mx); e1y = np.where(horiz, my, S[:, 1] - 1)
    e2x = np.where(horiz, S[:, 2] + 1, mx); e2y = np.where(horiz, my, S[:, 3] + 1)
    e1x, e2x = np.clip(e1x, 0, Wp - 1), np.clip(e2x, 0, Wp - 1)
    e1y, e2y = np.clip(e1y, 0, Hp - 1), np.clip(e2y, 0, Hp - 1)
    if rounds <= 0:   # no end test: every strip
        for a, b, c, d in S:
            cv2.rectangle(mask, (int(a), int(b)), (int(c), int(d)), 255, -1)
        return len(S)
    reach = reach_m / mpp * k
    done = np.zeros(len(S), bool)
    n = 0
    for _ in range(rounds):
        dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
        t1, t2 = dist[e1y, e1x] <= reach, dist[e2y, e2x] <= reach
        hit = ~done & ((t1 & t2) if both else (t1 | t2))
        if not hit.any():
            break
        for a, b, c, d in S[hit]:
            cv2.rectangle(mask, (int(a), int(b)), (int(c), int(d)), 255, -1)
        n += int(hit.sum())
        done |= hit
    return n


def _partitions(page, mask, x0, y0, k, mpp, reach_m=0.15, min_m=0.8, max_m=12.0, gap_m=0.4, inline=None):
    """Glass partitions and light walls drawn as thin lines: straight strokes (dashed runs merged when collinear
    with gaps < 0.4 m) 0.8-12 m long whose both ends touch a wall or an accepted separator (within 15 cm, so
    T-junctions count) and that run through free space are drawn into the wall mask as room separators."""
    import numpy as np
    import cv2
    tol = 0.5
    hz, vt, other = {}, {}, []
    for p in page.get("paths") or []:
        pts = p.get("pts") or []
        if len(pts) != 2 or p.get("closed") or p.get("stroke") is None or p.get("fill") is not None:
            continue
        (ax, ay), (bx, by) = pts
        if abs(ay - by) <= tol:
            hz.setdefault(round((ay + by) / 2 / tol), []).append((min(ax, bx), max(ax, bx)))
        elif abs(ax - bx) <= tol:
            vt.setdefault(round((ax + bx) / 2 / tol), []).append((min(ay, by), max(ay, by)))
        elif not p.get("dashed"):
            other.append((ax, ay, bx, by))
    gap = gap_m / mpp
    segs = list(other)
    for key, runs in ((0, hz), (1, vt)):
        for c, iv in runs.items():
            iv.sort()
            a0, a1 = iv[0]
            for b0, b1 in iv[1:] + [(math.inf, math.inf)]:
                if b0 - a1 <= gap:
                    a1 = max(a1, b1)
                    continue
                cc = c * tol
                segs.append((a0, cc, a1, cc) if key == 0 else (cc, a0, cc, a1))
                a0, a1 = b0, b1
    segs = [q for q in segs if min_m <= math.hypot(q[2] - q[0], q[3] - q[1]) * mpp <= max_m]
    if not segs:
        return 0
    S = np.array(segs, float)
    A = np.round((S[:, :2] - [x0, y0]) * k).astype(int)
    B = np.round((S[:, 2:] - [x0, y0]) * k).astype(int)
    Hp, Wp = mask.shape
    ok = (A[:, 0] >= 0) & (A[:, 0] < Wp) & (A[:, 1] >= 0) & (A[:, 1] < Hp) & \
         (B[:, 0] >= 0) & (B[:, 0] < Wp) & (B[:, 1] >= 0) & (B[:, 1] < Hp)
    A, B = A[ok], B[ok]
    if not len(A):
        return 0
    reach = reach_m / mpp * k
    wall_dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
    free_mid = wall_dist[(A[:, 1] + B[:, 1]) // 2, (A[:, 0] + B[:, 0]) // 2] > reach   # not along a wall
    done = np.zeros(len(A), bool)
    n = 0
    for _ in range(3):   # a second/third round accepts T-junctions onto separators found before
        dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
        hit = ~done & free_mid & (dist[A[:, 1], A[:, 0]] <= reach) & (dist[B[:, 1], B[:, 0]] <= reach)
        if not hit.any():
            break
        for (ax, ay), (bx, by) in zip(A[hit], B[hit]):
            if inline is not None and _wall_run_gap(mask, (ax, ay), (bx, by), k / mpp):
                inline.append(((int(ax), int(ay)), (int(bx), int(by))))
            cv2.line(mask, (int(ax), int(ay)), (int(bx), int(by)), 255, 2)
            n += 1
        done |= hit
    return n


def _wall_run_gap(mask, a, b, px_per_m, near_m=(0.5, 0.8)):
    """The drawn line a-b closes a gap IN a wall run (a facade line drawn across a door / glazing bay): the wall
    mask continues along the line's own direction 0.5-0.8 m beyond both ends. A partition meeting walls at
    T-junctions ends in a cross wall that is thinner than that, so it is not one."""
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    if L <= 0:
        return False
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    Hp, Wp = mask.shape
    for (px, py), sg in ((a, -1), (b, 1)):
        for d in near_m:
            x = int(round(px + sg * ux * d * px_per_m)); y = int(round(py + sg * uy * d * px_per_m))
            if not (0 <= x < Wp and 0 <= y < Hp) or mask[y, x] == 0:
                return False
    return True


_RASTER: dict = {}


def _group_labels(bl, mpp, near_m=0.5):
    """Label blocks closer than ~0.5 m to each other (a name block and its tag lines) seed one room together."""
    gap = near_m / mpp
    par = list(range(len(bl)))

    def f(i):
        while par[i] != i:
            i = par[i]
        return i
    for i in range(len(bl)):
        for j in range(i + 1, len(bl)):
            a, b = bl[i]["bbox"], bl[j]["bbox"]
            if all(q.get("number") and q.get("area_printed_m2") for q in (bl[i], bl[j])) and \
                    bl[i]["number"] != bl[j]["number"]:
                continue   # two complete tags (own number and own area) are two rooms, however close
            if max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3]) < gap:
                par[f(j)] = f(i)
    out = {}
    for i in range(len(bl)):
        out.setdefault(f(i), []).append(bl[i])
    return list(out.values())


def _watershed(lev, reg, seed_px, skip=()):
    """Seeded flooding of `reg` by levels (`lev`: 0 deep inside, rising towards the walls): at each level every
    part grows geodesically into the pixels at or below it, so parts meet at the narrowest necks (door gaps,
    corridor mouths) and split open areas half way between their seeds. Every region pixel gets a part 1..G."""
    import numpy as np
    import cv2
    lab = np.zeros(reg.shape, np.uint16)
    for gi, sp in enumerate(seed_px):
        if gi in skip:
            continue
        for py, px in sp:
            lab[py, px] = gi + 1
    k3 = np.ones((3, 3), np.uint8)
    free = reg & (lab == 0)
    top = int(lev[reg].max()) if reg.any() else 0
    for L in range(top + 1):
        allowed = free & (lev <= L)
        while allowed.any():
            d = cv2.dilate(lab, k3)
            upd = allowed & (d > 0)
            if not upd.any():
                break
            lab[upd] = d[upd]
            allowed &= ~upd
            free &= ~upd
    return lab.astype(np.int32)


def _cap_oversized(lab, groups, img3, reg, px_m2, seed_px, over=1.8, slack_m2=3.0):
    """A label with a small printed area that took a large part (a closet tag in an open area, its box not read
    as walls) keeps only the printed area around its tag; the rest of its part goes to the other labels."""
    import numpy as np
    G = len(groups)
    if G < 2:
        return lab
    areas = np.bincount(lab.ravel(), minlength=G + 1)[1:G + 1] * px_m2
    big = []
    for gi, grp in enumerate(groups):
        pr = [b["area_printed_m2"] for b in grp]
        if pr and all(v for v in pr):
            p = sum(pr)
            if areas[gi] > over * p and areas[gi] > p + slack_m2:
                big.append((gi, p))
    if not big or len(big) == G:
        return lab
    lab2 = _watershed(img3, reg, seed_px, skip={gi for gi, _ in big})
    if not (lab2 > 0).any():
        return lab
    yy, xx = np.nonzero(reg)
    for gi, p in big:
        part = lab == gi + 1
        py, px = seed_px[gi][0]
        ys, xs = np.nonzero(part)
        d = (ys - py) ** 2 + (xs - px) ** 2
        n = int(round(p / px_m2))
        keep = np.argsort(d)[:n]
        lab2[ys[keep], xs[keep]] = gi + 1
    return lab2


def _split_groups(page, groups, cid, mpp, min_m2=0.5, cap_m=1.5):
    """Partition one raster region between several label groups: a marker watershed of the (capped) distance to
    the walls seeded at the labels, so parts meet at the narrowest necks (door gaps, corridor mouths) and as a
    geodesic Voronoi split inside open areas. A part under `min_m2` gives its labels to the neighbour it touches
    most and the split is redone (no slivers). Returns ([polygon pt list | None], groups)."""
    import numpy as np
    import cv2
    from scipy import ndimage
    R_ = _RASTER
    grow, x0, y0, k = R_["grow"], R_["x0"], R_["y0"], R_["k"]
    sl = R_["slices"][cid - 1]
    pad = 2
    reg = np.pad(grow[sl] == cid, pad)
    oy, ox = sl[0].start - pad, sl[1].start - pad
    px_m2 = (mpp / k) ** 2
    free = reg
    if R_.get("sep") is not None:   # soft separators (thin partitions) inside the region: the parts meet on them
        free = reg & ~np.pad(R_["sep"][sl], pad)
    dist = cv2.distanceTransform(free.astype(np.uint8), cv2.DIST_L2, 5)
    cap = max(2.0, cap_m / mpp * k)
    img3 = np.round(cap - np.clip(dist, 0, cap)).astype(np.int32)   # flood levels
    img3[~reg] = 1 << 20
    _, (iy, ix) = ndimage.distance_transform_edt(~reg, return_indices=True)   # nearest region pixel
    groups = [list(g) for g in groups]
    while True:
        G = len(groups)
        seed_px = []
        for gi, grp in enumerate(groups):
            sp = []
            for b in grp:
                px = min(max(int(round((b["xy"][0] - x0) * k)) - ox, 0), reg.shape[1] - 1)
                py = min(max(int(round((b["xy"][1] - y0) * k)) - oy, 0), reg.shape[0] - 1)
                sp.append((int(iy[py, px]), int(ix[py, px])))
            seed_px.append(sp)
        lab = _watershed(img3, reg, seed_px)
        areas = np.bincount(lab.ravel(), minlength=G + 1)[1:G + 1]
        small = [gi for gi in range(G) if areas[gi] * px_m2 < min_m2]
        if not small or G == 1:
            break
        gi = min(small, key=lambda q: areas[q])
        ring = cv2.dilate((lab == gi + 1).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        nb = lab[ring & (lab > 0) & (lab != gi + 1)]
        if nb.size:
            j = int(np.bincount(nb).argmax()) - 1
        else:   # its seed took nothing: the nearest other group
            c = groups[gi][0]["xy"]
            j = min((q for q in range(G) if q != gi),
                    key=lambda q: math.hypot(groups[q][0]["xy"][0] - c[0], groups[q][0]["xy"][1] - c[1]))
        groups[j] += groups[gi]
        del groups[gi]
    lab = _cap_oversized(lab, groups, img3, reg, px_m2, seed_px)
    from shapely.geometry import Polygon
    out = []
    for gi in range(len(groups)):
        m = (lab == gi + 1).astype(np.uint8)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cs = [c for c in cs if len(c) >= 3]
        if not cs:
            out.append(None)
            continue
        cnt = cv2.approxPolyDP(max(cs, key=cv2.contourArea), 1.0, True)[:, 0, :]
        if len(cnt) < 3:
            out.append(None)
            continue
        g = Polygon([((x + ox) / k + x0, (y + oy) / k + y0) for x, y in cnt]).buffer(0)
        g = max(_poly_list(g.buffer(0.5 / k, join_style=2)), key=lambda q: q.area, default=None)
        out.append(_coords(g) if g is not None else None)
    return out, groups


def _absorb_fragments(grow, min_px):
    """Regions smaller than `min_px` pixels (slivers left in door gaps / at wall ends) join the neighbouring region
    they share the longest border with, instead of being dropped (and leaving their label without a polygon)."""
    import numpy as np
    cnt = np.bincount(grow.ravel())
    small = np.where((cnt > 0) & (cnt < min_px))[0]
    small = small[small > 0]
    if not small.size:
        return grow
    pairs = {}
    for A, B in ((grow[:, :-1], grow[:, 1:]), (grow[:-1, :], grow[1:, :])):
        m = (A != B) & (A > 0) & (B > 0)
        if not m.any():
            continue
        a, b = A[m].astype(np.int64), B[m].astype(np.int64)
        code = np.minimum(a, b) * (len(cnt) + 1) + np.maximum(a, b)
        u, c = np.unique(code, return_counts=True)
        for uu, cc in zip(u.tolist(), c.tolist()):
            pairs[uu] = pairs.get(uu, 0) + cc
    nb = {}
    for code, c in pairs.items():
        a, b = divmod(code, len(cnt) + 1)
        nb.setdefault(a, {})[b] = c
        nb.setdefault(b, {})[a] = c
    lut = np.arange(len(cnt), dtype=grow.dtype)
    size = cnt.astype(np.int64).copy()

    def fnd(a):
        while lut[a] != a:
            a = lut[a]
        return a
    for s in sorted(small.tolist(), key=lambda q: cnt[q]):
        r = fnd(s)
        if size[r] >= min_px or not nb.get(s):
            continue
        t = max(nb[s], key=lambda q: nb[s][q])
        rt = fnd(t)
        if rt != r:
            lut[r] = rt
            size[rt] += size[r]
    for a in range(len(lut)):
        lut[a] = fnd(a)
    return lut[grow]


def _components(page, walls, res_m=0.025, close_m=0.6, ext_m=1.5, frag_m2=0.5):
    """Free space between the walls as polygons (pt): rasterise walls at `res_m` per px, close gaps up to
    2*close_m (doors, windows), flood the exterior from the border, label the interior components, grow each back
    over the closing (not into the exterior or another room), vectorise. Returns ([shapely Polygon], m_per_pt)."""
    import numpy as np
    try:
        import cv2
        from shapely.geometry import Polygon
    except ImportError:
        return None
    wl = [w for w in walls or [] if len(w.get("polygon") or []) >= 3]
    if len(wl) < 3:
        return None
    mpp = prelim_m_per_pt(page, walls)
    k = mpp / res_m                                   # px per pt
    xs = [q[0] for w in wl for q in w["polygon"]]
    ys = [q[1] for w in wl for q in w["polygon"]]
    pad = 2.0 / mpp
    x0, y0 = min(xs) - pad, min(ys) - pad
    Wp, Hp = int((max(xs) + pad - x0) * k) + 1, int((max(ys) + pad - y0) * k) + 1
    if Wp * Hp > 8e6:                                 # keep memory and time bounded on huge sheets
        f = (8e6 / (Wp * Hp)) ** 0.5
        k *= f
        Wp, Hp = int(Wp * f) + 1, int(Hp * f) + 1
    mask = np.zeros((Hp, Wp), np.uint8)

    def P(poly):
        return np.round((np.array(poly, float) - [x0, y0]) * k).astype(np.int32)
    for w in wl:
        cv2.fillPoly(mask, [P(w["polygon"])], 255)
    for w in wl:
        for hole in w.get("holes") or []:
            if len(hole) >= 3:
                cv2.fillPoly(mask, [P(hole)], 0)
    # Light partitions (parallel line pairs, thin lines wall to wall) are SOFT separators: kept in their own mask
    # and used only where a region holds several room labels (_split_groups puts the cut on them). Burnt into the
    # wall mask they also cut single rooms apart at stair treads, benches, counters and equipment outlines,
    # leaving the labelled piece too small and dropping the rest.
    soft = os.environ.get("PDF_ROOMS_SOFT", "part").split(",")
    base = mask.copy()
    try:   # light partitions drawn as parallel line pairs
        _draw_strips(mask, _double_lines(page, (x0, y0, x0 + Wp / k, y0 + Hp / k), mpp), x0, y0, k, mpp, rounds=0)
    except Exception:  # noqa: BLE001
        pass
    s1 = mask.copy()
    inline = []   # drawn lines across a gap in a wall run (door / glazing chords on the wall line)
    _partitions(page, mask, x0, y0, k, mpp, inline=inline)
    sep = np.zeros(mask.shape, bool)
    if "dl" in soft:
        sep |= (s1 > 0) & (base == 0)
    if "part" in soft:
        sep |= (mask > 0) & (s1 == 0)
    mask[sep] = 0
    # ... but a drawn line on the wall's own line across a door or glazing bay bounds the room there (the door's
    # closed position / the facade line): kept hard, so a room cannot flood out through its terrace doors
    if inline:
        hard = np.zeros(mask.shape, np.uint8)
        for (ax, ay), (bx, by) in inline:
            cv2.line(hard, (ax, ay), (bx, by), 255, 2)
        mask[hard > 0] = 255
        sep &= hard == 0
    # (a morphological closing does not bridge a door in a thin wall: disks poke in from both sides; so separate
    # the rooms by dilating the walls, then grow each room back over the dilation)
    r = max(1, int(round(close_m / mpp * k)))                # doors up to ~1.2 m
    r_ext = max(r, int(round(ext_m / mpp * k)))              # exterior: glazing runs up to ~3 m along the outline
    disk = lambda rr: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rr + 1, 2 * rr + 1))  # noqa: E731

    def near(m, rr):  # dilation of mask m by a disk of radius rr, via a distance transform (fast for big radii)
        return cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 5) <= rr
    wall = mask > 0
    big = near(wall, r_ext)
    ne, labe = cv2.connectedComponents((~big).astype(np.uint8), connectivity=4)
    eb = set(np.unique(np.concatenate([labe[0], labe[-1], labe[:, 0], labe[:, -1]]).tolist())) - {0}
    ext = np.isin(labe, list(eb))
    # exterior = the outside disks (a morphological opening from the border): reaches the wall faces but only
    # pokes a little into a glazing gap narrower than 2*ext_m, so rooms behind glazed facades do not leak out
    ext = near(ext, r_ext) & ~wall
    k3 = np.ones((3, 3), np.uint8)
    free_o = (mask == 0) & ~ext
    dil = near(wall, r)
    n, lab = cv2.connectedComponents((~dil & free_o).astype(np.uint8), connectivity=4)
    cnt = np.bincount(lab.ravel(), minlength=n)
    speck = np.where(cnt < (0.4 / mpp * k) ** 2)[0]     # seeds smaller than 0.4 m x 0.4 m: slivers in door gaps
    speck = speck[speck > 0]
    if speck.size:
        lab[np.isin(lab, speck)] = 0
    # narrow rooms (closets, WCs) vanish under the dilation: seed them from what a small erosion keeps outside the
    # zone the big rooms will grow into, then grow all seeds together (a closet fills before a neighbour gets in)
    r2 = max(1, r // 3)
    zone = near(lab > 0, r + r2)
    s2 = ~near(~free_o, r2) & ~zone
    n2, lab2 = cv2.connectedComponents(s2.astype(np.uint8), connectivity=4)
    grow = lab.astype(np.int32)
    if n2 > 1:
        grow[lab2 > 0] = lab2[lab2 > 0] + n - 1
        n = n + n2 - 1
    dt = np.uint16 if n < 65000 else np.float32   # cv2.dilate works on uint16 without per-step conversions
    grow = grow.astype(dt)
    open_ = free_o.copy()
    for _ in range(r + r2 + 2):
        d = cv2.dilate(grow, k3)
        upd = open_ & (grow == 0) & (d > 0)
        if not upd.any():
            break
        grow[upd] = d[upd]
        open_ &= ~upd
    grow = grow.astype(np.int32)
    if n2 > 1:  # narrow-room pieces cut apart by a neighbour's door zone belong together
        base = n - n2 + 1
        par = {}

        def fnd(a):
            while par.get(a, a) != a:
                a = par[a]
            return a
        for A, B in ((grow[:, :-1], grow[:, 1:]), (grow[:-1, :], grow[1:, :])):
            m2 = (A >= base) & (B >= base) & (A != B)
            for a, b in set(zip(A[m2].tolist(), B[m2].tolist())):
                ra, rb = fnd(a), fnd(b)
                if ra != rb:
                    par[max(ra, rb)] = min(ra, rb)
        if par:
            lut = np.arange(n + 1, dtype=np.int32)
            for a in list(par):
                lut[a] = fnd(a)
            grow = lut[grow]
    try:
        grow = _absorb_fragments(grow, (frag_m2 ** 0.5 / mpp * k) ** 2)
    except Exception:  # noqa: BLE001 - keep the fragments (dropped below as before)
        pass
    min_px = (0.3 / mpp * k) ** 2
    polys = []
    _RASTER.clear()
    _RASTER["ids"] = []
    from scipy import ndimage
    slices = ndimage.find_objects(grow)
    for c0, sl in enumerate(slices):
        c = c0 + 1
        if sl is None:
            continue
        sub = grow[sl] == c
        if sub.sum() < min_px:
            continue
        m = np.zeros((sub.shape[0] + 2, sub.shape[1] + 2), np.uint8)
        m[1:-1, 1:-1] = sub
        oy, ox = sl[0].start - 1, sl[1].start - 1
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            continue
        cnt = max(cs, key=cv2.contourArea)
        cnt = cv2.approxPolyDP(cnt, 1.0, True)[:, 0, :]
        if len(cnt) < 3:
            continue
        g = Polygon([((x + ox) / k + x0, (y + oy) / k + y0) for x, y in cnt])
        if not g.is_valid:
            g = g.buffer(0)
        g = g.buffer(0.5 / k, join_style=2)   # contour runs through pixel centres: push out half a pixel
        g = max(_poly_list(g), key=lambda q: q.area, default=None)
        if g is not None and g.area > 0:
            polys.append(g)
            _RASTER["ids"].append(c)
    _RASTER.update({"grow": grow, "x0": x0, "y0": y0, "k": k, "wall": mask > 0, "slices": slices, "sep": sep})
    return polys, mpp


def _faces(page, walls, blocks):
    """{block index: (polygon pt list, split?)} from the free space between the walls."""
    try:
        from shapely.geometry import Point, Polygon
        from shapely.ops import unary_union
    except ImportError:
        return {}
    wp = []
    for w in walls or []:
        pts = w.get("polygon") or []
        if len(pts) >= 3:
            g = Polygon(pts, [h for h in (w.get("holes") or []) if len(h) >= 3])
            if not g.is_valid:
                g = g.buffer(0)
            if not g.is_empty and g.area > 0:
                wp.append(g)
    if len(wp) < 3:
        return {}
    mpp = prelim_m_per_pt(page, walls)
    eps = max(0.05, 0.01 / mpp)            # 1 cm: fuse touching wall pieces
    r = 0.6 / mpp                          # half of a 1.2 m door gap
    th = sorted(w.get("thickness_pt") for w in walls if w.get("thickness_pt"))
    ratio0, _ = _ratio(page)
    if th:  # a too-large scale guess must not swallow small rooms: a door is at most ~6 wall thicknesses
        cap = 3.0 * th[len(th) // 2]
        # trust a printed 1:N unless the walls say it is >2.5x off (a detail scale elsewhere on the sheet)
        r = min(r, cap) if not ratio0 or cap < r / 2.5 else r
    R = 1.6 / mpp                          # closing radius for the outline (window runs, notches)
    wu = unary_union([g.buffer(eps, join_style=2) for g in wp]).buffer(-eps, join_style=2)
    if wu.is_empty:
        return {}
    # outline: convex hull of each wall cluster (robust to big window runs and missing exterior wall pieces);
    # regions that leak into a concave notch fail the printed-area check below and stay label-only
    footprint = unary_union([p.convex_hull for p in _poly_list(wu.buffer(R, join_style=2, quad_segs=4))]).buffer(
        -R, join_style=2, mitre_limit=2.0)
    free = footprint.difference(wu)
    bridges = _door_bridges(wp, 2 * r, eps)
    cut = free.difference(unary_union(bridges)) if bridges else free
    faces = [f for f in _poly_list(cut) if f.area > (0.3 / mpp) ** 2]
    # labels -> faces
    owner = {}
    for i, b in enumerate(blocks):
        pt = Point(*b["xy"])
        hit = [k for k, f in enumerate(faces) if f.covers(pt)]
        if not hit:
            near = [(f.distance(pt), k) for k, f in enumerate(faces)]
            near = [x for x in near if x[0] < 0.5 / mpp]
            if near:
                hit = [min(near)[1]]
        if hit:
            owner.setdefault(min(hit, key=lambda k: faces[k].area), []).append(i)
    # the ratio-based scale (if any) lets a face be checked against its printed area
    ratio, _ = _ratio(page)
    sure = PT_M * ratio if ratio else _scalebar(page)
    res = {}
    taken = None
    for k in sorted(owner, key=lambda k: faces[k].area):
        g = faces[k]
        if g is None:
            continue
        if taken is not None:
            ov = g.intersection(taken).area
            if ov > 0.10 * g.area:   # overlaps rooms already placed by more than 10%: not a clean face
                continue
            g = max(_poly_list(g.difference(taken)), key=lambda x: x.area, default=g)
        if g.intersection(wu).area > 0.02 * g.area:   # cuts across walls
            continue
        idx = owner[k]
        a_m2 = g.area * sure * sure if sure else None
        pr = [i for i in idx if blocks[i]["area_printed_m2"]]
        if len(idx) > 1:
            # a unit/apartment tag inside a room (its area ~ the sum of the rooms) is not this face's label
            tot = sum(blocks[i]["area_printed_m2"] for i in pr)
            big = [i for i in pr if (a_m2 and blocks[i]["area_printed_m2"] > 1.6 * a_m2)
                   or (len(pr) >= 3 and blocks[i]["area_printed_m2"] >= 0.45 * tot)
                   or _is_unit_tag(blocks[i])]
            idx = [i for i in idx if i not in big]
            pr = [i for i in pr if i not in big]
        pick = None
        if len(idx) == 1:
            pick = idx[0]
        elif pr and a_m2:   # several labels in one face (open plan, missed wall): the one whose printed area fits
            best = min(pr, key=lambda i: abs(blocks[i]["area_printed_m2"] / a_m2 - 1))
            if abs(blocks[best]["area_printed_m2"] / a_m2 - 1) < 0.15:
                pick = best
        if pick is None:
            continue   # labels stay label-only rooms (printed area, no polygon) rather than a guessed shape
        taken = g if taken is None else taken.union(g)
        res[pick] = g
    # a face whose printed area disagrees with the others' (or with the printed 1:N) leaked or was cut: label-only
    ks = {i: blocks[i]["area_printed_m2"] / g.area for i, g in res.items() if blocks[i]["area_printed_m2"]}
    k0 = median(ks.values()) if len(ks) >= 3 else (sure * sure if sure else None)
    out = {}
    for i, g in res.items():
        if k0 and i in ks and not (1 / 1.6 <= ks[i] / k0 <= 1.6):
            continue
        out[i] = (_coords(g), False)
    return out



def _axis(g):
    """Unit vector of the long side of a polygon's minimum rotated rectangle, and its elongation."""
    mr = g.minimum_rotated_rectangle
    if mr.geom_type != "Polygon":
        return None, 1.0
    c = list(mr.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    if min(l1, l2) <= 0:
        return None, 1.0
    e, L = (e1, l1) if l1 >= l2 else (e2, l2)
    return (e[0] / L, e[1] / L), max(l1, l2) / min(l1, l2)


def _door_bridges(wp, gap_max, eps):
    """Thin closers across door gaps: the shortest link between two wall pieces closer than `gap_max`, kept only
    when it runs along one of the walls (a gap in a wall run), not across a corridor or closet between parallel walls."""
    from shapely.geometry import LineString
    from shapely.ops import nearest_points
    from shapely.strtree import STRtree
    tree = STRtree(wp)
    axes = [_axis(g) for g in wp]
    out = []
    for i, g in enumerate(wp):
        for j in tree.query(g.buffer(gap_max)):
            j = int(j)
            if j <= i:
                continue
            h = wp[j]
            d = g.distance(h)
            if d <= eps or d > gap_max:
                continue
            a, b = nearest_points(g, h)
            v = (b.x - a.x, b.y - a.y)
            L = math.hypot(*v)
            if L <= 0:
                continue
            ok = True
            n_el = 0
            for ax, el in (axes[i], axes[j]):
                if ax and el >= 1.8:
                    n_el += 1
                    if abs(v[0] * ax[0] + v[1] * ax[1]) / L < 0.966:  # must run along each wall it links (15 deg)
                        ok = False
            ok = ok and n_el >= 1
            if ok:
                out.append(LineString([(a.x, a.y), (b.x, b.y)]).buffer(max(eps, 0.25), cap_style=2))
    return out

def _coords(g):
    g = g.simplify(0.05, preserve_topology=True)
    cs = list(g.exterior.coords)[:-1]
    return [[round(x, 3), round(y, 3)] for x, y in cs]
