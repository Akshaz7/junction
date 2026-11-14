"""V-10: read a plumbing sheet (raster page image) with a vision model and return plan-map-style items. Ready to wire (ENGINE-FIX).

  from vision.piping_read import read_piping
  items, cost = read_piping(page_png, legend_png=None, tiles=(3, 2))

Items follow CONTRACT planmap items: {item_id, kind, label, bbox_px [x0,y0,x1,y1] in PAGE pixels of page_png, polygon_px None, props, conf, source}.
source is "vlm" (the contract enum; "model" is not allowed by the planmap schema); props.model + props.note carry the honesty label.
kinds: "pipe_label" (props.size_in, props.text, props.system = vent when the printed text says V/VENT/VTR else "pipe"), "fixture" (props.tag, props.fixture_type), "drain" (props.drain_kind).
Cost about $0.015 per tile call; all calls go through engine.models.call(). Never raises: returns ([], cost) on any model error.
NEEDS (ENGINE-FIX owns engine/models/models.yaml). Add this task, nothing else is required:
  read_piping:   # plumbing sheet reader (vision/piping_read.py). Gemini 4 Carbon read P1.02 label/tag counts exactly (results/vision/piping/v10)
    provider: runware_oai
    model: gemini-4-carbon
    max_tokens: 4000
    temperature: 0
    fallback:
      - {provider: runware_claude, model: claude-opus-5-5}
Until it exists, this module pins runware_oai/gemini-4-carbon on the read_drawing task.
"""
import json, re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NOTE = "Read by a model from the sheet, not measured"
BOX = {"type": "array", "items": {"type": "integer"}}
SCHEMA = {"type": "object", "properties": {
    "pipe_labels": {"type": "array", "items": {"type": "object", "properties": {"size": {"type": "string"}, "text": {"type": "string"}, "box": BOX}}},
    "fixtures": {"type": "array", "items": {"type": "object", "properties": {"tag": {"type": "string"}, "type": {"type": "string"}, "box": BOX}}},
    "drains": {"type": "array", "items": {"type": "object", "properties": {"kind": {"type": "string"}, "box": BOX}}}}}
PROMPT = """%s Read the plan image only. It may show only part of a sheet, or no plumbing at all: if nothing plumbing is drawn, return empty lists. List, each with a bounding box [ymin,xmin,ymax,xmax] on a 0-1000 grid of the plan image:
- pipe_labels: every pipe size annotation printed on a pipe run (e.g. 2"o, 3"o, 1 1/2"o) and every vent callout (e.g. 3"VENT UP, 3"V DN, 3"VTR); text = exactly what is printed, size = the diameter in inches as printed.
- fixtures: every plumbing fixture TAG box (LAV-1, WC-1, SH-1, KS-1 ...); type = lavatory, water closet, shower, kitchen sink, other.
- drains: ONLY floor-drain or shower-drain symbols drawn inside a fixture (the circle or square at the middle of a shower pan or in a floor). The small circle where a pipe run ends or turns is a pipe end, NOT a drain: never list it. One drain per shower.
Do not invent items that are not drawn. Return JSON only."""
LEGEND_LEAD = "Image 1 is the piping legend (line types, abbreviations) of this drawing set. Image 2 is the plan image."
NOLEG_LEAD = "The image is a plan image from a plumbing drawing set."


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u else 0.0


def _tiles(w, h, grid, ov=0.12):
    nx, ny = grid
    tw, th = w / nx, h / ny
    return [(int(max(0, i * tw - ov * tw)), int(max(0, j * th - ov * th)), int(min(w, (i + 1) * tw + ov * tw)), int(min(h, (j + 1) * th + ov * th))) for j in range(ny) for i in range(nx)]


def _call(images, lead, model):
    from engine.models import call
    from engine.models.core import config
    task = "read_piping" if "read_piping" in config()["tasks"] else "read_drawing"
    pin = None if task == "read_piping" else model
    return call(task, [{"role": "user", "content": PROMPT % lead}], images=images, schema=SCHEMA, only=pin)


def read_piping(page_png, legend_png=None, tiles=(1, 1), crop=None, model=("runware_oai", "gemini-4-carbon")):
    """crop: optional [x0,y0,x1,y1] page px region to read (the plan area). tiles: grid inside the crop."""
    from PIL import Image
    im = Image.open(page_png).convert("RGB"); W, H = im.size
    cx0, cy0, cx1, cy1 = crop or (0, 0, W, H)
    cost = 0.0; raw = []
    for (a, b, c, d) in _tiles(cx1 - cx0, cy1 - cy0, tiles):
        box = (cx0 + a, cy0 + b, cx0 + c, cy0 + d)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "tile.png"; im.crop(box).save(p)
            try:
                r = _call(([legend_png] if legend_png else []) + [p], LEGEND_LEAD if legend_png else NOLEG_LEAD, model)
            except Exception:  # noqa: BLE001  budget, network, no key: nothing is added, caller keeps whatever else it has
                continue
        cost += r.cost_usd or 0.0
        j = r.json if isinstance(r.json, dict) else {}
        tw, th = box[2] - box[0], box[3] - box[1]
        for kind, key in (("pipe_label", "pipe_labels"), ("fixture", "fixtures"), ("drain", "drains")):
            for it in j.get(key, []) or []:
                bb = it.get("box") or []
                if len(bb) != 4:
                    continue
                y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) for v in bb]
                if x1 <= x0 or y1 <= y0:
                    continue
                raw.append((kind, it, [box[0] + x0 * tw / 1000, box[1] + y0 * th / 1000, box[0] + x1 * tw / 1000, box[1] + y1 * th / 1000], r.model))
    items, n = [], {}
    for kind, it, bb, model_id in raw:
        txt = (it.get("text") or it.get("tag") or it.get("kind") or "").strip()
        if any(k == kind and _iou(bb, b2) > 0.3 for k, _, b2, _m in [(x["kind"], 0, x["bbox_px"], 0) for x in items]):
            continue  # same thing seen in two overlapping tiles
        n[kind] = n.get(kind, 0) + 1
        props = {"model": model_id, "note": NOTE}
        if kind == "pipe_label":
            props.update(text=txt, size_in=it.get("size") or None, system="vent" if re.search(r"vent|\bV\b|V UP|V DN|VTR", txt, re.I) else "pipe")
        elif kind == "fixture":
            props.update(tag=txt.upper(), fixture_type=it.get("type"))
        else:
            props.update(drain_kind=it.get("kind"))
        items.append({"item_id": f"pipe-{kind.replace('_', '')}-{n[kind]:03d}", "kind": kind, "label": txt or None, "bbox_px": [int(v) for v in bb], "polygon_px": None, "props": props, "conf": None, "source": "vlm"})
    return items, cost
