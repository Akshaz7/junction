"""Plan map from a page image by a vision-language model (the deploy-image path; no torch, no weights).

read_page(doc_id, page, image_path, out_dir) -> plan map dict (CONTRACT 5.4), written as planmap-<page>.json.
One call("read_drawing") per page. The model returns boxes (box_2d = [ymin, xmin, ymax, xmax] on 0-1000);
we convert to page pixels, then the existing geometry rules of vision/verify.py (tiny, dup, on_wall) clean the
items, the schema validates the result, and every item is marked source "vlm". Scale: printed dimensions the
model read (method "dimension") else the median door width (method "door-prior", confidence 0.3).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KINDS = ("wall", "door", "window", "room", "toilet", "sink", "shower", "bathtub", "stairs", "column")
ROOM_TYPES = ("bedroom", "living", "dining", "kitchen", "bathroom", "wc", "sauna", "balcony", "entry", "storage",
              "technical", "garage", "terrace", "study", "dressing", "corridor", "office", "stairwell", "other")
DOOR_WIDTH_M = 0.9
MAX_SIDE = 2048
CONF = {"room": 0.6, "wall": 0.5}  # the model gives no confidence; fixed, honest, lower for walls

_BOX = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}
SCHEMA = {
    "type": "object", "required": ["is_plan", "items", "dimensions"], "additionalProperties": False,
    "properties": {
        "is_plan": {"type": "boolean"},
        "scale_labels": {"type": "array", "items": {
            "type": "object", "required": ["text", "box_2d"], "additionalProperties": False,
            "properties": {"text": {"type": "string"}, "box_2d": _BOX}}},
        "views": {"type": "array", "items": {
            "type": "object", "required": ["view_type", "box_2d"], "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "box_2d": _BOX,
                           "view_type": {"type": "string", "enum": ["plan", "elevation", "section", "detail", "site", "unknown"]},
                           "printed_scale": {"type": "string"}}}},
        "items": {"type": "array", "items": {
            "type": "object", "required": ["kind", "box_2d"], "additionalProperties": False,
            "properties": {"kind": {"type": "string", "enum": list(KINDS)}, "box_2d": _BOX,
                           "label": {"type": "string"}, "room_type": {"type": "string", "enum": list(ROOM_TYPES)},
                           "printed_area_m2": {"type": "number"}}}},
        "dimensions": {"type": "array", "items": {
            "type": "object", "required": ["text", "meters", "box_2d"], "additionalProperties": False,
            "properties": {"text": {"type": "string"}, "meters": {"type": "number"}, "box_2d": _BOX}}},
    },
}
PROMPT = (
    "You read ONE page of a building drawing and return a structured plan map as JSON only.\n"
    "is_plan: true if the page contains at least one floor-plan view, including mixed sheets with elevations and sections. "
    "For elevations, sections, details, schedules or text pages set is_plan=false and items=[].\n"
    "views: identify EVERY separate drawing view, including elevations, sections, details and site plans. "
    "For each supply title exactly as printed (empty if none), view_type, box_2d enclosing the drawing AND its title/scale label, "
    "and printed_scale exactly as printed (e.g. 1:100 or 3/16\"=1'-0\"; empty if none). "
    "Regions must not overlap; never merge an elevation with a floor plan. "
    "Plan, Pohjapiirros, Grundriss and Våningsplan indicate plans; Julkisivu/Ansicht/Fasad indicate elevations; Leikkaus/Schnitt/Sektion indicate sections. "
    "A site plan, roof profile, detail or section does not provide floor-plan door/window/room counts. "
    "If view boundaries are unclear mark unknown. Never infer a printed scale from door size.\n"
    "scale_labels: every printed ratio label as exact text and a TIGHT box_2d around the label itself. "
    "Include shared or alternative scales here. Do not assign a shared/alternative label to individual views without evidence. "
    "A ratio is not a physical pixel scale unless image DPI, paper size or a local measured dimension is known.\n"
    "items: one entry per element you can SEE, box_2d=[ymin,xmin,ymax,xmax] on a 0-1000 scale of the full image, tight boxes.\n"
    "- room: the whole room area. label = the printed room name/number exactly as printed (else omit). room_type from the enum. "
    "printed_area_m2 only if an area is printed in m2 on the page.\n"
    "- wall: each straight wall run (long thin box along the wall, exterior and interior), not whole rooms.\n"
    "- door: each door, i.e. a gap in a wall with a door leaf line and usually a quarter-circle swing arc (also double doors, "
    "sliding and overhead doors); box it including the swing arc. window: each window (thin parallel lines in a wall). toilet, sink, shower, bathtub: fixtures. "
    "stairs: a staircase. column: a structural column.\n"
    "Only mark elements in PLAN views (looking straight down). Ignore elevations, sections, details and 3D views on the same sheet. "
    "Do not invent elements; count every visible door and window separately; no duplicates.\n"
    "dimensions: printed dimension strings with a clear real-world length (for example 3.20 m, 4200 mm, 12'-6\") with "
    "meters = the length in metres and box_2d = the box spanning the measured distance (its longer side is the measured length). "
    "Only dimensions you can read; [] if none.")


def _prep_image(src: Path) -> tuple[Path, tuple[int, int]]:
    """Downscale for the model (cost). Returns (path to send, original size)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(src)
    size = im.size
    if max(size) > MAX_SIDE:
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    else:
        im = im.convert("RGB")
    out = Path(tempfile.mkdtemp(prefix="vlm-")) / "in.jpg"
    im.save(out, quality=88)
    return out, size


def _px(box, W, H):
    try:
        y0, x0, y1, x1 = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    y0, x0, y1, x1 = (max(0.0, min(1000.0, v)) for v in (y0, x0, y1, x1))
    if y1 - y0 < 1 or x1 - x0 < 1:
        return None
    return [round(x0 / 1000 * W, 1), round(y0 / 1000 * H, 1), round(x1 / 1000 * W, 1), round(y1 / 1000 * H, 1)]


def _scale(items, dims, W, H):
    """(scale dict). Dimensions first, then the door prior."""
    ests = []
    for d in dims:
        b = d["px"]
        n = max(b[2] - b[0], b[3] - b[1])
        if d["meters"] > 0.2 and n > 8:
            ests.append(d["meters"] / n)
    if len(ests) >= 2 or (ests and not any(i["kind"] == "door" for i in items)):
        m = statistics.median(ests)
        spread = (max(ests) - min(ests)) / m if len(ests) > 1 else 0.5
        return {"m_per_px": round(m, 6), "method": "dimension", "confidence": round(0.7 if spread < 0.25 else 0.45, 2),
                "evidence": f"{len(ests)} printed dimension(s) read by the model"}
    widths = [max(i["bbox_px"][2] - i["bbox_px"][0], i["bbox_px"][3] - i["bbox_px"][1]) for i in items if i["kind"] == "door"]
    if widths:
        w = statistics.median(widths)
        return {"m_per_px": round(DOOR_WIDTH_M / w, 6), "method": "door-prior", "confidence": 0.3,
                "evidence": f"median door {w:.0f}px = {DOOR_WIDTH_M} m"}
    return {"m_per_px": None, "method": "none", "confidence": 0.0}


def _derive_walls(items, scale, W, H, VF):
    """The model lists only some wall runs. For the 3D scene, add wall strips along room outlines where no wall box is
    already there. They are labelled source "rule", props.derived = "room-outline", conf 0.25: not seen, inferred."""
    rooms = [i for i in items if i["kind"] == "room"]
    walls = [i for i in items if i["kind"] == "wall"]
    if not rooms or len(walls) >= 2 * len(rooms):
        return items
    mpp = scale.get("m_per_px")
    t = max(3.0, 0.12 / mpp) if mpp else max(3.0, 0.004 * max(W, H))
    new = []
    for r in rooms:
        x0, y0, x1, y1 = r["bbox_px"]
        for b in ([x0 - t / 2, y0 - t / 2, x1 + t / 2, y0 + t / 2], [x0 - t / 2, y1 - t / 2, x1 + t / 2, y1 + t / 2],
                  [x0 - t / 2, y0 - t / 2, x0 + t / 2, y1 + t / 2], [x1 - t / 2, y0 - t / 2, x1 + t / 2, y1 + t / 2]):
            b = [max(0.0, b[0]), max(0.0, b[1]), min(float(W), b[2]), min(float(H), b[3])]
            if b[2] - b[0] > 1 and b[3] - b[1] > 1:
                new.append({"kind": "wall", "label": None, "bbox_px": [round(v, 1) for v in b], "polygon_px": None,
                            "props": {"derived": "room-outline"}, "conf": 0.25, "source": "rule"})
    merged = VF.apply_rules({"image": {"w": W, "h": H}, "items": [dict(i, item_id="x") for i in walls + new]},
                            ["dup"], {"dup_kinds": ["wall"], "dup_iou": 0.2, "dup_contain": 0.5})
    return [i for i in items if i["kind"] != "wall"] + merged


def build(doc_id: str, page: int, W: int, H: int, raw: dict, model: str, ms: float) -> dict:
    sys.path.insert(0, str(REPO / "vision"))
    import verify as VF  # geometry rules only (pure python)
    items = []
    for it in raw.get("items") or []:
        px = _px(it.get("box_2d"), W, H)
        if px is None or it.get("kind") not in KINDS:
            continue
        props = {}
        if it["kind"] == "room":
            props["room_type"] = it.get("room_type") or "other"
            if isinstance(it.get("printed_area_m2"), (int, float)) and it["printed_area_m2"] > 0:
                props["area_m2_label"] = round(float(it["printed_area_m2"]), 2)
        items.append({"kind": it["kind"], "label": (it.get("label") or None), "bbox_px": px, "polygon_px": None,
                      "props": props, "conf": CONF.get(it["kind"], 0.55), "source": "vlm"})
    dims = []
    for d in raw.get("dimensions") or []:
        px = _px(d.get("box_2d"), W, H)
        if px and isinstance(d.get("meters"), (int, float)):
            dims.append({"text": str(d.get("text", ""))[:40], "meters": float(d["meters"]), "px": px})
    rules = ["tiny", "dup"]  # no on_wall: the model lists only some wall runs, so it would drop real doors/windows
    items = VF.apply_rules({"image": {"w": W, "h": H}, "items": [dict(i, item_id="x") for i in items]}, rules)
    scale = _scale(items, dims, W, H)
    if os.environ.get("DERIVE_WALLS", "1") == "1":
        items = _derive_walls(items, scale, W, H, VF)
    if scale["m_per_px"]:
        for i in items:
            if i["kind"] == "room" and "area_m2" not in i["props"]:
                b = i["bbox_px"]
                if i["props"].get("area_m2_label") is None:  # bbox area overstates non-rectangular rooms: label it
                    i["props"]["area_m2_geom_bbox"] = round((b[2] - b[0]) * (b[3] - b[1]) * scale["m_per_px"] ** 2, 2)
    counters, out = {}, []
    for it in sorted(items, key=lambda i: (i["kind"], i["bbox_px"][1], i["bbox_px"][0])):
        counters[it["kind"]] = counters.get(it["kind"], 0) + 1
        it = {k: v for k, v in it.items() if k != "item_id"}
        out.append({"item_id": f"{it['kind']}-{counters[it['kind']]:03d}", **it})
    pm = {"doc_id": doc_id, "page": page, "image": {"w": W, "h": H}, "scale": scale, "items": out,
          "dimension_evidence": [{"text": d["text"], "meters": d["meters"], "bbox_px": d["px"]} for d in dims],
            "provenance": {"models": {"vlm": model}, "rules": rules, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "ms": int(ms), "note": "read by a vision-language model, geometry-checked; boxes are approximate"}}
    from pipeline.sheet_views import annotate_views
    views = []
    for view in raw.get("views") or []:
        px = _px(view.get("box_2d"), W, H)
        if px:
            views.append({"bbox": px, "title": view.get("title") or None, "view_type": view.get("view_type", "unknown"),
                          "printed_scale": view.get("printed_scale") or "", "classification_source": "vlm"})
    labels = [{"text": label.get("text") or "", "bbox_px": _px(label.get("box_2d"), W, H)} for label in raw.get("scale_labels") or []]
    labels = [label for label in labels if label["bbox_px"]]
    pm["printed_scale_labels"] = labels
    return annotate_views(pm, labels, views=views) if views else pm


def validate(pm: dict) -> list[str]:
    from jsonschema import Draft202012Validator
    sch = json.loads((REPO / "vision" / "planmap_schema.json").read_text())
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in Draft202012Validator(sch).iter_errors(pm)][:5]


TILE_FROM = 3000      # px: pages larger than this also get 2x2 tile passes for the small things (doors, windows, fixtures)
TILE_KINDS = ("door", "window", "toilet", "sink", "shower", "bathtub", "stairs", "column")
TILE_NOTE = ("\n\nThis image is ONE TILE of a larger page. Return ONLY items of kind door, window, toilet, sink, shower, "
             "bathtub, stairs, column that are fully or mostly inside the tile (rooms and walls: none; dimensions: []; "
             "is_plan: true only if the tile contains a floor plan; ignore elevation/section symbols even in a mixed tile).")


def _tiles(src: Path, W: int, H: int):
    """2x2 tiles with 8% overlap: [(path, (x0, y0, x1, y1) in page px)]."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(src).convert("RGB")
    out, d = [], Path(tempfile.mkdtemp(prefix="vlmt-"))
    ox, oy = int(W * 0.04), int(H * 0.04)
    for r in range(2):
        for c in range(2):
            box = (max(0, c * W // 2 - ox), max(0, r * H // 2 - oy), min(W, (c + 1) * W // 2 + ox), min(H, (r + 1) * H // 2 + oy))
            t = im.crop(box)
            t.thumbnail((MAX_SIDE, MAX_SIDE))
            p = d / f"t{r}{c}.jpg"
            t.save(p, quality=88)
            out.append((p, box))
    return out


def _read_tiles(src: Path, W: int, H: int):
    """Tile passes in parallel. Returns (items in page 0-1000 coords, cost, ms)."""
    from concurrent.futures import ThreadPoolExecutor
    from engine.models import call

    def one(t):
        p, (x0, y0, x1, y1) = t
        r = call("read_drawing", [{"role": "user", "content": PROMPT + TILE_NOTE}], images=[p], schema=SCHEMA)
        items = []
        for it in (r.json or {}).get("items") or []:
            if it.get("kind") not in TILE_KINDS:
                continue
            try:
                ya, xa, yb, xb = (float(v) for v in it["box_2d"])
            except (KeyError, TypeError, ValueError):
                continue
            f = lambda v, o, n, tot: (o + v / 1000 * n) / tot * 1000  # noqa: E731
            items.append(dict(it, box_2d=[f(ya, y0, y1 - y0, H), f(xa, x0, x1 - x0, W), f(yb, y0, y1 - y0, H), f(xb, x0, x1 - x0, W)]))
        return items, r.cost_usd

    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one, _tiles(src, W, H)))
    return [i for items, _ in res for i in items], sum(c for _, c in res)


def read_page(doc_id: str, page: int, image_path: Path, out_dir: Path) -> dict:
    """Read one page image. Returns {"planmap": dict|None, "is_plan": bool, "cost_usd": float, "model": str}."""
    from engine.models import call
    img, (W, H) = _prep_image(Path(image_path))
    t = time.perf_counter()
    r = call("read_drawing", [{"role": "user", "content": PROMPT}], images=[img], schema=SCHEMA)
    ms = (time.perf_counter() - t) * 1000
    raw = r.json or {}
    cost = r.cost_usd
    if not raw.get("is_plan"):
        # Keep explicit non-plan regions as evidence. Otherwise a later count
        # falls back to reading elevation doors as if they were a floor plan.
        pm = build(doc_id, page, W, H, dict(raw, items=[], dimensions=[]), r.model, ms) if raw.get("views") else None
        if pm is not None:
            (Path(out_dir) / f"planmap-{page}.json").write_text(json.dumps(pm))
        return {"planmap": pm, "is_plan": False, "cost_usd": cost, "model": r.model, "ms": int(ms)}
    if max(W, H) > TILE_FROM:
        tile_items, tcost = _read_tiles(Path(image_path), W, H)
        cost += tcost
        raw = dict(raw, items=[i for i in raw.get("items") or [] if i.get("kind") not in TILE_KINDS] + tile_items)
        ms = (time.perf_counter() - t) * 1000
    pm = build(doc_id, page, W, H, raw, r.model, ms)
    problems = validate(pm)
    if problems:
        raise RuntimeError("plan map invalid: " + "; ".join(problems))
    (Path(out_dir) / f"planmap-{page}.json").write_text(json.dumps(pm))
    words = [{"text": i["label"], "bbox_px": i["bbox_px"]} for i in pm["items"] if i["label"] and i["kind"] == "room"] + pm.get("printed_scale_labels", [])
    return {"planmap": pm, "is_plan": True, "cost_usd": cost, "model": r.model, "ms": int(ms), "words": words}
