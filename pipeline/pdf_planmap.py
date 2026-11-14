"""Vector (CAD-exported) PDF floor plan -> plan map, no model calls.

Reads the page's drawing operators with pdfminer.six (points, exact: 1 pt = 25.4/72 mm), takes the wall shapes
(dark or hatch filled closed paths), turns the free space between them into rooms (door gaps closed, regions
that carry a text-layer label), and fits the scale from the printed 1:N, checked against printed room areas.
`process` returns None when the page is not a plan this reader understands, so the caller falls back to the VLM.

Pixel space = the rendered page-<n>.png: px = x_pt * s, (H_pt - y_pt) * s with s = W_px / W_pt.
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


def process(doc_id: str, ddir: Path, pdf_path: Path, page_index: int = 0, write: bool = True):
    """Plan map dict for a vector plan page, or None. Writes planmap-<n>.json when `write`."""
    from engine import scale_text
    n = page_index + 1
    meta = json.loads((ddir / "pages.json").read_text())
    pinfo = next(p for p in meta["pages"] if p["page"] == n)
    W, H = pinfo["w"], pinfo["h"]
    tf = ddir / f"text-{n}.json"
    if not tf.is_file():
        return None
    tj = json.loads(tf.read_text())
    words = tj["words"]
    if NOT_PLAN.search(" ".join(w["text"] for w in words[:400])) and sum(
            1 for w in words if UNIT.match(w["text"])) < 3:
        return None
    W_pt, H_pt, shapes = extract_shapes(pdf_path, page_index)
    if len(shapes) < 20:
        return None
    s = W / W_pt
    labels = label_blocks(words)
    if len(labels) < MIN_ROOMS:
        return None
    walls, thin = _wall_polys(shapes, s, H_pt)
    if len(walls) < MIN_WALL_SHAPES:
        return None
    # keep wall shapes in the neighbourhood of the labelled rooms (drops title blocks, scale bars, legends)
    xs = [b["cx"] for b in labels]; ys = [b["cy"] for b in labels]
    pad = 0.06 * max(W, H)
    box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    walls = [p for p in walls if box[0] <= sum(q[0] for q in p) / len(p) <= box[2]
             and box[1] <= sum(q[1] for q in p) / len(p) <= box[3]]
    if len(walls) < MIN_WALL_SHAPES:
        return None
    # scale: printed ratio (exact in points), then the printed room areas as a check/fallback
    ratio, sheet = scale_text.ratio_and_sheet(words)
    dpi = 72 * s
    sc = None
    if ratio:
        mpp = 25.4 / dpi * ratio / 1000
        sc = {"m_per_px": mpp, "method": "pdf-points-ratio", "confidence": 0.95,
              "evidence": f"printed scale 1:{ratio}; PDF points are exact (1 pt = 25.4/72 mm) at {dpi:.0f} dpi"}
    guess = sc["m_per_px"] if sc else 0.034
    rooms = _rooms_from_walls(walls, thin, labels, W, H, guess)
    if len(rooms) < MIN_ROOMS:
        return None
    ratios = []
    for i, poly in rooms:
        a_px = _poly_area([tuple(q) for q in poly])
        if a_px > 0 and labels[i]["area_m2"] > 0:
            ratios.append((labels[i]["area_m2"] / a_px) ** 0.5)
    fit = float(np.median(ratios)) if len(ratios) >= 2 else None
    if sc is None:
        if fit is None:
            return None
        sc = {"m_per_px": fit, "method": "printed-areas-fit", "confidence": 0.6,
              "evidence": f"fitted to {len(ratios)} printed room areas (no printed scale ratio)"}
    elif fit and abs(fit / sc["m_per_px"] - 1) > 0.25:
        sc = {"m_per_px": fit, "method": "printed-areas-fit", "confidence": 0.5,
              "evidence": f"printed 1:{ratio} disagrees with the printed room areas by {abs(fit / sc['m_per_px'] - 1) * 100:.0f}%: areas used"}
    mpp = sc["m_per_px"]

    def box_of(poly):
        a = [q[0] for q in poly]; b = [q[1] for q in poly]
        return [min(a), min(b), max(a), max(b)]

    items, cnt = [], Counter()

    def add(kind, label, poly, props, conf=0.9):
        cnt[kind] += 1
        items.append({"item_id": f"{kind}-{cnt[kind]}", "kind": kind, "label": label, "bbox_px": box_of(poly),
                      "polygon_px": poly, "props": props, "conf": conf, "source": "pdf-vector"})

    for i, poly in rooms:
        b = labels[i]
        a_geom = round(_poly_area([tuple(q) for q in poly]) * mpp ** 2, 2)
        add("room", b["name"], poly, {"number": b["number"], "area_m2_label": b["area_m2"],
                                       "area_m2_geom": a_geom, "labelled": bool(b["name"])}, 0.85)
    for p in walls:
        add("wall", "", [[round(x, 1), round(y, 1)] for x, y in p], {}, 0.85)
    for b in labels:
        cnt["text"] += 1
        bb = b["bbox"]
        items.append({"item_id": f"text-{cnt['text']}", "kind": "text", "label": b["name"] or b["number"],
                      "bbox_px": bb, "polygon_px": None, "props": {}, "conf": 0.9, "source": "pdf-vector"})
    pm = {"doc_id": doc_id, "page": n, "image": {"w": W, "h": H}, "scale": sc, "items": items,
          "provenance": {"models": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "ms": 0,
                         "note": "from PDF vector geometry (pdfminer.six); generated for demo"}}
    if write:
        (ddir / f"planmap-{n}.json").write_text(json.dumps(pm))
    return pm


if __name__ == "__main__":
    import sys
    r = process(Path(sys.argv[2]).name, Path(sys.argv[2]), Path(sys.argv[1]), int(sys.argv[3]) - 1 if len(sys.argv) > 3 else 0)
    print(None if r is None else dict(Counter(i["kind"] for i in r["items"])), None if r is None else r["scale"])
