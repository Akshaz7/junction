"""F-SCANSYM: count the symbols a drawing's own legend explains (sockets, light fittings, detectors, valves, ...) on raster sheets.

    count_symbols(image_path, legend=None, target=None) -> {counts, boxes, legend_used, ...}

How it works (general: no file, label or unit is special-cased):
  1. find_legend   Text with pixel boxes (text layer or OCR) gives label rows. A legend row is a label with a compact ink shape
                   immediately to its left (or right); three or more such rows stacked in one column form a legend block. A heading
                   such as LEGEND / SYMBOLS / SELITE / LEGENDE / MERKINNAT only raises trust, it is not required. Shapes that are long
                   thin lines (pipe and wall types) are listed but not counted.
  2. match_symbol  Free first pass: normalised cross-correlation of the symbol's ink against the sheet's ink, 4 rotations, several
                   scales, non-maximum suppression, then an ink-overlap test. Strong hits count; weak hits are "uncertain".
  3. verify        A vision model (engine.models call "symbols_verify") only answers yes/no for numbered candidate tiles it is shown, so
                   it can confirm or drop a candidate but never adds one. It also re-checks a sample of the strong hits (the "Checked"
                   step). Without a model the uncertain hits are listed as "possible", never counted.
  4. answer_symbols  The chat route: legend question, "how many <legend label>", numbered boxes, citations, evidence card.

Never raises into the answer path; no data means a plain sentence saying so.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path

import cv2
import numpy as np

# ------------------------------------------------------------------------------------------------ tunables (physics-free, relative)
TARGET_PX = 26          # work resolution: the symbol's longest side is shrunk to about this many pixels
SCALES = (0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0, 1.2, 1.45)   # legends are often drawn larger than the symbols on the plan
LOW_NCC, ACCEPT_NCC = 0.50, 0.72
LOW_RECALL, ACCEPT_RECALL = 0.62, 0.80
MAX_PEAKS = 400
MIN_HIT_PX = 14                 # smallest side of a counted hit (about 1.2 mm at 300 dpi)
VERIFY_TILES_PER_CALL = 20
VERIFY_MAX_CALLS = 8            # per question across all symbols (budget cap on top of the model layer's own caps)
VERIFY_SAMPLE_OK = 6            # strong hits re-checked by the model per symbol
MAX_ENTRIES_PER_QUESTION = 8
MAX_PAGES = 6
LEGEND_KEYS = {"legend", "legends", "symbol", "symbols", "key", "keys", "selite", "selitteet", "merkinnat", "merkit", "merkintatavat",
               "legende", "zeichenerklarung", "zeichen", "teckenforklaring", "forklaring", "symboler", "legenda", "leyenda", "simbolos"}
CACHE_DIR = Path(os.environ.get("RESULTS_DIR") or "/tmp/hologram") / "symbols_cache"


# ------------------------------------------------------------------------------------------------ text helpers
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def _toks(s: str) -> list[str]:
    return re.findall(r"[^\W_]+", _norm(s), re.U)


def _stem(t: str) -> str:
    for suf in ("ies", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


# equivalent words (English, Finnish, German, Swedish) used only to match a question noun to a printed legend label
SYN_GROUPS = [
    {"light", "lighting", "luminaire", "fixture", "fitting", "lamp", "downlight", "valaisin", "valaisimet", "leuchte", "armatur", "belysning", "lampa"},
    {"socket", "receptacle", "outlet", "plug", "pistorasia", "steckdose", "uttag", "stikkontakt", "gfci", "gfi", "duplex"},
    {"smoke", "savu", "rauch", "rok"},
    {"detector", "sensor", "alarm", "ilmaisin", "melder", "detektor", "larm"},
    {"switch", "kytkin", "schalter", "brytare"},
    {"valve", "venttiili", "ventil", "ventile"},
    {"extinguisher", "sammutin", "feuerloscher", "slackare"},
    {"diffuser", "grille", "register", "terminal", "tuloilma", "poistoilma"},
    {"cleanout", "clean", "puhdistus"},
    {"drain", "viemari", "abfluss", "avlopp"},
    {"exit", "poistumis", "ausgang", "utgang"},
    {"sprinkler", "sprinkleri", "sprinkleranlage"},
    {"thermostat", "termostaatti", "thermostat"},
    {"camera", "kamera"},
    {"speaker", "kaiutin", "lautsprecher"},
    {"hydrant", "paloposti"},
    {"pump", "pumppu", "pumpe"},
    {"fan", "puhallin", "ventilator", "fläkt"},
]
STOP = {"the", "of", "a", "an", "all", "this", "that", "on", "in", "at", "for", "are", "is", "there", "sheet", "drawing", "plan", "page",
        "total", "number", "many", "how", "count", "and", "or", "symbol", "symbols", "type", "to", "with", "shown", "marked", "drawn",
        "do", "does", "have", "has", "be", "been", "by", "from", "me", "show", "please", "can", "you", "tell", "what", "which"}


def _canon(t: str) -> str:
    t = _stem(t)
    for g in SYN_GROUPS:
        if t in g or _stem(t) in {_stem(x) for x in g}:
            return "~" + sorted(g)[0]
    return t


def _forms(t: str) -> set[str]:
    """The word, its stem and every word of its synonym group (all languages)."""
    f = {t, _stem(t)}
    for g in SYN_GROUPS:
        if t in g or _stem(t) in {_stem(x) for x in g}:
            f |= {_norm(x) for x in g}
    return {x for x in f if x}


def target_score(target: str, label: str) -> float:
    """Share of the target's content words that the legend label also has. Synonym groups across languages count as the same word,
    and a long form may sit inside a compound word (savuilmaisin = smoke detector)."""
    tt = [t for t in _toks(target) if t not in STOP and len(t) > 1]
    lt = _toks(label)
    if not tt:
        return 0.0
    hit = 0
    for t in tt:
        fs = _forms(t)
        if any(w in fs or any(len(f) >= 4 and f in w for f in fs) for w in lt):
            hit += 1
    return hit / len(tt)


# ------------------------------------------------------------------------------------------------ images
def load_gray(path) -> np.ndarray:
    g = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise ValueError(f"cannot read image {path}")
    if g.mean() < 90:   # white-on-black drawing: flip so ink is dark
        g = 255 - g
    return g


def ink_mask(gray: np.ndarray) -> np.ndarray:
    """1 where there is ink (dark lines), 0 elsewhere. Otsu, capped so pale tints do not become ink."""
    t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    thr = max(min(float(t), 200.0), 100.0)   # floor: a two-tone image makes Otsu return 0
    return (gray < thr).astype(np.uint8)


def _sha(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:20]


def _cache_get(name: str):
    try:
        return json.loads((CACHE_DIR / name).read_text())
    except (OSError, ValueError):
        return None


def _cache_put(name: str, data) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / name).write_text(json.dumps(data))
    except OSError:
        pass


def _dedupe_words(ws: list[dict]) -> list[dict]:
    """OCR tiles overlap, so a word near a tile edge is read twice: keep one of each same-text, same-place pair."""
    out: list[dict] = []
    for w in ws:
        b = w.get("bbox_px")
        dup = False
        if b:
            for o in out[-400:]:
                ob = o.get("bbox_px")
                if ob and o.get("text") == w.get("text"):
                    iw = min(b[2], ob[2]) - max(b[0], ob[0])
                    ih = min(b[3], ob[3]) - max(b[1], ob[1])
                    if iw > 0 and ih > 0 and iw * ih > 0.5 * min((b[2] - b[0]) * (b[3] - b[1]), (ob[2] - ob[0]) * (ob[3] - ob[1])):
                        dup = True
                        break
        if not dup:
            out.append(w)
    return out


def page_words(image_path, words=None) -> tuple[list[dict], str]:
    """Words with pixel boxes of the image: the caller's, a cached OCR, or a fresh OCR (rapidocr, local, free)."""
    if words is not None:
        return list(words), "given"
    key = f"ocr-{_sha(image_path)}.json"
    hit = _cache_get(key)
    if hit is not None:
        return _dedupe_words(hit), "ocr"
    try:
        from engine.reader.text import ocr_words
        w = ocr_words(Path(image_path))
    except Exception:  # noqa: BLE001 - no OCR installed: the legend finder then reports "no legend found"
        return [], "none"
    w = _dedupe_words(w)
    _cache_put(key, w)
    return w, "ocr"


# ------------------------------------------------------------------------------------------------ 1. legend finder
def _segments(words: list[dict], w: int, h: int) -> list[dict]:
    from engine.reader.text import PageText, build_segments
    pt = PageText("", 1, w, h, [x for x in words if x.get("bbox_px") and str(x.get("text") or "").strip()], "given")
    return build_segments(pt)


def _components(ink: np.ndarray, words: list[dict]):
    """Connected shapes of the ink with the text removed, after a 1-pixel dilation that bridges symbol parts."""
    m = ink.copy()
    H, W = m.shape
    for wd in words:
        b = wd.get("bbox_px")
        if not b:
            continue
        x0, y0, x1, y1 = max(0, int(b[0]) - 1), max(0, int(b[1]) - 1), min(W, int(b[2]) + 2), min(H, int(b[3]) + 2)
        m[y0:y1, x0:x1] = 0
    d = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=1)
    n, lab, st, cen = cv2.connectedComponentsWithStats(d, connectivity=8)
    keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 6 and st[i, 2] < W / 5 and st[i, 3] < H / 5]
    return st[keep], cen[keep], lab, keep


def _symbol_near(seg, side, st, cen, hs, pitch, left_limit=None):
    """Union box of the shapes beside a label (side -1 = left, +1 = right); None when there is no compact one."""
    x0, y0, x1, y1 = seg["bbox_px"]
    cy = (y0 + y1) / 2
    reach = 12 * hs
    if side < 0:
        wx0, wx1 = x0 - reach, x0 - 0.1 * hs
        if left_limit is not None:
            wx0 = max(wx0, left_limit)
    else:
        wx0, wx1 = x1 + 0.1 * hs, x1 + reach
    wy0, wy1 = cy - 0.62 * pitch, cy + 0.62 * pitch
    sel = (cen[:, 0] >= wx0) & (cen[:, 0] <= wx1) & (cen[:, 1] >= wy0) & (cen[:, 1] <= wy1)
    idx = np.nonzero(sel)[0]
    if not len(idx):
        return None
    boxes = []
    for i in idx:
        x, y, w, h = (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]), int(st[i, 3]))
        if h > 1.7 * pitch or w > 12 * hs:      # table borders, frames, long rules
            continue
        if side < 0 and x < wx0 - hs:           # a shape that starts far left of the window: part of something bigger
            continue
        boxes.append((x, y, x + w, y + h))
    if not boxes:
        return None
    ux0, uy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    ux1, uy1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    if (ux1 - ux0) < 0.3 * hs and (uy1 - uy0) < 0.3 * hs:
        return None
    return [ux0, uy0, ux1, uy1]


def _clean_label(t: str) -> str:
    t = re.sub(r"^\s*(?:\d+|[A-Za-z])\s*[.)\]:]\s+", "", t.strip())
    t = re.sub(r"^[\-–—:=\s]+|[\-–—:=\s]+$", "", t)
    return re.sub(r"\s+", " ", t)


def find_legend(image_path, words=None, ink=None) -> dict:
    """-> {entries:[{label,label_bbox,symbol_bbox,kind,section,block}], regions:[bbox], titled:bool, source, image}.

    entries is empty when the sheet has no legend-like block (three or more label rows with a shape beside each)."""
    gray = None
    if ink is None:
        gray = load_gray(image_path)
        ink = ink_mask(gray)
    H, W = ink.shape
    words, src = page_words(image_path, words)
    out = {"entries": [], "regions": [], "titled": False, "source": src, "image": str(image_path), "size": [W, H]}
    segs = [s for s in _segments(words, W, H) if re.search(r"[^\W\d_]{2,}", s["text"], re.U)]
    if len(segs) < 3:
        return out
    hts = sorted(s["bbox_px"][3] - s["bbox_px"][1] for s in segs)
    h_med = max(hts[len(hts) // 2], 6.0)
    st, cen, _lab, _keep = _components(ink, words)
    if not len(st):
        return out

    rows = []   # one per label segment that has a shape beside it
    for i, s in enumerate(segs):
        hs = max(s["bbox_px"][3] - s["bbox_px"][1], 6.0)
        if hs > 2.2 * h_med or len(s["text"]) > 90:
            continue
        # row pitch: distance to the nearest label above/below in the same column
        pitches = [abs((o["bbox_px"][1] + o["bbox_px"][3]) / 2 - (s["bbox_px"][1] + s["bbox_px"][3]) / 2) for j, o in enumerate(segs)
                   if j != i and abs(o["bbox_px"][0] - s["bbox_px"][0]) < 3 * hs]
        pitches = [p for p in pitches if p >= 1.1 * hs]
        pitch = min(max(min(pitches) if pitches else 2.4 * hs, 1.5 * hs), 8 * hs)
        box = _symbol_near(s, -1, st, cen, hs, pitch)
        side = "left"
        if box is None:
            box, side = _symbol_near(s, +1, st, cen, hs, pitch), "right"
        if box is None:
            continue
        rows.append({"i": i, "seg": s, "sym": box, "side": side, "hs": hs, "pitch": pitch})

    # group rows into columns (label x0 or, for right-side shapes, label x1) and stack them
    blocks = []
    for side in ("left", "right"):
        rs = sorted((r for r in rows if r["side"] == side),
                    key=lambda r: (round((r["seg"]["bbox_px"][0] if side == "left" else r["seg"]["bbox_px"][2]) / (2.5 * h_med)), r["seg"]["bbox_px"][1]))
        cur = []
        for r in rs:
            ax = r["seg"]["bbox_px"][0] if side == "left" else r["seg"]["bbox_px"][2]
            if cur:
                pax = cur[-1]["seg"]["bbox_px"][0] if side == "left" else cur[-1]["seg"]["bbox_px"][2]
                gap = r["seg"]["bbox_px"][1] - cur[-1]["seg"]["bbox_px"][3]
                if abs(ax - pax) > 3.0 * h_med or gap > 4.5 * max(r["hs"], cur[-1]["hs"]) + cur[-1]["pitch"] * 0.5:
                    blocks.append(cur)
                    cur = []
            cur.append(r)
        if cur:
            blocks.append(cur)
    heads = [s for s in _segments(words, W, H) if LEGEND_KEYS & set(_toks(s["text"])) and len(_toks(s["text"])) <= 6]
    for blk in blocks:
        if len(blk) < 3:
            continue
        bx0 = min(r["seg"]["bbox_px"][0] for r in blk)
        by0 = min(r["seg"]["bbox_px"][1] for r in blk)
        by1 = max(r["seg"]["bbox_px"][3] for r in blk)
        # coverage: rows with a shape / all label rows of the same column span (a table of text with one icon is not a legend)
        same = [s for s in segs if abs(s["bbox_px"][0] - bx0) < 3 * h_med and by0 - 1 <= s["bbox_px"][1] <= by1 + 1]
        cover = len(blk) / max(len(same), 1)
        near_head = [hd for hd in heads if hd["bbox_px"][3] <= by0 + h_med and by0 - hd["bbox_px"][3] < 14 * h_med
                     and hd["bbox_px"][0] < bx0 + 40 * h_med and hd["bbox_px"][2] > bx0 - 20 * h_med]
        titled = bool(near_head)
        if cover < (0.4 if titled else 0.6) or len(blk) < (3 if titled else 5):
            continue
        # a legend is a tidy list: different labels, shapes lined up in one column, evenly spaced rows. Room labels scattered over a plan are not.
        labs = [_norm(r["seg"]["text"]) for r in blk]
        if len(set(labs)) < 0.8 * len(labs):
            continue
        sx = [r["sym"][0] if r["side"] == "left" else r["sym"][2] for r in blk]
        if np.ptp(sx) > 6.0 * h_med:
            continue
        cy_ = sorted((r["seg"]["bbox_px"][1] + r["seg"]["bbox_px"][3]) / 2 for r in blk)
        dd = np.diff(cy_)
        if len(dd) >= 2 and float(np.std(dd)) > 0.6 * float(np.mean(dd)):
            continue
        # a block whose shapes are all different sizes of the same big frame is not a legend: shapes must be small next to the page
        section = None
        above = [s for s in segs if s["bbox_px"][3] <= by0 + 2 and by0 - s["bbox_px"][3] < 9 * h_med
                 and s["bbox_px"][0] < bx0 + 30 * h_med and s["bbox_px"][2] > bx0 - 30 * h_med
                 and (s["bbox_px"][3] - s["bbox_px"][1]) >= 1.15 * h_med]
        if above:
            section = max(above, key=lambda s: s["bbox_px"][3])["text"]
        ents = []
        for r in blk:
            sb = r["sym"]
            w_, h_ = sb[2] - sb[0], sb[3] - sb[1]
            aspect = max(w_, h_) / max(min(w_, h_), 1)
            line_like = aspect > 7 or min(w_, h_) < 0.25 * r["hs"] and aspect > 4
            if not line_like and (max(w_, h_) < 0.9 * r["hs"] or min(w_, h_) < 0.3 * r["hs"]):
                continue   # a speck or fragment (an abbreviation list, a table border), not a drawn symbol
            label = _clean_label(r["seg"]["text"])
            if len(re.findall(r"[^\W\d_]", label, re.U)) < 4:
                continue   # an abbreviation or code, not a description of a symbol
            ents.append({"label": label, "label_bbox": [int(v) for v in r["seg"]["bbox_px"]], "symbol_bbox": [int(v) for v in sb],
                         "kind": "line" if line_like else "symbol", "section": section, "titled": titled, "side": r["side"]})
        if len(ents) < 3:
            continue
        xs = [e["label_bbox"][0] for e in ents] + [e["symbol_bbox"][0] for e in ents]
        xe = [e["label_bbox"][2] for e in ents] + [e["symbol_bbox"][2] for e in ents]
        ys = [e["label_bbox"][1] for e in ents] + [e["symbol_bbox"][1] for e in ents]
        ye = [e["label_bbox"][3] for e in ents] + [e["symbol_bbox"][3] for e in ents]
        pad = int(0.6 * h_med)
        out["regions"].append([max(0, min(xs) - pad), max(0, min(ys) - pad), min(W, max(xe) + pad), min(H, max(ye) + pad)])
        out["titled"] = out["titled"] or titled
        for e in ents:
            e["block"] = len(out["regions"]) - 1
        out["entries"].extend(ents)
    for k, e in enumerate(out["entries"]):
        e["id"] = k
    return out


# ------------------------------------------------------------------------------------------------ 2. template matching
def _crop(ink: np.ndarray, bb, pad=2) -> np.ndarray:
    H, W = ink.shape
    x0, y0, x1, y1 = [int(v) for v in bb]
    return ink[max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)]


def symbol_weakness(tmpl: np.ndarray) -> str | None:
    """Why this shape cannot be matched reliably (None = fine). Matching would flood the sheet with false hits."""
    h, w = tmpl.shape
    if min(h, w) < 6 or max(h, w) < 9:
        return "too small to match"
    n = int(tmpl.sum())
    if n < 25:
        return "too little drawn"
    if n / (h * w) > 0.7:
        return "a solid blob"
    if max(int(tmpl.sum(axis=1).max()), int(tmpl.sum(axis=0).max())) > 0.55 * n:
        return "mostly one straight line"
    # what is left after taking away the long straight runs (pipes, wires, walls): too little means the symbol is mostly line work
    L = max(5, int(0.55 * max(h, w)))
    t8 = tmpl.astype(np.uint8)
    runs = cv2.morphologyEx(t8, cv2.MORPH_OPEN, np.ones((1, L), np.uint8)) | cv2.morphologyEx(t8, cv2.MORPH_OPEN, np.ones((L, 1), np.uint8))
    rest = t8 & (1 - cv2.dilate(runs, np.ones((3, 3), np.uint8)))
    if int(rest.sum()) < 0.3 * n:
        # a closed outline (box, circle, triangle) encloses area; a pipe, wire or wall piece with ticks does not
        pad = np.pad(t8, 1)
        ff = (1 - pad).astype(np.uint8)
        cv2.floodFill(ff, np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8), (0, 0), 2)
        enclosed = int((ff == 1).sum())
        if enclosed < 0.25 * h * w:
            return "mostly line work"
    return None


def _smooth(a: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(a, (0, 0), sigma)


def _peaks(res: np.ndarray, thr: float, rad: int):
    mx = cv2.dilate(res, np.ones((2 * rad + 1, 2 * rad + 1), np.uint8))
    ys, xs = np.nonzero((res >= thr) & (res >= mx - 1e-6))
    sc = res[ys, xs]
    order = np.argsort(-sc)[:MAX_PEAKS]
    return [(int(xs[i]), int(ys[i]), float(sc[i])) for i in order]


def match_symbol(plan_ink: np.ndarray, tmpl: np.ndarray, _small_cache: dict | None = None) -> list[dict]:
    """Candidates [{box, score, recall, clutter, rot, scale}] of one symbol on a sheet (full-resolution pixel boxes), NMS-ed."""
    th, tw = tmpl.shape
    tmax = max(th, tw)
    f = max(1.0, tmax / TARGET_PX)
    fkey = round(f * 4) / 4
    cache = _small_cache if _small_cache is not None else {}
    if fkey not in cache:
        pf = plan_ink.astype(np.float32)
        small = pf if fkey == 1.0 else cv2.resize(pf, None, fx=1 / fkey, fy=1 / fkey, interpolation=cv2.INTER_AREA)
        cache[fkey] = _smooth(small, 0.9)
    plan_s = cache[fkey]
    f = fkey
    tf = tmpl.astype(np.float32)
    cands = []
    seen_sym = []
    for k in range(4):
        base = np.rot90(tf, k)
        if k and any(np.corrcoef(base.ravel(), np.rot90(tf, j).ravel())[0, 1] > 0.985 for j in seen_sym if base.shape == np.rot90(tf, j).shape):
            continue   # the symbol looks the same turned: no need to search it again
        seen_sym.append(k)
        for s in SCALES:
            bh, bw = base.shape
            nh, nw = max(3, int(round(bh * s / f))), max(3, int(round(bw * s / f)))
            if min(nh, nw) < 5 or nh >= plan_s.shape[0] or nw >= plan_s.shape[1]:
                continue
            t = _smooth(cv2.resize(base, (nw, nh), interpolation=cv2.INTER_AREA), 0.9)
            if float(t.std()) < 1e-3:
                continue
            res = cv2.matchTemplate(plan_s, t, cv2.TM_CCOEFF_NORMED)
            res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
            for x, y, sc in _peaks(res, LOW_NCC, max(2, int(0.4 * min(nh, nw)))):
                cands.append({"box": [x * f, y * f, (x + nw) * f, (y + nh) * f], "score": sc, "rot": k, "scale": s})
    cands.sort(key=lambda c: -c["score"])
    kept = []
    for c in cands:
        cx, cy = (c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2
        sz = max(c["box"][2] - c["box"][0], c["box"][3] - c["box"][1])
        if any(abs(cx - k["_cx"]) < 0.45 * max(sz, k["_sz"]) and abs(cy - k["_cy"]) < 0.45 * max(sz, k["_sz"]) for k in kept):
            continue
        c["_cx"], c["_cy"], c["_sz"] = cx, cy, sz
        kept.append(c)
    H, W = plan_ink.shape
    ones = np.ones((3, 3), np.uint8)
    for c in kept:
        x0, y0, x1, y1 = [int(round(v)) for v in c["box"]]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        win = plan_ink[y0:y1, x0:x1]
        if win.size == 0:
            c["recall"], c["clutter"], c["prec"] = 0.0, 9.0, 0.0
            continue
        tb = cv2.resize(np.rot90(tmpl, c["rot"]).astype(np.uint8), (win.shape[1], win.shape[0]), interpolation=cv2.INTER_NEAREST)
        tn = max(int(tb.sum()), 1)
        c["recall"] = float((tb & cv2.dilate(win, ones)).sum()) / tn
        c["prec"] = float((win & cv2.dilate(tb, ones)).sum()) / max(int(win.sum()), 1)
        c["clutter"] = float(win.sum()) / tn
        del c["_cx"], c["_cy"], c["_sz"]
    return kept


def classify(c: dict, weak: bool) -> str:
    """strong | uncertain | drop"""
    if c["score"] >= ACCEPT_NCC and c["recall"] >= ACCEPT_RECALL and c["prec"] >= 0.6 and c["clutter"] <= 2.2 and not weak:
        return "strong"
    if c["score"] >= LOW_NCC and c["recall"] >= LOW_RECALL and c["prec"] >= 0.4:
        return "uncertain"
    return "drop"


# ------------------------------------------------------------------------------------------------ 3. model check of candidates
def _tile(gray: np.ndarray, box, n: int, size=132) -> np.ndarray:
    H, W = gray.shape
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = max(x1 - x0, y1 - y0) * 1.1 + 10
    a, b, c_, d = int(max(0, cx - half)), int(max(0, cy - half)), int(min(W, cx + half)), int(min(H, cy + half))
    crop = gray[b:d, a:c_]
    if crop.size == 0:
        crop = np.full((8, 8), 255, np.uint8)
    t = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    t = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
    # centre marker: a thin square around the candidate itself
    fx = size / max(c_ - a, 1)
    fy = size / max(d - b, 1)
    cv2.rectangle(t, (int((x0 - a) * fx), int((y0 - b) * fy)), (int((x1 - a) * fx), int((y1 - b) * fy)), (0, 0, 220), 1)
    cv2.rectangle(t, (0, 0), (26, 18), (255, 255, 255), -1)
    cv2.putText(t, str(n), (2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.rectangle(t, (0, 0), (size - 1, size - 1), (160, 160, 160), 1)
    return t


def _mosaic(gray, boxes, start=1, cols=5, size=132) -> np.ndarray:
    tiles = [_tile(gray, b, start + i, size) for i, b in enumerate(boxes)]
    rows = [np.hstack(tiles[i:i + cols] + [np.full((size, size, 3), 255, np.uint8)] * (cols - len(tiles[i:i + cols]))) for i in range(0, len(tiles), cols)]
    return np.vstack(rows)


VERIFY_SCHEMA = {"type": "object", "required": ["results"], "additionalProperties": False, "properties": {"results": {
    "type": "array", "items": {"type": "object", "required": ["n", "match"], "additionalProperties": False,
                               "properties": {"n": {"type": "integer"}, "match": {"type": "boolean"}}}}}}
VERIFY_PROMPT = ("Image 1 is a reference drawing symbol from a legend, labelled \"%s\". Image 2 is a grid of numbered tiles cut from the same "
                 "set of drawings; the thin red box marks the item to judge. For each numbered tile answer match=true only if the item in the "
                 "red box is this same symbol (same shape; it may be turned by 90 degrees or drawn slightly larger or smaller). Text, wall "
                 "lines, door arcs, furniture or a different symbol are match=false. Tiles: %s. Reply JSON only: "
                 "{\"results\":[{\"n\":<tile number>,\"match\":<true|false>}]}.")


def _ref_img(tmpl: np.ndarray) -> np.ndarray:
    """the legend symbol as a reader sees it: dark lines on white paper (the ink mask itself is white on black)"""
    return (255 - tmpl.astype(np.uint8) * 255) if tmpl.max() <= 1 else tmpl


def _verify_tiles(ref_img: np.ndarray, label: str, gray: np.ndarray, boxes: list, budget: dict) -> list[bool | None]:
    """Yes/no per candidate from the vision model; None = no verdict (no model, over budget, bad reply)."""
    out: list[bool | None] = [None] * len(boxes)
    if not boxes or os.environ.get("SYMBOLS_VERIFY", "1") == "0":
        return out
    try:
        from engine.models import call
    except Exception:  # noqa: BLE001
        return out
    tmp = Path(tempfile.mkdtemp(prefix="sym-"))
    refp = tmp / "ref.png"
    rh, rw = ref_img.shape[:2]
    sc = 120 / max(rh, rw)
    ref = cv2.resize(ref_img, (max(8, int(rw * sc)), max(8, int(rh * sc))), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(refp), cv2.copyMakeBorder(ref, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255))
    for i in range(0, len(boxes), VERIFY_TILES_PER_CALL):
        if budget["calls"] >= VERIFY_MAX_CALLS:
            break
        chunk = boxes[i:i + VERIFY_TILES_PER_CALL]
        mp = tmp / f"m{i}.png"
        cv2.imwrite(str(mp), _mosaic(gray, chunk, start=1))
        try:
            r = call("symbols_verify", [{"role": "user", "content": VERIFY_PROMPT % (label.replace('"', "'"), f"1 to {len(chunk)}")}],
                     images=[refp, mp], schema=VERIFY_SCHEMA)
        except Exception:  # noqa: BLE001 - budget, network, no key
            break
        budget["calls"] += 1
        budget["usd"] += float(getattr(r, "cost_usd", 0) or 0)
        budget["models"].add(getattr(r, "model", "") or "")
        js = r.json if isinstance(r.json, dict) else {}
        for item in js.get("results") or []:
            try:
                n = int(item["n"])
                if 1 <= n <= len(chunk):
                    out[i + n - 1] = bool(item["match"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


# ------------------------------------------------------------------------------------------------ 4. the public function
def _inside(pt, bb) -> bool:
    return bb[0] <= pt[0] <= bb[2] and bb[1] <= pt[1] <= bb[3]


def _reading_order(items: list[dict]) -> list[dict]:
    if not items:
        return items
    hs = sorted(i["box"][3] - i["box"][1] for i in items)
    band = max(hs[len(hs) // 2], 1) * 1.2
    return sorted(items, key=lambda c: (round(((c["box"][1] + c["box"][3]) / 2) / band), (c["box"][0] + c["box"][2]) / 2))


def pick_entries(legend: dict, target: str | None) -> tuple[list[dict], str | None]:
    """Legend entries to count: the ones whose label matches the target; all countable ones when there is no target."""
    ents = [e for e in legend.get("entries") or []]
    if not target:
        return [e for e in ents if e["kind"] == "symbol"][:MAX_ENTRIES_PER_QUESTION], None
    scored = [(target_score(target, e["label"]), e) for e in ents]
    best = max((s for s, _ in scored), default=0.0)
    if best < 0.5:
        return [], f"No legend entry is called anything like \"{target}\"."
    return [e for s, e in scored if s >= best - 1e-9][:MAX_ENTRIES_PER_QUESTION], None


def count_symbols(image_path, legend: dict | None = None, target: str | None = None, *, words=None, verify: bool = True,
                  budget: dict | None = None, exclude_regions: list | None = None) -> dict:
    """Count the legend symbols on one raster sheet.

    legend  : a dict from find_legend (it may come from another sheet: entries carry boxes into legend["image"]); None = find it on this sheet
    target  : text such as "smoke detectors"; only legend entries with such a label are counted (None = every countable entry)
    returns : {counts, boxes, possible, legend_used, checked, cost_usd, notes}; boxes are the counted items, numbered 1..N in reading order
    """
    t0 = time.perf_counter()
    notes: list[str] = []
    gray = load_gray(image_path)
    ink = ink_mask(gray)
    budget = budget if budget is not None else {"calls": 0, "usd": 0.0, "models": set()}
    own = None
    plan_ink = ink          # the sheet's ink with its text blanked: printed words must never match a drawn symbol
    try:
        pw, _src = page_words(image_path, words)
        plan_ink = ink.copy()
        Hh, Ww = plan_ink.shape
        for wd in pw:
            b = wd.get("bbox_px")
            # OCR reads stars, crosses and circles as odd characters (CJK, punctuation): a word without a Latin letter or digit is a symbol, not text
            if b and re.search(r"[0-9A-Za-z\u00c0-\u024f]", str(wd.get("text", ""))):
                plan_ink[max(0, int(b[1]) - 1):min(Hh, int(b[3]) + 2), max(0, int(b[0]) - 1):min(Ww, int(b[2]) + 2)] = 0
    except Exception:  # noqa: BLE001
        plan_ink = ink
    if legend is None:
        legend = find_legend(image_path, words, ink=ink)
        own = legend
    same_sheet = str(legend.get("image")) == str(image_path)
    regions = [list(r) for r in (legend.get("regions") or [])] if same_sheet else []
    regions += [list(r) for r in (exclude_regions or [])]
    res = {"counts": {}, "boxes": [], "possible": [], "legend_used": {"source": legend.get("source"), "image": legend.get("image"),
                                                                        "titled": legend.get("titled"), "regions": legend.get("regions") or [],
                                                                        "entries": []},
           "checked": {"sampled": 0, "agree": 0, "uncertain": 0, "confirmed": 0, "rejected": 0, "model": None},
           "cost_usd": 0.0, "notes": notes, "image": str(image_path)}
    if not legend.get("entries"):
        notes.append("no legend found on this sheet")
        return res
    ents, why = pick_entries(legend, target)
    if why:
        notes.append(why)
    leg_gray = gray if same_sheet else load_gray(legend["image"])
    leg_ink = ink if same_sheet else ink_mask(leg_gray)
    cache: dict = {}
    allc = []
    for e in ents:
        tmpl = _crop(leg_ink, e["symbol_bbox"])
        weak_why = symbol_weakness(tmpl)
        entry_info = {"id": e["id"], "label": e["label"], "symbol_bbox": e["symbol_bbox"], "weak": weak_why}
        res["legend_used"]["entries"].append(entry_info)
        if weak_why:
            notes.append(f"\"{e['label']}\": symbol is {weak_why}, matches are only counted after a model check")
        cands = match_symbol(plan_ink, tmpl, cache)
        keep = []
        for c in cands:
            if min(c["box"][2] - c["box"][0], c["box"][3] - c["box"][1]) < MIN_HIT_PX:
                continue       # smaller than anything a person could read as a symbol: a dot or a crossing
            cls = classify(c, bool(weak_why))
            if cls == "drop":
                continue
            ctr = ((c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2)
            if any(_inside(ctr, r) for r in regions):
                continue
            c.update(entry=e["id"], label=e["label"], cls=cls, box=[int(round(v)) for v in c["box"]])
            keep.append(c)
        allc.append((e, tmpl, keep))
    # a spot that matches two legend symbols belongs to the better one
    flat = [c for _e, _t, ks in allc for c in ks]
    flat.sort(key=lambda c: -c["score"])
    taken: list[dict] = []
    for c in flat:
        ctr = ((c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2)
        sz = max(c["box"][2] - c["box"][0], c["box"][3] - c["box"][1])
        clash = [t for t in taken if abs(ctr[0] - t["_c"][0]) < 0.45 * sz and abs(ctr[1] - t["_c"][1]) < 0.45 * sz]
        if clash:
            if clash[0]["entry"] != c["entry"] and c["cls"] == "strong" and clash[0]["score"] - c["score"] < 0.03:
                clash[0]["cls"] = "uncertain"
            c["cls"] = "drop"
            continue
        c["_c"] = ctr
        taken.append(c)
    weak_entry = {ei["id"]: bool(ei["weak"]) for ei in res["legend_used"]["entries"]}
    for e, tmpl, ks in allc:
        live = [c for c in ks if c["cls"] != "drop"]
        strong = [c for c in live if c["cls"] == "strong"]
        unc = [c for c in live if c["cls"] == "uncertain"]
        sample = []
        if verify and strong:
            step = max(1, len(strong) // VERIFY_SAMPLE_OK)
            sample = strong[::step][:VERIFY_SAMPLE_OK]
        if weak_entry.get(e["id"]):
            unc = sorted(unc + [c for c in strong], key=lambda c: -c["score"])   # weak symbol: nothing is counted on the template alone
            for c in unc:
                c["cls"] = "uncertain"
            strong, sample = [], []
        todo = unc[:VERIFY_TILES_PER_CALL * 2] + sample
        verdicts = _verify_tiles(_ref_img(tmpl), e["label"], gray, [c["box"] for c in todo], budget) if (verify and todo) else []
        res["checked"]["uncertain"] += len(unc)
        for c, v in zip(todo, verdicts):
            if c in sample:
                if v is not None:
                    res["checked"]["sampled"] += 1
                    res["checked"]["agree"] += int(v)
                    if not v:
                        c["cls"] = "drop"      # both passes must agree
            else:
                if v is True:
                    c["cls"] = "confirmed"
                    res["checked"]["confirmed"] += 1
                elif v is False:
                    c["cls"] = "drop"
                    res["checked"]["rejected"] += 1
        if verify and sample and res["checked"]["sampled"] and res["checked"]["agree"] < res["checked"]["sampled"]:
            # the model disagreed with the template on a sampled hit: do not trust the template for this symbol, check every strong hit
            rest = sorted([c for c in strong if c["cls"] == "strong" and c not in sample], key=lambda c: c["score"])
            vs = _verify_tiles(_ref_img(tmpl), e["label"], gray, [c["box"] for c in rest], budget) if rest else []
            vs = list(vs) + [None] * (len(rest) - len(vs))
            for c, v in zip(rest, vs):
                if v is True:
                    c["cls"] = "confirmed"
                    res["checked"]["confirmed"] += 1
                elif v is False:
                    c["cls"] = "drop"
                    res["checked"]["rejected"] += 1
                else:
                    c["cls"] = "uncertain"       # no verdict: possible, not counted
            res["checked"]["uncertain"] += sum(1 for v in vs if v is None)
            notes.append(f"\"{e['label']}\": the template matched hatching and line crossings too, so every hit was checked by the model")
        kept = [c for c in live if c["cls"] in ("strong", "confirmed")]
        poss = [c for c in live if c["cls"] == "uncertain"]
        res["counts"][e["label"]] = res["counts"].get(e["label"], 0) + len(kept)
        for c in kept:
            res["boxes"].append({"label": e["label"], "entry": e["id"], "bbox_px": c["box"], "score": round(c["score"], 3),
                                 "status": "template+model" if c["cls"] == "confirmed" else "template", "rot": c["rot"], "scale": c["scale"]})
        for c in poss:
            res["possible"].append({"label": e["label"], "entry": e["id"], "bbox_px": c["box"], "score": round(c["score"], 3)})
    ordered = sorted(res["boxes"], key=lambda b: ((b["bbox_px"][1] + b["bbox_px"][3]) / 2 // max(1, 0.6 * np.median([b["bbox_px"][3] - b["bbox_px"][1] for b in res["boxes"]] or [1])), b["bbox_px"][0]))
    for n, b in enumerate(ordered, 1):
        b["n"] = n
    res["boxes"] = ordered
    res["checked"]["model"] = ", ".join(sorted(m for m in budget["models"] if m)) or None
    res["cost_usd"] = round(budget["usd"], 6)
    res["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    if own is not None:
        res["legend_found"] = own
    return res


# ------------------------------------------------------------------------------------------------ 5. chat route
BASIC = {"door", "window", "room", "wall", "storey", "story", "floor", "stair", "staircase", "toilet", "wc", "sink", "shower", "bathtub", "bath",
         "column", "slab", "page", "sheet", "file", "document", "drawing", "level", "bedroom", "kitchen", "bathroom", "balcony", "unit", "apartment",
         "text", "word", "label", "line", "dimension", "symbol"}
LEGEND_Q = re.compile(r"\b(?:legend|legends|key to (?:the )?symbols?|symbol\s+(?:list|key|table)|list of symbols|(?:what|which)\s+symbols?\b|symbols?\s+(?:are|is)?\s*(?:used|shown|listed|explained)|"
                      r"what\s+(?:do|does)\s+(?:the\s+)?symbols?\s+mean|selite|merkinn\w+|legende|zeichenerkl\w+|teckenf\w+)", re.I)
COUNT_Q = re.compile(r"^\W*(?:how many|count|number of|total number of|what(?:'s| is) the (?:total |number of )?(?:count|number) of|tell me how many|can you count)\s+(?:of\s+)?(?:the\s+|all\s+(?:the\s+)?)?(.+?)"
                     r"(?:\s+(?:are|is|do|does|can|have|has|were|there|on|in|shown|drawn|marked|appear|exist|included|listed)\b.*)?[?.!\s]*$", re.I)


def question_noun(q: str) -> str | None:
    m = COUNT_Q.search((q or "").strip())
    if not m:
        return None
    noun = m.group(1).strip()
    toks = [t for t in _toks(noun) if t not in STOP]
    if not toks or all(_stem(t) in BASIC for t in toks):
        return None
    return " ".join(toks)


def _pages(doc_id: str, root: Path) -> list[int]:
    d = root / doc_id
    ps = sorted(int(m.group(1)) for p in d.glob("page-*.png") if (m := re.fullmatch(r"page-(\d+)\.png", p.name)) and ".thumb" not in p.name)
    return ps[:MAX_PAGES]


def _doc_legends(doc_id: str, root: Path, allow_ocr: bool = True) -> list[tuple[int, dict]]:
    """[(page, legend dict)] for the pages of a document that carry a legend (cached by image hash)."""
    from engine.reader.text import load_page_text
    out = []
    for p in _pages(doc_id, root):
        img = root / doc_id / f"page-{p}.png"
        key = f"legend-{_sha(img)}.json"
        lg = _cache_get(key)
        if lg is None:
            try:
                pt = load_page_text(doc_id, p, root, allow_ocr=allow_ocr)
            except Exception:  # noqa: BLE001
                continue
            if not pt.words:
                continue
            try:
                lg = find_legend(img, pt.words)
            except Exception:  # noqa: BLE001
                continue
            _cache_put(key, lg)
        lg["page"] = p
        if lg.get("entries"):
            out.append((p, lg))
    return out


def _doc_meta(doc_id: str, root: Path) -> dict:
    try:
        return json.loads((root / doc_id / "doc.json").read_text())
    except (OSError, ValueError):
        return {}


def _conf_label(checked: dict, n_boxes: int, weak: bool) -> tuple[str, int]:
    m, a, u = checked["sampled"], checked["agree"], checked["uncertain"]
    if m >= 3 and a / m >= 0.9 and not weak:
        return "Cross-checked", min(90, 80 + int(10 * a / m))
    if m >= 1 and a / m >= 0.75 and not weak:
        return "Cross-checked", 80
    return "Estimate", 62 if m == 0 else 70


def _step(step, detail, ms=0, model=None, cost=0.0):
    return {"step": step, "detail": detail, "ms": ms, "model": model, "cost_usd": cost}


def _obj(question, doc_id, text, value, conf, abstained, boxes, cites, trace, t0, cost_calls=None, reasoning=None, page=1):
    res = {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc_id],
           "answer": {"text_md": text, "value": value, "unit": "count" if isinstance(value, int) else None, "confidence": round(conf, 3), "abstained": abstained},
           "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": doc_id, "highlight_item_ids": [], "camera_target_item_id": None}},
           "trace": trace, "route": "symbols",
           "cost": {"usd_total": round(sum(c.get("cost_usd", 0) for c in (cost_calls or [])), 6), "calls": cost_calls or []},
           "latency_ms": int((time.perf_counter() - t0) * 1000)}
    if reasoning:
        res["reasoning"] = reasoning
    return res


def answer_symbols(question: str, doc_ids: list[str], root, t0: float | None = None) -> dict | None:
    """Answer object for a legend question or a count of a symbol the legend names; None when this is not that kind of question."""
    t0 = t0 or time.perf_counter()
    root = Path(root)
    if len(doc_ids or []) != 1 or os.environ.get("SYMBOLS", "1") == "0":
        return None
    doc_id = doc_ids[0]
    want_legend = bool(LEGEND_Q.search(question or ""))
    noun = None if want_legend else question_noun(question)
    if not want_legend and not noun:
        return None
    meta = _doc_meta(doc_id, root)
    if meta.get("kind") in ("ifc", "dxf") or not _pages(doc_id, root):
        return None
    trace = [_step("route", "legend symbols" if want_legend else f"count legend symbol: {noun}")]
    legends = _doc_legends(doc_id, root)
    if not legends:
        if not want_legend:
            return None     # not our question after all: the other routes keep it
        txt = ("I could not find a legend on this drawing, so I cannot say what its symbols mean. "
               "I can still count the kinds I detect without one: doors, windows, toilets, sinks, showers and bathtubs.")
        trace.append(_step("legend", "no block of labels with a symbol beside each found on any page"))
        return _obj(question, doc_id, txt, None, 0.0, True, [], [], trace, t0)
    if want_legend:
        return _legend_answer(question, doc_id, root, legends, trace, t0)
    # count: the legend entry (any page) whose label matches the noun, counted on every page
    best, best_s = [], 0.0
    for p, lg in legends:
        for e in lg["entries"]:
            if e["kind"] != "symbol":
                continue
            s = target_score(noun, e["label"])
            if s > best_s + 1e-9:
                best, best_s = [(p, lg, e)], s
            elif s >= best_s - 1e-9 and s > 0:
                best.append((p, lg, e))
    if best_s < 0.5:
        return None
    return _count_answer(question, doc_id, root, noun, best, legends, trace, t0)


def _legend_answer(question, doc_id, root, legends, trace, t0):
    lines, boxes, cites = [], [], []
    total = 0
    for p, lg in legends:
        for e in lg["entries"]:
            total += 1
            lines.append(f"- {e['label']}" + ("" if e["kind"] == "symbol" else " (a line style, not a countable symbol)"))
    shown = lines[:14]
    n = 0
    for p, lg in legends:
        for e in lg["entries"]:
            if n >= 14:
                break
            n += 1
            boxes.append({"item_id": f"legend-{p}-{e['id']}", "page": p, "bbox_px": list(e["symbol_bbox"]), "label": str(n)})
            cites.append({"n": n, "doc_id": doc_id, "page": p, "kind": "region", "bbox_px": list(e["symbol_bbox"]), "item_ids": [boxes[-1]["item_id"]], "quote": e["label"]})
    shown = [f"{ln} [{i}]" for i, ln in enumerate(shown, 1)]
    more = f"\n- and {total - len(shown)} more" if total > len(shown) else ""
    txt = f"**The legend lists {total} {'entry' if total == 1 else 'entries'}.**\n" + "\n".join(shown) + more
    reasoning = {"steps": [{"kind": "read", "title": "Read", "text": f"A legend block with {total} labelled symbols was found (text read from the sheet, a shape beside each label)",
                            "cite": 1, "ok": None}],
                 "confidence": {"label": "Cross-checked", "pct": 82, "reason": "Printed legend text and the shape drawn beside it.", "improve": None}}
    trace.append(_step("legend", f"{total} entries on page(s) {sorted({p for p, _ in legends})}"))
    return _obj(question, doc_id, txt, total, 0.82, False, boxes, cites, trace, t0, reasoning=reasoning)


def _count_answer(question, doc_id, root, noun, entries, legends, trace, t0):
    pages = _pages(doc_id, root)
    budget = {"calls": 0, "usd": 0.0, "models": set()}
    agg = {"counts": {}, "boxes": [], "possible": [], "checked": {"sampled": 0, "agree": 0, "uncertain": 0, "confirmed": 0, "rejected": 0}, "notes": [], "weak": False}
    legend_page, legend_img = entries[0][0], None
    for p in pages:
        img = root / doc_id / f"page-{p}.png"
        # every entry that matched, counted on this page against the legend it was read from
        by_legend: dict[int, list] = {}
        for lp, lg, e in entries:
            by_legend.setdefault(lp, [lg, []])[1].append(e)
        for lp, (lg, es) in by_legend.items():
            sub = dict(lg)
            sub["entries"] = es
            sub["regions"] = lg.get("regions") or []
            try:
                r = count_symbols(img, legend=sub, verify=True, budget=budget)
            except Exception as ex:  # noqa: BLE001
                agg["notes"].append(f"page {p}: {type(ex).__name__}")
                continue
            for b in r["boxes"]:
                b["page"] = p
                agg["boxes"].append(b)
            for b in r["possible"]:
                b["page"] = p
                agg["possible"].append(b)
            for k, v in r["counts"].items():
                agg["counts"][k] = agg["counts"].get(k, 0) + v
            for k in ("sampled", "agree", "uncertain", "confirmed", "rejected"):
                agg["checked"][k] += r["checked"][k]
            agg["weak"] = agg["weak"] or any(e.get("weak") for e in r["legend_used"]["entries"])
            agg["notes"] += [n for n in r["notes"] if n not in agg["notes"]]
    boxes_in = agg["boxes"]
    for k, b in enumerate(sorted(boxes_in, key=lambda b: (b["page"], b["n"])), 1):
        b["n"] = k
    n = len(boxes_in)
    label = entries[0][2]["label"] if len({e["label"] for _, _, e in entries}) == 1 else noun
    lg_page = legend_page
    conf_label, pct = _conf_label(agg["checked"], n, agg["weak"])
    cost_calls = [{"task": "symbols_verify", "provider": "vision", "model": ", ".join(sorted(m for m in budget["models"] if m)) or "", "cost_usd": round(budget["usd"], 6)}] if budget["calls"] else []
    trace.append(_step("legend", f"legend symbol \"{label}\" on page {lg_page}"))
    trace.append(_step("template", f"template match on {len(pages)} page(s): {n} counted, {len(agg['possible'])} possible, {agg['checked']['uncertain']} uncertain sent to the model check"))
    if budget["calls"]:
        trace.append(_step("check", f"model check: {agg['checked']['agree']} of {agg['checked']['sampled']} sampled strong matches agreed, "
                                    f"{agg['checked']['confirmed']} uncertain confirmed, {agg['checked']['rejected']} dropped", 0, ", ".join(sorted(m for m in budget["models"] if m)), budget["usd"]))
    page_of = {b["page"] for b in boxes_in}
    bx = [{"item_id": f"sym-{b['page']}-{b['n']}", "page": b["page"], "bbox_px": b["bbox_px"], "label": str(b["n"])} for b in boxes_in]
    cites = []
    if bx:
        xs = [b["bbox_px"] for b in bx]
        cites.append({"n": 1, "doc_id": doc_id, "page": bx[0]["page"], "kind": "region", "bbox_px": [min(a[0] for a in xs), min(a[1] for a in xs), max(a[2] for a in xs), max(a[3] for a in xs)],
                      "item_ids": [b["item_id"] for b in bx], "quote": label})
    e0 = entries[0][2]
    cites.append({"n": len(cites) + 1, "doc_id": doc_id, "page": lg_page, "kind": "region", "bbox_px": list(e0["symbol_bbox"]), "item_ids": [], "quote": f"Legend: {label}"})
    if n == 0:
        txt = f"I found **no \"{label}\"** symbols on this drawing, although the legend defines one. [{cites[-1]['n']}]"
        if agg["possible"]:
            txt += f" There are {len(agg['possible'])} faint look-alikes I could not confirm."
        return _obj(question, doc_id, txt, 0, 0.5, False, [], cites[-1:], trace, t0, cost_calls)
    per = [f"- {k}: {v}" for k, v in agg["counts"].items() if len(agg["counts"]) > 1]
    where = f"page{'s' if len(page_of) > 1 else ''} {', '.join(str(p) for p in sorted(page_of))}" if len(pages) > 1 else "this sheet"
    bullets = [f"- Symbol matched to the legend entry \"{label}\" ({'page ' + str(lg_page) if len(pages) > 1 else 'on this sheet'}) [{cites[-1]['n']}]."]
    if budget["calls"] and agg["checked"]["sampled"]:
        bullets.append(f"- Second look by a vision model agreed on {agg['checked']['agree']} of {agg['checked']['sampled']} checked.")
    elif not budget["calls"]:
        bullets.append("- Template matching only; the model check was not available.")
    if agg["possible"]:
        bullets.append(f"- {len(agg['possible'])} further look-alike{'s' if len(agg['possible']) != 1 else ''} not counted because they could not be confirmed.")
    bullets += per
    txt = f"There {'is' if n == 1 else 'are'} **{n} \"{label}\"** on {where}. [1]\n\n" + "\n".join(bullets[:4])
    improve = None if conf_label != "Estimate" else "Check the numbered boxes against the legend symbol, or ask for a count of a single symbol."
    reasoning = {"steps": [
        {"kind": "read", "title": "Read", "text": f"Legend entry \"{label}\" and the shape drawn beside it", "cite": cites[-1]["n"], "ok": None},
        {"kind": "found", "title": "Found", "text": f"{n} matching symbol{'s' if n != 1 else ''} on {where}, each boxed and numbered", "cite": 1, "ok": None},
        {"kind": "checked", "title": "Checked", "text": (f"Template match and model check agree on {agg['checked']['agree']} of {agg['checked']['sampled']} sampled"
                                                         + (f"; {agg['checked']['confirmed']} weak match(es) confirmed, {agg['checked']['rejected']} dropped" if agg["checked"]["uncertain"] else ""))
                    if agg["checked"]["sampled"] else "Template match only; no model check", "cite": None, "ok": True if agg["checked"]["sampled"] and agg["checked"]["agree"] == agg["checked"]["sampled"] else None},
    ], "confidence": {"label": conf_label, "pct": pct,
                      "reason": "Matched to the legend by shape" + ("; a vision model re-checked a sample" if agg["checked"]["sampled"] else "; not model-checked") + ".",
                      "improve": improve}}
    return _obj(question, doc_id, txt, n, pct / 100, False, bx, cites, trace, t0, cost_calls, reasoning)
