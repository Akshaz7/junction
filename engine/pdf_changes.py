"""D-14: revision diff of two PDF versions of a sheet (raster + text layer; no model call, cost 0).

  compare_docs(doc_a, doc_b, art=None)        -> result dict (see below), not cached
  compare_versions(series, i, art=None)       -> cached diff of series["versions"][i] -> [i+1]; file
                                                 artifacts/series/diffs/<series_id>--<i+1>-<i+2>.json
  cached(series_id, i, art=None)              -> the cached result or None (stdlib only: the deployed API reads this)

Algorithm per matched page pair (pages matched by index when the counts agree, else greedily by text/thumbnail similarity):
  1. Load the page images the pipeline already wrote (artifacts/<doc>/page-N.png; same pixel frame the web uses), grey.
  2. Work at <= 2400 px: ink = dark pixels. Translation between versions by phase correlation; kept only when it lowers
     the amount of mismatching ink (re-plotted PDFs drift by a few px).
  3. added = ink of B not within 2 px of ink of A; removed = ink of A not within 2 px of ink of B (anti-aliasing and
     sub-pixel drift vanish). Both are merged with a morphological close and split into connected regions; tiny regions drop.
  4. Region kind: type "added" (ink almost only in B), "removed", else "modified". Description from the text layer
     (text-N.json words inside the region, old vs new), else a plain "changed region" sentence.
Result: {"doc_a","doc_b","source":"pdf-diff","generated_for_demo":false,"note","pages":[{page_a,page_b,image,image_v1,shift_px,n_changes}],
         "changes":[{change_id,type,kind:"region"|"page",description,v1_item:null,v2_item:null,bbox_px_v1,bbox_px_v2,
                     page,page_v1,page_v2,text_old,text_new,ink_px}]}  (same fields engine/changes.py produces + page info;
bbox_px_v1 is in the page-image frame of version A, bbox_px_v2 in that of version B; null on the side that has no such region).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WORK_MAX = 2400
INK_LEVEL = 200
TOL = 5            # dilation kernel (working px): ink within ~2 px counts as the same ink
MERGE = 35         # close kernel (working px): nearby marks form one region
MIN_INK = 40       # working px of changed ink below which a region is noise
MIN_BOX = 8
MAX_CHANGES_PER_PAGE = 25
SHIFT_MAX_FRAC = 0.03


def _art(art):
    import os
    return Path(art or os.environ.get("ARTIFACTS_DIR") or Path(__file__).resolve().parent.parent / "artifacts")


def diff_path(series_id: str, i: int, art=None) -> Path:
    return _art(art) / "series" / "diffs" / f"{series_id}--{i + 1}-{i + 2}.json"


def cached(series_id: str, i: int, art=None) -> dict | None:
    try:
        return json.loads(diff_path(series_id, i, art).read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- inputs
def _pages_info(doc_dir: Path) -> list[dict]:
    try:
        return json.loads((doc_dir / "pages.json").read_text()).get("pages", [])
    except (OSError, ValueError):
        return []


def _load_gray(doc_id: str, page: int, art: Path):
    import cv2
    p = art / doc_id / f"page-{page}.png"
    if p.is_file():
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            return img
    return _render(doc_id, page, art)


def _render(doc_id: str, page: int, art: Path):
    """Fallback when the page image is not built: render the source PDF at 150 dpi with pypdfium2."""
    import numpy as np
    import pypdfium2 as pdfium
    from pipeline.series import source_path
    rec = {"doc_id": doc_id, "files": _doc_files(doc_id, art)}
    src = source_path(rec)
    if src is None:
        return None
    pdf = pdfium.PdfDocument(str(src))
    bm = pdf[page - 1].render(scale=150 / 72, grayscale=True)
    return np.asarray(bm.to_numpy()).reshape(bm.height, bm.width)


def _doc_files(doc_id: str, art: Path) -> dict:
    try:
        return json.loads((art / doc_id / "doc.json").read_text()).get("files") or {}
    except (OSError, ValueError):
        return {}


def load_words(doc_id: str, page: int, art: Path) -> list[dict]:
    """Words with bbox_px in the page-image frame: artifacts/<doc>/text-N.json (pipeline), else text.json, else pdfminer."""
    for name, pick in ((f"text-{page}.json", None), ("text.json", page)):
        try:
            d = json.loads((art / doc_id / name).read_text())
        except (OSError, ValueError):
            continue
        if pick is not None:  # per-document text.json: {"pages": [{"page": n, "words": [...]}]}
            d = next((p for p in d.get("pages", []) if p.get("page") == pick), None)
            if d is None:
                continue
        words = d.get("words")
        if isinstance(words, list):
            return [w for w in words if w.get("bbox_px") and str(w.get("text", "")).strip()]
    return _pdfminer_words(doc_id, page, art)


def _pdfminer_words(doc_id: str, page: int, art: Path) -> list[dict]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTChar, LTTextContainer, LAParams
        from pipeline.series import source_path
        src = source_path({"doc_id": doc_id, "files": _doc_files(doc_id, art)})
        if src is None:
            return []
        pg = next(iter(extract_pages(str(src), page_numbers=[page - 1], laparams=LAParams())), None)
        if pg is None:
            return []
        k = 150 / 72
        out = []
        for box in pg:
            if not isinstance(box, LTTextContainer):
                continue
            for line in box:
                for tok in re.finditer(r"\S+", line.get_text()):
                    chars = [c for c in line if isinstance(c, LTChar)][tok.start():tok.end()]
                    if not chars:
                        continue
                    x0 = min(c.x0 for c in chars); x1 = max(c.x1 for c in chars)
                    y0 = min(c.y0 for c in chars); y1 = max(c.y1 for c in chars)
                    out.append({"text": tok.group(), "bbox_px": [x0 * k, (pg.height - y1) * k, x1 * k, (pg.height - y0) * k]})
        return out
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- page matching
def _sig_words(words: list[dict]) -> set[str]:
    return {re.sub(r"\W", "", w["text"].lower()) for w in words} - {""}


def _thumb(img):
    import cv2
    return cv2.resize(img, (48, 48), interpolation=cv2.INTER_AREA).astype("float32").ravel()


def _similarity(ga, gb, wa, wb) -> float:
    import numpy as np
    sa, sb = _sig_words(wa), _sig_words(wb)
    if len(sa) >= 12 and len(sb) >= 12:
        return len(sa & sb) / len(sa | sb)
    ta, tb = _thumb(ga), _thumb(gb)
    ta, tb = ta - ta.mean(), tb - tb.mean()
    d = float(np.linalg.norm(ta) * np.linalg.norm(tb))
    return float(ta @ tb / d) if d > 0 else 0.0


def match_pages(na: int, nb: int, sim) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """-> (pairs of 1-based page numbers, unmatched pages of A, unmatched pages of B)."""
    if na == nb:
        return [(i, i) for i in range(1, na + 1)], [], []
    cand = sorted(((sim(i, j), i, j) for i in range(1, na + 1) for j in range(1, nb + 1)), reverse=True)
    ua, ub, pairs = set(), set(), []
    for s, i, j in cand:
        if s < 0.3:
            break
        if i in ua or j in ub:
            continue
        ua.add(i); ub.add(j); pairs.append((i, j))
    pairs.sort()
    return pairs, [i for i in range(1, na + 1) if i not in ua], [j for j in range(1, nb + 1) if j not in ub]


# ---------------------------------------------------------------- pixel diff
def _ink(gray, scale):
    import cv2
    g = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    return g, (g < INK_LEVEL).astype("uint8")


def _estimate_shift(ga, gb, ia, ib):
    """(sx, sy) in working px such that moving B by (+sx, +sy) lines it up with A; (0, 0) unless it clearly helps."""
    import cv2
    import numpy as np
    h, w = ga.shape
    fa, fb = ((255 - g).astype("float32") for g in (ga, gb))
    try:
        (dx, dy), resp = cv2.phaseCorrelate(fa, fb, cv2.createHanningWindow((w, h), cv2.CV_32F))
    except cv2.error:
        return 0.0, 0.0
    # phaseCorrelate returns the shift of B relative to A; moving B by -d aligns it
    sx, sy = -dx, -dy
    if resp < 0.03 or (abs(sx) < 0.5 and abs(sy) < 0.5) or abs(sx) > SHIFT_MAX_FRAC * w or abs(sy) > SHIFT_MAX_FRAC * h:
        return 0.0, 0.0
    k = np.ones((TOL, TOL), np.uint8)

    def cost(ib_):
        return int((ib_ & ~cv2.dilate(ia, k)).sum() + (ia & ~cv2.dilate(ib_, k)).sum())

    M = np.float32([[1, 0, sx], [0, 1, sy]])
    moved = cv2.warpAffine(ib, M, (w, h), flags=cv2.INTER_NEAREST)
    return (sx, sy) if cost(moved) < 0.9 * cost(ib) else (0.0, 0.0)


def _components(mask, added, removed, kernel, offset=(0, 0), out=None, big_frac=0.25):
    """Close `mask`, split into regions; a region covering > big_frac of the page is split again with a smaller kernel."""
    import cv2
    import numpy as np
    out = [] if out is None else out
    ox, oy = offset
    merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(merged)
    page_area = added.shape[0] * added.shape[1]
    for c in range(1, n):
        x, y, w, h, _ = stats[c]
        m = lab[y:y + h, x:x + w] == c
        if w * h > big_frac * page_area and kernel > 9:
            sub = np.zeros_like(mask)
            sub[y:y + h, x:x + w] = mask[y:y + h, x:x + w] & m
            _components(sub, added, removed, max(9, kernel // 3), offset, out, big_frac)
            continue
        ad = int(added[y:y + h, x:x + w][m].sum())
        rm = int(removed[y:y + h, x:x + w][m].sum())
        if w * h > big_frac * page_area and (ad + rm) < 0.03 * w * h:
            continue  # a thin outline spanning the sheet (drawing border moved a few px), not a content change
        if ad + rm < MIN_INK or w < MIN_BOX or h < MIN_BOX:
            continue
        out.append((int(x), int(y), int(x + w), int(y + h), ad, rm))
    return out


def _regions(ia, ib):
    """-> (regions [(x0, y0, x1, y1, added_px, removed_px)] in working px of A's frame, total number found)."""
    import cv2
    import numpy as np
    k = np.ones((TOL, TOL), np.uint8)
    added = ib & ~cv2.dilate(ia, k)
    removed = ia & ~cv2.dilate(ib, k)
    union = added | removed
    long_len = max(80, int(0.18 * max(ia.shape)))  # sheet border / title-block rules shifted by a few px
    lines = cv2.dilate(cv2.morphologyEx(union, cv2.MORPH_OPEN, np.ones((1, long_len), np.uint8))
                       | cv2.morphologyEx(union, cv2.MORPH_OPEN, np.ones((long_len, 1), np.uint8)), k)
    union = union & ~lines
    added, removed = added & ~lines, removed & ~lines
    out = _components(union, added, removed, MERGE)
    out.sort(key=lambda r: r[4] + r[5], reverse=True)
    return out[:MAX_CHANGES_PER_PAGE], len(out)


def _in_box(words, box):
    x0, y0, x1, y1 = box
    out = []
    for w in words:
        b = w["bbox_px"]
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append(w)
    out.sort(key=lambda w: (round(w["bbox_px"][1] / 25), w["bbox_px"][0]))
    return [str(w["text"]).strip() for w in out]


def _text_delta(wa: list[str], wb: list[str]) -> tuple[list[str], list[str]]:
    """Multiset difference, order kept: (words only in A, words only in B)."""
    from collections import Counter
    ca, cb = Counter(wa), Counter(wb)
    only_a, only_b = [], []
    for w in wa:
        if ca[w] > cb[w]:
            only_a.append(w)
            ca[w] -= 1
    ca, cb = Counter(wa), Counter(wb)
    for w in wb:
        if cb[w] > ca[w]:
            only_b.append(w)
            cb[w] -= 1
    return only_a, only_b


def _short(ws: list[str], n: int = 12) -> str:
    s = " ".join(ws[:n])
    return s + (" …" if len(ws) > n else "")


def _describe(typ: str, old: list[str], new: list[str]) -> str:
    if old and new:
        return f"Text changed from \"{_short(old)}\" to \"{_short(new)}\"."
    if new:
        return f"Text added: \"{_short(new)}\"."
    if old:
        return f"Text removed: \"{_short(old)}\"."
    return {"added": "Content added in this region (no text change).",
            "removed": "Content removed from this region (no text change)."}.get(typ, "Changed region (no text change).")


def diff_page(ga, gb, words_a, words_b) -> tuple[list[dict], dict]:
    """ga, gb: grey page images (any size). -> (changes with bbox in each version's frame, info)."""
    import cv2
    ha, wa = ga.shape
    hb, wb = gb.shape
    info = {"image": {"w": int(wb), "h": int(hb)}, "image_v1": {"w": int(wa), "h": int(ha)}, "shift_px": [0, 0]}
    if abs(wa - wb) > 0.02 * wa or abs(ha - hb) > 0.02 * ha:
        if abs(wa / ha - wb / hb) > 0.02 * wa / ha:
            info["note"] = "page sizes differ; compared as a whole"
            return [{"type": "modified", "kind": "page", "description": "The sheet size changed between the two versions.",
                     "bbox_px_v1": [0, 0, int(wa), int(ha)], "bbox_px_v2": [0, 0, int(wb), int(hb)],
                     "text_old": None, "text_new": None, "ink_px": 0}], info
        gb_cmp = cv2.resize(gb, (wa, ha), interpolation=cv2.INTER_AREA)  # same shape, different dpi
    else:
        gb_cmp = cv2.resize(gb, (wa, ha), interpolation=cv2.INTER_AREA) if gb.shape != ga.shape else gb
    sx_f = wb / wa  # frame B px per frame A px (1.0 unless resized)
    sy_f = hb / ha
    scale = min(1.0, WORK_MAX / max(wa, ha))
    a_w, ia = _ink(ga, scale)
    b_w, ib = _ink(gb_cmp, scale)
    sx, sy = _estimate_shift(a_w, b_w, ia, ib)
    if sx or sy:
        import numpy as np
        M = np.float32([[1, 0, sx], [0, 1, sy]])
        ib = cv2.warpAffine(ib, M, (ia.shape[1], ia.shape[0]), flags=cv2.INTER_NEAREST)
    info["shift_px"] = [round(sx / scale, 1), round(sy / scale, 1)]
    pad = 6
    changes = []
    regions, n_found = _regions(ia, ib)
    info["n_regions_found"] = n_found
    for x0, y0, x1, y1, ad, rm in regions:
        a_box = [max(0, int((x0 - pad) / scale)), max(0, int((y0 - pad) / scale)),
                 min(wa, int((x1 + pad) / scale)), min(ha, int((y1 + pad) / scale))]
        ox, oy = -sx / scale, -sy / scale  # A-frame -> B-frame offset (B moved by +s to align, so B = A - s)
        b_box = [max(0, int((a_box[0] + ox) * sx_f)), max(0, int((a_box[1] + oy) * sy_f)),
                 min(wb, int((a_box[2] + ox) * sx_f)), min(hb, int((a_box[3] + oy) * sy_f))]
        typ = "added" if ad > 2 * rm else "removed" if rm > 2 * ad else "modified"
        old, new = _text_delta(_in_box(words_a, a_box), _in_box(words_b, b_box))
        changes.append({"type": typ, "kind": "region", "description": _describe(typ, old, new),
                        "bbox_px_v1": None if typ == "added" else a_box, "bbox_px_v2": None if typ == "removed" else b_box,
                        "text_old": " ".join(old) or None, "text_new": " ".join(new) or None, "ink_px": int((ad + rm) / scale ** 2)})
    changes.sort(key=lambda c: ((c["bbox_px_v1"] or c["bbox_px_v2"])[1] // 400, (c["bbox_px_v1"] or c["bbox_px_v2"])[0]))
    return changes, info


# ---------------------------------------------------------------- documents
def compare_docs(doc_a: str, doc_b: str, art=None) -> dict:
    art = _art(art)
    na = len(_pages_info(art / doc_a)) or 0
    nb = len(_pages_info(art / doc_b)) or 0
    result = {"doc_a": doc_a, "doc_b": doc_b, "source": "pdf-diff", "generated_for_demo": False, "pages": [], "changes": []}
    if not na or not nb:
        result["note"] = "page images are not built for both versions"
        return result
    gray: dict = {}
    words: dict = {}

    def g(doc, p):
        if (doc, p) not in gray:
            gray[(doc, p)] = _load_gray(doc, p, art)
        return gray[(doc, p)]

    def w(doc, p):
        if (doc, p) not in words:
            words[(doc, p)] = load_words(doc, p, art)
        return words[(doc, p)]

    pairs, only_a, only_b = match_pages(na, nb, lambda i, j: _similarity(g(doc_a, i), g(doc_b, j), w(doc_a, i), w(doc_b, j)))
    changes: list[dict] = []
    for pa, pb in pairs:
        ga, gb = g(doc_a, pa), g(doc_b, pb)
        if ga is None or gb is None:
            continue
        page_changes, info = diff_page(ga, gb, w(doc_a, pa), w(doc_b, pb))
        for c in page_changes:
            c.update(page=pb, page_v1=pa, page_v2=pb)
        changes += page_changes
        result["pages"].append({"page_a": pa, "page_b": pb, **info, "n_changes": len(page_changes)})
    for pa in only_a:
        ga = g(doc_a, pa)
        if ga is not None:
            changes.append({"type": "removed", "kind": "page", "description": f"Page {pa} of the earlier version has no counterpart in the later one.",
                            "bbox_px_v1": [0, 0, int(ga.shape[1]), int(ga.shape[0])], "bbox_px_v2": None, "text_old": None,
                            "text_new": None, "ink_px": 0, "page": pa, "page_v1": pa, "page_v2": None})
    for pb in only_b:
        gb = g(doc_b, pb)
        if gb is not None:
            changes.append({"type": "added", "kind": "page", "description": f"Page {pb} is new in the later version.",
                            "bbox_px_v1": None, "bbox_px_v2": [0, 0, int(gb.shape[1]), int(gb.shape[0])], "text_old": None,
                            "text_new": None, "ink_px": 0, "page": pb, "page_v1": None, "page_v2": pb})
    for n, c in enumerate(changes, 1):
        c["change_id"] = f"c{n}"
        c["v1_item"] = c["v2_item"] = None
    result["changes"] = changes
    result["note"] = "Compared by the PDF revision diff (raster ink + text layer, no model call)."
    return result


def compare_versions(series: dict, i: int, art=None, force: bool = False) -> dict:
    sid = series["series_id"]
    a, b = series["versions"][i]["doc_id"], series["versions"][i + 1]["doc_id"]
    if not force:
        c = cached(sid, i, art)
        if c and c.get("doc_a") == a and c.get("doc_b") == b:
            return c
    r = compare_docs(a, b, art)
    r["series_id"] = sid
    p = diff_path(sid, i, art)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(r))
    return r
