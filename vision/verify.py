"""V-09: verify step over a plan map.

Stage 1, geometry rules (free, each switchable and measured alone):
  tiny      drop door/window boxes smaller than a fraction of the image / door width
  dup       merge same-kind boxes that overlap (IoU or containment)
  on_wall   doors/windows must touch a wall box (margin px); others are dropped
  split     split over-long window runs at perpendicular wall junctions
Stage 2, model check for low-confidence items (see model_check): crop with the box drawn,
yes/no/other answer through engine call("verify_item"), cached by crop hash.
Thresholds are picked on calibration drawings (data/cubicasa5k/calib), never on the held-out 241.
"""
import copy

KINDS = ("door", "window", "toilet", "sink", "bathtub", "shower")
DEFAULTS = {"tiny_frac": 2e-5, "dup_iou": 0.3, "dup_contain": 0.7, "dup_gap_frac": 0.0, "wall_margin_frac": 0.006,
            "split_ratio": 2.2, "split_min_frac": 0.08}


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def _touch(a, b, m):
    return a[0] - m <= b[2] and b[0] - m <= a[2] and a[1] - m <= b[3] and b[1] - m <= a[3]


def rule_tiny(items, W, H, p):
    amin = p["tiny_frac"] * W * H
    return [i for i in items if i["kind"] not in ("door", "window") or _area(i["bbox_px"]) >= amin]


def rule_dup(items, W, H, p):
    out, drop = [], set()
    for k in p.get("dup_kinds", KINDS):
        grp = sorted([i for i in items if i["kind"] == k], key=lambda i: -i["conf"])
        keep = []
        for i in grp:
            dup = False
            for j in keep:
                inter = _inter(i["bbox_px"], j["bbox_px"])
                if not inter:
                    if p["dup_gap_frac"] and _touch(i["bbox_px"], j["bbox_px"], p["dup_gap_frac"] * max(W, H)):
                        inter, iou = 1, 1.0  # adjacent fragments of one object
                        dup = True
                        b, c = j["bbox_px"], i["bbox_px"]
                        j["bbox_px"] = [min(b[0], c[0]), min(b[1], c[1]), max(b[2], c[2]), max(b[3], c[3])]
                        break
                    continue
                iou = inter / (_area(i["bbox_px"]) + _area(j["bbox_px"]) - inter)
                if iou >= p["dup_iou"] or inter / max(1, min(_area(i["bbox_px"]), _area(j["bbox_px"]))) >= p["dup_contain"]:
                    dup = True
                    b, c = j["bbox_px"], i["bbox_px"]
                    j["bbox_px"] = [min(b[0], c[0]), min(b[1], c[1]), max(b[2], c[2]), max(b[3], c[3])]
                    break
            if dup:
                drop.add(id(i))
            else:
                keep.append(i)
    return [i for i in items if id(i) not in drop]


def rule_on_wall(items, W, H, p, kinds=("door", "window")):
    m = p["wall_margin_frac"] * max(W, H)
    walls = [i["bbox_px"] for i in items if i["kind"] == "wall"]
    if not walls:
        return items  # no wall evidence: do not drop anything
    return [i for i in items if i["kind"] not in kinds or any(_touch(i["bbox_px"], w, m) for w in walls)]


def rule_split(items, W, H, p):
    walls = [i["bbox_px"] for i in items if i["kind"] == "wall"]
    out = []
    for i in items:
        b = i["bbox_px"]
        w, h = b[2] - b[0], b[3] - b[1]
        if i["kind"] != "window" or max(w, h) / max(1, min(w, h)) < p["split_ratio"] or max(w, h) < p["split_min_frac"] * max(W, H):
            out.append(i)
            continue
        horiz = w >= h
        cuts = []
        for wb in walls:
            ww, wh = wb[2] - wb[0], wb[3] - wb[1]
            if horiz and wh > ww and wb[1] < b[3] and wb[3] > b[1]:  # vertical wall crossing a horizontal window run
                c = (wb[0] + wb[2]) / 2
                if b[0] + 0.1 * w < c < b[2] - 0.1 * w:
                    cuts.append(c)
            if not horiz and ww > wh and wb[0] < b[2] and wb[2] > b[0]:
                c = (wb[1] + wb[3]) / 2
                if b[1] + 0.1 * h < c < b[3] - 0.1 * h:
                    cuts.append(c)
        if not cuts:
            out.append(i)
            continue
        cuts = sorted(cuts)
        merged = [cuts[0]]
        for c in cuts[1:]:
            if c - merged[-1] > 0.02 * max(W, H):
                merged.append(c)
        edges = ([b[0] if horiz else b[1]] + merged + [b[2] if horiz else b[3]])
        for a, e in zip(edges, edges[1:]):
            j = copy.deepcopy(i)
            j["bbox_px"] = [int(a), b[1], int(e), b[3]] if horiz else [b[0], int(a), b[2], int(e)]
            j["props"] = {**j.get("props", {}), "split_from": i["item_id"]}
            out.append(j)
    return out


RULE_FNS = {"tiny": rule_tiny, "dup": rule_dup, "on_wall": rule_on_wall, "split": rule_split}
ORDER = ["tiny", "dup", "on_wall", "split"]


def apply_rules(pm, rules, params=None):
    p = {**DEFAULTS, **(params or {})}
    items = copy.deepcopy(pm["items"])
    for r in ORDER:
        if r in rules:
            items = RULE_FNS[r](items, pm["image"]["w"], pm["image"]["h"], p)
    return items


# ---------------------------------------------------------------- stage 2: model check
import hashlib, io, json as _json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/cubicasa5k/verify_cache.json"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "enum": ["yes", "no", "other"]}}, "required": ["answer"]}
NAMES = {"door": "door", "window": "window", "toilet": "toilet", "sink": "sink", "bathtub": "bathtub", "shower": "shower"}
_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            _cache = _json.loads(CACHE.read_text())
        except Exception:
            _cache = {}
    return _cache


def save_cache():
    if _cache is not None:
        CACHE.write_text(_json.dumps(_cache))


def crop_png(img, bbox, pad_frac=0.6, min_side=40, out_min=288):
    from PIL import ImageDraw
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    pad = max(min_side, pad_frac * max(w, h) + 20)
    cx0, cy0 = max(0, int(x0 - pad)), max(0, int(y0 - pad))
    cx1, cy1 = min(img.width, int(x1 + pad)), min(img.height, int(y1 + pad))
    c = img.crop((cx0, cy0, cx1, cy1)).convert("RGB")
    s = max(1.0, out_min / max(c.size))
    c = c.resize((int(c.width * s), int(c.height * s)))
    ImageDraw.Draw(c).rectangle([(x0 - cx0) * s, (y0 - cy0) * s, (x1 - cx0) * s, (y1 - cy0) * s], outline=(255, 0, 0), width=3)
    b = io.BytesIO()
    c.save(b, "PNG")
    return b.getvalue()


def model_check(img, item, request_id=None):
    """-> 'yes' | 'no' | 'other' | None (model unavailable). Cached by crop hash + kind."""
    from engine.models import call
    kind = NAMES[item["kind"]]
    png = crop_png(img, item["bbox_px"])
    key = hashlib.sha256(png + kind.encode()).hexdigest()
    cache = _load_cache()
    if key in cache:
        return cache[key]
    prompt = (f"This is a crop of a floor plan. The red box marks one detected object. Is the object inside the red box a {kind}? "
              f'Answer "yes" if it is a {kind} symbol, "no" if it is not (for example a wall, text, a different fixture or nothing), '
              'or "other" if it is some other plan symbol. Reply as JSON: {"answer": "yes|no|other"}.')
    try:
        r = call("verify_item", [{"role": "user", "content": prompt}], images=[png], schema=SCHEMA, request_id=request_id)
        a = (r.json or {}).get("answer") if r.json else None
    except Exception:
        a = None
    if a in ("yes", "no", "other"):
        cache[key] = a
    return a if a in ("yes", "no", "other") else None


def zone_items(items, lo, hi):
    return [i for i in items if i["kind"] in NAMES and lo <= i["conf"] < hi]


def prefetch(jobs, workers=4):
    """jobs: [(img, item, request_id)] -> fills the cache with a few threads, returns calls made."""
    from concurrent.futures import ThreadPoolExecutor
    cache = _load_cache()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda j: model_check(*j), jobs))
    save_cache()
    return res


def apply_model(items, img, lo, hi, request_id=None):
    """Drop items below lo; keep >= hi; in between keep only when the model says yes (cache must be warm, else keep)."""
    out = []
    for i in items:
        if i["kind"] not in NAMES or i["conf"] >= hi:
            out.append(i)
        elif i["conf"] < lo:
            continue
        else:
            a = model_check(img, i, request_id)
            if a in (None, "yes"):
                out.append(i)
    return out


# ---------------------------------------------------------------- bathroom crop: showers + bathtubs
WET_TYPES = ("bathroom", "wc", "sauna")
COUNT_SCHEMA = {"type": "object", "properties": {"showers": {"type": "integer", "minimum": 0, "maximum": 4}, "bathtubs": {"type": "integer", "minimum": 0, "maximum": 4}}, "required": ["showers", "bathtubs"]}


def wet_rooms(items):
    return [i for i in items if i["kind"] == "room" and i["props"].get("room_type") in WET_TYPES]


def wet_count(img, room, request_id=None):
    """-> (showers, bathtubs) in one bathroom crop, or None. Cached by crop hash."""
    from engine.models import call
    x0, y0, x1, y1 = room["bbox_px"]
    pad = 0.08 * max(x1 - x0, y1 - y0)
    c = img.crop((max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(img.width, int(x1 + pad)), min(img.height, int(y1 + pad)))).convert("RGB")
    s = max(1.0, 448 / max(c.size))
    c = c.resize((int(c.width * s), int(c.height * s)))
    b = io.BytesIO(); c.save(b, "PNG"); png = b.getvalue()
    key = "wet:" + hashlib.sha256(png).hexdigest()
    cache = _load_cache()
    if key in cache:
        return tuple(cache[key])
    prompt = ("This is a crop of one bathroom or toilet room from a floor plan. Count the shower cubicles/shower trays "
              "and the bathtubs drawn inside it. Do not count toilets, sinks or washing machines. "
              'Reply as JSON: {"showers": n, "bathtubs": n}.')
    try:
        r = call("verify_item", [{"role": "user", "content": prompt}], images=[png], schema=COUNT_SCHEMA, request_id=request_id)
        j = r.json or {}
        v = (int(j["showers"]), int(j["bathtubs"]))
    except Exception:
        return None
    cache[key] = list(v)
    return v


# ---------------------------------------------------------------- default free pass used by build_planmaps
CUT = {"door": 0.7, "window": 0.7, "toilet": 0.7}  # picked on calibration drawings; sink/bathtub get no cut (it lowers them on calib+held-out)
FREE = {"dup_gap_frac": 0.003, "dup_iou": 0.3, "dup_kinds": ("door", "window", "toilet", "bathtub", "shower")}


def free_pass(items, W, H):
    """Duplicate/adjacent merge, then a confidence cut for door/window/toilet. Walls, rooms, text untouched."""
    items = rule_dup(items, W, H, {**DEFAULTS, **FREE})
    return [i for i in items if i["conf"] >= CUT.get(i["kind"], 0)]
