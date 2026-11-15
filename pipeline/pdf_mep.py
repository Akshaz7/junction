"""MEP (ventilation) sheet drawn over an architect underlay -> ducts + air terminals -> IfcDuctSegment/IfcAirTerminal
added to the ARK IFC built by pipeline.pdf_to_ifc.

    load(pdf_path, page_index=0) -> page        fast pypdfium2 read: paths (stroke/fill rgb, CTM-scaled width, dash,
                                                optional-content layer name) + words, page points, top-left, y down
    align(src_page, dst_page) -> T              similarity transform src pt -> dst pt from text both sheets share
                                                (room numbers, door/wall tags, grid bubbles): RANSAC over unique words
    separate(mep_page, ark_page=None, T=None)   which paths are the MEP layer; ladder:
                                                  1 "ocg"       optional-content layers (marked content /OC) by name
                                                  2 "geometric" style clusters (stroke rgb + width + dash) whose paths
                                                                coincide with the ARK sheet's linework after aligning
                                                                are underlay; leftover coincident paths dropped one by one
                                                  3 "style"     no ARK sheet: screened (mid-grey) clusters are underlay
    ducts(mep_page, sel, m_per_pt)              parallel MEP line pairs 100-1500 mm apart -> runs (centreline, width)
                                                + nearest size label ("400x200", "ø250")
    terminals(mep_page, sel, m_per_pt)          small closed square/round MEP symbols (+ "l/s" airflow label if near)
    build_ifc(model_ifc_path, ducts, terminals, *, ceiling_height=2.7, out_path=None, T=None, m_per_pt=None)
                                                copy of the ARK IFC + IfcDuctSegment / IfcAirTerminal on its storey
    overlay(...)                                2D check picture: underlay grey, MEP red, ducts blue, terminals green
    combine(ark_pdf, mep_pdf, ark_ifc, out_ifc) the whole thing, returns a report dict

Single sheet (an MEP sheet uploaded on its own already carries the architect underlay, screened grey):
    is_mep_sheet(pdf_path, page_index=0) -> bool       text gate (airflow l/s, duct sizes, type-size tags: >= 2 kinds,
                                                      >= 4 words) then grey-underlay split; never raises
    enrich_ifc(ifc_path, pdf_path, page_index, planmap) -> dict
                                                      ducts / fittings / terminals of that page added in place to the
                                                      IFC pdf_to_ifc built from the same page (same transform), in one
                                                      IfcDistributionSystem VENTILATION; atomic write

Coordinates: everything is converted into ARK page points first (T), then into the ARK IFC's plan metres the same
way pdf_to_ifc does (x_m = x_pt * m_per_pt, y_m = -y_pt * m_per_pt; m_per_pt read from the IFC's Hologram_Provenance).
No per-document constants: tolerances are in metres (through the scale) or relative to the page.
"""
from __future__ import annotations

import ctypes
import math
import os
import re
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

DUCT_MIN_M, DUCT_MAX_M = 0.10, 1.50          # duct widths we accept from a line pair
DUCT_MIN_LEN_M = 0.8                          # shortest duct run
TERM_MIN_M, TERM_MAX_M = 0.15, 0.9           # air terminal symbol size
DEFAULT_DUCT_H_M = 0.3
DASH_GAP_M = 0.5                              # exploded dash-dot linetypes: dashes this close are one line
TEXT_STROKES_PER_M = 20                       # tiny strokes per metre inside a "duct": vectorised text in a frame
MEP_DEFAULT_RATIO = 50                        # MEP plan scale assumed when the plan map's scale is only a guess
CEILING_GAP_M = 0.1                           # duct top sits this far under the ceiling
COINCIDE_TOL_M = 0.04                         # a path "is in the ARK sheet" if it lies within this of ARK linework
MEP_LAYER_RE = re.compile(r"vent|duct|hvac|mech|lvi|ilma|kanav|air|supply|exhaust|M-|IV|LVI|ventil", re.I)
SIZE_RE = re.compile(r"^(\d{2,4})\s*[x×X*]\s*(\d{2,4})$")
ROUND_RE = re.compile(r"^[øØ⌀Ф∅]\s*(\d{2,4})$")
FLOW_RE = re.compile(r"^[+\-−–]?\d{1,4}(?:[.,]\d)?$")


# ---------------------------------------------------------------- reading

def _mat_mul(a, b):
    a1, b1, c1, d1, e1, f1 = a
    a2, b2, c2, d2, e2, f2 = b
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def load(pdf_path, page_index: int = 0) -> dict:
    """Paths + words of one page. page["xy"]: (N,2) all path points (displayed pt); each path: {"i0","i1" (its points
    are xy[i0:i1]), "closed", "stroke": (r,g,b)|None (0-255), "fill": (r,g,b)|None, "width" (pt, CTM-scaled),
    "dashed", "layer": str|None (optional-content group), "curves": int}."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as R
    from pipeline.pdf_vector import _displayer, _words_pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        rot = page.get_rotation() % 360
        cl, cb, cr, ct = page.get_cropbox()
        W0, H0 = cr - cl, ct - cb
        disp = _displayer(rot, W0, H0, cl, cb)
        Wd, Hd = (H0, W0) if rot in (90, 270) else (W0, H0)
        # disp is affine: fold it into every CTM so points come out displayed directly
        o, ex, ey = disp(0.0, 0.0), disp(1.0, 0.0), disp(0.0, 1.0)
        D = (ex[0] - o[0], ex[1] - o[1], ey[0] - o[0], ey[1] - o[1], o[0], o[1])

        fx, fy = ctypes.c_float(), ctypes.c_float()
        bfx, bfy = ctypes.byref(fx), ctypes.byref(fy)
        ri, gi, bi, ai = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        bc = (ctypes.byref(ri), ctypes.byref(gi), ctypes.byref(bi), ctypes.byref(ai))
        fm, sk = ctypes.c_int(), ctypes.c_int()
        bfm, bsk = ctypes.byref(fm), ctypes.byref(sk)
        wv = ctypes.c_float()
        bwv = ctypes.byref(wv)
        M = R.FS_MATRIX()
        bM = ctypes.byref(M)
        buf = ctypes.create_string_buffer(512)
        ln = ctypes.c_ulong()
        GetSeg, GetPt, GetType, GetClose = (R.FPDFPath_GetPathSegment, R.FPDFPathSegment_GetPoint,
                                            R.FPDFPathSegment_GetType, R.FPDFPathSegment_GetClose)
        MOVE, BEZ = R.FPDF_SEGMENT_MOVETO, R.FPDF_SEGMENT_BEZIERTO
        xs, ys, paths = [], [], []
        layers = Counter()

        def matrix(obj):
            if R.FPDFPageObj_GetMatrix(obj, bM):
                return (M.a, M.b, M.c, M.d, M.e, M.f)
            return (1, 0, 0, 1, 0, 0)

        def rgb(getter, obj):
            if getter(obj, *bc) and ai.value:
                return (ri.value, gi.value, bi.value)
            return None

        def layer_of(obj, inherited):
            for i in range(R.FPDFPageObj_CountMarks(obj)):
                mk = R.FPDFPageObj_GetMark(obj, i)
                if not R.FPDFPageObjMark_GetName(mk, buf, 512, ctypes.byref(ln)):
                    continue
                if buf.raw[:max(0, ln.value - 2)].decode("utf-16le", "ignore") != "OC":
                    continue
                for key in (b"Name", b"name"):
                    if R.FPDFPageObjMark_GetParamStringValue(mk, key, buf, 512, ctypes.byref(ln)):
                        return buf.raw[:max(0, ln.value - 2)].decode("utf-16le", "ignore") or "OC"
                return "OC"
            return inherited

        def do_path(obj, m, layer):
            n = R.FPDFPath_CountSegments(obj)
            if n <= 0:
                return
            R.FPDFPath_GetDrawMode(obj, bfm, bsk)
            filled, stroked = fm.value != 0, bool(sk.value)
            if not filled and not stroked:
                return
            a, b, c, d, e, f = m
            stroke = rgb(R.FPDFPageObj_GetStrokeColor, obj) if stroked else None
            fill = rgb(R.FPDFPageObj_GetFillColor, obj) if filled else None
            width = 0.0
            if stroked and R.FPDFPageObj_GetStrokeWidth(obj, bwv):
                width = round(wv.value * math.sqrt(abs(a * d - b * c)), 3)
            dashed = stroked and R.FPDFPageObj_GetDashCount(obj) > 0
            i0, closed, curves, nb = len(xs), False, 0, 0

            def flush(i0, closed, curves):
                if len(xs) - i0 >= 2:
                    paths.append({"i0": i0, "i1": len(xs), "closed": closed or filled, "stroke": stroke,
                                  "fill": fill, "width": width, "dashed": dashed, "layer": layer, "curves": curves})
                else:
                    del xs[i0:], ys[i0:]
            # hot loop (~1M segments on an MEP sheet): type first, point only when kept, close flag only on the
            # last segment of each subpath (the one before a moveto, and the path's last)
            prev = None
            for k in range(n):
                seg = GetSeg(obj, k)
                t = GetType(seg)
                if t == MOVE:
                    if prev is not None and GetClose(prev):
                        closed = True
                        xs.append(xs[i0])
                        ys.append(ys[i0])
                    flush(i0, closed, curves)
                    i0, closed, curves, nb = len(xs), False, 0, 0
                elif t == BEZ:
                    nb += 1
                    if nb % 3 == 1:                  # keep curve ends + mid control: enough for symbol sizes
                        prev = seg
                        continue
                    if nb % 3 == 0:
                        curves += 1
                GetPt(seg, bfx, bfy)
                x, y = fx.value, fy.value
                xs.append(a * x + c * y + e)
                ys.append(b * x + d * y + f)
                prev = seg if t != MOVE else None
            if prev is not None and GetClose(prev):
                closed = True
                xs.append(xs[i0])
                ys.append(ys[i0])
            flush(i0, closed, curves)

        PATH, FORM = R.FPDF_PAGEOBJ_PATH, R.FPDF_PAGEOBJ_FORM
        probe = [0, False]       # marked content: probe the first objects; a page without any marks skips the calls

        def walk(get_count, get_obj, parent, depth, layer):
            for k in range(get_count()):
                obj = get_obj(k)
                t = R.FPDFPageObj_GetType(obj)
                if t != PATH and t != FORM:
                    continue        # text / image / shading objects: words come from the text layer
                lay = layer
                if probe[1] or probe[0] < 3000:
                    probe[0] += 1
                    if R.FPDFPageObj_CountMarks(obj) > 0:
                        probe[1] = True
                        lay = layer_of(obj, layer)
                if lay:
                    layers[lay] += 1
                if t == PATH:
                    do_path(obj, _mat_mul(matrix(obj), parent), lay)
                elif depth < 12:
                    m = _mat_mul(matrix(obj), parent)
                    walk(lambda o=obj: R.FPDFFormObj_CountObjects(o), lambda j, o=obj: R.FPDFFormObj_GetObject(o, j),
                         m, depth + 1, lay)

        raw = page.raw
        walk(lambda: R.FPDFPage_CountObjects(raw), lambda j: R.FPDFPage_GetObject(raw, j), D, 0, None)
        words = _words_pdfium(page, disp)
        page.close()
    finally:
        doc.close()
    xy = np.c_[np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)] if xs else np.zeros((0, 2))
    return {"W_pt": float(Wd), "H_pt": float(Hd), "rotate": rot, "xy": xy, "paths": paths, "words": words,
            "layers": dict(layers), "pdf": str(pdf_path), "page_index": page_index}


def pts(page, p) -> np.ndarray:
    return page["xy"][p["i0"]:p["i1"]]


def style_key(p) -> tuple:
    """Stroke colour + width (2 significant digits) + dash; fills keyed by colour."""
    if p["stroke"] is not None:
        w = p["width"]
        w = float(f"{w:.2g}") if w > 0 else 0.0
        return ("s", p["stroke"], w, p["dashed"])
    return ("f", p["fill"], 0.0, False)


def _seg_array(page, idx=None) -> tuple[np.ndarray, np.ndarray]:
    """Straight pieces of the page's paths (all, or path indices idx) as (N,4) x0,y0,x1,y1 + owning path index."""
    paths = page["paths"]
    idx = np.arange(len(paths)) if idx is None else np.asarray(idx, dtype=int)
    if not len(idx):
        return np.zeros((0, 4)), np.zeros(0, int)
    i0 = np.array([paths[i]["i0"] for i in idx])
    i1 = np.array([paths[i]["i1"] for i in idx])
    n = i1 - i0 - 1
    own = np.repeat(idx, n)
    start = np.repeat(i0 - (np.cumsum(n) - n), n) + np.arange(n.sum())
    xy = page["xy"]
    return np.c_[xy[start], xy[start + 1]], own


# ---------------------------------------------------------------- aligning two sheets of the same floor

def _norm_text(t: str) -> str:
    return re.sub(r"\s+", "", t).upper()


def _fit_similarity(A, B):
    """Least-squares similarity (scale, rotation, translation; no reflection) with B ~ s R A + t."""
    ma, mb = A.mean(0), B.mean(0)
    a, b = A - ma, B - mb
    H = a.T @ b
    U, S, Vt = np.linalg.svd(H)
    dd = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    Dm = np.diag([1.0, dd])
    Rm = Vt.T @ Dm @ U.T
    s = (S * np.diag(Dm)).sum() / max((a ** 2).sum(), 1e-12)
    t = mb - s * Rm @ ma
    return s, Rm, t


def apply_T(T, P):
    P = np.asarray(P, dtype=np.float64).reshape(-1, 2)
    return (T["s"] * (np.asarray(T["R"]) @ P.T)).T + np.asarray(T["t"])


def align(src: dict, dst: dict, *, iters: int = 400, seed: int = 0) -> dict | None:
    """Similarity transform src page pt -> dst page pt from words that appear exactly once on each sheet with the same
    text (two sheets of one floor share room numbers, tags and grid bubbles). RANSAC on 2-point fits, then a
    least-squares refit on the inliers. None when fewer than 4 words agree."""
    def uniq(page):
        c = Counter(_norm_text(w["text"]) for w in page["words"])
        out = {}
        for w in page["words"]:
            k = _norm_text(w["text"])
            if c[k] == 1 and len(k) >= 2 and re.search(r"[A-Z0-9]", k):
                b = w["bbox"]
                out[k] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        return out
    us, ud = uniq(src), uniq(dst)
    keys = sorted(set(us) & set(ud))
    if len(keys) < 4:
        return None
    A = np.array([us[k] for k in keys])
    B = np.array([ud[k] for k in keys])
    tol = 0.002 * math.hypot(dst["W_pt"], dst["H_pt"])
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iters):
        i, j = rng.choice(len(keys), 2, replace=False)
        if np.linalg.norm(A[i] - A[j]) < 20 * tol:
            continue
        s, Rm, t = _fit_similarity(A[[i, j]], B[[i, j]])
        if not (0.2 < s < 5):
            continue
        err = np.linalg.norm((s * (Rm @ A.T)).T + t - B, axis=1)
        inl = err < tol
        if best is None or inl.sum() > best.sum():
            best = inl
    if best is None or best.sum() < 4:
        return None
    s, Rm, t = _fit_similarity(A[best], B[best])
    err = np.linalg.norm((s * (Rm @ A[best].T)).T + t - B[best], axis=1)
    return {"s": float(s), "R": Rm.tolist(), "t": t.tolist(), "rot_deg": float(math.degrees(math.atan2(Rm[1, 0], Rm[0, 0]))),
            "n_words": int(len(keys)), "n_inliers": int(best.sum()), "rms_pt": float(np.sqrt((err ** 2).mean())),
            "method": "shared-text", "residual": float(np.sqrt((err ** 2).mean())), "matches": int(best.sum()),
            "T": _T3({"s": s, "R": Rm, "t": t.tolist()})}


# ---------------------------------------------------------------- separating the MEP layer

def _mask(segs: np.ndarray, W: float, H: float, cell: float, dilate: int) -> np.ndarray:
    nx, ny = int(W / cell) + 2, int(H / cell) + 2
    m = np.zeros((ny, nx), dtype=bool)
    if len(segs):
        L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
        n = np.maximum(1, np.ceil(L / (cell * 0.5)).astype(int))
        idx = np.repeat(np.arange(len(segs)), n + 1)
        tt = (np.arange(idx.size) - np.repeat(np.cumsum(n + 1) - (n + 1), n + 1)) / np.repeat(n, n + 1)
        x = segs[idx, 0] + (segs[idx, 2] - segs[idx, 0]) * tt
        y = segs[idx, 1] + (segs[idx, 3] - segs[idx, 1]) * tt
        ix, iy = np.clip((x / cell).astype(int), 0, nx - 1), np.clip((y / cell).astype(int), 0, ny - 1)
        m[iy, ix] = True
    for _ in range(dilate):
        d = m.copy()
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def _coverage(segs, own, n_paths, mask, cell) -> np.ndarray:
    """Per path: fraction of its length lying on the mask."""
    ny, nx = mask.shape
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    n = np.maximum(1, np.ceil(L / cell).astype(int))
    idx = np.repeat(np.arange(len(segs)), n)
    tt = (np.arange(idx.size) - np.repeat(np.cumsum(n) - n, n) + 0.5) / np.repeat(n, n)
    x = segs[idx, 0] + (segs[idx, 2] - segs[idx, 0]) * tt
    y = segs[idx, 1] + (segs[idx, 3] - segs[idx, 1]) * tt
    ix, iy = (x / cell).astype(int), (y / cell).astype(int)
    ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
    hit = np.zeros(idx.size, bool)
    hit[ok] = mask[iy[ok], ix[ok]]
    w = np.repeat(L / n, n)
    tot = np.bincount(own[idx], weights=w, minlength=n_paths)
    on = np.bincount(own[idx], weights=w * hit, minlength=n_paths)
    return np.where(tot > 0, on / np.maximum(tot, 1e-9), 1.0)


def _is_grey(c) -> bool:
    return c is not None and max(c) - min(c) <= 12 and 60 <= c[0] <= 230


def separate(mep: dict, ark: dict | None = None, T: dict | None = None, *, m_per_pt: float | None = None) -> dict:
    """{"method", "mep": bool ndarray per mep path, "clusters": [...], "stats": {...}}.
    T maps mep pt -> ark pt (from align)."""
    paths = mep["paths"]
    n = len(paths)
    keys = [style_key(p) for p in paths]
    # 1) optional content layers
    lay = [p.get("layer") for p in paths]
    names = {x for x in lay if x}
    if len(names) >= 2:
        mep_names = {x for x in names if MEP_LAYER_RE.search(x)}
        if mep_names and len(mep_names) < len(names):
            sel = np.array([x in mep_names for x in lay])
            return {"method": "ocg", "mep": sel, "layers": sorted(names), "mep_layers": sorted(mep_names),
                    "stats": _stats(sel, paths, np.ones(len(paths)))}
    segs, own = _seg_array(mep)
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]) if len(segs) else np.zeros(0)
    plen = np.bincount(own, weights=L, minlength=n)
    groups = defaultdict(list)
    for i, k in enumerate(keys):
        groups[k].append(i)
    clusters = []
    # 2) geometric difference against the ARK sheet, decided per style cluster then per path
    if ark is not None and T is not None:
        mpp = m_per_pt or 0.00035278 * 100
        tol_pt = COINCIDE_TOL_M / mpp            # in mep page points
        cell = max(tol_pt / 2, 0.25)
        aseg, _ = _seg_array(ark)
        Ti = invert_T(T)
        a0, a1 = apply_T(Ti, aseg[:, :2]), apply_T(Ti, aseg[:, 2:])
        mask = _mask(np.c_[a0, a1], mep["W_pt"], mep["H_pt"], cell, dilate=2)
        # ARK text the MEP sheet re-draws as linework (room names, areas, tags): the word boxes count as ARK ink
        ny, nx = mask.shape
        for w in ark["words"]:
            b = w["bbox"]
            q = apply_T(Ti, [[b[0], b[1]], [b[2], b[3]]])
            x0, y0 = (q.min(0) / cell).astype(int) - 2
            x1, y1 = (q.max(0) / cell).astype(int) + 3
            mask[max(0, y0):min(ny, y1), max(0, x0):min(nx, x1)] = True
        cov = _coverage(segs, own, n, mask, cell)
        sel = np.zeros(n, bool)
        for k, idx in groups.items():
            idx = np.array(idx)
            wl = plen[idx]
            c = float((cov[idx] * wl).sum() / max(wl.sum(), 1e-9))
            under = c >= 0.6
            clusters.append({"style": _kname(k), "paths": int(len(idx)), "length_pt": round(float(wl.sum())),
                             "coincident": round(c, 3), "underlay": bool(under)})
            if not under:
                sel[idx] = cov[idx] < 0.8         # leftover underlay pieces drawn in an MEP style
        clusters.sort(key=lambda c: -c["length_pt"])
        return {"method": "geometric", "mep": sel, "clusters": clusters, "coverage": cov,
                "stats": _stats(sel, paths, plen)}
    # 3) style only: screened grey = underlay
    grey_k = {k: _is_grey(k[1]) for k in groups}
    grey_len = sum(float(plen[idx].sum()) for k, idx in groups.items() if grey_k[k])
    sel = np.array([not grey_k[k] for k in keys])
    for k, idx in groups.items():
        clusters.append({"style": _kname(k), "paths": len(idx), "length_pt": round(float(plen[idx].sum())),
                         "underlay": _is_grey(k[1])})
    clusters.sort(key=lambda c: -c["length_pt"])
    if grey_len < 0.2 * plen.sum():
        return {"method": "none", "mep": np.zeros(n, bool), "clusters": clusters, "stats": _stats(np.zeros(n, bool), paths, plen)}
    return {"method": "style", "mep": sel, "clusters": clusters, "stats": _stats(sel, paths, plen)}


def _kname(k):
    kind, c, w, d = k
    return f"{'stroke' if kind == 's' else 'fill'} rgb{tuple(c) if c else None} w{w}{' dashed' if d else ''}"


def _stats(sel, paths, plen=None):
    return {"paths": len(paths), "mep_paths": int(sel.sum()), "underlay_paths": int((~sel).sum()),
            "mep_length_pt": round(float(plen[sel].sum())), "underlay_length_pt": round(float(plen[~sel].sum()))}


def invert_T(T):
    Rm = np.asarray(T["R"])
    Ri = Rm.T
    s = 1.0 / T["s"]
    t = -s * (Ri @ np.asarray(T["t"]))
    return {"s": s, "R": Ri.tolist(), "t": t.tolist()}


# ---------------------------------------------------------------- pictures

def overlay(page: dict, sel: np.ndarray, out_png, *, ducts=(), terms=(), max_side: int = 3000, title: str = ""):
    """White sheet: underlay paths grey, MEP paths red, duct runs blue outlines, terminals green."""
    from PIL import Image, ImageDraw
    k = max_side / max(page["W_pt"], page["H_pt"])
    im = Image.new("RGB", (int(page["W_pt"] * k) + 1, int(page["H_pt"] * k) + 1), "white")
    dr = ImageDraw.Draw(im)
    segs, own = _seg_array(page)
    for flag, col in ((False, (175, 175, 175)), (True, (220, 20, 20))):
        for s in segs[sel[own] == flag] * k:
            dr.line([(s[0], s[1]), (s[2], s[3])], fill=col, width=1)
    for d in ducts:
        q = [(x * k, y * k) for x, y in d["outline_pt"]]
        dr.polygon(q, outline=(20, 60, 230), width=3)
    for t in terms:
        x, y, r = t["center_pt"][0] * k, t["center_pt"][1] * k, max(4, t["size_pt"] * k / 2)
        dr.ellipse([x - r, y - r, x + r, y + r], outline=(0, 160, 60), width=3)
    if title:
        dr.text((10, 10), title, fill=(0, 0, 0))
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    im.save(out_png)
    return str(out_png)


# ---------------------------------------------------------------- ducts

def _merge_collinear(segs: np.ndarray, ang_q: float, off_q: float, gap: float, style=None) -> np.ndarray:
    """Join straight pieces of one pen (style id) lying on one line (angle bin + offset bin) whose gaps are <= gap
    (dash-dot linetypes are often exploded into separate dashes). Returns (N,9): theta, rho (normal offset), t0, t1
    (along u), unit u (ux, uy), style id, drawn length, owning closed-path id (-1 if several/open)."""
    d = segs[:, 2:] - segs[:, :2]
    th = np.mod(np.arctan2(d[:, 1], d[:, 0]), np.pi)
    ab = np.round(th / ang_q).astype(int) % int(round(np.pi / ang_q))
    thq = ab * ang_q
    u = np.c_[np.cos(thq), np.sin(thq)]
    nrm = np.c_[-u[:, 1], u[:, 0]]
    rho = (segs[:, :2] * nrm).sum(1)
    ta, tb = (segs[:, :2] * u).sum(1), (segs[:, 2:] * u).sum(1)
    t0, t1 = np.minimum(ta, tb), np.maximum(ta, tb)
    ob = np.round(rho / off_q).astype(int)
    sty = np.zeros(len(segs), int) if style is None else np.asarray(style[0])
    own = np.full(len(segs), -1) if style is None else np.asarray(style[1])
    if not len(segs):
        return np.zeros((0, 9))
    order = np.lexsort((t0, ob, ab, sty))
    sty, ab, ob, thq, rho, t0, t1, own = (x[order] for x in (sty, ab, ob, thq, rho, t0, t1, own))
    newkey = np.r_[True, (sty[1:] != sty[:-1]) | (ab[1:] != ab[:-1]) | (ob[1:] != ob[:-1])]
    kidx = np.cumsum(newkey) - 1
    big = float(np.abs(np.r_[t0, t1]).max()) * 4 + 1.0
    run = np.maximum.accumulate(t1 + kidx * big) - kidx * big      # running end of the current line (within the key)
    brk = newkey.copy()
    brk[1:] |= t0[1:] > run[:-1] + gap
    st = np.flatnonzero(brk)
    cnt = np.diff(np.r_[st, len(t0)])
    T0 = np.minimum.reduceat(t0, st)
    T1 = np.maximum.reduceat(t1, st)
    RHO = np.add.reduceat(rho, st) / cnt
    DRAWN = np.add.reduceat(t1 - t0, st)
    o_min, o_max = np.minimum.reduceat(own, st), np.maximum.reduceat(own, st)
    OWN = np.where(o_min == o_max, o_min, -1)
    TH = thq[st]
    return np.c_[TH, RHO, T0, T1, np.cos(TH), np.sin(TH), sty[st], DRAWN, OWN].astype(float)


def ducts(page: dict, sel: np.ndarray, m_per_pt: float, *, min_w: float = DUCT_MIN_M, max_w: float = DUCT_MAX_M,
          min_len: float = DUCT_MIN_LEN_M, wall_mode: bool = False) -> list[dict]:
    """Duct runs = pairs of parallel MEP lines min_w..max_w apart that run side by side for >= min_len.
    Hatching (3+ equally spaced parallels) is rejected. Width in metres from the pair gap; a size label
    ("400x200", "ø250") from the text layer within 1.5 m sets the section."""
    keep = [i for i in np.flatnonzero(sel) if page["paths"][i]["stroke"] is not None and not page["paths"][i]["dashed"]]
    segs, own = _seg_array(page, keep)
    if not len(segs):
        return []
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    ok = L * m_per_pt >= 0.005     # keep the dots of dash-dot lines: they bridge the gaps between dashes
    segs, own = segs[ok], own[ok]
    uo, inv = np.unique(own, return_inverse=True)       # per path, not per segment
    skeys = {}
    sid = np.array([skeys.setdefault(style_key(page["paths"][o]), len(skeys)) for o in uo], dtype=int)[inv]
    # closed small rectangles (label frames, symbols) keep their path id so their sides are not read as a duct
    cid = np.array([o if page["paths"][o]["closed"] and page["paths"][o]["i1"] - page["paths"][o]["i0"] <= 6 else -1
                    for o in uo], dtype=int)[inv]
    S = _merge_collinear(segs, math.radians(1.0), 0.01 / m_per_pt, DASH_GAP_M / m_per_pt, (sid, cid))
    # lines under 0.4 m can neither be a side (min_len) nor a "third line" (half of a >= 0.8 m run)
    S = S[((S[:, 3] - S[:, 2]) * m_per_pt >= min(0.4, min_len / 2)) & (S[:, 7] >= 0.4 * (S[:, 3] - S[:, 2]))]
    if not len(S):
        return []
    dmin, dmax, lmin = min_w / m_per_pt, max_w / m_per_pt, min_len / m_per_pt
    nb = int(round(180 / 1.0))
    ab = np.round(S[:, 0] / math.radians(1.0)).astype(int) % nb
    cand = []
    by = defaultdict(list)
    for i, b in enumerate(ab):
        by[(b, int(S[i, 6]))].append(i)      # both sides of one duct are drawn with the same pen
    LEN = S[:, 3] - S[:, 2]
    for _, idx in by.items():
        idx = np.array(idx)
        idx = idx[np.argsort(S[idx, 1])]
        rho = S[idx, 1]
        for a_, i in enumerate(idx):
            if LEN[i] < lmin:
                continue
            j0, j1 = np.searchsorted(rho, rho[a_] + dmin), np.searchsorted(rho, rho[a_] + dmax, side="right")
            js = idx[j0:j1]
            if not len(js):
                continue
            lo = np.maximum(S[i, 2], S[js, 2])
            hi = np.minimum(S[i, 3], S[js, 3])
            ov = hi - lo
            # side by side over most of both lines (fans of leader lines are staggered); a main duct's side is
            # broken at its branch take-offs, so the other side may be longer: the shorter side must be mostly
            # covered and the longer at least a third. Two sides of one small closed rectangle: frame/symbol.
            ok = ((ov >= lmin) & (ov >= 0.7 * np.minimum(LEN[i], LEN[js])) &
                  (ov >= 0.35 * np.maximum(LEN[i], LEN[js]) - 1.0 / m_per_pt) &
                  ~((S[i, 8] >= 0) & (S[js, 8] == S[i, 8])))
            for k in np.flatnonzero(ok):
                j = js[k]
                # a third parallel line drawn with the SAME pen between the two along most of the run: two
                # neighbouring ducts, not one wide duct. Other pens (centre lines, insulation, leaders, the
                # neighbour duct's dash-dot) do not count: corridor ducts are drawn side by side in mixed pens;
                # a same-pen centre line (middle 24 %) does not count either
                g = S[j, 1] - S[i, 1]
                mid = idx[a_ + 1:j0 + k]
                mid = mid[(S[mid, 1] > S[i, 1] + 0.05 * g) & (S[mid, 1] < S[j, 1] - 0.05 * g) &
                          (np.abs(S[mid, 1] - (S[i, 1] + S[j, 1]) / 2) > 0.12 * g)]
                if len(mid) and np.any(np.minimum(S[mid, 3], hi[k]) - np.maximum(S[mid, 2], lo[k]) >= 0.5 * ov[k]):
                    continue
                cand.append((g, i, j, lo[k], hi[k]))
    cand.sort()
    used_lo, used_hi, pairs = defaultdict(list), defaultdict(list), []

    def free(spans, lo, hi):
        return all(min(hi, b) - max(lo, a) <= 0.2 * (hi - lo) for a, b in spans)
    for gap, i, j, lo, hi in cand:      # nearest partner first; each stretch of a line pairs once per side
        if not free(used_lo[i], lo, hi) or not free(used_hi[j], lo, hi):
            continue
        used_lo[i].append((lo, hi))
        used_hi[j].append((lo, hi))
        pairs.append((gap, i, j, lo, hi))
    # hatching / stacked runs: a line that is the upper side of one pair and the lower of another at a similar gap
    up = {}
    for g, i, j, lo, hi in pairs:
        up.setdefault(j, (g, i))
    hatch = set()
    for g, i, j, lo, hi in pairs:      # chain of >= 3 pairs at one spacing
        chain, cur = [j, i], i
        while cur in up and abs(up[cur][0] - g) <= 0.1 * g:
            cur = up[cur][1]
            chain.append(cur)
        if len(chain) >= 4:
            hatch.update(chain)
    words = page["words"]
    labels = []
    for w in words:
        t = w["text"].strip()
        m1, m2 = SIZE_RE.match(t), ROUND_RE.match(t)
        if m1 or m2:
            b = w["bbox"]
            labels.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, t,
                           ("rect", int(m1.group(1)), int(m1.group(2))) if m1 else ("round", int(m2.group(1)), int(m2.group(1)))))
    # ink inside the run (sides excluded): text frames and symbol rows are full of glyph strokes, ducts are empty
    cell = 0.05 / m_per_pt
    allseg, _ = _seg_array(page, np.flatnonzero(sel))
    ink = _mask(allseg, page["W_pt"], page["H_pt"], cell, dilate=0)
    # short strokes only (glyphs, symbol details): centre lines, insulation outlines and leaders crossing a duct
    # are long and must not make its inside look "full"
    dxy = allseg[:, 2:] - allseg[:, :2]
    sl = np.hypot(dxy[:, 0], dxy[:, 1])
    short = sl * m_per_pt < 0.25
    glyph = _mask(allseg[short], page["W_pt"], page["H_pt"], cell, dilate=0)
    # clutter masks for axis-aligned runs: short strokes NOT parallel to the run (dashes of a centre line are)
    cs = np.abs(dxy[:, 0]) / np.maximum(sl, 1e-9)
    clutter = {0: _mask(allseg[short & (cs < 0.97)], page["W_pt"], page["H_pt"], cell, dilate=0),
               1: _mask(allseg[short & (cs > 0.26)], page["W_pt"], page["H_pt"], cell, dilate=0)}
    ny, nx = ink.shape
    # vectorised text (labels drawn as strokes): many tiny strokes per metre. Counts of tiny-stroke midpoints per
    # cell, without the strokes parallel to the run (dashes of a centre line)
    tiny = sl * m_per_pt < 0.15
    mid_xy = (allseg[:, :2] + allseg[:, 2:]) / 2

    def count_grid(m):
        g_ = np.zeros((ny, nx), np.int32)
        q = mid_xy[m]
        np.add.at(g_, (np.clip((q[:, 1] / cell).astype(int), 0, ny - 1), np.clip((q[:, 0] / cell).astype(int), 0, nx - 1)), 1)
        return g_
    tcount = {0: count_grid(tiny & (cs < 0.97)), 1: count_grid(tiny & (cs > 0.26)), 2: count_grid(tiny)}
    try:
        rej = _pair_rejector(page, sel, S, m_per_pt)
    except Exception:  # noqa: BLE001  new rules are optional: fall back to the previous behaviour
        rej = None
    out = []
    for g, i, j, lo, hi in pairs:
        if i in hatch or j in hatch:
            continue
        if wall_mode:       # wall bands (pair_walls): partitions meet other walls without end caps and carry
            pass            # poche hatching, so the duct-only rules below (ends, clutter, text frames) do not apply
        elif rej is not None and rej(i, j, lo, hi):
            continue        # encloses text / grid-line pair / leader or dimension pair
        u = S[i, 4:6]
        nrm = np.array([-u[1], u[0]])
        if not wall_mode:
            ts = np.linspace(lo, hi, max(2, int((hi - lo) / cell)))
            rs = np.linspace(S[i, 1] + 0.2 * g, S[j, 1] - 0.2 * g, max(2, int(0.6 * g / cell)))
            TT, RR = np.meshgrid(ts, rs)
            X, Y = TT * u[0] + RR * nrm[0], TT * u[1] + RR * nrm[1]
            ix, iy = np.clip((X / cell).astype(int), 0, nx - 1), np.clip((Y / cell).astype(int), 0, ny - 1)
            cm = clutter[0] if abs(u[0]) > 0.97 else clutter[1] if abs(u[1]) > 0.97 else glyph
            G = cm[iy, ix]
            G = G[ink[iy, ix].mean(axis=1) < 0.6]   # rows along a parallel line (centre line, insulation) are not clutter
            if G.size and G.mean() > 0.15:
                continue        # text frame / symbol row
            tc = tcount[0] if abs(u[0]) > 0.97 else tcount[1] if abs(u[1]) > 0.97 else tcount[2]
            cells = np.unique(iy * nx + ix)
            if tc.ravel()[cells].sum() / max((hi - lo) * m_per_pt, 1e-6) > TEXT_STROKES_PER_M:
                continue        # a label frame around vectorised text
            # ends: a duct run is closed by an end cap or opens into a fitting / branch, so ink crosses its mouth at
            # one end at least; a pair of leader lines has nothing across either end
            def mouth(t):
                tt = np.linspace(t - 0.08 / m_per_pt, t + 0.08 / m_per_pt, 5)
                rr = np.linspace(S[i, 1] + 0.25 * g, S[j, 1] - 0.25 * g, max(3, int(0.5 * g / cell)))
                A, B = np.meshgrid(tt, rr)
                X, Y = A * u[0] + B * nrm[0], A * u[1] + B * nrm[1]
                ix, iy = np.clip((X / cell).astype(int), 0, nx - 1), np.clip((Y / cell).astype(int), 0, ny - 1)
                return ink[iy, ix].any(axis=1).mean()

            def texty(t, sgn):   # ink density just beyond an end: text (labels, tags) is dense
                tt = np.linspace(t, t + sgn * 0.5 / m_per_pt, 10)
                rr = np.linspace(S[i, 1] - 0.25 / m_per_pt, S[j, 1] + 0.25 / m_per_pt, 10)
                A, B = np.meshgrid(tt, rr)
                X, Y = A * u[0] + B * nrm[0], A * u[1] + B * nrm[1]
                ix, iy = np.clip((X / cell).astype(int), 0, nx - 1), np.clip((Y / cell).astype(int), 0, ny - 1)
                return glyph[iy, ix].mean()
            m0, m1 = mouth(lo), mouth(hi)
            broken = (S[i, 7] < 0.9 * (S[i, 3] - S[i, 2])) or (S[j, 7] < 0.9 * (S[j, 3] - S[j, 2]))
            if max(m0, m1) < 0.5 and not broken:
                continue        # open at both ends and solid: leader / dimension lines (pairs with a broken (dash-dot) side are
                #                 exempt: hidden ducts above the ceiling, and leaders are never drawn broken)
            if (hi - lo) * m_per_pt < 1.5 and max(texty(lo, -1), texty(hi, 1)) > 0.25:
                continue        # short pair ending in text: a label frame or a leader into its tag
        u = S[i, 4:6]
        nrm = np.array([-u[1], u[0]])
        rm = (S[i, 1] + S[j, 1]) / 2
        p0, p1 = u * lo + nrm * rm, u * hi + nrm * rm
        half = nrm * g / 2
        d = {"start_pt": p0.tolist(), "end_pt": p1.tolist(), "width_pt": float(g), "width_m": round(g * m_per_pt, 3), "width_drawn_m": round(g * m_per_pt, 3),
             "length_m": round((hi - lo) * m_per_pt, 3), "shape": "rect", "height_m": None, "label": None,
             "outline_pt": [(p0 - half).tolist(), (p1 - half).tolist(), (p1 + half).tolist(), (p0 + half).tolist()]}
        best = None
        for lx, ly, t, (shape, a, b) in labels:
            q = np.array([lx, ly])
            tt = np.clip((q - p0) @ u, 0, hi - lo)
            dist = np.linalg.norm(p0 + u * tt - q) * m_per_pt
            if dist <= 1.5 and (best is None or dist < best[0]):
                best = (dist, t, shape, a, b)
        if best:
            d["label"], d["shape"] = best[1], best[2]
            if best[2] == "round":
                d["diameter_m"] = best[3] / 1000
                if abs(d["diameter_m"] - d["width_m"]) > 0.5 * d["diameter_m"]:
                    d["label"], d["shape"] = None, "rect"   # the ø label belongs to another (round) duct nearby
                    d.pop("diameter_m")
                else:
                    d["label_across_m"] = d["diameter_m"]
            else:   # "WxH": the drawn width tells which of the two numbers is across the plan
                a, b = best[3] / 1000, best[4] / 1000
                across, d["height_m"] = (a, b) if abs(a - d["width_m"]) <= abs(b - d["width_m"]) else (b, a)
                if abs(across - d["width_m"]) <= 0.35 * across:
                    d["width_m"] = across       # the printed size wins over the measured gap
                    d["label_across_m"] = across
        out.append(d)
    out = _dedupe(_on_grid(page, sel, out), m_per_pt)
    if len(out) >= 5:   # one wide "duct" spanning several: cap at 3x the typical run width
        wmed = float(np.median([d["width_m"] for d in out]))
        out = [d for d in out if d["width_m"] <= 3 * wmed]
    return out


LAST_REJECTS: Counter = Counter()      # reasons from the last ducts() call (diagnostics)
PT_PER_MM = 72 / 25.4       # paper millimetre in points: symbol/text/bubble sizes are fixed on paper at any scale


LABEL_RE = re.compile(r"[øØ⌀∅Ф]\s*\d|\d{2,4}\s*[x×X*]\s*\d{2,4}|l/s|^[+\-−–]?\d|^h=", re.I)


def _is_label(t: str) -> bool:
    """Duct size / airflow / level labels written inside or along a run (kept: they belong to the duct)."""
    return bool(LABEL_RE.search(t.strip()))


def _pair_rejector(page: dict, sel: np.ndarray, S: np.ndarray, m_per_pt: float):
    """Rules against the commonest false duct pairs (sizes on paper in mm, run lengths in metres):
      - label frame / table row: the pair encloses text (not its own size/airflow label) over >= 30 % of its length,
        or hugs it (gap <= 2.5 x text height);
      - grid lines: a side ends in a grid bubble (circle 4-16 mm on the line's extension), or both sides run over
        >= 60 % of the drawing's extent;
      - leaders / dimension lines: a side ends at an arrowhead / tick (small filled mark), or a short pair (< 3 m)
        whose sides both end on (non-label) text.
    Returns rej(i, j, lo, hi) -> bool."""
    mm = PT_PER_MM
    W = [w for w in page["words"] if w["text"].strip()]
    WB = np.array([w["bbox"] for w in W], float).reshape(-1, 4)
    lab = np.array([_is_label(w["text"]) for w in W], bool)
    WC = (WB[:, :2] + WB[:, 2:]) / 2
    WS = WB[:, 2:] - WB[:, :2]
    th = np.minimum(WS[:, 0], WS[:, 1])                 # text height (rotated words: the smaller side)
    circ, arrow = [], []
    for p in page["paths"]:
        if not p["closed"]:
            continue
        P = page["xy"][p["i0"]:p["i1"]]
        w_, h_ = np.ptp(P[:, 0]), np.ptp(P[:, 1])
        if p["curves"] >= 3 and 4 * mm <= max(w_, h_) <= 16 * mm and max(w_, h_) <= 1.2 * min(w_, h_):
            circ.append(((P.min(0) + P.max(0)) / 2, max(w_, h_) / 2))
        elif p["fill"] is not None and p["fill"] != (255, 255, 255) and 0.4 * mm <= max(w_, h_) <= 4 * mm \
                and p["i1"] - p["i0"] <= 6:
            arrow.append((P.min(0) + P.max(0)) / 2)
    CC = np.array([c for c, _ in circ], float).reshape(-1, 2)
    CR = np.array([r for _, r in circ], float)
    AR = np.array(arrow, float).reshape(-1, 2)
    under = np.flatnonzero(~sel) if (~sel).sum() > 100 else np.arange(len(page["paths"]))
    us, _ = _seg_array(page, under)
    if len(us) > 50:
        Q = np.r_[us[:, :2], us[:, 2:]]
        ext = np.percentile(Q, 98, axis=0) - np.percentile(Q, 2, axis=0)
    else:
        ext = np.array([page["W_pt"], page["H_pt"]], float)

    def ends(k):
        u = S[k, 4:6]
        n = np.array([-u[1], u[0]])
        return [(u * S[k, 2] + n * S[k, 1], -u), (u * S[k, 3] + n * S[k, 1], u)]

    def bubble(k):
        if not len(CC):
            return False
        for e, out in ends(k):
            d = CC - e
            along, perp = d @ out, np.abs(d @ np.array([-out[1], out[0]]))
            if np.any((along >= -0.3 * CR) & (along <= 1.6 * CR + mm) & (perp <= 0.4 * CR + 0.5 * mm)):
                return True
        return False

    def arrowed(k):
        if not len(AR):
            return False
        return any(np.any(np.hypot(*(AR - e).T) <= 2.5 * mm) for e, _ in ends(k))

    def on_text(k):
        if not len(WB):
            return False
        for e, _ in ends(k):
            pad = 1.0 * mm
            if np.any(~lab & (WB[:, 0] - pad <= e[0]) & (e[0] <= WB[:, 2] + pad) &
                      (WB[:, 1] - pad <= e[1]) & (e[1] <= WB[:, 3] + pad)):
                return True
        return False

    def rej(i, j, lo, hi):
        u = S[i, 4:6]
        n = np.array([-u[1], u[0]])
        g = S[j, 1] - S[i, 1]
        L = hi - lo
        if len(WB):
            tc, rc = WC @ u, WC @ n
            inside = ~lab & (tc >= lo) & (tc <= hi) & (rc > S[i, 1]) & (rc < S[j, 1])
            if inside.any():
                along = np.abs(WS[inside, 0] * u[0]) + np.abs(WS[inside, 1] * u[1])
                if along.sum() >= 0.3 * L or g <= 2.5 * float(np.median(th[inside])):
                    return _why("encloses text")
        span = abs(u[0]) * ext[0] + abs(u[1]) * ext[1]
        if min(S[i, 3] - S[i, 2], S[j, 3] - S[j, 2]) >= 0.6 * span:
            return _why("full span")
        if bubble(i) or bubble(j):
            return _why("grid bubble")
        if L * m_per_pt < 3.0 and arrowed(i) and arrowed(j):
            return _why("arrows")
        if L * m_per_pt < 3.0 and on_text(i) and on_text(j):
            return _why("ends on text")
        return False
    why = Counter()

    def _why(r):
        why[r] += 1
        return True
    rej.why = why
    global LAST_REJECTS
    LAST_REJECTS = why
    return rej


def _on_grid(page: dict, sel: np.ndarray, D: list[dict], tol_deg: float = 2.0) -> list[dict]:
    """Ducts follow the building's axes; leader lines (the commonest false pair) run at any angle. Keep runs within
    tol_deg of the drawing's dominant axes (length-weighted angle histogram of the underlay, mod 90 deg) or of the
    second strongest axis family (a wing drawn at an angle)."""
    if not D:
        return D
    under = np.flatnonzero(~sel) if (~sel).sum() > 100 else np.arange(len(page["paths"]))
    segs, _ = _seg_array(page, under)
    if not len(segs):
        return D
    d = segs[:, 2:] - segs[:, :2]
    L = np.hypot(d[:, 0], d[:, 1])
    a = np.degrees(np.mod(np.arctan2(d[:, 1], d[:, 0]), np.pi / 2))
    h, _ = np.histogram(a, bins=90, range=(0, 90), weights=L)
    peaks = [int(np.argmax(h))]
    h2 = h.copy()
    for k in range(-4, 5):
        h2[(peaks[0] + k) % 90] = 0
    if h2.max() > 0.25 * h.max():
        peaks.append(int(np.argmax(h2)))
    axes = [p + 0.5 for p in peaks]
    keep = []
    for x in D:
        v = np.subtract(x["end_pt"], x["start_pt"])
        ang = math.degrees(math.atan2(v[1], v[0])) % 90
        if any(min(abs(ang - ax), 90 - abs(ang - ax)) <= tol_deg for ax in axes):
            keep.append(x)
    return keep


def _dedupe(D: list[dict], m_per_pt: float) -> list[dict]:
    """A duct drawn with an insulation outline (or doubled pens) gives nested pairs along one run: keep the narrowest
    of parallel runs whose centre lines lie within half the wider width and overlap for most of the shorter."""
    if not D:
        return D
    A = np.array([d["start_pt"] for d in D], float)
    B = np.array([d["end_pt"] for d in D], float)
    Wd = np.array([d["width_pt"] for d in D], float)
    L = np.linalg.norm(B - A, axis=1)
    U = (B - A) / np.maximum(L, 1e-9)[:, None]
    N = np.c_[-U[:, 1], U[:, 0]]
    kept = []
    for k in np.argsort(Wd, kind="stable"):
        if L[k] <= 0:
            continue
        if kept:
            K = np.array(kept)
            par = np.abs(U[K] @ U[k]) >= 0.995
            off = np.abs(((A[k] - A[K]) * N[K]).sum(1)) <= 0.5 * np.maximum(Wd[k], Wd[K]) + 0.02 / m_per_pt
            ta = ((A[k] - A[K]) * U[K]).sum(1)
            tb = ((B[k] - A[K]) * U[K]).sum(1)
            ov = np.minimum(np.maximum(ta, tb), L[K]) - np.maximum(np.minimum(ta, tb), 0.0)
            if np.any(par & off & (ov >= 0.5 * np.minimum(L[k], L[K]))):
                continue
        kept.append(k)
    return [D[k] for k in sorted(kept)]


def clip_to_outline(ducts_, terminals_, ark_ifc, T=None, margin_m: float = 1.0):
    """Keep MEP items whose midpoint lies inside the ARK building outline (the slab pdf_to_ifc lays under the
    footprint; walls' hull if there is no slab), after mapping MEP pt -> ARK pt (T) -> plan metres."""
    import ifcopenshell
    from shapely.geometry import MultiPoint, Point, Polygon
    from shapely.ops import unary_union
    f = ifcopenshell.open(str(ark_ifc))
    mpt = _ark_scale(f)
    polys = []
    for s in f.by_type("IfcSlab"):
        for rep in (s.Representation.Representations if s.Representation else []):
            for it in rep.Items:
                try:
                    pts = it.SweptArea.OuterCurve.Points.CoordList
                    polys.append(Polygon([(x, y) for x, y in pts]))
                except Exception:  # noqa: BLE001
                    pass
    if polys:
        outline = unary_union([p.buffer(0) for p in polys])
    else:
        pts = []
        for w in f.by_type("IfcWall"):
            try:
                pts += [(x, y) for x, y in w.Representation.Representations[0].Items[0].SweptArea.OuterCurve.Points.CoordList]
            except Exception:  # noqa: BLE001
                pass
        if len(pts) < 3:
            return ducts_, terminals_
        outline = MultiPoint(pts).convex_hull
    outline = outline.buffer(margin_m)

    def inside(p):
        q = apply_T(T, p)[0] if T else np.asarray(p, float)
        return outline.contains(Point(q[0] * mpt, -q[1] * mpt))
    D = [d for d in ducts_ if inside((np.array(d["start_pt"]) + np.array(d["end_pt"])) / 2)]
    TT = [t for t in terminals_ if inside(t["center_pt"])]
    return D, TT


def terminals(page: dict, sel: np.ndarray, m_per_pt: float) -> list[dict]:
    """Air terminals: small closed MEP symbols, roughly square (square/rectangular diffusers) or round (curves),
    TERM_MIN_M..TERM_MAX_M across; concentric symbols merge into one. Airflow from a "<n> l/s" text within 2 m."""
    cands = []
    for i in np.flatnonzero(sel):
        p = page["paths"][i]
        if not p["closed"] or p["dashed"]:
            continue
        P = pts(page, p)
        w, h = np.ptp(P[:, 0]) * m_per_pt, np.ptp(P[:, 1]) * m_per_pt
        if not (TERM_MIN_M <= min(w, h) and max(w, h) <= TERM_MAX_M and max(w, h) <= 1.25 * min(w, h)):
            continue
        keep = np.r_[True, np.any(np.abs(np.diff(P, axis=0)) > 1e-6, axis=1)]
        Q = P[keep]
        n = len(Q) - 1 if np.allclose(Q[0], Q[-1]) else len(Q)     # corners
        round_ = p["curves"] >= 3
        if not round_ and n != 4:
            continue        # squares only (4 corners): keeps hatching/text glyph loops out
        c = (P.min(0) + P.max(0)) / 2
        cands.append((c, max(w, h) / m_per_pt, round_))
    cands.sort(key=lambda c: -c[1])
    out = []
    for c, s, r in cands:
        if any(np.linalg.norm(c - np.array(o["center_pt"])) * m_per_pt < 0.5 * o["size_m"] for o in out):
            continue        # inner ring of a symbol already taken
        out.append({"center_pt": c.tolist(), "size_pt": float(s), "size_m": round(s * m_per_pt, 3),
                    "shape": "round" if r else "square", "airflow_ls": None, "label": None})
    # airflow labels: a number word followed by "l/s" (or "123l/s")
    W = page["words"]
    flows = []
    for k, w in enumerate(W):
        t = w["text"].strip().replace("−", "-")
        m = re.match(r"^([+\-]?\d{1,4}(?:[.,]\d)?)\s*l/s$", t, re.I)
        if m:
            flows.append((w["bbox"], float(m.group(1).replace(",", "."))))
        elif t.lower() == "l/s" and k > 0 and FLOW_RE.match(W[k - 1]["text"].strip()):
            b0, b1 = W[k - 1]["bbox"], w["bbox"]
            flows.append(([min(b0[0], b1[0]), min(b0[1], b1[1]), max(b0[2], b1[2]), max(b0[3], b1[3])],
                          float(W[k - 1]["text"].strip().replace("−", "-").replace(",", "."))))
    for b, v in flows:
        q = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])
        best = min(out, key=lambda o: np.linalg.norm(q - np.array(o["center_pt"])), default=None)
        if best is not None and np.linalg.norm(q - np.array(best["center_pt"])) * m_per_pt <= 2.0 and best["airflow_ls"] is None:
            best["airflow_ls"], best["label"] = v, f"{v:+g} l/s"
    return out


# ---------------------------------------------------------------- IFC

def _ark_scale(f) -> float:
    import ifcopenshell.util.element as ue
    for st in f.by_type("IfcBuildingStorey"):
        pv = ue.get_psets(st).get("Hologram_Provenance") or {}
        if pv.get("m_per_pt"):
            return float(pv["m_per_pt"])
    raise ValueError("ARK IFC has no Hologram_Provenance.m_per_pt on its storey (not from pdf_to_ifc?)")


def _fittings(ducts_: list[dict], m_per_pt: float) -> list[dict]:
    """Bends and tees where duct runs meet: an end of one run within 3/4 of the wider width (+5 cm) of another run
    at an angle (> 30 deg). End to end = BEND, end into the side of another = JUNCTION (tee). Page points."""
    if len(ducts_) < 2:
        return []
    A = np.array([d["start_pt"] for d in ducts_], float)
    B = np.array([d["end_pt"] for d in ducts_], float)
    Wd = np.array([d["width_pt"] if "width_pt" in d else d["width_m"] / m_per_pt for d in ducts_], float)
    L = np.linalg.norm(B - A, axis=1)
    U = (B - A) / np.maximum(L, 1e-9)[:, None]
    out, seen = [], []
    for i in range(len(ducts_)):
        for p in (A[i], B[i]):
            t = np.clip(((p - A) * U).sum(1), 0, L)
            Q = A + U * t[:, None]
            dist = np.linalg.norm(p - Q, axis=1)
            tol = 0.75 * np.maximum(Wd[i], Wd) + 0.05 / m_per_pt   # a branch ends on its parent's side
            ok = (dist <= tol) & (np.abs(U @ U[i]) <= 0.866)
            ok[i] = False
            for j in np.flatnonzero(ok):
                kind = "BEND" if min(t[j], L[j] - t[j]) <= tol[j] else "JUNCTION"
                at = Q[j] if kind == "JUNCTION" else (p + Q[j]) / 2
                if any(np.linalg.norm(at - s_) < tol[j] for s_ in seen):
                    continue
                seen.append(at)
                out.append({"center_pt": at.tolist(), "kind": kind, "size_m": round(float(max(Wd[i], Wd[j])) * m_per_pt, 3),
                            "runs": [int(i), int(j)]})
    return out


def _add_mep(f, w, st, ducts_, terminals_, fittings_, plan, *, ceiling_height: float, building=None,
             ceiling_source: str = "default") -> dict:
    """IfcDuctSegment / IfcDuctFitting / IfcAirTerminal in storey st + one IfcDistributionSystem (VENTILATION) that
    groups them (IfcRelAssignsToGroup) and serves the building. plan(pt) -> plan metres (x, y)."""
    import ifcopenshell.api.spatial
    import ifcopenshell.api.style
    import ifcopenshell.api.system
    import ifcopenshell.guid
    sp = st.ObjectPlacement

    def style(key, rgb):
        if key not in w.styles:
            s = ifcopenshell.api.style.add_style(f, name=f"pdf_{key}")
            ifcopenshell.api.style.add_surface_style(f, style=s, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "Transparency": 0.0})
            w.styles[key] = s
        return w.styles[key]

    def put(product, item, key, rgb):
        rep = f.createIfcShapeRepresentation(w.body, "Body", "SweptSolid", [item])
        product.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        product.ObjectPlacement = w.placement(sp)
        ifcopenshell.api.style.assign_representation_styles(f, shape_representation=rep, styles=[style(key, rgb)])

    def safe_pset(e, name, props):
        try:
            w.pset(e, name, props)
        except Exception:  # noqa: BLE001  (a property the template rejects must not lose the element)
            pass

    made = {"ducts": 0, "duct_length_m": 0.0, "fittings": 0, "terminals": 0}
    products = []
    void_top = ceiling_height - CEILING_GAP_M
    dmax = 0.0
    for k, d in enumerate(ducts_):
        a, b = np.array(plan(d["start_pt"])), np.array(plan(d["end_pt"]))
        L = float(np.linalg.norm(b - a))
        if L < 0.05:
            continue
        u = (b - a) / L
        round_ = d.get("shape") == "round"
        wid = float(d.get("diameter_m") or d["width_m"]) if round_ else float(d["width_m"])
        h = wid if round_ else float(d.get("height_m") or min(DEFAULT_DUCT_H_M, wid))
        dmax = max(dmax, h)
        zc = void_top - h / 2
        zsrc = f"top {CEILING_GAP_M} m under ceiling {ceiling_height:.2f} m ({ceiling_source})"
        try:  # printed duct elevation from pdf_ducts (KL centre / AK bottom / YK top, absolute level in m)
            if d.get("elev_m") is not None and getattr(st, "Elevation", None) is not None:
                zc = float(d["elev_m"]) - float(st.Elevation) + {"centre": 0.0, "bottom": h / 2, "top": -h / 2}.get(d.get("elev_ref"), 0.0)
                zsrc = f"printed elevation {float(d['elev_m']):.3f} m ({d.get('elev_ref') or 'centre'})"
        except Exception:  # noqa: BLE001
            pass
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(a[0]), float(a[1]), float(zc))),
                                          f.createIfcDirection((float(u[0]), float(u[1]), 0.0)),
                                          f.createIfcDirection((float(-u[1]), float(u[0]), 0.0)))
        prof = (f.createIfcCircleProfileDef("AREA", None, None, wid / 2) if round_ else
                f.createIfcRectangleProfileDef("AREA", None, None, wid, h))   # local x across, y up
        solid = f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), L)
        e = w.entity("IfcDuctSegment", f"duct{k}", name=d.get("label") or f"Duct {wid * 1000:.0f}"
                     + ("" if round_ else f"x{h * 1000:.0f}"), predefined="RIGIDSEGMENT")
        put(e, solid, "duct", (0.55, 0.62, 0.72))
        safe_pset(e, "Pset_DuctSegmentTypeCommon", {"Shape": "ROUND" if round_ else "RECTANGULAR",
                                                     "NominalDiameterOrWidth": round(wid, 3),
                                                     "NominalHeight": None if round_ else round(h, 3)})
        try:
            w.qto(e, "Qto_DuctSegmentBaseQuantities", {"Length": L})
        except Exception:  # noqa: BLE001
            pass
        w.pset(e, "Hologram_MEP", {"width_m": round(wid, 3), "height_m": round(h, 3), "size_label": d.get("label"),
                                   "height_source": "label" if d.get("height_m") or round_ else "default",
                                   "source": "pdf_mep pair of parallel MEP lines"})
        lab = d.get("label")
        safe_pset(e, "Hologram_Evidence", {
            "Source": "printed" if lab else "measured",
            "Detail": (f"width {wid:.3f} m " + (f"from printed size label '{lab}'" if lab else
                       f"measured: drawn band {float(d.get('width_pt') or 0):.2f} pt between two parallel MEP lines")
                       + f"; run page pt {[round(v, 1) for v in d['start_pt']]}->{[round(v, 1) for v in d['end_pt']]}"
                       + f"; depth {h:.3f} m " + ("printed (size label)" if (d.get("height_m") or round_) and lab
                                                  else "default (no printed depth)")
                       + f"; {zsrc}"
                       + (f"; {d['evidence']}" if isinstance(d.get("evidence"), str) else ""))})
        w.provenance(e, {"item_id": f"duct{k}"})
        products.append(e)
        made["ducts"] += 1
        made["duct_length_m"] += L
    for k, t in enumerate(fittings_):
        c = np.array(plan(t["center_pt"]))
        s = float(t["size_m"])
        h = min(DEFAULT_DUCT_H_M, s)
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(c[0]), float(c[1]), float(void_top - h))),
                                          None, None)
        solid = f.createIfcExtrudedAreaSolid(f.createIfcRectangleProfileDef("AREA", None, None, s * 1.1, s * 1.1),
                                             pos, f.createIfcDirection((0.0, 0.0, 1.0)), h)
        e = w.entity("IfcDuctFitting", f"fitting{k}", name=f"{t['kind'].title()} {s * 1000:.0f}", predefined=t["kind"])
        put(e, solid, "duct_fitting", (0.45, 0.52, 0.62))
        w.pset(e, "Hologram_MEP", {"kind": t["kind"], "size_m": s, "source": "pdf_mep meeting duct runs"})
        safe_pset(e, "Hologram_Evidence", {"Source": "derived", "Detail": f"{t['kind']} where detected duct runs meet "
                                           f"at page pt {[round(v, 1) for v in t['center_pt']]}; size = run width"})
        w.provenance(e, {"item_id": f"fitting{k}"})
        products.append(e)
        made["fittings"] += 1
    term_z = ceiling_height - 0.05      # face flush with the ceiling (no printed terminal level is read)
    for k, t in enumerate(terminals_):
        c = np.array(plan(t["center_pt"]))
        s = float(t["size_m"])
        th = 0.05
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(c[0]), float(c[1]), float(term_z))),
                                          None, None)
        prof = (f.createIfcCircleProfileDef("AREA", None, None, s / 2) if t.get("shape") == "round" else
                f.createIfcRectangleProfileDef("AREA", None, None, s, s))
        solid = f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), th)
        e = w.entity("IfcAirTerminal", f"term{k}", name=t.get("label") or f"Air terminal {k + 1}", predefined="DIFFUSER")
        put(e, solid, "air_terminal", (0.2, 0.7, 0.4))
        if t.get("airflow_ls") is not None:
            safe_pset(e, "Pset_AirTerminalOccurrence", {"AirFlowRate": abs(float(t["airflow_ls"])) / 1000.0})
        w.pset(e, "Hologram_MEP", {"size_m": s, "shape": t.get("shape"), "airflow_ls": t.get("airflow_ls"),
                                   "source": "pdf_mep small closed MEP symbol"})
        safe_pset(e, "Hologram_Evidence", {
            "Source": "measured",
            "Detail": f"drawn {t.get('shape')} symbol {s:.3f} m across at page pt "
                      f"{[round(v, 1) for v in t['center_pt']]} ({t.get('source') or 'closed symbol'})"
                      + (f"; airflow printed '{t.get('label')}'" if t.get("airflow_ls") is not None else "")
                      + f"; at ceiling {ceiling_height:.2f} m ({ceiling_source})"})
        w.provenance(e, {"item_id": f"term{k}"})
        products.append(e)
        made["terminals"] += 1
    if products:
        ifcopenshell.api.spatial.assign_container(f, products=products, relating_structure=st)
        sysm = ifcopenshell.api.system.add_system(f, ifc_class="IfcDistributionSystem")
        sysm.Name = "Ventilation"
        sysm.PredefinedType = "VENTILATION"
        sysm.GlobalId = w.gid("mep_system_ventilation")
        ifcopenshell.api.system.assign_system(f, products=products, system=sysm)    # IfcRelAssignsToGroup
        bldg = building or next(iter(f.by_type("IfcBuilding")), None)
        if bldg is not None:
            f.createIfcRelServicesBuildings(ifcopenshell.guid.new(), None, None, None, sysm, [bldg])
    made["duct_length_m"] = round(made["duct_length_m"], 1)
    return made


def build_ifc(model_ifc_path, ducts_, terminals_, *, ceiling_height: float = 2.7, out_path=None, T: dict | None = None,
              doc_id: str = "mep", storey_name: str | None = None, fittings_=None, ceiling_source: str = "default") -> Path:
    """Copy of the ARK IFC (pdf_to_ifc output) + IfcDuctSegment per duct run, IfcDuctFitting at bends/tees,
    IfcAirTerminal per terminal, all in one IfcDistributionSystem (VENTILATION), contained in the ARK storey (first
    one, or storey_name). Duct/terminal coordinates are MEP page points; T maps them to ARK page points (None =
    already ARK points), then plan metres exactly like pdf_to_ifc (x*m_per_pt, -y*m_per_pt). Duct tops sit
    CEILING_GAP_M under the ceiling (the ceiling void); height from the size label else min(0.3 m, width); round
    ducts (ø label) get a circle. Writes out_path (default <model>.mep.ifc) and never touches the input file."""
    import ifcopenshell
    import ifcopenshell.guid  # noqa: F401
    from pipeline.pdf_to_ifc import _W

    src = Path(model_ifc_path)
    out = Path(out_path) if out_path else src.with_name(src.stem + ".mep.ifc")
    if out.resolve() == src.resolve():
        raise ValueError("out_path must differ from the ARK IFC")
    f = ifcopenshell.open(str(src))
    mpt = _ark_scale(f)
    storeys = f.by_type("IfcBuildingStorey")
    st = next((s for s in storeys if storey_name and s.Name == storey_name), storeys[0])
    body = next(c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
    w = _W(f, body, doc_id, 1, {"source": "pdf_mep", "m_per_pt": mpt, "ceiling_height_m": ceiling_height})

    def plan(p):
        q = apply_T(T, p)[0] if T else np.asarray(p, float)
        return float(q[0] * mpt), float(-q[1] * mpt)
    if fittings_ is None:
        fittings_ = _fittings(ducts_, (mpt * T["s"]) if T else mpt) if all("width_pt" in d for d in ducts_) else []
    _add_mep(f, w, st, ducts_, terminals_, fittings_, plan, ceiling_height=ceiling_height, ceiling_source=ceiling_source)
    try:        # MEP types, ports, materials (ifc_enrich v2 marks material Source=default, ports derived)
        from pipeline import ifc_enrich
        ifc_enrich.mep_native(f)
    except Exception:  # noqa: BLE001  optional
        pass
    out.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out))
    return out


# ---------------------------------------------------------------- building shell from the grey underlay (r5)

SHELL_CAP_S = 35.0          # wall detector time on the underlay subset of an MEP sheet
SHELL_MIN_M = 0.07          # thinnest underlay wall kept (thinner pairs: furniture, hatching, fixture outlines)
SHELL_MAX_M = 0.9           # thickest (thicker "walls" are filled areas, not wall bands)
SHELL_MIN_LEN_M = 0.3       # shortest wall piece kept
SHELL_MIN_WALLS = 6         # fewer kept walls than this is no shell (the plan-map gate needs 6 wall shapes)
SHELL_MIN_SHARE = 0.05      # the underlay must be at least this share of the page paths to be read alone


def _neutral_grey01(c) -> bool:
    """A 0-1 colour that is a neutral grey (no chroma, neither black nor white): the architect underlay pen."""
    return c is not None and len(c) >= 3 and max(c[:3]) - min(c[:3]) <= 0.05 and 0.2 <= c[0] <= 0.9


def underlay_subpage(vp: dict) -> dict | None:
    """pipeline.pdf_vector page -> the same page with only its neutral-grey underlay paths (grey stroke, or grey
    fill with no stroke): the architect plan an MEP sheet is drawn over. None when there is too little of it."""
    paths = vp.get("paths") or []
    keep = [p for p in paths if _neutral_grey01(p.get("stroke"))
            or (p.get("stroke") is None and _neutral_grey01(p.get("fill")))]
    if len(keep) < max(200, SHELL_MIN_SHARE * len(paths)):
        return None
    q = dict(vp)
    q["paths"] = keep
    q["obj_form"] = None
    return q


def _shell_m_per_pt(vp: dict) -> float:
    """Scale used to size the shell filter before the plan map has fitted its own: the finer of the printed
    scale and the MEP default (MEP sheets are drawn at 1:50 more often than the printed sheet scale says)."""
    return min(_printed_m_per_pt(vp), 0.0254 / 72 * MEP_DEFAULT_RATIO)


def filter_shell(walls_: list, m_per_pt: float) -> list:
    """Underlay wall candidates -> walls: thickness inside [SHELL_MIN_M, SHELL_MAX_M], length >= SHELL_MIN_LEN_M,
    and a candidate lying inside a thicker kept wall (same band read twice) dropped."""
    def length(w):
        c = w.get("centerline") or []
        return math.dist(c[0], c[-1]) if len(c) >= 2 else 0.0
    cand = [w for w in walls_ if SHELL_MIN_M <= w.get("thickness_pt", 0) * m_per_pt <= SHELL_MAX_M
            and length(w) * m_per_pt >= SHELL_MIN_LEN_M]
    cand.sort(key=lambda w: -w["thickness_pt"])
    kept, boxes = [], []
    for w in cand:
        P = np.asarray(w["polygon"], float)
        lo, hi = P.min(0), P.max(0)
        tol = 0.25 * w["thickness_pt"]
        if any((lo >= b[0] - tol).all() and (hi <= b[1] + tol).all() for b in boxes):
            continue
        kept.append(w)
        boxes.append((lo, hi))
    return kept


def pair_walls(vp: dict, m_per_pt: float) -> list:
    """Wall bands of the grey underlay as parallel stroke pairs SHELL_MIN_M..SHELL_MAX_M apart running >= 0.3 m
    side by side (the duct pair finder on the underlay pen: ~10 s where the general wall detector needs minutes
    on an MEP sheet). pdf_vector wall dicts: polygon, centerline, thickness_pt, style."""
    mp = from_vector_page(vp)
    sel = np.array([_neutral_grey01(p.get("stroke")) for p in vp.get("paths") or []], bool)
    if not sel.any():
        return []
    out = []
    for d in ducts(mp, sel, m_per_pt, min_w=SHELL_MIN_M, max_w=SHELL_MAX_M, min_len=SHELL_MIN_LEN_M, wall_mode=True):
        out.append({"polygon": [list(map(float, q)) for q in d["outline_pt"]],
                    "centerline": [list(map(float, d["start_pt"])), list(map(float, d["end_pt"]))],
                    "thickness_pt": float(d["width_pt"]), "style": "stroke", "kind": "underlay-pair"})
    return out


def shell_walls(vp: dict, walls_fn, *, budget_s: float = SHELL_CAP_S) -> list:
    """MEP sheet walls: the grey architect underlay's wall bands (pair_walls), filtered by filter_shell. The full
    sheet's black duct pens would make the general detector run for minutes and keep nothing. Falls back to
    walls_fn(vp, budget_s) (pdf_vector.walls) when the page has no clear underlay. Fewer than SHELL_MIN_WALLS
    -> [] (the caller's no-walls path). Returns a list of the walls_fn result type (with .truncated)."""
    if underlay_subpage(vp) is None:
        return walls_fn(vp, budget_s=budget_s)
    mpt = _shell_m_per_pt(vp)
    t0 = time.monotonic()
    kept = filter_shell(pair_walls(vp, mpt), mpt)
    if len(kept) < SHELL_MIN_WALLS:     # no credible shell: the caller's no-walls path (draft walls) as before
        kept = []
    try:
        from pipeline import pdf_vector
        out = pdf_vector.WallList(kept)
        pdf_vector.LAST_WALLS.clear()
        pdf_vector.LAST_WALLS.update(n=len(kept), s=round(time.monotonic() - t0, 2), truncated=False,
                                     budget_s=budget_s, method="mep underlay pairs")
    except Exception:  # noqa: BLE001
        out = list(kept)
    try:
        out.truncated = False
    except AttributeError:
        pass
    vp["walls_truncated"] = False
    return out


# ---------------------------------------------------------------- public interface (names agreed with the LEAD)

def _T3(T):
    Rm = np.asarray(T["R"]) * T["s"]
    return [[Rm[0, 0], Rm[0, 1], T["t"][0]], [Rm[1, 0], Rm[1, 1], T["t"][1]], [0.0, 0.0, 1.0]]


def split_mep(vent_page: dict, underlay_page: dict | None = None, *, m_per_pt: float | None = None) -> dict:
    """{"method": "ocg"|"geometric"|"style"|"none", "mep_paths": [i...], "underlay_paths": [i...], "mep": bool mask,
    "T": align() result (vent pt -> underlay pt) or None, "m_per_pt": vent sheet metres per point, "clusters", "stats"}.
    m_per_pt: the underlay's metres per point (default: its printed 1:N, else 1:100)."""
    T = align(vent_page, underlay_page) if underlay_page is not None else None
    if m_per_pt is None:
        m_per_pt = _printed_m_per_pt(underlay_page if underlay_page is not None else vent_page)
    vm = m_per_pt * T["s"] if T else m_per_pt
    r = separate(vent_page, underlay_page if T else None, T, m_per_pt=vm)
    r.update({"mep_paths": np.flatnonzero(r["mep"]).tolist(), "underlay_paths": np.flatnonzero(~r["mep"]).tolist(),
              "T": T, "m_per_pt": vm})
    return r


def _printed_m_per_pt(page) -> float:
    try:
        from engine import scale_text
        ratio, _ = scale_text.ratio_and_sheet(page.get("words") or [])
    except Exception:  # noqa: BLE001
        ratio = None
    return 0.0254 / 72 * (ratio or 100)


def _pen_terminals(page: dict, m_per_pt: float, D: list, TT: list) -> list:
    """Air terminals of an MEP sheet aligned onto an architect sheet: read from the sheet's own pen split (grey
    underlay vs MEP pen, separate() "style") when it has one. A terminal symbol often sits on the architect's
    ceiling / room lines, so the geometric split (MEP = what the architect sheet does not draw) loses its sides.
    Same reading as detect(): box + symbol terminals, then the pdf_ducts terminal/damper split. TT kept when the
    sheet has no pen split or anything fails."""
    try:
        st = separate(page, None, None)
        if st["method"] != "style" or not st["mep"].any():
            return TT
        T2 = terminals(page, st["mep"], m_per_pt)
        try:
            T2 = T2 + symbol_terminals(page, st["mep"], m_per_pt, D, T2)
        except Exception:  # noqa: BLE001
            pass
        try:
            T2 = T2 + tagged_terminals(page, st["mep"], m_per_pt, T2)
        except Exception:  # noqa: BLE001
            pass
        T2 = _with_tag_terminals(page, st["mep"], m_per_pt, T2)
        try:
            from pipeline import pdf_ducts
            _, T2, _ = pdf_ducts.refine([], T2, page, m_per_pt)
        except Exception:  # noqa: BLE001
            pass
        return T2 if len(T2) >= len(TT) else TT
    except Exception:  # noqa: BLE001
        return TT


def _printed_ceiling(page: dict) -> tuple[float, str] | None:
    """(ceiling height m, source) printed on the sheet (pipeline.pdf_levels.storey_info on the page words: a
    ceiling-height note), or None."""
    try:
        from pipeline import pdf_levels
        st = pdf_levels.storey_info({"words": page.get("words") or [], "W_pt": page.get("W_pt"),
                                     "H_pt": page.get("H_pt"), "paths": []})
        c = st.get("ceiling_m")
        if c and 2.0 <= float(c) <= 6.0:
            return float(c), f"printed ({st.get('height_source') or 'ceiling height'})"
    except Exception:  # noqa: BLE001
        pass
    return None


def _storey_height(ifc_path, default: float = 2.7) -> tuple[float, str]:
    """(ceiling height, source) of the ARK IFC's first storey (pdf_to_ifc's Hologram_StoreySource WallHeight),
    else (default, "default")."""
    try:
        import ifcopenshell
        import ifcopenshell.util.element as ue
        st = ifcopenshell.open(str(ifc_path)).by_type("IfcBuildingStorey")[0]
        h = (ue.get_psets(st).get("Hologram_StoreySource") or {}).get("WallHeight")
        if h and 2.0 <= float(h) <= 6.0:
            return float(h), "architect IFC storey WallHeight"
    except Exception:  # noqa: BLE001
        pass
    return default, "default"


def combine(ark_pdf, mep_pdf, ark_ifc, out_ifc, *, ceiling_height: float | None = None, shots_prefix=None,
            ark_page_index: int = 0, mep_page_index: int = 0, mep_artifact_dir=None) -> dict:
    """ARK sheet + MEP sheet of the same floor + the ARK IFC -> out_ifc with ducts/terminals. Returns a report."""
    import ifcopenshell
    t0 = time.time()
    ark, mep = load(ark_pdf, ark_page_index), load(mep_pdf, mep_page_index)
    t_load = time.time() - t0
    mpt = _ark_scale(ifcopenshell.open(str(ark_ifc)))
    sp = split_mep(mep, ark, m_per_pt=mpt)
    vt = prime_vtext(mep, sp["m_per_pt"], mep_artifact_dir, mep_page_index)    # the MEP sheet's saved stroke text
    r = detect(mep, sp["m_per_pt"], sp["mep"])           # same detection as the single sheet (+ symbol terminals)
    D, TT = r["ducts"], r["terminals"]
    TT = _pen_terminals(mep, sp["m_per_pt"], D, TT)
    n_raw = len(D)
    D, TT = clip_to_outline(D, TT, ark_ifc, sp["T"])
    csrc = "given"
    if ceiling_height is None:      # printed on the MEP sheet, else on the ARK sheet, else the ARK IFC storey
        pc = _printed_ceiling(mep) or _printed_ceiling(ark)
        ceiling_height, csrc = pc if pc else _storey_height(ark_ifc)
    out = build_ifc(ark_ifc, D, TT, ceiling_height=ceiling_height, out_path=out_ifc, T=sp["T"], ceiling_source=csrc)
    rep = {"method": sp["method"], "stats": sp["stats"], "clusters": sp.get("clusters", [])[:8],
           "align": {k: v for k, v in (sp["T"] or {}).items() if k not in ("R",)}, "m_per_pt_mep": sp["m_per_pt"],
           "ceiling_height_m": ceiling_height, "ceiling_source": csrc, "vtext": vt, "fittings": len(_fittings(D, sp["m_per_pt"])),
           "ducts": len(D), "ducts_before_outline_clip": n_raw, "duct_length_m": round(sum(d["length_m"] for d in D), 1), "terminals": len(TT),
           "terminals_with_airflow": sum(t["airflow_ls"] is not None for t in TT), "out_ifc": str(out),
           "load_s": round(t_load, 1), "total_s": round(time.time() - t0, 1)}
    if shots_prefix:
        rep["overlay"] = overlay(mep, sp["mep"], f"{shots_prefix}-split.png", ducts=D, terms=TT,
                                 title=f"{sp['method']}: underlay grey, MEP red, ducts blue, terminals green")
    return rep


# ---------------------------------------------------------------- single sheet: an MEP sheet on its own (r3)

TAG_RE = re.compile(r"^(\d{1,2}\s*[x×]\s*)?[A-ZÄÖ]{1,4}\d{0,2}-\d{3}$")      # terminal/damper type-size tags 2xK3-160
MEP_WORD_RE = re.compile(r"^(IV|LVI|HVAC|ILMANVAIHTO|VENTILATION|VENTILAATIO|KANAVA|DUCT|SUPPLY|EXHAUST|TULOILMA|"
                         r"POISTOILMA)\b", re.I)
_CACHE: dict = {}


def _load_cached(pdf_path, page_index: int) -> dict:
    """One page kept between is_mep_sheet and enrich_ifc (the ingest calls both on the same page)."""
    p = Path(pdf_path)
    key = (str(p.resolve()), int(page_index), p.stat().st_mtime_ns)
    if _CACHE.get("key") != key:
        _CACHE.clear()
        _CACHE.update(key=key, page=load(p, page_index))
    return _CACHE["page"]


def from_vector_page(vp: dict, pdf_path=None, page_index: int = 0) -> dict:
    """The page pipeline.pdf_vector.load_page already read (same pdfium walk: displayed pt, top-left, y down) in
    this module's layout, so an ingest that has it does not read the ~1M path segments of an MEP sheet twice.
    Colours 0-1 -> 0-255, closed paths repeat their first point, curves = n_curves; no optional-content layers."""
    xs, ys, paths = [], [], []

    def c255(c):
        return None if c is None else tuple(int(round(float(v) * 255)) for v in c[:3])
    for q in vp["paths"]:
        P = q["pts"]
        if len(P) < 2:
            continue
        i0 = len(xs)
        xs.extend(float(x) for x, _ in P)
        ys.extend(float(y) for _, y in P)
        if q.get("closed") and (P[0][0] != P[-1][0] or P[0][1] != P[-1][1]):
            xs.append(float(P[0][0]))
            ys.append(float(P[0][1]))
        paths.append({"i0": i0, "i1": len(xs), "closed": bool(q.get("closed")), "stroke": c255(q.get("stroke")),
                      "fill": c255(q.get("fill")), "width": round(float(q.get("width") or 0.0), 3),
                      "dashed": bool(q.get("dashed")), "layer": None, "curves": int(q.get("n_curves") or 0)})
    xy = np.c_[np.asarray(xs, np.float64), np.asarray(ys, np.float64)] if xs else np.zeros((0, 2))
    return {"W_pt": float(vp["W_pt"]), "H_pt": float(vp["H_pt"]), "rotate": vp.get("rotate", 0), "xy": xy,
            "paths": paths, "words": list(vp.get("words") or []), "layers": {}, "pdf": str(pdf_path),
            "page_index": page_index}


def prime(pdf_path, page_index: int, vector_page: dict) -> bool:
    """Hand this module the page pdf_vector.load_page already read (saves the second ~1M-call pdfium walk in
    is_mep_sheet / enrich_ifc). Never raises; False when it could not be used (load() then reads the page)."""
    try:
        p = Path(pdf_path)
        key = (str(p.resolve()), int(page_index), p.stat().st_mtime_ns)
        if _CACHE.get("key") != key:
            _CACHE.clear()
            _CACHE.update(key=key, page=from_vector_page(vector_page, p, page_index))
        return True
    except Exception:  # noqa: BLE001
        return False


def text_cues(words) -> dict:
    """Counts of ventilation-sheet text on a page: airflows (l/s), duct sizes (400x200, ø250), terminal/damper
    type-size tags (2xK3-160), MEP words (IV-, LVI, ventilation...)."""
    c = Counter()
    W = [w["text"].strip() for w in words]
    for k, t in enumerate(W):
        tl = t.lower()
        if tl.endswith("l/s") or tl.endswith("m3/h") or tl.endswith("m³/h"):
            c["airflow"] += 1
        elif SIZE_RE.match(t) or ROUND_RE.match(t) or re.match(r"^[øØ⌀∅]\s*\d{2,4}", t):
            c["size"] += 1
        elif TAG_RE.match(t):
            c["tag"] += 1
        elif MEP_WORD_RE.match(t):
            c["word"] += 1
    return dict(c)


def _cue_score(c: dict) -> tuple[int, int]:
    kinds = sum(1 for k in ("airflow", "size", "tag") if c.get(k))
    return kinds, sum(c.get(k, 0) for k in ("airflow", "size", "tag"))


def is_mep_sheet(pdf_path, page_index: int = 0) -> bool:
    """True when the page is a ventilation sheet drawn over an architectural underlay: MEP text (at least two kinds
    of airflow / duct size / type-size tag, 4+ in all), and a screened (grey) underlay carrying a large share of the
    linework (15-95 %) with a non-grey layer on top. Text first (cheap); never raises."""
    try:
        import pypdfium2 as pdfium
        from pipeline.pdf_vector import _displayer, _words_pdfium
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            pg = doc[page_index]
            rot = pg.get_rotation() % 360
            cl, cb, cr, ct = pg.get_cropbox()
            words = _words_pdfium(pg, _displayer(rot, cr - cl, ct - cb, cl, cb))
            pg.close()
        finally:
            doc.close()
        kinds, n = _cue_score(text_cues(words))
        if kinds < 2 or n < 4:
            return False
        page = _load_cached(pdf_path, page_index)
        sp = separate(page, None, None)
        _CACHE["sep"] = sp                     # enrich_ifc reuses the split
        st = sp["stats"]
        tot = st["mep_length_pt"] + st["underlay_length_pt"]
        return bool(sp["method"] == "style" and tot > 0 and 0.05 <= st["mep_length_pt"] / tot <= 0.85)
    except Exception:  # noqa: BLE001
        return False


def _planmap_m_per_pt(planmap: dict, page: dict) -> float:
    sc = planmap.get("scale") or {}
    if sc.get("m_per_pt"):
        return float(sc["m_per_pt"])
    img = planmap.get("image") or {}
    if sc.get("m_per_px") and img.get("w"):
        return float(sc["m_per_px"]) * float(img["w"]) / page["W_pt"]
    raise ValueError("plan map has no scale")


def detect(page: dict, m_per_pt: float, sel: np.ndarray | None = None) -> dict:
    """Single sheet: style split (grey underlay vs MEP pen) -> ducts, fittings, terminals in this page's points."""
    if sel is None:
        sp = separate(page, None, None)
        method, sel = sp["method"], sp["mep"]
    else:
        method = "given"
    if method == "none" or not sel.any():
        return {"method": method, "mep": sel, "ducts": [], "terminals": [], "fittings": []}
    D = ducts(page, sel, m_per_pt)
    TT = terminals(page, sel, m_per_pt)
    try:
        TT = TT + symbol_terminals(page, sel, m_per_pt, D, TT)
    except Exception:  # noqa: BLE001  optional: closed-symbol terminals only
        pass
    try:
        TT = TT + tagged_terminals(page, sel, m_per_pt, TT)
    except Exception:  # noqa: BLE001  optional
        pass
    TT = _with_tag_terminals(page, sel, m_per_pt, TT)
    try:
        from pipeline import pdf_ducts
        D, TT, _ = pdf_ducts.refine(D, TT, page, m_per_pt)
    except Exception:  # noqa: BLE001  optional second pass
        pass
    return {"method": method, "mep": sel, "ducts": D, "terminals": TT, "fittings": _fittings(D, m_per_pt)}


def _has_cross(segs: np.ndarray, c: np.ndarray, size: float) -> bool:
    """Two strokes >= 0.6 x size crossing within 0.2 x size of c at >= 45 deg (the X / cross of a terminal)."""
    dv = segs[:, 2:] - segs[:, :2]
    sl = np.hypot(dv[:, 0], dv[:, 1])
    lg = np.flatnonzero(sl >= 0.6 * size)[:40]
    for a_ in lg:
        ua = dv[a_] / sl[a_]
        for b_ in lg:
            if b_ <= a_:
                continue
            ub = dv[b_] / sl[b_]
            cr = ua[0] * ub[1] - ua[1] * ub[0]
            if abs(cr) < 0.7:
                continue
            q = segs[b_, :2] - segs[a_, :2]
            ta = (q[0] * ub[1] - q[1] * ub[0]) / cr
            if 0 <= ta <= sl[a_] and np.linalg.norm(segs[a_, :2] + ua * ta - c) <= 0.2 * size:
                return True
    # the X drawn as strokes radiating from the centre: >= 3 strokes >= 0.4 x size with one end at c, >= 2 directions
    rad = (sl >= 0.4 * size) & ((np.hypot(*(segs[:, :2] - c).T) <= 0.1 * size) | (np.hypot(*(segs[:, 2:] - c).T) <= 0.1 * size))
    if rad.sum() >= 3:
        ang = np.round(np.degrees(np.arctan2(dv[rad, 1], dv[rad, 0])) % 180 / 15).astype(int) % 12
        return len(set(ang.tolist())) >= 2
    return False


def symbol_terminals(page: dict, sel: np.ndarray, m_per_pt: float, D: list[dict] = (), known: list[dict] = (),
                     *, min_repeat: int = 3) -> list[dict]:
    """Air terminals drawn as open linework: an outline (a circle/arc path with >= 3 curves, or a path with >= 4
    corners: square / rectangle, open or closed) TERM_MIN_M..TERM_MAX_M across and near-square, with an X / cross
    of MEP strokes through its centre (square diffuser with diagonals, circle with a cross), no text inside. A
    symbol counts when its geometry (size class, round/square) repeats >= min_repeat times on the sheet, or once
    next to a duct end (<= 1 m) or an MEP tag / airflow word (<= 2 m). Already-known terminals are skipped."""
    paths, xy = page["paths"], page["xy"]
    mi = np.flatnonzero(sel)
    allseg, _ = _seg_array(page, mi)
    if not len(allseg):
        return []
    sx0 = np.minimum(allseg[:, 0], allseg[:, 2])
    order = np.argsort(sx0)
    allseg, sx0 = allseg[order], sx0[order]
    sx1 = np.maximum(allseg[:, 0], allseg[:, 2])
    sy0, sy1 = np.minimum(allseg[:, 1], allseg[:, 3]), np.maximum(allseg[:, 1], allseg[:, 3])
    W = page["words"]
    WC = np.array([[(w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2] for w in W], float).reshape(-1, 2)
    cue = np.array([bool(TAG_RE.match(w["text"].strip()) or "l/s" in w["text"].lower()) for w in W], bool)
    ends = np.array([q for d in D for q in (d["start_pt"], d["end_pt"])], float).reshape(-1, 2)
    known_c = np.array([t["center_pt"] for t in known], float).reshape(-1, 2)
    cands = []
    i0 = np.array([paths[i]["i0"] for i in mi])
    i1 = np.array([paths[i]["i1"] for i in mi])
    n = np.maximum(i1 - i0, 1)
    off = np.r_[0, np.cumsum(n)[:-1]]
    Q = xy[np.repeat(i0 - off, n) + np.arange(n.sum())]      # the points of the MEP paths, path after path
    BX0, BY0 = np.minimum.reduceat(Q[:, 0], off), np.minimum.reduceat(Q[:, 1], off)
    BX1, BY1 = np.maximum.reduceat(Q[:, 0], off), np.maximum.reduceat(Q[:, 1], off)
    bw, bh = (BX1 - BX0) * m_per_pt, (BY1 - BY0) * m_per_pt
    pre = (np.minimum(bw, bh) >= TERM_MIN_M) & (np.maximum(bw, bh) <= TERM_MAX_M)
    for i in mi[pre]:
        p = paths[i]
        if p["stroke"] is None or p["dashed"]:
            continue
        P = xy[p["i0"]:p["i1"]]
        x0, y0 = P.min(0)
        x1, y1 = P.max(0)
        w_, h_ = (x1 - x0) * m_per_pt, (y1 - y0) * m_per_pt
        if not (TERM_MIN_M <= min(w_, h_) and max(w_, h_) <= TERM_MAX_M and max(w_, h_) <= 1.3 * min(w_, h_)):
            continue
        round_ = p["curves"] >= 3
        if not round_ and p["i1"] - p["i0"] < 4:
            continue
        c = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
        size = max(x1 - x0, y1 - y0)
        if len(WC) and np.any((WC[:, 0] > x0) & (WC[:, 0] < x1) & (WC[:, 1] > y0) & (WC[:, 1] < y1)):
            continue        # a text frame (tag box), not a terminal
        e = 0.05 * size
        k0, k1 = np.searchsorted(sx0, x0 - e), np.searchsorted(sx0, x1 + e, side="right")
        m = (sx1[k0:k1] <= x1 + e) & (sy0[k0:k1] >= y0 - e) & (sy1[k0:k1] <= y1 + e)
        inner = allseg[k0:k1][m]
        if len(inner) > 600 or not _has_cross(inner, c, size):
            continue
        cands.append((c, max(w_, h_), (int(round(max(w_, h_) / 0.05)), round_), round_))
    if not cands:
        return []
    cnt = Counter(sg for _, _, sg, _ in cands)
    out = []
    for c, s, sg, rnd in sorted(cands, key=lambda z: -z[1]):
        near_end = bool(len(ends)) and np.min(np.hypot(*(ends - c).T)) * m_per_pt <= 1.0
        near_cue = bool(cue.any()) and np.min(np.hypot(*(WC[cue] - c).T)) * m_per_pt <= 2.0
        if not (cnt[sg] >= min_repeat or near_end or near_cue):
            continue
        if len(known_c) and np.min(np.hypot(*(known_c - c).T)) * m_per_pt < 0.5 * s:
            continue
        if any(np.linalg.norm(c - np.array(o["center_pt"])) * m_per_pt < 0.5 * o["size_m"] for o in out):
            continue
        out.append({"center_pt": c.tolist(), "size_pt": float(s / m_per_pt), "size_m": round(s, 3),
                    "shape": "round" if rnd else "square", "airflow_ls": None, "label": None,
                    "source": "symbol", "repeat": int(cnt[sg])})
    return out


TAGGED_MIN_M = 0.10        # smallest tagged terminal symbol (a 100 mm valve drawn at its size)
TAGGED_LEADER_TOL_M = 0.4  # the leader ends this close to the symbol outline (at its arrow / connection stub)


def tagged_terminals(page: dict, sel: np.ndarray, m_per_pt: float, known: list[dict] = ()) -> list[dict]:
    """Air terminals too small for terminals() / without a cross for symbol_terminals(): a closed (or round) MEP
    symbol TAGGED_MIN_M..TERM_MAX_M across, near-square, at which a tag leader ends (pdf_ducts.leader_ends: a long
    oblique stroke from a type/airflow tag block). Concentric outlines count once; known terminals are skipped."""
    from pipeline import pdf_ducts
    LE = pdf_ducts.leader_ends(page, m_per_pt)
    if not len(LE):
        return []
    xy, cands = page["xy"], []
    for i in np.flatnonzero(sel):
        p = page["paths"][i]
        if p["stroke"] is None or p["dashed"] or p["i1"] - p["i0"] < 4:
            continue
        P = xy[p["i0"]:p["i1"]]
        closed = p["closed"] or bool(np.allclose(P[0], P[-1]))
        if not (closed or p["curves"] >= 3):
            continue
        lo, hi = P.min(0), P.max(0)
        w, h = (hi - lo) * m_per_pt
        if not (TAGGED_MIN_M <= min(w, h) and max(w, h) <= TERM_MAX_M and max(w, h) <= 1.3 * min(w, h)):
            continue
        c = (lo + hi) / 2
        size = max(w, h)
        if np.min(np.hypot(*(LE - c).T)) * m_per_pt > size / 2 + TAGGED_LEADER_TOL_M:
            continue
        cands.append((c, size, p["curves"] >= 3))
    known_c = np.array([t["center_pt"] for t in known], float).reshape(-1, 2)
    out = []
    for c, size, rnd in sorted(cands, key=lambda z: -z[1]):
        if len(known_c) and np.min(np.hypot(*(known_c - c).T)) * m_per_pt < max(0.5 * size, 0.1):
            continue
        if any(np.linalg.norm(c - np.array(o["center_pt"])) * m_per_pt < max(0.5 * o["size_m"], 0.1) for o in out):
            continue
        out.append({"center_pt": c.tolist(), "size_pt": float(size / m_per_pt), "size_m": round(size, 3),
                    "shape": "round" if rnd else "square", "airflow_ls": None, "label": None, "source": "tagged"})
    return out


TYPE_TAG_RE = re.compile(r"^(?:(\d{1,2})\s*[xX×])?([A-ZÄÖ]{1,3}\d{1,2})-(\d{2,4})$")   # [Nx]TYPE-SIZE device tag
TAG_LEADER_GAP = 8.0       # a leader starts within this many tag text heights of the tag word (its block)
TAG_SYMBOL_M = 0.6         # the tagged symbol lies within this of the leader's far end (plus its own half size)
TAG_MIN_SYMBOL_M = 0.05    # smallest symbol a tag may point at
VTEXT_FOCUS_M = 1.5        # stroke text is read within this of a tag leader's ends
TAG_AIRFLOW_LINES = 4.0    # the tag block's airflow ("+30" / "-25 l/s") within this many text heights of the tag


def _leaders(page: dict, m_per_pt: float) -> list[tuple]:
    """[(path index, end a, end b)] of tag leaders: an open solid non-grey path of 2-3 points whose longest piece is
    >= pdf_ducts.LEADER_MIN_M and >= LEADER_OFF_AXIS_DEG off both axes (a leader, or a tag underline + leader)."""
    from pipeline import pdf_ducts
    xy, out = page["xy"], []
    for i, p in enumerate(page["paths"]):
        n = p["i1"] - p["i0"]
        if p["stroke"] is None or p.get("dashed") or p["closed"] or not 2 <= n <= 3 or pdf_ducts._grey(p["stroke"]):
            continue
        P = xy[p["i0"]:p["i1"]]
        v = np.diff(P, axis=0)
        Ls = np.hypot(v[:, 0], v[:, 1])
        k = int(np.argmax(Ls))
        if Ls[k] * m_per_pt < pdf_ducts.LEADER_MIN_M:
            continue
        ang = math.degrees(math.atan2(abs(v[k, 1]), abs(v[k, 0])))
        if min(ang, 90 - ang) >= pdf_ducts.LEADER_OFF_AXIS_DEG:
            out.append((i, P[0].copy(), P[-1].copy()))
    return out


STROKE_JOIN_M = 0.02       # separate strokes whose ends meet this close form one drawn symbol


def _two_point_strokes(page: dict, sel: np.ndarray) -> tuple:
    """(path ids, start points, end points) of the solid non-grey 2-point MEP strokes."""
    from pipeline import pdf_ducts
    xy, ids = page["xy"], []
    for i in np.flatnonzero(sel):
        p = page["paths"][i]
        if p["stroke"] is not None and p["i1"] - p["i0"] == 2 and not pdf_ducts._grey(p["stroke"]):
            ids.append(int(i))
    i0 = np.array([page["paths"][i]["i0"] for i in ids], int)
    return np.array(ids, int), xy[i0].reshape(-1, 2), xy[i0 + 1].reshape(-1, 2)


def _stroke_symbol(page: dict, strokes: tuple, far, m_per_pt: float, skip=()) -> tuple | None:
    """A symbol drawn from separate 2-point MEP strokes at a leader end: strokes within TAG_SYMBOL_M of the end,
    joined when their ends meet within STROKE_JOIN_M; the group whose box the end touches (<= 0.15 m), largest
    first, TAG_MIN_SYMBOL_M..TERM_MAX_M across and no longer than 2:1. -> (path ids, centre, size m) or None."""
    r = (TAG_SYMBOL_M + 0.1) / m_per_pt
    I, A, Bp = strokes
    if not len(I):
        return None
    near = (np.minimum(np.hypot(*(A - far).T), np.hypot(*(Bp - far).T)) <= r) & \
           (np.hypot(*(Bp - A).T) * m_per_pt <= TERM_MAX_M) & ~np.isin(I, list(skip))
    ids = [int(i) for i in I[near]]
    segs = list(zip(A[near], Bp[near]))
    if not ids:
        return None
    n = len(ids)
    par = list(range(n))

    def root(k):
        while par[k] != k:
            par[k] = par[par[k]]
            k = par[k]
        return k
    tol = STROKE_JOIN_M / m_per_pt
    E = np.array([q for sg in segs for q in sg])
    for u in range(2 * n):
        d = np.hypot(*(E - E[u]).T)
        for v in np.flatnonzero(d <= tol):
            ru, rv = root(u // 2), root(int(v) // 2)
            if ru != rv:
                par[ru] = rv
    groups: dict = {}
    for k in range(n):
        groups.setdefault(root(k), []).append(k)
    best = None
    for g in groups.values():
        P = np.array([q for k in g for q in segs[k]])
        lo, hi = P.min(0), P.max(0)
        w_, h_ = (hi - lo) * m_per_pt
        if len(g) < 3 or min(w_, h_) < TAG_MIN_SYMBOL_M or max(w_, h_) > TERM_MAX_M or max(w_, h_) > 2 * min(w_, h_):
            continue
        gap = math.hypot(max(lo[0] - far[0], 0.0, far[0] - hi[0]), max(lo[1] - far[1], 0.0, far[1] - hi[1])) * m_per_pt
        if gap > 0.15:
            continue
        size = float(max(w_, h_))
        if best is None or size > best[2]:
            best = ([ids[k] for k in g], (lo + hi) / 2, size)
    return best


def terminals_from_tags(page: dict, sel: np.ndarray, m_per_pt: float, words: list) -> tuple[list[dict], list[dict]]:
    """Air terminals the sheet itself tags: every device tag ("[Nx]TYPE-SIZE" word, e.g. from pdf_vtext) with a
    leader starting within TAG_LEADER_GAP text heights of it; the N symbols (closed or round MEP paths >=
    TAG_MIN_SYMBOL_M, <= TERM_MAX_M) nearest the leader's far end, within TAG_SYMBOL_M, are terminals of that tag.
    A tag in a schedule / legend has no leader and yields nothing. Returns (terminals, misses); every terminal
    carries its evidence (tag text + position, leader path id, symbol path ids, airflow if read); misses are the
    tags whose leader end found no symbol (tag, leader, end point)."""
    tags = []
    for k, w in enumerate(words or []):
        m = TYPE_TAG_RE.match(str(w.get("text", "")).strip())
        if m:
            tags.append((k, w, int(m.group(1) or 1), m.group(2), int(m.group(3))))
    if not tags:
        return [], []
    L = _leaders(page, m_per_pt)
    if not L:
        return [], []
    xy = page["xy"]
    sym = []    # (path index, centre, size m, round)
    for i in np.flatnonzero(sel):
        p = page["paths"][i]
        if p["stroke"] is None and p["fill"] is None:
            continue
        P = xy[p["i0"]:p["i1"]]
        if len(P) < 3:
            continue
        closed = p["closed"] or bool(np.allclose(P[0], P[-1]))
        if not (closed or p["curves"] >= 3 or len(P) >= 5):     # closed, round, or an open outline (>= 4 sides)
            continue
        lo, hi = P.min(0), P.max(0)
        w_, h_ = (hi - lo) * m_per_pt
        if min(w_, h_) < TAG_MIN_SYMBOL_M or max(w_, h_) > TERM_MAX_M or max(w_, h_) > 1.3 * min(w_, h_):
            continue
        sym.append((int(i), (lo + hi) / 2, float(max(w_, h_)), p["curves"] >= 3, lo, hi))
    # text drawn in the MEP pen (stroke text, src "vtext") when the words carry it: the architect's room names in the
    # text layer sit everywhere under the ducts and say nothing about MEP symbols
    mep_words = [w for w in words if w.get("src") == "vtext"] or list(words)
    WB = np.array([w["bbox"] for w in mep_words], float).reshape(-1, 4)
    if len(WB) and sym:     # glyph strokes of (stroke) text are not symbols
        sym = [z for z in sym if not np.any((WB[:, 0] <= z[1][0]) & (z[1][0] <= WB[:, 2]) &
                                            (WB[:, 1] <= z[1][1]) & (z[1][1] <= WB[:, 3]))]
    SC = np.array([z[1] for z in sym], float).reshape(-1, 2)
    flow_re = re.compile(r"^[+\-−–]\d{1,4}(?:[.,]\d)?(?:\s*l/s)?$")

    def boxdist(p, b):
        return math.hypot(max(b[0] - p[0], 0.0, p[0] - b[2]), max(b[1] - p[1], 0.0, p[1] - b[3]))
    pairs = []      # (gap in text heights, tag #, leader #, far end): nearest tag-leader pairs first, each once
    for ti, (k, w, n, typ, size) in enumerate(tags):
        b = w["bbox"]
        th = max(min(b[2] - b[0], b[3] - b[1]), 1e-6)
        for lj, (li, a, e) in enumerate(L):
            da, de = boxdist(a, b), boxdist(e, b)
            d0, far = (da, e) if da <= de else (de, a)
            if d0 <= TAG_LEADER_GAP * th:
                pairs.append((d0 / th, ti, lj, far))
    pairs.sort(key=lambda z: z[0])
    tag_of, used_t, used_l = {}, set(), set()
    for g, ti, lj, far in pairs:
        if ti in used_t or lj in used_l:
            continue
        used_t.add(ti)
        used_l.add(lj)
        tag_of[ti] = (lj, far)
    out, misses, strokes = [], [], None
    for ti, (k, w, n, typ, size) in enumerate(tags):
        if ti not in tag_of:
            continue
        b = w["bbox"]
        th = max(min(b[2] - b[0], b[3] - b[1]), 1e-6)
        lj, far = tag_of[ti]
        li = L[lj][0]
        # airflow of the tag block: a signed number word close to the tag
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        flow = None
        if len(WB):
            dd = np.hypot((WB[:, 0] + WB[:, 2]) / 2 - cx, (WB[:, 1] + WB[:, 3]) / 2 - cy)
            for j in np.argsort(dd):
                if dd[j] > TAG_AIRFLOW_LINES * th:
                    break
                t = str(mep_words[j].get("text", "")).strip().replace("−", "-").replace("–", "-")
                if flow_re.match(t):
                    flow = float(re.sub(r"\s*l/s$", "", t).replace(",", "."))
                    break
        in_text = len(WB) and bool(np.any((WB[:, 0] <= far[0]) & (far[0] <= WB[:, 2]) &
                                          (WB[:, 1] <= far[1]) & (far[1] <= WB[:, 3])))
        if not len(SC) or in_text:      # a leader ending in text (another tag block) points at no device
            misses.append({"tag": w["text"], "tag_pt": [cx, cy], "leader_path": li, "end_pt": far.tolist()})
            continue
        d = np.hypot(*(SC - far).T) * m_per_pt
        reach = [j for j in np.argsort(d) if d[j] <= TAG_SYMBOL_M + sym[j][2] / 2]
        # the whole symbol, not a piece of it: among those whose outline the leader end touches (<= 0.15 m from
        # their box) the largest first, then the rest by distance
        def gap(j):
            lo, hi = sym[j][4], sym[j][5]
            return math.hypot(max(lo[0] - far[0], 0.0, far[0] - hi[0]), max(lo[1] - far[1], 0.0, far[1] - hi[1])) * m_per_pt
        touch = sorted([j for j in reach if gap(j) <= 0.15], key=lambda j: -sym[j][2])
        got = []
        for j in touch + [j for j in reach if j not in touch]:
            pi, c, sz, rnd = sym[j][:4]
            if len(got) >= n:
                break
            if any(np.linalg.norm(c - g[1]) * m_per_pt < max(0.5 * g[2], 0.05) for g in got):
                continue        # inner ring / piece of a symbol already taken
            got.append((pi, c, sz, rnd))
        if not got:     # a symbol drawn from separate strokes
            if strokes is None:
                strokes = _two_point_strokes(page, sel)
            ss = _stroke_symbol(page, strokes, far, m_per_pt, skip={li})
            if ss is not None:
                got = [(ss[0], ss[1], ss[2], False)]
        if not got:
            misses.append({"tag": w["text"], "tag_pt": [cx, cy], "leader_path": li, "end_pt": far.tolist()})
            continue
        for pi, c, sz, rnd in got:
            out.append({"center_pt": c.tolist(), "size_pt": float(sz / m_per_pt), "size_m": round(sz, 3),
                        "shape": "round" if rnd else "square", "airflow_ls": flow,
                        "label": w["text"] + (f" {flow:+g} l/s" if flow is not None else ""),
                        "source": "tag", "type": typ, "nominal_mm": size,
                        "evidence": {"tag": w["text"], "tag_pt": [round(cx, 1), round(cy, 1)], "leader_path": li,
                                     "symbol_paths": pi if isinstance(pi, list) else [pi], "airflow_ls": flow}})
    return out, misses


VTEXT_CAP_S = 40.0         # hard cap on a live stroke-text read (forked child killed at it)
VTEXT_INNER = 0.75         # share of the cap given to pdf_vtext.words' own deadline


def _vtext_cache(art_dir, page_index: int):
    return Path(art_dir) / f"vtext-{int(page_index) + 1}.json" if art_dir else None


def _read_vtext_live(page: dict, m_per_pt: float, cap_s: float) -> tuple[list, dict] | None:
    """Stroke text around the tag leaders (pdf_vtext.words, focus = leader ends, VTEXT_FOCUS_M) in a forked child
    killed at cap_s. -> (words sorted by position, pdf_vtext.LAST) or None (off, missing, over time, error)."""
    if os.environ.get("PDF_VTEXT", "1") == "0" or cap_s <= 1 or not hasattr(os, "fork"):
        return None
    try:
        from pipeline import pdf_vtext
    except Exception:  # noqa: BLE001
        return None
    import pickle
    import select
    import signal
    L = _leaders(page, m_per_pt)
    F = np.array([q for _, a, b in L for q in (a, b)], float).reshape(-1, 2)
    if not len(F):
        return [], {"partial": False, "clusters": 0, "decoded": 0, "s": 0.0}
    deadline = time.monotonic() + cap_s
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        code = 0
        try:
            os.close(r)
            got = pdf_vtext.words(page, budget_s=VTEXT_INNER * cap_s, focus=F, focus_r_pt=VTEXT_FOCUS_M / m_per_pt)
            ws = [{"text": str(x["text"]), "bbox": [round(float(v), 2) for v in x["bbox"]], "src": "vtext"} for x in got]
            with os.fdopen(w, "wb") as f:
                f.write(pickle.dumps((ws, dict(pdf_vtext.LAST))))
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
        return None
    try:
        ws, last = pickle.loads(buf)
    except Exception:  # noqa: BLE001
        return None
    ws.sort(key=lambda x: (x["bbox"][1], x["bbox"][0], x["text"]))     # same order every run
    return ws, last


def prime_vtext(page: dict, m_per_pt: float, art_dir=None, page_index: int = 0) -> dict:
    """page["_vtext_words"] (what pdf_ducts.vtext_words and the tag terminals read) from the artifact's
    vtext-<page>.json when it exists, else from one live read, saved there (only a read that finished). The words
    come from this PDF page's own stroke text, so a later build (combine onto ARK) reuses the very same words.
    Returns {"source": "cache" | "live" | "none", "n", "partial", "s"}."""
    if "_vtext_words" in page:
        return {"source": "given", "n": len(page["_vtext_words"])}
    import json
    fp = _vtext_cache(art_dir, page_index)
    if fp is not None and fp.is_file():
        try:
            d = json.loads(fp.read_text())
            page["_vtext_words"] = [w for w in d.get("words") or [] if "text" in w and len(w.get("bbox") or ()) == 4]
            return {"source": "cache", "n": len(page["_vtext_words"]), "partial": d.get("partial"), "s": d.get("s")}
        except Exception:  # noqa: BLE001
            pass
    cap = float(os.environ.get("PDF_VTEXT_S", VTEXT_CAP_S))
    t0 = time.time()
    got = _read_vtext_live(page, m_per_pt, cap)
    if got is None:
        page["_vtext_words"] = []
        return {"source": "none", "n": 0, "s": round(time.time() - t0, 1)}
    ws, last = got
    page["_vtext_words"] = ws
    info = {"source": "live", "n": len(ws), "partial": bool(last.get("partial")), "s": round(time.time() - t0, 1)}
    if fp is not None:
        try:
            tmp = fp.with_suffix(".tmp")
            tmp.write_text(json.dumps({"words": ws, "partial": info["partial"], "s": info["s"], "cap_s": cap,
                                       "focus_m": VTEXT_FOCUS_M, "clusters": last.get("clusters"),
                                       "decoded": last.get("decoded"),
                                       "source": "pdf_vtext: stroke text of this PDF page around tag leaders"}))
            os.replace(tmp, fp)
        except OSError:
            pass
    return info


def _with_tag_terminals(page: dict, sel: np.ndarray, m_per_pt: float, TT: list) -> list:
    """TT merged with the terminals the sheet tags (text layer + stroke-text words via pdf_ducts.vtext_words).
    No tags read (stroke text off / over time) or any error -> TT unchanged (the symbol rules alone)."""
    try:
        from pipeline import pdf_ducts
        L = _leaders(page, m_per_pt)       # stroke text read only around tag leaders (tags, sizes on leaders)
        F = np.array([q for _, a, b in L for q in (a, b)], float).reshape(-1, 2)
        vw = pdf_ducts.vtext_words(page, focus=F, focus_r_pt=VTEXT_FOCUS_M / m_per_pt) if len(F) else []
        words = list(page.get("words") or []) + list(vw)
        TG, MS = terminals_from_tags(page, sel, m_per_pt, words)
        page["_tag_misses"] = MS
        return merge_tagged(TT, TG, m_per_pt) if TG else TT
    except Exception:  # noqa: BLE001
        return TT


def merge_tagged(TT: list[dict], tagged: list[dict], m_per_pt: float, *, min_tagged: int = 5) -> list[dict]:
    """Tag terminals first; a rule-found terminal at the same place (< 0.3 m) is the same device. When the sheet
    tags its terminals (>= min_tagged found), an untagged rule-found symbol is kept only if a tagged terminal of the
    same shape has a similar size (within 30 %): the sheet's own terminal symbols, not plant-room openings."""
    if not tagged:
        return TT
    out = list(tagged)
    C = np.array([t["center_pt"] for t in tagged], float)
    for t in TT:
        if np.min(np.hypot(*(C - np.array(t["center_pt"])).T)) * m_per_pt < 0.3:
            continue
        if len(tagged) >= min_tagged and not any(
                g["shape"] == t.get("shape") and abs(g["size_m"] - t["size_m"]) <= 0.3 * max(g["size_m"], t["size_m"])
                for g in tagged):
            continue
        out.append(t)
    return out


def _clip_to_underlay(page: dict, sel: np.ndarray, D: list, TT: list):
    """Keep runs/terminals whose midpoint lies inside the 2-98 % extent of the underlay linework of this page."""
    segs, _ = _seg_array(page, np.flatnonzero(~sel))
    if len(segs) < 50:
        return D, TT
    P = np.r_[segs[:, :2], segs[:, 2:]]
    (x0, y0), (x1, y1) = np.percentile(P, 2, axis=0), np.percentile(P, 98, axis=0)

    def inside(p):
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1
    return ([d for d in D if inside((np.array(d["start_pt"]) + np.array(d["end_pt"])) / 2)],
            [t for t in TT if inside(t["center_pt"])])


def label_scale(D: list[dict], min_n: int = 3, spread: float = 0.15) -> float | None:
    """Sheet scale (m per pt) from printed duct sizes: each run whose size label sits next to it gives
    label_across_m / drawn width (pt). Solid only with >= min_n labelled runs that agree within +-spread of their
    median; else None."""
    r = np.array([d["label_across_m"] / d["width_pt"] for d in D if d.get("label_across_m") and d.get("width_pt")])
    if len(r) < min_n:
        return None
    med = float(np.median(r))
    ok = np.abs(r / med - 1) <= spread
    return float(np.median(r[ok])) if ok.sum() >= min_n and ok.mean() >= 0.7 else None


def write_lengths(out_dir, D: list[dict], page: dict, planmap: dict, m_per_pt: float | None, *, source: str) -> Path | None:
    """<out_dir>/mep-lengths.json for engine.honesty.pdf_mep_lengths: one run per duct (item_id = the IfcDuctSegment
    item id "duct<k>", same k as _add_mep), length at the trusted sheet scale, bbox in page-image px. m_per_pt None
    (no solid scale evidence) -> no file, and a stale one is removed, so the engine abstains."""
    f = Path(out_dir) / "mep-lengths.json"
    if not m_per_pt or not D:
        f.unlink(missing_ok=True)
        return None
    img = planmap.get("image") or {}
    px_per_pt = float(img["w"]) / page["W_pt"] if img.get("w") else 1.0
    runs = []
    for k, d in enumerate(D):
        L = float(np.linalg.norm(np.subtract(d["end_pt"], d["start_pt"]))) * m_per_pt
        if L < 0.05:
            continue
        o = np.asarray(d["outline_pt"], float) * px_per_pt
        runs.append({"item_id": f"duct{k}", "kind": "duct", "length_m": round(L, 2),
                     "page": int(planmap.get("page", page.get("page_index", 0) + 1)),
                     "bbox_px": [round(float(v), 1) for v in (*o.min(0), *o.max(0))], "source": "pdf_mep",
                     "width_m": round(float(d["width_pt"]) * m_per_pt, 3), "label": d.get("label")})
    import json
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"runs": runs, "m_per_pt": m_per_pt, "scale_source": source,
                               "total_length_m": round(sum(r["length_m"] for r in runs), 1)}))
    tmp.replace(f)
    return f


def enrich_ifc(ifc_path, pdf_path, page_index: int, planmap: dict, *, shots_prefix=None) -> dict:
    """Add the ventilation system drawn on this PDF page to the IFC that pdf_to_ifc built from the same page's plan
    map. Same transform as pdf_to_ifc (plan x = pt * m_per_pt, y = -pt * m_per_pt; m_per_pt from the plan map).
    Writes ifc_path in place via a temp file + atomic replace (the input is untouched if anything fails). Ducts are
    clipped to the building outline (slab) + 1 m. Returns a report; raises on failure."""
    import os
    import ifcopenshell
    from pipeline.pdf_to_ifc import _W
    t0 = time.time()
    page = _load_cached(pdf_path, page_index)
    mpt = _planmap_m_per_pt(planmap, page)
    sc = planmap.get("scale") or {}
    # detection tolerances are in metres: a guessed plan-map scale (door guess on a sheet full of MEP arcs) can be
    # off by 4x; then read the sheet at the usual MEP plan scale 1:50 and size the IFC elements from the drawing
    confident = float(sc.get("confidence") or 0) >= 0.6 or "printed" in str(sc.get("method") or "")
    mdet = mpt if confident else 0.0254 / 72 * MEP_DEFAULT_RATIO
    kinds, n = _cue_score(text_cues(page["words"]))
    if kinds < 2 or n < 4:          # precision first: no MEP text, no MEP elements (same gate as is_mep_sheet)
        _CACHE.clear()
        try:
            (Path(ifc_path).parent / "mep-lengths.json").unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True, "method": "not an MEP sheet", "ducts": 0, "fittings": 0, "terminals": 0,
                "total_s": round(time.time() - t0, 1)}
    sp = _CACHE.get("sep") or separate(page, None, None)
    vt = prime_vtext(page, mdet, Path(ifc_path).parent, page_index)
    r = detect(page, mdet, sp["mep"] if sp["method"] == "style" else np.zeros(len(page["paths"]), bool))
    r["method"] = sp["method"]
    if mdet != mpt:
        for d in r["ducts"]:
            d.update(width_m=round(d["width_pt"] * mpt, 3), length_m=round(d["length_m"] * mpt / mdet, 3),
                     height_m=None)
            if d.get("shape") == "round":
                d["diameter_m"] = d["width_m"]
        for t in r["terminals"]:
            t["size_m"] = round(t["size_pt"] * mpt, 3)
    D, TT, clip = r["ducts"], r["terminals"], "none"
    if D or TT:
        # the building outline from the IFC (slab) when it is credible (holds most of the runs); else the extent
        # of the underlay linework on this page (title block / legend sit outside it)
        D1, T1 = clip_to_outline(D, TT, ifc_path, None)
        if len(D1) >= 0.5 * len(D):
            D, TT, clip = D1, T1, "ifc outline"
        else:
            (D, TT), clip = _clip_to_underlay(page, r["mep"], D, TT), "underlay extent"
    FF = _fittings(D, mpt)
    t_det = time.time() - t0
    rep = {"ok": True, "detect_s": round(t_det, 1), "vtext": vt,
           "duct_length_m_drawing_scale": round(sum(d["length_m"] for d in D) * (mdet / mpt), 1), "method": r["method"], "m_per_pt": mpt, "m_per_pt_detect": mdet, "ducts": len(D),
           "duct_length_m": round(sum(d["length_m"] for d in D), 1), "fittings": len(FF), "terminals": len(TT),
           "ducts_before_outline_clip": len(r["ducts"]), "clip": clip}
    if D or TT:
        f = ifcopenshell.open(str(ifc_path))
        st = f.by_type("IfcBuildingStorey")[0]
        body = next(c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
        import ifcopenshell.util.element as ue
        h0 = (ue.get_psets(st).get("Hologram_StoreySource") or {}).get("WallHeight")
        h1 = (planmap.get("semantics") or {}).get("wall_height_m")
        pc = _printed_ceiling(page)
        if pc:
            h, csrc = pc
        else:
            h = h0 or h1 or 2.7
            csrc = "storey WallHeight" if h0 else "plan map wall height" if h1 else "default"
        doc_id = (ue.get_psets(st).get("Hologram_Provenance") or {}).get("doc_id") or "mep"
        w = _W(f, body, doc_id, int(planmap.get("page", page_index + 1)),
               {"source": "pdf_mep", "m_per_pt": mpt, "ceiling_height_m": float(h)})

        def plan(p):
            return float(p[0] * mpt), float(-p[1] * mpt)
        rep.update(_add_mep(f, w, st, D, TT, FF, plan, ceiling_height=float(h), ceiling_source=csrc))
        try:    # MEP types, ports, materials (ifc_enrich v2)
            from pipeline import ifc_enrich
            ifc_enrich.mep_native(f)
        except Exception:  # noqa: BLE001  optional
            pass
        tmp = Path(str(ifc_path) + ".mep.tmp")
        f.write(str(tmp))
        os.replace(tmp, ifc_path)
    # duct lengths for cited answers, only at a scale with solid evidence (printed / confident plan-map scale, or
    # >= 3 agreeing printed duct sizes); the 1:50 working assumption is not evidence
    try:
        ls = label_scale(D)
        trusted, src = (mpt, f"plan map ({sc.get('method')})") if confident else \
            (ls, "printed duct sizes") if ls else (None, None)
        lf = write_lengths(Path(ifc_path).parent, D, page, planmap, trusted, source=src or "")
        rep["lengths_file"] = str(lf) if lf else None
        rep["lengths_scale"] = src
    except Exception as e:  # noqa: BLE001  optional: the IFC is already written
        rep["lengths_file"], rep["lengths_error"] = None, repr(e)[:160]
    if shots_prefix:
        rep["overlay"] = overlay(page, r["mep"], f"{shots_prefix}-split.png", ducts=D, terms=TT,
                                 title=f"{r['method']}: underlay grey, MEP red, ducts blue, terminals green")
    _CACHE.clear()
    rep["total_s"] = round(time.time() - t0, 1)
    return rep
