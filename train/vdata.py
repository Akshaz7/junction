"""Shared data layer for V-06 / V-07 (runs on Modal and locally). Reads labels.jsonl written by train/build_v05.py."""
import json, math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

DET_KINDS = ["door", "window", "toilet", "sink", "shower", "bathtub"]
SEG_CLASSES = ["floor", "wall", "door", "window"]


def load_records(root, split, need_seg=False):
    recs = [json.loads(l) for l in open(Path(root) / "labels.jsonl")]
    return [r for r in recs if r["split"] == split and (r["has_seg"] or not need_seg)]


def open_img(root, r):
    return Image.open(Path(root) / r["image"]).convert("RGB")


def augment(img, items, rnd, train=True):
    """rot90 / flip / scale jitter / colour + line-weight jitter / scan noise. Boxes move with the image. items: list of dicts with bbox_px (+polygon_px)."""
    if not train:
        return img, items
    W, H = img.size
    k = rnd.choice([0, 1, 2, 3])
    flip = rnd.random() < 0.5
    def tb(b):
        x0, y0, x1, y1 = b
        if flip:
            x0, x1 = W - x1, W - x0
        return [x0, y0, x1, y1]
    def tp(p):
        return [[W - x if flip else x, y] for x, y in p]
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    out = []
    for it in items:
        j = dict(it); j["bbox_px"] = tb(it["bbox_px"])
        if it.get("polygon_px"):
            j["polygon_px"] = tp(it["polygon_px"])
        out.append(j)
    items = out
    for _ in range(k):  # rotate 90 deg counter-clockwise
        w, h = img.size
        img = img.transpose(Image.ROTATE_90)
        nxt = []
        for it in items:
            x0, y0, x1, y1 = it["bbox_px"]
            j = dict(it); j["bbox_px"] = [y0, w - x1, y1, w - x0]
            if it.get("polygon_px"):
                j["polygon_px"] = [[y, w - x] for x, y in it["polygon_px"]]
            nxt.append(j)
        items = nxt
    img = ImageEnhance.Brightness(img).enhance(rnd.uniform(0.8, 1.2))
    img = ImageEnhance.Contrast(img).enhance(rnd.uniform(0.7, 1.3))
    if rnd.random() < 0.3:
        img = img.filter(ImageFilter.MinFilter(3))  # thicker lines
    if rnd.random() < 0.3:
        img = img.filter(ImageFilter.GaussianBlur(rnd.uniform(0.3, 1.2)))
    if rnd.random() < 0.3:  # scan noise
        import numpy as np
        a = np.asarray(img).astype("float32") + np.random.RandomState(rnd.randrange(1 << 30)).normal(0, rnd.uniform(3, 12), (img.height, img.width, 1))
        img = Image.fromarray(a.clip(0, 255).astype("uint8"))
    return img, items


def seg_mask(size, items):
    """4-class mask (0 floor, 1 wall, 2 door, 3 window); walls from polygons, doors/windows from boxes. Later items overwrite earlier ones."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    order = {"wall": 1, "door": 2, "window": 3}
    for it in sorted([i for i in items if i["kind"] in order], key=lambda i: order[i["kind"]]):
        v = order[it["kind"]]
        if it["kind"] == "wall" and it.get("polygon_px"):
            d.polygon([tuple(p) for p in it["polygon_px"]], fill=v)
        else:
            d.rectangle(it["bbox_px"], fill=v)
    return m


def clip_box(b, W, H):
    x0, y0, x1, y1 = max(0, b[0]), max(0, b[1]), min(W, b[2]), min(H, b[3])
    return [x0, y0, x1, y1] if x1 - x0 >= 2 and y1 - y0 >= 2 else None
