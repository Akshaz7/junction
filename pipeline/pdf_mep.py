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

Coordinates: everything is converted into ARK page points first (T), then into the ARK IFC's plan metres the same
way pdf_to_ifc does (x_m = x_pt * m_per_pt, y_m = -y_pt * m_per_pt; m_per_pt read from the IFC's Hologram_Provenance).
No per-document constants: tolerances are in metres (through the scale) or relative to the page.
"""
from __future__ import annotations

import ctypes
import math
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
DASH_GAP_M = 0.3                              # exploded dash-dot linetypes: dashes this close are one line
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
            for k in range(n):
                seg = GetSeg(obj, k)
                GetPt(seg, bfx, bfy)
                t = GetType(seg)
                x, y = fx.value, fy.value
                if t == MOVE:
                    flush(i0, closed, curves)
                    i0, closed, curves, nb = len(xs), False, 0, 0
                elif t == BEZ:
                    nb += 1
                    if nb % 3 == 1:                  # keep curve ends + mid control: enough for symbol sizes
                        continue
                    if nb % 3 == 0:
                        curves += 1
                xs.append(a * x + c * y + e)
                ys.append(b * x + d * y + f)
                if GetClose(seg):
                    closed = True
                    xs.append(xs[i0])
                    ys.append(ys[i0])
            flush(i0, closed, curves)

        def walk(get_count, get_obj, parent, depth, layer):
            for k in range(get_count()):
                obj = get_obj(k)
                t = R.FPDFPageObj_GetType(obj)
                lay = layer_of(obj, layer)
                if lay:
                    layers[lay] += 1
                if t == R.FPDF_PAGEOBJ_PATH:
                    do_path(obj, _mat_mul(matrix(obj), parent), lay)
                elif t == R.FPDF_PAGEOBJ_FORM and depth < 12:
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
    grey_len = sum(plen[i] for k, idx in groups.items() for i in idx if _is_grey(k[1]))
    sel = np.array([not _is_grey(k[1]) for k in keys])
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
    order = np.lexsort((t0, ob, ab, sty))
    out = []
    cur = None
    for i in order:
        key = (sty[i], ab[i], ob[i])
        if cur is not None and cur[0] == key and t0[i] <= cur[3] + gap:
            cur[3] = max(cur[3], t1[i])
            cur[4].append(rho[i])
            cur[5] += t1[i] - t0[i]
            if cur[6] != own[i]:
                cur[6] = -1
            continue
        if cur is not None:
            out.append(cur)
        cur = [key, thq[i], t0[i], t1[i], [rho[i]], t1[i] - t0[i], own[i]]
    if cur is not None:
        out.append(cur)
    return np.array([[c[1], float(np.mean(c[4])), c[2], c[3], math.cos(c[1]), math.sin(c[1]), c[0][0], c[5], c[6]]
                     for c in out]) if out else np.zeros((0, 9))


def ducts(page: dict, sel: np.ndarray, m_per_pt: float, *, min_w: float = DUCT_MIN_M, max_w: float = DUCT_MAX_M,
          min_len: float = DUCT_MIN_LEN_M) -> list[dict]:
    """Duct runs = pairs of parallel MEP lines min_w..max_w apart that run side by side for >= min_len.
    Hatching (3+ equally spaced parallels) is rejected. Width in metres from the pair gap; a size label
    ("400x200", "ø250") from the text layer within 1.5 m sets the section."""
    keep = [i for i in np.flatnonzero(sel) if page["paths"][i]["stroke"] is not None and not page["paths"][i]["dashed"]]
    segs, own = _seg_array(page, keep)
    if not len(segs):
        return []
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    ok = L * m_per_pt >= 0.03
    segs, own = segs[ok], own[ok]
    skeys = {}
    sid = np.array([skeys.setdefault(style_key(page["paths"][o]), len(skeys)) for o in own])
    # closed small rectangles (label frames, symbols) keep their path id so their sides are not read as a duct
    cid = np.array([o if page["paths"][o]["closed"] and page["paths"][o]["i1"] - page["paths"][o]["i0"] <= 6 else -1
                    for o in own])
    S = _merge_collinear(segs, math.radians(1.0), 0.01 / m_per_pt, DASH_GAP_M / m_per_pt, (sid, cid))
    S = S[((S[:, 3] - S[:, 2]) * m_per_pt >= 0.3) & (S[:, 7] >= 0.4 * (S[:, 3] - S[:, 2]))]   # short ones only
    # count as "a line between" below; pairs still need min_len
    if not len(S):
        return []
    dmin, dmax, lmin = min_w / m_per_pt, max_w / m_per_pt, min_len / m_per_pt
    nb = int(round(180 / 1.0))
    ab = np.round(S[:, 0] / math.radians(1.0)).astype(int) % nb
    cand = []
    by = defaultdict(list)
    for i, b in enumerate(ab):
        by[b].append(i)
    for b, idx in by.items():
        idx = np.array(idx)
        idx = idx[np.argsort(S[idx, 1])]
        rho = S[idx, 1]
        for a_, i in enumerate(idx):
            j0, j1 = np.searchsorted(rho, rho[a_] + dmin), np.searchsorted(rho, rho[a_] + dmax, side="right")
            for j in idx[j0:j1]:
                if S[i, 6] != S[j, 6]:
                    continue        # both sides of one duct are drawn with the same pen
                if S[i, 8] >= 0 and S[i, 8] == S[j, 8]:
                    continue        # two sides of one small closed rectangle: a frame or symbol
                lo, hi = max(S[i, 2], S[j, 2]), min(S[i, 3], S[j, 3])
                li, lj = S[i, 3] - S[i, 2], S[j, 3] - S[j, 2]
                # side by side over most of both lines, ends roughly level (fans of leader lines are staggered)
                if hi - lo >= lmin and hi - lo >= 0.7 * max(li, lj) - 1.0 / m_per_pt:
                    # a third parallel line (any pen) between the two along most of the run: two neighbouring
                    # ducts (or a duct and a leader), not one wide duct
                    mid = idx[a_ + 1:np.searchsorted(rho, S[j, 1])]
                    mid = mid[(S[mid, 1] > S[i, 1] + 0.05 * (S[j, 1] - S[i, 1])) &
                              (S[mid, 1] < S[j, 1] - 0.05 * (S[j, 1] - S[i, 1]))]
                    if len(mid) and np.any(np.minimum(S[mid, 3], hi) - np.maximum(S[mid, 2], lo) >= 0.5 * (hi - lo)):
                        continue
                    cand.append((S[j, 1] - S[i, 1], i, j, lo, hi))
    cand.sort()
    used_lo, used_hi, pairs = set(), set(), []
    for gap, i, j, lo, hi in cand:      # nearest partner first; each line pairs once per side
        if i in used_lo or j in used_hi:
            continue
        used_lo.add(i)
        used_hi.add(j)
        pairs.append((gap, i, j, lo, hi))
    # hatching / stacked runs: a line that is the upper side of one pair and the lower of another at a similar gap
    up = {j: (g, i) for g, i, j, lo, hi in pairs}
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
    ny, nx = ink.shape
    out = []
    for g, i, j, lo, hi in pairs:
        if i in hatch or j in hatch:
            continue
        u = S[i, 4:6]
        nrm = np.array([-u[1], u[0]])
        ts = np.linspace(lo, hi, max(2, int((hi - lo) / cell)))
        rs = np.linspace(S[i, 1] + 0.2 * g, S[j, 1] - 0.2 * g, max(2, int(0.6 * g / cell)))
        TT, RR = np.meshgrid(ts, rs)
        X, Y = TT * u[0] + RR * nrm[0], TT * u[1] + RR * nrm[1]
        ix, iy = np.clip((X / cell).astype(int), 0, nx - 1), np.clip((Y / cell).astype(int), 0, ny - 1)
        if ink[iy, ix].mean() > 0.15:
            continue        # text frame / symbol row
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
            return ink[iy, ix].mean()
        m0, m1 = mouth(lo), mouth(hi)
        if max(m0, m1) < 0.5:
            continue        # open at both ends: leader lines / dimension lines
        if (hi - lo) * m_per_pt < 1.5 and max(texty(lo, -1), texty(hi, 1)) > 0.25:
            continue        # short pair ending in text: a label frame or a leader into its tag
        u = S[i, 4:6]
        nrm = np.array([-u[1], u[0]])
        rm = (S[i, 1] + S[j, 1]) / 2
        p0, p1 = u * lo + nrm * rm, u * hi + nrm * rm
        half = nrm * g / 2
        d = {"start_pt": p0.tolist(), "end_pt": p1.tolist(), "width_pt": float(g), "width_m": round(g * m_per_pt, 3),
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
            else:   # "WxH": the drawn width tells which of the two numbers is across the plan
                a, b = best[3] / 1000, best[4] / 1000
                d["height_m"] = b if abs(a - d["width_m"]) <= abs(b - d["width_m"]) else a
        out.append(d)
    if len(out) >= 5:   # one wide "duct" spanning several: cap at 3x the typical run width
        wmed = float(np.median([d["width_m"] for d in out]))
        out = [d for d in out if d["width_m"] <= 3 * wmed]
    return out


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


def build_ifc(model_ifc_path, ducts_, terminals_, *, ceiling_height: float = 2.7, out_path=None, T: dict | None = None,
              doc_id: str = "mep", storey_name: str | None = None) -> Path:
    """Copy of the ARK IFC (pdf_to_ifc output) + one IfcDuctSegment per duct run and one IfcAirTerminal per terminal,
    contained in the ARK storey (first one, or storey_name). Duct/terminal coordinates are MEP page points; T maps them
    to ARK page points (None = already ARK points), then plan metres exactly like pdf_to_ifc (x*m_per_pt, -y*m_per_pt).
    Duct top = ceiling_height - 0.1 m; height from the size label else 0.3 m; round ducts (ø label) get a circle.
    Writes out_path (default <model>.mep.ifc) and never touches the input file."""
    import ifcopenshell
    import ifcopenshell.api.spatial
    from pipeline.pdf_to_ifc import _W, guid_for

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
    sp = st.ObjectPlacement

    def plan(p):
        q = apply_T(T, p)[0] if T else np.asarray(p, float)
        return float(q[0] * mpt), float(-q[1] * mpt)

    def style(key, rgb):
        if key not in w.styles:
            import ifcopenshell.api.style
            s = ifcopenshell.api.style.add_style(f, name=f"pdf_{key}")
            ifcopenshell.api.style.add_surface_style(f, style=s, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "Transparency": 0.0})
            w.styles[key] = s
        return w.styles[key]

    def put(product, item, key, rgb):
        import ifcopenshell.api.style
        rep = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [item])
        product.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        product.ObjectPlacement = w.placement(sp)
        ifcopenshell.api.style.assign_representation_styles(f, shape_representation=rep, styles=[style(key, rgb)])
        ifcopenshell.api.spatial.assign_container(f, products=[product], relating_structure=st)

    made = {"ducts": 0, "terminals": 0}
    for k, d in enumerate(ducts_):
        a, b = np.array(plan(d["start_pt"])), np.array(plan(d["end_pt"]))
        L = float(np.linalg.norm(b - a))
        if L < 0.05:
            continue
        u = (b - a) / L
        round_ = d.get("shape") == "round"
        wid = float(d.get("diameter_m") or d["width_m"]) if round_ else float(d["width_m"])
        h = wid if round_ else float(d.get("height_m") or DEFAULT_DUCT_H_M)
        zc = ceiling_height - CEILING_GAP_M - h / 2
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(a[0]), float(a[1]), float(zc))),
                                          f.createIfcDirection((float(u[0]), float(u[1]), 0.0)),
                                          f.createIfcDirection((float(-u[1]), float(u[0]), 0.0)))
        prof = (f.createIfcCircleProfileDef("AREA", None, None, wid / 2) if round_ else
                f.createIfcRectangleProfileDef("AREA", None, None, wid, h))
        solid = f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), L)
        e = w.entity("IfcDuctSegment", f"duct{k}", name=d.get("label") or f"Duct {k + 1}", predefined="RIGIDSEGMENT")
        put(e, solid, "duct", (0.55, 0.62, 0.72))
        w.pset(e, "Pset_DuctSegmentTypeCommon", {"Shape": "ROUND" if round_ else "RECTANGULAR"})
        w.qto(e, "Qto_DuctSegmentBaseQuantities", {"Length": L})
        w.pset(e, "Hologram_MEP", {"width_m": round(wid, 3), "height_m": round(h, 3), "size_label": d.get("label"),
                                   "height_source": "label" if d.get("height_m") or round_ else "default 0.3 m",
                                   "source": "pdf_mep pair of parallel MEP lines"})
        w.provenance(e, {"item_id": f"duct{k}"})
        made["ducts"] += 1
    for k, t in enumerate(terminals_):
        c = np.array(plan(t["center_pt"]))
        s = float(t["size_m"])
        th = 0.05
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(c[0]), float(c[1]), float(ceiling_height - th))),
                                          None, None)
        prof = (f.createIfcCircleProfileDef("AREA", None, None, s / 2) if t.get("shape") == "round" else
                f.createIfcRectangleProfileDef("AREA", None, None, s, s))
        solid = f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), th)
        e = w.entity("IfcAirTerminal", f"term{k}", name=t.get("label") or f"Air terminal {k + 1}", predefined="DIFFUSER")
        put(e, solid, "air_terminal", (0.2, 0.7, 0.4))
        w.pset(e, "Hologram_MEP", {"size_m": s, "shape": t.get("shape"), "airflow_ls": t.get("airflow_ls"),
                                   "source": "pdf_mep small closed MEP symbol"})
        w.provenance(e, {"item_id": f"term{k}"})
        made["terminals"] += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out))
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


def combine(ark_pdf, mep_pdf, ark_ifc, out_ifc, *, ceiling_height: float = 2.7, shots_prefix=None,
            ark_page_index: int = 0, mep_page_index: int = 0) -> dict:
    """ARK sheet + MEP sheet of the same floor + the ARK IFC -> out_ifc with ducts/terminals. Returns a report."""
    import ifcopenshell
    t0 = time.time()
    ark, mep = load(ark_pdf, ark_page_index), load(mep_pdf, mep_page_index)
    t_load = time.time() - t0
    mpt = _ark_scale(ifcopenshell.open(str(ark_ifc)))
    sp = split_mep(mep, ark, m_per_pt=mpt)
    D = ducts(mep, sp["mep"], sp["m_per_pt"])
    TT = terminals(mep, sp["mep"], sp["m_per_pt"])
    n_raw = len(D)
    D, TT = clip_to_outline(D, TT, ark_ifc, sp["T"])
    out = build_ifc(ark_ifc, D, TT, ceiling_height=ceiling_height, out_path=out_ifc, T=sp["T"])
    rep = {"method": sp["method"], "stats": sp["stats"], "clusters": sp.get("clusters", [])[:8],
           "align": {k: v for k, v in (sp["T"] or {}).items() if k not in ("R",)}, "m_per_pt_mep": sp["m_per_pt"],
           "ducts": len(D), "ducts_before_outline_clip": n_raw, "duct_length_m": round(sum(d["length_m"] for d in D), 1), "terminals": len(TT),
           "terminals_with_airflow": sum(t["airflow_ls"] is not None for t in TT), "out_ifc": str(out),
           "load_s": round(t_load, 1), "total_s": round(time.time() - t0, 1)}
    if shots_prefix:
        rep["overlay"] = overlay(mep, sp["mep"], f"{shots_prefix}-split.png", ducts=D, terms=TT,
                                 title=f"{sp['method']}: underlay grey, MEP red, ducts blue, terminals green")
    return rep
