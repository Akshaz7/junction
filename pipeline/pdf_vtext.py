"""Read text that a CAD plot drew as strokes (vectorised single-stroke fonts: AutoCAD txt/simplex/romans plots).

    words(page, *, budget_s=30.0, region=None) -> [{"text", "bbox", "angle", "conf", "src": "vtext"}]

page is a pdf_mep page (paths with i0/i1 into xy, stroke/fill colours 0-255; page points, top-left, y down).
Many MEP sheets carry their duct sizes ("Ø180", "400x200"), airflows ("-25 l/s") and terminal tags ("T2-125") only
as strokes, so the PDF text layer is empty of them. A plotted CAD font draws every copy of a character with the
same strokes, so the sheet is read with a glyph table it teaches itself:
  1. glyph strokes: open, stroked, non-grey paths at most GLYPH_MAX_MM on paper (the screened neutral-grey underlay
     is the architect's sheet, with its own text layer, and is skipped)
  2. text clusters: glyph strokes whose boxes lie within LINK x glyph size of each other; inside a cluster,
     strokes whose boxes overlap form one character unit ("+", "x", "Ø" = 2 strokes)
  3. learn: a budgeted sample of clusters is drawn upright (vertical ones turned both ways) into mosaics and read
     by the tesseract binary (one call per mosaic, TSV); a read word whose character count equals its unit count
     votes each unit's shape -> character
  4. decode every cluster by nearest shape in the table (in its better orientation); lines / words by spacing
No tesseract on PATH, a timeout or any error -> [] (callers fall back to the text layer). Paper-size rules only
(mm on paper through 72/25.4 pt per mm); no per-document constants.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter

import numpy as np

PT_PER_MM = 72 / 25.4
GLYPH_MAX_MM = 4.5          # a glyph (or a glyph stroke) is at most this tall/wide on paper
GLYPH_MIN_MM = 0.3          # specks below this do not set the link distance
LINK = 0.55                 # glyph boxes closer than this x glyph size belong to one text cluster
CL_MAX_MM = 90.0            # longest text cluster kept (a long run of linked "glyphs" is hatch / dash linetype)
CL_MAX_UNITS = 160          # most character units in one cluster
PX_PER_MM = 10.0            # OCR raster: 2.5 mm text -> 25 px cap height
SHAPE_TOL = 0.06            # two units are the same character when their points agree within this x letter height
LEARN_SHARE = 0.4           # share of the budget spent on the first learning round (the rest: unknown units)
WHITELIST = "0123456789xX/+-.,=ØølsmaPDNhHABCEFGIJKLMORSTUVWYZ"


def _grey(c) -> bool:
    return c is not None and max(c) - min(c) <= 12 and 60 <= c[0] <= 235


def glyph_paths(page: dict):
    """-> (idx array of glyph path ids, boxes N x 4 page pt). Vectorised over all paths."""
    paths, xy = page["paths"], page["xy"]
    n = len(paths)
    if n == 0 or len(xy) == 0:
        return np.zeros(0, int), np.zeros((0, 4))
    i0 = np.fromiter((p["i0"] for p in paths), int, n)
    i1 = np.fromiter((p["i1"] for p in paths), int, n)
    ok = np.fromiter((p.get("stroke") is not None and not _grey(p["stroke"]) and p.get("fill") is None
                      for p in paths), bool, n) & (i1 - i0 >= 2)
    k = np.flatnonzero(ok)
    if not len(k):
        return np.zeros(0, int), np.zeros((0, 4))
    k = k[np.argsort(i0[k], kind="stable")]
    st, en = i0[k], i1[k]
    mn = np.minimum.reduceat(xy, st, axis=0)
    mx = np.maximum.reduceat(xy, st, axis=0)
    nxt = np.r_[st[1:], len(xy)]
    for j in np.flatnonzero(nxt != en):          # reduceat ran past the path's end: recompute exactly
        P = xy[st[j]:en[j]]
        mn[j], mx[j] = P.min(0), P.max(0)
    B = np.c_[mn, mx]
    keep = np.maximum(B[:, 2] - B[:, 0], B[:, 3] - B[:, 1]) <= GLYPH_MAX_MM * PT_PER_MM
    return k[keep], B[keep]


def _components(n, i, j) -> list[np.ndarray]:
    """Connected components of n nodes with edges (i, j) -> index groups."""
    if not n:
        return []
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    g = coo_matrix((np.ones(len(i), bool), (np.asarray(i, int), np.asarray(j, int))), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    order = np.argsort(lab, kind="stable")
    return np.split(order, np.flatnonzero(np.diff(lab[order])) + 1)


def _clusters(B: np.ndarray) -> list[np.ndarray]:
    """Glyph boxes within LINK x the larger glyph size of each other -> groups of indices (KD-tree on centres)."""
    n = len(B)
    if n == 0:
        return []
    from scipy.spatial import cKDTree
    ext = np.maximum(np.maximum(B[:, 2] - B[:, 0], B[:, 3] - B[:, 1]), GLYPH_MIN_MM * PT_PER_MM)
    cen = (B[:, :2] + B[:, 2:]) / 2
    hd = np.hypot(B[:, 2] - B[:, 0], B[:, 3] - B[:, 1]) / 2
    pr = cKDTree(cen).query_pairs(2 * float(hd.max()) + LINK * float(ext.max()), output_type="ndarray")
    i, j = pr[:, 0], pr[:, 1]
    t = LINK * np.maximum(ext[i], ext[j])
    ok = (B[j, 0] - B[i, 2] <= t) & (B[i, 0] - B[j, 2] <= t) & (B[j, 1] - B[i, 3] <= t) & (B[i, 1] - B[j, 3] <= t)
    return _components(n, i[ok], j[ok])


def _up(P, rot, box):
    """Page pt -> upright frame of a cluster box (pt; x along the reading direction, y down the letters)."""
    x0, y0, x1, y1 = box
    P = np.asarray(P, float)
    if rot == 90:                # text running up the page
        return np.c_[y1 - P[:, 1], P[:, 0] - x0]
    if rot == 270:               # text running down the page
        return np.c_[P[:, 1] - y0, x1 - P[:, 0]]
    return np.c_[P[:, 0] - x0, P[:, 1] - y0]


class _Cluster:
    __slots__ = ("cid", "pids", "box", "units", "vertical", "_sh")

    def __init__(self, cid, pids, boxes, box):
        self.cid, self.pids, self.box, self._sh = cid, pids, box, {}
        w, h = box[2] - box[0], box[3] - box[1]
        self.vertical = h > 1.15 * w
        # character units: strokes whose boxes overlap or touch (a 2-stroke "+", "x", "Ø")
        bx = np.asarray(boxes, float)
        e = 0.04 * np.maximum(np.maximum(bx[:, 2] - bx[:, 0], bx[:, 3] - bx[:, 1]), 0.5)
        ox = np.minimum(bx[:, None, 2], bx[None, :, 2]) - np.maximum(bx[:, None, 0], bx[None, :, 0])
        oy = np.minimum(bx[:, None, 3], bx[None, :, 3]) - np.maximum(bx[:, None, 1], bx[None, :, 1])
        ee = np.maximum(e[:, None], e[None, :])
        i, j = np.nonzero(np.triu((ox > -ee) & (oy > -ee), 1))
        self.units = [[int(pids[k]) for k in sorted(g)] for g in _components(len(pids), i, j)]

    def is_text(self, page) -> bool:
        """Not a dash / hatch run: text has varied glyphs, a linetype has mostly single straight strokes."""
        P = page["paths"]
        single = sum(1 for u in self.units if len(u) == 1 and P[u[0]]["i1"] - P[u[0]]["i0"] == 2)
        return not (len(self.units) >= 4 and single >= 0.7 * len(self.units))

    def shapes(self, page, rot):
        """Unit shapes in the upright frame, points scaled by the cluster's letter height (one table entry serves
        every text height of the same font)."""
        if rot not in self._sh:
            P, xy = page["paths"], page["xy"]
            allp = [k for u in self.units for k in u]
            Q = _up(np.concatenate([xy[P[k]["i0"]:P[k]["i1"]] for k in allp]), rot, self.box)
            cuts = np.cumsum([P[k]["i1"] - P[k]["i0"] for k in allp])[:-1]
            seg = dict(zip(allp, np.split(Q, cuts)))
            sh = [_unit_shape([seg[k] for k in u]) for u in self.units]
            hl = max(float(np.percentile([b[3] - b[1] for _, _, b in sh], 75)), 1e-6)
            self._sh[rot] = [(sg, P / hl, b) for sg, P, b in sh]
        return self._sh[rot]


def _unit_shape(segs):
    """Upright stroke point arrays of one unit -> (signature, points relative to the unit's box corner, box)."""
    lo = np.min([q.min(0) for q in segs], axis=0)
    hi = np.max([q.max(0) for q in segs], axis=0)
    segs = sorted(segs, key=lambda q: (round(float(q[:, 0].min() - lo[0]), 1), round(float(q[:, 1].min() - lo[1]), 1),
                                       len(q)))
    return tuple(len(q) for q in segs), np.concatenate(segs) - lo, (lo[0], lo[1], hi[0], hi[1])


class _Table:
    """Unit shape -> character votes; lookup by nearest stored shape with the same stroke signature."""

    def __init__(self):
        self.by_sig: dict = {}

    def find(self, sig, pts):
        best, bd = None, SHAPE_TOL
        for ent in self.by_sig.get(sig, ()):
            d = float(np.abs(ent[0] - pts).max())
            if d <= bd:
                best, bd = ent, d
        return best

    def vote(self, sig, pts, ch):
        ent = self.find(sig, pts)
        if ent is None:
            ent = (pts, Counter())
            self.by_sig.setdefault(sig, []).append(ent)
        ent[1][ch] += 1

    def char(self, sig, pts):
        if _is_dia(sig, pts):
            return "Ø"
        ent = self.find(sig, pts)
        return ent[1].most_common(1)[0][0] if ent is not None and ent[1] else None


def _draw(page, c, rot, scale, pad):
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = c.box
    w, h = (x1 - x0) * scale, (y1 - y0) * scale
    W, H = (w, h) if rot == 0 else (h, w)
    im = Image.new("L", (int(W + 2 * pad) + 1, int(H + 2 * pad) + 1), 255)
    d = ImageDraw.Draw(im)
    lw = max(2, int(round(0.25 * PX_PER_MM)))
    for k in c.pids:
        p = page["paths"][k]
        Q = _up(page["xy"][p["i0"]:p["i1"]], rot, c.box) * scale + pad
        d.line([tuple(q) for q in Q.tolist()], fill=0, width=lw)
    return im


def _ocr(img, timeout: float) -> list[dict]:
    exe = shutil.which("tesseract")
    if not exe:
        return []
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, "m.png")
        img.save(fn)
        cmd = [exe, fn, "stdout", "--psm", "6", "-l", "eng", "-c", "tessedit_char_whitelist=" + WHITELIST, "tsv"]
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout
        except (subprocess.TimeoutExpired, OSError):
            return []
    rows = []
    for ln in out.splitlines()[1:]:
        f = ln.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        rows.append({"l": int(f[6]), "t": int(f[7]), "w": int(f[8]), "h": int(f[9]), "conf": float(f[10]),
                     "text": f[11].strip()})
    return rows


def _learn(page, table, items, rot, scale, pad, timeout, max_h=6000) -> int:
    """OCR clusters (one per mosaic row) drawn at rot; words whose char count matches their unit count vote."""
    from PIL import Image
    votes = 0

    def run(cur, y, wmax):
        nonlocal votes
        M = Image.new("L", (wmax, max(y, 1)), 255)
        for c, y_, im in cur:
            M.paste(im, (0, y_))
        rows = _ocr(M, timeout)
        del M
        for c, y_, im in cur:
            sh = c.shapes(page, rot)
            cen = [((b[0] + b[2]) / 2 * scale + pad, (b[1] + b[3]) / 2 * scale + pad + y_) for _, _, b in sh]
            for r in rows:
                if not (y_ <= r["t"] + r["h"] / 2 < y_ + im.height):
                    continue
                txt = _fix(r["text"])
                ins = [i for i, (cx, cy) in enumerate(cen)
                       if r["l"] - 2 <= cx <= r["l"] + r["w"] + 2 and r["t"] - 2 <= cy <= r["t"] + r["h"] + 2]
                if not ins or len(ins) != len(txt):
                    continue
                ins.sort(key=lambda i: cen[i][0])
                for i, ch in zip(ins, txt):
                    if _is_dia(sh[i][0], sh[i][1]):
                        ch = "Ø"
                    table.vote(sh[i][0], sh[i][1], ch)
                    votes += 1
    cur, y, wmax = [], 0, 1
    for c in items:
        im = _draw(page, c, rot, scale, pad)
        if y + im.height > max_h and cur:
            run(cur, y, wmax)
            cur, y, wmax = [], 0, 1
        cur.append((c, y, im))
        y += im.height
        wmax = max(wmax, im.width)
    if cur:
        run(cur, y, wmax)
    return votes


def _decode(page, table, c, rot):
    """-> (words [(text, page bbox)], n units known, n units)."""
    sh = c.shapes(page, rot)
    if not sh:
        return [], 0, 0
    chars = [table.char(s, p) for s, p, _ in sh]
    hl = float(np.percentile([b[3] - b[1] for _, _, b in sh], 75))
    cy = np.array([(b[1] + b[3]) / 2 for _, _, b in sh])
    lines, cur = [], []
    for i in np.argsort(cy, kind="stable"):
        if cur and abs(cy[i] - float(np.mean(cy[cur]))) > 0.5 * hl:
            lines.append(cur)
            cur = []
        cur.append(int(i))
    if cur:
        lines.append(cur)
    groups = []
    for ln in lines:
        ln = sorted(ln, key=lambda i: sh[i][2][0])
        wd = [ln[0]]
        for a, b in zip(ln, ln[1:]):
            if sh[b][2][0] - sh[a][2][2] > 0.55 * hl:
                groups.append(wd)
                wd = []
            wd.append(b)
        groups.append(wd)
    res = []
    for wd in groups:
        txt = "".join(chars[i] or "?" for i in wd)
        P = np.concatenate([page["xy"][page["paths"][k]["i0"]:page["paths"][k]["i1"]] for i in wd for k in c.units[i]])
        res.append((_fix(txt), [float(P[:, 0].min()), float(P[:, 1].min()), float(P[:, 0].max()), float(P[:, 1].max())]))
    return res, sum(ch is not None for ch in chars), len(chars)


def _best_rot(page, table, c):
    best = None
    for r in ((90, 270) if c.vertical else (0,)):
        out = _decode(page, table, c, r)
        if best is None or out[1] > best[0][1]:
            best = (out, r)
    return best


LAST: dict = {}             # last words() call: {"partial", "clusters", "decoded", "learn_s", "s"}
LEARN_MAX = 60              # clusters per orientation in the one learning round (fixed: same table every run)


def words(page: dict, *, budget_s: float = 30.0, region=None, seed: int = 0, max_units: int = CL_MAX_UNITS,
          focus=None, focus_r_pt: float = 0.0) -> list[dict]:
    """Vectorised text on the page as words (see module doc). Never raises; [] when tesseract is missing.
    focus (N x 2 page pt) + focus_r_pt: read only text clusters within focus_r_pt of a focus point (e.g. leader
    ends, duct runs), nearest first. One learning round on a fixed sample (LEARN_MAX per orientation, focus clusters
    first), then decoding in that fixed order until the deadline: LAST["partial"] says whether it stopped early.
    Character units are only built for the clusters actually learned or decoded."""
    t0 = time.time()
    LAST.clear()
    LAST.update(partial=False, clusters=0, decoded=0, learn_s=0.0, s=0.0)
    try:
        if not shutil.which("tesseract"):
            return []
        idx, B = glyph_paths(page)
        if region is not None:
            rx0, ry0, rx1, ry1 = region
            m = (B[:, 0] >= rx0) & (B[:, 2] <= rx1) & (B[:, 1] >= ry0) & (B[:, 3] <= ry1)
            idx, B = idx[m], B[m]
        cmax = CL_MAX_MM * PT_PER_MM
        raw = []    # (cluster id, member indices, box) after the cheap size tests; no unit building yet
        for ci, mem in enumerate(_clusters(B)):
            bb = B[mem]
            box = (bb[:, 0].min(), bb[:, 1].min(), bb[:, 2].max(), bb[:, 3].max())
            w, h = box[2] - box[0], box[3] - box[1]
            if len(mem) < 2 or len(mem) > 4 * max_units or max(w, h) > cmax or max(w, h) < 1.2 * PT_PER_MM:
                continue
            raw.append((ci, mem, box))
        if focus is not None and len(raw):
            F = np.asarray(focus, float).reshape(-1, 2)
            if not len(F):
                return []
            from scipy.spatial import cKDTree
            ctr = np.array([((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, _, b in raw])
            half = np.array([max(b[2] - b[0], b[3] - b[1]) / 2 for _, _, b in raw])
            dist, _ = cKDTree(F).query(ctr)
            dist = np.maximum(dist - half, 0.0)
            order = [int(i) for i in np.argsort(dist, kind="stable") if dist[i] <= focus_r_pt]
            raw = [raw[i] for i in order]
        LAST["clusters"] = len(raw)
        if not raw:
            return []
        made: dict = {}

        def cl(r):
            """the _Cluster of a raw cluster, built once; None when it is not text"""
            ci, mem, box = r
            if ci not in made:
                c = _Cluster(ci, idx[mem], B[mem], box)
                made[ci] = c if 2 <= len(c.units) <= max_units and c.is_text(page) else None
            return made[ci]
        scale, pad = PX_PER_MM / PT_PER_MM, int(1.5 * PX_PER_MM)
        table = _Table()
        left = lambda: budget_s - (time.time() - t0)  # noqa: E731
        rng = np.random.default_rng(seed)
        short = [r for r in raw if len(r[1]) <= 4 * 40]
        pick = list(range(min(len(short), 4 * LEARN_MAX)))              # the nearest focus clusters first ...
        rest = list(range(len(pick), len(short)))
        if rest:                                                         # ... plus a fixed random share of the rest
            pick += [rest[i] for i in rng.permutation(len(rest))[:LEARN_MAX]]
        hz, vt = [], []
        for i in pick:
            c = cl(short[i])
            if c is None:
                continue
            (vt if c.vertical else hz).append(c)
        hz, vt = hz[:LEARN_MAX], vt[:LEARN_MAX]
        learn_end = time.time() + LEARN_SHARE * budget_s           # all learning rounds together
        for items, rot in ((hz, 0), (vt, 90), (vt, 270)):
            if items and learn_end - time.time() > 1:
                _learn(page, table, items, rot, scale, pad, max(1.0, learn_end - time.time()))
        LAST["learn_s"] = round(time.time() - t0, 1)
        res = []
        for r in raw:
            if left() <= 0.5:
                LAST["partial"] = True
                break
            c = cl(r)
            if c is None:
                continue
            (out, k, n), rot = _best_rot(page, table, c)
            LAST["decoded"] += 1
            if k == 0:
                continue
            for txt, bb in out:
                if not txt.strip("?"):
                    continue
                res.append({"text": txt, "bbox": [round(v, 2) for v in bb], "angle": rot,
                            "conf": round(k / max(n, 1), 2), "src": "vtext", "cluster": int(c.cid)})
        return res
    except Exception:  # noqa: BLE001  optional reader
        return []
    finally:
        LAST["s"] = round(time.time() - t0, 1)


def _is_dia(sig, pts) -> bool:
    """The diameter sign of a single-stroke font: a round stroke (>= 8 points, about as wide as tall) crossed by one
    straight diagonal stroke spanning it."""
    if len(sig) != 2 or sorted(sig)[0] != 2 or sorted(sig)[1] < 8:
        return False
    a = 0 if sig[0] == 2 else 1
    off = 0 if a == 0 else sig[0]
    s0, s1 = pts[off], pts[off + 1]
    ring = np.delete(pts, [off, off + 1], axis=0)
    w, h = np.ptp(ring, axis=0)
    if min(w, h) <= 0 or max(w, h) / min(w, h) > 1.6:
        return False
    d = np.abs(s1 - s0)
    return d[0] >= 0.6 * w and d[1] >= 0.6 * h


_DIA = re.compile(r"^[ØøO0@QD](\d{2,4})$")


def _fix(t: str) -> str:
    """Single-stroke-font OCR repairs: a diameter sign read as O/0/@ before a 2-4 digit size -> Ø; I/s -> l/s."""
    t = t.replace("×", "x").replace("ø", "Ø")
    m = _DIA.match(t)
    if m and t[0] != "Ø" and (t[0] != "0" or len(m.group(1)) >= 3):
        t = "Ø" + m.group(1)
    if t in ("I/s", "1/s", "|/s"):
        t = "l/s"
    return t
