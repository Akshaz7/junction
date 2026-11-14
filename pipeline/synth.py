"""V-05b: synthetic labelled floor plans for VISION.
Sources: IFC docs that are NOT held out and carry no question (registry heldout=false), minus
ND / GPL-data / banned docs. Geometry is read straight from the IFC (exact), drawn with PIL in
varied styles. Output: data/synth/<id>.png + <id>.json, sources.txt, README.md.
Labels are exact boxes from IFC footprints; nothing is detected or guessed.
CLI: python -m pipeline.synth probe | extract [--only ID] | render [--per-storey N] [--limit N]"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import signal
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "data" / "full" / "junction-dataset"
OUT = REPO / "data" / "synth"
CACHE = REPO / "artifacts" / "_synth_cache"
BAN = ("duplex", "dental", "hitos")
MAX_MB = 60

ROOM_TYPES = [  # keyword (lowercase) -> room_type
    (("bad", "bath", "badezimmer", "dusche", "sauna"), "bathroom"), (("wc", "toilet", "toilette", "abort"), "wc"),
    (("küche", "kueche", "kitchen", "kochen", "cuisine"), "kitchen"), (("schlaf", "bed", "kinder", "zimmer"), "bedroom"),
    (("wohn", "living", "salon", "stube", "aufenthalt"), "living"), (("flur", "gang", "korridor", "hall", "diele", "entrée", "eingang"), "hall"),
    (("treppe", "stair"), "stairs"), (("keller", "abstell", "lager", "storage", "technik", "heiz"), "storage"),
    (("büro", "buero", "office", "arbeit"), "office"), (("balkon", "terrasse", "loggia"), "balcony"),
]
SAN_BY_PDT = {"TOILETPAN": "toilet", "WC": "toilet", "SINK": "sink", "WASHHANDBASIN": "sink", "BASIN": "sink",
              "SHOWER": "shower", "BATH": "bathtub", "BIDET": "sink"}
SAN_BY_NAME = [(("wc", "toilet", "closet", "vaso", "bacia", "inodoro", "urinal"), "toilet"),
               (("shower", "dusche", "chuveiro", "ducha"), "shower"),
               (("bath", "wanne", "badewanne", "tub", "banheira"), "bathtub"),
               (("sink", "basin", "waschtisch", "lavabo", "spül", "washbasin", "handwasch", "cuba", "lavat", "pia-"), "sink")]


def room_type(s: str | None):
    s = (s or "").lower()
    for keys, t in ROOM_TYPES:
        if any(k in s for k in keys):
            return t
    return None


def san_kind(el):
    pdt = str(getattr(el, "PredefinedType", "") or "").upper()
    if pdt in SAN_BY_PDT:
        return SAN_BY_PDT[pdt]
    txt = " ".join(str(x or "") for x in (el.Name, getattr(el, "ObjectType", None))).lower()
    try:
        import ifcopenshell.util.element as ue
        t = ue.get_type(el)
        if t is not None:
            txt += " " + str(t.Name or "").lower() + " " + str(getattr(t, "PredefinedType", "") or "").lower()
    except Exception:
        pass
    for keys, k in SAN_BY_NAME:
        if any(w in txt for w in keys):
            return k
    return None


def eligible():
    rows = [json.loads(l) for l in open(REPO / "artifacts" / "registry.jsonl")]
    held = set((REPO / "data" / "sets" / "heldout_docs.txt").read_text().split())
    out = []
    for r in rows:
        if r["heldout"] or "ifc" not in r["formats"] or r["doc_id"] in held:
            continue
        if r["licence"] and "ND" in r["licence"].split("-"):
            continue
        if any(b in r["doc_id"] for b in BAN):
            continue
        p = ROOT / r["files"]["ifc"]
        if not p.exists() or p.stat().st_size < 20_000 or p.stat().st_size > MAX_MB * 1e6:
            continue
        out.append((r, p))
    return out


def extract(r, p):
    """-> {storey: {kind: [ {poly: [[x,y]..], bbox:[..], room_type?} ]}} in metres, world XY."""
    import ifcopenshell
    import ifcopenshell.geom as geom
    import ifcopenshell.util.element as ue
    f = ifcopenshell.open(str(p))
    s = geom.settings()
    s.set("use-world-coords", True)
    wanted = [("IfcWall", "wall"), ("IfcDoor", "door"), ("IfcWindow", "window"), ("IfcSpace", "room"),
              ("IfcStair", "stairs"), ("IfcSanitaryTerminal", None), ("IfcFlowTerminal", None)]
    res: dict = {}
    seen = set()
    for cls, kind in wanted:
        try:
            els = f.by_type(cls)
        except Exception:
            continue
        for el in els:
            if el.id() in seen:
                continue
            seen.add(el.id())
            k = kind or san_kind(el)
            if k is None:
                continue
            try:
                sh = geom.create_shape(s, el)
                v = np.array(sh.geometry.verts).reshape(-1, 3)
                t = np.array(sh.geometry.faces).reshape(-1, 3)
            except Exception:
                continue
            if len(t) == 0:
                continue
            c = ue.get_container(el)
            if c is None:
                c = ue.get_aggregate(el)
            for _ in range(6):
                if c is None or c.is_a("IfcBuildingStorey"):
                    break
                c = ue.get_container(c) or ue.get_aggregate(c)
            if c is None:
                continue
            tris = []
            for a, b, d in t:
                pg = Polygon(v[[a, b, d], :2])
                if pg.area > 1e-8:
                    tris.append(pg)
            if not tris:
                continue
            u = unary_union([q.buffer(0.001) for q in tris]).buffer(-0.001)
            if u.is_empty:
                continue
            u = u if isinstance(u, Polygon) else max(u.geoms, key=lambda g: g.area)
            u = u.simplify(0.01)
            item = {"poly": [[round(x, 3), round(y, 3)] for x, y in u.exterior.coords[:-1]], "bbox": [round(x, 3) for x in u.bounds]}
            if k == "room":
                item["room_type"] = room_type(el.LongName) or room_type(el.Name)
            res.setdefault(c.Name or f"storey{c.id()}", {}).setdefault(k, []).append(item)
    return res


def probe():
    el = eligible()
    print(len(el), "eligible docs")
    tot = {}
    for r, p in el:
        print(r["doc_id"], round(p.stat().st_size / 1e6, 1), "MB")


# ---------------------------------------------------------------- rendering
FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Narrow.ttf",
         "/System/Library/Fonts/Supplemental/Courier New.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
         "/System/Library/Fonts/Supplemental/Verdana.ttf", "/System/Library/Fonts/Supplemental/Tahoma.ttf"]
KINDS_OUT = ["wall", "door", "window", "room", "toilet", "sink", "shower", "bathtub", "stairs"]


def _font(size):
    from PIL import ImageFont
    rng = random.choice([f for f in FONTS if Path(f).exists()] or [None])
    try:
        return ImageFont.truetype(rng, size) if rng else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _rot(pt, k):
    x, y = pt
    for _ in range(k % 4):
        x, y = -y, x
    return x, y


def render_storey(items, doc_id, storey, out_id, rng: random.Random):
    """items: {kind: [ {poly,bbox,room_type} ]} in metres. Returns (image, json) or None."""
    from PIL import Image, ImageDraw, ImageFilter
    k = rng.choice([0, 0, 1, 2, 3])
    pts = {kd: [[_rot(q, k) for q in it["poly"]] for it in lst] for kd, lst in items.items()}
    allp = [q for lst in pts.values() for poly in lst for q in poly]
    xs = [q[0] for q in allp]; ys = [q[1] for q in allp]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w_m, h_m = x1 - x0, y1 - y0
    if w_m < 3 or h_m < 3 or w_m > 400 or h_m > 400:
        return None
    ppm = rng.choice([10, 14, 18, 24, 32, 42, 56])
    m = rng.randint(30, 90)
    long_px = max(w_m, h_m) * ppm
    if long_px > 2000:
        ppm *= 2000 / long_px
    if max(w_m, h_m) * ppm < 450:
        ppm = 450 / max(w_m, h_m)
    W, H = int(w_m * ppm + 2 * m), int(h_m * ppm + 2 * m)
    T = lambda q: ((q[0] - x0) * ppm + m, (y1 - q[1]) * ppm + m)
    paper = rng.choice([255, 255, 250, 245, 238])
    ink = rng.choice([0, 0, 20, 40])
    lw = rng.choice([1, 1, 2, 2, 3, 4]) if ppm > 14 else rng.choice([1, 1, 2])
    wall_mode = rng.choice(["solid", "solid", "outline", "grey", "hatch"])
    img = Image.new("L", (W, H), paper)
    d = ImageDraw.Draw(img)
    labels = rng.random() < 0.6
    dims = rng.random() < 0.5
    out = []
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)

    def bb(poly):
        px = [T(q) for q in poly]
        xs_ = [q[0] for q in px]; ys_ = [q[1] for q in px]
        return [round(max(0, min(xs_)), 1), round(max(0, min(ys_)), 1), round(min(W, max(xs_)), 1), round(min(H, max(ys_)), 1)], px

    fsz = max(9, int(ppm * rng.uniform(0.35, 0.6)))
    font = _font(fsz)
    for it, poly in zip(items.get("room", []), pts.get("room", [])):
        b, px = bb(poly)
        d.polygon(px, outline=None, fill=rng.choice([paper, paper, paper - 8]) if wall_mode != "solid" else paper)
        out.append({"kind": "room", "bbox_px": b, "polygon_px": [[round(a, 1), round(c, 1)] for a, c in px], "room_type": it.get("room_type")})
    for poly in pts.get("wall", []):
        b, px = bb(poly)
        fill = {"solid": ink, "outline": paper, "grey": 150, "hatch": 200}[wall_mode]
        d.polygon(px, fill=fill, outline=ink)
        if wall_mode == "hatch":
            x_a, y_a, x_b, y_b = b
            for t in range(int(x_a - (y_b - y_a)), int(x_b), max(4, int(ppm * 0.3))):
                pass
        md.polygon(px, fill=255)
        out.append({"kind": "wall", "bbox_px": b, "polygon_px": [[round(a, 1), round(c, 1)] for a, c in px]})
    for poly in pts.get("window", []):
        b, px = bb(poly)
        d.polygon(px, fill=paper, outline=ink)
        x_a, y_a, x_b, y_b = b
        if x_b - x_a > y_b - y_a:
            d.line([(x_a, (y_a + y_b) / 2), (x_b, (y_a + y_b) / 2)], fill=ink, width=max(1, lw // 2))
        else:
            d.line([((x_a + x_b) / 2, y_a), ((x_a + x_b) / 2, y_b)], fill=ink, width=max(1, lw // 2))
        out.append({"kind": "window", "bbox_px": b, "polygon_px": None})
    for poly in pts.get("door", []):
        b, px = bb(poly)
        d.polygon(px, fill=paper, outline=ink)
        x_a, y_a, x_b, y_b = b
        r = max(x_b - x_a, y_b - y_a)
        if rng.random() < 0.8:
            d.arc([x_a, y_a, x_a + 2 * (x_b - x_a), y_a + 2 * (y_b - y_a)], 180, 270, fill=ink, width=max(1, lw // 2)) if False else d.line([(x_a, y_a), (x_b, y_b)], fill=ink, width=max(1, lw // 2))
        out.append({"kind": "door", "bbox_px": b, "polygon_px": None})
    for poly in pts.get("stairs", []):
        b, px = bb(poly)
        d.polygon(px, fill=paper, outline=ink)
        x_a, y_a, x_b, y_b = b
        n = max(3, int(max(x_b - x_a, y_b - y_a) / max(4, ppm * 0.28)))
        for i in range(1, n):
            if (x_b - x_a) >= (y_b - y_a):
                xx = x_a + (x_b - x_a) * i / n; d.line([(xx, y_a), (xx, y_b)], fill=ink, width=1)
            else:
                yy = y_a + (y_b - y_a) * i / n; d.line([(x_a, yy), (x_b, yy)], fill=ink, width=1)
        out.append({"kind": "stairs", "bbox_px": b, "polygon_px": None})
    for kd in ("toilet", "sink", "shower", "bathtub"):
        for poly in pts.get(kd, []):
            b, px = bb(poly)
            x_a, y_a, x_b, y_b = b
            d.rectangle([x_a, y_a, x_b, y_b], fill=paper, outline=ink, width=max(1, lw // 2))
            if kd == "toilet":
                d.ellipse([x_a + (x_b - x_a) * .15, y_a + (y_b - y_a) * .35, x_b - (x_b - x_a) * .15, y_b - 1], outline=ink)
            elif kd == "sink":
                d.ellipse([x_a + (x_b - x_a) * .25, y_a + (y_b - y_a) * .25, x_b - (x_b - x_a) * .25, y_b - (y_b - y_a) * .25], outline=ink)
            elif kd == "shower":
                d.line([(x_a, y_a), (x_b, y_b)], fill=ink); d.line([(x_a, y_b), (x_b, y_a)], fill=ink)
            else:
                ins = min(3, (x_b - x_a) / 4, (y_b - y_a) / 4)
                d.rounded_rectangle([x_a + ins, y_a + ins, x_b - ins, y_b - ins], radius=min(8, ins * 2), outline=ink)
            out.append({"kind": kd, "bbox_px": b, "polygon_px": None})
    if labels:
        for it, poly in zip(items.get("room", []), pts.get("room", [])):
            if it.get("room_type") and rng.random() < 0.9:
                b, _ = bb(poly)
                d.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), it["room_type"].upper(), fill=ink, font=font, anchor="mm")
    if dims:
        d.line([(m, m / 2), (W - m, m / 2)], fill=ink, width=1)
        d.text((W / 2, m / 2 - 2), f"{w_m:.2f}", fill=ink, font=font, anchor="ms")
        d.line([(m / 2, m), (m / 2, H - m)], fill=ink, width=1)
        d.text((m / 2 - 2, H / 2), f"{h_m:.2f}", fill=ink, font=font, anchor="rm")
    # scan noise
    if rng.random() < 0.7:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.3)))
    a = np.asarray(img, dtype=np.float32)
    if rng.random() < 0.8:
        a += np.random.default_rng(rng.randint(0, 10**9)).normal(0, rng.uniform(2, 14), a.shape)
        sp = np.random.default_rng(rng.randint(0, 10**9)).random(a.shape)
        a[sp < rng.uniform(0, 0.003)] = 0
    if rng.random() < 0.5:
        gx = np.linspace(rng.uniform(-18, 0), rng.uniform(0, 18), W)[None, :]
        a += gx
    a = np.clip((a - 128) * rng.uniform(0.8, 1.1) + 128 + rng.uniform(-8, 8), 0, 255).astype(np.uint8)
    img = Image.fromarray(a)
    js = {"image": {"w": W, "h": H}, "items": out, "doc_id": doc_id, "storey": storey,
          "style": {"rot90": k, "px_per_m": round(ppm, 2), "wall_mode": wall_mode, "line_w": lw, "labels": labels, "dims": dims}}
    return img, mask, js


# ---------------------------------------------------------------- procedural plans
FIX_SIZE = {"toilet": (0.40, 0.70), "sink": (0.55, 0.45), "shower": (0.90, 0.90), "bathtub": (1.70, 0.75)}


def _rectpoly(x0, y0, x1, y1):
    return [[round(x0, 3), round(y0, 3)], [round(x1, 3), round(y0, 3)], [round(x1, 3), round(y1, 3)], [round(x0, 3), round(y1, 3)]]


def _item(poly, **kw):
    xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
    return {"poly": poly, "bbox": [min(xs), min(ys), max(xs), max(ys)], **kw}


def procedural_plan(rng: random.Random):
    """Random BSP floor plan, metres, same item structure as extract(). Exact fixtures/openings; all generated."""
    W, H = rng.uniform(7, 18), rng.uniform(6, 14)
    t_ext, t_int = rng.uniform(0.2, 0.35), rng.uniform(0.08, 0.16)
    segs, leaves = [], []  # segs: (orient 'h'/'v', fixed, a, b, thickness, exterior)

    def split(x0, y0, x1, y1, depth):
        w, h = x1 - x0, y1 - y0
        can_v, can_h = w > 4.4, h > 4.4
        if depth >= 4 or not (can_v or can_h) or (depth >= 2 and rng.random() < 0.25):
            leaves.append((x0, y0, x1, y1)); return
        vert = can_v and (not can_h or rng.random() < w / (w + h))
        if vert:
            c = rng.uniform(x0 + 2.2, x1 - 2.2); segs.append(("v", c, y0, y1, t_int, False))
            split(x0, y0, c, y1, depth + 1); split(c, y0, x1, y1, depth + 1)
        else:
            c = rng.uniform(y0 + 2.2, y1 - 2.2); segs.append(("h", c, x0, x1, t_int, False))
            split(x0, y0, x1, c, depth + 1); split(x0, c, x1, y1, depth + 1)

    split(0, 0, W, H, 0)
    for o, f, a, b in (("h", 0, 0, W), ("h", H, 0, W), ("v", 0, 0, H), ("v", W, 0, H)):
        segs.append((o, f, a, b, t_ext, True))
    # room types
    order = sorted(range(len(leaves)), key=lambda i: (leaves[i][2] - leaves[i][0]) * (leaves[i][3] - leaves[i][1]))
    types = [None] * len(leaves)
    small = [i for i in order if min(leaves[i][2] - leaves[i][0], leaves[i][3] - leaves[i][1]) >= 1.9]
    if small:
        types[small[0]] = "bathroom"
        if len(small) > 2 and rng.random() < 0.5:
            types[small[1]] = rng.choice(["wc", "bathroom"])
    pool = ["living", "bedroom", "kitchen", "bedroom", "office", "hall", "storage"]
    for i in range(len(leaves)):
        if types[i] is None:
            types[i] = rng.choice(pool)
    items = {"wall": [], "door": [], "window": [], "room": [], "toilet": [], "sink": [], "shower": [], "bathtub": []}
    opens = []  # (kind, rect poly)
    for o, f, a, b, th, ext in segs:
        L = b - a
        gaps = []
        if ext:
            if f == 0 and o == "h" and rng.random() < 0.9:
                gaps.append(("door", a + rng.uniform(0.5, max(0.6, L - 1.6)), rng.uniform(0.9, 1.1)))
            for _ in range(rng.randint(1, 4)):
                wl = rng.uniform(0.8, 2.0)
                if L > wl + 1:
                    gaps.append(("window", a + rng.uniform(0.4, L - wl - 0.4), wl))
        elif L > 1.5 and rng.random() < 0.9:
            dl = rng.uniform(0.75, 1.0)
            gaps.append(("door", a + rng.uniform(0.3, L - dl - 0.3), dl))
        gaps.sort(key=lambda g: g[1])
        ok, last = [], a - 1
        for k, s0, ln in gaps:  # drop overlaps
            if s0 > last + 0.15 and s0 + ln < b:
                ok.append((k, s0, ln)); last = s0 + ln
        pos = a
        half = th / 2
        mk = (lambda p0, p1: _rectpoly(p0, f - half, p1, f + half)) if o == "h" else (lambda p0, p1: _rectpoly(f - half, p0, f + half, p1))
        for k, s0, ln in ok:
            if s0 - pos > 0.05:
                items["wall"].append(_item(mk(pos, s0)))
            op = _item(mk(s0, s0 + ln)); items[k].append(op); opens.append(op["bbox"])
            pos = s0 + ln
        if b - pos > 0.05:
            items["wall"].append(_item(mk(pos, b)))
    keepout = [box(*bx).buffer(0.55) for bx in opens]
    for (x0, y0, x1, y1), rt in zip(leaves, types):
        ins = t_ext / 2 if False else 0.12
        px0, py0, px1, py1 = x0 + ins, y0 + ins, x1 - ins, y1 - ins
        items["room"].append(_item(_rectpoly(x0 + t_int / 2, y0 + t_int / 2, x1 - t_int / 2, y1 - t_int / 2), room_type=rt))
        want = {"bathroom": ["toilet", "sink"] + [rng.choice(["shower", "bathtub", "bathtub"])], "wc": ["toilet", "sink"], "kitchen": ["sink"]}.get(rt, [])
        if rt == "bathroom" and rng.random() < 0.3:
            want.append("shower")
        placed = []
        for kd in want:
            fw, fd = FIX_SIZE[kd]
            for _ in range(40):
                side = rng.choice("NSEW"); rot = side in "EW"
                w_, d_ = (fd, fw) if rot else (fw, fd)
                wall_clear = 0.01
                if side in "NS":
                    cx = rng.uniform(px0 + w_ / 2 + 0.02, px1 - w_ / 2 - 0.02) if px1 - px0 > w_ + 0.04 else None
                    if cx is None: continue
                    cy = py0 + d_ / 2 + wall_clear if side == "S" else py1 - d_ / 2 - wall_clear
                else:
                    cy = rng.uniform(py0 + d_ / 2 + 0.02, py1 - d_ / 2 - 0.02) if py1 - py0 > d_ + 0.04 else None
                    if cy is None: continue
                    cx = px0 + w_ / 2 + wall_clear if side == "W" else px1 - w_ / 2 - wall_clear
                r = box(cx - w_ / 2, cy - d_ / 2, cx + w_ / 2, cy + d_ / 2)
                if px0 > r.bounds[0] or py0 > r.bounds[1] or px1 < r.bounds[2] or py1 < r.bounds[3]:
                    continue
                if any(r.intersects(q.buffer(0.08)) for q in placed) or any(r.intersects(k) for k in keepout):
                    continue
                placed.append(r)
                items[kd].append(_item(_rectpoly(*r.bounds)))
                break
    return {"Procedural": {k: v for k, v in items.items() if v}}


# ---------------------------------------------------------------- overlap guard
def question_docs() -> set:
    """Every doc that carries a question (full set + preview) plus heldout_docs.txt."""
    docs = set((REPO / "data" / "sets" / "heldout_docs.txt").read_text().split())
    for f in [REPO / "data" / "sets" / "questions_en.full.jsonl", REPO / "data" / "sets" / "questions_en.jsonl",
              REPO / "data" / "junction-dataset-preview" / "questions.jsonl"]:
        if f.exists():
            for l in open(f):
                try:
                    d = json.loads(l).get("doc_id")
                except Exception:
                    continue
                if d:
                    docs.add(d)
    return docs


def assert_no_overlap(source_docs, forbidden) -> dict:
    """Raise AssertionError if any source doc is held out / has a question. Returns the check record."""
    src = {d for d in source_docs if d}
    bad = sorted(src & set(forbidden))
    assert not bad, f"overlap with held-out/question docs: {bad[:5]}"
    return {"source_docs": len(src), "forbidden_docs": len(set(forbidden)), "overlap": 0}


def render_all(per_storey=2, n_proc=1200, limit=None, seed=42):
    import hashlib
    import shutil
    forbidden = question_docs()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "images").mkdir(parents=True)
    (OUT / "masks").mkdir()
    rng = random.Random(seed)
    recs, src = [], []

    def emit(oid, origin, doc, storey, items, sub_rng):
        r = render_storey(items, doc, storey, oid, sub_rng)
        if not r:
            return False
        img, mask, js = r
        p = OUT / "images" / f"sy_{oid}.png"
        img.save(p, compress_level=3)
        mask.save(OUT / "masks" / f"sy_{oid}.png", compress_level=3)
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        split = "val" if int(hashlib.md5((doc or oid).encode()).hexdigest(), 16) % 10 == 0 else "train"
        recs.append({"id": f"sy_{oid}", "source": "synthetic", "origin": origin, "items": js["items"], "has_seg": True,
                     "image": f"images/sy_{oid}.png", "w": js["image"]["w"], "h": js["image"]["h"], "sha256": h,
                     "split": split, "style": js["style"]})
        src.append((oid, origin))
        return True

    for cf in sorted(CACHE.glob("*.json")):
        doc = cf.stem
        d = json.loads(cf.read_text())
        if "error" in d:
            continue
        for si, (storey, items) in enumerate(sorted(d.items())):
            if re.search(r"roof|top of|dach|site|section", storey.lower()) or len(items.get("wall", [])) < 4 or (not items.get("room") and len(items.get("wall", [])) < 8):
                continue
            for v in range(per_storey):
                oid = f"{re.sub(r'[^a-z0-9]+', '-', doc.split('__', 1)[-1])[:40]}-s{si}-v{v}"
                if not emit(oid, "ifc:" + doc, doc, storey, items, random.Random(rng.randint(0, 10**9))):
                    break
            if limit and len(recs) >= limit:
                break
        if limit and len(recs) >= limit:
            break
    n_ifc = len(recs)
    for i in range(n_proc if not limit else 0):
        sr = random.Random(rng.randint(0, 10**9))
        items = procedural_plan(sr)["Procedural"]
        emit(f"proc-{i:04d}", "procedural", None, "Procedural", items, sr)
    docs = {o[4:] for _, o in src if o.startswith("ifc:")}
    chk = assert_no_overlap(docs, forbidden)
    with open(OUT / "labels.jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    (OUT / "sources.txt").write_text("".join(f"{a}\t{b}\n" for a, b in src))
    kinds = {}
    for r in recs:
        for it in r["items"]:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    rep = {"images": len(recs), "images_ifc": n_ifc, "images_procedural": len(recs) - n_ifc,
           "by_split": {s: sum(r["split"] == s for r in recs) for s in ("train", "val")}, "labels_by_kind": kinds,
           "images_with_kind": {k: sum(any(i["kind"] == k for i in r["items"]) for r in recs) for k in kinds},
           "sources_used": sorted(docs), "n_ifc_docs": len(docs), "overlap_check": chk,
           "overlap_check_note": "source doc ids vs heldout_docs.txt + every doc with a question (full, en, preview); procedural images use no source doc",
           "note": "generated for demo; IFC geometry exact, procedural plans random; no duplex/dental/hitos"}
    (REPO / "results").mkdir(exist_ok=True)
    (REPO / "results" / "synth_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ("images", "images_ifc", "images_procedural", "labels_by_kind", "overlap_check")}))


def preview(n=20, seed=7):
    from PIL import Image, ImageDraw
    pv = REPO / "results" / "synth_preview"
    pv.mkdir(parents=True, exist_ok=True)
    for f in pv.glob("*.png"):
        f.unlink()
    recs = [json.loads(l) for l in open(OUT / "labels.jsonl")]
    rng = random.Random(seed)
    proc = [r for r in recs if r["origin"] == "procedural"]
    ifc = [r for r in recs if r["origin"] != "procedural" and not any(b in r["origin"] for b in BAN)]
    withfix = [r for r in ifc if any(i["kind"] in FIX_SIZE for i in r["items"])]
    pick = rng.sample(proc, min(10, len(proc))) + withfix[:3] + rng.sample([r for r in ifc if r not in withfix], min(n - 10 - len(withfix[:3]), len(ifc)))
    col = {"door": "red", "window": "blue", "toilet": "green", "sink": "orange", "shower": "magenta", "bathtub": "cyan", "stairs": "purple"}
    for r in pick[:n]:
        im = Image.open(OUT / r["image"]).convert("RGB")
        d = ImageDraw.Draw(im)
        for it in r["items"]:
            if it["kind"] in col:
                d.rectangle(it["bbox_px"], outline=col[it["kind"]], width=max(2, im.width // 300))
        sc = 800 / max(im.size)
        if sc < 1:
            im = im.resize((int(im.width * sc), int(im.height * sc)), Image.LANCZOS)
        im.save(pv / f"{r['id']}.png", optimize=True)
        if (pv / f"{r['id']}.png").stat().st_size > 290_000:
            im.quantize(64).save(pv / f"{r['id']}.png", optimize=True)
    print(len(list(pv.glob('*.png'))), "previews")


def extract_all(only=None, limit=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    n = 0
    for r, p in sorted(eligible(), key=lambda rp: rp[1].stat().st_size):
        if only and r["doc_id"] not in only:
            continue
        out = CACHE / f"{r['doc_id']}.json"
        if out.exists():
            continue
        try:
            signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("300s")))
            signal.alarm(300)
            d = extract(r, p)
            signal.alarm(0)
        except BaseException as e:
            signal.alarm(0)
            d = {"error": str(e)[:200]}
        out.write_text(json.dumps(d))
        cnt = {s: {k: len(v) for k, v in kk.items()} for s, kk in d.items()} if "error" not in d else d
        print(r["doc_id"], json.dumps(cnt)[:300], flush=True)
        n += 1
        if limit and n >= limit:
            break


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["probe", "extract", "render", "preview"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--per-storey", type=int, default=2)
    ap.add_argument("--n-proc", type=int, default=1200)
    a = ap.parse_args()
    if a.cmd == "probe":
        probe()
    elif a.cmd == "extract":
        extract_all(a.only, a.limit)
    elif a.cmd == "preview":
        preview()
    else:
        render_all(a.per_storey, a.n_proc, a.limit)
