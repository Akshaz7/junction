"""Furniture and fixture symbols on a vector plan page, found by repetition.

    find(page, mpt, *, wall_u=None, footprint=None, doors=None, rooms=None, words=None, budget_s=8.0)
        -> [{"kind", "polygon": [[x,y],...] page pt, "conf", "props": {"type", "size_m", "group", "n_group", ...}}]

CAD plots place the same block (bed, WC, chair, basin ...) many times, and most exports explode each instance
into loose lines and curves. So: segments that are not walls, hatch, dimension or long linework are clustered by
touch into components; components with the same rotation- and mirror-invariant signature (segment count, total
length, oriented-box size, curved share) that also match point for point after aligning their oriented boxes are
one symbol. A symbol placed 2+ times inside the building is classified from its real size in metres, its curved
share, the room label it sits in (several languages) and nearby printed words. No model is called (an optional
image check would go behind PDF_SYMBOLS_VISION, off by default). Never raises: [] on any error.

Page coordinates are pdf_vector's (page points, top-left origin, y down). Kinds follow pdf_fixtures:
wc | basin | shower | bath | sink | furniture (props.type bed/sofa/table/chair/desk/wardrobe/furniture).
"""
from __future__ import annotations

import math
import re
import time

import numpy as np

MAX_EXT_M = 3.3      # biggest symbol extent (a double bed with bedside tables)
MAX_SEG_M = 2.6      # longer lines are walls, counters, grids, dimensions
MIN_EXT_M = 0.30     # smaller repeated things are dimension ticks, outlets, tags
MIN_SEGS = 3
TOUCH_M = 0.012      # lines of one exploded block touch (shared endpoints / T-junctions)

BATH = re.compile(r"bath|\bwc\b|w\.c|toilet|restroom|\blav|\bkh\b|\bph\b|\bpkh\b|\bkph\b|\bbad\b|suihku|\bwash\b|wash ?room|shower|"
                  r"dusche|wasch|sauna|\bmen\b|women|unisex|badrum|toalett|kylpy|\bdu\b", re.I)
KITCHEN = re.compile(r"kitchen|kitch|\bkit\b|keitti|k[üu]che|\bkt\b|\bkk\b|kök|pantry|break ?room|cafe|galley", re.I)
BED = re.compile(r"bed|\bbr\b|sleep|schlaf|makuu|\bmh\b|sovrum|chambre|dorm|guest", re.I)
LIVING = re.compile(r"living|lounge|family|\bliv\b|wohn|olohuone|\boh\b|vardagsrum|salon|den\b|great ?room", re.I)
OFFICE = re.compile(r"office|work|study|b[üu]ro|toimisto|kontor|classroom|class|lab\b|library|meeting|conf", re.I)
DINING = re.compile(r"dining|dine|\bdin\b|ess|ruokailu|matsal|cafe|break|lunch|canteen", re.I)
NOT_FURN = re.compile(r"stor|mech|hvac|elec|janitor|jan\.?|shaft|corr|hall|lobby|stair|elev|w/d|laundry|clos|"
                      r"garage|park|vest|entry|balc|patio|deck|roof|tekn|vari|porras|käytävä", re.I)


def find(page, mpt, *, wall_u=None, footprint=None, doors=None, rooms=None, words=None, budget_s=8.0) -> list:
    try:
        return _find(page, float(mpt or 0), wall_u, footprint, doors, rooms or [], words, float(budget_s))
    except Exception:  # noqa: BLE001 - symbols never break ingest
        return []


# ---------------------------------------------------------------- segments and components

def _segments(page, mpt, wall_u, footprint):
    """(N,4) segments in pt with curved flags and owner path ids; walls, hatch, dashes and long lines removed."""
    import shapely
    paths = page.get("paths") or []
    drop = _layer_drop(page)
    A, I, C, K = [], [], [], []
    pens = {}
    for i, p in enumerate(paths):
        q = p.get("pts") or ()
        if len(q) < 2 or p.get("dashed") or p.get("pattern"):
            continue
        st = p.get("stroke")
        if st is None:  # fills alone (poché, masks) draw no symbol linework
            continue
        if 0.299 * st[0] + 0.587 * st[1] + 0.114 * st[2] > 0.8:
            continue  # very light pens: floor hatch, background / xref underlay
        if drop is not None and drop[i]:
            continue
        if p.get("closed") and (q[0][0] != q[-1][0] or q[0][1] != q[-1][1]):
            q = list(q) + [q[0]]
        cur = int(p.get("n_curves") or 0) > 0
        pen = pens.setdefault((tuple(round(float(v), 2) for v in st), round(float(p.get("width") or 0), 2)), len(pens))
        for a, b in zip(q[:-1], q[1:]):
            A.append((a[0], a[1], b[0], b[1]))
            I.append(i)
            C.append(cur)
            K.append(pen)
    if not A:
        return None
    S = np.asarray(A, float)
    I = np.asarray(I)
    C = np.asarray(C, bool)
    K = np.asarray(K)
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) * mpt
    keep = (L > 1e-4) & (L <= MAX_SEG_M)
    mx, my = (S[:, 0] + S[:, 2]) / 2, (S[:, 1] + S[:, 3]) / 2
    if footprint is not None:
        keep &= shapely.contains_xy(footprint, mx, my)
    if wall_u is not None:
        wb = wall_u.buffer(0.02 / mpt)
        shapely.prepare(wb)
        keep &= ~shapely.contains_xy(wb, mx, my)
    return S[keep], C[keep], I[keep], L[keep], K[keep]


def _layer_drop(page):
    """Paths on pseudo-layers that are confidently hatch, dimensions, text or grid (pdf_layers, when present)."""
    try:
        from pipeline import pdf_layers
        m = pdf_layers.role_mask(page, "hatch", "dimension", "text", "grid", min_conf=0.5)
        return m if len(m) == len(page.get("paths") or []) and m.any() else None
    except Exception:  # noqa: BLE001 - layers are optional
        return None


class _DSU:
    def __init__(self, n):
        self.p = np.arange(n)

    def find(self, a):
        p = self.p
        r = a
        while p[r] != r:
            r = p[r]
        while p[a] != r:
            p[a], a = r, p[a]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _components(S, K, mpt, t_end):
    """Groups of touching segments drawn with the same pen (STRtree dwithin on the segment lines): a symbol is
    one CAD block on one layer, while floor hatch, dimensions and leaders that touch it come in other pens."""
    import shapely
    n = len(S)
    lines = shapely.linestrings(np.stack([S[:, :2], S[:, 2:]], axis=1))
    tree = shapely.STRtree(lines)
    a, b = tree.query(lines, predicate="dwithin", distance=TOUCH_M / mpt)
    same = K[a] == K[b]
    a, b = a[same], b[same]
    d = _DSU(n)
    for x, y in zip(a.tolist(), b.tolist()):
        if x < y:
            d.union(x, y)
        if time.time() > t_end:
            break
    roots = np.array([d.find(i) for i in range(n)])
    order = np.argsort(roots, kind="stable")
    r = roots[order]
    cuts = np.flatnonzero(np.r_[True, r[1:] != r[:-1], True])
    return [order[cuts[k]:cuts[k + 1]] for k in range(len(cuts) - 1)]


def _split(S, K, L, mpt, t_end, cuts=(1.2, 0.7)):
    """Components small enough to be one symbol. A cluster bigger than any symbol (fixtures drawn into a
    counter or tied by a partition line) is split again without its longer lines, at most twice."""
    todo = [(c, 0) for c in _components(S, K, mpt, t_end)]
    while todo:
        idx, lev = todo.pop()
        if len(idx) < MIN_SEGS:
            continue
        P = np.vstack([S[idx, :2], S[idx, 2:]])
        ext = float(np.hypot(*(P.max(0) - P.min(0)))) * mpt
        if ext <= MAX_EXT_M * 1.3 and len(idx) <= 400:
            yield idx
            continue
        if lev >= len(cuts) or time.time() > t_end:
            continue
        sub = idx[L[idx] <= cuts[lev]]
        if len(sub) < MIN_SEGS:
            continue
        for c in _components(S[sub], K[sub], mpt, t_end):
            todo.append((sub[c], lev + 1))


def _measure(S, C, L, idx, mpt):
    """Rotation-invariant measures of one component, plus its points in its own oriented frame."""
    from shapely.geometry import MultiPoint
    P = np.vstack([S[idx, :2], S[idx, 2:]])
    hull = MultiPoint([tuple(p) for p in P]).convex_hull
    if hull.geom_type != "Polygon" or hull.area <= 0:
        return None
    r = hull.minimum_rotated_rectangle
    c = np.asarray(r.exterior.coords)[:4]
    e1, e2 = c[1] - c[0], c[2] - c[1]
    l1, l2 = float(np.hypot(*e1)), float(np.hypot(*e2))
    if min(l1, l2) <= 0:
        return None
    u = e1 / l1 if l1 >= l2 else e2 / l2
    v = np.array([-u[1], u[0]])
    ctr = c.mean(axis=0)
    l, w = max(l1, l2) * mpt, min(l1, l2) * mpt
    if not (MIN_EXT_M <= l <= MAX_EXT_M) or w < 0.12:
        return None
    # sample points along every segment (every 4 cm) in the oriented frame, metres
    pts = []
    for k in idx:
        n = max(2, int(L[k] / 0.04) + 1)
        t = np.linspace(0, 1, n)[:, None]
        pts.append(S[k, :2] * (1 - t) + S[k, 2:] * t)
    Q = np.vstack(pts) - ctr
    Q = np.stack([Q @ u, Q @ v], axis=1) * mpt
    tot = float(L[idx].sum())
    ang = np.arctan2(S[idx, 3] - S[idx, 1], S[idx, 2] - S[idx, 0])
    rel = np.mod(ang - math.atan2(u[1], u[0]), math.pi)
    axis_share = float(L[idx][(np.minimum(rel, math.pi - rel) < 0.05) | (np.abs(rel - math.pi / 2) < 0.05)].sum() / tot)
    # share of the length along the one dominant direction (floor plank / tile hatch runs one way)
    a2 = np.mod(ang, math.pi)
    a0 = a2[np.argmax(L[idx])]
    dom = float(L[idx][np.abs(np.mod(a2 - a0 + math.pi / 2, math.pi) - math.pi / 2) < 0.03].sum() / tot)
    # corner-to-corner diagonals: an X in a box marks a column, shaft or void, never a bowl
    xd = int((L[idx] >= 0.85 * math.hypot(l, w)).sum())
    short = float((L[idx] < 0.06).mean())  # dot / stipple share: hatched columns and wall pieces, not furniture
    return {"idx": idx, "hull": hull, "dom": dom, "xdiag": xd, "short": short, "rect": c, "l": l, "w": w, "c": ctr, "u": u, "Q": Q, "tot": tot,
            "n": len(idx), "curved": float(L[idx][C[idx]].sum() / tot), "axis": axis_share}


def _same(a, b, tol):
    """Point-for-point match of two components in their oriented frames, trying the four flips."""
    from scipy.spatial import cKDTree
    tb = cKDTree(b["Q"])
    best = math.inf
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        q = a["Q"] * (sx, sy)
        d1 = tb.query(q)[0]
        d2 = cKDTree(q).query(b["Q"])[0]
        best = min(best, max(float(np.mean(d1)), float(np.mean(d2))))
        if best <= tol:
            return True
    return False


def _groups(comps, t_end):
    """Symbols: components with matching signatures and geometry; [[comp idx, ...], ...] with 2+ members."""
    order = sorted(range(len(comps)), key=lambda k: comps[k]["tot"])
    groups = []  # [exemplar, members]
    for k in order:
        a = comps[k]
        placed = False
        for g in groups[::-1][:60]:
            e = comps[g[0]]
            if a["tot"] > e["tot"] * 1.06 + 0.05:
                break
            if abs(a["l"] - e["l"]) > 0.04 * e["l"] + 0.02 or abs(a["w"] - e["w"]) > 0.04 * e["w"] + 0.02:
                continue
            if abs(a["curved"] - e["curved"]) > 0.12 or abs(a["tot"] - e["tot"]) > 0.06 * e["tot"] + 0.05:
                continue
            if _same(a, e, 0.012 + 0.01 * e["l"]):
                g.append(k)
                placed = True
                break
        if not placed:
            groups.append([k])
        if time.time() > t_end:
            break
    return [g for g in groups if len(g) >= 2]


# ---------------------------------------------------------------- classification

def _room_label(rooms, pt):
    from shapely.geometry import Point
    p = Point(pt)
    best = None
    for g, lab in rooms:
        if g.contains(p) and (best is None or g.area < best[0]):
            best = (g.area, lab)
    return best[1] if best else ""


# a generic chair / table needs a room that holds furniture around it: repeated small squares elsewhere are column
# markers, roof drains, grid heads and fixings (no room, or a corridor / roof / plant room)
FURN_ROOM = re.compile("|".join(r.pattern for r in (KITCHEN, BED, LIVING, OFFICE)) +
                       r"|dining|dine|\bdin\b|\bess|ruokailu|matsal|lunch|canteen", re.I)
LOCKER = re.compile(r"locker|kaapi|kaappi|skåp|spind|garderob", re.I)
ROOM_WORD = re.compile("|".join(r.pattern for r in (BATH, KITCHEN, BED, LIVING, DINING)), re.I)


def _room_word(words, c, mpt, reach_m=3.5):
    """The nearest printed room name within reach (rooms without a polygon still print their name)."""
    best = None
    r = reach_m / mpt
    for wd in words:
        b = wd["bbox"]
        d = math.hypot((b[0] + b[2]) / 2 - c[0], (b[1] + b[3]) / 2 - c[1])
        if d <= r and (best is None or d < best[0]) and ROOM_WORD.search(wd["text"]):
            best = (d, wd["text"])
    return best[1] if best else ""


def _near_words(words, c, mpt, reach_m=1.0, wc=None):
    r = reach_m / mpt
    if wc is not None and len(wc) == len(words):  # vectorised: word centres precomputed
        hit = np.flatnonzero((np.abs(wc[:, 0] - c[0]) <= r) & (np.abs(wc[:, 1] - c[1]) <= r))
        return " ".join(words[j]["text"] for j in hit)
    out = []
    for wd in words:
        b = wd["bbox"]
        if abs((b[0] + b[2]) / 2 - c[0]) <= r and abs((b[1] + b[3]) / 2 - c[1]) <= r:
            out.append(wd["text"])
    return " ".join(out)


def classify(m, room="", near=""):
    """(kind, type, conf, why) from real size, curved share and the room label; None when unsure."""
    l, w = m["l"], m["w"]
    cu = max(m["curved"], 1.0 - m["axis"])  # CAD plots often flatten bowls into short polyline chords
    asp = l / w
    rb = bool(BATH.search(room))
    rk = bool(KITCHEN.search(room))
    lab = room + " " + near
    if room and NOT_FURN.search(room) and not (rb or rk):
        return None
    if m.get("locker") and 0.8 <= l <= MAX_EXT_M and 0.3 <= w <= 1.2 and m["axis"] >= 0.6:
        return "furniture", "locker", 0.6, "bank size next to a printed LOCKERS label"
    if m.get("xdiag", 0) >= 2 and m["curved"] < 0.05 and m["n"] <= 8:
        return None  # boxed X: column / shaft / void marker
    bowl = m["curved"] >= 0.1 or m["n"] >= 8  # a few straight diagonals (stove, bench end) are no flattened bowl
    if cu >= 0.25 and bowl:
        if 0.55 <= l <= 0.85 and 0.33 <= w <= 0.62 and asp >= 1.2 and (rb or not room):
            return "wc", None, 0.7 if rb else 0.55, "oval bowl + cistern size"
        if 0.33 <= l <= 0.75 and 0.28 <= w <= 0.62 and asp < 1.6 and (rb or rk):
            return ("sink" if rk and not rb else "basin"), None, 0.65, "round bowl size"
        if 1.4 <= l <= 2.0 and 0.65 <= w <= 1.0 and rb:
            return "bath", None, 0.7, "tub size in a bath room"
    if rb:
        if 1.4 <= l <= 2.0 and 0.65 <= w <= 1.0:
            return "bath", None, 0.6, "tub size in a bath room"
        if 0.75 <= l <= 1.25 and asp <= 1.4:
            return "shower", None, 0.55, "tray size in a bath room"
        if not rk:  # a merged "kitchen / bath" room label leaves the furniture rules open
            return None
    if rk and 0.6 <= l <= 1.1 and 0.4 <= w <= 0.65 and m["axis"] < 0.95:
        return "sink", None, 0.55, "double bowl size in a kitchen"
    bed_room = bool(BED.search(lab))
    if 1.85 <= l <= 2.3 and 0.85 <= w <= 2.1 and (bed_room or not room) and not rk:
        return "furniture", "bed", 0.65 if bed_room else 0.5, "bed size"
    if bed_room and 1.85 <= l <= MAX_EXT_M and 1.4 <= w <= 2.8:
        return "furniture", "bed", 0.6, "bed + bedside tables size in a bedroom"
    liv = bool(LIVING.search(lab))
    if 1.4 <= l <= 2.6 and 0.7 <= w <= 1.05 and liv:
        return "furniture", "sofa", 0.6, "sofa size in a living room"
    if liv and 0.6 <= w and l <= 1.3 and asp <= 1.5:
        return "furniture", "chair", 0.55, "armchair size in a living room"
    furn_room = bool(FURN_ROOM.search(lab))
    stipple = m["n"] >= 10 and m.get("short", 0) >= 0.5  # dotted square: a column in section, not a chair
    if 0.38 <= l <= 0.7 and 0.38 <= w <= 0.7 and furn_room and not stipple:
        return "furniture", "chair", 0.5, "chair / stool size"
    if 1.0 <= l <= 2.0 and 0.5 <= w <= 0.9 and OFFICE.search(lab):
        return "furniture", "desk", 0.55, "desk size in an office"
    if 0.7 <= l <= 2.6 and 0.6 <= w <= 1.4 and m["axis"] >= 0.6 and not rk and furn_room:
        return "furniture", "table", 0.5, "table size"
    if 0.8 <= l <= 2.6 and 0.5 <= w <= 0.7 and bed_room:
        return "furniture", "wardrobe", 0.45, "wardrobe size in a bedroom"
    return None


def _find(page, mpt, wall_u, footprint, doors, rooms, words, budget_s):
    if not mpt or not page or not page.get("paths"):
        return []
    seg = _segments(page, mpt, wall_u, footprint)
    # the clock starts after _segments: its pdf_layers pass is cached on the page and shared with pdf_vector
    t_end = time.time() + budget_s
    if seg is None or not len(seg[0]):
        return []
    S, C, I, L, K = seg
    comps = []
    for idx in _split(S, K, L, mpt, t_end):
        m = _measure(S, C, L, idx, mpt)
        if m is not None:
            p0 = page["paths"][int(I[idx[0]])]
            m["pen"] = [p0.get("stroke"), p0.get("width")]
            comps.append(m)
        if time.time() > t_end:
            return []
    if words is None:
        words = [w for w in page.get("words") or [] if w.get("bbox") and w.get("text")]
    import shapely
    wc = np.array([[(w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2] for w in words]).reshape(-1, 2)
    keep = []
    for m in comps:
        h = m["hull"]
        if doors is not None and doors.intersection(h).area > 0.3 * h.area:
            continue  # door leaf + swing
        if len(wc):
            hit = np.flatnonzero(shapely.contains_xy(h, wc[:, 0], wc[:, 1]))
            if len(hit):  # tags, callouts, legend boxes are mostly text; a room label may sit on a bed
                ta = sum((words[j]["bbox"][2] - words[j]["bbox"][0]) * (words[j]["bbox"][3] - words[j]["bbox"][1]) for j in hit)
                if ta > 0.08 * h.area or m["l"] < 1.0:
                    continue
        # hatch / tiling: many equal parallel lines
        if m["n"] >= 8 and m["axis"] > 0.97 and m["curved"] == 0 and _parallel_hatch(S[m["idx"]]):
            continue
        keep.append(m)
    groups = _groups(keep, t_end)
    grouped = {k for g in groups for k in g}
    # a symbol drawn once still counts when its room names it (bed in a bedroom, WC in a bath room)
    groups += [[k] for k in range(len(keep)) if k not in grouped]
    out = []
    grid = None
    on_wall = {}
    for gi, g in enumerate(groups):
        res = []
        for k in g:
            m = keep[k]
            room = (_room_label(rooms, m["c"]) if rooms else "") or _room_word(words, m["c"], mpt)
            near = _near_words(words, m["c"], mpt, wc=wc)
            m["locker"] = bool(LOCKER.search(_near_words(words, m["c"], mpt, 2.5, wc=wc)))
            res.append((k, room, classify(m, room, near)))
        # one CAD block is one thing: a "chair" whose copies mostly sit outside furniture rooms (roofs, grid, plant)
        # is a column / drain / fixing marker
        n_chair = sum(1 for _, _, r in res if r and r[1] == "chair")
        for k, room, r in res:
            m = keep[k]
            if r is None:
                continue
            kind, typ, conf, why = r
            if typ == "chair" and len(g) >= 3 and n_chair < 0.5 * len(g):
                continue
            if typ == "chair" and wall_u is not None:
                if gi not in on_wall:  # share of this symbol's copies that sit on a wall line
                    on_wall[gi] = float(np.mean([wall_u.distance(keep[j]["hull"]) * mpt < 0.1 for j in g]))
                if on_wall[gi] >= 0.5 or wall_u.distance(m["hull"]) * mpt < 0.1:
                    continue  # squares on wall lines are columns / pilasters (and so are their free copies)
            if typ == "chair":
                if grid is None:
                    grid = _grid_tree(page, mpt)
                if grid is not False and len(grid.query(shapely.points(*m["c"]), predicate="dwithin",
                                                        distance=0.06 / mpt)):
                    continue  # centred on a structural grid line: a column, not a chair
            if len(g) == 1:
                if not room or not _room_backs(kind, typ, room):
                    continue
                conf -= 0.1
            conf = min(0.75, conf + 0.02 * min(len(g) - 2, 5))
            poly = [[round(float(x), 3), round(float(y), 3)] for x, y in np.asarray(m["hull"].exterior.coords)[:-1]]
            props = {"size_m": [round(m["l"], 2), round(m["w"], 2)], "group": gi, "n_group": len(g),
                     "room": room or None, "source": "pdf_symbols",
                     "evidence": (f"symbol repeated {len(g)}x; " if len(g) > 1 else "single symbol; ") + why}
            if typ:
                props["type"] = typ
            out.append({"kind": kind, "polygon": poly, "conf": round(conf, 2), "props": props})
    return out


def _grid_tree(page, mpt, min_len_m=6.0):
    """STRtree of structural grid lines: the pdf_layers 'grid' layer, else long dashed (dash-dot) lines."""
    import shapely
    paths = page.get("paths") or []
    try:
        from pipeline import pdf_layers
        mask = pdf_layers.role_mask(page, "grid", min_conf=0.5)
    except Exception:  # noqa: BLE001
        mask = np.zeros(len(paths), bool)
    lines = []
    for i, p in enumerate(paths):
        q = p.get("pts") or ()
        if len(q) < 2:
            continue
        if (i < len(mask) and mask[i]) or p.get("dashed"):
            ln = shapely.linestrings(np.asarray(q, float)[:, :2])
            if ln.length * mpt >= min_len_m:
                lines.append(ln)
    return shapely.STRtree(lines) if lines else False


def _room_backs(kind, typ, room):
    if kind in ("wc", "basin", "bath", "shower"):
        return bool(BATH.search(room))
    if kind == "sink":
        return bool(KITCHEN.search(room))
    return {"bed": BED, "sofa": LIVING, "desk": OFFICE, "wardrobe": BED}.get(typ, re.compile("$^")).search(room) is not None


def _parallel_hatch(seg):
    d = seg[:, 2:] - seg[:, :2]
    ang = np.mod(np.arctan2(d[:, 1], d[:, 0]), math.pi)
    a0 = np.median(ang)
    same = np.abs(np.mod(ang - a0 + math.pi / 2, math.pi) - math.pi / 2) < 0.03
    return same.mean() > 0.8
