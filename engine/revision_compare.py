"""Compare ingested revisions, without models or source-format dependencies.

IFC indexes use GlobalId and metre coordinates (CONTRACT 5.5), independent of
schema, authoring tool or original units. Drawing indexes use kind and overlap
after robust uniform-scale/translation registration. Positional plan item IDs
are deliberately never used for matching. Source artifacts are read only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
from statistics import median
import time
import uuid

MOVE_M = 0.05
SIZE_M = 0.001  # millimetre precision; indexed geometry is rounded to 0.1 mm
PIXEL_TOL = 2.0  # two raster edge samples, independent of sheet size
IOU_MIN = 0.4
TYPES = ("added", "removed", "moved", "resized", "property_changed")
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=lambda _: None)
    except (OSError, ValueError, TypeError):
        return None


def _number(x):
    return isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)


def _dict(value):
    return value if isinstance(value, dict) else {}


def _box(box, dims=2):
    if dims == 3 and isinstance(box, list) and len(box) == 2:
        box = [*box[0], *box[1]] if all(isinstance(p, list) and len(p) == 3 for p in box) else None
    return box if (isinstance(box, (tuple, list)) and len(box) == dims * 2
                   and all(_number(v) for v in box) and all(box[i + dims] >= box[i] for i in range(dims))) else None


def _same(a, b):
    if _number(a) and _number(b):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _label(item):
    return " ".join(str(item.get("label") or "").casefold().split())


def _kind(item):
    return str(item.get("kind") or "other")


def kind_word(kind):
    return {"mep_other": "services item", "proxy": "building item", "other": "item", "space": "room",
            "curtain_wall": "curtain wall", "flow_segment": "services segment"}.get(kind, kind.replace("_", " "))


def _storey(item):
    s = item.get("storey") or _dict(item.get("props")).get("storey")
    value = s.get("name") if isinstance(s, dict) else s
    return value if isinstance(value, str) and value.strip() else None


def _property_details(a, b):
    """Readable values for known fields; internal classifications stay in data."""
    names = {"material": "Material", "fire_rating": "Fire rating", "is_external": "Exterior",
             "width_m": "Width (m)", "height_m": "Height (m)", "length_m": "Length (m)",
             "area_m2": "Area (m²)", "area_m2_label": "Printed area (m²)", "volume_m3": "Volume (m³)",
             "label": "Label", "room_type": "Room use"}
    def value(x):
        if x is None:
            return "Not recorded"
        if isinstance(x, bool):
            return "Yes" if x else "No"
        if _number(x):
            return f"{x:g}"
        if isinstance(x, str) and not re.search(r"\bIfc[A-Z]|[A-Za-z0-9_$]{22}", x):
            return x[:180]
        return None
    details = []
    for key in names:
        if not _same(a.get(key), b.get(key)):
            old, new = value(a.get(key)), value(b.get(key))
            if old is not None and new is not None:
                details.append({"label": names[key], "old": old, "new": new})
    return details


def _source(item, doc_id, page=1):
    if item is None:
        return None
    return {"doc_id": doc_id, "item_id": item["item_id"], "page": page,
            "bbox_px": _box(item.get("bbox_px")), "bbox_m": item.get("bbox_m") if _box(item.get("bbox_m"), 3) else None,
            "storey": _storey(item)}


def _change(out, type_, a, b, doc_a, doc_b, description, page=1, **extra):
    kind = _kind(b or a)
    n = len(out) + 1
    sources = [_source(a, doc_a, page), _source(b, doc_b, page)]
    cites = []
    for side, (doc, src) in enumerate(zip((doc_a, doc_b), sources)):
        cites.append({"n": 2 * n - 1 + side, "doc_id": doc, "page": page,
                      "kind": "element" if src and src["bbox_m"] else "region",
                      "bbox_px": src["bbox_px"] if src else None,
                      "item_ids": [src["item_id"]] if src else [],
                      "quote": None if src else "No matching item in this version's compared inventory."})
    out.append({"change_id": f"c{n}", "n": n, "type": type_, "kind": kind,
                "storey": _storey(b or a), "description": description, "sentence": description,
                "v1": sources[0], "v2": sources[1], "page": page, "citations": cites, **extra})


def _counts(changes):
    def counts(rows):
        c = Counter(x["type"] for x in rows)
        return {"total": len(rows), **{t: c[t] for t in TYPES}}
    by_kind, by_storey = defaultdict(list), defaultdict(list)
    for c in changes:
        by_kind[c["kind"]].append(c)
        by_storey[c["storey"] or "Storey not recorded"].append(c)
    return {**counts(changes), "by_kind": {k: counts(v) for k, v in sorted(by_kind.items())},
            "by_storey": {k: counts(v) for k, v in sorted(by_storey.items())},
            "affected_items": len({(c["v1"]["item_id"] if c["v1"] else None,
                                     c["v2"]["item_id"] if c["v2"] else None, c["page"]) for c in changes})}


def _inventory(data, key, warnings, label):
    items = data.get(key) if isinstance(data, dict) else data
    if not isinstance(items, list):
        warnings.append(f"{label}: item inventory is missing or unreadable.")
        return None
    valid, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str) or not item["item_id"]:
            warnings.append(f"{label}: an item without a usable identity was skipped.")
            continue
        if item["item_id"] in seen:
            warnings.append(f"{label}: duplicate item identities; those items cannot be compared reliably.")
            continue
        seen.add(item["item_id"])
        valid.append(item)
    return valid


def _world_box(item, data, scene):
    bb = _box(item.get("bbox_m"), 3)
    if bb is None:
        return None
    offset = _dict(scene).get("origin_offset_m") or _dict(data).get("origin_offset_m")
    recentered = "recentr" in str(data.get("coords") or "").lower()
    if offset is None and recentered:
        return None  # comparing independently centred coordinates would invent movement
    if offset is None:
        offset = [0, 0, 0]
    if not isinstance(offset, list) or len(offset) != 3 or not all(_number(x) for x in offset):
        return None
    return [bb[i] + offset[i % 3] for i in range(6)]


def _properties(item):
    return {"name": item.get("name"), "type": item.get("type_name"), "classification": item.get("ifc_class"),
            "predefined_type": item.get("predefined_type"), "storey": item.get("storey"),
            "properties": item.get("props") or {}, "quantities": item.get("quantities") or {}}


def compare_ifc(a, b, doc_a="A", doc_b="B", scene_a=None, scene_b=None):
    """Compare normalized IFC indexes. A change is one event, not one item."""
    warnings, out = [], []
    aa = _inventory(a, "elements", warnings, "Version A")
    bb = _inventory(b, "elements", warnings, "Version B")
    if aa is None or bb is None:
        return {"changes": [], "warnings": warnings, "status": "unavailable"}
    ma, mb = {x["item_id"]: x for x in aa}, {x["item_id"]: x for x in bb}
    missing_geometry = 0
    for iid in sorted(ma.keys() | mb.keys()):
        x, y = ma.get(iid), mb.get(iid)
        word = kind_word(_kind(y or x))
        if x is None or y is None:
            type_ = "added" if y else "removed"
            _change(out, type_, x, y, doc_a, doc_b, f"A {word} was {type_}.")
            continue
        xa = _world_box(x, a if isinstance(a, dict) else {}, scene_a or {})
        yb = _world_box(y, b if isinstance(b, dict) else {}, scene_b or {})
        if xa and yb:
            da = [xa[i + 3] - xa[i] for i in range(3)]
            db = [yb[i + 3] - yb[i] for i in range(3)]
            resized = any(abs(v - w) > SIZE_M for v, w in zip(da, db))
            delta = [yb[i] - xa[i] for i in range(3)]
            if resized:
                # Resizing about the centre or one fixed face is not movement.
                # If both faces shift in the same direction, only the smaller
                # shift is established by boxes; never invent a placement.
                delta = [math.copysign(min(abs(delta[i]), abs(yb[i + 3] - xa[i + 3])), delta[i])
                         if delta[i] * (yb[i + 3] - xa[i + 3]) > 0 else 0 for i in range(3)]
            displacement = math.dist([0, 0, 0], delta)
            if displacement > MOVE_M + 1e-9:
                desc = f"A {word}'s outer bounds shifted at least {displacement:.2f} m." if resized else f"A {word} moved {displacement:.2f} m."
                _change(out, "moved", x, y, doc_a, doc_b, desc,
                        distance_m=round(displacement, 5), delta_m=[round(v, 5) for v in delta])
            if resized:
                _change(out, "resized", x, y, doc_a, doc_b, f"A {word}'s outer dimensions changed.",
                        dimensions_m_v1=da, dimensions_m_v2=db)
        else:
            missing_geometry += 1
        pa, pb = _properties(x), _properties(y)
        fields = [k for k in pa if not _same(pa[k], pb[k])]
        if fields:
            display = {"classification": "item classification", "predefined_type": "item type", "quantities": "recorded measurements"}
            _change(out, "property_changed", x, y, doc_a, doc_b,
                    f"A {word}'s {', '.join(display.get(k, k) for k in fields)} changed.",
                    fields=fields, old={k: pa[k] for k in fields}, new={k: pb[k] for k in fields},
                    property_details=_property_details(_dict(pa["properties"]) | _dict(pa["quantities"]),
                                                       _dict(pb["properties"]) | _dict(pb["quantities"])))
    if missing_geometry:
        warnings.append(f"Movement and size could not be checked for {missing_geometry} matched items because geometry or source offsets are missing.")
    shared = len(ma.keys() & mb.keys())
    if not shared and ma and mb:
        warnings.append("These models share no stable item identities. Added and removed means unmatched identities; an exporter may have replaced the identities.")
    return {"changes": out, "warnings": list(dict.fromkeys(warnings)), "status": "partial" if warnings else "ready",
            "matched_items": shared, "inventory_a": len(aa), "inventory_b": len(bb), "method": "ifc-globalid"}


def _center(bb):
    return [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]


def _transform(bb, scale, tx, ty):
    return [bb[0] * scale + tx, bb[1] * scale + ty, bb[2] * scale + tx, bb[3] * scale + ty]


def _iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


def _overlaps(a, b, transform):
    """Sparse overlap candidates, using the installed geometry library's R-tree."""
    from shapely.geometry import box
    from shapely.strtree import STRtree
    if not a or not b:
        return []
    tree = STRtree([box(*x["bbox_px"]) for x in b])
    candidates = []
    for i, x in enumerate(a):
        rect = _transform(x["bbox_px"], *transform)
        for jj in tree.query(box(*rect)):
            j = int(jj)
            if _kind(x) != _kind(b[j]):
                continue
            score = _iou(rect, b[j]["bbox_px"])
            if score >= IOU_MIN:
                candidates.append((score, i, j))
    return sorted(candidates, reverse=True)


def _unique_labels(items):
    grouped = defaultdict(list)
    for i, x in enumerate(items):
        if _label(x):
            grouped[(_kind(x), _label(x))].append(i)
    return {key: ids[0] for key, ids in grouped.items() if len(ids) == 1}


def _match(a, b, transform, labels=False):
    pairs, used_a, used_b = [], set(), set()
    if labels:
        la, lb = _unique_labels(a), _unique_labels(b)
        for key in sorted(la.keys() & lb.keys()):
            if key[0] not in ("room", "space"):
                continue
            i, j = la[key], lb[key]
            pairs.append((i, j)); used_a.add(i); used_b.add(j)
    for _, i, j in _overlaps(a, b, transform):
        if i not in used_a and j not in used_b:
            pairs.append((i, j)); used_a.add(i); used_b.add(j)
    return pairs, [i for i in range(len(a)) if i not in used_a], [j for j in range(len(b)) if j not in used_b]


def _mpp(plan):
    sc = _dict(plan.get("scale"))
    v = sc.get("m_per_px")
    confidence = sc.get("confidence", 1)
    return v if _number(v) and v > 0 and sc.get("method") not in (None, "none", "door-prior") and _number(confidence) and confidence >= 0.5 else None


def _sample(items, limit=100):
    ordered = sorted(items, key=lambda x: (_kind(x), *x["bbox_px"]))
    return ordered if len(ordered) <= limit else [ordered[i * len(ordered) // limit] for i in range(limit)]


def align_planmaps(a, b, ma, mb):
    """Find scale and translation supported by multiple unchanged items.

    Candidate sampling bounds registration cost; final matching uses every item.
    Translation consensus is verified by one-to-one geometric overlap. A lone
    item can never establish a new registration (it may itself have moved).
    """
    sa, sb = _sample(a), _sample(b)
    scales = [1.0]
    mpa, mpb = _mpp(ma), _mpp(mb)
    if mpa and mpb:
        scales = [mpa / mpb]
    else:
        for axis in ("w", "h"):
            av, bv = _dict(ma.get("image")).get(axis), _dict(mb.get("image")).get(axis)
            if _number(av) and _number(bv) and av > 0 and bv > 0:
                scales.append(bv / av)
        ratios = []
        la, lb = _unique_labels(sa), _unique_labels(sb)
        for key in la.keys() & lb.keys():
            x, y = sa[la[key]]["bbox_px"], sb[lb[key]]["bbox_px"]
            for i in (0, 1):
                if x[i + 2] > x[i]:
                    ratios.append((y[i + 2] - y[i]) / (x[i + 2] - x[i]))
        if ratios:
            scales.append(median(ratios))
        # Cropped sheets need not have the same canvas size. Stable fixture
        # dimensions provide scale hypotheses even without readable room labels.
        for kind in sorted({_kind(x) for x in sa} & {_kind(x) for x in sb}):
            for axis in (0, 1):
                dims = [[x["bbox_px"][axis + 2] - x["bbox_px"][axis] for x in sample if _kind(x) == kind]
                        for sample in (sa, sb)]
                if all(d and median(d) > 0 for d in dims):
                    scales.append(median(dims[1]) / median(dims[0]))
    best = None
    for s in sorted({round(x, 8) for x in scales if _number(x) and x > 0}):
        votes = defaultdict(list)
        for x in sa:
            bx = x["bbox_px"]
            for y in sb:
                if _kind(x) != _kind(y):
                    continue
                by = y["bbox_px"]
                if any(abs((bx[i + 2] - bx[i]) * s - (by[i + 2] - by[i])) > max(PIXEL_TOL, (by[i + 2] - by[i]) * 0.03) for i in (0, 1)):
                    continue
                cx, cy = _center(bx), _center(by)
                tx, ty = cy[0] - s * cx[0], cy[1] - s * cx[1]
                votes[(round(tx / PIXEL_TOL), round(ty / PIXEL_TOL))].append((tx, ty))
        shifts = [(0.0, 0.0)]
        for _, values in sorted(votes.items(), key=lambda kv: -len(kv[1]))[:12]:
            shifts.append((median(p[0] for p in values), median(p[1] for p in values)))
        for tx, ty in shifts:
            pairs, _, _ = _match(sa, sb, (s, tx, ty))
            exact = sum(_iou(_transform(sa[i]["bbox_px"], s, tx, ty), sb[j]["bbox_px"]) >= 0.9 for i, j in pairs)
            # Prefer more unchanged anchors; identity wins a tie, preventing a
            # repetitive grid from spuriously aligning to its adjacent bay.
            score = (exact, len(pairs), -(abs(tx) + abs(ty)), -abs(s - 1))
            if best is None or score > best[0]:
                best = (score, (s, tx, ty), exact, len(pairs))
    _, transform, anchors, matched = best or (None, (1, 0, 0), 0, 0)
    verified = anchors >= 3 and anchors >= min(len(sa), len(sb)) / 2
    if not verified and (abs(transform[1]) > PIXEL_TOL or abs(transform[2]) > PIXEL_TOL):
        transform = (mpa / mpb if mpa and mpb else 1.0, 0.0, 0.0)
    return {"scale": transform[0], "translation_px": list(transform[1:]), "verified": verified,
            "anchors": anchors, "sampled_items": [len(sa), len(sb)], "matched_sample": matched}


def compare_planmaps(ma, mb, doc_a="A", doc_b="B", page=1):
    warnings, out = [], []
    aa = _inventory(ma, "items", warnings, "Version A")
    bb = _inventory(mb, "items", warnings, "Version B")
    if aa is None or bb is None:
        return {"changes": [], "warnings": warnings, "status": "unavailable"}
    def usable(items):
        keep = []
        for x in items:
            if _kind(x) in ("text", "dimension"):
                continue
            conf = x.get("conf", 1)
            if _number(conf) and conf < 0.5:
                warnings.append("Items below 50% detection confidence were excluded; check the source drawings for omissions.")
                continue
            box = _box(x.get("bbox_px"))
            if not box or box[2] <= box[0] or box[3] <= box[1]:
                warnings.append("Items without drawing boxes were skipped.")
                continue
            keep.append(x)
        return keep
    a, b = usable(aa), usable(bb)
    alignment = align_planmaps(a, b, ma, mb)
    tr = (alignment["scale"], *alignment["translation_px"])
    if a and b and not alignment["verified"]:
        warnings.append("Drawing alignment could not be verified from at least three unchanged items. Review the marked differences.")
    pairs, gone, added = _match(a, b, tr, labels=True)
    for i in gone:
        _change(out, "removed", a[i], None, doc_a, doc_b, f"A {kind_word(_kind(a[i]))} was removed.", page)
    for j in added:
        _change(out, "added", None, b[j], doc_a, doc_b, f"A {kind_word(_kind(b[j]))} was added.", page)
    mpp = _mpp(mb)
    for i, j in pairs:
        x, y = a[i], b[j]
        bx, by = _transform(x["bbox_px"], *tr), y["bbox_px"]
        word = kind_word(_kind(y))
        distance = math.dist(_center(bx), _center(by))
        if distance > max(PIXEL_TOL, MOVE_M / mpp if mpp else PIXEL_TOL):
            _change(out, "moved", x, y, doc_a, doc_b, f"A {word} shifted in the aligned drawings.", page,
                    **({"distance_m": round(distance * mpp, 4)} if mpp else {"distance_px": round(distance, 2)}))
        if any(abs((bx[k + 2] - bx[k]) - (by[k + 2] - by[k])) > max(PIXEL_TOL, (by[k + 2] - by[k]) * 0.03) for k in (0, 1)):
            _change(out, "resized", x, y, doc_a, doc_b, f"A {word} changed size in the aligned drawings.", page)
        px, py = dict(_dict(x.get("props"))), dict(_dict(y.get("props")))
        # Geometry-derived pixel bookkeeping and per-run labels are not properties.
        px, py = ({k: v for k, v in p.items() if not k.endswith("_px") and k not in ("tag",)} for p in (px, py))
        fields = [k for k in sorted(px.keys() | py.keys()) if not _same(px.get(k), py.get(k))]
        if _label(x) != _label(y):
            fields.append("label"); px["label"], py["label"] = x.get("label"), y.get("label")
        if fields:
            old_area, new_area = px.get("area_m2"), py.get("area_m2")
            if _kind(y) in ("room", "space") and _number(old_area) and _number(new_area) and not _same(old_area, new_area):
                description = f"The area of the room reads {new_area:g} m² where it read {old_area:g} m²."
            else:
                description = f"A {word}'s recorded properties changed."
            _change(out, "property_changed", x, y, doc_a, doc_b, description, page, fields=fields,
                    old={k: px.get(k) for k in fields}, new={k: py.get(k) for k in fields}, property_details=_property_details(px, py))
    return {"changes": out, "warnings": list(dict.fromkeys(warnings)), "status": "partial" if warnings else "ready",
            "alignment": alignment, "matched_items": len(pairs), "inventory_a": len(a), "inventory_b": len(b), "method": "planmap-aligned"}


def compare_documents(doc_a, doc_b, root):
    """Read normalized artifacts; unavailable data stays unavailable (never zero)."""
    if any(not isinstance(d, str) or not SAFE_ID.fullmatch(d) or d in (".", "..") for d in (doc_a, doc_b)):
        raise ValueError("Invalid document identity.")
    root = Path(root)
    da, db = root / doc_a, root / doc_b
    meta_a, meta_b = _dict(_read(da / "doc.json")), _dict(_read(db / "doc.json"))
    result = {"doc_a": doc_a, "doc_b": doc_b, "source": "revision-code",
              "generated_for_demo": bool(meta_a.get("generated_for_demo") or meta_b.get("generated_for_demo")),
              "versions": [{"doc_id": d, "label": meta.get("title") or f"Version {label}", "kind": meta.get("kind")}
                           for d, label, meta in ((doc_a, "A", meta_a), (doc_b, "B", meta_b))], "pages": []}
    ea, eb = _read(da / "elements.json"), _read(db / "elements.json")
    if ea is not None and eb is not None:
        result.update(compare_ifc(ea, eb, doc_a, doc_b, _read(da / "scene.json"), _read(db / "scene.json")))
    else:
        # Select only numbered maps, never detector/debug maps. Pair equal page
        # numbers; sheet reordering is explicitly outside this matching method.
        def maps(d):
            return {int(p.stem.split("-")[1]): p for p in d.glob("planmap-*.json") if re.fullmatch(r"planmap-[1-9]\d*", p.stem)}
        pa, pb = maps(da), maps(db)
        warnings, changes, pages = [], [], []
        matched = na = nb = 0
        declared = [m.get("pages") for m in (meta_a, meta_b)]
        declared_max = max((n for n in declared if isinstance(n, int) and 0 < n < 100000), default=0)
        for n in sorted(pa.keys() | pb.keys() | set(range(1, declared_max + 1))):
            if n not in pa or n not in pb:
                warnings.append(f"Page {n} has no plan map in one version; it was not compared.")
                continue
            ma, mb = _read(pa[n]), _read(pb[n])
            if not isinstance(ma, dict) or not isinstance(mb, dict):
                warnings.append(f"Page {n} has an unreadable plan map; it was not compared.")
                continue
            part = compare_planmaps(ma, mb, doc_a, doc_b, n)
            if part["status"] == "unavailable":
                warnings.extend(part["warnings"]); continue
            for c in part["changes"]:
                c["n"] = len(changes) + 1; c["change_id"] = f"c{c['n']}"
                for side, cite in enumerate(c["citations"]):
                    cite["n"] = 2 * c["n"] - 1 + side
                changes.append(c)
            warnings.extend(part["warnings"])
            matched += part["matched_items"]; na += part["inventory_a"]; nb += part["inventory_b"]
            pages.append({"page": n, "image_a": ma.get("image"), "image_b": mb.get("image"),
                          "page_image_a": f"/api/docs/{doc_a}/pages/{n}/image" if (da / f"page-{n}.png").is_file() else None,
                          "page_image_b": f"/api/docs/{doc_b}/pages/{n}/image" if (db / f"page-{n}.png").is_file() else None,
                          "alignment": part["alignment"]})
        if not pages:
            warnings.append("Both versions need an IFC item index or an existing plan map. No comparable drawing data is available yet.")
        result.update(changes=changes, warnings=list(dict.fromkeys(warnings)), pages=pages, matched_items=matched,
                      inventory_a=na, inventory_b=nb, method="planmap-aligned",
                      status="unavailable" if not pages else "partial" if warnings else "ready")
    result["summary"] = _counts(result["changes"]) if result["status"] != "unavailable" else None
    result["note"] = ("Compared stable item identities, source positions, outer dimensions and recorded properties. Movement threshold: more than 5 cm. Rotation or a changed model coordinate system can also change outer dimensions."
                      if result.get("method") == "ifc-globalid" else
                      "Compared drawing items by kind and overlap after scale and translation alignment; rooms also use unique labels. Pages are paired by page number. Text and dimensions are not compared.")
    return result


COMPARE_INTENT = re.compile(r"\b(?:what(?:'s| is)?\s+(?:has\s+)?changed|what\s+has\s+changed|changes?\s+(?:between|from|since|in)|compare\s+(?:these|the\s+(?:two|versions)|versions|revisions)|differences?\s+between)\b", re.I)


LEVEL_REF = re.compile(r"\b(?:level|floor|storey|story)s?\s*\d+\b|\b\d+(?:st|nd|rd|th)\s+(?:floor|level|storey|story)\b|"
                       r"\b(?:ground|first|second|third|fourth|top|basement|roof)\s+(?:floor|level|storey|story)\b", re.I)
VERSION_WORD = re.compile(r"\b(?:versions?|revisions?|rev\.?|v\d+|issued|transfer|before|after)\b", re.I)


def _count_difference(question, ids, root):
    """A net inventory change is B minus A, not the number of changed properties."""
    q = question.casefold()
    if not (re.search(r"\b(?:net (?:change|difference)|(?:second|first) minus (?:first|second)|difference in)\b", q)
            and re.search(r"\bcounts?\b|\bnumber\b|\bhow many\b", q)):
        return None
    kinds = [kind for kind, rx in (("door", r"doors?"), ("window", r"windows?"), ("wall", r"walls?"),
             ("room", r"rooms?|spaces?"), ("column", r"columns?"), ("beam", r"beams?"))
             if re.search(r"\b(?:" + rx + r")\b", q)]
    if len(kinds) != 1 or len(ids) != 2:
        return None
    from engine.solvers.data import load_doc
    from engine.solvers.solve import MIN_CONF, _answer_obj, _step
    t0 = time.perf_counter()
    try:
        docs = [load_doc(did, root) for did in ids]
    except (OSError, ValueError, KeyError, TypeError):
        docs = [None, None]
    if any(doc is None for doc in docs):
        return None  # The comparison route explains missing source inventories.
    kind = kinds[0]
    inventories = [[it for it in doc.items if it.kind == kind and (doc.mode == "ifc" or it.conf >= MIN_CONF)] for doc in docs]
    counts = [len({it.item_id for it in items}) for items in inventories]
    reverse = bool(re.search(r"\bfirst minus second\b", q))
    value = counts[0] - counts[1] if reverse else counts[1] - counts[0]
    direction = "first minus second" if reverse else "second minus first"
    exact = all(doc.mode == "ifc" for doc in docs)
    noun = kind + "s"
    text = (f"**Net change in {'recorded' if exact else 'detected'} {kind} count: {value:+d} ({direction}).** [1] [2]"
            f"\n\n- First model: {counts[0]} {noun}; second model: {counts[1]} {noun}."
            "\n- This compares inventory totals; additions and removals can cancel out.")
    if not exact:
        text += "\n- Drawing detections can be incomplete; check the marked items in both versions."
    citations = []
    for n, (doc, items) in enumerate(zip(docs, inventories), 1):
        # Each version has one source citation covering its complete inventory.
        citations.append(dict(n=n, doc_id=doc.doc_id, page=1,
            kind="element" if doc.mode == "ifc" else "region", bbox_px=None,
            inventory_check=True,
            item_ids=[it.item_id for it in items], quote=f"{len(items)} {noun} in this version's checked inventory."))
    trace = [_step("revision_count", f"{direction}: {counts[0] if reverse else counts[1]} - {counts[1] if reverse else counts[0]} = {value}")]
    highlights = [it.item_id for it in inventories[1]]
    res = _answer_obj(question, ids, text, value, "count", 1 if exact else .5, False, [], citations,
        {"doc_id": ids[1], "highlight_item_ids": highlights, "camera_target_item_id": highlights[0] if highlights else None},
        trace, "index" if exact else "planmap", t0)
    res["reasoning"] = {"steps": [
        {"kind": "found", "title": "Found", "text": f"First inventory: {counts[0]} {noun}; second: {counts[1]}.", "cite": 1, "ok": True},
        {"kind": "calculated", "title": "Calculated", "text": trace[0]["detail"], "cite": 2, "ok": True}],
        "confidence": {"label": "Verified" if exact else "Estimate", "pct": 100 if exact else 50,
            "reason": "Counted each stored element identity once in both inventories." if exact else "Compared drawing detections; completeness is not verified.",
            "improve": None if exact else "Verify detections against both source drawings."}}
    return res


def comparison_answer(question, doc_ids, root):
    """Early code route; returning it before context/explain avoids any model call."""
    is_count_change = bool(re.search(r"\bnet (?:change|difference)\b|\b(?:first|second) minus (?:first|second)\b", question or "", re.I))
    if not COMPARE_INTENT.search(question or "") and not (len(doc_ids or []) == 2 and re.search(r"\bcompar(?:e|ing)\b", question or "", re.I)) and not is_count_change:
        return None
    # "compare level 1 and level 2" compares parts of one project (projects engine), not two versions of a drawing.
    if LEVEL_REF.search(question or "") and not VERSION_WORD.search(question or ""):
        return None
    t0 = time.perf_counter()
    ids = list(dict.fromkeys(doc_ids or []))
    # Explicit first/second operands refer to attachment order. Named-version
    # direction for a full geometric comparison is resolved separately below.
    count_result = _count_difference(question, ids, root)
    if count_result is not None:
        return count_result
    # Explicit names in the question establish direction; attachment order is
    # the fallback. Never infer chronology from a particular document name.
    if len(ids) == 2:
        positions = []
        for did in ids:
            meta = _dict(_read(Path(root) / did / "doc.json"))
            names = [did, meta.get("title") or ""]
            hits = [question.casefold().find(name.casefold()) for name in names if len(name) > 1 and name.casefold() in question.casefold()]
            positions.append(min(hits) if hits else None)
        if all(pos is not None for pos in positions) and positions[1] < positions[0]:
            ids.reverse()
    result = compare_documents(*ids, root) if len(ids) == 2 else None
    available = result is not None and result["status"] != "unavailable"
    citations = []
    if result:
        for c in result["changes"]:
            citations.extend(c["citations"])
        if not citations:
            citations = [{"n": n, "doc_id": d, "page": 1, "kind": "element" if result.get("method") == "ifc-globalid" else "region",
                          "bbox_px": None, "item_ids": [], "quote": f"Compared inventory: {result.get('inventory_' + side, 0)} items."}
                         for n, d, side in ((1, ids[0], "a"), (2, ids[1], "b"))] if available else []
    if result is None:
        text = "**Select exactly two versions to compare.** Attach version A first and version B second."
    elif not available:
        text = "**These versions do not have comparable drawing data yet.** " + result["warnings"][-1]
    else:
        s = result["summary"]
        text = f"**{s['total']} change{'s' if s['total'] != 1 else ''} found between the two versions.** [1] [2]"
        lines = []
        for type_, title in (("added", "Added"), ("removed", "Removed"), ("moved", "Moved"), ("resized", "Resized"), ("property_changed", "Properties changed")):
            if s[type_]:
                lines.append(f"{title}: {s[type_]}")
        if lines:
            text += "\n\n- " + "; ".join(lines) + "."
        text += f"\n- [Open the comparison](#/changes?a={ids[0]}&b={ids[1]}) to inspect each change."
        if result["warnings"]:
            text += "\n- " + result["warnings"][0]
        if result["generated_for_demo"]:
            text += "\n- Includes content generated for demo."
    scene_ids = list(dict.fromkeys(c["v2"]["item_id"] for c in result["changes"] if c["v2"])) if available else []
    pct = 100 if available and result["status"] == "ready" and result["method"] == "ifc-globalid" else 80 if available and result["status"] == "ready" else 50 if available else 0
    confidence = {"label": "Verified" if pct == 100 else "Cross-checked" if pct == 80 else "Estimate", "pct": pct,
                  "reason": result["note"] if available else "Two comparable source inventories are required.",
                  "improve": "; ".join(result["warnings"]) if result and result["warnings"] else None}
    steps = [{"kind": "found", "title": "Found", "text": f"Read both version inventories: {result['inventory_a']} and {result['inventory_b']} items.", "cite": 1, "ok": True},
             {"kind": "checked", "title": "Checked", "text": result["note"], "cite": 2, "ok": result["status"] == "ready"}] if available else []
    res = {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": ids,
            "answer": {"text_md": text, "value": result["summary"]["total"] if available else None,
                       "unit": "changes" if available else None, "confidence": pct / 100, "abstained": not available},
            "citations": citations, "evidence": {"boxes": [], "scene": {"doc_id": ids[-1] if ids else "", "highlight_item_ids": scene_ids,
                                                                         "camera_target_item_id": scene_ids[0] if scene_ids else None}},
            "trace": [{"step": "revision_compare", "detail": result["note"] if result else "Two versions required", "ms": 0, "model": None, "cost_usd": 0}],
            "route": "index" if result and result.get("method") == "ifc-globalid" else "planmap", "cost": {"usd_total": 0, "calls": []},
            "latency_ms": int((time.perf_counter() - t0) * 1000), "reasoning": {"steps": steps, "confidence": confidence}}
    if available:
        from engine.calc_inventory import revisions
        revisions(res, result)
    return res
