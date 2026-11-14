"""Vector (CAD-exported) PDF floor plan -> plan map (CONTRACT 5.4), no model calls.

`process` runs the role modules on one page, all in page points (top-left origin, y down, after /Rotate and CropBox):
pipeline.pdf_vector (load_page, is_scanned, walls), pipeline.pdf_rooms (rooms, scale), pipeline.pdf_openings (gate,
openings). `build` turns their output into plan-map items with the PDF-3D addendum's provenance: q.area_m2 (shoelace on
the pt polygon x m_per_pt^2), q.area_m2_printed, q.length_m (walls), props.measure {from, pts_area, m_per_pt,
scale_source, scale_check}, top-level scale {m_per_px = m_per_pt / s, m_per_pt, method, confidence, ratio}.
Pixels = page-<n>.png: px = pdf_vector.to_px(pt, s), s = W_px / W_pt. Returns None (caller falls back to the VLM) for
scanned pages, gate rejects, no scale, or a page size that does not match the render.
The older draft reader below (extract_shapes, label_blocks, _wall_polys, _rooms_from_walls) is only a fallback for a
role module that still returns its stub result, and only with PDF_PLANMAP_DRAFT=1 (off by default: pdfminer is slow).
CLI: python -m pipeline.pdf_planmap <pdf> <artifact_dir> [page]
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

NUM = re.compile(r"^\d{1,3}[.,]\d{1,3}$")
AREA_NUM = re.compile(r"^\d{1,4}(?:[.,]\d{1,2})?$")
UNIT = re.compile(r"^(?:m²|m2|m\^2|㎡)$", re.I)
UNIT_FUSED = re.compile(r"^(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:m²|m2)$", re.I)
NOT_PLAN = re.compile(r"\b(elevation|section|schedule|ansicht|schnitt|fassade|facade|detail|legend only|door schedule|"
                      r"window schedule|restroom|toilet partition)\b", re.I)
MIN_WALL_SHAPES = 6
MIN_ROOMS = 2


def _grey(c):
    """Colour as 0..1 darkness-friendly grey, or None for a pattern/unknown fill."""
    if isinstance(c, (int, float)):
        return float(c)
    if isinstance(c, (tuple, list)) and c and all(isinstance(v, (int, float)) for v in c):
        if len(c) == 1:
            return float(c[0])
        if len(c) == 3:
            return sum(c) / 3
        if len(c) == 4:  # cmyk
            k = c[3]
            return (1 - k) * (1 - sum(c[:3]) / 3)
    return None


def _is_wall_fill(c) -> bool:
    if c is None:
        return False
    g = _grey(c)
    if g is None:
        return True  # pattern fill (hatch): the way CAD exports cut walls
    return g < 0.35


def _poly_area(p):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def extract_shapes(pdf_path: Path, page_index: int = 0):
    """Return (width_pt, height_pt, shapes) with shapes = [{pts, lw, stroke, fill, fill_color, stroke_color}]."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTCurve, LTFigure, LTLine, LTRect
    pg = next(extract_pages(str(pdf_path), page_numbers=[page_index]))
    shapes = []

    def walk(objs):
        for o in objs:
            if isinstance(o, (LTLine, LTRect, LTCurve)):
                shapes.append({"pts": [(float(x), float(y)) for x, y in o.pts], "lw": float(o.linewidth or 0),
                               "stroke": bool(o.stroke), "fill": bool(o.fill),
                               "fill_color": o.non_stroking_color, "stroke_color": o.stroking_color})
            elif isinstance(o, LTFigure):
                walk(o)
    walk(pg)
    return pg.width, pg.height, shapes


def label_blocks(words, line_h=None):
    """Room labels from the text layer: one block per printed area ('15.61 m²'), name and number above it.
    Returns [{name, number, area_m2, cx, cy, bbox}] in pixel space."""
    ws = [w for w in words if w.get("bbox_px")]
    if not ws:
        return []
    hs = sorted(w["bbox_px"][3] - w["bbox_px"][1] for w in ws)
    lh = line_h or max(4.0, hs[len(hs) // 2])
    anchors = []
    for i, w in enumerate(ws):
        t = w["text"].strip()
        m = UNIT_FUSED.match(t)
        if m:
            anchors.append((i, float(m.group(1).replace(",", ".")), w["bbox_px"]))
            continue
        if UNIT.match(t):
            b = w["bbox_px"]
            prev = [(j, v) for j, v in enumerate(ws) if j != i and AREA_NUM.match(v["text"].strip())
                    and abs((v["bbox_px"][1] + v["bbox_px"][3]) / 2 - (b[1] + b[3]) / 2) < 0.6 * lh
                    and 0 <= b[0] - v["bbox_px"][2] < 1.5 * lh]
            if prev:
                j, v = max(prev, key=lambda jv: jv[1]["bbox_px"][2])
                bb = [min(v["bbox_px"][0], b[0]), b[1], b[2], b[3]]
                anchors.append((i, float(v["text"].strip().replace(",", ".")), bb))
    anchor_ids = {i for i, _, _ in anchors}
    block_of = {k: [] for k in range(len(anchors))}
    for j, w in enumerate(ws):
        if j in anchor_ids:
            continue
        b = w["bbox_px"]
        wc, wb = (b[0] + b[2]) / 2, b[3]
        best, bd = None, 1e9
        for k, (_, _, bb) in enumerate(anchors):
            h = max(4.0, bb[3] - bb[1])
            gap = bb[1] + 0.3 * h - wb
            dx = abs(wc - (bb[0] + bb[2]) / 2)
            if gap < -0.0 or gap > 3.6 * h or dx > 4.5 * h + (b[2] - b[0]) / 2 + 1.5 * h:
                continue
            d = dx / h + 2 * gap / h
            if d < bd:
                best, bd = k, d
        if best is not None:
            block_of[best].append(w)
    blocks = []
    for k, (i, area, bb) in enumerate(anchors):
        block = block_of[k]
        lh_k = max(4.0, bb[3] - bb[1])
        name_words, number = [], ""
        for w in sorted(block, key=lambda w: (w["bbox_px"][1], w["bbox_px"][0])):
            t = w["text"].strip()
            if NUM.match(t):
                number = number or t
            elif any(ch.isalpha() for ch in t) and not t.startswith("Whg") and not UNIT.match(t):
                name_words.append(w)
        name = ""
        if name_words:  # the text line nearest above the number/area (drops unit tags such as 'Whg. A')
            rows = {}
            for w in name_words:
                rows.setdefault(round((w["bbox_px"][1] + w["bbox_px"][3]) / 2 / lh_k), []).append(w)
            ref = next((w["bbox_px"] for w in block if w["text"].strip() == number), bb) if number else bb
            cand = [r for r in rows if (ref[1] + ref[3]) / 2 / lh_k - r > 0.5] or list(rows)
            name = " ".join(w["text"] for w in sorted(rows[max(cand)], key=lambda w: w["bbox_px"][0]))
        allb = [w["bbox_px"] for w in block if w["text"].strip() in ([number] if number else [])
                or w in name_words] + [bb]
        cy = (min(b[1] for b in allb) + bb[3]) / 2
        blocks.append({"name": name, "number": number, "area_m2": area, "cx": (bb[0] + bb[2]) / 2,
                       "cy": cy, "bbox": [min(b[0] for b in allb), min(b[1] for b in allb),
                                          max(b[2] for b in allb), bb[3]]})
    return blocks


def _wall_polys(shapes, s, H_pt):
    """Wall shapes in pixel space: closed paths with a dark/pattern fill and some size."""
    out, thin = [], []
    for sh in shapes:
        pts = sh["pts"]
        if len(pts) < 4:
            continue
        px = [(x * s, (H_pt - y) * s) for x, y in pts]
        if sh["fill"] and _is_wall_fill(sh["fill_color"]):
            if _poly_area(px) >= 4.0:
                out.append(px)
        elif sh["stroke"] and math.dist(px[0], px[-1]) < 1.0 and _poly_area(px) > 0.5:
            thin.append(px)  # closed outline (window, door leaf, jamb): a barrier if it is thin
    return out, thin


def _rooms_from_walls(walls, thin, labels, W, H, mpp_guess):
    """Label free-space regions of the wall mask; return [(label_index, polygon_px)]."""
    import cv2
    f = 0.5  # work at half resolution
    w2, h2 = int(W * f), int(H * f)
    mask = np.zeros((h2, w2), np.uint8)
    for p in walls:
        cv2.fillPoly(mask, [np.round(np.array(p) * f).astype(np.int32)], 255)
    for p in thin:
        (_, _), (rw_, rh_), _ = cv2.minAreaRect(np.round(np.array(p)).astype(np.float32))
        if min(rw_, rh_) * mpp_guess < 0.4 and max(rw_, rh_) * mpp_guess < 3.0:
            cv2.fillPoly(mask, [np.round(np.array(p) * f).astype(np.int32)], 255)
    r = max(2, int(round(0.55 / mpp_guess * f)))  # half a door width (door width ~1.1 m worst case)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    closed = cv2.dilate(mask, k)
    free = (closed == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(free, connectivity=4)
    seeds = np.zeros((h2, w2), np.int32)
    taken = {}
    for i, b in enumerate(labels):
        x, y = int(b["cx"] * f), int(b["cy"] * f)
        if not (0 <= x < w2 and 0 <= y < h2):
            continue
        c = lab[y, x]
        if c == 0:  # label sits on a wall/hatch: nearest free pixel in a small window
            win = lab[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
            vals = win[win > 0]
            if not vals.size:
                continue
            c = Counter(vals.tolist()).most_common(1)[0][0]
        taken.setdefault(int(c), []).append(i)
    # a component with two labels is a merged region (open plan or a missed wall): keep it for the first label only
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    out = []
    grow = np.zeros((h2, w2), np.int32)
    for c, idxs in taken.items():
        if c in border or len(idxs) != 1:
            continue
        grow[lab == c] = idxs[0] + 1
    # grow each region back into the open space the closing took (inverse of the dilation)
    free_orig = (mask == 0)
    kk = np.ones((3, 3), np.uint8)
    for _ in range(r + 1):
        d = cv2.dilate(grow.astype(np.float32), kk).astype(np.int32)
        # only fill unlabelled free pixels; max() picks a neighbour label, ties are rare and harmless
        upd = (grow == 0) & free_orig & (d > 0)
        if not upd.any():
            break
        grow[upd] = d[upd]
    for i in sorted({int(v) for v in np.unique(grow) if v > 0}):
        m = (grow == i).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            continue
        c = max(cs, key=cv2.contourArea)
        eps = 1.2
        c = cv2.approxPolyDP(c, eps, True)[:, 0, :] / f
        if len(c) >= 3:
            out.append((i - 1, [[round(float(x), 1), round(float(y), 1)] for x, y in c]))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Draft fallback in the shared interface (page points, top-left origin, y down). Used only where a role module
# still returns its stub result (no walls / no rooms / no scale / gate "stub"), so the path runs end to end.
# Off by default; PDF_PLANMAP_DRAFT=1 turns it on.
# ---------------------------------------------------------------------------------------------------------------
M_PER_PT_1 = 25.4 / 72 / 1000  # metres per pt at 1:1


def _draft_page(pdf_path: Path, page_index: int) -> dict:
    """Minimal load_page: size and words in pt (y down). Shapes are read lazily by _draft_walls."""
    import pypdfium2 as pdfium
    d = pdfium.PdfDocument(str(pdf_path))
    try:
        W_pt, H_pt = d[page_index].get_size()
    finally:
        d.close()
    return {"W_pt": float(W_pt), "H_pt": float(H_pt), "rotate": 0, "paths": [], "words": [], "image_cover": 0.0,
            "_draft": {"pdf": str(pdf_path), "index": page_index}}


def _draft_shapes(page: dict):
    dr = page.setdefault("_draft", {})
    if "shapes" not in dr:
        _, H_pt, shapes = extract_shapes(Path(dr["pdf"]), dr["index"])
        dr["shapes"], dr["H_mb"] = shapes, H_pt
    return dr["shapes"], dr["H_mb"]


def _draft_walls(page: dict) -> list:
    shapes, H_mb = _draft_shapes(page)
    walls, thin = _wall_polys(shapes, 1.0, H_mb)  # s = 1: page points, y down
    page["_draft"]["thin"] = thin
    out = []
    for p in walls:
        a = _poly_area(list(p))
        per = sum(math.dist(p[i], p[(i + 1) % len(p)]) for i in range(len(p)))
        t = 2 * a / per if per else 0.0  # thickness of a long thin shape
        out.append({"polygon": [[x, y] for x, y in p], "thickness_pt": t, "style": "fill"})
    return out


def _draft_rooms(page: dict, walls: list, words_pt: list, s: float, W: int, H: int) -> list:
    """Draft room finder (raster flood fill between walls) run in page pixels, returned in pt."""
    labels = label_blocks([{"text": w["text"], "bbox_px": [v * s for v in w["bbox"]]} for w in words_pt])
    if len(labels) < MIN_ROOMS:
        return []
    from engine import scale_text
    ratio, _ = scale_text.ratio_and_sheet([{"text": w["text"]} for w in words_pt])
    guess = (M_PER_PT_1 * ratio / s) if ratio else 0.034
    wpx = [[(x * s, y * s) for x, y in w["polygon"]] for w in walls]
    thin = [[(x * s, y * s) for x, y in p] for p in page.get("_draft", {}).get("thin", [])]
    got = dict(_rooms_from_walls(wpx, thin, labels, W, H, guess))
    out = []
    for i, b in enumerate(labels):
        poly = [[x / s, y / s] for x, y in got[i]] if i in got else None
        out.append({"polygon": poly, "label": b["name"] or None, "number": b["number"] or None,
                    "area_printed_m2": b["area_m2"], "label_bbox": [v / s for v in b["bbox"]],
                    "pts_area": _poly_area([tuple(q) for q in poly]) if poly else None})
    return out


def _draft_scale(page: dict, rooms_: list, words_pt: list) -> dict:
    """Ladder rungs 1 and 3: printed 1:N, checked against (or replaced by) a fit to the printed room areas."""
    from engine import scale_text
    ratio, _ = scale_text.ratio_and_sheet([{"text": w["text"]} for w in words_pt])
    pairs = [(r["pts_area"], r["area_printed_m2"]) for r in rooms_ if r.get("pts_area") and r.get("area_printed_m2")]
    fit = None
    if len(pairs) >= 2:  # least squares of printed m² = k² * pt²  ->  k² = sum(a*m)/sum(a*a)
        k2 = sum(a * m for a, m in pairs) / sum(a * a for a, _ in pairs)
        fit = math.sqrt(k2) if k2 > 0 else None
    check = {}
    if ratio:
        mpt = M_PER_PT_1 * ratio
        if fit:
            check["printed_areas_rel_err"] = round(abs(fit ** 2 / mpt ** 2 - 1), 4)
        if fit and check["printed_areas_rel_err"] > 0.25:  # the printed ratio is for another view on the sheet
            return {"m_per_pt": fit, "method": "printed_areas_fit", "confidence": 0.6, "ratio": f"1:{ratio}", "check": check}
        return {"m_per_pt": mpt, "method": "printed_ratio", "confidence": 0.95 if not fit or check["printed_areas_rel_err"] < 0.05 else 0.8,
                "ratio": f"1:{ratio}", "check": check}
    if fit:
        return {"m_per_pt": fit, "method": "printed_areas_fit", "confidence": 0.6, "ratio": None, "check": check}
    return {"m_per_pt": None, "method": None, "confidence": 0.0, "ratio": None, "check": {}}


def _draft_gate(page: dict, walls: list, rooms_: list, words_pt: list) -> tuple[bool, str]:
    txt = " ".join(w["text"] for w in words_pt[:400])
    if NOT_PLAN.search(txt) and sum(1 for w in words_pt if UNIT.match(w["text"]) or UNIT_FUSED.match(w["text"])) < 3:
        return False, "heading says elevation/section/schedule/detail"
    if len(walls) < MIN_WALL_SHAPES:
        return False, f"{len(walls)} wall shapes < {MIN_WALL_SHAPES}"
    if sum(1 for r in rooms_ if r.get("polygon") or r.get("area_printed_m2")) < MIN_ROOMS:
        return False, "fewer than 2 rooms"
    return True, "draft gate"


# ---------------------------------------------------------------------------------------------------------------
# Assembly: role modules -> plan map (CONTRACT 5.4 + the PDF-3D addendum's provenance keys)
# ---------------------------------------------------------------------------------------------------------------
ROOM_TYPE_WORDS = [  # keyword (lowercase, substring) -> props.room_type (extrude tints by it)
    (("bagno", "bad", "bath", "salle de bain", "douche", "dusche", "shower"), "bathroom"),
    (("wc", "toilet", "toilette", "abort", "restroom", "lavatory"), "wc"),
    (("cucina", "küche", "kueche", "kitchen", "cuisine", "kochen"), "kitchen"),
    (("camera", "schlaf", "bed", "chambre", "zimmer", "kinder"), "bedroom"),
    (("soggiorno", "wohn", "living", "salon", "séjour", "sejour", "lounge", "family"), "living"),
    (("corridoio", "disimpegno", "ingresso", "flur", "gang", "korridor", "hall", "corridor", "entr", "foyer", "diele"), "hall"),
    (("balcon", "balkon", "terrazz", "terrasse", "terrace", "loggia", "deck", "patio"), "balcony"),
    (("ripostiglio", "abstell", "keller", "storage", "réduit", "reduit", "closet", "cellar", "pantry"), "storage"),
    (("lavanderia", "wasch", "laundry", "buanderie"), "laundry"),
    (("scala", "treppe", "stair", "escalier"), "stairs"),
    (("ufficio", "büro", "buero", "office", "bureau", "study"), "office"),
    (("pranzo", "dining", "essen", "repas"), "dining"),
]


MIN_WALL_LEN_M = 0.3     # wall pieces shorter than this (at the page scale) are dropped before extrusion
MIN_WALL_THICK_M = 0.05  # ... and thinner than 50 mm


def room_type(label: str | None) -> str:
    s = (label or "").lower()
    for keys, t in ROOM_TYPE_WORDS:
        if any(k in s for k in keys):
            return t
    return "other"


SCALE_SOURCE = (("ratio", "printed 1:{n}"), ("printed 1:", "printed 1:{n}"), ("bar", "scale bar"),
                ("area", "printed areas fit"), ("dim", "dimensions"), ("door", "door guess"))


def scale_source(method: str | None, ratio) -> str:
    m = (method or "").lower()
    n = str(ratio or "").split(":")[-1]
    for key, text in SCALE_SOURCE:
        if key in m:
            return text.format(n=n)
    return m or "unknown"


def _ratio_str(r):
    if r in (None, ""):
        return None
    r = str(r)
    return r if ":" in r else f"1:{r}"


def shoelace(poly) -> float:
    return _poly_area([tuple(q[:2]) for q in poly]) if poly and len(poly) >= 3 else 0.0


def _perimeter(poly) -> float:
    return sum(math.dist(poly[i][:2], poly[(i + 1) % len(poly)][:2]) for i in range(len(poly))) if poly else 0.0


def rect_equivalent(area: float, perimeter: float) -> tuple[float, float]:
    """(long side, short side) of the rectangle with this area and perimeter: wall length and thickness from the exact
    pt polygon (L + t = P/2, L*t = A). Shapes that no rectangle matches give (P/4, A/(P/4))."""
    h = perimeter / 2
    d = h * h - 4 * area
    L = (h + math.sqrt(d)) / 2 if d >= 0 else h / 2
    return L, (area / L if L > 0 else 0.0)


def _bbox(poly):
    xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def _rect(b):
    return [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]


def _image_size(ddir: Path, n: int) -> tuple[int, int]:
    f = ddir / "pages.json"
    if f.is_file():
        for p in json.loads(f.read_text()).get("pages", []):
            if p["page"] == n:
                return int(p["w"]), int(p["h"])
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(ddir / f"page-{n}.png") as im:
        return im.size


def _words_pt(ddir: Path, n: int, s: float, page: dict) -> list:
    """Words in pt (y down): the vector reader's own text if it gave any, else text-<n>.json (page pixels / s)."""
    if page.get("words"):
        return page["words"]
    f = ddir / f"text-{n}.json"
    if not f.is_file():
        return []
    return [{"text": w["text"], "bbox": [v / s for v in w["bbox_px"]]} for w in json.loads(f.read_text())["words"]]


def _draft_on() -> bool:
    import os
    return os.environ.get("PDF_PLANMAP_DRAFT", "0") == "1"


def build(doc_id: str, n: int, W: int, H: int, page: dict, walls: list, rooms_: list, opens: list, sc: dict,
          words_pt: list | None = None, used: dict | None = None, ms: int = 0) -> dict:
    """Plan map dict from the role modules' outputs (all geometry in page pt, top-left, y down)."""
    from pipeline import pdf_vector
    s = W / page["W_pt"]
    px = lambda p: [round(float(v), 1) for v in pdf_vector.to_px(p, s)]
    mpt = float(sc["m_per_pt"])
    ratio = _ratio_str(sc.get("ratio"))
    src = scale_source(sc.get("method"), ratio)
    check = dict(sc.get("check") or {})
    measure = lambda **kw: {"from": "pdf_vector", "m_per_pt": mpt, "scale_source": src, "scale_check": check, **kw}
    items, cnt = [], Counter()

    def add(kind, label, poly_px, bbox_px, props, conf, q=None):
        cnt[kind] += 1
        it = {"item_id": f"{kind}-{cnt[kind]:03d}", "kind": kind, "label": label,
              "bbox_px": [round(float(v), 1) for v in bbox_px], "polygon_px": poly_px, "props": props,
              "conf": round(float(conf), 3), "source": "pdf_vector"}
        if q is not None:
            it["q"] = q
        items.append(it)
        return it

    for r in rooms_:
        poly = r.get("polygon")
        printed = r.get("area_printed_m2")
        label = r.get("label") or None
        if poly and len(poly) >= 3:
            pts_area = float(r.get("pts_area") or shoelace(poly))
            a = round(pts_area * mpt ** 2, 2)
            ppx = [px(p) for p in poly]
            bb = _bbox(ppx)
            frm, conf = "polygon", 0.85
        elif r.get("label_bbox") and printed:  # no polygon: a room at its label, printed area only
            pts_area, a = None, None
            bb = [px(r["label_bbox"][:2])[0], px(r["label_bbox"][:2])[1], *px(r["label_bbox"][2:4])]
            ppx, frm, conf = None, "label", 0.5
        else:
            continue
        m = measure(pts_area=round(pts_area, 2) if pts_area else None, geometry=frm)
        if a and printed:
            m["printed_rel_err"] = round(abs(a / printed - 1), 4)
        props = {"room_type": room_type(label), "number": r.get("number"),
                 "area_m2": printed if printed else a,  # printed label wins (as for DXF), measured kept in area_m2_geom
                 "area_m2_label": printed, "area_m2_geom": a, "labelled": bool(label), "measure": m}
        add("room", label, ppx, bb, props, conf, {"area_m2": a, "area_m2_printed": printed})
    for w in walls:
        poly = w.get("polygon")
        if not poly or len(poly) < 3:
            continue
        pts_area = shoelace(poly)
        t = float(w.get("thickness_pt") or 0)
        length_pt, t_eq = rect_equivalent(pts_area, _perimeter(poly))
        t = t or t_eq
        if length_pt * mpt < MIN_WALL_LEN_M or (t_eq or t) * mpt < MIN_WALL_THICK_M:
            continue  # casework, fixture outlines, dimension ticks: not walls at full height
        ppx = [px(p) for p in poly]
        props = {"thickness_px": round(t * s, 2), "thickness_m": round(t * mpt, 3), "style": w.get("style"),
                 "length_m": round(length_pt * mpt, 3),
                 "measure": measure(pts_area=round(pts_area, 2), length_pt=round(length_pt, 2))}
        add("wall", "", ppx, _bbox(ppx), props, 0.85, {"length_m": round(length_pt * mpt, 3)})
    for o in opens:
        k = o.get("kind")
        if k not in ("door", "window"):
            continue
        poly = o.get("polygon")
        b = o.get("bbox") or (_bbox(poly) if poly else None)
        if not b:
            continue
        bb = [*px(b[:2]), *px(b[2:4])]
        ppx = [px(p) for p in poly] if poly and len(poly) >= 3 else [list(q) for q in _rect(bb)]
        props = dict(o.get("props") or {})
        props.setdefault("width_m", round(max(b[2] - b[0], b[3] - b[1]) * mpt, 3))
        props["measure"] = measure(width_pt=round(max(b[2] - b[0], b[3] - b[1]), 2))
        add(k, o.get("label") or "", ppx, bb, props, o.get("conf") or 0.7, {"width_m": props["width_m"]})
    for r in rooms_:
        lb = r.get("label_bbox")
        if lb and (r.get("label") or r.get("number")):
            add("text", r.get("label") or r.get("number"), None, [*px(lb[:2]), *px(lb[2:4])], {"role": "room_label"}, 0.9)
    scale = {"m_per_px": mpt / s, "m_per_pt": mpt, "method": sc.get("method") or "none",
             "confidence": float(sc.get("confidence") or 0), "ratio": ratio, "source": src, "check": check,
             "evidence": f"{src}: {mpt:.6f} m per pt; page-{n}.png at {s:.4f} px per pt"}
    return {"doc_id": doc_id, "page": n, "image": {"w": int(W), "h": int(H)}, "scale": scale, "items": items,
            "provenance": {"models": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "ms": int(ms),
                           "from": "pdf_vector", "modules": used or {},
                           "page_pt": [page["W_pt"], page["H_pt"]], "px_per_pt": s,
                           "note": "from PDF vector geometry; measurements in exact page points"}}


def process(doc_id: str, ddir: Path, pdf_path: Path, page_index: int = 0, write: bool = True):
    """Plan map dict for a vector plan page, or None (scanned / not a plan / no scale), so the caller falls back.
    Writes planmap-<n>.json when `write`."""
    from pipeline import pdf_openings, pdf_rooms, pdf_vector
    t0 = time.time()
    n = page_index + 1
    ddir, pdf_path = Path(ddir), Path(pdf_path)
    W, H = _image_size(ddir, n)
    draft = _draft_on()
    used = {}
    page = pdf_vector.load_page(pdf_path, page_index)
    if not page.get("W_pt"):
        if not draft:
            return None
        page, used["page"] = _draft_page(pdf_path, page_index), "draft"
    if pdf_vector.is_scanned(page):
        return None
    s = W / page["W_pt"]
    if abs(page["H_pt"] * s - H) > max(2.0, 0.01 * H):  # rotation/crop mismatch: pixel mapping would be wrong
        return None
    words_pt = _words_pt(ddir, n, s, page)
    walls = pdf_vector.walls(page)
    if not walls and draft:
        walls, used["walls"] = _draft_walls(page), "draft"
    rooms_ = pdf_rooms.rooms(page, walls)
    if not rooms_ and draft:
        rooms_, used["rooms"] = _draft_rooms(page, walls, words_pt, s, W, H), "draft"
    ok, reason = pdf_openings.gate(page, walls, rooms_)
    if reason == "stub" and draft:
        (ok, reason), used["gate"] = _draft_gate(page, walls, rooms_, words_pt), "draft"
    if not ok:
        return None
    sc = pdf_rooms.scale(page, rooms_)
    if not sc or not sc.get("m_per_pt"):
        if not draft:
            return None
        sc, used["scale"] = _draft_scale(page, rooms_, words_pt), "draft"
        if not sc.get("m_per_pt"):
            return None
    opens = pdf_openings.openings(page, walls)
    page.pop("_draft", None)
    pm = build(doc_id, n, W, H, page, walls, rooms_, opens, sc, words_pt, used, ms=(time.time() - t0) * 1000)
    if sum(1 for i in pm["items"] if i["kind"] in ("room", "wall")) < 3:
        return None
    pm["provenance"]["gate"] = reason
    if write:
        (ddir / f"planmap-{n}.json").write_text(json.dumps(pm))
    return pm


if __name__ == "__main__":
    import sys
    r = process(Path(sys.argv[2]).name, Path(sys.argv[2]), Path(sys.argv[1]), int(sys.argv[3]) - 1 if len(sys.argv) > 3 else 0)
    print(None if r is None else dict(Counter(i["kind"] for i in r["items"])), None if r is None else r["scale"])
