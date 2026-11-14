"""Raster/DXF view scale extraction. Optional image analysis; no model calls.

annotate_planmap(pm, words, image=None, dpi=None, frames=None) -> plan map.
PDF integration may call this hook with pixel-space words and frames; PDF ingest
is deliberately outside this module.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from statistics import median

from engine.scales import (
    box_area,
    contains,
    positive,
    scale_anchors,
    unknown,
    valid_box,
)


def _partitions(image, anchors, width, height):
    """Split only on blank gutters that separate printed scale anchors.

    The minimum gutter is one printed text height. Sampling is bounded; no
    assumption about sheet size, room names, drawing units, or language.
    """
    if image is None or len(anchors) < 2:
        return [[0, 0, width, height]]
    import numpy as np
    from PIL import Image
    gray = image.convert("L") if hasattr(image, "convert") else Image.fromarray(image).convert("L")
    gray.thumbnail((1800, 1800))
    sx, sy = gray.width / width, gray.height / height
    ink = np.asarray(gray) < 200
    font = median(a["bbox"][3] - a["bbox"][1] for a in anchors)
    regions = []

    def split(b, aa, depth=0):
        if len(aa) < 2 or depth >= 12:
            regions.append(b)
            return
        candidates = []
        for axis, factor in ((0, sx), (1, sy)):
            crop = ink[int(b[1] * sy):int(b[3] * sy), int(b[0] * sx):int(b[2] * sx)]
            if not crop.size:
                continue
            crop = crop.copy()
            # Long enclosing frame strokes must not close an otherwise blank
            # gutter. Remove only near-continuous rows/columns, not drawing ink.
            if axis == 0:
                crop[crop.sum(axis=1) >= .9 * crop.shape[1], :] = False
            else:
                crop[:, crop.sum(axis=0) >= .9 * crop.shape[0]] = False
            # A gutter may meet the two strokes of an enclosing sheet frame.
            # Allow only a fraction of one text height of ink along its span.
            blank = crop.sum(axis=0 if axis == 0 else 1) <= max(1, font * factor * .25)
            start = None
            for i, isblank in enumerate([*blank, False]):
                if isblank and start is None:
                    start = i
                if not isblank and start is not None:
                    if i - start >= max(1, font * factor):
                        cut = b[axis] + (start + i) / 2 / factor
                        left = [a for a in aa if a["bbox"][axis + 2] < cut]
                        right = [a for a in aa if a["bbox"][axis] > cut]
                        if left and right and len(left) + len(right) == len(aa):
                            candidates.append(((i - start) / factor, axis, cut, left, right))
                    start = None
        if not candidates:
            regions.append(b)
            return
        _, axis, cut, left, right = max(candidates, key=lambda c: c[0])
        b1, b2 = list(b), list(b)
        b1[axis + 2], b2[axis] = cut, cut
        split(b1, left, depth + 1)
        split(b2, right, depth + 1)
    split([0, 0, width, height], anchors)
    return regions


def _frames(image, anchors, width, height):
    if image is None:
        return []
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    gray = image.convert("L").copy()
    gray.thumbnail((1800, 1800))
    sx, sy = width / gray.width, height / gray.height
    contours, _ = cv2.findContours((np.asarray(gray) < 200).astype("uint8"), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    font = median(a["bbox"][3] - a["bbox"][1] for a in anchors)
    out = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * sx < 12 * font or h * sy < 6 * font:
            continue
        if cv2.contourArea(c) / (w * h) < .94:
            continue
        b = [x * sx, y * sy, (x + w) * sx, (y + h) * sy]
        if (box_area(b) < .95 * width * height and any(contains(b, a["bbox"]) for a in anchors)
                and not any(all(abs(u-v) <= max(sx, sy) * 3 for u, v in zip(b, prior)) for prior in out)):
            out.append(b)
    return out


def annotate_planmap(pm, words, image=None, dpi=None, frames=None):
    out = copy.deepcopy(pm)
    if pm.get("regions"):
        return out
    anchors = scale_anchors(words)
    if not anchors:
        return out
    width, height = pm["image"]["w"], pm["image"]["h"]
    boxes = [list(b) for b in (frames or _frames(image, anchors, width, height)) if valid_box(b)]
    boxes += _partitions(image, anchors, width, height)
    # Smallest physical frame containing each title; otherwise the gutter cell.
    chosen = []
    for a in anchors:
        owners = [b for b in boxes if contains(b, a["bbox"])]
        if owners:
            b = min(owners, key=box_area)
            if b not in chosen:
                chosen.append(b)
    regions = []
    from engine.scale_text import from_ratio, ratio_and_sheet, scalebar
    _, sheet = ratio_and_sheet(words)
    for b in chosen:
        aa = [a for a in anchors if contains(b, a["bbox"]) and not any(contains(sm, a["bbox"]) for sm in chosen if box_area(sm) < box_area(b))]
        if not aa:
            continue
        ratios = {a["ratio"] for a in aa}
        if len(ratios) != 1:
            sc = unknown("Several printed scales share a view with no verified boundary")
        else:
            ratio = aa[0]["ratio"]
            sc = from_ratio(ratio, sheet, width, height, positive(dpi)) or unknown("Printed ratio needs image DPI or a verified whole-sheet paper size")
            local_words = [w for w in words if contains(b, w.get("bbox_px"))]
            bar = scalebar(local_words)
            if bar:
                if sc.get("m_per_px") and abs(sc["m_per_px"] / bar["m_per_px"] - 1) <= .06:
                    sc["confidence"] = .9
                    sc["evidence"] += "; the local scale bar agrees"
                else:
                    sc = bar
            reused_prior = not sc.get("m_per_px") and len(anchors) == 1 and positive((pm.get("scale") or {}).get("m_per_px"))
            if reused_prior:
                sc = copy.deepcopy(pm["scale"])
                sc["evidence"] = str(sc.get("evidence") or "existing scale") + "; printed ratio could not be calibrated"
                sc["unverified_printed_ratio"] = ratio
            else:
                sc.update(ratio=ratio, evidence=f"printed scale 1:{ratio:g}: " + sc["evidence"])
            sc["boxes"] = [a["bbox"] for a in aa]
        regions.append({"bbox": b, "scale": sc, "title": aa[0]["title"] or None})
    if regions:
        out["source_scale"] = copy.deepcopy(pm.get("scale") or {})
        out["regions"] = regions
        out["scale"] = copy.deepcopy(max(regions, key=lambda r: box_area(r["bbox"]))["scale"])
    return out


def annotate_cached(pm, directory, allow_ocr=False):
    """Read cached OCR and page metadata. Never writes shared source artifacts."""
    d = Path(directory)
    if any(i.get("source") in ("dxf", "ifc") for i in pm.get("items", [])):
        return copy.deepcopy(pm)
    page = pm.get("page", 1)
    words, dpi, model_text = [], None, False
    for name in (f"text-{page}.json", f"rtext-{page}.json", f"scale-ocr-{page}.json"):
        try:
            data = json.loads((d / name).read_text())
            if isinstance(data, dict) and data.get("image") and data["image"] != pm.get("image"):
                continue
            words.extend(data if isinstance(data, list) else data.get("words", []))
            dpi = dpi or (data.get("dpi") if isinstance(data, dict) else None)
            model_text = model_text or isinstance(data, dict) and data.get("source") == "vlm"
        except (OSError, ValueError, TypeError):
            pass
    try:
        from PIL import Image
        with Image.open(d / f"page-{page}.png") as im:
            # Pixel-space DPI only: never use a pre-resize DPI from an original.
            dd = im.info.get("dpi")
            if dd and positive(dd[0]) and positive(dd[1]) and abs(dd[0] / dd[1] - 1) < .01:
                dpi = dpi or positive(dd[0])
            # VLM room labels are not an OCR pass. They used to prevent OCR,
            # hiding printed scales on precisely the scanned upload path.
            if allow_ocr and (model_text or not scale_anchors(words)) and not (d / f"scale-ocr-{page}.json").exists():
                try:
                    from engine.reader.text import ocr_words
                    extra = ocr_words(d / f"page-{page}.png")
                except (ImportError, OSError):
                    extra = None
                if extra is not None:
                    words.extend(extra)
                    (d / f"scale-ocr-{page}.json").write_text(json.dumps({"image": pm["image"], "words": extra}))
            from pipeline.sheet_views import annotate_views
            annotated = annotate_planmap(pm, words, im, dpi)
            # Revisit model view boxes with real OCR/DPI rather than letting a
            # previously stored annotation prevent scale recovery.
            if annotated.get("view_analysis"):
                annotated.pop("view_analysis")
            return annotate_views(annotated, words, im, dpi)
    except (OSError, ImportError):
        from pipeline.sheet_views import annotate_views
        return annotate_views(annotate_planmap(pm, words, dpi=dpi), words, dpi=dpi)


def annotate_document(directory, page):
    """Upload hook; returns without touching PDF/IFC or already annotated maps."""
    d = Path(directory)
    meta = json.loads((d / "doc.json").read_text())
    if meta.get("kind") not in ("raster", "dxf", "dwg"):
        return
    path = d / f"planmap-{page}.json"
    pm = json.loads(path.read_text())
    annotated = annotate_cached(pm, d, allow_ocr=True)
    if annotated != pm:
        path.write_text(json.dumps(annotated))


def region_map(directory, page):
    """Read a page for measurement tools; PDFs keep their existing ingest path."""
    d = Path(directory)
    try:
        pm = json.loads((d / f"planmap-{page}.json").read_text())
        meta = json.loads((d / "doc.json").read_text()) if (d / "doc.json").exists() else {}
        return annotate_cached(pm, d) if meta.get("kind") in ("raster", "dxf", "dwg") else pm
    except (OSError, ValueError):
        return {}


def dxf_regions(doc, transform, layout=None):
    """Regions in the rendered coordinate system, never mix model/paper space.

    `transform` maps the chosen layout as px=a*x+bx, py=-a*y+by.
    The current renderer uses modelspace. A paper-space renderer can supply its
    own layout to this same hook; viewports then use view_height/paper_height.
    """
    from ezdxf import bbox, units
    a = positive(abs(transform.get("a", 0)))
    if not a:
        return []
    layout = doc.modelspace() if layout is None else layout
    def metres(code):
        try:
            return units.conversion_factor(int(code), 6) if code else None
        except (TypeError, ValueError, IndexError):
            return None
    unit = metres(doc.header.get("$INSUNITS", 0))
    regions = []
    def pixel_box(x0, y0, x1, y1):
        return [a*x0 + transform["bx"], -a*y1 + transform["by"], a*x1 + transform["bx"], -a*y0 + transform["by"]]
    if layout.name != "Model":
        # PlotPaperUnits: 0 inches, 1 millimetres. Unknown stays unknown.
        paper_code = layout.dxf_layout.dxf.get("plot_paper_units", 1)
        paper_m = {0: .0254, 1: .001}.get(paper_code)
        for vp in layout.query("VIEWPORT"):
            if vp.dxf.id <= 1 or vp.dxf.status <= 0:
                continue
            w, h, vh = positive(vp.dxf.width), positive(vp.dxf.height), positive(vp.dxf.view_height)
            if not w or not h or not vh:
                continue
            cx, cy = vp.dxf.center.x, vp.dxf.center.y
            sc = unknown("Viewport units, clipping or projection cannot be verified")
            direction = vp.dxf.view_direction_vector
            if unit and abs(direction.x) < 1e-9 and abs(direction.y) < 1e-9 and not (vp.dxf.flags & (1 | 65536)):
                sc = {"m_per_px": unit * vh / (a*h), "method": "dxf-units", "confidence": 1.0,
                      "evidence": "CAD viewport model height divided by its rendered paper height"}
                if paper_m:
                    sc["ratio"] = unit * vh / (paper_m * h)
            regions.append({"bbox": pixel_box(cx-w/2, cy-h/2, cx+w/2, cy+h/2), "title": "CAD viewport", "scale": sc})
        return regions
    for insert in layout.query("INSERT"):
        try:
            ext = bbox.extents([insert])
            if not ext.has_data:
                continue
            block = doc.blocks.get(insert.dxf.name)
            block_unit = metres(block.block_record.dxf.get("units", 0)) or unit
            xs, ys = abs(insert.dxf.xscale), abs(insert.dxf.yscale)
            if not block_unit or not positive(xs) or not positive(ys):
                sc = unknown("CAD block units or insertion scale are missing")
            elif abs(xs / ys - 1) > 1e-6:
                sc = unknown("CAD block is stretched differently along each axis")
            else:
                sc = {"m_per_px": block_unit / (a * xs), "method": "dxf-units", "confidence": 1.0,
                      "evidence": "CAD block units and uniform insertion transform"}
            b = pixel_box(ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)
            if valid_box(b):
                regions.append({"bbox": b, "title": "CAD detail", "scale": sc})
        except (ValueError, AttributeError, KeyError, ZeroDivisionError):
            continue
    return regions
