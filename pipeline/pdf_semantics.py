"""Drawing semantics for vector-PDF floor plans: what a CAD export would carry that plain geometry does not.

    plan_region(page, walls, rooms, opens, mpt) -> (shapely Polygon | None, stats)
        (walls may gain clipped copies of exterior walls, see envelope(); stats keep_ids lists the walls to keep)
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
import time
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


def _buf(geoms: list, d: float, quad_segs: int = 16) -> list:
    """[g.buffer(d, quad_segs) for g in geoms] in one vectorised shapely call (same GEOS op, same result)."""
    if not geoms:
        return []
    import numpy as np
    import shapely
    return list(shapely.buffer(np.array(geoms, dtype=object), d, quad_segs=quad_segs))


def plan_region(page: dict, walls: list, rooms: list, opens: list, mpt: float):
    pts = seeds(page, rooms, opens)
    st = {"seeds": len(pts)}
    if len(pts) < MIN_SEEDS or not walls:
        st["skipped"] = "too little plan evidence"
        return None, st
    R, pad = CLOSE_M / mpt, PAD_M / mpt
    blobs = unary_union(_buf([Point(p) for p in pts], R, 8))
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
    lay = unary_union(_buf(wp + op, gap))
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
    # labelled rooms (pdf_rooms polygons): a room whose label sits in the evidence region is plan, wall face to
    # wall face, however sparse its labels (big rooms labelled once, off-centre)
    lab = labelled_rooms(rooms, closed, FACE_MAX_SHARE * ext, mpt)
    region = unary_union([closed] + faces + [g.buffer(gap) for g in lab])
    # walls: keep those mostly inside; the region then grows to cover them (exterior walls of the plan)
    near = unary_union(_buf([Point(p) for p in pts], NEAR_SEED_M / mpt, 8))
    kept, core = [], []
    grown = {}  # region grown by half a wall thickness: one buffer per distinct thickness, not per wall
    for w in walls:
        ax = _axis(w)
        if ax is None or ax.length <= 0:
            continue
        t = float(w.get("thickness_pt") or 0)
        if t not in grown:
            grown[t] = region.buffer(t / 2 + 0.3 / mpt)
        fr = ax.intersection(grown[t]).length / ax.length
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
    kg = unary_union(_buf([g for g in (_poly(w["polygon"]) for w in core) if g], 1.5 / mpt))
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
    kp = [g for g in (_poly(w["polygon"]) for w in kept) if g is not None and not g.is_empty]
    kp_gap = _buf(kp, gap)
    region = unary_union([region] + kp_gap)
    try:  # unlabelled rooms (pdf_rooms faces) inside the hull of the kept walls are plan too, not clipped away
        kh = unary_union([g.convex_hull for g in getattr(unary_union(kp_gap), "geoms", [])] or
                         [unary_union(kp).convex_hull])
        for r in rooms:
            g = _poly(r.get("polygon") or []) if r.get("polygon") else None
            if g is None or g.is_empty or g.area >= FACE_MAX_SHARE * ext or NOT_ROOM.search(r.get("label") or ""):
                continue
            if g.intersection(kh).area >= HULL_FRAC * g.area:
                region = region.union(g.buffer(gap))
    except Exception:  # noqa: BLE001
        pass
    region = region.buffer(r2, join_style="mitre").buffer(-r2, join_style="mitre")
    region = unary_union([Polygon(g.exterior) for g in getattr(region, "geoms", [region]) if g.area > 0])
    try:  # safety valve: a crop that loses labelled room area or the walls bounding those rooms is wrong
        lost = crop_loss(walls, kept, lab, region, mpt)
        st.update(lost)
        if lost["room_area_lost"] > VALVE_LOSS or lost["room_wall_lost"] > VALVE_LOSS:
            st["skipped"] = f"crop would drop {lost['room_area_lost']:.0%} of labelled room area, " \
                            f"{lost['room_wall_lost']:.0%} of their walls"
            return None, st
    except Exception as e:  # noqa: BLE001
        st["valve_error"] = f"{type(e).__name__}: {e}"[:120]
    ost, t_out = {}, time.monotonic()
    try:  # the building's own outline (outline pen): crop to it, clip walls reaching past it, close its facades
        fp, pen, ost = building_outline(page, region, walls, kept, opens, rooms, mpt) if OUTLINE_ON else (None, None, {})
        if fp is not None:
            kept2 = crop_to_outline(walls, kept, fp, mpt)
            add = close_outline(fp, pen, kept2, opens, mpt)
            if time.monotonic() - t_out > 2 * OUT_TIME_S:  # crop + close are bounded; only a stalled machine
                fp = None
                ost["outline"] = "time cap"
        if fp is not None:
            region2 = fp.buffer(0.3 / mpt, join_style="mitre")
            lost = crop_loss(walls, kept2, lab, region2, mpt)["room_area_lost"]
            if lost > VALVE_LOSS:
                ost["outline"] = f"outline would drop {lost:.0%} of labelled room area"
            else:
                for w in kept2 + add:
                    if not any(w is v for v in walls):
                        walls.append(w)
                kept, region = kept2 + add, region2
                ost.update(outline_walls_added=len(add), outline_clipped=sum(1 for w in kept2 if w.get("clipped_to_plan")))
    except Exception as e:  # noqa: BLE001  never worse than the evidence crop
        ost["outline_error"] = f"{type(e).__name__}: {e}"[:120]
    st.update(ost)
    readmit = []
    try:  # third round: the envelope (exterior walls at the plan's edge, away from the room evidence)
        readmit = envelope(walls, kept, region, mpt)
    except Exception as e:  # noqa: BLE001  never worse than the crop alone
        st["envelope_error"] = f"{type(e).__name__}: {e}"[:120]
    for w in readmit:
        if not any(w is v for v in walls):
            walls.append(w)  # a clipped piece: the caller filters its own list by keep_ids
        kept.append(w)
    st.update(faces=len(faces), walls_in=len(kept), walls_out=len(walls) - len(kept), clusters=len(keep),
              envelope_readmitted=len(readmit), keep_ids=[id(w) for w in kept])
    return region, st


ROOM_LEAK = 1.5      # a room polygon this much bigger than its printed area leaked through a wall gap (roof, yard)
VALVE_LOSS = 0.3     # skip the crop when it would drop more than this share of labelled room area / their walls
ROOM_WALL_M = 0.3    # walls this close to a labelled room bound it


def labelled_rooms(rooms: list, evidence, max_area: float, mpt: float) -> list:
    """Polygons of labelled rooms (not roof areas) whose label lies in the evidence region; leaked rooms (polygon
    > ROOM_LEAK x printed area, or bigger than max_area) are left out."""
    out = []
    for r in rooms:
        lab, lb = r.get("label") or "", r.get("label_bbox")
        if not (r.get("number") or lab) or not lb or NOT_ROOM.search(lab) or not r.get("polygon"):
            continue
        if not evidence.buffer(PAD_M / mpt).contains(Point(_c(lb))):
            continue
        g = _poly(r["polygon"])
        if g is None or g.is_empty or g.area >= max_area:
            continue
        pr = r.get("area_printed_m2")
        if pr and g.area * mpt * mpt > ROOM_LEAK * float(pr):
            continue
        out.append(g)
    return out


def crop_loss(walls: list, kept: list, lab: list, region, mpt: float) -> dict:
    """Share of labelled room area outside the region, and of the length of walls bounding those rooms not kept."""
    if not lab:
        return {"room_area_lost": 0.0, "room_wall_lost": 0.0}
    rp = unary_union(lab)
    a_lost = rp.difference(region).area / rp.area if rp.area > 0 else 0.0
    kept_ids = {id(w) for w in kept}
    tot = lost = 0.0
    for w in walls:
        g = _poly(w.get("polygon") or [])
        ax = _axis(w)
        if g is None or ax is None or g.distance(rp) > ROOM_WALL_M / mpt:
            continue
        tot += ax.length
        if id(w) not in kept_ids:
            lost += ax.length
    return {"room_area_lost": round(a_lost, 3), "room_wall_lost": round(lost / tot, 3) if tot else 0.0}


ENV_SIDE_M = 1.0     # a re-admitted piece has the plan on one side only: this far past its face, on the other
ENV_OUT_FRAC = 0.3   # side, at most this share of its length lies in the plan
ENV_MIN_M = 1.5      # ... and is at least this long inside the plan
ENV_CLIP_FRAC = 0.9  # pieces with this share of their axis inside are taken whole, others are clipped to the plan
ENV_JOIN_M = 0.3     # ... and both its ends are this close to kept walls (corners / the walls it closes between)
ENV_GAP_M = 4.0      # inside pieces of one axis this close together are one run


def _rect(a, b, t):
    import math
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    nx, ny = -(b[1] - a[1]) / L * t / 2, (b[0] - a[0]) / L * t / 2
    return [[round(a[0] + nx, 3), round(a[1] + ny, 3)], [round(b[0] + nx, 3), round(b[1] + ny, 3)],
            [round(b[0] - nx, 3), round(b[1] - ny, 3)], [round(a[0] - nx, 3), round(a[1] - ny, 3)]]


def envelope(walls: list, kept: list, region, mpt: float) -> list:
    """Dropped walls that form the plan's outline, after the crop: the part of the axis inside the plan (pieces
    merged across dents < ENV_GAP_M) is >= ENV_MIN_M long, has the plan on one side only (the other side, ENV_SIDE_M
    past its face, is outside) and is joined to kept walls at BOTH ends (corners, or the walls it closes between).
    A wall drawn as one segment through the plan's exterior wall and on along a roof's edge comes back clipped to
    the plan; roof outlines beside the plan touch it at one end only and stay out; interior walls the crop dropped
    have plan on both sides and stay out. Returns wall dicts: the original when >= ENV_CLIP_FRAC of it lies inside,
    otherwise a clipped copy (same keys, new polygon/centerline, clipped_to_plan=True)."""
    if region is None or region.is_empty:
        return []
    kept_ids = {id(w) for w in kept}
    out, kg = [], None
    grown = {}  # one region buffer per distinct wall thickness
    for w in walls:
        if id(w) in kept_ids:
            continue
        ax = _axis(w)
        if ax is None or ax.length <= 0:
            continue
        t = float(w.get("thickness_pt") or 0)
        if t not in grown:
            grown[t] = region.buffer(t / 2 + 0.3 / mpt)
        inside = ax.intersection(grown[t])
        parts = [g for g in getattr(inside, "geoms", [inside]) if g.geom_type == "LineString" and g.length > 0]
        if not parts:
            continue
        # pieces inside, merged across short gaps (a dent in the region where a room's evidence was missing)
        pos = sorted((ax.project(Point(g.coords[0])), ax.project(Point(g.coords[-1]))) for g in parts)
        runs = []
        for s0, s1 in ((min(p), max(p)) for p in pos):
            if runs and s0 - runs[-1][1] <= ENV_GAP_M / mpt:
                runs[-1][1] = max(runs[-1][1], s1)
            else:
                runs.append([s0, s1])
        s0, s1 = max(runs, key=lambda r: r[1] - r[0])
        seg = LineString([ax.interpolate(s0), ax.interpolate(s1)])
        if seg.length * mpt < ENV_MIN_M:
            continue
        d = t / 2 + ENV_SIDE_M / mpt
        sides = [seg.parallel_offset(d, side) for side in ("left", "right")]
        sides = [g.intersection(region).length / g.length if g.length > 0 else 1.0 for g in sides]
        if min(sides) > ENV_OUT_FRAC:
            continue  # plan on both sides: an interior wall the crop dropped on purpose
        if kg is None:
            kg = unary_union([g for g in (_poly(v.get("polygon") or []) for v in kept) if g is not None])
        reach = t / 2 + (ENV_JOIN_M + 0.3) / mpt  # the clip itself reaches 0.3 m past the region
        a, b = Point(seg.coords[0]), Point(seg.coords[-1])
        if a.distance(kg) > reach or b.distance(kg) > reach:
            continue  # a ring piece is joined to the kept walls at both ends; a roof edge only touches at one
        if seg.length >= ENV_CLIP_FRAC * ax.length:
            out.append(w)
            continue
        a, b = list(seg.coords)[0], list(seg.coords)[-1]
        c = {k: v for k, v in w.items() if k not in ("polygon", "centerline")}
        c.update(polygon=_rect(a, b, t), centerline=[[round(a[0], 3), round(a[1], 3)], [round(b[0], 3), round(b[1], 3)]],
                 clipped_to_plan=True)
        out.append(c)
    return out


# ---------------------------------------------------------------- text semantics

_LINES_CACHE: list = []  # [(words list, n words, gap_h, result)]: analyse() reads the same words 3 times


def lines(words: list, gap_h: float = 2.5) -> list:
    """Words -> text lines [(text, bbox, words)], left to right, for horizontal text.
    Row candidates come from a binary search over the word centres (same result as the all-pairs scan, n log n)."""
    for wl, n, g, res in _LINES_CACHE:
        if wl is words and n == len(words) and g == gap_h:
            return res
    res = _lines(words, gap_h)
    _LINES_CACHE[:] = ([(words, len(words), gap_h, res)] + _LINES_CACHE)[:3]
    return res


def _lines(words: list, gap_h: float) -> list:
    import bisect
    ws = sorted((w for w in words if w.get("bbox") and (w.get("text") or "").strip()),
                key=lambda w: (round(_c(w["bbox"])[1]), w["bbox"][0]))
    cys = [_c(w["bbox"])[1] for w in ws]
    order = sorted(range(len(ws)), key=cys.__getitem__)
    scy = [cys[j] for j in order]
    out, used = [], set()
    for i, w in enumerate(ws):
        if i in used:
            continue
        h = max(w["bbox"][3] - w["bbox"][1], 0.5)
        cy = cys[i]
        lo = bisect.bisect_left(scy, cy - 0.45 * h - 1e-6)
        hi = bisect.bisect_right(scy, cy + 0.45 * h + 1e-6)
        row = [(j, ws[j]) for j in sorted(order[lo:hi]) if j not in used and abs(cys[j] - cy) <= 0.45 * h
               and abs((ws[j]["bbox"][3] - ws[j]["bbox"][1]) - h) <= 0.6 * h]
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
    """Storey name/number from the title text, elevation from level marks (e.g. +9.000) in the plan, height system."""
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


# ---------------------------------------------------------------- building outline (outline pen)

OUTLINE_ON = True     # the outline-pen crop
OUT_TIME_S = 4.0      # the outline pass gives up (old region kept) past this many seconds (~1 s idle, ~3 s at
                      # load 22; the ingest budget leaves plan_region >= 6 s: PLAN_REGION/OPENINGS_RESERVE_S)
OUT_PATHS_PER_M = 20  # pens with more paths per metre of the region's edge are linework, not the outline
OUT_INK_PER_EDGE = 6  # ... or with more ink than this many times the edge length
OUT_OPEN_M = 0.6      # strips narrower than twice this (walls running on past the outline) are not footprint
OUT_DIR_SHARE = 0.1   # a wall direction with this share of the wall length is a facade direction
OUT_BAND_M = 2.5      # a pen traces the plan's outline when most of its in-plan ink lies this close to the region edge
OUT_COV = 0.5         # ... and it covers at least this share of the region's boundary
OUT_SHARE = 0.6       # ... with at least this share of its in-plan length in that band
OUT_CLOSE_M = 1.0     # closing radius over the outline pen + kept walls + openings (window gaps < 2 m)
OUT_MIN_AREA = 0.5    # the closed outline must hold this share of the evidence region
OUT_LABELS = 0.9      # ... and this share of the room labels inside the region
OUT_PEN_M = 0.6       # synthesized facade pieces lie this close to the outline pen's strokes
OUT_MIN_PIECE_M = 0.8
OUT_SKIP_ROLES = ("text", "background", "dimension", "grid", "hatch", "mask", "titleblock", "wall_fill")


def _pens_near(page, bounds, max_paths: int):
    """{pen signature: [segments x0, y0, x1, y1]} of the solid stroked paths starting inside bounds, for pens with at
    most max_paths such paths there (an outline pen is sparse; hatch, text and linework pens are not). A pen
    signature is the stroke colour + line width: CAD plots draw each layer with its own pen."""
    x0, y0, x1, y1 = bounds
    groups: dict = {}
    for p in page.get("paths") or []:
        st, pts = p.get("stroke"), p.get("pts")
        if st is None or not pts or len(pts) < 2 or p.get("dashed") or p.get("pattern"):
            continue
        x, y = pts[0]
        if x0 <= x <= x1 and y0 <= y <= y1:
            groups.setdefault((tuple(st), p.get("width")), []).append(p)
    out = {}
    for k, ps in groups.items():
        if not 4 <= len(ps) <= max_paths:
            continue
        seg = []
        for p in ps:
            q = p["pts"]
            q = list(q) + [q[0]] if p.get("closed") else q
            seg.extend((a[0], a[1], b[0], b[1]) for a, b in zip(q[:-1], q[1:]))
        out[k] = seg
    return out


def outline_pen(page: dict, region, mpt: float):
    """The pen that draws the plan's outer outline: most of its ink inside the plan lies along the evidence region's
    edge and it covers most of that edge (CAD plots draw the cut exterior wall with its own heavier pen).
    Returns (array of its segment LineStrings in the plan + margin, stats) or (None, stats)."""
    import numpy as np
    import shapely
    reg = region.simplify(0.2 / mpt)
    zone = reg.buffer(OUT_BAND_M / mpt, quad_segs=2)
    inner = reg.buffer(-OUT_BAND_M / mpt, quad_segs=2)
    shapely.prepare(zone)
    shapely.prepare(inner)
    edge = reg.boundary
    samples = shapely.line_interpolate_point(edge, np.arange(0, edge.length, 0.5 / mpt) if edge.length > 0 else [0.0])
    best, bst = None, {}
    for k, segs in _pens_near(page, zone.bounds, int(OUT_PATHS_PER_M * edge.length * mpt) + 50).items():
        if len(segs) < 4:
            continue
        S = np.asarray(segs, float)
        mx, my = (S[:, 0] + S[:, 2]) / 2, (S[:, 1] + S[:, 3]) / 2
        ln = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
        inz = shapely.contains_xy(zone, mx, my) & (ln > 0)
        lin = float(ln[inz].sum())
        if lin * mpt < 10 or lin > OUT_INK_PER_EDGE * edge.length:
            continue  # too little ink, or far more than an outline (double line + returns) along the edge
        deep = shapely.contains_xy(inner, mx[inz], my[inz]) if not inner.is_empty else np.zeros(int(inz.sum()), bool)
        share = float(ln[inz][~deep].sum()) / lin  # in-plan ink near the region's edge
        if share < OUT_SHARE:
            continue
        lines = shapely.linestrings(S[inz].reshape(-1, 2, 2))
        tree = shapely.STRtree(lines)
        hit = np.unique(tree.query(samples, predicate="dwithin", distance=OUT_BAND_M / mpt)[0])
        cov = len(hit) / len(samples)
        sc = share * cov
        if cov >= OUT_COV and (best is None or sc > bst["score"]):
            best, bst = lines, {"pen": f"stroke {k[0]} w {k[1]}", "share": round(share, 2), "cov": round(cov, 2),
                                "score": round(sc, 3), "pen_segs": int(inz.sum())}
    return best, bst


def building_outline(page: dict, region, walls: list, kept: list, opens: list, rooms: list, mpt: float):
    """Closed footprint of the plan's building from its outline pen: closing (OUT_CLOSE_M) over the pen strokes, the
    kept walls and the openings, holes filled, dangling strokes (a parapet drawn on past the facade) eroded away.
    Returns (Polygon | None, pen lines | None, stats)."""
    import numpy as np
    import time
    import shapely
    t0 = time.monotonic()
    pen, st = outline_pen(page, region, mpt)
    if pen is None:
        return None, None, {**st, "outline": "no outline pen"}
    if time.monotonic() - t0 > 0.6 * OUT_TIME_S:
        return None, None, {**st, "outline": "time cap"}
    kp = [g for g in (_poly(w.get("polygon") or []) for w in kept) if g is not None and not g.is_empty]
    op = [box(*o["bbox"]) for o in opens if o.get("bbox") and region.intersects(box(*o["bbox"]))]
    merged = shapely.line_merge(shapely.multilinestrings(pen))  # 1000s of plot segments -> a few polylines
    geoms = np.array(list(getattr(merged, "geoms", [merged])) + kp + op, dtype=object)
    parts = []
    for cm in (OUT_CLOSE_M,):
        c = cm / mpt
        u = shapely.union_all(shapely.buffer(geoms, c, quad_segs=1))
        fills = [Polygon(g.exterior) for g in getattr(u, "geoms", [u]) if g.geom_type == "Polygon"]
        fp = unary_union(fills).buffer(-c, join_style="mitre")
        parts = [g for g in getattr(fp, "geoms", [fp]) if g.geom_type == "Polygon" and g.area * mpt * mpt >= 2.0
                 and g.intersection(region).area >= 0.5 * g.area]
        if parts and sum(g.area for g in parts) >= OUT_MIN_AREA * region.area:
            st["outline_close_m"] = cm
            break
    if not parts:
        st["outline"] = "outline not closed"
        return None, None, st
    fp = unary_union([Polygon(g.exterior) for g in parts]).simplify(0.05 / mpt)
    o = OUT_OPEN_M / mpt  # opening: walls drawn on past the facade (a terrace parapet) are strips, not building
    fp = fp.buffer(-o, join_style="mitre").buffer(o, join_style="mitre")
    fp = unary_union([Polygon(g.exterior) for g in getattr(fp, "geoms", [fp]) if g.geom_type == "Polygon"
                      and g.area * mpt * mpt >= 2.0])
    if fp.is_empty:
        st["outline"] = "outline not closed"
        return None, None, st
    st["outline_m2"] = round(fp.area * mpt * mpt, 1)
    if fp.area > region.area:  # the outline tightens the evidence crop (facades, not the 3-4 m evidence margin)
        st["outline"] = f"outline larger than the evidence region ({fp.area / region.area:.2f}x)"
        return None, None, st
    if fp.area < OUT_MIN_AREA * region.area:
        st["outline"] = f"outline holds {fp.area / region.area:.0%} of the region"
        return None, None, st
    # room labels and ceiling-height marks only: wall-type, fire and window codes (US202, EI60, F13) and door tags
    # are printed just OUTSIDE the facade they annotate, so they say nothing about where the rooms end
    pts = [Point(_c(r["label_bbox"])) for r in rooms if r.get("label_bbox") and (r.get("number") or r.get("label"))
           and not NOT_ROOM.search(r.get("label") or "")]
    pts += [Point(_c(w["bbox"])) for w in page.get("words") or [] if CEIL.match((w.get("text") or "").strip())]
    pts = [p for p in pts if region.contains(p)]
    grow = fp.buffer(0.5 / mpt)
    if pts and sum(1 for p in pts if grow.contains(p)) < OUT_LABELS * len(pts):
        st["outline"] = "outline misses room labels"
        return None, None, st
    if time.monotonic() - t0 > OUT_TIME_S:
        return None, None, {**st, "outline": "time cap"}
    st["outline"] = "ok"
    st["outline_s"] = round(time.monotonic() - t0, 2)
    return fp, pen, st


def _clip_wall(w, ax, g, t):
    """Wall w clipped to the longest piece of its axis ax inside g (None when nothing is left)."""
    inside = ax.intersection(g)
    parts = [q for q in getattr(inside, "geoms", [inside]) if q.geom_type == "LineString" and q.length > 0]
    if not parts:
        return None
    s = max(parts, key=lambda q: q.length)
    a, b = list(s.coords)[0], list(s.coords)[-1]
    c = {k: v for k, v in w.items() if k not in ("polygon", "centerline")}
    c.update(polygon=_rect(a, b, t), centerline=[[round(a[0], 3), round(a[1], 3)], [round(b[0], 3), round(b[1], 3)]],
             clipped_to_plan=True)
    return c, s.length


def crop_to_outline(walls: list, kept: list, fp, mpt: float) -> list:
    """Walls of the building: kept walls and any wall almost wholly inside the footprint; walls reaching out past it
    (a facade line drawn on along a terrace parapet) clipped to the footprint; walls outside dropped."""
    kept_ids = {id(w) for w in kept}
    out, grown = [], {}
    for w in walls:
        ax = _axis(w)
        if ax is None or ax.length <= 0:
            continue
        t = float(w.get("thickness_pt") or 0)
        if t not in grown:
            grown[t] = fp.buffer(t / 2 + 0.3 / mpt, join_style="mitre")
        fr = ax.intersection(grown[t]).length / ax.length
        if fr >= 0.97:
            if id(w) in kept_ids or fr >= 0.99:
                out.append(w)
            continue
        if id(w) not in kept_ids and fr < HULL_FRAC:
            continue
        r = _clip_wall(w, ax, grown[t], t)
        if r is not None and r[1] * mpt >= OUT_MIN_PIECE_M:
            out.append(r[0])
    return out


def close_outline(fp, pen, kept: list, opens: list, mpt: float) -> list:
    """Facade pieces the walls miss: along each edge of the footprint, the stretch (offset half a wall inside) that no
    kept wall or opening covers and that the outline pen draws, as a wall of the facade's own thickness."""
    import statistics
    rings = [g.exterior.simplify(0.1 / mpt) for g in getattr(fp, "geoms", [fp])]
    edge = fp.boundary
    ts = [float(w.get("thickness_pt") or 0) for w in kept
          if w.get("thickness_pt") and (_poly(w.get("polygon") or []) or Point(0, 0)).distance(edge) <= 0.3 / mpt
          and float(w["thickness_pt"]) * mpt >= 0.15]
    t = statistics.median(ts) if ts else 0.3 / mpt
    t = min(max(t, 0.15 / mpt), 0.6 / mpt)
    import numpy as np
    import shapely
    cg = [g for g in (_poly(w.get("polygon") or []) for w in kept) if g is not None] + \
         [box(*o["bbox"]) for o in opens if o.get("bbox")]
    cover = shapely.union_all(shapely.buffer(np.array(cg, dtype=object), 0.1 / mpt, quad_segs=1))
    shapely.prepare(cover)
    tree = shapely.STRtree(pen)  # the outline pen's segments
    reach = OUT_PEN_M / mpt + t / 2
    out = []
    edges = [e for r in rings for e in zip(list(r.coords)[:-1], list(r.coords)[1:])]
    import math
    hist = Counter()  # the walls' main directions (length-weighted, 5-degree bins): facades run along them
    for w in kept:
        x = _axis(w)
        if x is not None and x.length > 0:
            (x0, y0), (x1, y1) = x.coords[0], x.coords[-1]
            hist[int(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180 // 5)] += x.length
    tot = sum(hist.values()) or 1.0
    main = [(k * 5 + 2.5) for k, v in hist.items() if v >= OUT_DIR_SHARE * tot]
    for a, b in edges:
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
        if main and min(min(abs(ang - m), 180 - abs(ang - m)) for m in main) > 7.5:
            continue  # a chamfer the closing cut across a notch, not a facade
        seg = LineString([a, b])
        if seg.length * mpt < OUT_MIN_PIECE_M:
            continue
        cl = None
        for side in ("left", "right"):
            o = seg.parallel_offset(t / 2, side)
            if o.length > 0 and fp.contains(o.interpolate(0.5, normalized=True)):
                cl = o
                break
        if cl is None:
            continue
        miss = cl.difference(cover)
        for p in getattr(miss, "geoms", [miss]):
            if p.geom_type != "LineString" or p.length * mpt < OUT_MIN_PIECE_M:
                continue
            sm = shapely.line_interpolate_point(p, np.arange(0, p.length, 0.25 / mpt))
            if len(np.unique(tree.query(sm, predicate="dwithin", distance=reach)[0])) < 0.7 * len(sm):
                continue  # the outline pen does not draw this stretch
            q0, q1 = list(p.coords)[0], list(p.coords)[-1]
            L = p.length
            ext = t / 2  # reach the corner / the covered wall it closes between
            ux, uy = (q1[0] - q0[0]) / L, (q1[1] - q0[1]) / L
            a2, b2 = (q0[0] - ux * ext, q0[1] - uy * ext), (q1[0] + ux * ext, q1[1] + uy * ext)
            out.append({"polygon": _rect(a2, b2, t), "centerline": [[round(a2[0], 3), round(a2[1], 3)],
                        [round(b2[0], 3), round(b2[1], 3)]], "thickness_pt": round(t, 3), "style": "outline",
                        "from_outline_pen": True})
    return out


def envelope_clip(page: dict, walls: list, rooms: list | None, m_per_pt: float):
    """plan_region's crop for any wall set (e.g. an MEP sheet's shell walls from its architect underlay): the walls of
    the building that holds the plan evidence, closed along its outline pen, neighbouring roofs and context wings
    out. Returns (walls, region): the input list unchanged and None when there is too little evidence to decide.
    Never raises."""
    try:
        ws = list(walls)
        region, st = plan_region(page, ws, list(rooms or []), [], m_per_pt)
        if region is None:
            return walls, None
        keep = set(st.get("keep_ids") or [])
        return [w for w in ws if id(w) in keep], region
    except Exception:  # noqa: BLE001
        return walls, None

