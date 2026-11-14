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
import re
from statistics import median

PT_M = 25.4 / 72 / 1000  # metres of paper per pt (0.00035278)
FT2_M2 = 0.09290304
FT_M = 0.3048

_NUM = r"(\d{1,3}(?:[ ,']\d{3})+(?:[.,]\d{1,2})?|\d{1,5}(?:[.,]\d{1,3})?)"
_M2 = r"(?:m\s?²|m\s?2|m\^2|㎡|qm|sq\.?\s?m(?:eters?|etres?)?|m\s?\?)"
_FT2 = r"(?:ft\s?²|ft\s?2|sq\.?\s?f(?:ee)?t\.?|s\.?\s?f\.?|sf)"
AREA_RE = re.compile(_NUM + r"\s*(" + _M2 + "|" + _FT2 + r")(?![a-z])", re.I)
ROOM_NO_RE = re.compile(r"^(?:[A-Z]{0,2}[-.]?)?\d{1,4}(?:[.,]\d{1,3})?[A-Z]?$")
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
    A block is a printed area with the name/number above it, or a room-name phrase (with a nearby number)."""
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
                               < 1.8 * p["h"] and abs(_cx(q["bbox"]) - _cx(p["bbox"])) < 1.5 * p["h"] + (p["bbox"][2] - p["bbox"][0]) / 2
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
            if -2.6 * h <= dy <= 3.6 * h and abs(dy) > 0.3 * h:
                t = p["text"]
                d = abs(dy) / h + dx / (4 * h)
                if _room_no(t):
                    nums.append((d, t.replace(" ", ""), pb))
                elif dy > 0 and sum(ch.isalpha() for ch in t) >= 2 and not AREA_RE.search(t) and len(t) <= 40 \
                        and not SKIP_LABEL.search(t.replace("/", " ")):
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
    """A room number ('1.02', 'B324', '201', 'U208'), not a dimension in mm ('2040', '6000')."""
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
    ratio, sheet = scale_text.ratio_and_sheet(page.get("words") or [])
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


def _area_fit(rooms_):
    """Least squares printed_m2 = k * pts_area (k = m_per_pt²), robust to a few mismatched labels."""
    pairs = [(r["pts_area"], r["area_printed_m2"]) for r in rooms_
             if r.get("polygon") and r.get("pts_area") and r.get("area_printed_m2") and not r.get("split")]
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
        if w > 3 and h > 3 and 0.7 < w / h < 1.4:
            rs.append(max(w, h))
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
        return {"m_per_pt": fit["m_per_pt"], "method": "printed areas fit", "confidence": conf,
                "ratio": f"1:{round(fit['m_per_pt'] / PT_M)}", "check": check}
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
    for k, g in enumerate(polys):
        bl = [blocks[i] for i in owner.get(k, [])]
        if not bl and (g.area * mpp * mpp < 2.0 or main is None or not main.contains(g.representative_point())):
            continue   # unlabelled scraps (shafts, wall cavities) or outside the plan
        real = [b for b in bl if not _is_unit_tag(b)]
        if len(real) >= 2 and _RASTER.get("ids"):
            try:   # several labels in one region: split it at its narrowings, one room per label
                parts = _split([b["xy"] for b in real], _RASTER["ids"][k])
                if sum(1 for q in parts if q) == len(real):
                    out += [_room(q, [b]) for q, b in zip(parts, real)]
                    continue
            except Exception:  # noqa: BLE001 - keep the merged room
                pass
        out.append(_room(_coords(g), bl))
    out += [_room(None, [blocks[i]]) for i in lone]
    return out


def _room(poly, bl):
    """One room dict; several labels in one region are kept together (not split). Unit/apartment tags
    (TYPE B / U212 / Whg. A, or an area covering the others) are dropped when real room labels share the region."""
    if len(bl) > 1:
        pr = [b["area_printed_m2"] for b in bl if b["area_printed_m2"]]
        keep = [b for b in bl if not _is_unit_tag(b) and not (len(pr) >= 3 and b["area_printed_m2"]
                                                              and b["area_printed_m2"] >= 0.45 * sum(pr))]
        bl = keep or bl
    lab = " / ".join(b["label"] for b in bl if b["label"]) or None
    num = " / ".join(b["number"] for b in bl if b["number"]) or None
    pr = [b["area_printed_m2"] for b in bl]
    ap = round(sum(pr), 3) if pr and all(v is not None for v in pr) else None
    b0 = bl[0] if bl else None
    if b0:
        bb = [min(b["bbox"][0] for b in bl), min(b["bbox"][1] for b in bl), max(b["bbox"][2] for b in bl),
              max(b["bbox"][3] for b in bl)]
    return {"polygon": poly, "label": lab, "number": num, "area_printed_m2": ap,
            "label_bbox": [round(v, 3) for v in bb] if b0 else None,
            "label_xy": [round(v, 3) for v in b0["xy"]] if b0 else None,
            "labels": [{"label": b["label"], "number": b["number"], "area_printed_m2": b["area_printed_m2"]} for b in bl],
            "pts_area": round(shoelace(poly), 3) if poly else None, "split": False, "merged": len(bl) > 1}



def _partitions(page, mask, x0, y0, k, mpp, reach_m=0.15, min_m=0.8, max_m=12.0):
    """Glass partitions and light walls drawn as thin solid lines: straight 2-point strokes 0.8-12 m long whose
    both ends touch a wall (within 15 cm) are drawn into the wall mask as room separators."""
    import numpy as np
    import cv2
    segs = []
    for p in page.get("paths") or []:
        pts = p.get("pts") or []
        if len(pts) != 2 or p.get("closed") or p.get("dashed") or p.get("stroke") is None or p.get("fill") is not None:
            continue
        (ax, ay), (bx, by) = pts
        L = math.hypot(bx - ax, by - ay) * mpp
        if min_m <= L <= max_m:
            segs.append((ax, ay, bx, by))
    if not segs:
        return 0
    S = np.array(segs, float)
    A = np.round((S[:, :2] - [x0, y0]) * k).astype(int)
    B = np.round((S[:, 2:] - [x0, y0]) * k).astype(int)
    Hp, Wp = mask.shape
    ok = (A[:, 0] >= 0) & (A[:, 0] < Wp) & (A[:, 1] >= 0) & (A[:, 1] < Hp) & \
         (B[:, 0] >= 0) & (B[:, 0] < Wp) & (B[:, 1] >= 0) & (B[:, 1] < Hp)
    if not ok.any():
        return 0
    dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
    reach = reach_m / mpp * k
    A, B = A[ok], B[ok]
    hit = (dist[A[:, 1], A[:, 0]] <= reach) & (dist[B[:, 1], B[:, 0]] <= reach)
    # and the line itself runs through free space (not along / inside a wall)
    n = 0
    for (ax, ay), (bx, by) in zip(A[hit], B[hit]):
        mx, my = (ax + bx) // 2, (ay + by) // 2
        if dist[my, mx] <= reach:
            continue
        cv2.line(mask, (int(ax), int(ay)), (int(bx), int(by)), 255, 2)
        n += 1
    return n

_RASTER: dict = {}


def _split(bl_pts, cid):
    """Split one raster region between several labels at its narrowings (door gaps, corridor necks):
    watershed of the distance-to-wall map seeded at the label points. Returns [polygon pt list | None]."""
    import numpy as np
    import cv2
    from scipy import ndimage
    from shapely.geometry import Polygon
    R_ = _RASTER
    grow, x0, y0, k = R_["grow"], R_["x0"], R_["y0"], R_["k"]
    sl = ndimage.find_objects((grow == cid).astype(np.int32))[0]
    reg = grow[sl] == cid
    pad = 2
    reg = np.pad(reg, pad)
    oy, ox = sl[0].start - pad, sl[1].start - pad
    dist = cv2.distanceTransform(reg.astype(np.uint8), cv2.DIST_L2, 5)
    img = (255 - np.clip(dist / max(1e-6, dist.max()) * 255, 0, 255)).astype(np.uint8)
    img = cv2.merge([img, img, img])
    mk = np.zeros(reg.shape, np.int32)
    mk[~reg] = len(bl_pts) + 1
    for i, (x, y) in enumerate(bl_pts):
        px, py = int(round((x - x0) * k)) - ox, int(round((y - y0) * k)) - oy
        if 0 <= py < reg.shape[0] and 0 <= px < reg.shape[1] and reg[py, px]:
            mk[max(0, py - 1):py + 2, max(0, px - 1):px + 2] = i + 1
    cv2.watershed(img, mk)
    out = []
    for i in range(len(bl_pts)):
        m = ((mk == i + 1) & reg).astype(np.uint8)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs or m.sum() < 4:
            out.append(None)
            continue
        cnt = cv2.approxPolyDP(max(cs, key=cv2.contourArea), 1.0, True)[:, 0, :]
        if len(cnt) < 3:
            out.append(None)
            continue
        g = Polygon([((x + ox) / k + x0, (y + oy) / k + y0) for x, y in cnt]).buffer(0)
        g = max(_poly_list(g.buffer(0.5 / k, join_style=2)), key=lambda q: q.area, default=None)
        out.append(_coords(g) if g is not None else None)
    return out


def _components(page, walls, res_m=0.025, close_m=0.6, ext_m=1.5):
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
    _partitions(page, mask, x0, y0, k, mpp)
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
    min_px = (0.3 / mpp * k) ** 2
    polys = []
    _RASTER.clear()
    _RASTER["ids"] = []
    from scipy import ndimage
    for c0, sl in enumerate(ndimage.find_objects(grow)):
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
    _RASTER.update({"grow": grow, "x0": x0, "y0": y0, "k": k, "wall": mask > 0})
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
