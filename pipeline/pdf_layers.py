"""Pseudo-layers of a vector PDF page (research test, used only when env PDF_PEN_LAYERS is set).

CAD plots draw each CAD layer with its own pen, so a "pen signature" (stroke colour rounded to 0.05, line width
to 0.01, fill colour or pattern, dash) is a usable stand-in for the lost layer table. Real optional-content layers
win when the loader exposes them (a path key "ocg" with the layer name; the current loaders do not yet).

layers(page) -> list of dicts (cached on page["_layers"]; never raises; [] on error):
    {"id": "L03", "source": "ocg"|"pen", "name": str|None, "sig": {"stroke","width","fill","dash"},
     "paths": [path indices], "n": int, "role": str, "conf": float, "evidence": str, "ink": share of page ink}
role_mask(page, *roles) -> bool array over page["paths"] (True = the path's layer has one of the roles).
wall_page(page, level) -> a shallow copy of page whose "paths" omit layers that are clearly not walls (level 1:
    text, light background linework, dimension, dashed; level 2 also door/fixture/other pens when the page
    has wall pens), or the page itself when the layers give no confident split.

Roles come only from general geometry evidence: parallel partners at wall spacing (2.5-20 pt) measured along
the page's dominant direction, orthogonality, 45-degree ticks, arcs, glyph-sized curves inside word boxes, fill
grey, pattern fills, dashes. No document-specific colours, widths or sizes.
"""
from __future__ import annotations

import math

import numpy as np

ROLES = ("wall", "wall_fill", "door", "window", "stair", "fixture", "furniture", "column", "grid", "dimension",
         "text", "hatch", "mep", "background", "titleblock", "mask", "other")
DROP_L1 = ("text", "background", "dimension", "grid")  # hatch stays: walls() gates double outlines on poche
DROP_L2 = DROP_L1 + ("door", "fixture", "other")
MIN_CONF = 0.5


def _q(c, s=0.05):
    return None if c is None else tuple(round(round(float(v) / s) * s, 2) for v in c)


_SIG_CACHE: dict = {}


def _sig(p):
    raw = (tuple(p["stroke"]) if p.get("stroke") is not None else None, p.get("width"),
           tuple(p["fill"]) if p.get("fill") is not None else None, bool(p.get("pattern")), bool(p.get("dashed")))
    try:
        hit = _SIG_CACHE.get(raw)
    except TypeError:  # unhashable colour entry
        return _sig_raw(p)
    if hit is None:
        if len(_SIG_CACHE) > 10000:
            _SIG_CACHE.clear()
        hit = _SIG_CACHE[raw] = _sig_raw(p)
    return hit


def _sig_raw(p):
    st = _q(p.get("stroke"))
    fill = "pattern" if p.get("pattern") else _q(p.get("fill"))
    return (st, round(float(p.get("width") or 0), 2) if st is not None else 0.0, fill, bool(p.get("dashed")))


def _grey(c):
    return float("nan") if c is None else 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _dominant_angle(seg, L):
    a = np.mod(np.arctan2(seg[:, 3] - seg[:, 1], seg[:, 2] - seg[:, 0]), np.pi / 2)
    h = np.bincount(np.degrees(a).astype(int) % 90, L, 90)
    h = h + np.roll(h, 1) + np.roll(h, -1)
    return math.radians(int(np.argmax(h)) + 0.5)


def _par_fraction(S, L, ang, rng):
    """Share of a pen's straight ink that has a parallel partner segment 2.5-20 pt away (wall spacing).
    Partners are searched among up to 60k probe points along the pen's segments; the share is estimated from a
    random 4k subset of them as queries (the costly all-pairs search over 60k points is not needed)."""
    if len(S) > 20000:
        sel = rng.choice(len(S), 20000, replace=False, p=L / L.sum())
        S, L, ang = S[sel], L[sel], ang[sel]
    m = np.clip((L / 3).astype(int), 1, 30)
    rep = np.repeat(np.arange(len(S)), m)
    t = (np.arange(len(rep)) - np.repeat(np.cumsum(m) - m, m) + 0.5) / m[rep]
    px = S[rep, 0] + t * (S[rep, 2] - S[rep, 0])
    py = S[rep, 1] + t * (S[rep, 3] - S[rep, 1])
    pa, pw = ang[rep], (L / m)[rep]
    if len(px) > 60000:
        k = rng.choice(len(px), 60000, replace=False)
        px, py, pa, pw, rep = px[k], py[k], pa[k], pw[k], rep[k]
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([px, py]))
    qi = rng.choice(len(px), 4000, replace=False) if len(px) > 4000 else np.arange(len(px))
    sm = cKDTree(np.column_stack([px[qi], py[qi]])).sparse_distance_matrix(tree, 20.0, output_type="ndarray")
    if not len(sm):
        return 0.0
    i0, i1 = qi[sm["i"]], sm["j"]
    dx, dy = px[i1] - px[i0], py[i1] - py[i0]
    dist = np.hypot(dx, dy)
    da = np.abs(pa[i0] - pa[i1])
    da = np.minimum(da, np.pi - da)
    perp = np.abs(-np.sin(pa[i0]) * dx + np.cos(pa[i0]) * dy) / np.maximum(dist, 1e-9)
    ok = (dist >= 2.5) & (da < math.radians(2)) & (perp > 0.97) & (rep[i0] != rep[i1])
    has = np.zeros(len(px), bool)
    has[i0[ok]] = True
    return float(pw[qi][has[qi]].sum() / max(pw[qi].sum(), 1e-9))


def _role(f):
    """(role, conf, evidence) from one layer's feature dict."""
    g, fg = f["grey"], f["fgrey"]
    if f["fill"] > 0.5 and not math.isnan(fg) and fg > 0.97 and math.isnan(g):
        return "mask", 0.9, "white fills only"
    if f["in_word"] > 0.5 or (f["small"] > 0.6 and f["curv"] > 0.4 and f["med_size"] < 6):
        return "text", 0.5 + 0.5 * max(f["in_word"], f["small"]), f"in_word {f['in_word']:.2f} small {f['small']:.2f}"
    if f["pattern"] > 0.5:
        return "hatch", 0.9, "pattern fill"
    if f["dashed"] > 0.5:
        return "grid", 0.7, "dashed"
    wallish = f["par"] > 0.55 and f["ortho"] > 0.6
    if not math.isnan(g) and f["fill"] < 0.5 and (g > 0.7 or (g > 0.6 and f["par"] < 0.4)) and not wallish:  # light pens that pair up at wall spacing stay walls
        return "background", min(1.0, 0.5 + (g - 0.6) * 2), f"light pen {g:.2f} par {f['par']:.2f}"
    if f["arc"] > 0.25 and f["ortho"] < 0.8:
        return "door", 0.6, f"arc ink {f['arc']:.2f}"
    if f["diag45"] > 0.5 and f["short"] > 0.3:
        return "dimension", 0.7, f"45deg ticks {f['diag45']:.2f} short {f['short']:.2f}"
    if f["diag45"] > 0.6 or (f["par"] > 0.7 and f["ortho"] < 0.4):
        return "hatch", 0.6, f"diag {f['diag45']:.2f} par {f['par']:.2f}"
    if f["fill"] > 0.5 and not math.isnan(fg) and fg < 0.97 and f["ortho"] > 0.6 and (fg < 0.7 or f["par"] > 0.5):
        return "wall_fill", 0.6 + 0.4 * min(1.0, f["par"]), f"fills grey {fg:.2f} par {f['par']:.2f}"
    if wallish:
        return "wall", min(1.0, 0.4 + f["par"] * 0.6 * f["ortho"] + 0.1), f"par {f['par']:.2f} ortho {f['ortho']:.2f}"
    if f["curv"] > 0.2 or (f["closed"] > 0.5 and f["med_size"] < 60):
        return "fixture", 0.4, f"curv {f['curv']:.2f} closed {f['closed']:.2f}"
    return "other", 0.3, f"par {f['par']:.2f} ortho {f['ortho']:.2f}"


def _build(page):
    paths = page.get("paths") or []
    n = len(paths)
    if not n:
        return []
    from pipeline import pdf_vector
    F = pdf_vector._flat(page)
    seg, sp = F["seg"], F["sp"]
    L = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]) if len(seg) else np.zeros(0)
    ink = np.bincount(sp, L, n) if len(seg) else np.zeros(n)
    tot = max(float(ink.sum()), 1e-9)
    # group: real OCG name when the loader gave one, else the pen signature
    # one pass over the paths builds a raw key; the (slower) quantised signature is computed per distinct raw key
    raw_ids: dict = {}
    firsts: list = []
    rid = np.empty(n, np.int64)
    for i, p in enumerate(paths):
        o = p.get("ocg")
        st_, fl_ = p.get("stroke"), p.get("fill")
        k = ("ocg", o) if o else (tuple(st_) if st_ is not None else None, p.get("width"),
                                  tuple(fl_) if fl_ is not None else None, bool(p.get("pattern")), bool(p.get("dashed")))
        r = raw_ids.get(k)
        if r is None:
            r = raw_ids[k] = len(raw_ids)
            firsts.append(i)  # a path carrying this raw key
        rid[i] = r
    ids = {}
    r2g = np.empty(len(raw_ids), np.int64)
    for k, r in raw_ids.items():
        key = k if k[0] == "ocg" else ("pen", _sig_raw(paths[firsts[r]]))
        r2g[r] = ids.setdefault(key, len(ids))
    gid = r2g[rid]
    klist = list(ids)
    bb = F["bbox"]
    size = np.nan_to_num(np.maximum(bb[:, 2] - bb[:, 0], bb[:, 3] - bb[:, 1]), nan=0.0)
    cx, cy = (bb[:, 0] + bb[:, 2]) / 2, (bb[:, 1] + bb[:, 3]) / 2
    in_word = np.zeros(n, bool)
    words = page.get("words") or []
    if words:
        from scipy.spatial import cKDTree
        WB = np.array([w["bbox"] for w in words], float).reshape(-1, 4)
        ok = np.isfinite(cx)
        d, j = cKDTree(np.column_stack([(WB[:, 0] + WB[:, 2]) / 2, (WB[:, 1] + WB[:, 3]) / 2])).query(
            np.column_stack([np.nan_to_num(cx[ok]), np.nan_to_num(cy[ok])]))
        wb = WB[j]
        cxo, cyo = cx[ok], cy[ok]
        in_word[ok] = ((cxo >= wb[:, 0] - 1) & (cxo <= wb[:, 2] + 1) & (cyo >= wb[:, 1] - 1) & (cyo <= wb[:, 3] + 1)
                       & (size[ok] < 12))
    straight = ~F["arc"][sp] & (L > 0.3) if len(seg) else np.zeros(0, bool)
    dom = _dominant_angle(seg[straight], L[straight]) if straight.any() else 0.0
    ang_all = np.mod(np.arctan2(seg[:, 3] - seg[:, 1], seg[:, 2] - seg[:, 0]) - dom + math.radians(0.5), np.pi) \
        if len(seg) else np.zeros(0)
    sgid = gid[sp] if len(seg) else np.zeros(0, np.int64)
    fills = [p.get("fill") for p in paths]
    fgrey_all = np.array([np.nan if c is None else _grey(c) for c in fills], float)
    pattern_all = np.fromiter((bool(p.get("pattern")) for p in paths), bool, n)
    rng = np.random.default_rng(0)
    out = []
    order = np.argsort(-np.bincount(gid, ink, len(klist)), kind="stable")
    for rank, g in enumerate(order):
        ix = np.flatnonzero(gid == g)
        wk = ink[ix]
        T = max(float(wk.sum()), 1e-9)
        sk = np.flatnonzero((sgid == g) & straight)
        par = ortho = diag45 = short = 0.0
        if len(sk):
            S, Ls, an = seg[sk], L[sk], ang_all[sk]
            sw = Ls.sum()
            dev = np.minimum(np.abs(an - np.pi / 2), np.minimum(an, np.pi - an))
            ortho = float(Ls[dev < math.radians(3)].sum() / sw)
            diag45 = float(Ls[np.minimum(np.abs(an - np.pi / 4), np.abs(an - 3 * np.pi / 4)) < math.radians(5)].sum() / sw)
            short = float(Ls[Ls < 3].sum() / sw)
            if T / tot > 0.002 or len(ix) > 20:
                par = _par_fraction(S, Ls, an, rng)
        sg_ = F["grey"][ix]
        sg_ = sg_[~np.isnan(sg_)]
        fg_ = fgrey_all[ix]
        fg_ = fg_[~np.isnan(fg_)]
        f = {"ink": T / tot, "closed": float(wk[F["closed"][ix]].sum() / T), "arc": float(wk[F["arc"][ix]].sum() / T),
             "curv": float(wk[F["n_curves"][ix] > 0].sum() / T), "fill": float(F["fill"][ix].mean()),
             "in_word": float(wk[in_word[ix]].sum() / T) if T > 1e-6 else float(in_word[ix].mean()),
             "small": float(wk[size[ix] < 8].sum() / T), "par": par, "ortho": ortho, "diag45": diag45,
             "short": short, "grey": float(np.median(sg_)) if len(sg_) else float("nan"),
             "fgrey": float(np.median(fg_)) if len(fg_) else float("nan"),
             "dashed": float(F["dashed"][ix].mean()), "pattern": float(pattern_all[ix].mean()),
             "med_size": float(np.median(size[ix]))}
        role, conf, ev = _role(f)
        kind, k = klist[g]
        if kind == "pen":
            sig = {"stroke": k[0], "width": k[1], "fill": k[2], "dash": k[3]}
        else:
            p0 = paths[ix[0]]
            sig = {"stroke": _q(p0.get("stroke")), "width": round(float(p0.get("width") or 0), 2),
                   "fill": "pattern" if p0.get("pattern") else _q(p0.get("fill")), "dash": bool(p0.get("dashed"))}
        out.append({"id": f"L{rank:02d}", "source": kind, "name": k if kind == "ocg" else None, "sig": sig,
                    "paths": ix.tolist(), "n": int(len(ix)), "role": role, "conf": round(float(conf), 2),
                    "evidence": ev, "ink": round(f["ink"], 4), "feats": {a: (None if isinstance(b, float) and
                                                                            math.isnan(b) else round(b, 3))
                                                                        for a, b in f.items()}})
    return out


def layers(page) -> list:
    """Pseudo-layers of page (cached on page["_layers"]). Never raises; [] on error."""
    try:
        c = page.get("_layers")
        if c is not None and c[0] is page.get("paths"):
            return c[1]
        out = _build(page)
        page["_layers"] = (page.get("paths"), out)
        return out
    except Exception:  # noqa: BLE001
        return []


def role_mask(page, *roles, min_conf: float = 0.0) -> np.ndarray:
    """Bool mask over page["paths"]: path belongs to a layer whose role is in roles (and conf >= min_conf)."""
    n = len(page.get("paths") or [])
    m = np.zeros(n, bool)
    try:
        for L in layers(page):
            if L["role"] in roles and L["conf"] >= min_conf:
                m[L["paths"]] = True
    except Exception:  # noqa: BLE001
        return np.zeros(n, bool)
    return m


def wall_page(page, level: int = 1):
    """Shallow copy of page with the paths of clearly-non-wall layers removed (see module docstring), or page
    itself when nothing confident is found. The copy keeps the original indices in "_orig_index"."""
    Ls = layers(page)
    if not Ls:
        return page
    wall_ink = sum(L["ink"] for L in Ls if L["role"] in ("wall", "wall_fill"))
    if wall_ink < 0.05:  # no wall pens: the split is not trustworthy for this page
        return page
    drop = DROP_L2 if level >= 2 and wall_ink >= 0.2 else DROP_L1
    m = role_mask(page, *drop, min_conf=MIN_CONF)
    if not m.any():
        return page
    keep = np.flatnonzero(~m)
    q = dict(page)
    q.pop("_layers", None)
    q["paths"] = [page["paths"][i] for i in keep]
    q["_orig_index"] = keep
    q["_pen_dropped"] = int(m.sum())
    return q
