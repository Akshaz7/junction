"""Spatial scales for independent views on a sheet. No OCR, models, or file I/O.

Only a containing region may lend its scale to an item. A box crossing views,
an uncalibrated detail, or conflicting labels never inherits the main scale.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction


def positive(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError):
        return None


def valid_box(b):
    try:
        return len(b) == 4 and all(math.isfinite(float(v)) for v in b) and b[2] > b[0] and b[3] > b[1]
    except (TypeError, ValueError):
        return False


def contains(outer, inner):
    return valid_box(outer) and valid_box(inner) and outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def box_area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


METRIC = re.compile(r"(?<![\d.])1\s*:\s*(\d+(?:[.,]\d+)?)(?!\d)")
IMPERIAL = re.compile(r'''(\d+(?:\s+\d+)?(?:\s*/\s*\d+)?)\s*["”″]\s*=\s*(\d+(?:\.\d+)?)\s*['’′](?:\s*-\s*(\d+(?:\.\d+)?)\s*["”″]?)?''')


def _ratio(text):
    # Imperial first: the fraction in 1/4" must not become a metric ratio.
    m = IMPERIAL.search(text)
    if m:
        try:
            inch = sum(float(Fraction(p)) for p in re.sub(r"\s*/\s*", "/", m[1]).split())
            return ((float(m[2]) * 12 + float(m[3] or 0)) / inch, m.span()) if inch > 0 else (None, None)
        except (ValueError, ZeroDivisionError):
            return None, None
    m = METRIC.search(text)
    if m:
        return positive(m[1].replace(",", ".")), m.span()
    return None, None


def scale_anchors(words):
    """Read spatial lines, including split `M 1 : 50` and imperial labels.

    Never concatenate words on separate lines or distant view titles.
    """
    rows = []
    seen = set()
    for w in sorted((w for w in words if valid_box(w.get("bbox_px"))), key=lambda w: (w["bbox_px"][1], w["bbox_px"][0])):
        b = w["bbox_px"]
        key = (str(w.get("text")), tuple(b))
        if key in seen:
            continue
        seen.add(key)
        cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
        row = next((r for r in rows if abs(r[0] - cy) <= min(r[1], h) * .5), None)
        if row is None:
            rows.append([cy, h, [w]])
        else:
            row[2].append(w)
    anchors = []
    for _, h, ws in rows:
        groups = [[]]
        for w in sorted(ws, key=lambda w: w["bbox_px"][0]):
            if groups[-1] and w["bbox_px"][0] - groups[-1][-1]["bbox_px"][2] > 4 * h:
                groups.append([])
            groups[-1].append(w)
        for group in groups:
            text = " ".join(str(w.get("text") or "") for w in group)
            ratio, span = _ratio(text)
            if not ratio:
                continue
            # Several labels in one OCR line are ambiguous; do not pick the first.
            imperial = list(IMPERIAL.finditer(text))
            ratios = [_ratio(m[0])[0] for m in imperial]
            ratios += [float(m[1].replace(",", ".")) for m in METRIC.finditer(text)
                       if not any(im.start() <= m.start() < im.end() for im in imperial)]
            if len(set(ratios)) > 1:
                for rr in set(ratios):
                    anchors.append({"bbox": _union([w["bbox_px"] for w in group]), "ratio": rr, "title": None, "quote": text})
                continue
            title = text[:span[0]].strip(" :=-;")
            title = re.sub(r"\b(?:scale|maßstab|massstab|mittakaava|skala|m)\s*$", "", title, flags=re.IGNORECASE).strip(" :=-;")
            b = _union([w["bbox_px"] for w in group])
            if not title:
                above = [(b[1] - r[2][0]["bbox_px"][3], r) for r in rows if r[0] < b[1] and 0 <= b[1] - r[2][0]["bbox_px"][3] <= 3 * h
                         and any(w["bbox_px"][0] < b[2] and w["bbox_px"][2] > b[0] for w in r[2])]
                if above:
                    nearby = min(above, key=lambda p: p[0])[1][2]
                    title = " ".join(str(w.get("text") or "") for w in sorted(nearby, key=lambda w: w["bbox_px"][0]) if w["bbox_px"][0] < b[2] + 4 * h and w["bbox_px"][2] > b[0] - 4 * h)
                    if _ratio(title)[0]:
                        title = ""
            anchors.append({"bbox": b, "ratio": ratio, "title": title, "quote": text})
    return anchors


def unknown(evidence):
    return {"m_per_px": None, "method": "none", "confidence": 0.0, "evidence": evidence}


def region_scale(pm, bbox):
    """Full-box containment; nested detail frames win over enclosing views."""
    regions = pm.get("regions") or []
    if not regions:
        return pm.get("scale") or unknown("No scale supplied"), None
    owners = [r for r in regions if contains(r.get("bbox"), bbox)]
    if not owners:
        return unknown("Item crosses view boundaries or has no containing scaled view"), None
    owner = min(owners, key=lambda r: box_area(r["bbox"]))
    # An item containing part of a nested detail cannot use the enclosing view.
    for r in regions:
        b = r.get("bbox")
        if r is owner or not valid_box(b) or box_area(b) >= box_area(owner["bbox"]):
            continue
        if min(b[2], bbox[2]) > max(b[0], bbox[0]) and min(b[3], bbox[3]) > max(b[1], bbox[1]):
            return unknown("Item overlaps a nested detail view"), None
    return owner.get("scale") or unknown("View scale is missing"), owner


def points_scale(pm, points):
    """Scale for a polyline, including horizontal/vertical lines."""
    try:
        xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
        epsilon = math.ulp(max(1, *(abs(v) for v in xs + ys)))
        b = [min(xs), min(ys), max(xs), max(ys)]
        b[2], b[3] = max(b[2], b[0] + epsilon), max(b[3], b[1] + epsilon)
        return region_scale(pm, b)
    except (TypeError, ValueError, IndexError):
        return unknown("Invalid measurement points"), None


def scale_description(scale, title=None):
    ratio = positive((scale or {}).get("ratio"))
    name = f"detail '{title}'" if title else "view"
    mpp = positive((scale or {}).get("m_per_px"))
    if not mpp:
        return f"{name}: scale unavailable"
    if ratio:
        return f"{name} at 1:{ratio:g}"
    return f"{name} at {mpp:.5g} m/px"


def apply_item_scales(items, pm):
    """Adjust pixel-derived quantities in loaded Items, preserving printed/native data."""
    if not pm.get("regions"):
        return
    from engine.scale_text import rescale_items
    old = positive((pm.get("source_scale") or pm.get("scale") or {}).get("m_per_px"))
    for it in items:
        sc, region = region_scale(pm, it.bbox_px)
        it.props["measurement_scale"] = dict(sc)
        it.props["scale_region"] = region.get("title") if region else None
        mpp = positive(sc.get("m_per_px"))
        printed = it.props.get("area_m2_label") is not None
        native = it.source == "dxf"
        if not mpp:
            if not printed and not native:
                for key in ("area_m2", "width_m", "height_m", "length_m"):
                    it.q.pop(key, None)
                    it.props.pop(key, None)
            continue
        if not native:
            if not old and not printed:
                it.q.pop("area_m2", None)
            rescale_items([it], old, mpp)
            for key in ("area_m2", "width_m", "height_m", "length_m"):
                if key in it.q:
                    it.props[key] = it.q[key]


def item_scale(it, fallback=None):
    return (it.props or {}).get("measurement_scale", fallback or {})
