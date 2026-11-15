"""Drawing semantics for vector-PDF floor plans: what a CAD export would carry that plain geometry does not.

    plan_region(page, walls, rooms, opens, mpt) -> (shapely Polygon | None, stats)
        The floor-plan area: enclosed wall faces that hold room evidence (room numbers, ceiling-height marks, fire
        marks, door swings) plus a morphological closing of that evidence. Roof plans of neighbouring blocks (big
        outlines with ridge/valley lines and no room evidence), the legend, notes, key plan and title block fall
        outside. None when the page has too little evidence to decide (then nothing is cropped).
    analyse(page, walls, opens, rooms, mpt, region) -> dict
        storey name/elevation/height system from the title and level marks, door height from the notes, legend
        entries (code -> description, kind, material), per-wall type (glass partitions next to a GLASS mark),
        fire/acoustic ratings next to doors and walls, ceiling heights per room, wall height.
All geometry in page points (top-left origin, y down), as pdf_vector returns it. Pure functions, no I/O.
"""
from __future__ import annotations

import re
from collections import Counter

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

ROOM_NO = re.compile(r"^[A-Z]{1,3}\d{2,4}[a-z]?$|^\d{1,2}\.\d{2,3}$")
NOT_ROOM = re.compile(r"\b(roof|katto|vesikatto|canopy|skylight)\b", re.I)
CEIL = re.compile(r"^h=(\d{4})(?:mm)?;?$", re.I)
FIRE = re.compile(r"^(R?EI[WM]?|EW|E)\s?(\d{2,3})(?:-\w+)?$")
ACOUSTIC = re.compile(r"^(Rw\s?\d{2}|dB\d{2}(?:/\d{2})?)[,;]?$")
LEVEL = re.compile(r"^([+-]\d{1,3}[.,]\d{3})$")
HEIGHT_SYS = re.compile(r"^(N2000|N60|NN|NAP|NHN|DHHN\d*|ODN|NAVD88|NGVD29|RH2000|EVRF\d*)$", re.I)
CODE = re.compile(r"^[A-Z]{1,3}(?:-[A-Z0-9]{1,3})?$")
ORD_FLOOR = re.compile(r"\b(\d{1,2})\s*(?:ST|ND|RD|TH)\s+FLOOR\b|\bFLOOR\s+(\d{1,2})\b|\b(\d{1,2})\.\s*KERROS\b|"
                       r"\b(GROUND|FIRST|SECOND|THIRD|FOURTH|FIFTH|BASEMENT|ATTIC|ROOF)\s+(?:FLOOR|LEVEL|PLAN)\b", re.I)
WORD_FLOOR = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "basement": -1}
MATERIALS = [("glass", "Glass"), ("brick", "Brick"), ("concrete", "Concrete"), ("block", "Concrete block"),
             ("gypsum", "Gypsum board"), ("plaster", "Gypsum board"), ("board", "Board"), ("timber", "Timber"),
             ("wood", "Timber"), ("steel", "Steel"), ("stud", "Steel stud"), ("masonry", "Masonry")]

MIN_SEEDS = 8
CLOSE_M = 4.0           # evidence closer than 2x this is one plan region
PAD_M = 1.2             # region margin around the outermost evidence
FACE_MAX_SHARE = 0.6    # an enclosed face bigger than this share of the wall extent is the page frame, not a room
FACE_CORE_M = 0.6       # a face counts as a room only with evidence this far inside it (not on its edge)
FACE_IN_CLOSED = 0.6    # ... and with most of its area near the evidence
FILL_M = 2.5            # closing radius over the kept walls
NEAR_SEED_M = 3.0       # walls mostly this close to evidence always stay
HULL_FRAC = 0.9         # second round: share of a wall inside the hull of the kept walls
KEEP_FRAC = 0.5         # a wall stays if at least this share of its axis lies in the region


def _c(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _poly(p):
    try:
        g = Polygon(p)
        return g if g.is_valid else g.buffer(0)
    except Exception:  # noqa: BLE001
        return None


def _axis(w):
    cl = w.get("centerline")
    if cl and len(cl) >= 2:
        return LineString(cl)
    g = _poly(w.get("polygon") or [])
    if g is None or g.is_empty:
        return None
    r = g.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4] if r.geom_type == "Polygon" else []
    if len(c) < 4:
        return None
    e = [((c[i][0] + c[(i + 1) % 4][0]) / 2, (c[i][1] + c[(i + 1) % 4][1]) / 2) for i in range(4)]
    a, b = LineString([e[0], e[2]]), LineString([e[1], e[3]])
    return a if a.length >= b.length else b


def seeds(page: dict, rooms: list, opens: list, doors: bool = True) -> list:
    """Points (pt) that only occur inside a floor plan: door swings, room numbers, ceiling-height and fire marks."""
    pts = [_c(o["bbox"]) for o in opens if doors and o.get("kind") == "door" and o.get("bbox")]
    for w in page.get("words") or []:
        t = (w.get("text") or "").strip()
        if ROOM_NO.match(t) or CEIL.match(t) or FIRE.match(t):
            pts.append(_c(w["bbox"]))
    for r in rooms:  # labelled rooms (not roof areas: a roof plan names its roofs too)
        lab = r.get("label") or ""
        if (r.get("number") or lab) and r.get("label_bbox") and not NOT_ROOM.search(lab):
            pts.append(_c(r["label_bbox"]))
    return pts


def plan_region(page: dict, walls: list, rooms: list, opens: list, mpt: float):
    pts = seeds(page, rooms, opens)
    st = {"seeds": len(pts)}
    if len(pts) < MIN_SEEDS or not walls:
        st["skipped"] = "too little plan evidence"
        return None, st
    R, pad = CLOSE_M / mpt, PAD_M / mpt
    blobs = unary_union([Point(p).buffer(R, 8) for p in pts])
    blobs = list(getattr(blobs, "geoms", [blobs]))
    cnt = [sum(1 for p in pts if b.contains(Point(p))) for b in blobs]
    top = max(cnt)
    keep = [b for b, n in zip(blobs, cnt) if n >= max(3, 0.3 * top)]
    closed = unary_union(keep).buffer(-(R - pad))
    closed = unary_union([Polygon(g.exterior) for g in getattr(closed, "geoms", [closed]) if g.area > 0])
    # enclosed faces of the wall (+opening) layout that hold evidence: rooms reach their walls even when the
    # evidence sits in the middle of a big room
    gap = 0.15 / mpt
    wp = [g for g in (_poly(w["polygon"]) for w in walls if w.get("polygon")) if g is not None and not g.is_empty]
    op = [box(*o["bbox"]) for o in opens if o.get("bbox")]
    lay = unary_union([g.buffer(gap) for g in wp + op])
    ext = unary_union(wp).envelope.area or 1.0
    faces = []
    inner = [Point(p) for p in seeds(page, rooms, opens, doors=False)]  # doors sit in walls, on a face's edge
    for g in getattr(lay, "geoms", [lay]):
        for ring in getattr(g, "interiors", []):
            f = Polygon(ring)
            if f.area >= FACE_MAX_SHARE * ext or f.intersection(closed).area < FACE_IN_CLOSED * f.area:
                continue  # a face leaking into an unlabelled roof/yard through a wall gap is not a room
            core = f.buffer(-FACE_CORE_M / mpt)
            if not core.is_empty and any(core.contains(p) for p in inner):
                faces.append(f.buffer(gap))
    region = unary_union([closed] + faces)
    # walls: keep those mostly inside; the region then grows to cover them (exterior walls of the plan)
    near = unary_union([Point(p).buffer(NEAR_SEED_M / mpt, 8) for p in pts])
    kept, core = [], []
    for w in walls:
        ax = _axis(w)
        if ax is None or ax.length <= 0:
            continue
        t = float(w.get("thickness_pt") or 0)
        fr = ax.intersection(region.buffer(t / 2 + 0.3 / mpt)).length / ax.length
        if fr < KEEP_FRAC and ax.intersection(near).length >= KEEP_FRAC * ax.length:
            fr = KEEP_FRAC  # a wall right next to room evidence (sparsely labelled plans)
        if fr >= KEEP_FRAC:
            kept.append(w)
        if fr >= HULL_FRAC:
            core.append(w)
    if not kept:
        st["skipped"] = "no walls in the plan region"
        return None, st
    # second round: walls almost wholly inside the convex hull of the walls wholly in the region (a big room's far corner
    # whose label sat in its middle); roofs beside the plan only touch the hull and stay out
    kg = unary_union([_poly(w["polygon"]).buffer(1.5 / mpt) for w in core if _poly(w["polygon"])])
    hulls = unary_union([g.convex_hull for g in getattr(kg, "geoms", [kg])])
    kept_ids = {id(w) for w in kept}
    for w in walls:
        if id(w) in kept_ids:
            continue
        ax = _axis(w)
        if ax is not None and ax.length > 0 and ax.intersection(hulls).length >= HULL_FRAC * ax.length:
            kept.append(w)
            kept_ids.add(id(w))
    r2 = FILL_M / mpt  # close the plan between its kept walls (rooms whose evidence sat off-centre)
    region = unary_union([region] + [_poly(w["polygon"]).buffer(gap) for w in kept if _poly(w["polygon"])])
    region = region.buffer(r2, join_style="mitre").buffer(-r2, join_style="mitre")
    region = unary_union([Polygon(g.exterior) for g in getattr(region, "geoms", [region]) if g.area > 0])
    st.update(faces=len(faces), walls_in=len(kept), walls_out=len(walls) - len(kept), clusters=len(keep),
              keep_ids=[id(w) for w in kept])
    return region, st


# ---------------------------------------------------------------- text semantics

def lines(words: list, gap_h: float = 2.5) -> list:
    """Words -> text lines [(text, bbox, words)], left to right, for horizontal text."""
    ws = sorted((w for w in words if w.get("bbox") and (w.get("text") or "").strip()),
                key=lambda w: (round(_c(w["bbox"])[1]), w["bbox"][0]))
    out, used = [], set()
    for i, w in enumerate(ws):
        if i in used:
            continue
        h = max(w["bbox"][3] - w["bbox"][1], 0.5)
        cy = _c(w["bbox"])[1]
        row = [(j, v) for j, v in enumerate(ws) if j not in used and abs(_c(v["bbox"])[1] - cy) <= 0.45 * h
               and abs((v["bbox"][3] - v["bbox"][1]) - h) <= 0.6 * h]
        row.sort(key=lambda jv: jv[1]["bbox"][0])
        seg = []
        for j, v in row:
            if seg and v["bbox"][0] - seg[-1]["bbox"][2] > gap_h * h:
                break
            if not seg and v is not w:
                if v["bbox"][0] < w["bbox"][0]:
                    continue
            seg.append(v)
            used.add(j)
        if not seg:
            continue
        bb = [min(v["bbox"][0] for v in seg), min(v["bbox"][1] for v in seg),
              max(v["bbox"][2] for v in seg), max(v["bbox"][3] for v in seg)]
        out.append((" ".join(v["text"].strip() for v in seg), bb, seg))
    return out


def _material(desc: str):
    d = desc.lower()
    for k, m in MATERIALS:
        if k in d:
            return m
    return None


def legend(words: list) -> list:
    """Legend entries [{code, description, kind, material, bbox}] from a block headed LEGEND/SYMBOLS/KEY."""
    ls = lines(words, gap_h=6.0)
    heads = [bb for t, bb, _ in ls if re.match(r"^(LEGEND|SYMBOLS|KEY|SELITE|MERKINNÄT)\b", t.strip(), re.I)]
    out = []
    for hb in heads:
        h = max(hb[3] - hb[1], 1.0)
        for t, bb, seg in ls:
            if not (hb[1] < bb[1] <= hb[3] + 40 * h and abs(bb[0] - hb[0]) <= 4 * h):
                continue
            code = seg[0]["text"].strip()
            desc = " ".join(v["text"].strip() for v in seg[1:])
            if not CODE.match(code) or len(desc) < 3:
                continue
            d = desc.lower()
            kind = "glass_partition" if "glass" in d and ("partition" in d or "wall" in d) else \
                "wall" if ("wall" in d or "partition" in d) else "symbol"
            out.append({"code": code, "description": desc, "kind": kind, "material": _material(desc), "bbox": bb})
    return out


def storey(words: list, region=None) -> dict:
    """Storey name/number from the title text, elevation from level marks (+13.000) in the plan, height system."""
    out, cands = {}, []
    for t, bb, _ in lines(words):
        m = ORD_FLOOR.search(t)
        if m:  # the biggest lettering wins (sheet title over unit-type captions and key-plan notes)
            g = [x for x in m.groups() if x]
            num = int(g[0]) if g[0].isdigit() else WORD_FLOOR.get(g[0].lower())
            cands.append((bb[3] - bb[1], "plan" in t.lower(), m.group(0).upper().strip(), num))
        if "height_system" not in out:
            for tok in t.split():
                if HEIGHT_SYS.match(tok):
                    out["height_system"] = tok.upper()
    if cands:
        _, _, out["name"], num = max(cands, key=lambda c: (round(c[0], 0), c[1]))
        if num is not None:
            out["number"] = num
    lv = []
    for w in words:
        m = LEVEL.match((w.get("text") or "").strip())
        if m and (region is None or region.contains(Point(_c(w["bbox"])))):
            lv.append(float(m.group(1).replace(",", ".")))
    if lv:
        val, n = Counter(lv).most_common(1)[0]
        if n >= 2 or len(lv) == 1:
            out["elevation_m"] = val
            out["elevation_source"] = f"level mark {val:+.3f} ({n} of {len(lv)} marks in the plan)"
    return out


def door_height(words: list):
    """Door height in m from a note such as 'DOOR HEIGHT h=2100'."""
    for t, _, _ in lines(words):
        if re.search(r"DOOR\s+HEIGHT|OVIKORKEUS|DOOR\s+HEAD", t, re.I):
            m = re.search(r"h\s*=\s*(\d{4})|(\d{4})\s*mm", t, re.I)
            if m:
                v = int(m.group(1) or m.group(2)) / 1000
                if 1.8 <= v <= 3.0:
                    return v
    return None


def _nearest(pt, cands, maxd):
    best, bd = None, maxd
    for i, g in cands:
        d = g.distance(Point(pt))
        if d <= bd:
            best, bd = i, d
    return best


def analyse(page: dict, walls: list, opens: list, rooms: list, mpt: float, region=None) -> dict:
    words = page.get("words") or []
    inr = (lambda b: True) if region is None else (lambda b: region.contains(Point(_c(b))))
    sem = {"storey": storey(words, region), "door_height_m": door_height(words), "legend": legend(words)}
    wg = [(i, g) for i, g in ((i, _poly(w.get("polygon") or [])) for i, w in enumerate(walls)) if g is not None]
    dg = [(i, box(*o["bbox"])) for i, o in enumerate(opens) if o.get("kind") == "door" and o.get("bbox")]
    wall_tags, door_tags = {}, {}
    glass_types = [e for e in sem["legend"] if e["kind"] == "glass_partition"]
    for w in words:
        t = (w.get("text") or "").strip()
        b = w.get("bbox")
        if not b or not inr(b):
            continue
        c = _c(b)
        if FIRE.match(t):
            k = _nearest(c, dg, 1.5 / mpt)
            if k is not None:
                door_tags.setdefault(k, {})["fire_rating"] = t
            else:
                k = _nearest(c, wg, 0.6 / mpt)
                if k is not None:
                    wall_tags.setdefault(k, {})["fire_rating"] = t
        elif ACOUSTIC.match(t):
            t = t.rstrip(",;")
            k = _nearest(c, dg, 1.5 / mpt)
            if k is not None and t.lower().startswith("db"):
                door_tags.setdefault(k, {})["acoustic_rating"] = t
            else:
                k = _nearest(c, wg, 0.8 / mpt)
                if k is not None:
                    wall_tags.setdefault(k, {})["acoustic_rating"] = t
        elif t.upper().startswith("GLASS"):
            thin = [(i, g) for i, g in wg if float(walls[i].get("thickness_pt") or 99) * mpt <= 0.16]
            k = _nearest(c, thin, 1.0 / mpt)
            if k is not None:
                tag = wall_tags.setdefault(k, {})
                tag["glass"] = True
                if glass_types:
                    tag["wall_type"] = glass_types[0]["code"]
                    tag["type_description"] = glass_types[0]["description"]
    # glass spreads along collinear thin pieces touching a tagged one (one partition drawn in segments)
    for i in [i for i, t in wall_tags.items() if t.get("glass")]:
        gi = dict(wg).get(i)
        for j, g in wg:
            if j not in wall_tags and gi is not None and g.distance(gi) < 0.05 / mpt and \
                    abs(float(walls[j].get("thickness_pt") or 0) - float(walls[i].get("thickness_pt") or 0)) * mpt < 0.02:
                wall_tags[j] = {k: v for k, v in wall_tags[i].items() if k in ("glass", "wall_type", "type_description")}
    # ceiling heights per room (h=NNNN marks inside the room polygon)
    room_h = {}
    ch = [(int(CEIL.match(w["text"].strip()).group(1)) / 1000, Point(_c(w["bbox"]))) for w in words
          if CEIL.match((w.get("text") or "").strip()) and w.get("bbox") and inr(w["bbox"])]
    near_door = unary_union([g.buffer(1.0 / mpt) for _, g in dg]) if dg else None
    ch = [(v, p) for v, p in ch if 2.0 <= v <= 6.0 and (near_door is None or not near_door.contains(p))]
    for i, r in enumerate(rooms):
        g = _poly(r.get("polygon") or []) if r.get("polygon") else None
        if g is None:
            continue
        vs = [v for v, p in ch if g.contains(p)]
        if vs:
            room_h[i] = max(vs)
    ceil_all = [v for v, _ in ch]
    wall_h = None
    if ceil_all:
        wall_h = round(min(max(3.0, max(ceil_all) + 0.3), 4.5), 2)  # walls run to the slab above the highest ceiling
    sem.update(wall_tags=wall_tags, door_tags=door_tags, room_ceiling_m=room_h, ceiling_heights_m=sorted(set(ceil_all)),
               wall_height_m=wall_h)
    return sem
