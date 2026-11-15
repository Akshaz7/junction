"""Second pass over pdf_mep duct runs and air terminals: drop false runs, attach printed sizes, split dampers out.

    refine(ducts, terminals, page, mpt) -> (ducts, terminals, report)

ducts / terminals are the dicts pdf_mep.ducts() / terminals() / symbol_terminals() return (page points, top-left,
y down); page is a pdf_mep page (paths, xy, words); mpt the detection scale (m per pt). Never raises: on any error
the input comes back unchanged with report["error"].

Rules (sizes on the sheet in metres through mpt, symbol/text sizes in paper mm; no per-document constants):
  text      words inside the run that are not size labels (a frame around notes, a table cell, a tag box)
  leaders   > 3 strokes cross the whole band (both sides) inside the run: a corridor/note band crossed by leaders
  hatch     >= 4 parallel oblique strokes inside the band, evenly repeated: a hatched area, not an empty duct
  orphan    a long thin run (>= 8 m, < 0.2 m wide) with no size label and no other run touching it: a
            reservation / corridor band
A run carrying a matching size label is kept by the text / orphan rules (its label explains the words).
Sizes: "400x200", "Ø280", "ø 180", "DN140" (also split over two words) within 1.5 m of the run's axis (measured
perpendicular, inside the run's span + 0.5 m) -> props.w_m / h_m (rect) or props.d_m (round). Unset when none.
Vector text: when the text layer holds fewer than VTEXT_MIN_LABELS size labels (CAD plots draw them as strokes),
pipeline.pdf_vtext reads the stroke text (forked, hard cap VTEXT_S, PDF_VTEXT=0 off); only its words that parse as
a duct size are used, as labels (never as "words inside the run"). Any failure -> no vector-text labels.
Terminals: a symbol that a duct passes THROUGH (duct sides continue out of two opposite sides of it), or a filled
body, is a damper ("kind": "damper"); the rest stay air terminals ("kind": "terminal"). Dampers are returned in
report["dampers"], not in the terminal list.
"""
from __future__ import annotations

import math
import os
import re

import numpy as np

PT_PER_MM = 72 / 25.4
SIZE_RE = re.compile(r"^(\d{2,4})\s*[x×X*]\s*(\d{2,4})$")
ROUND_RE = re.compile(r"^(?:[øØ⌀Ф∅]|DN)\s*(\d{2,4})$", re.I)
ROUND_PREFIX_RE = re.compile(r"^(?:[øØ⌀Ф∅]|DN)$", re.I)
NUM_RE = re.compile(r"^\d{2,4}$")
LABELISH_RE = re.compile(r"[øØ⌀∅Ф]\s*\d|\d{2,4}\s*[x×X*]\s*\d{2,4}|^DN\s*\d|l/s|^[+\-−–]?\d+([.,]\d+)?$|^h=|^Pa$",
                         re.I)
MAX_LEADERS = 3
LABEL_DIST_M = 1.5
VTEXT_S = 40.0              # hard cap on the vector-text reader (its own budget: VTEXT_INNER of it)
VTEXT_INNER = 0.75          # share of the cap given to pdf_vtext.words (it overruns its budget by its preprocessing)
VTEXT_MIN_LABELS = 3        # the text layer has this many size labels already: no vector-text pass


def _grey(c) -> bool:
    return c is not None and max(c) - min(c) <= 12 and 60 <= c[0] <= 235


def _mep_segments(page: dict):
    """All segments of non-grey paths (the MEP pens; the screened underlay is neutral grey), + per-segment path id."""
    paths, xy = page["paths"], page["xy"]
    idx = [k for k, p in enumerate(paths) if (p["stroke"] is not None and not _grey(p["stroke"]))
           or (p["stroke"] is None and p["fill"] is not None and not _grey(p["fill"]))]
    if not idx:
        return np.zeros((0, 4)), np.zeros(0, int)
    i0 = np.array([paths[k]["i0"] for k in idx])
    i1 = np.array([paths[k]["i1"] for k in idx])
    n = np.maximum(i1 - i0 - 1, 0)
    keep = n > 0
    i0, n, own = i0[keep], n[keep], np.array(idx)[keep]
    starts = np.repeat(i0, n) + (np.arange(n.sum()) - np.repeat(np.r_[0, np.cumsum(n)[:-1]], n))
    S = np.c_[xy[starts], xy[starts + 1]]
    return S, np.repeat(own, n)


class _XIndex:
    """Segments sorted by min x; short ones (< `long_pt`) found by a searchsorted slab, long ones always checked."""

    def __init__(self, S: np.ndarray, long_pt: float):
        L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
        self.long = np.flatnonzero(L >= long_pt)
        short = np.flatnonzero(L < long_pt)
        x0 = np.minimum(S[short, 0], S[short, 2])
        o = np.argsort(x0)
        self.short, self.x0, self.pad = short[o], x0[o], long_pt

    def query(self, bx0, by0, bx1, by1) -> np.ndarray:
        a, b = np.searchsorted(self.x0, bx0 - self.pad), np.searchsorted(self.x0, bx1, side="right")
        return np.r_[self.short[a:b], self.long]


def parse_labels(words: list) -> list[tuple]:
    """Size labels -> [(x, y, text, shape, a_mm, b_mm)] (page pt). Handles 'ø 160' / 'DN 125' split over 2 words."""
    out = []
    for k, w in enumerate(words):
        t = str(w.get("text", "")).strip()
        b = w["bbox"]
        m1, m2 = SIZE_RE.match(t), ROUND_RE.match(t)
        if not (m1 or m2) and ROUND_PREFIX_RE.match(t) and k + 1 < len(words):
            nxt = words[k + 1]
            nb = nxt["bbox"]
            h = max(b[3] - b[1], 1e-6)
            if NUM_RE.match(str(nxt.get("text", "")).strip()) and math.hypot(nb[0] - b[2], (nb[1] + nb[3] - b[1] - b[3]) / 2) <= 1.5 * h:
                t = t + str(nxt["text"]).strip()
                m2 = ROUND_RE.match(t)
                b = [min(b[0], nb[0]), min(b[1], nb[1]), max(b[2], nb[2]), max(b[3], nb[3])]
        if m1:
            out.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, t, "rect", int(m1.group(1)), int(m1.group(2))))
        elif m2:
            d = int(m2.group(1))
            out.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, t, "round", d, d))
    return out


def _frame(d):
    p0, p1 = np.asarray(d["start_pt"], float), np.asarray(d["end_pt"], float)
    L = float(np.linalg.norm(p1 - p0))
    u = (p1 - p0) / max(L, 1e-9)
    return p0, u, np.array([-u[1], u[0]]), L, float(d["width_pt"])


def _local(P, p0, u, nrm):
    Q = np.asarray(P, float).reshape(-1, 2) - p0
    return Q @ u, Q @ nrm


def duct_features(d: dict, S: np.ndarray, labels: list, words: list, others: list, mpt: float,
                  SW: np.ndarray | None = None, SC: np.ndarray | None = None, index=None, wtext=None) -> dict:
    p0, u, nrm, L, g = _frame(d)
    h = g / 2
    # bbox prefilter (run + end zones), then the run's own frame
    pad = h * 1.5 + 0.6 / mpt
    O = np.asarray(d["outline_pt"], float)
    bx0, by0 = O.min(0) - pad
    bx1, by1 = O.max(0) + pad
    if index is not None:
        cand = index.query(bx0, by0, bx1, by1)
    else:
        cand = np.arange(len(S))
    Sc = S[cand]
    m = ((np.maximum(Sc[:, 0], Sc[:, 2]) >= bx0) & (np.minimum(Sc[:, 0], Sc[:, 2]) <= bx1) &
         (np.maximum(Sc[:, 1], Sc[:, 3]) >= by0) & (np.minimum(Sc[:, 1], Sc[:, 3]) <= by1))
    bb = cand[m]
    Sb = S[bb]
    sc = SC[bb] if SC is not None else np.zeros(len(Sb), bool)
    ta, va = _local(Sb[:, :2], p0, u, nrm)
    tb, vb = _local(Sb[:, 2:], p0, u, nrm)
    # end fittings: curved MEP strokes (bends, round take-offs) within 0.6 m beyond / at either end, across the run
    end_curve = 0
    for t_end, sgn in ((0.0, -1), (L, 1)):
        q = sc & (((ta - t_end) * sgn >= -0.1 / mpt) & ((ta - t_end) * sgn <= 0.6 / mpt) & (np.abs(va) <= h * 1.6))
        end_curve += int(q.any())
    # what the side lines meet at each end: a bend / angled fitting (stroke leaving a side corner at 3-80 deg,
    # polyline arcs included) or a cap (one stroke across the whole width at the end)
    tol = max(0.03 / mpt, 0.15 * h)
    dtA, dvA = tb - ta, vb - va
    angA = np.degrees(np.arctan2(np.abs(dvA), np.abs(dtA) + 1e-12))
    bend_ends, cap_ends = 0, 0
    for t_end in (0.0, L):
        hit = False
        for v_side in (-h, h):
            m0 = (np.hypot(ta - t_end, va - v_side) <= tol) | (np.hypot(tb - t_end, vb - v_side) <= tol)
            if np.any(m0 & (angA >= 3) & (angA <= 80)):
                hit = True
        bend_ends += int(hit)
        cap = (np.abs(ta - t_end) <= tol) & (np.abs(tb - t_end) <= tol) & (np.minimum(va, vb) <= -h * 0.9) & (np.maximum(va, vb) >= h * 0.9)
        cap_ends += int(cap.any())
    near = (np.maximum(ta, tb) >= 0) & (np.minimum(ta, tb) <= L) & (np.maximum(va, vb) >= -h * 1.5) & (np.minimum(va, vb) <= h * 1.5)
    ta, va, tb, vb = ta[near], va[near], tb[near], vb[near]
    sw = SW[bb][near] if SW is not None else np.zeros(len(ta))
    dt, dv = tb - ta, vb - va
    sl = np.hypot(dt, dv)
    # crossing both sides inside the run (ends excluded: end caps / fittings)
    lo_v, hi_v = np.minimum(va, vb), np.maximum(va, vb)
    cross = (lo_v <= -h * 1.1) & (hi_v >= h * 1.1)
    with np.errstate(divide="ignore", invalid="ignore"):
        tm = np.where(np.abs(dv) > 1e-9, ta + dt * (0 - va) / dv, ta)
    endz = max(0.15 / mpt, 0.05 * L)
    cross &= (tm > endz) & (tm < L - endz)
    n_cross = int(cross.sum())
    # oblique strokes inside the band (hatching): angle 20-70 deg to the axis, mostly inside
    ang = np.degrees(np.arctan2(np.abs(dv), np.abs(dt) + 1e-12))
    inside = (lo_v >= -h * 1.05) & (hi_v <= h * 1.05) & (np.minimum(ta, tb) >= 0) & (np.maximum(ta, tb) <= L)
    obl = inside & (ang >= 20) & (ang <= 70) & (sl >= 0.5 * g)
    sgn = np.sign(dt * dv)[obl]
    n_hatch = 0
    if obl.sum() >= 4:
        a_ = np.round(np.degrees(np.arctan2(dv[obl] * np.sign(dt[obl] + 1e-12), np.abs(dt[obl]) + 1e-12)) / 5)
        vals, cnt = np.unique(a_, return_counts=True)
        n_hatch = int(cnt.max())
    del sgn
    # glyph strokes inside (vectorised text in a frame / table cell): short, not parallel to the run
    gly = inside & (sl <= max(0.6 * g, 3 * PT_PER_MM)) & (ang >= 15) & (sl >= 0.3 * PT_PER_MM)
    glyph_pm = float(gly.sum()) / max(L * mpt, 1e-6)
    # pen of the two sides: segments parallel to the run lying on either side line; length-weighted widest pen
    par = (ang <= 2) & (np.abs((va + vb) / 2 - 0) >= h * 0.8) & (np.abs((va + vb) / 2) <= h * 1.2)
    side_w = []
    for sg in (-1, 1):
        m = par & (np.sign((va + vb) / 2) == sg)
        if m.any():
            ww = sw[m]
            ln = sl[m]
            side_w.append(float(np.max(ww[ln >= 0.2 * ln.max()])))
        else:
            side_w.append(0.0)
    # words inside the run
    n_text, n_lab_in = 0, 0
    if len(words):
        WC = np.array([((w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2) for w in words], float) \
            if not isinstance(words, np.ndarray) else words
        tw, vw = _local(WC, p0, u, nrm)
        for k in np.flatnonzero((tw >= 0) & (tw <= L) & (np.abs(vw) <= h * 0.9)):
            txt = wtext[k] if wtext is not None else ""
            if not txt:
                continue
            if LABELISH_RE.search(txt) and not re.search(r"[A-Za-zÄÖäö]{3,}", txt):
                n_lab_in += 1
            else:
                n_text += 1
    # nearest size label along the axis
    best = None
    for (x, y, txt, shape, a, b) in labels:
        t, v = _local([(x, y)], p0, u, nrm)
        t, v = float(t[0]), float(v[0])
        if -0.5 / mpt <= t <= L + 0.5 / mpt:
            dist = abs(v) * mpt + max(0.0, -t, t - L) * mpt
            if dist <= LABEL_DIST_M and (best is None or dist < best[0]):
                best = (dist, txt, shape, a, b)
    # touching other runs (network)
    ends = [p0, p0 + u * L]
    conn = 0
    for o in others:
        if o is d:
            continue
        q0, ou, on, oL, og = o["_frame"] if "_frame" in o else _frame(o)
        for e in ends:
            t, v = _local([e], q0, ou, on)
            if -0.3 / mpt <= t[0] <= oL + 0.3 / mpt and abs(v[0]) <= og / 2 + 0.3 / mpt:
                conn += 1
                break
    return {"n_cross": n_cross, "n_hatch": n_hatch, "n_text": n_text, "n_label_in": n_lab_in,
            "label": best, "conn": conn, "glyph_pm": glyph_pm, "side_w": side_w, "end_curve": end_curve, "bend_ends": bend_ends, "cap_ends": cap_ends, "length_m": L * mpt, "width_m": g * mpt}


def _size_ok(best, width_m) -> bool:
    if not best:
        return False
    _, _, shape, a, b = best
    return min(abs(a / 1000 - width_m), abs(b / 1000 - width_m)) <= 0.35 * max(width_m, 0.1)


def judge(f: dict) -> str | None:
    """Reason a run is false, or None to keep it."""
    sized = _size_ok(f["label"], f["width_m"])
    if f["n_text"] >= 1 and not sized:
        return "text"           # words of the text layer inside the run (note frame, table cell, tag box)
    if f["cap_ends"] >= 1 and f["glyph_pm"] >= 15 and not sized:
        return "frame"          # capped box full of vectorised glyph strokes: a label / note frame
    if f["conn"] == 0 and not sized and (f["glyph_pm"] >= 25 or f["cap_ends"] == 2):
        return "box"            # unconnected: a table / note cell full of glyphs, or a box closed at both ends
    if f["n_cross"] > MAX_LEADERS and f["bend_ends"] < 2:
        return "leaders"        # band crossed by leaders, not a run between two fittings
    if f["n_hatch"] >= 4:
        return "hatch"
    if f["length_m"] >= 8 and f["width_m"] < 0.2 and not sized and f["conn"] == 0:
        return "orphan"
    return None


def attach_size(d: dict, best, mpt: float) -> None:
    props = d.setdefault("props", {})
    if not best:
        return
    _, txt, shape, a, b = best
    props["size_label"] = txt
    if shape == "round":
        props["d_m"] = a / 1000
        d.update(shape="round", diameter_m=a / 1000, label=txt)      # what pdf_mep._add_mep reads
    else:
        wd = float(d["width_pt"]) * mpt
        a_m, b_m = a / 1000, b / 1000
        w_, h_ = (a_m, b_m) if abs(a_m - wd) <= abs(b_m - wd) else (b_m, a_m)
        props["w_m"], props["h_m"] = w_, h_
        d.update(shape="rect", width_m=w_, height_m=h_, label=txt, label_across_m=w_)


LEADER_MIN_M = 1.5          # a tag leader: one straight MEP stroke at least this long ...
LEADER_OFF_AXIS_DEG = 8.0   # ... drawn off the building axes (ducts and walls run along them)
LEADER_TOL_M = 0.2          # its end this close to a symbol's outline points at that symbol


def leader_ends(page: dict, mpt: float) -> np.ndarray:
    """End points (N,2 page pt) of tag leaders: single-segment, solid, non-grey strokes >= LEADER_MIN_M long and
    >= LEADER_OFF_AXIS_DEG off both axes."""
    xy, out = page["xy"], []
    for p in page["paths"]:
        if p["stroke"] is None or p.get("dashed") or p["i1"] - p["i0"] != 2 or _grey(p["stroke"]):
            continue
        a, b = xy[p["i0"]], xy[p["i0"] + 1]
        v = b - a
        if math.hypot(v[0], v[1]) * mpt < LEADER_MIN_M:
            continue
        ang = math.degrees(math.atan2(abs(v[1]), abs(v[0])))
        if min(ang, 90 - ang) >= LEADER_OFF_AXIS_DEG:
            out += [a, b]
    return np.array(out, float).reshape(-1, 2)


def _tagged(c, s_pt: float, leaders, mpt: float) -> bool:
    """A tag leader ends at the symbol: the drawing labels it as a device of its own (type tag + airflow), which is
    how air terminals are annotated; an in-line damper drawn on the run is not given its own leader-tag here."""
    if leaders is None or not len(leaders):
        return False
    return bool(np.min(np.hypot(*(leaders - c).T)) * mpt <= s_pt * mpt + LEADER_TOL_M)


def classify_terminal(t: dict, S: np.ndarray, own: np.ndarray, page: dict, mpt: float, index=None, leaders=None) -> str:
    """'damper' when duct sides pass through two opposite sides of the symbol, or its body is filled; else 'terminal'.
    A symbol a tag leader points at stays a terminal (leaders: leader_ends(page, mpt))."""
    return classify_terminal_why(t, S, own, page, mpt, index, leaders)[0]


def classify_terminal_why(t: dict, S: np.ndarray, own: np.ndarray, page: dict, mpt: float, index=None,
                          leaders=None) -> tuple[str, str]:
    """(kind, rule): 'damper' when duct sides pass through two opposite sides of the symbol, or its body is filled;
    else 'terminal'."""
    c = np.asarray(t["center_pt"], float)
    s = float(t["size_pt"]) / 2
    if index is not None:
        q = index.query(c[0] - 4 * s, c[1] - 4 * s, c[0] + 4 * s, c[1] + 4 * s)
        S, own = S[q], own[q]
    # filled body: a filled MEP path whose bbox is the symbol
    paths, xy = page["paths"], page["xy"]
    m = (np.abs((S[:, 0] + S[:, 2]) / 2 - c[0]) <= s * 1.2) & (np.abs((S[:, 1] + S[:, 3]) / 2 - c[1]) <= s * 1.2)
    for k in sorted(set(own[m].tolist())):       # sorted: deterministic order
        p = paths[k]
        if p["fill"] is not None and not _grey(p["fill"]) and max(p["fill"]) < 100:
            P = xy[p["i0"]:p["i1"]]
            ext = np.ptp(P, axis=0)
            if ext.max() >= 0.5 * s and ext.max() <= 2.6 * s:
                return "damper", "filled"
    # lines leaving the symbol: segments with one end on the symbol outline (+-25 %) and going outward >= 0.5 size
    sides = set()
    r_in, r_out = s * 0.8, s * 1.3
    for a, b in ((S[:, :2], S[:, 2:]), (S[:, 2:], S[:, :2])):
        da = np.abs(a - c)
        on = (da.max(1) >= r_in) & (da.max(1) <= r_out)
        db = b - c
        out_ = (np.abs(db).max(1) >= s * 1.5)
        sel = on & out_
        if not sel.any():
            continue
        vec = db[sel]
        # only lines leaving straight out (axis-parallel to the outward direction), i.e. duct sides
        ang = np.degrees(np.arctan2(vec[:, 1], vec[:, 0])) % 360
        for q in ang:
            for k, a0 in enumerate((0, 90, 180, 270)):
                if min(abs(q - a0), 360 - abs(q - a0)) <= 12:
                    sides.add(k)
    if (0 in sides and 2 in sides) or (1 in sides and 3 in sides):
        return ("terminal", "tagged") if _tagged(c, s, leaders, mpt) else ("damper", "sides")
    # a duct side drawn straight through the symbol (axis-parallel line from beyond one side to beyond the other)
    for ax in (0, 1):
        o = 1 - ax
        par = np.abs(S[:, 2 + o] - S[:, o]) <= 0.03 * np.abs(S[:, 2 + ax] - S[:, ax]) + 1e-9
        lo_, hi_ = np.minimum(S[:, ax], S[:, 2 + ax]), np.maximum(S[:, ax], S[:, 2 + ax])
        # (the duct about as wide as the symbol: a terminal hanging under a narrower duct is not a damper)
        thru = par & (lo_ <= c[ax] - 1.5 * s) & (hi_ >= c[ax] + 1.5 * s) & (np.abs(S[:, o] - c[o]) <= 1.1 * s) & (np.abs(S[:, o] - c[o]) >= 0.6 * s)
        if thru.sum() >= 2:
            return ("terminal", "tagged") if _tagged(c, s, leaders, mpt) else ("damper", "through")
    # filled body drawn as nested outlines (solid fill emulated by >= 3 concentric strokes)
    nest = 0
    for k in sorted(set(own.tolist())):
        p = paths[k]
        P = xy[p["i0"]:p["i1"]]
        if len(P) < 4:
            continue
        lo_, hi_ = P.min(0), P.max(0)
        ext = hi_ - lo_
        if (np.all(np.abs((lo_ + hi_) / 2 - c) <= 0.15 * s) and ext.max() >= 1.2 * s and ext.max() <= 2.2 * s
                and ext.min() >= 0.7 * ext.max()):
            nest += 1
    if nest >= 3:
        return ("terminal", "tagged") if _tagged(c, s, leaders, mpt) else ("damper", "nested")
    return "terminal", ""


def vtext_words(page: dict, budget_s: float | None = None, focus=None, focus_r_pt: float = 0.0) -> list[dict]:
    """Stroke-text words ({"text", "bbox"}) of the page read by pipeline.pdf_vtext in a forked child killed at
    budget_s (default env PDF_VTEXT_S, else VTEXT_S; its own budget does not cover its preprocessing). Cached on
    the page (page["_vtext_words"]) so one read serves sizes and tags. [] when disabled, missing, over time, error."""
    if "_vtext_words" in page:
        return page["_vtext_words"]
    if budget_s is None:
        budget_s = float(os.environ.get("PDF_VTEXT_S", VTEXT_S))
    page["_vtext_words"] = _vtext_read(page, budget_s, focus, focus_r_pt)
    return page["_vtext_words"]


def _vtext_read(page: dict, budget_s: float, focus=None, focus_r_pt: float = 0.0) -> list[dict]:
    if os.environ.get("PDF_VTEXT", "1") == "0" or budget_s <= 1 or not hasattr(os, "fork"):
        return []
    try:
        from pipeline import pdf_vtext
        if not hasattr(pdf_vtext, "words"):
            return []
    except Exception:  # noqa: BLE001
        return []
    import pickle
    import select
    import signal
    import time
    deadline = time.monotonic() + budget_s
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:    # child: read, keep only size labels, send, exit
        code = 0
        try:
            os.close(r)
            got = pdf_vtext.words(page, budget_s=VTEXT_INNER * budget_s, focus=focus, focus_r_pt=focus_r_pt)
            data = pickle.dumps([{"text": str(x["text"]), "bbox": [float(v) for v in x["bbox"]], "src": "vtext"}
                                 for x in got])
            with os.fdopen(w, "wb") as f:
                f.write(data)
        except BaseException:  # noqa: BLE001
            code = 1
        os._exit(code)
    os.close(w)
    buf, done = b"", False
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            rd, _, _ = select.select([r], [], [], left)
            if not rd:
                break
            chunk = os.read(r, 1 << 16)
            if not chunk:
                done = True
                break
            buf += chunk
    finally:
        os.close(r)
        if not done:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
    if not done or not buf:
        return []
    try:
        out = pickle.loads(buf)
        return [x for x in out if isinstance(x, dict) and "text" in x and len(x.get("bbox") or ()) == 4]
    except Exception:  # noqa: BLE001
        return []


def _vtext_labels(page: dict, budget_s: float = VTEXT_S) -> list[tuple]:
    """Duct size labels (parse_labels tuples) among the page's stroke-text words (vtext_words)."""
    return parse_labels(vtext_words(page, budget_s))


# ---------------------------------------------------------------- r6: pen pattern, duplicates, equipment, bends,
# small round ducts, printed sizes / elevations. All lengths in metres through mpt; no per-document constants.
DASH_COVER = 0.9            # a solid side line covers at least this share of its run
DASH_MIN_GAPS = 3           # a broken side (exploded dash / dash-dot linetype) has at least this many gaps ...
DASH_GAPS_PM = 1.5          # ... and at least this many per metre
STACK_OVERLAP = 0.6         # a run lying inside another run's band over this share of its length is a duplicate
EQUIP_MIN_M, EQUIP_MAX_M = 1.0, 15.0     # machine outline (closed rectangle) side lengths
EQUIP_MIN_CIRCLES = 2       # ... holding at least this many drawn circles (fans, motors, connections)
INSIDE_SHARE = 0.8          # a run with this share of its length inside a machine outline is a machine part
ARC_MIN_DEG, ARC_MAX_DEG = 15.0, 200.0   # an arc piece of a bend
BEND_MAX_DEG = 135.0        # two concentric arcs over at most this angle at duct spacing: a bend
BEND_CHORD_DEG = 45.0       # a bend is drawn in 3D as straight chord pieces of at most this angle
ROUND_MIN_M, ROUND_MAX_M = 0.08, 0.26    # small round ducts drawn as two lines + a centre line
ROUND_MIN_LEN_M = 0.25      # a drawn piece between two in-line symbols
ROUND_JOIN_M = 0.45         # pieces of one run on one centre line, split by valves / dampers, join over this gap
LABEL_NEAR_M = 1.0          # a size label this close to a run, written along it, labels it
LABEL_LEADER_M = 3.0        # ... or further, when a leader from the label ends on the run
ALIGN_DEG = 15.0            # "written along": text direction within this of the run axis

ROUND_FULL_RE = re.compile(r"^(?:[øØ⌀Ф∅]|DN)\s*(\d{2,4})(?:L(\d{2,3}))?(?:PK)?(?:[E?]I\d{2,3})?P?$", re.I)
RECT_FULL_RE = re.compile(r"^(\d{2,4})\s*[x×X*]\s*(\d{2,4})(?:L(\d{2,3}))?(?:PK)?(?:[E?]I\d{2,3})?P?$")
ELEV_RE = re.compile(r"^(KL|AK|YK)[\s_:=]*([+\-−]?\d{1,3}[.,]\d{1,3})$", re.I)
ELEV_KEY_RE = re.compile(r"^(KL|AK|YK)[_:=]?$", re.I)
LEVEL_RE = re.compile(r"^[+\-−]?\d{1,3}[.,]\d{1,3}$")
ELEV_REF = {"KL": "centre", "AK": "bottom", "YK": "top"}     # keskilinja / alapinta / yläpinta


def _union(iv: list, join: float) -> tuple[float, int]:
    """(covered length, interior gaps) of 1-D intervals."""
    cov, gaps, cur = 0.0, 0, None
    for a, b in sorted(iv):
        if cur is None:
            cur = [a, b]
        elif a <= cur[1] + join:
            cur[1] = max(cur[1], b)
        else:
            cov += cur[1] - cur[0]
            gaps += 1
            cur = [a, b]
    if cur is not None:
        cov += cur[1] - cur[0]
    return cov, gaps


def side_pattern(d: dict, S: np.ndarray, SD: np.ndarray, mpt: float, index=None) -> list[dict]:
    """Per side line of a run: share drawn by solid pens, interior gaps, share drawn by a dashed pen, and whether
    the side is broken like a dash / dash-dot linetype (exploded by the CAD plot or a pen dash pattern)."""
    p0, u, nrm, L, g = _frame(d)
    h = g / 2
    O = np.asarray(d["outline_pt"], float)
    pad = 0.05 / mpt
    bx0, by0 = O.min(0) - pad
    bx1, by1 = O.max(0) + pad
    cand = index.query(bx0, by0, bx1, by1) if index is not None else np.arange(len(S))
    Sc = S[cand]
    m = ((np.maximum(Sc[:, 0], Sc[:, 2]) >= bx0) & (np.minimum(Sc[:, 0], Sc[:, 2]) <= bx1) &
         (np.maximum(Sc[:, 1], Sc[:, 3]) >= by0) & (np.minimum(Sc[:, 1], Sc[:, 3]) <= by1))
    bb = cand[m]
    ta, va = _local(S[bb, :2], p0, u, nrm)
    tb, vb = _local(S[bb, 2:], p0, u, nrm)
    sd = SD[bb] if SD is not None else np.zeros(len(bb), bool)
    out = []
    Lm = max(L * mpt, 1e-6)
    for sv in (-h, h):
        tol = max(0.02 / mpt, 0.1 * h)
        on = (np.abs(va - sv) <= tol) & (np.abs(vb - sv) <= tol) & (np.maximum(ta, tb) >= 0) & (np.minimum(ta, tb) <= L)
        a_, b_ = np.clip(np.minimum(ta, tb), 0, L), np.clip(np.maximum(ta, tb), 0, L)
        cov_s, gaps = _union(list(zip(a_[on & ~sd], b_[on & ~sd])), 0.01 / mpt)
        cov_d, _ = _union(list(zip(a_[on & sd], b_[on & sd])), 0.01 / mpt)
        share = cov_s / max(L, 1e-9)
        dashed = share < DASH_COVER and ((gaps >= DASH_MIN_GAPS and gaps / Lm >= DASH_GAPS_PM)
                                         or cov_d >= 0.5 * L)
        out.append({"solid_share": round(share, 2), "gaps": int(gaps), "dash_pen_share": round(cov_d / max(L, 1e-9), 2),
                    "dashed": bool(dashed)})
    return out


def _poly_contains(poly: np.ndarray, P: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon for points P (N,2)."""
    x, y = P[:, 0], P[:, 1]
    inside = np.zeros(len(P), bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        c = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / ((y2 - y1) if y2 != y1 else 1e-12) + x1)
        inside ^= c
    return inside


def _fit_circle(P: np.ndarray):
    """Least-squares circle (cx, cy, r, rms) through points P (N>=3)."""
    A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]
    bvec = (P ** 2).sum(1)
    try:
        sol, *_ = np.linalg.lstsq(A, bvec, rcond=None)
    except Exception:  # noqa: BLE001
        return None
    cx, cy = sol[0], sol[1]
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    rms = float(np.sqrt(np.mean((np.hypot(P[:, 0] - cx, P[:, 1] - cy) - r) ** 2)))
    return float(cx), float(cy), r, rms


def _curved(page: dict, mpt: float, grey_ok: bool = False) -> list[tuple]:
    """Arcs of the page's solid stroked paths with >= 4 points that lie on a circle (CAD plots flatten arcs to
    polylines): [(path id, cx, cy, r, a0, a1 (deg, a0 < a1), pen width, closed)]. Circle through the first, middle
    and last point, then every point checked against it (cheap, no least squares)."""
    paths, xy = page["paths"], page["xy"]
    out = []
    lo_m, hi_m = 0.04 / mpt, 6.0 / mpt
    for k, p in enumerate(paths):
        n = p["i1"] - p["i0"]
        if n < 3 or p["stroke"] is None or p.get("dashed") or (not grey_ok and _grey(p["stroke"])):
            continue
        P = xy[p["i0"]:p["i1"]]
        nc = int(p.get("curves") or 0)
        if nc and n == 2 * nc + 1:
            P = P[0::2]         # Bezier path stored as start, (2nd control, end) per curve: keep the on-curve points
            n = len(P)
        if n < (3 if nc else 4):
            continue
        a, b, c = P[0], P[n // 2], P[-1]
        if abs(a[0] - c[0]) + abs(a[1] - c[1]) < 1e-6:
            b, c = P[n // 3], P[(2 * n) // 3]
        ext = max(P[:, 0].max() - P[:, 0].min(), P[:, 1].max() - P[:, 1].min())
        if ext < lo_m or ext > hi_m:
            continue
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-9:
            continue        # three points on a line: straight
        sa, sb, sc = a @ a, b @ b, c @ c
        cx = (sa * (b[1] - c[1]) + sb * (c[1] - a[1]) + sc * (a[1] - b[1])) / d
        cy = (sa * (c[0] - b[0]) + sb * (a[0] - c[0]) + sc * (b[0] - a[0])) / d
        r = math.hypot(a[0] - cx, a[1] - cy)
        if not (0.03 / mpt <= r <= 3.0 / mpt):
            continue
        dr = np.hypot(P[:, 0] - cx, P[:, 1] - cy) - r
        if float(np.sqrt(np.mean(dr * dr))) > max(0.03 * r, 0.3):
            continue
        ang = np.arctan2(P[:, 1] - cy, P[:, 0] - cx)
        dA = np.diff(ang)
        dA = (dA + math.pi) % (2 * math.pi) - math.pi
        dA = dA[np.abs(dA) > 1e-9]
        if not len(dA) or not (np.all(dA > 0) or np.all(dA < 0)):
            continue        # not a monotonic sweep
        a0 = math.degrees(float(ang[0]))
        a1 = a0 + math.degrees(float(dA.sum()))
        a0, a1 = min(a0, a1), max(a0, a1)
        out.append((k, float(cx), float(cy), float(r), a0, a1, float(p.get("width") or 0.0), bool(p["closed"])))
    return out


def equipment_boxes(page: dict, mpt: float, arcs=None) -> list[dict]:
    """Machine outlines: closed rectangles EQUIP_MIN_M..EQUIP_MAX_M a side (any pen: the underlay draws machines
    too) holding >= EQUIP_MIN_CIRCLES drawn circles (fans, motors, duct connections). [{"poly", "path", "circles"}]"""
    paths, xy = page["paths"], page["xy"]
    arcs = _curved(page, mpt, grey_ok=True) if arcs is None else arcs
    circ = np.array([(cx, cy) for (_, cx, cy, r, a0, a1, _, _) in arcs if a1 - a0 >= 300 and 0.1 / mpt <= 2 * r <= 1.6 / mpt],
                    float).reshape(-1, 2)
    out = []
    if not len(circ):
        return out
    for k, p in enumerate(paths):
        if not p["closed"] or not 4 <= p["i1"] - p["i0"] <= 6:
            continue
        P = xy[p["i0"]:p["i1"]]
        Q = P[:-1] if np.allclose(P[0], P[-1]) else P
        if len(Q) != 4:
            continue
        e = np.roll(Q, -1, axis=0) - Q
        ln = np.hypot(e[:, 0], e[:, 1])
        if ln.min() * mpt < EQUIP_MIN_M or ln.max() * mpt > EQUIP_MAX_M:
            continue
        cosang = np.abs((e * np.roll(e, -1, axis=0)).sum(1)) / np.maximum(ln * np.roll(ln, -1), 1e-9)
        if cosang.max() > 0.05:
            continue        # not a rectangle
        n_in = int(_poly_contains(Q, circ).sum())
        if n_in >= EQUIP_MIN_CIRCLES:
            out.append({"poly": Q, "path": k, "circles": n_in})
    return out


def _share_inside(d: dict, boxes: list) -> float:
    if not boxes:
        return 0.0
    a, b = np.asarray(d["start_pt"], float), np.asarray(d["end_pt"], float)
    P = a + np.linspace(0, 1, 21)[:, None] * (b - a)
    best = 0.0
    for bx in boxes:
        best = max(best, float(_poly_contains(bx["poly"], P).mean()))
    return best


def dedupe_stacked(D: list[dict], mpt: float) -> tuple[list[dict], int, int]:
    """Parallel runs whose bands overlap or share a side line over >= STACK_OVERLAP of the shorter one are one run:
    the solid / sized / longer one is kept; collinear runs of one width that overlap are merged into one.
    -> (runs, dropped, merged)."""
    order = sorted(range(len(D)), key=lambda i: (int(D[i].get("linetype") == "dashed"),
                                                 -int(bool((D[i].get("props") or {}).get("size_label"))),
                                                 -float(D[i]["length_m"]), i))
    keep: list[dict] = []
    dropped = merged = 0
    for i in order:
        d = D[i]
        p0, u, nrm, L, g = _frame(d)
        dup = False
        for k in keep:
            q0, ku, kn, kL, kg = _frame(k)
            if abs(float(u @ ku)) < math.cos(math.radians(3)):
                continue
            t, v = _local([p0, p0 + u * L], q0, ku, kn)
            lo, hi = max(0.0, float(t.min())), min(kL, float(t.max()))
            ov = hi - lo
            off = float(np.mean(v))
            if ov <= 0:
                continue
            if abs(off) <= 0.25 * min(kg, g) and abs(kg - g) <= 0.2 * max(kg, g):     # collinear, same width
                t0, t1 = min(0.0, float(t.min())), max(kL, float(t.max()))
                a, b = q0 + ku * t0, q0 + ku * t1
                half = kn * kg / 2
                k.update(start_pt=a.tolist(), end_pt=b.tolist(), length_m=round((t1 - t0) * mpt, 3),
                         outline_pt=[(a - half).tolist(), (b - half).tolist(), (b + half).tolist(), (a + half).tolist()])
                k.pop("_frame", None)
                dup = True
                merged += 1
                break
            # bands overlap, or the two share a side line (a set of parallel lines paired twice): one run
            if abs(off) <= (kg + g) / 2 + 0.02 / mpt and ov >= STACK_OVERLAP * min(L, kL):
                dup = True
                break
        if dup:
            dropped += 1
            continue
        keep.append(d)
    pos = {id(d): i for i, d in enumerate(D)}
    keep.sort(key=lambda d: pos.get(id(d), 0))
    return keep, dropped - merged, merged


def _run(a, b, g: float, mpt: float, **kw) -> dict:
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = float(np.linalg.norm(b - a))
    u = (b - a) / max(L, 1e-9)
    half = np.array([-u[1], u[0]]) * g / 2
    d = {"start_pt": a.tolist(), "end_pt": b.tolist(), "width_pt": float(g), "width_m": round(g * mpt, 3),
         "width_drawn_m": round(g * mpt, 3), "length_m": round(L * mpt, 3), "shape": "rect", "height_m": None,
         "label": None, "outline_pt": [(a - half).tolist(), (b - half).tolist(), (b + half).tolist(), (a + half).tolist()]}
    d.update(kw)
    return d


def arc_bends(arcs: list, mpt: float) -> list[dict]:
    """Duct bends: two concentric solid arcs of one pen whose radii differ by a duct width (0.1-1.5 m), overlapping
    over 15..BEND_MAX_DEG. Arcs that close into a full circle with others on the same centre (round symbols) are
    left out. Each bend comes back as chord runs along the mid radius (<= BEND_CHORD_DEG each, one bend id), width =
    radius gap."""
    if not arcs:
        return []
    A = np.array([(cx, cy, r, a0, a1, w) for (_, cx, cy, r, a0, a1, w, _) in arcs], float)
    ids = [a[0] for a in arcs]
    ok = (A[:, 4] - A[:, 3] >= ARC_MIN_DEG) & (A[:, 4] - A[:, 3] <= ARC_MAX_DEG)
    # full circles assembled from pieces on one centre and radius
    tol_c = 0.02 / mpt
    for i in np.flatnonzero(ok):
        same = (np.hypot(A[:, 0] - A[i, 0], A[:, 1] - A[i, 1]) <= tol_c) & (np.abs(A[:, 2] - A[i, 2]) <= tol_c)
        if (A[same, 4] - A[same, 3]).sum() >= 300:
            ok[i] = False
    idx = np.flatnonzero(ok)
    idx = idx[np.argsort(A[idx, 0], kind="stable")]
    xs = A[idx, 0]
    cand = []
    for a_, i in enumerate(idx):
        lo_, hi_ = np.searchsorted(xs, A[i, 0] - 0.1 / mpt), np.searchsorted(xs, A[i, 0] + 0.1 / mpt, side="right")
        for j in idx[lo_:hi_]:
            dr = A[j, 2] - A[i, 2]
            if dr * mpt < 0.1 or dr * mpt > 1.5 or abs(A[j, 5] - A[i, 5]) > 1e-6:
                continue
            if math.hypot(A[j, 0] - A[i, 0], A[j, 1] - A[i, 1]) > max(0.04 / mpt, 0.08 * dr):
                continue
            # angular overlap (try the +-360 shifts of j)
            best = None
            for sh in (-360.0, 0.0, 360.0):
                lo, hi = max(A[i, 3], A[j, 3] + sh), min(A[i, 4], A[j, 4] + sh)
                if hi - lo > 0 and (best is None or hi - lo > best[1] - best[0]):
                    best = (lo, hi)
            if best is None:
                continue
            sw = best[1] - best[0]
            if sw < ARC_MIN_DEG or sw > BEND_MAX_DEG or sw < 0.6 * min(A[i, 4] - A[i, 3], A[j, 4] - A[j, 3]):
                continue
            cand.append((dr, int(i), int(j), best))
    cand.sort(key=lambda c: (c[0], c[1], c[2]))
    used_in, used_out, out = set(), set(), []
    for dr, i, j, (lo, hi) in cand:
        if i in used_in or j in used_out:
            continue
        used_in.add(i)
        used_out.add(j)
        cx, cy = (A[i, 0] + A[j, 0]) / 2, (A[i, 1] + A[j, 1]) / 2
        rm = (A[i, 2] + A[j, 2]) / 2
        n = max(1, int(math.ceil((hi - lo) / BEND_CHORD_DEG - 1e-6)))
        th = np.radians(np.linspace(lo, hi, n + 1))
        pts = np.c_[cx + rm * np.cos(th), cy + rm * np.sin(th)]
        ev = {"rule": "arc pair", "paths": [ids[i], ids[j]], "r_in_m": round(A[i, 2] * mpt, 3),
              "r_out_m": round(A[j, 2] * mpt, 3), "sweep_deg": round(hi - lo, 1)}
        for q in range(n):
            out.append(_run(pts[q], pts[q + 1], dr, mpt, fitting="bend", bend_id=len(used_in), source="arc pair",
                            evidence=ev))
    return out


def _lines(S: np.ndarray, own: np.ndarray, pw: np.ndarray, mpt: float, gap_m: float) -> np.ndarray:
    """Collinear straight pieces of one pen width joined over gaps <= gap_m: (N,9) as pdf_mep._merge_collinear."""
    from pipeline import pdf_mep
    wid = np.round(pw[own] * 100).astype(int)
    return pdf_mep._merge_collinear(S, math.radians(1.0), 0.01 / mpt, gap_m / mpt, (wid, np.full(len(S), -1)))


def round_pairs(S: np.ndarray, own: np.ndarray, SD: np.ndarray, pw: np.ndarray, mpt: float) -> list[dict]:
    """Small round ducts drawn as two solid lines of one pen ROUND_MIN_M..ROUND_MAX_M apart with a centre line
    (any non-grey pen, often dash-dot) half-way between them. Pieces between in-line symbols (valves, dampers)
    are joined along their centre line over gaps <= ROUND_JOIN_M."""
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    solid = ~SD & (L * mpt >= 0.03)
    if not solid.any():
        return []
    Ls = _lines(S[solid], own[solid], pw, mpt, 0.02)          # sides: solid pieces, tiny gaps only
    Lc = _lines(S, own, pw, mpt, 0.5)                          # centre lines: dash-dot pieces joined
    Ls = Ls[(Ls[:, 3] - Ls[:, 2]) * mpt >= ROUND_MIN_LEN_M]
    if not len(Ls):
        return []
    nb = 180
    ab_s = np.round(Ls[:, 0] / math.radians(1.0)).astype(int) % nb
    ab_c = np.round(Lc[:, 0] / math.radians(1.0)).astype(int) % nb
    pieces = []
    for b in np.unique(ab_s):
        si = np.flatnonzero(ab_s == b)
        si = si[np.argsort(Ls[si, 1], kind="stable")]
        ci = np.flatnonzero(ab_c == b)
        ci = ci[np.argsort(Lc[ci, 1], kind="stable")]
        rc = Lc[ci, 1]
        rs = Ls[si, 1]
        for a_, i in enumerate(si):
            j1 = int(np.searchsorted(rs, Ls[i, 1] + ROUND_MAX_M / mpt, side="right"))
            js = si[a_ + 1:j1]
            if not len(js):
                continue
            gaps_ = Ls[js, 1] - Ls[i, 1]
            lo_ = np.maximum(Ls[i, 2], Ls[js, 2])
            hi_ = np.minimum(Ls[i, 3], Ls[js, 3])
            okj = (gaps_ * mpt >= ROUND_MIN_M) & (Ls[js, 6] == Ls[i, 6]) & ((hi_ - lo_) * mpt >= ROUND_MIN_LEN_M)
            for j in js[okj]:
                gap = Ls[j, 1] - Ls[i, 1]
                lo, hi = max(Ls[i, 2], Ls[j, 2]), min(Ls[i, 3], Ls[j, 3])
                mid = (Ls[i, 1] + Ls[j, 1]) / 2
                c0, c1 = np.searchsorted(rc, mid - 0.12 * gap), np.searchsorted(rc, mid + 0.12 * gap, side="right")
                cc = ci[c0:c1]
                cov = (np.minimum(Lc[cc, 3], hi) - np.maximum(Lc[cc, 2], lo)).clip(0).sum() if len(cc) else 0
                if cov < 0.4 * (hi - lo):
                    continue
                # a third same-pen line at the same spacing: hatching / stacked lines, not a duct
                third = (np.abs(rs - (Ls[j, 1] + gap)) <= 0.1 * gap) | (np.abs(rs - (Ls[i, 1] - gap)) <= 0.1 * gap)
                third &= (np.minimum(Ls[si, 3], hi) - np.maximum(Ls[si, 2], lo)) >= 0.5 * (hi - lo)
                third &= Ls[si, 6] == Ls[i, 6]
                if third.any():
                    continue
                pieces.append((int(b), float(mid), float(lo), float(hi), float(gap), float(Ls[i, 4]), float(Ls[i, 5])))
    # join pieces on one centre line
    pieces.sort(key=lambda q: (q[0], round(q[1] / max(0.02 / mpt, 1e-9)), q[2]))
    runs = []
    for q in pieces:
        if runs:
            r = runs[-1]
            if (r[0] == q[0] and abs(r[1] - q[1]) <= 0.12 * min(r[4], q[4]) and abs(r[4] - q[4]) <= 0.15 * r[4]
                    and q[2] - r[3] <= ROUND_JOIN_M / mpt):
                r[3] = max(r[3], q[3])
                r[7] += 1
                continue
        runs.append(list(q) + [1])
    out = []
    for b, rho, lo, hi, g, ux, uy, n in runs:
        ang = math.degrees(math.atan2(abs(uy), abs(ux)))
        if min(ang, 90 - ang) >= 8.0 and (hi - lo) * mpt >= 0.6:
            continue        # long and off the building axes: a pair of tag leaders, not a small duct
        u = np.array([ux, uy])
        nrm = np.array([-u[1], u[0]])
        a, e = u * lo + nrm * rho, u * hi + nrm * rho
        out.append(_run(a, e, g, mpt, source="round pair", evidence={"rule": "two solid lines + centre line",
                                                                       "pieces": int(n), "gap_m": round(g * mpt, 3)}))
    return out


def _word_dir(w: dict) -> np.ndarray | None:
    """Unit reading direction of a word (page pt, y down): its "angle" when given, else from a long bbox."""
    a = w.get("angle")
    if a is not None:
        r = math.radians(float(a))
        return np.array([abs(math.cos(r)), abs(math.sin(r))])
    b = w["bbox"]
    bw, bh = b[2] - b[0], b[3] - b[1]
    if len(str(w.get("text", ""))) >= 3 and max(bw, bh) >= 1.8 * min(bw, bh):
        return np.array([1.0, 0.0]) if bw > bh else np.array([0.0, 1.0])
    return None


def parse_printed(words: list) -> list[dict]:
    """Printed duct sizes and elevations: [{"xy", "bbox", "text", "kind": "round"|"rect"|"elev", "a_mm", "b_mm",
    "ins_mm", "elev_m", "ref", "dir"}]. Sizes: "Ø500", "Ø500L80" (L = insulation mm), "Ø250EI60", "DN125",
    "2300x1200L100PK", "400x200"; elevations "KL +16.66" (centre line), "AK" (bottom), "YK" (top), also split
    over two words. A type tag ("S1-900x150") is not a duct size."""
    out = []
    for k, w in enumerate(words):
        t = str(w.get("text", "")).strip().replace(" ", "")
        b = list(w["bbox"])
        m1, m2, me = RECT_FULL_RE.match(t), ROUND_FULL_RE.match(t), ELEV_RE.match(t)
        if not (m1 or m2 or me) and k + 1 < len(words):
            nxt = words[k + 1]
            nb = nxt["bbox"]
            h = max(min(b[3] - b[1], b[2] - b[0]), 1e-6)
            close = math.hypot((nb[0] + nb[2] - b[0] - b[2]) / 2, (nb[1] + nb[3] - b[1] - b[3]) / 2) <= \
                max(b[2] - b[0], b[3] - b[1]) + 2.5 * h
            nt = str(nxt.get("text", "")).strip()
            if close and ((ROUND_PREFIX_RE.match(t) and NUM_RE.match(nt)) or (ELEV_KEY_RE.match(t) and LEVEL_RE.match(nt))):
                t = t.rstrip("_:=") + nt
                b = [min(b[0], nb[0]), min(b[1], nb[1]), max(b[2], nb[2]), max(b[3], nb[3])]
                m2, me = ROUND_FULL_RE.match(t), ELEV_RE.match(t)
        rec = {"xy": ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), "bbox": b, "text": t, "dir": _word_dir(w)}
        if m1:
            rec.update(kind="rect", a_mm=int(m1.group(1)), b_mm=int(m1.group(2)), ins_mm=int(m1.group(3) or 0))
        elif m2:
            d = int(m2.group(1))
            rec.update(kind="round", a_mm=d, b_mm=d, ins_mm=int(m2.group(2) or 0))
        elif me:
            rec.update(kind="elev", ref=ELEV_REF[me.group(1).upper()],
                       elev_m=float(me.group(2).replace(",", ".").replace("−", "-")))
        else:
            continue
        out.append(rec)
    return out


def _label_fits(lab: dict, width_m: float) -> bool:
    """A printed size fits a drawn band: round Ø (or Ø + insulation) / one side of W x H within 35 %."""
    if lab["kind"] == "elev":
        return True
    ins = 2 * lab.get("ins_mm", 0) / 1000
    for s in {lab["a_mm"] / 1000, lab["b_mm"] / 1000}:
        for v in (s, s + ins):
            if abs(v - width_m) <= 0.35 * max(v, 0.1):
                return True
    return False


def _leader_segments(page: dict, mpt: float) -> np.ndarray:
    """Candidate leaders: single straight solid non-grey strokes 0.1..LABEL_LEADER_M long, (N,4)."""
    paths, xy = page["paths"], page["xy"]
    idx = [k for k, p in enumerate(paths) if p["i1"] - p["i0"] == 2 and p["stroke"] is not None
           and not p.get("dashed") and not _grey(p["stroke"])]
    if not idx:
        return np.zeros((0, 4))
    i0 = np.array([paths[k]["i0"] for k in idx])
    L = np.c_[xy[i0], xy[i0 + 1]]
    ln = np.hypot(L[:, 2] - L[:, 0], L[:, 3] - L[:, 1]) * mpt
    return L[(ln >= 0.1) & (ln <= LABEL_LEADER_M)]


def _leader_far_ends(lab: dict, LS: np.ndarray) -> np.ndarray:
    """Far ends of the leaders that start at the label (within 2 text heights of its box)."""
    if not len(LS):
        return np.zeros((0, 2))
    b = lab["bbox"]
    th = max(min(b[2] - b[0], b[3] - b[1]), 1.0)
    pad = 2 * th
    out = []
    for e0, e1 in ((LS[:, :2], LS[:, 2:]), (LS[:, 2:], LS[:, :2])):
        near = (e0[:, 0] >= b[0] - pad) & (e0[:, 0] <= b[2] + pad) & (e0[:, 1] >= b[1] - pad) & (e0[:, 1] <= b[3] + pad)
        out.append(e1[near])
    return np.concatenate(out)


def assign_printed(D: list[dict], labels: list[dict], S: np.ndarray, mpt: float, index=None,
                   leader_segs: np.ndarray | None = None) -> dict:
    """Each printed size / elevation goes to the one run it labels: within LABEL_NEAR_M of the run's axis (inside
    its span +- 0.3 m) and written along it, or joined to it by a leader (<= LABEL_LEADER_M). A size must fit the
    drawn band (_label_fits). Sets on the run: shape/diameter_m or width_m/height_m (+ props, Source printed),
    props elev_m / elev_ref; a run with no size label keeps its measured width, depth "default" and is marked
    rectangular by default. -> counts."""
    if not D:
        return {"sized": 0, "elev": 0}
    P0 = np.array([d["start_pt"] for d in D], float)
    E = np.array([d["end_pt"] for d in D], float)
    Ln = np.maximum(np.hypot(*(E - P0).T), 1e-9)
    U = (E - P0) / Ln[:, None]
    NR = np.c_[-U[:, 1], U[:, 0]]
    G = np.array([float(d["width_pt"]) for d in D])
    Wm = np.array([float(d.get("width_drawn_m") or d.get("width_m") or g * mpt) for d, g in zip(D, G)])
    LS = leader_segs if leader_segs is not None else np.zeros((0, 4))
    cos_al = math.cos(math.radians(ALIGN_DEG))
    best_for: dict[int, list] = {}
    for li, lab in enumerate(labels):
        q = np.asarray(lab["xy"], float)
        t = ((q - P0) * U).sum(1)
        v = ((q - P0) * NR).sum(1)
        fit = np.ones(len(D), bool) if lab["kind"] == "elev" else np.array([_label_fits(lab, w) for w in Wm])
        dist = np.full(len(D), np.inf)
        dvec = lab.get("dir")
        if dvec is not None:
            al = dvec[0] * np.abs(U[:, 0]) + dvec[1] * np.abs(U[:, 1]) >= cos_al
            near = fit & al & (t >= -0.3 / mpt) & (t <= Ln + 0.3 / mpt) & (np.abs(v) * mpt <= LABEL_NEAR_M)
            dist[near] = np.abs(v[near]) * mpt
        F = _leader_far_ends(lab, LS)
        if len(F):
            cand = np.flatnonzero(fit & ~np.isfinite(dist) & (np.abs(v) * mpt <= LABEL_LEADER_M + G * mpt))
            for di in cand:
                tf = (F - P0[di]) @ U[di]
                vf = (F - P0[di]) @ NR[di]
                if np.any((tf >= 0) & (tf <= Ln[di]) & (np.abs(vf) <= G[di] / 2 + 0.1 / mpt)):
                    dist[di] = LABEL_NEAR_M + abs(v[di]) * mpt
        if np.isfinite(dist).any():
            di = int(np.argmin(dist))
            best_for.setdefault(di, []).append((float(dist[di]), li))
    n_size = n_elev = 0
    for di, d in enumerate(D):
        props = d.setdefault("props", {})
        got = sorted(best_for.get(di, []))
        size = next((labels[li] for _, li in got if labels[li]["kind"] != "elev"), None)
        elev = next((labels[li] for _, li in got if labels[li]["kind"] == "elev"), None)
        wd = float(d.get("width_drawn_m") or d.get("width_m") or float(d["width_pt"]) * mpt)
        geo = d.get("evidence") if isinstance(d.get("evidence"), dict) else props.get("geometry_evidence")
        if geo:
            props["geometry_evidence"] = geo
        pre = (f"{geo['rule']} (paths {geo['paths']}); " if geo and "paths" in geo else
               f"{geo['rule']}; " if geo else "two parallel solid MEP lines; ")
        if d.get("linetype") == "dashed":
            props["linetype"] = "dashed"
            pre = ("two parallel MEP lines drawn dash-dot; linetype not defined in the sheet legend "
                   "(its meaning is not read); ")
        if size is not None:
            n_size += 1
            props["size_label"] = size["text"]
            props["size_source"] = "printed"
            if size.get("ins_mm"):
                props["insulation_mm"] = size["ins_mm"]
            if size["kind"] == "round":
                dm = size["a_mm"] / 1000
                props["d_m"] = dm
                props["shape_source"] = "printed"
                d.update(shape="round", diameter_m=dm, label=size["text"], label_across_m=dm)
            else:
                a_m, b_m = size["a_mm"] / 1000, size["b_mm"] / 1000
                w_, h_ = (a_m, b_m) if abs(a_m - wd) <= abs(b_m - wd) else (b_m, a_m)
                props["w_m"], props["h_m"] = w_, h_
                props["shape_source"] = "printed"
                d.update(shape="rect", width_m=w_, height_m=h_, label=size["text"], label_across_m=w_)
            d["evidence"] = pre + (f"size printed '{size['text']}' at page pt {[round(v, 1) for v in size['xy']]}"
                             + (f", insulation {size['ins_mm']} mm" if size.get("ins_mm") else ""))
        else:
            props.pop("size_label", None)
            props.pop("d_m", None)
            props.pop("w_m", None)
            props.pop("h_m", None)
            props["size_source"] = "measured width; depth default"
            props["shape_source"] = f"default (no printed size within {LABEL_NEAR_M:.1f} m): rectangular assumed"
            d.update(shape="rect", label=None)
            d.pop("diameter_m", None)
            d["height_m"] = None
            d["evidence"] = pre + (f"width measured {wd:.3f} m (drawn band); no printed size within {LABEL_NEAR_M:.1f} m: "
                             "shape rectangular by default, depth default")
        if elev is not None:
            n_elev += 1
            props["elev_m"], props["elev_ref"] = elev["elev_m"], elev["ref"]
            props["elev_source"] = f"printed '{elev['text']}'"
            d["elev_m"], d["elev_ref"] = elev["elev_m"], elev["ref"]
            d["evidence"] += f"; elevation printed '{elev['text']}' ({elev['ref']} of duct)"
    return {"sized": n_size, "elev": n_elev}


def _covered(d: dict, D: list[dict], mpt: float) -> bool:
    """d's mid point lies inside one of D's bands (+0.05 m) and runs along it."""
    if not D:
        return False
    c = (np.asarray(d["start_pt"], float) + np.asarray(d["end_pt"], float)) / 2
    u = np.asarray(d["end_pt"], float) - np.asarray(d["start_pt"], float)
    u = u / max(float(np.hypot(*u)), 1e-9)
    P0 = np.array([k["start_pt"] for k in D], float)
    E = np.array([k["end_pt"] for k in D], float)
    Ln = np.maximum(np.hypot(*(E - P0).T), 1e-9)
    U = (E - P0) / Ln[:, None]
    G = np.array([float(k["width_pt"]) for k in D])
    t = ((c - P0) * U).sum(1)
    v = (c - P0)[:, 0] * -U[:, 1] + (c - P0)[:, 1] * U[:, 0]
    pad = 0.05 / mpt
    return bool(np.any((t >= -pad) & (t <= Ln + pad) & (np.abs(v) <= G / 2 + pad) & (np.abs(U @ u) >= 0.7)))


def single_line_runs(S: np.ndarray, own: np.ndarray, SD: np.ndarray, pw: np.ndarray, labels: list[dict],
                     D: list[dict], mpt: float) -> list[dict]:
    """Round ducts drawn as ONE centre line, only where the sheet prints their size: a solid non-grey straight
    line >= 0.8 m with a round size label within LABEL_NEAR_M written along it, with no same-pen parallel line at
    0.05-1.6 m beside it (not the side of a double-line duct) and not inside a run already found. Width = the
    printed Ø (Source printed)."""
    rl = [lab for lab in labels if lab["kind"] == "round" and lab.get("dir") is not None]
    if not rl:
        return []
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    solid = ~SD & (L * mpt >= 0.05)
    Ls = _lines(S[solid], own[solid], pw, mpt, 0.02)
    Ls = Ls[(Ls[:, 3] - Ls[:, 2]) * mpt >= 0.8]
    out = []
    used = set()
    for lab in rl:
        q = np.asarray(lab["xy"], float)
        best = None
        for i in range(len(Ls)):
            u = Ls[i, 4:6]
            if lab["dir"][0] * abs(u[0]) + lab["dir"][1] * abs(u[1]) < math.cos(math.radians(ALIGN_DEG)):
                continue
            nrm = np.array([-u[1], u[0]])
            t, v = float(q @ u), float(q @ nrm) - Ls[i, 1]
            if not (Ls[i, 2] - 0.3 / mpt <= t <= Ls[i, 3] + 0.3 / mpt) or abs(v) * mpt > LABEL_NEAR_M:
                continue
            if best is None or abs(v) < best[0]:
                best = (abs(v), i)
        if best is None or best[1] in used:
            continue
        i = best[1]
        u = Ls[i, 4:6]
        nrm = np.array([-u[1], u[0]])
        bb = lab["bbox"]
        corners = np.array([[bb[0], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]], [bb[2], bb[1]]], float) @ u
        beyond = max(0.0, corners.min() - Ls[i, 2]) + max(0.0, Ls[i, 3] - corners.max())
        if beyond * mpt < 1.0:
            continue        # the label's own underline / frame line, not a duct running past it
        par = (np.abs(Ls[:, 0] - Ls[i, 0]) <= math.radians(1.5)) & (Ls[:, 6] == Ls[i, 6])
        off = np.abs(Ls[:, 1] - Ls[i, 1]) * mpt
        ov = np.minimum(Ls[:, 3], Ls[i, 3]) - np.maximum(Ls[:, 2], Ls[i, 2])
        if np.any(par & (off >= 0.05) & (off <= 1.6) & (ov >= 0.5 * (Ls[i, 3] - Ls[i, 2]))):
            continue
        dm = lab["a_mm"] / 1000
        a, e = u * Ls[i, 2] + nrm * Ls[i, 1], u * Ls[i, 3] + nrm * Ls[i, 1]
        r = _run(a, e, dm / mpt, mpt, source="single line + printed size",
                 evidence={"rule": "single centre line with a printed round size", "label": lab["text"],
                           "label_pt": [round(v, 1) for v in lab["xy"]]})
        if _covered(r, D, mpt):
            continue
        used.add(i)
        out.append(r)
    return out


def _chain_leaders(D: list[dict], feats: list[dict], mpt: float) -> set:
    """Runs that are pieces of one longer band (collinear, same width +-20 %, gaps <= 1 m), judged as one: a band
    cut into pieces (e.g. by another sheet's walls) must get the same "leaders" verdict as the whole band. ->
    indices of pieces whose chain has > MAX_LEADERS leader crossings in total and fewer than 2 bend ends."""
    n = len(D)
    if n < 2:
        return set()
    fr = [_frame(d) for d in D]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        p0, u, nrm, L, g = fr[i]
        for j in range(i + 1, n):
            q0, v_, n2, L2, g2 = fr[j]
            if abs(float(u @ v_)) < math.cos(math.radians(2)) or abs(g - g2) > 0.2 * max(g, g2):
                continue
            t, v = _local([q0, q0 + v_ * L2], p0, u, nrm)
            if abs(float(np.mean(v))) > 0.25 * g:
                continue
            gap = max(float(t.min()) - L, -float(t.max()), 0.0)
            if gap * mpt <= 1.0:
                parent[find(j)] = find(i)
    groups: dict[int, list] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    bad = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        cross = sum(feats[i]["n_cross"] for i in members)
        bends = sum(feats[i]["bend_ends"] for i in members)
        if cross > MAX_LEADERS and bends < 2:
            bad.update(members)
    return bad


def refine(ducts, terminals, page, mpt):
    """-> (ducts, terminals, report). Never raises; on error returns the input unchanged.

    Order: false-run rules (judge) -> broken side lines (dashed) -> machine parts (inside an equipment outline)
    -> stacked duplicates -> added runs the pair finder misses (arc bends, small round ducts with a centre line,
    single centre lines with a printed Ø) -> printed sizes / elevations -> terminal / damper split."""
    ducts_in, terms_in = list(ducts or []), list(terminals or [])
    try:
        S, own = _mep_segments(page)
        pw = np.array([float(q.get("width") or 0.0) for q in page["paths"]])
        SW = pw[own] if len(own) else np.zeros(0)
        pdash = np.array([bool(q.get("dashed")) for q in page["paths"]], bool)
        SD = pdash[own] if len(own) else np.zeros(0, bool)
        IX = _XIndex(S, 2.0 / mpt) if len(S) else None
        pc = np.array([int(q.get("curves") or 0) > 0 for q in page["paths"]], bool)
        SC = pc[own] if len(own) else np.zeros(0, bool)
        words = page.get("words") or []
        labels = parse_labels(words)
        n_vtext = 0
        vw = []
        if ducts_in and len(labels) < VTEXT_MIN_LABELS:     # sizes drawn as strokes: read them (labels only)
            vw = vtext_words(page, float(os.environ.get("PDF_VTEXT_S", VTEXT_S)))
            vl = parse_labels(vw)
            labels, n_vtext = labels + vl, len(vl)
        printed = parse_printed(list(words)) + parse_printed(list(vw)) if ducts_in else []
        keep, rejects = [], {}
        feats, dashed_runs = [], []
        WC = np.array([((w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2) for w in words],
                      float).reshape(-1, 2)
        wtext = [str(w.get("text", "")).strip() for w in words]
        fr = [{"_frame": _frame(d)} for d in ducts_in]
        for k, d in enumerate(ducts_in):
            f = duct_features(d, S, labels, WC, fr[:k] + fr[k + 1:], mpt, SW, SC, IX, wtext)
            f["sides"] = side_pattern(d, S, SD, mpt, IX) if len(S) else []
            feats.append(f)
        arcs = _curved(page, mpt) if ducts_in or terms_in else []
        boxes = equipment_boxes(page, mpt, arcs) if (ducts_in or terms_in) else []
        chain_bad = _chain_leaders(ducts_in, feats, mpt)
        for i_d, (d, f) in enumerate(zip(ducts_in, feats)):
            why = judge(f)
            if why is None and i_d in chain_bad:
                why = "leaders"         # one piece of a longer collinear band that leaders cross (see _chain_leaders)
            if why is None and any(s["dashed"] for s in f["sides"]):
                dashed_runs.append({"start_pt": d["start_pt"], "end_pt": d["end_pt"], "width_m": d.get("width_m"),
                                    "sides": f["sides"]})
                if os.environ.get("PDF_DUCTS_DASHED", "keep") == "drop":
                    why = "dashed"      # a side drawn as a dash / dash-dot linetype: not a solid duct outline
                else:
                    d = dict(d, linetype="dashed")
            if why is None and _share_inside(d, boxes) >= INSIDE_SHARE:
                why = "equipment"       # drawn inside a machine outline: a machine part
            if why:
                rejects[why] = rejects.get(why, 0) + 1
                continue
            d2 = dict(d)
            d2["props"] = dict(d.get("props") or {})
            d2["source"] = d.get("source") or "line pair"
            keep.append(d2)
        keep, n_stacked, n_merged = dedupe_stacked(keep, mpt)
        if n_stacked:
            rejects["stacked"] = n_stacked
        added = {"bends": 0, "round_pairs": 0, "single_line": 0}
        if ducts_in and os.environ.get("PDF_DUCTS_EXTRA", "1") != "0":   # extra runs (PDF_DUCTS_EXTRA=0 off), only on an MEP plan
            for name, fn in (("bends", lambda: arc_bends(arcs, mpt)),
                             ("round_pairs", lambda: round_pairs(S, own, SD, pw, mpt)),
                             ("single_line", lambda: single_line_runs(S, own, SD, pw, printed, keep, mpt))):
                try:
                    new = fn()
                except Exception:  # noqa: BLE001  optional rule
                    new = []
                for r in new:
                    if _covered(r, keep, mpt) or _share_inside(r, boxes) >= INSIDE_SHARE:
                        continue
                    r.setdefault("props", {})
                    keep.append(r)
                    added[name] += 1
        cnt = assign_printed(keep, printed, S, mpt, IX, _leader_segments(page, mpt)) if keep else {"sized": 0, "elev": 0}
        tout, dampers = [], []
        try:
            LE = leader_ends(page, mpt) if terms_in else None
        except Exception:  # noqa: BLE001
            LE = None
        n_term_equip = 0
        for t in terms_in:
            # a terminal the sheet tags with a terminal type (pdf_mep.terminals_from_tags) stays a terminal
            if t.get("source") != "tag" and boxes and _poly_any(boxes, t["center_pt"]):
                n_term_equip += 1           # a circle / symbol inside a machine outline: a machine part
                continue
            k = "terminal" if t.get("source") == "tag" else classify_terminal(t, S, own, page, mpt, IX, LE)
            t2 = dict(t, kind=k)
            (dampers if k == "damper" else tout).append(t2)
        n_bends = len({d.get("bend_id") for d in keep if d.get("fitting") == "bend"})
        rep = {"ok": True, "ducts_in": len(ducts_in), "ducts_out": len(keep), "rejects": rejects, "merged": n_merged,
               "bends": n_bends,
               "added": added, "sized": cnt["sized"], "elevations": cnt["elev"], "labels": len(labels),
               "printed": len(printed), "labels_vtext": n_vtext, "equipment_boxes": len(boxes),
               "terminals_in": len(terms_in), "terminals_out": len(tout), "terminals_in_equipment": n_term_equip,
               "dampers": dampers, "dashed_runs": dashed_runs, "features": feats}
        return keep, tout, rep
    except Exception as e:  # noqa: BLE001  never raises: keep the input
        return ducts_in, terms_in, {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _grey_pen(page: dict, k: int) -> bool:
    return _grey(page["paths"][k]["stroke"])


def _poly_any(boxes: list, c) -> bool:
    P = np.asarray(c, float).reshape(1, 2)
    return any(bool(_poly_contains(b["poly"], P)[0]) for b in boxes)
