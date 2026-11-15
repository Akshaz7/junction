"""Swiss PDF + DXF twin -> YOLO labels (door, window, fixture) on the rendered PDF page.

The PDF is the DXF geometry printed at a fixed scale (1:200 / 1:100 / 1:50), same orientation, plus a frame,
legend and title block. Alignment: rasterise the DXF WALL layer at each candidate scale and find the offset by
FFT cross-correlation with the PDF ink mask; keep the best normalised score. Instances: entities of one layer
whose boxes touch (within 5 cm) are one object.
"""
import math

import numpy as np

CLASSES = ["door", "window", "fixture"]
LAYER_CLS = {"DOOR": 0, "WINDOW": 1, "FIXTURE": 2}
PT_PER_M_1 = 72 / 0.0254  # pt per metre at 1:1
RATIOS = (200, 100, 50, 150, 250)


def _ent_pts(e):
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return [(p[0], p[1]) for p in e.get_points()]
    if t == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    if t in ("CIRCLE", "ARC"):
        c, r = e.dxf.center, e.dxf.radius
        if t == "CIRCLE":
            a0, a1 = 0.0, 360.0
        else:
            a0, a1 = e.dxf.start_angle, e.dxf.end_angle
            if a1 < a0:
                a1 += 360
        n = max(4, int((a1 - a0) / 10))
        return [(c.x + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                 c.y + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    if t == "HATCH":
        out = []
        for p in e.paths:
            if hasattr(p, "vertices"):
                out += [(v[0], v[1]) for v in p.vertices]
            else:
                for ed in getattr(p, "edges", []):
                    for a in ("start", "end"):
                        if hasattr(ed, a):
                            v = getattr(ed, a); out.append((v[0], v[1]))
        return out
    return []


def dxf_objects(path):
    import ezdxf
    d = ezdxf.readfile(path)
    walls, items = [], {k: [] for k in LAYER_CLS}
    for e in d.modelspace():
        lay = e.dxf.layer
        pts = _ent_pts(e)
        if len(pts) < 2:
            continue
        if lay == "WALL":
            walls.append((e.dxftype(), pts))
        elif lay in LAYER_CLS:
            xs, ys = zip(*pts)
            items[lay].append([min(xs), min(ys), max(xs), max(ys)])
    objs = []
    for lay, boxes in items.items():  # union-find on touching boxes
        n = len(boxes); par = list(range(n))

        def f(i):
            while par[i] != i:
                par[i] = par[par[i]]; i = par[i]
            return i
        tol = 0.05
        for i in range(n):
            for j in range(i + 1, n):
                a, b = boxes[i], boxes[j]
                if a[0] - tol <= b[2] and b[0] - tol <= a[2] and a[1] - tol <= b[3] and b[1] - tol <= a[3]:
                    par[f(i)] = f(j)
        g = {}
        for i in range(n):
            r = f(i); bb = g.get(r)
            g[r] = boxes[i] if bb is None else [min(bb[0], boxes[i][0]), min(bb[1], boxes[i][1]),
                                               max(bb[2], boxes[i][2]), max(bb[3], boxes[i][3])]
        objs += [(LAYER_CLS[lay], bb) for bb in g.values()]
    return walls, objs


def _wall_mask(walls, px_per_m, x0, y1, shape):
    from PIL import Image, ImageDraw
    im = Image.new("L", (shape[1], shape[0]), 0); dr = ImageDraw.Draw(im)
    for t, pts in walls:
        p = [((x - x0) * px_per_m, (y1 - y) * px_per_m) for x, y in pts]
        if t == "HATCH" and len(p) >= 3:
            dr.polygon(p, fill=1, outline=1)
        else:
            dr.line(p, fill=1, width=max(1, int(0.05 * px_per_m)))
    return np.asarray(im, np.float32)


def align(pdf_ink, px_per_pt, walls):
    """-> (ratio, px_per_m, ox, oy, score): page px = ((x - x0) * px_per_m + ox, (y1 - y) * px_per_m + oy)."""
    xs = [x for _, pts in walls for x, _ in pts]; ys = [y for _, pts in walls for _, y in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    H, W = pdf_ink.shape
    F = np.fft.rfft2(pdf_ink)
    best = None
    for ratio in RATIOS:
        ppm = PT_PER_M_1 / ratio * px_per_pt
        w, h = int((x1 - x0) * ppm) + 2, int((y1 - y0) * ppm) + 2
        if w >= W or h >= H or w < 20 or h < 20:
            continue
        m = np.zeros((H, W), np.float32)
        m[:h, :w] = _wall_mask(walls, ppm, x0, y1, (h, w))
        c = np.fft.irfft2(F * np.conj(np.fft.rfft2(m)), s=(H, W))
        oy, ox = np.unravel_index(int(np.argmax(c)), c.shape)
        score = float(c[oy, ox]) / max(1.0, float(m.sum()))  # share of wall pixels landing on ink
        if best is None or score > best[4]:
            best = (ratio, ppm, int(ox), int(oy), score, x0, y1)
    return best


PX_PER_M = 40.0  # every page is rendered so 1 m on paper-scale = 40 px (a 0.9 m door is ~36 px)
TILE, STRIDE = 1280, 1024


def dpi_for(ratio, px_per_m=PX_PER_M):
    return px_per_m * ratio * 0.0254


def label_pair(pdf_path, dxf_path, px_per_m=PX_PER_M, min_score=0.45):
    """-> (PIL image at px_per_m, [(cls, x0, y0, x1, y1) px], info) or (None, [], info) when alignment is not trusted."""
    import pypdfium2 as pdfium
    pg = pdfium.PdfDocument(pdf_path)[0]
    sa = 40 / 72  # align at 40 dpi
    ink = (np.asarray(pg.render(scale=sa).to_pil().convert("L"), np.float32) < 235).astype(np.float32)
    walls, objs = dxf_objects(dxf_path)
    if not walls:
        return None, [], {"why": "no WALL layer"}
    a = align(ink, sa, walls)
    if a is None:
        return None, [], {"why": "no scale fits the page"}
    ratio, ppm, ox, oy, score, x0, y1 = a
    info = {"ratio": ratio, "score": round(score, 3), "n_obj": len(objs)}
    if score < min_score:
        info["why"] = f"alignment score {score:.2f} < {min_score}"
        return None, [], info
    s = dpi_for(ratio, px_per_m) / 72
    img = pg.render(scale=s).to_pil().convert("RGB")
    k = s / sa
    ppm, ox, oy = ppm * k, ox * k, oy * k
    W, H = img.size
    out = []
    for c, (bx0, by0, bx1, by1) in objs:
        X0, X1 = (bx0 - x0) * ppm + ox, (bx1 - x0) * ppm + ox
        Y0, Y1 = (y1 - by1) * ppm + oy, (y1 - by0) * ppm + oy
        pad = 1.5
        X0, Y0, X1, Y1 = max(0, X0 - pad), max(0, Y0 - pad), min(W, X1 + pad), min(H, Y1 + pad)
        if X1 - X0 >= 3 and Y1 - Y0 >= 3:
            out.append((c, X0, Y0, X1, Y1))
    return img, out, info


def tiles(img, boxes, keep_empty=0.15, seed=0):
    """Cut TILE x TILE crops (stride STRIDE, white padding at the edge). A box goes to a tile when >= 60 % of its area
    is inside (clipped). Tiles with no box are kept with probability keep_empty. -> [(name_suffix, crop, [(c, x0, y0, x1, y1)])]"""
    import random
    from PIL import Image
    rnd = random.Random(seed)
    W, H = img.size
    xs = list(range(0, max(1, W - TILE) + 1, STRIDE)) or [0]
    ys = list(range(0, max(1, H - TILE) + 1, STRIDE)) or [0]
    if xs[-1] + TILE < W:
        xs.append(W - TILE)
    if ys[-1] + TILE < H:
        ys.append(H - TILE)
    out = []
    for ty in ys:
        for tx in xs:
            tx, ty = max(0, tx), max(0, ty)
            bb = []
            for c, x0, y0, x1, y1 in boxes:
                cx0, cy0, cx1, cy1 = max(x0, tx), max(y0, ty), min(x1, tx + TILE), min(y1, ty + TILE)
                if cx1 <= cx0 or cy1 <= cy0:
                    continue
                if (cx1 - cx0) * (cy1 - cy0) >= 0.6 * (x1 - x0) * (y1 - y0):
                    bb.append((c, cx0 - tx, cy0 - ty, cx1 - tx, cy1 - ty))
            if not bb and rnd.random() > keep_empty:
                continue
            crop = Image.new("RGB", (TILE, TILE), "white")
            crop.paste(img.crop((tx, ty, min(W, tx + TILE), min(H, ty + TILE))), (0, 0))
            out.append((f"_x{tx}_y{ty}", crop, bb))
    return out
