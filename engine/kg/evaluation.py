"""Read-only KG evaluation with explicit truth, unknowns, and heldout boundaries.

An identity is evidence only within a known document pair. Sequential drawing
IDs are never ground truth. Generated projections are labelled by the caller.
No cache writes, model calls, or PDF ingestion happen here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

RESIDUAL_BINS = (0.01, 0.05, 0.2, 0.5, 1.0, math.inf)
METHODS = ("guid", "tag_text", "position", "label_text")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(), parse_constant=lambda _: None)
    except (OSError, ValueError):
        return None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def kind(value):
    return {"stairs": "stair", "curtain_wall": "wall", "space": "room"}.get(value, value)


@dataclass(frozen=True)
class Item:
    id: str
    identity: str | None
    kind: str
    level: str | None = None
    label: str = ""
    tag: str = ""
    xy: tuple | None = None


@dataclass
class Case:
    name: str
    left: list[Item]
    right: list[Item]
    heldout: bool = True
    generated: bool = False
    alignment: dict | None = None
    notes: str = ""


def centre(box, dims=2):
    if dims == 3:
        if not isinstance(box, list) or len(box) != 2 or any(not isinstance(p, list) or len(p) != 3 for p in box):
            return None
        if not all(number(x) for row in box for x in row) or any(box[0][i] > box[1][i] for i in range(3)):
            return None
        return ((box[0][0] + box[1][0]) / 2, (box[0][2] + box[1][2]) / 2)
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(number(v) for v in box):
        return None
    if box[2] < box[0] or box[3] < box[1]:
        return None
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def ifc_items(index):
    result = []
    for e in (index or {}).get("elements", []):
        level = e.get("storey") or {}
        level = level.get("name") if isinstance(level, dict) else level
        props = e.get("props") or {}
        result.append(Item(e["item_id"], e["item_id"], kind(e.get("kind")), level,
                           e.get("name") or "", props.get("tag") or props.get("mark") or e.get("tag") or "",
                           centre(e.get("bbox_m"), 3)))
    return result


def plan_items(plan):
    """Inverse documented projection; identity is valid ONLY for IFC-derived items."""
    projection = (plan or {}).get("projection") or {}
    ppm = projection.get("ppm")
    result = []
    for e in (plan or {}).get("items", []):
        props = e.get("props") or {}
        level = (plan.get("storey") or props.get("storey"))
        level = level.get("name") if isinstance(level, dict) else level
        point = centre(e.get("bbox_px"))
        # The expression carries its own margin: do not assume page dimensions.
        margin = []
        for axis in ("x_px", "y_px"):
            m = re.search(r"\+\s*([\d.]+)\s*$", str(projection.get(axis, "")))
            margin.append(float(m[1]) if m else None)
        if point and number(ppm) and ppm > 0 and all(number(v) for v in margin) and all(number(projection.get(k)) for k in ("x0", "z0")):
            point = ((point[0] - margin[0]) / ppm + projection["x0"],
                     (point[1] - margin[1]) / ppm + projection["z0"])
        else:
            point = None
        result.append(Item(e["item_id"], e["item_id"] if e.get("source") == "ifc" else None,
                           kind(e.get("kind")), level, e.get("label") or "",
                           props.get("tag") or props.get("mark") or "", point))
    return result


def _unique(items):
    groups = defaultdict(list)
    for item in items:
        if item.identity:
            groups[item.identity].append(item)
    return {identity: entries[0] for identity, entries in groups.items() if len(entries) == 1}


def truth(case):
    a, b = _unique(case.left), _unique(case.right)
    return {(a[i].id, b[i].id) for i in a.keys() & b.keys()}


def distance(a, b):
    return math.dist(a.xy, b.xy) if a.xy is not None and b.xy is not None else None


def proposals(case, method):
    """Reference matchers. Score actual production graph edges separately.

    Text uses unique same-kind/level labels, never first-match tie breaking.
    Position uses mutual nearest neighbours on same kind and known level.
    """
    left, right = case.left, case.right
    out = []
    if method == "position":
        buckets = defaultdict(list)
        for b in right:
            if b.xy is not None and b.level:
                buckets[(b.kind, norm(b.level))].append(b)
        nearest = {}
        for a in left:
            options = buckets.get((a.kind, norm(a.level)), []) if a.level and a.xy is not None else []
            ds = sorted((distance(a, b), b.id, b) for b in options)
            if ds and (len(ds) == 1 or ds[0][0] < ds[1][0] - 1e-9):
                nearest[a.id] = ds[0]
        for a in left:
            if a.id not in nearest:
                continue
            d, _, b = nearest[a.id]
            reverse = sorted((distance(x, b), x.id) for x in left
                             if x.xy is not None and x.kind == b.kind and norm(x.level) == norm(b.level))
            if reverse and reverse[0][1] == a.id and (len(reverse) == 1 or reverse[0][0] < reverse[1][0] - 1e-9):
                out.append((a, b, d))
    else:
        attr = {"guid": "identity", "tag_text": "tag", "label_text": "label"}[method]
        def groups(items):
            groups = defaultdict(list)
            for item in items:
                # IFC GlobalIds are case-sensitive base64 identifiers.
                label = str(getattr(item, attr) or "") if method == "guid" else norm(getattr(item, attr))
                if label:
                    key = label if method == "guid" else (item.kind, norm(item.level), label)
                    groups[key].append(item)
            return groups
        aa, bb = groups(left), groups(right)
        for key in sorted(aa.keys() & bb.keys()):
            if len(aa[key]) == len(bb[key]) == 1:
                a, b = aa[key][0], bb[key][0]
                out.append((a, b, distance(a, b)))
    return out


def distribution(values):
    values = sorted(v for v in values if number(v))
    if not values:
        return {"n": 0, "min": None, "p50": None, "p90": None, "p95": None, "max": None}
    def percentile(p):
        i = (len(values) - 1) * p
        return values[int(i)] + (values[math.ceil(i)] - values[int(i)]) * (i % 1)
    return {"n": len(values), "min": values[0], "p50": percentile(.5), "p90": percentile(.9),
            "p95": percentile(.95), "max": values[-1]}


def metrics(predicted, expected, unknown=0):
    """Set metrics: duplicates never improve precision; empty denominators are null."""
    tp = len(predicted & expected)
    return {"tp": tp, "fp": len(predicted - expected), "fn": len(expected - predicted),
            "predicted": len(predicted), "expected": len(expected), "unknown": unknown,
            "precision": tp / len(predicted) if predicted else None,
            "recall": tp / len(expected) if expected else None}


def evaluate(case):
    expected = truth(case)
    summaries, observations = {}, []
    for method in METHODS:
        predictions = proposals(case, method)
        known = [(a, b, d) for a, b, d in predictions if a.identity and b.identity]
        summaries[method] = {**metrics({(a.id, b.id) for a, b, _ in known}, expected, len(predictions) - len(known)),
                             "residual_m": distribution([d for _, _, d in known])}
        for a, b, residual in known:
            observations.append({"case": case.name, "method": method, "residual_m": residual,
                                 "correct": (a.id, b.id) in expected, "heldout": case.heldout,
                                 "left": a.id, "right": b.id})
    return {"name": case.name, "heldout": case.heldout, "generated_for_demo": case.generated,
            "left_items": len(case.left), "right_items": len(case.right), "methods": summaries,
            "alignment": case.alignment, "notes": case.notes}, observations


def bin_index(residual):
    if not number(residual) or residual < 0:
        return None
    return next(i for i, limit in enumerate(RESIDUAL_BINS) if residual <= limit)


def fit_table(observations):
    """Empirical bins with Laplace smoothing; never fit a heldout observation.

    Position bins are pooled by PAVA if sampling noise reverses the expected
    distance ordering. Missing bins stay missing; no extrapolated accuracy.
    """
    result = {}
    for method in METHODS:
        rows = [o for o in observations if o["method"] == method and not o["heldout"]]
        entries = []
        for i, limit in enumerate(RESIDUAL_BINS if method == "position" else [math.inf]):
            part = [o for o in rows if bin_index(o["residual_m"]) == i] if method == "position" else rows
            n, correct = len(part), sum(o["correct"] for o in part)
            entries.append({"max_residual_m": limit if math.isfinite(limit) else None,
                            "n": n, "correct": correct, "probability": (correct + 1) / (n + 2) if n else None})
        if method == "position":
            blocks = []
            for i, entry in enumerate(entries):
                if not entry["n"]:
                    continue
                blocks.append(([i], entry["correct"] + 1, entry["n"] + 2))
                while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] < blocks[-1][1] / blocks[-1][2]:
                    b = blocks.pop(); a = blocks.pop()
                    blocks.append((a[0] + b[0], a[1] + b[1], a[2] + b[2]))
            for indices, correct, total in blocks:
                for i in indices:
                    entries[i]["probability"] = correct / total
        result[method] = entries
    return result


def svg_items(path, level=None):
    """IFC SVG groups retain GUIDs. Bound only explicit straight path geometry.

    Curved paths and transformed groups are skipped, not approximated as boxes.
    This reads a source SVG, and is deliberately not a PDF ingestion hook.
    """
    root = ET.parse(path).getroot()
    result = []
    class_kinds = {"IfcSpace": "room", "IfcDoor": "door", "IfcWindow": "window", "IfcWall": "wall",
                   "IfcWallStandardCase": "wall", "IfcStair": "stair", "IfcColumn": "column"}
    def walk(group, transformed=False):
        transformed = transformed or bool(group.get("transform"))
        guid = group.get("data-guid")
        if guid and not transformed:
            points = []
            for node in group.iter():
                if node.tag.rsplit("}", 1)[-1] != "path" or node.get("transform"):
                    continue
                d = node.get("d", "")
                if set(re.findall(r"[A-DF-Za-df-z]", d)) - {"M", "L", "Z", "z"}:
                    continue
                nums = [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?", d)]
                if len(nums) % 2 == 0:
                    points.extend(zip(nums[::2], nums[1::2]))
            if points:
                xs, ys = zip(*points)
                xy = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
                result.append(Item(guid, guid, class_kinds.get(group.get("class"), group.get("class", "other")),
                                   level, group.get("data-name", ""), "", xy))
        for child in group:
            walk(child, transformed)
    walk(root)
    return result


def align(left, right):
    """Fit a similarity on a deterministic half of GUID anchors; test the rest.

    At least three spatially non-collinear anchors are required. Alignment is
    geometric registration, never a fitted confidence or an evaluation score.
    """
    import numpy as np
    aa, bb = _unique(left), _unique(right)
    identities = sorted(i for i in aa.keys() & bb.keys() if aa[i].xy and bb[i].xy)
    anchors = [i for i in identities if int(hashlib.sha256(i.encode()).hexdigest(), 16) % 2 == 0]
    if len(anchors) < 3:
        return None
    x = np.array([aa[i].xy for i in anchors]); y = np.array([bb[i].xy for i in anchors])
    xc, yc = x - x.mean(0), y - y.mean(0)
    if np.linalg.matrix_rank(xc) < 2 or np.linalg.matrix_rank(yc) < 2:
        return None
    u, singular, vt = np.linalg.svd(xc.T @ yc)
    rotation = u @ vt
    scale = singular.sum() / (xc ** 2).sum()
    offset = y.mean(0) - scale * x.mean(0) @ rotation
    transformed = [Item(i.id, i.identity, i.kind, i.level, i.label, i.tag,
                        tuple(scale * np.array(i.xy) @ rotation + offset) if i.xy else None) for i in left]
    residual = np.linalg.norm(scale * x @ rotation + offset - y, axis=1)
    evidence = {"matches": len(anchors), "residual_m": float(np.sqrt(np.mean(residual ** 2))),
                "T": {"scale": float(scale), "rotation": rotation.tolist(), "translation": offset.tolist()},
                "withheld": len(identities) - len(anchors), "anchor_ids": anchors}
    return [i for i in transformed if i.identity not in anchors], [i for i in right if i.identity not in anchors], evidence
