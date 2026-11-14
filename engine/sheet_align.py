"""Sheet registration, in page-image pixels. No PDF ingest or model calls.

The matrix maps OVERLAY pixels to BASE pixels. ``load_pdf_page`` is the small
fallback adapter for pdf_vector.load_page: image size, words with bbox_px and
optional paths. Only text and long grid lines are used; never the full paths.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

import numpy as np

VERSION = 2


def _normal(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", str(text)).upper()))


def _labels(sheet):
    labels = defaultdict(list)
    for word in sheet.get("words", []):
        box = word.get("bbox_px")
        text = _normal(word.get("text", word.get("label", "")))
        if not text or not box or len(box) != 4 or not np.isfinite(box).all():
            continue
        # Pure dimensions and repeated generic words cannot independently anchor a sheet.
        if len(text) > 100:
            continue
        point = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        if point not in labels[text]:
            labels[text].append(point)
    return labels


def _grid_labels(sheet, labels):
    """Intersections of labelled, long horizontal/vertical grid lines.

    Input grid_lines: [[x0,y0,x1,y1], ...]. Do not infer grid order from page
    bounds: title blocks and margins often differ between disciplines.
    """
    w, h = sheet["image"]["w"], sheet["image"]["h"]
    axes = {"x": {}, "y": {}}
    for text, points in labels.items():
        if not re.fullmatch(r"(?:[A-ZÅÄÖ]{1,2}|\d{1,2})", text):
            continue
        for x, y in points:
            for x0, y0, x1, y1 in sheet.get("grid_lines", []):
                if abs(x1-x0) < w*.003 and abs(y1-y0) > h*.25 and abs(x-(x0+x1)/2) < w*.005:
                    axes["x"][text] = (x0+x1)/2
                if abs(y1-y0) < h*.003 and abs(x1-x0) > w*.25 and abs(y-(y0+y1)/2) < h*.005:
                    axes["y"][text] = (y0+y1)/2
    return {f"grid:{x}/{y}": [(vx, vy)] for x, vx in axes["x"].items() for y, vy in axes["y"].items()}


def raster_grid_lines(image_path):
    """Bounded raster fallback; detects long grid lines on at most 1600 px."""
    import cv2
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return []
    scale = min(1., 1600 / max(image.shape))
    image = cv2.resize(image, None, fx=scale, fy=scale)
    lines = cv2.HoughLinesP(cv2.Canny(image, 80, 160), 1, np.pi/1800,
                            threshold=80, minLineLength=min(image.shape)*.25, maxLineGap=12)
    return [] if lines is None else (lines[:500, 0, :] / scale).tolist()


def _failure(detail, candidates=0):
    return {"status": "needs_manual", "matrix": None, "method": None,
            "anchor_count": 0, "candidate_count": candidates, "residual_px": None,
            "residual_mm": None, "detail": detail, "anchors": []}


def _fit(src, dst, affine=False):
    if affine:
        design = np.column_stack((src, np.ones(len(src))))
        if np.linalg.matrix_rank(design) < 3:
            return None
        return np.linalg.lstsq(design, dst, rcond=None)[0].T
    # Similarity [a -b tx; b a ty], no reflections.
    x, y = src.T
    design = np.zeros((len(src)*2, 4))
    design[::2] = np.column_stack((x, -y, np.ones(len(x)), np.zeros(len(x))))
    design[1::2] = np.column_stack((y, x, np.zeros(len(x)), np.ones(len(x))))
    if np.linalg.matrix_rank(design) < 4:
        return None
    a, b, tx, ty = np.linalg.lstsq(design, dst.reshape(-1), rcond=None)[0]
    return np.array([[a, -b, tx], [b, a, ty]])


def _transform(points, matrix):
    return np.asarray(points) @ matrix[:, :2].T + matrix[:, 2]


def manual_alignment(base_points, overlay_points, *, m_per_px=None):
    """Two corresponding grid crossings, in click order. No accuracy claim."""
    dst, src = np.asarray(base_points, dtype=float), np.asarray(overlay_points, dtype=float)
    if dst.shape != (2, 2) or src.shape != (2, 2) or not np.isfinite([dst, src]).all():
        raise ValueError("Choose two points on each sheet.")
    if min(np.linalg.norm(dst[1]-dst[0]), np.linalg.norm(src[1]-src[0])) < 1:
        raise ValueError("Choose two different grid crossings, at least one pixel apart.")
    matrix = _fit(src, dst)
    return {"status": "manual", "matrix": matrix.tolist(), "method": "two-point",
            "anchor_count": 2, "candidate_count": 2, "residual_px": None, "residual_mm": None,
            "detail": "Manually aligned on 2 points. Check a third crossing before relying on it.",
            "anchors": [{"base": a, "overlay": b, "label": str(i+1)}
                        for i, (a, b) in enumerate(zip(dst.tolist(), src.tolist()))]}


def _align_labels(base, overlay, *, m_per_px=None, model="similarity", tolerance_px=None):
    """Robust shared-label fit; scale is metres in the building per BASE pixel.

    RANSAC rejects annotations/title blocks that moved separately. Repeated
    labels are admitted only after a unique-label consensus seeds the fit.
    Affine is opt-in for stretched scans. An unscaled residual stays in pixels.
    """
    if model not in {"similarity", "affine"}:
        raise ValueError("model must be similarity or affine")
    for sheet in (base, overlay):
        size = sheet.get("image", {})
        if not all(isinstance(size.get(k), (int, float)) and math.isfinite(size[k]) and size[k] > 0 for k in ("w", "h")):
            return _failure("Page image dimensions are missing.")
    a, b = _labels(base), _labels(overlay)
    a.update(_grid_labels(base, a)); b.update(_grid_labels(overlay, b))
    pairs = [(text, a[text][0], b[text][0]) for text in sorted(a.keys() & b.keys())
             if len(a[text]) == len(b[text]) == 1]
    minimum = 4 if model == "affine" else 3
    if len(pairs) < minimum:
        return _failure("Too few shared labels. Choose the same two grid crossings on both sheets.", len(pairs))
    # Two typographic pixels at 72 dpi, scaled with the raster. Avoid file-specific thresholds.
    tol = float(tolerance_px or max(2., min(base["image"][k] for k in ("w", "h")) * .002))
    dst = np.array([p[1] for p in pairs]); src = np.array([p[2] for p in pairs])
    n = len(src); sample_size = 3 if model == "affine" else 2
    rng = np.random.default_rng(0)
    best = np.zeros(n, dtype=bool)
    for _ in range(min(1200, max(100, n*12))):
        sample = rng.choice(n, sample_size, replace=False)
        matrix = _fit(src[sample], dst[sample], model == "affine")
        if matrix is None or np.linalg.det(matrix[:, :2]) <= 0:
            continue
        good = np.linalg.norm(_transform(src, matrix)-dst, axis=1) <= tol
        if good.sum() > best.sum():
            best = good
    if best.sum() < minimum:
        return _failure("Shared labels do not agree on an alignment. Use two grid crossings.", n)
    matrix = _fit(src[best], dst[best], model == "affine")
    # Recover repeated room/grid labels by proximity to the established transform.
    extra = []
    for text in sorted(a.keys() & b.keys()):
        if len(a[text]) == len(b[text]) == 1 or len(a[text])*len(b[text]) > 2500:
            continue
        used = set()
        for q in b[text]:
            distances = np.linalg.norm(np.array(a[text])-_transform([q], matrix)[0], axis=1)
            order = np.argsort(distances)
            i = int(order[0])
            if i not in used and distances[i] <= tol and (len(order) < 2 or distances[order[1]] > tol):
                extra.append((text, a[text][i], q)); used.add(i)
    accepted = [p for p, good in zip(pairs, best) if good] + extra
    dst = np.array([p[1] for p in accepted]); src = np.array([p[2] for p in accepted])
    matrix = _fit(src, dst, model == "affine")
    # Require support in two dimensions: title-block-only/one row fits are unsafe.
    spread = np.ptp(dst, axis=0) / [base["image"]["w"], base["image"]["h"]]
    if min(spread) < .08 or np.linalg.svd(dst-dst.mean(0), compute_uv=False)[-1] < tol:
        return _failure("Shared labels cover too little of the drawing. Use two distant grid crossings.", n)
    residual = float(np.sqrt(np.mean(np.sum((_transform(src, matrix)-dst)**2, axis=1))))
    scale = m_per_px if m_per_px is not None else base.get("m_per_px")
    mm = residual*scale*1000 if isinstance(scale, (int, float)) and math.isfinite(scale) and scale > 0 else None
    count = len(accepted)
    return {"status": "aligned", "matrix": matrix.tolist(), "method": model,
            "anchor_count": count, "candidate_count": n+len(extra), "residual_px": residual,
            "residual_mm": mm, "detail": f"Aligned on {count} shared labels, " +
            (f"± {mm:.1f} mm" if mm is not None else f"± {residual:.1f} px · drawing scale unavailable"),
            "anchors": [{"label": p[0], "base": list(p[1]), "overlay": list(p[2])} for p in accepted]}


@lru_cache(maxsize=32)
def _pdf_text(path, page, width, height, stamp):
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextLine
    layout = next(extract_pages(path, page_numbers=[page-1]))
    sx, sy = width/layout.width, height/layout.height
    words = []

    def walk(node):
        if isinstance(node, LTTextLine):
            # Lines plus individual tokens: room IDs survive differences in wrapping.
            chars = list(node)
            groups, group = [], []
            for char in chars:
                if not hasattr(char, "bbox") or not char.get_text().strip():
                    if group: groups.append(group); group = []
                else:
                    group.append(char)
            if group: groups.append(group)
            if len(groups) > 1:
                groups.append([c for c in chars if hasattr(c, "bbox")])
            for g in groups:
                x0, y0 = min(c.x0 for c in g), min(c.y0 for c in g)
                x1, y1 = max(c.x1 for c in g), max(c.y1 for c in g)
                words.append({"text": "".join(c.get_text() for c in g).strip(),
                              "bbox_px": [x0*sx, (layout.height-y1)*sy, x1*sx, (layout.height-y0)*sy]})
        elif hasattr(node, "__iter__"):
            for child in node:
                walk(child)
    walk(layout)
    sheet = {"image": {"w": width, "h": height}, "words": words, "paths": []}
    ratios = {float(m) for word in words for m in re.findall(r"(?<!\d)1\s*:\s*(\d+(?:\.\d+)?)(?!\d)", word["text"])
              if 5 <= float(m) <= 10000}
    if len(ratios) == 1:
        sheet["m_per_px"] = layout.width / 72 * .0254 / width * next(iter(ratios))
    return sheet


def load_pdf_page(path, page=1, image_size=None):
    """Fallback adapter. Replace this call with Awais's loader when it lands.

    page is contract 1-based. Rotation/crop are handled by pdfminer layout;
    image_size must be the actual page PNG dimensions, never a guessed DPI.
    """
    path = Path(path)
    if image_size is None:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(path) as doc:
            p = doc[page-1]
            image_size = tuple(round(x) for x in p.get_size())
            p.close()
    return _pdf_text(str(path.resolve()), page, *image_size, path.stat().st_mtime_ns)


def cached_alignment(base, overlay, *, cache_dir=None, **options):
    """Content-keyed cache; changed OCR, dimensions, scale or options invalidate it."""
    payload = json.dumps([VERSION, base, overlay, options], sort_keys=True, allow_nan=False)
    key = hashlib.sha256(payload.encode()).hexdigest()
    if cache_dir is None:
        return json.loads(_cached_json(payload))
    path = Path(cache_dir) / f"{key}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        result = align_sheets(base, overlay, **options)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temporary name avoids simultaneous requests racing over one temp file.
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            json.dump(result, f); temporary = Path(f.name)
        temporary.replace(path)
        return result


@lru_cache(maxsize=128)
def _cached_json(payload):
    _, base, overlay, options = json.loads(payload)
    return json.dumps(align_sheets(base, overlay, **options))


def provider_alignment(src_page, dst_page, *, aligner=None, m_per_px=None):
    """Awais adapter: pdf_mep.align(src_page, dst_page) -> T, residual, matches.

    The provider's page objects must already use the actual page-image pixels.
    Residual is treated as pixels; millimetres require a trusted destination scale.
    No vector traversal here. Call only on cached, loaded provider pages.
    """
    if aligner is None:
        from pipeline.pdf_mep import align as aligner
    raw = aligner(src_page, dst_page)
    matrix = np.asarray(raw.get("T"), dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or not np.allclose(matrix[2], [0, 0, 1]):
        return _failure("The PDF alignment provider returned no usable transform.")
    matches = raw.get("matches", [])
    count = matches if isinstance(matches, int) else len(matches)
    residual = raw.get("residual")
    if count < 3 or residual is None or not math.isfinite(residual) or residual < 0:
        return _failure("Too few reliable PDF anchors. Use two grid crossings.")
    mm = residual * m_per_px * 1000 if m_per_px and m_per_px > 0 else None
    return {"status": "aligned", "matrix": matrix[:2].tolist(), "method": "pdf-mep",
            "anchor_count": count, "candidate_count": count, "residual_px": residual,
            "residual_mm": mm, "anchors": [], "detail": f"Aligned on {count} shared anchors, " +
            (f"± {mm:.1f} mm" if mm is not None else f"± {residual:.1f} px · drawing scale unavailable")}


def _raster_alignment(base, overlay, m_per_px=None):
    """Bounded, reciprocal feature fit for rasters without positioned text.

    Features are geometric evidence, not shared-label claims. A minimum of 12
    distributed inliers and 35% consensus rejects unrelated/ambiguous sheets.
    """
    import cv2

    def features(sheet):
        image = cv2.imread(str(sheet["image_path"]), cv2.IMREAD_GRAYSCALE)
        if image is None:
            return [], None, 1
        factor = min(1., 1800 / max(image.shape))
        image = cv2.resize(image, None, fx=factor, fy=factor)
        points, desc = cv2.ORB_create(nfeatures=3500).detectAndCompute(image, None)
        return points, desc, factor

    a, da, sa = features(base); b, db, sb = features(overlay)
    if da is None or db is None:
        return _failure("No reliable shared drawing features. Use two grid crossings.")
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    forward = {m.queryIdx: m.trainIdx for pair in matcher.knnMatch(db, da, k=2)
               if len(pair) == 2 for m, n in [pair] if m.distance < .7*n.distance}
    reverse = {m.queryIdx: m.trainIdx for pair in matcher.knnMatch(da, db, k=2)
               if len(pair) == 2 for m, n in [pair] if m.distance < .7*n.distance}
    pairs = [(i, j) for i, j in forward.items() if reverse.get(j) == i]
    if len(pairs) < 12:
        return _failure("Too few shared drawing features. Use two grid crossings.", len(pairs))
    src = np.array([b[i].pt for i, _ in pairs], dtype=float) / sb
    dst = np.array([a[j].pt for _, j in pairs], dtype=float) / sa
    tol = 3 / sa  # three pixels on the bounded working raster, not a building-size assumption
    matrix, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=tol, maxIters=2000)
    if matrix is None:
        return _failure("Drawing features do not agree. Use two grid crossings.", len(pairs))
    good = mask.ravel().astype(bool)
    spread = np.ptp(dst[good], axis=0) / [base["image"]["w"], base["image"]["h"]]
    if good.sum() < 12 or good.mean() < .35 or min(spread) < .15:
        return _failure("Shared features cover too little of the drawing. Use two grid crossings.", len(pairs))
    residual = float(np.sqrt(np.mean(np.sum((_transform(src[good], matrix)-dst[good])**2, axis=1))))
    scale = m_per_px or base.get("m_per_px")
    mm = residual*scale*1000 if scale and math.isfinite(scale) and scale > 0 else None
    count = int(good.sum())
    return {"status": "aligned", "matrix": matrix.tolist(), "method": "raster-features",
            "anchor_count": count, "candidate_count": len(pairs), "residual_px": residual, "residual_mm": mm,
            "detail": f"Aligned on {count} shared drawing features, " +
            (f"± {mm:.1f} mm" if mm is not None else f"± {residual:.1f} px · drawing scale unavailable"),
            "anchors": [{"label": str(k+1), "base": p.tolist(), "overlay": q.tolist()}
                        for k, (p, q) in enumerate(zip(dst[good], src[good]))]}


def align_sheets(base, overlay, *, m_per_px=None, model="similarity", tolerance_px=None):
    result = _align_labels(base, overlay, m_per_px=m_per_px, model=model, tolerance_px=tolerance_px)
    if result["status"] == "needs_manual" and all(sheet.get("image_path") for sheet in (base, overlay)):
        try:
            return _raster_alignment(base, overlay, m_per_px)
        except (ImportError, OSError, ValueError):
            pass  # OCR-only deployments still support manual alignment.
    return result
