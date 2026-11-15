"""Cross-discipline checks in page-image pixels; no model calls or PDF ingestion.

``analyse(base, services)`` accepts normalised sheets (see ``load_sheet``).
Only classified geometry is used for quantities/intersections. Text-only rooms
remain label records, never invented polygons. ``prepare_pdf`` is an OFFLINE,
cached adapter; chat only reads ingestion outputs. Pages are contract 1-based.
Optional Awais and F-OVERLAY adapters are imported lazily after integration.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

VERSION = 2
NUM = r"\d+(?:[.,]\d+)?"
AREA_NUM = rf"(?:\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|{NUM})"
AREA = re.compile(rf"^\s*({AREA_NUM})\s*(m[²2]|sq\.?\s*ft|ft[²2]|SF)\s*$", re.IGNORECASE)
FLOW = re.compile(rf"^\s*([+−-]?{NUM})\s*(l\s*/\s*s|m[³3]\s*/\s*h|cfm)\s*$", re.IGNORECASE)
HEIGHT = re.compile(rf"^\s*(.*?)\s*\bh\s*=\s*({NUM})\s*(mm|cm|m|ft|in)?\s*$", re.IGNORECASE)


def _number(x):
    try:
        v = float(str(x).replace(",", ".").replace("−", "-"))
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def _box(x):
    if not isinstance(x, (list, tuple)) or len(x) != 4:
        return None
    b = [_number(v) for v in x]
    return b if all(v is not None for v in b) and b[2] > b[0] and b[3] > b[1] else None


def _centre(b):
    return [(b[0]+b[2])/2, (b[1]+b[3])/2]


def _bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _words(sheet):
    out, seen = [], set()
    for w in sheet.get("words", []):
        b = _box(w.get("bbox_px", w.get("bbox")))
        text = str(w.get("text", "")).strip()
        if b and text and (text, tuple(b)) not in seen:
            out.append({"text": text, "bbox_px": b}); seen.add((text, tuple(b)))
    # Ingest may deliver tokens ("16.5", "m²") rather than full lines.
    # Join only a number and its immediately adjacent, aligned unit token.
    units = [w for w in out if re.fullmatch(r"m[²2]|sq\.?\s*ft|ft[²2]|SF|l/s|m[³3]/h|cfm", w["text"], re.IGNORECASE)]
    joined = []
    for w in out:
        if not re.fullmatch(rf"[+−-]?{AREA_NUM}", w["text"]):
            continue
        a = w["bbox_px"]; ac = _centre(a)
        candidates = []
        for u in units:
            b = u["bbox_px"]; bc = _centre(b)
            em = max(min(a[2]-a[0], a[3]-a[1]), min(b[2]-b[0], b[3]-b[1]))
            horizontal = abs(ac[1]-bc[1]) < em*.6 and 0 <= b[0]-a[2] < em*2
            vertical = abs(ac[0]-bc[0]) < em*.6 and (0 <= b[1]-a[3] < em*2 or 0 <= a[1]-b[3] < em*2)
            if horizontal or vertical:
                candidates.append(u)
        if candidates:
            u = min(candidates, key=lambda v: math.dist(ac, _centre(v["bbox_px"])))
            joined.append({"text": w["text"] + " " + u["text"], "bbox_px": _union([a, u["bbox_px"]])})
    return out + joined


def _near(a, b, factor=5):
    # Typography-sized grouping, independent of sheet size and drawing scale.
    ca, cb = _centre(a), _centre(b)
    em = max(min(a[2]-a[0], a[3]-a[1]), min(b[2]-b[0], b[3]-b[1]))
    return math.dist(ca, cb) <= factor*em


def room_table(sheet):
    """Use supplied room polygons; otherwise extract printed label blocks only.

    Name/number associations in the fallback are explicitly candidates. Ceiling
    text is attached only inside a supplied polygon, or when it is part of the
    same label. Unqualified h= values retain their printed unit as unknown.
    """
    words = _words(sheet)
    out = []
    for i, raw in enumerate(sheet.get("rooms", [])):
        r = dict(raw)
        r.setdefault("item_id", f"room-{i+1:03}")
        r["bbox_px"] = _box(r.get("bbox_px", r.get("label_bbox")))
        r.setdefault("polygon_px", None)
        r.setdefault("area_m2", r.get("area_printed_m2"))
        r.setdefault("label", r.get("name") or r.get("number") or "Room")
        r.setdefault("association", "supplied")
        if r.get("merged") or r.get("split"):
            r["polygon_px"] = None
            r["association"] = "unresolved source region"
        out.append(r)
    if not out:
        for w in words:
            m = AREA.fullmatch(w["text"])
            if not m:
                continue
            metric = m[2].lower().startswith("m")
            token = m[1]
            if not metric and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", token):
                token = token.replace(",", "")
            value = _number(token)
            if value is None:
                continue
            area = value * (1 if metric else .09290304)
            nearby = [v for v in words if v is not w and _near(w["bbox_px"], v["bbox_px"], 4)
                      and len(v["text"]) <= 80 and not AREA.fullmatch(v["text"])]
            # Prefer full-word text. A nearby reference is never silently a room id.
            ids = [v for v in nearby if re.fullmatch(r"(?:[A-ZÅÄÖ]{0,3}\d{1,5}[A-Z]?|\d{1,4}[./-]\d{1,3})", v["text"], re.IGNORECASE)]
            names = [v for v in nearby if re.fullmatch(r"[^\W\d_][^\d=]{1,60}", v["text"], re.UNICODE)]
            origin = _centre(w["bbox_px"])
            order = lambda v, origin=origin: math.dist(origin, _centre(v["bbox_px"]))
            # A room label is a stack of similarly oriented lines. A diagonal
            # ceiling code crossing the area text cannot become its room id.
            ab = w["bbox_px"]; vertical = ab[3]-ab[1] > ab[2]-ab[0]
            def oriented(v, vertical=vertical):
                b = v["bbox_px"]
                return (b[3]-b[1] >= (b[2]-b[0])*.8) if vertical else (b[2]-b[0] >= (b[3]-b[1])*.8)
            names = [v for v in names if oriented(v)]
            name = min(names, key=order) if names else None
            ids = [v for v in ids if oriented(v)]
            if name:
                axis = 0 if vertical else 1
                direction = _centre(name["bbox_px"])[axis]-origin[axis]
                ids = [v for v in ids if (_centre(v["bbox_px"])[axis]-origin[axis])*direction > direction**2]
            num = min(ids, key=order) if ids and name else None
            parts = [w, *([num] if num else []), *([name] if name else [])]
            out.append({"item_id": f"room-label-{len(out)+1:03}", "number": num["text"] if num else None,
                        "label": name["text"] if name else "Unidentified room label", "area_m2": area,
                        "area_quote": w["text"], "area_bbox_px": w["bbox_px"],
                        "bbox_px": _union([p["bbox_px"] for p in parts]), "polygon_px": None,
                        "association": "nearby text candidate"})
    for r in out:
        # Only polygon containment can associate detached ceiling tags to a room.
        ceilings, height_candidates = [], []
        for w in words:
            m = HEIGHT.fullmatch(w["text"])
            if not m or not r.get("polygon_px") or not _inside(_centre(w["bbox_px"]), r["polygon_px"]):
                continue
            unit = str(m[3] or sheet.get("height_unit") or "").lower()
            h = _number(m[2])
            factor = {"mm": .001, "cm": .01, "m": 1, "ft": .3048, "in": .0254}.get(unit)
            metres = h * factor if factor is not None else None
            label = {"type": m[1] or None, "height_m": metres, "printed": w["text"], "bbox_px": w["bbox_px"]}
            definition = (sheet.get("ceiling_types") or {}).get(m[1]) or {}
            if definition.get("source") or re.search(r"\b(?:ceiling|alakatto|undertak|decke)\b", m[1], re.IGNORECASE):
                ceilings.append(label)
            else:
                height_candidates.append(label)
        if height_candidates:
            r["unclassified_height_labels"] = height_candidates
        if ceilings:
            r["ceiling_labels"] = ceilings
            values = {c["height_m"] for c in ceilings}
            types = {c["type"] for c in ceilings}
            if len(values) == 1 and None not in values and r.get("ceiling_height_m") is None:
                r["ceiling_height_m"] = next(iter(values))
            if len(types) == 1 and r.get("ceiling_type") is None:
                r["ceiling_type"] = next(iter(types))
    return out


def airflow_labels(sheet):
    """Explicit units only. A bare +25 is ambiguous without a supplied legend.

    Signs do not imply supply/extract. The caller may supply ``flow_signs``
    with ``source`` evidence and + / - roles established by that sheet's legend.
    A label is a label, never an inferred terminal or terminal multiplier.
    """
    out = []
    signs = sheet.get("flow_signs") or {}
    for w in _words(sheet):
        m = FLOW.fullmatch(w["text"])
        if not m:
            continue
        v = _number(m[1]); unit = re.sub(r"\s", "", m[2].lower())
        factor = 1 if unit == "l/s" else 1/3.6 if unit in ("m³/h", "m3/h") else .4719474432
        role = signs.get("-" if v < 0 else "+") if signs.get("source") else None
        out.append({"item_id": f"flow-label-{len(out)+1:03}", "bbox_px": w["bbox_px"],
                    "flow_ls": abs(v)*factor, "signed_flow_ls": v*factor,
                    "role": role, "quote": w["text"], "kind": "airflow label"})
    return out


def _inside(point, polygon):
    from shapely.geometry import Point, Polygon
    try:
        p = Polygon(polygon)
        return p.is_valid and p.contains(Point(point))
    except (ValueError, TypeError):
        return False


def _matrix(alignment):
    import numpy as np
    try:
        if not isinstance(alignment, dict):
            return None
        if all(k in alignment for k in ("s", "R", "t")):
            rotation = np.asarray(alignment["R"], dtype=float)*float(alignment["s"])
            alignment = {"matrix": [[*rotation[0], alignment["t"][0]], [*rotation[1], alignment["t"][1]], [0, 0, 1]]}
        a = np.asarray(alignment.get("matrix", alignment.get("T")), dtype=float)
        if a.shape == (2, 3):
            a = np.vstack((a, [0, 0, 1]))
        if a.shape != (3, 3) or not np.isfinite(a).all() or not np.allclose(a[2], [0, 0, 1]) or np.linalg.det(a[:2, :2]) <= 0:
            return None
        return a
    except (ValueError, TypeError):
        return None


def transform(points, alignment, inverse=False):
    import numpy as np
    a = _matrix(alignment)
    if a is None:
        raise ValueError("A valid registration is required")
    if inverse:
        a = np.linalg.inv(a)
    p = np.asarray(points, dtype=float)
    return (np.column_stack((p, np.ones(len(p)))) @ a.T)[:, :2].tolist()


def align(base, services):
    """Map services -> base. Prefer F-OVERLAY when present; robust label fallback."""
    supplied = services.get("alignment_to") or {}
    if (supplied.get("base_doc_id") == base.get("doc_id") and supplied.get("base_page", 1) == base.get("page", 1)
            and supplied.get("status") in ("manual", "aligned") and _matrix(supplied) is not None):
        return supplied
    try:
        from engine.sheet_align import align_sheets
    except ImportError:
        align_sheets = None
    if align_sheets:
        return align_sheets(base, services)
    import numpy as np
    labels = []
    for s in (base, services):
        d = defaultdict(list)
        for w in _words(s):
            text = " ".join(w["text"].casefold().split())
            # Dimensions and generic prose cannot independently anchor a room.
            if re.fullmatch(r"(?=.*\d)(?=.*[^\W\d_])[\w./-]{2,24}", text):
                d[text].append(_centre(w["bbox_px"]))
        labels.append(d)
    a, b = labels
    names = sorted(k for k in a.keys() & b.keys() if len(a[k]) == len(b[k]) == 1)
    fail = {"status": "needs_manual", "matrix": None, "detail": "No reliable shared-label alignment."}
    if len(names) < 3:
        return fail
    src, dst = np.array([b[k][0] for k in names]), np.array([a[k][0] for k in names])
    def fit(ix):
        x, y = src[ix].T
        des = np.zeros((len(ix)*2, 4))
        des[::2] = np.column_stack((x, -y, np.ones(len(ix)), np.zeros(len(ix))))
        des[1::2] = np.column_stack((y, x, np.zeros(len(ix)), np.ones(len(ix))))
        if np.linalg.matrix_rank(des) < 4:
            return None
        u, v, tx, ty = np.linalg.lstsq(des, dst[ix].reshape(-1), rcond=None)[0]
        return np.array([[u, -v, tx], [v, u, ty], [0, 0, 1]])
    size = base.get("image") or {}
    tol = max(2., min(size.get("w", 1000), size.get("h", 1000))*.002)
    rng = np.random.default_rng(0); best = []
    for _ in range(min(600, len(names)*20)):
        mat = fit(rng.choice(len(names), 2, replace=False))
        if mat is None:
            continue
        err = np.linalg.norm(np.column_stack((src, np.ones(len(src)))) @ mat.T[:, :2] - dst, axis=1)
        hit = np.flatnonzero(err <= tol)
        if len(hit) > len(best):
            best = hit
    if len(best) < 3:
        return fail
    mat = fit(best)
    spread = np.ptp(dst[best], axis=0)
    if (min(spread) < tol*4 or min(spread / [size.get("w", 1000), size.get("h", 1000)]) < .08
            or np.linalg.svd(dst[best]-dst[best].mean(0), compute_uv=False)[-1] < tol):
        return fail
    err = np.linalg.norm(np.column_stack((src[best], np.ones(len(best)))) @ mat.T[:, :2] - dst[best], axis=1)
    return {"status": "aligned", "matrix": mat.tolist(), "method": "shared-label similarity",
            "anchor_count": len(best), "residual_px": float(np.sqrt(np.mean(err**2))),
            "anchors": [{"label": names[i], "base": dst[i].tolist(), "overlay": src[i].tolist()} for i in best]}


def _mapped_box(b, registration, inverse=False):
    return _bounds(transform([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], registration, inverse))


def _poly(item):
    from shapely.geometry import Polygon
    try:
        p = Polygon(item.get("polygon_px") or [], holes=item.get("holes_px"))
        return p if p.is_valid and p.area > 0 else None
    except (ValueError, TypeError):
        return None


def analyse(base, services, *, alignment=None, threshold_ls_m2=None, ceiling_below_m=None):
    """Findings are records with both-sheet evidence; missing geometry stays unknown.

    complete.terminals is an explicit ingest guarantee, never inferred from a
    nonempty list. Boundary cases inside registration residual stay unassigned.
    Classified duct/pipe centrelines and wall/beam/opening polygons are accepted.
    Intersections are 2D coordination candidates, never certified 3D clashes.
    """
    from shapely.geometry import LineString, Point
    from shapely.geometry import box as rect
    from shapely.ops import transform as geom_transform
    reg = alignment if alignment is not None else align(base, services)
    rooms = room_table(base)
    labels = airflow_labels(services)
    out = {"version": VERSION, "base_doc_id": base.get("doc_id"), "services_doc_id": services.get("doc_id"),
           "alignment": reg, "rooms": rooms, "airflow_labels": labels, "airflow": [], "missing_air": [],
           "crossings": [], "low_ceilings": [], "unassigned_terminals": [], "limitations": []}
    out["limitations"].extend(base.get("limitations", []) + services.get("limitations", []))
    if _matrix(reg) is None or reg.get("status") not in ("aligned", "manual"):
        out["limitations"].append("Sheets are not reliably aligned; room-level checks were not run.")
        return out
    residual = _number(reg.get("residual_px")) or 0
    polygons = {r["item_id"]: _poly(r) for r in rooms}
    if any(p is None for p in polygons.values()):
        out["limitations"].append("Some rooms have labels only; no terminal, duct or ceiling assignment was guessed for them.")
    if any(d.get("classification") == "unverified" for d in services.get("ducts", [])):
        out["limitations"].append("Unverified line pairs may be annotation leaders rather than ducts; confirm their type on the source sheet.")
    if any(w.get("classification") == "unverified" for w in base.get("walls", [])):
        out["limitations"].append("Wall shapes from vector rules are unverified; check each proposed crossing on both sheets.")
    matrix = _matrix(reg)
    def gmap(g):
        return geom_transform(lambda x, y, z=None: (matrix[0, 0]*x+matrix[0, 1]*y+matrix[0, 2],
                                                   matrix[1, 0]*x+matrix[1, 1]*y+matrix[1, 2]), g)
    def evidence(room=None, service=None, base_box=None):
        bb = base_box or (room or {}).get("bbox_px")
        sb = _mapped_box(base_box, reg, True) if base_box else _box((service or {}).get("bbox_px"))
        if bb is None and sb:
            bb = _mapped_box(sb, reg)
        if sb is None and bb:
            sb = _mapped_box(bb, reg, True)
        return [{"doc_id": s.get("doc_id", ""), "page": s.get("page", 1), "bbox_px": b,
                 "item_ids": [str(it.get("item_id"))] if it and it.get("item_id") else [],
                 "quote": it.get("quote") or it.get("area_quote") or it.get("label"),
                 "projected": projected}
                for s, b, it, projected in [(base, bb, room or {}, base_box is not None or not room),
                                            (services, sb, service or {}, bool(base_box) or not bool(service))] if b]
    assigned = defaultdict(list)
    for t in services.get("terminals", []):
        b = _box(t.get("bbox_px"))
        if not b:
            out["unassigned_terminals"].append({"item_id": t.get("item_id"), "reason": "Position unavailable"}); continue
        pt = Point(transform([t.get("point_px") or _centre(b)], reg)[0])
        matches = [r for r in rooms if polygons[r["item_id"]] is not None and polygons[r["item_id"]].buffer(-residual).contains(pt)]
        if len(matches) == 1:
            assigned[matches[0]["item_id"]].append(t)
        else:
            out["unassigned_terminals"].append({"item_id": t.get("item_id"), "reason": "Room boundary, overlap or missing polygon"})
    complete = (services.get("complete") or {}).get("terminals") is True
    if not complete:
        out["limitations"].append("Terminal extraction is incomplete; absence of supply or extract air cannot be established.")
    coverage = _poly({"polygon_px": services.get("coverage_polygon_px")})
    if coverage is None and complete and services.get("image"):
        sz = services["image"]
        if sz.get("w", 0) > 0 and sz.get("h", 0) > 0:
            coverage = rect(0, 0, sz["w"], sz["h"])
    coverage = gmap(coverage) if coverage is not None else None
    for r in rooms:
        p = polygons[r["item_id"]]
        if p is None:
            continue
        ts = assigned[r["item_id"]]
        ev = evidence(r)
        for t in ts:
            ev.extend(evidence(r, t)[1:])
        roles = defaultdict(list)
        for t in ts:
            roles[t.get("role", "unknown")].append(t)
        row = {"room_id": r["item_id"], "number": r.get("number"), "label": r["label"], "area_m2": r.get("area_m2"),
               "terminal_ids": [t.get("item_id") for t in ts], "evidence": ev, "arithmetic": []}
        for role in ("supply", "extract"):
            vals = [_number(t.get("flow_ls")) for t in roles[role]]
            # A partial list cannot support a total, even when every found label has a value.
            known = (complete and coverage is not None and coverage.covers(p)
                     and not any(k not in ("supply", "extract") and v for k, v in roles.items())
                     and not out["unassigned_terminals"])
            total = sum(vals) if known and all(v is not None and v >= 0 for v in vals) else None
            row[f"{role}_ls"] = total
            area = _number(r.get("area_m2"))
            ratio = total/area if total is not None and area is not None and area > 0 else None
            row[f"{role}_ls_m2"] = ratio
            if total is not None:
                terms = " + ".join(f"{v:g}" for v in vals) if vals else "0 recorded terminals"
                row["arithmetic"].append(f"{role}: {terms} = {total:g} l/s" + (f"; {total:g} / {area:g} = {ratio:.6g} l/s/m²" if ratio is not None else "; area unknown"))
            elif vals and all(v is not None and v >= 0 for v in vals):
                recorded = sum(vals)
                row[f"recorded_{role}_ls"] = recorded
                arithmetic = f"recorded {role}: " + " + ".join(f"{v:g}" for v in vals) + f" = {recorded:g} l/s"
                if area is not None and area > 0:
                    arithmetic += f"; {recorded:g} / {area:g} = {recorded/area:.6g} l/s/m²"
                row["arithmetic"].append(arithmetic + "; incomplete evidence, not a room total")
            if known and not roles[role] and not out["unassigned_terminals"]:
                out["missing_air"].append({"room_id": r["item_id"], "role": role, "status": "no recorded terminal", "evidence": ev})
        threshold = _number(threshold_ls_m2)
        source = "user"
        stated = services.get("airflow_threshold") or {}
        if threshold is None and stated.get("source"):
            threshold = _number(stated.get("value_ls_m2")); source = "sheet"
        if threshold is not None and row.get("supply_ls_m2") is not None:
            row["below_user_threshold"] = row["supply_ls_m2"] < threshold
            row["threshold_ls_m2"] = threshold
            row["threshold_source"] = source
            if source == "sheet" and isinstance(stated["source"], dict) and _box(stated["source"].get("bbox_px")):
                row["evidence"].append({**stated["source"], "doc_id": services.get("doc_id", ""), "page": stated["source"].get("page", services.get("page", 1)), "projected": False})
        unknown_values = [_number(t.get("signed_flow_ls", t.get("flow_ls"))) for role, terms in roles.items() if role not in ("supply", "extract") for t in terms]
        row["unclassified_flow_labels_ls"] = [v for v in unknown_values if v is not None]
        if row["unclassified_flow_labels_ls"]:
            row["arithmetic"].append("Unclassified terminal labels: " + ", ".join(f"{v:+g} l/s" for v in row["unclassified_flow_labels_ls"]) + "; supply/extract direction is not established")
        out["airflow"].append(row)
    lines = []
    for d in services.get("ducts", []) + services.get("pipes", []):
        points = d.get("centreline_px", d.get("centerline_px"))
        if not points or len(points) < 2 or d.get("classification") == "candidate":
            continue
        try:
            line = gmap(LineString(points))
            if line.is_valid and line.length > 0:
                lines.append((d, line))
        except (ValueError, TypeError):
            continue
    for d, line in lines:
        width = _number(d.get("width_px")) or 0
        import numpy as np
        footprint = line.buffer(width*math.sqrt(float(np.linalg.det(matrix[:2, :2])))/2) if width > 0 else line
        for wall in base.get("walls", []) + base.get("beams", []) + base.get("openings", []):
            p = _poly(wall)
            # Must enter the interior and exit, not run along or end on the edge.
            if p is None or not line.crosses(p):
                continue
            intersection = line.intersection(p)
            bb = list(intersection.bounds)
            if bb[0] == bb[2]: bb[0] -= .5; bb[2] += .5
            if bb[1] == bb[3]: bb[1] -= .5; bb[3] += .5
            # The pair immediately beside this wall, rather than every room
            # traversed by a long run elsewhere on the page.
            pieces = list(intersection.geoms) if hasattr(intersection, "geoms") else [intersection]
            distances = [line.project(Point(q)) for piece in pieces if hasattr(piece, "coords") for q in piece.coords]
            margin = max(residual*2, intersection.length*.01, 1e-6)
            beside = [line.interpolate(max(0, min(distances)-margin)), line.interpolate(min(line.length, max(distances)+margin))] if distances else []
            adjacent = [r["item_id"] for r in rooms if polygons[r["item_id"]] is not None and any(polygons[r["item_id"]].contains(pt) for pt in beside)]
            rating = wall.get("fire_rating") if wall.get("fire_rating_source") else None
            proof = evidence(service=d, base_box=bb)
            source = wall.get("fire_rating_source")
            if rating and isinstance(source, dict) and _box(source.get("bbox_px")):
                proof.append({"doc_id": base.get("doc_id", ""), "page": source.get("page", base.get("page", 1)),
                              "bbox_px": source["bbox_px"], "quote": source.get("quote"), "item_ids": [wall["item_id"]], "projected": False})
            out["crossings"].append({"service_id": d.get("item_id"), "barrier_id": wall.get("item_id"),
                                     "service_classification": d.get("classification", "supplied"),
                                     "barrier_classification": wall.get("classification", "supplied"),
                                     "barrier_kind": wall.get("kind", "wall"), "room_ids": adjacent,
                                     "fire_rating": rating, "fire_rating_source": wall.get("fire_rating_source"),
                                     "status": "2D crossing candidate; check elevation and fire seal", "evidence": proof})
        limit = _number(ceiling_below_m)
        if limit is not None:
            for r in rooms:
                p = polygons[r["item_id"]]; h = _number(r.get("ceiling_height_m"))
                if p is not None and h is not None and h < limit and footprint.intersects(p):
                    out["low_ceilings"].append({"room_id": r["item_id"], "service_id": d.get("item_id"),
                                                "service_classification": d.get("classification", "supplied"),
                                                "ceiling_height_m": h, "ceiling_type": r.get("ceiling_type"), "user_limit_m": limit,
                                                "status": "Duct in room with low ceiling; duct elevation not checked", "evidence": evidence(r, d)})
    if not lines:
        out["limitations"].append("No classified duct or pipe centrelines are available; crossings and ceiling checks need geometry.")
    if ceiling_below_m is not None and any(_number(r.get("ceiling_height_m")) is None for r in rooms):
        out["limitations"].append("Some rooms have no verified ceiling height; they were excluded from the height check.")
    return out


def change_impact(before, after, services, *, alignment=None, revision_alignment=None):
    """Stable-id revision changes and affected services; no guessed plasterboard."""
    analysis = analyse(after, services, alignment=alignment)
    previous_rooms = room_table(before)
    old_groups = defaultdict(list)
    for r in previous_rooms:
        if r.get("stable_id"): old_groups[r["stable_id"]].append(r)
    old = {k: v[0] for k, v in old_groups.items() if len(v) == 1}
    rev = revision_alignment if revision_alignment is not None else align(after, before)
    same_frame = before.get("coordinate_frame") and before.get("coordinate_frame") == after.get("coordinate_frame")
    revision_geometry_known = same_frame or _matrix(rev) is not None
    impacts = []
    for r in analysis["rooms"]:
        prev = old.get(r.get("stable_id"))
        if not prev:
            continue
        fields = [k for k in ("area_m2", "ceiling_height_m", "ceiling_type") if prev.get(k) != r.get(k)]
        previous_poly = _poly(prev)
        if previous_poly is not None and not same_frame and _matrix(rev) is not None:
            previous_poly = _poly({"polygon_px": transform(prev["polygon_px"], rev)})
        current_poly = _poly(r)
        if revision_geometry_known and previous_poly is not None and current_poly is not None:
            # Ignore polygon vertex order; account for registration residual.
            tolerance = _number(rev.get("residual_px")) or 0
            if previous_poly.hausdorff_distance(current_poly) > max(tolerance*2, 1e-6):
                fields.append("polygon_px")
        if not fields:
            continue
        aid = r["item_id"]
        flow = next((f for f in analysis["airflow"] if f["room_id"] == aid), {})
        affected, affected_terminals = [], set(flow.get("terminal_ids", []))
        if _matrix(analysis["alignment"]) is not None and current_poly is not None:
            from shapely.geometry import LineString, Point
            region = current_poly.union(previous_poly) if revision_geometry_known and previous_poly is not None else current_poly
            for d in services.get("ducts", []) + services.get("pipes", []):
                points = d.get("centreline_px", d.get("centerline_px"))
                if points and d.get("classification") != "candidate" and region.intersects(LineString(transform(points, analysis["alignment"]))):
                    affected.append(d.get("item_id"))
            for t in services.get("terminals", []):
                b = _box(t.get("bbox_px"))
                if b and region.contains(Point(transform([t.get("point_px") or _centre(b)], analysis["alignment"])[0])):
                    affected_terminals.add(t.get("item_id"))
        impacts.append({"room_id": aid, "stable_id": r["stable_id"], "changed": {k: {"before": prev.get(k), "after": r.get(k)} for k in fields},
                        "terminal_ids": sorted(affected_terminals), "service_ids": affected,
                        "ceiling_height_m": r.get("ceiling_height_m"), "ceiling_type": r.get("ceiling_type"),
                        "wall_area_m2": r.get("wall_area_m2"), "plasterboard_area_m2": r.get("plasterboard_area_m2"),
                        "evidence": [{"doc_id": before.get("doc_id", ""), "page": before.get("page", 1),
                                      "bbox_px": prev["bbox_px"], "item_ids": [prev["item_id"]], "quote": prev.get("label"), "projected": False}]
                                    + flow.get("evidence", [])})
    limitations = ["Change impact requires unique stable room ids from ingestion.",
                  "Wall and plasterboard areas are reported only when explicitly supplied; room floor area is never substituted."]
    if not revision_geometry_known:
        limitations.append("Revisions could not be aligned; shape changes and services in the old footprint are unknown.")
    return {"impacts": impacts, "analysis": analysis, "revision_alignment": rev, "limitations": limitations}


def load_sheet(doc_id, root, page=1):
    """Normalise contract artifacts plus optional xdisc-<page>.json enrichment.

    Enrichment: rooms {item_id, stable_id?, number?, label, area_m2?, bbox_px,
    polygon_px?, ceiling_height_m?, ceiling_type?}; terminals {item_id,bbox_px,
    point_px?,role: supply|extract|unknown,flow_ls?}; ducts/pipes {item_id,bbox_px,
    centreline_px,width_px?}; walls/beams/openings {item_id,polygon_px,
    fire_rating?,fire_rating_source?}; complete {terminals: bool}; height_unit?.
    All coordinates MUST refer to the actual page image, including enrichment.
    """
    folder = Path(root) / doc_id
    s = {"doc_id": doc_id, "page": page, "words": [], "rooms": [], "walls": [], "ducts": [], "terminals": []}
    for prefix in ("text", "planmap", "xdisc"):
        p = folder / f"{prefix}-{page}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
            if not isinstance(data, dict):
                raise TypeError("Expected a sheet object")
        except (OSError, ValueError, TypeError):
            s.setdefault("limitations", []).append(f"The cached {prefix} page data could not be read.")
            continue
        if prefix == "planmap":
            s.setdefault("image", data.get("image", {}))
            for it in data.get("items", []):
                props = it.get("props") or {}
                kind = it.get("kind")
                if kind == "room":
                    s["rooms"].append({**props, **it, "area_m2": props.get("area_m2_label", props.get("area_m2")),
                                       "number": props.get("number"), "ceiling_height_m": props.get("ceiling_height_m"),
                                       "ceiling_type": props.get("ceiling_type")})
                elif kind in ("wall", "beam", "opening", "duct", "pipe", "terminal"):
                    s[{"wall": "walls", "beam": "beams", "opening": "openings", "duct": "ducts", "pipe": "pipes", "terminal": "terminals"}[kind]] = s.get({"beam": "beams", "opening": "openings", "pipe": "pipes"}.get(kind, kind+"s"), []) + [{**props, **it}]
        else:
            s.update(data)
    s["doc_id"], s["page"] = doc_id, page
    image_path = folder / f"page-{page}.png"
    if image_path.exists():
        s["image_path"], s["image_stamp"] = str(image_path), image_path.stat().st_mtime_ns
        if not s.get("image"):
            from PIL import Image
            with Image.open(image_path) as image:
                s["image"] = {"w": image.width, "h": image.height}
    return s


def adapt_pdf_page(raw, *, doc_id, image_size, rooms=None, walls=None, ducts=None, terminals=None, complete_terminals=False):
    """Awais pdf_vector/pdf_rooms/pdf_mep -> normalised page-image pixels.

    Current pdf_vector.load_page returns top-left PAGE POINTS, not pixels.
    W_pt/H_pt therefore require an explicit conversion. Future pixel output
    must declare coordinate_space='px'. Never infer this from coordinate sizes.
    Provider room/duct/wall ids are not assumed stable across revisions.
    """
    width, height = image_size
    space = raw.get("coordinate_space", "pt")
    if space == "pt":
        wp, hp = _number(raw.get("W_pt")), _number(raw.get("H_pt"))
        if not wp or not hp:
            raise ValueError("Point-space PDF output needs W_pt and H_pt")
        sx, sy = width/wp, height/hp
    elif space == "px":
        original = raw.get("image") or {}
        if not original.get("w") or not original.get("h"):
            raise ValueError("Pixel-space output needs source image dimensions")
        sx, sy = width/original["w"], height/original["h"]
    else:
        raise ValueError("Unknown PDF coordinate space")
    def point(p): return [float(p[0])*sx, float(p[1])*sy]
    def converted(rec, i, kind):
        r = dict(rec)
        if kind in ("duct", "terminal", "wall"):
            r.setdefault("classification", "unverified")
            r.setdefault("source_method", "PDF geometric rules; confirm on source")
        r.setdefault("item_id", str(r.get("id") or f"{kind}-{i+1:03}"))
        box = _box(r.get("bbox_px", r.get("bbox", r.get("label_bbox"))))
        if box: r["bbox_px"] = [box[0]*sx, box[1]*sy, box[2]*sx, box[3]*sy]
        poly = r.get("polygon_px", r.get("polygon"))
        if poly: r["polygon_px"] = [point(p) for p in poly]
        if r.get("holes"): r["holes_px"] = [[point(p) for p in hole] for hole in r["holes"]]
        line = r.get("centreline_px", r.get("centerline_px", r.get("centreline", r.get("centerline"))))
        if line is None and r.get("start_pt") is not None and r.get("end_pt") is not None:
            line = [r["start_pt"], r["end_pt"]]
        if line:
            r["centreline_px"] = [point(p) for p in line]
            if not box:
                b = _bounds(r["centreline_px"])
                # A zero-width line still needs a drawable evidence region.
                r["bbox_px"] = [b[0]-.5, b[1]-.5, b[2]+.5, b[3]+.5]
        if r.get("point_px", r.get("point")):
            r["point_px"] = point(r.get("point_px", r.get("point")))
        if r.get("center_pt") is not None:
            r["point_px"] = point(r["center_pt"])
            if not box and r.get("size_pt"):
                x, y = r["center_pt"]; h = r["size_pt"]/2
                r["bbox_px"] = [(x-h)*sx, (y-h)*sy, (x+h)*sx, (y+h)*sy]
        if r.get("width_pt") is not None: r["width_px"] = float(r["width_pt"])*math.sqrt(sx*sy)
        elif r.get("width_px") is not None: r["width_px"] *= math.sqrt(sx*sy)
        if kind == "room":
            r.setdefault("area_m2", r.get("area_printed_m2"))
            r.setdefault("label", r.get("name") or r.get("number") or "Room")
        if kind == "terminal":
            # No role inference from symbol code, colour or airflow sign.
            r.setdefault("role", r.get("air_type", "unknown"))
            flow = _number(r.get("flow_ls", r.get("ls", r.get("airflow_ls"))))
            r["flow_ls"] = abs(flow) if flow is not None else None
            r["signed_flow_ls"] = flow
        return r
    result = {"doc_id": doc_id, "page": raw.get("page", 1), "image": {"w": width, "h": height},
              "words": [{"text": w["text"], "bbox_px": [w["bbox"][0]*sx, w["bbox"][1]*sy, w["bbox"][2]*sx, w["bbox"][3]*sy]}
                        for w in raw.get("words", []) if _box(w.get("bbox"))],
              "complete": {"terminals": complete_terminals}, "provider": raw.get("reader", "pdf_mep"),
              "coordinate_space": "px", "point_to_pixel": [sx, sy]}
    for key, values, kind in [("rooms", rooms, "room"), ("walls", walls, "wall"), ("ducts", ducts, "duct"), ("terminals", terminals, "terminal")]:
        result[key] = [converted(r, i, kind) for i, r in enumerate(values or [])]
    return result


def paper_scale(page):
    """Metres per page point from an unambiguous printed metric/imperial scale.

    No default scale: the provider's convenient 1:100 fallback is deliberately
    bypassed. Multiple view scales require viewport selection by ingestion.
    """
    text = " ".join(w.get("text", "") for w in page.get("words", []))
    ratios = {float(v.replace(",", ".")) for v in re.findall(rf"(?<!\d)1\s*:\s*({NUM})(?!\d)", text)}
    imperial = re.compile(r"(\d+(?:\.\d+)?|\d+/\d+)\s*[\"″]\s*=\s*(\d+(?:\.\d+)?)\s*['′]\s*(?:-?\s*(\d+(?:\.\d+)?)\s*[\"″])?")
    for match in imperial.finditer(text):
        left = match[1]
        inches = float(left.split("/")[0])/float(left.split("/")[1]) if "/" in left else float(left)
        if inches > 0:
            ratios.add((float(match[2])*12+float(match[3] or 0))/inches)
    ratios = {v for v in ratios if v > 0 and math.isfinite(v)}
    return next(iter(ratios))*.0254/72 if len(ratios) == 1 else None


def prepare_mep_pair(base_page, service_page, *, provider=None, m_per_pt=None):
    """Offline adapter for the agreed pdf_mep API; original page space in/out.

    load(path,page_index), align(src,dst), split_mep(vent,underlay,m_per_pt=...),
    ducts(page,mask,m_per_pt), terminals(page,mask,m_per_pt) belong to Awais.
    This adapter accepts already loaded pages
    so no request ever traverses 94k PDF paths. After normalising page geometry
    with adapt_pdf_page, conjugate the returned T with point_to_pixel scales.
    A differing provider argument convention requires a change only here.
    """
    if provider is None:
        try:
            from pipeline import pdf_mep as provider
        except ImportError:
            return {"ducts": [], "terminals": [], "alignment": None, "complete": {"terminals": False},
                    "limitations": ["PDF duct/terminal provider is not installed."]}
    try:
        scale = _number(m_per_pt) if m_per_pt is not None else paper_scale(base_page)
        if scale is None or scale <= 0:
            return {"ducts": [], "terminals": [], "alignment": provider.align(service_page, base_page), "complete": {"terminals": False},
                    "limitations": ["An unambiguous printed scale or trusted scale is required; no default scale was used."]}
        split = provider.split_mep(service_page, base_page, m_per_pt=scale)
        return {"ducts": provider.ducts(service_page, split["mep"], split["m_per_pt"]),
                "terminals": provider.terminals(service_page, split["mep"], split["m_per_pt"]),
                "alignment": split.get("T"), "split_method": split.get("method"), "split_stats": split.get("stats"),
                "m_per_pt": split["m_per_pt"], "complete": {"terminals": False},
                "limitations": ["Provider extraction completeness must be established separately before absence/total checks."]}
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return {"ducts": [], "terminals": [], "alignment": None, "complete": {"terminals": False},
                "limitations": [f"PDF duct/terminal adapter unavailable ({type(exc).__name__}); no geometry guessed."]}


def adapt_alignment(raw, base, services):
    """Conjugate a point-space src->dst transform into the two PNG spaces."""
    import numpy as np
    mat = _matrix(raw)
    if mat is None:
        return {"status": "needs_manual", "matrix": None, "detail": "Provider registration is invalid."}
    b = base.get("point_to_pixel", [1, 1]); s = services.get("point_to_pixel", [1, 1])
    mat = np.diag([*b, 1]) @ mat @ np.diag([1/s[0], 1/s[1], 1])
    residual = _number(raw.get("residual_px", raw.get("residual")))
    matches = raw.get("matches", [])
    count = matches if isinstance(matches, int) else len(matches or [])
    if count < 3 or residual is None or residual < 0:
        return {"status": "needs_manual", "matrix": None, "detail": "Provider alignment needs at least three matches and a measured residual."}
    return {"status": "aligned", "matrix": mat.tolist(), "method": "pdf_mep.align",
            "residual_px": residual*max(b) if residual is not None else None,
            "anchor_count": count,
            "detail": "Provider similarity fit in page-image pixels; inspect a third grid crossing."}


@lru_cache(maxsize=8)
def _prepare_pdf(path, page, width, height, stamp):
    # pdfminer traversal is deliberately offline, bounded in-memory and cached.
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextLine
    layout = next(extract_pages(path, page_numbers=[page-1], laparams=LAParams(detect_vertical=True)))
    sx, sy = width/layout.width, height/layout.height
    words = []
    def walk(node):
        if isinstance(node, LTTextLine):
            b = [node.x0*sx, (layout.height-node.y1)*sy, node.x1*sx, (layout.height-node.y0)*sy]
            words.append({"text": node.get_text().strip(), "bbox_px": b})
        elif hasattr(node, "__iter__"):
            for child in node:
                walk(child)
    walk(layout)
    return {"page": page, "image": {"w": width, "h": height}, "words": words,
            "source": "pdf-text-layer", "complete": {"terminals": False}, "rooms": [], "ducts": [], "terminals": []}


def prepare_pdf(path, *, page=1, image_size=None, cache_dir=None):
    """Offline text fallback. Never called by ``answer``; no PDF ingest edits.

    cache_dir must be a worker-local directory, never shared data/artifacts.
    Awais's full 94k-path loader is intentionally not called in a chat request.
    """
    path = Path(path)
    if page < 1:
        raise ValueError("Pages are 1-based")
    if image_size is None:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(path) as pdf:
            pg = pdf[page-1]; image_size = tuple(round(v) for v in pg.get_size()); pg.close()
    key = hashlib.sha256(json.dumps([VERSION, str(path.resolve()), path.stat().st_mtime_ns, page, image_size]).encode()).hexdigest()
    target = Path(cache_dir) / f"{key}.json" if cache_dir else None
    if target and target.exists():
        return json.loads(target.read_text())
    s = _prepare_pdf(str(path.resolve()), page, *image_size, path.stat().st_mtime_ns)
    s = json.loads(json.dumps(s))
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(s))
    return s


def prepare_pair(base_pdf, services_pdf, *, doc_ids, image_sizes, cache_dir, pages=(1, 1), m_per_pt=None):
    """Offline ingest hook -> {base, services, alignment, findings}, disk cached.

    Run this in the existing background ingestion/compare job through heavy.sh,
    never synchronously in chat. Persist base/services as xdisc-<page>.json in
    each document's artifacts directory; ``load_sheet`` then reads them. The
    caller owns those writes. This function writes only to its explicit cache.
    No paths, guessed scales, default duct heights or IFC placements become
    source facts. The two PDFs and their own actual PNG dimensions are inputs.
    """
    paths = [Path(base_pdf), Path(services_pdf)]
    cache = Path(cache_dir)
    providers = None
    try:
        from pipeline import pdf_mep, pdf_rooms, pdf_vector
        providers = (pdf_mep, pdf_rooms, pdf_vector)
    except ImportError:
        pass
    provider_stamps = [(Path(m.__file__).stat().st_mtime_ns if getattr(m, "__file__", None) else 0,
                        getattr(m, "__version__", "")) for m in providers or []]
    key = hashlib.sha256(json.dumps([VERSION, [(str(p.resolve()), p.stat().st_mtime_ns) for p in paths], doc_ids, image_sizes,
                                    pages, m_per_pt, provider_stamps]).encode()).hexdigest()
    target = cache / f"pair-{key}.json"
    if target.exists():
        return json.loads(target.read_text())
    base, services = [prepare_pdf(p, page=pg, image_size=sz, cache_dir=cache) for p, pg, sz in zip(paths, pages, image_sizes)]
    base["doc_id"], services["doc_id"] = doc_ids
    if providers:
        try:
            raw_base, raw_services = [pdf_mep.load(str(p), pg-1) for p, pg in zip(paths, pages)]
            split = prepare_mep_pair(raw_base, raw_services, provider=pdf_mep, m_per_pt=m_per_pt)
            vector = pdf_vector.load_page(str(paths[0]), pages[0]-1)
            walls = pdf_vector.walls(vector)
            room_geometry = pdf_rooms.rooms(vector, walls)
            geometry = adapt_pdf_page(vector, doc_id=doc_ids[0], image_size=image_sizes[0], rooms=room_geometry, walls=walls)
            # A region containing multiple printed room areas is unresolved,
            # even when the upstream parser gives it a polygon.
            text_rooms = room_table(base)
            candidates = [(r, _poly(r)) for r in room_table(geometry)]
            for room in text_rooms:
                pt = _centre(room.get("area_bbox_px") or room["bbox_px"])
                matches = [(r, p) for r, p in candidates if p is not None and _inside(pt, r["polygon_px"])]
                if len(matches) == 1:
                    r, _poly_shape = matches[0]
                    held = [other for other in text_rooms if _inside(_centre(other.get("area_bbox_px") or other["bbox_px"]), r["polygon_px"])]
                    if len(held) == 1:
                        room["polygon_px"] = r["polygon_px"]
                        room["geometry_source"] = "pdf_rooms: single printed label in unmerged region"
            base["rooms"], base["walls"] = text_rooms, geometry["walls"]
            normal_services = adapt_pdf_page(raw_services, doc_id=doc_ids[1], image_size=image_sizes[1],
                                             ducts=split["ducts"], terminals=split["terminals"])
            normal_services["words"] = services["words"]
            normal_services["page"] = pages[1]
            normal_services["limitations"] = split["limitations"]
            services = normal_services
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            services.setdefault("limitations", []).append(f"PDF geometry is unavailable ({type(exc).__name__}); printed facts only.")
    else:
        services.setdefault("limitations", []).append("PDF geometry provider is not installed; printed facts only.")
    registration = align(base, services)
    result = {"base": base, "services": services, "alignment": registration,
              "findings": analyse(base, services, alignment=registration)}
    cache.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result))
    return result


def _intent(q):
    if re.search(r"\bchange impact\b|\b(?:changed?|revis\w+).*(?:affect|touch|impact)\b", q, re.IGNORECASE): return "impact"
    if re.search(r"\b(?:ducts?|pipes?).*\b(?:cross|penetrat|intersect)|\bpenetrations?\b", q, re.IGNORECASE): return "crossings"
    if re.search(r"\b(?:ducts?|pipes?).*\bceiling|\bceiling.*\b(?:ducts?|pipes?)", q, re.IGNORECASE): return "low_ceilings"
    if re.search(r"\b(?:no|without|missing)\s+(?:supply|extract)(?:\s+air)?\b", q, re.IGNORECASE): return "missing_air"
    if re.search(r"\bairflow\b|\b(?:supply|extract)\s+air.*\brooms?", q, re.IGNORECASE): return "airflow"
    if re.search(r"\broom table\b", q, re.IGNORECASE): return "rooms"
    return None


def answer(question, doc_ids, root, t0=None):
    """Small chat hook. Reads cached ingestion outputs only; $0 model cost."""
    intent = _intent(question)
    if not intent or len(doc_ids) < 2:
        return None
    t0 = t0 or time.perf_counter()
    sheets = [load_sheet(d, root) for d in doc_ids]
    # Explicit geometry can identify the service sheet even if attachment order
    # differs. Otherwise retain base/services order; never guess from filenames.
    if intent != "impact" and len(sheets) == 2 and (sheets[0].get("ducts") or sheets[0].get("terminals")) and not (sheets[1].get("ducts") or sheets[1].get("terminals")):
        sheets.reverse()
    # Revisions are selected before, after, services.
    threshold = re.search(rf"(?:below|under|threshold(?: of)?)\s*({NUM})\s*l/s\s*(?:/|per)\s*m[²2]", question, re.IGNORECASE)
    height = re.search(rf"(?:below|under|less than)\s*({NUM})\s*(mm|cm|m|ft|feet)\b", question, re.IGNORECASE)
    limit = _number(height[1])*{"mm": .001, "cm": .01, "m": 1, "ft": .3048, "feet": .3048}[height[2].lower()] if height else None
    impact = change_impact(*sheets[:3]) if intent == "impact" and len(sheets) >= 3 else None
    result = impact["analysis"] if impact else analyse(sheets[0], sheets[1], threshold_ls_m2=_number(threshold[1]) if threshold else None, ceiling_below_m=limit)
    records = impact["impacts"] if impact else result.get(intent, [])
    if intent == "missing_air":
        requested_roles = set(re.findall(r"\b(?:no|without|missing)\s+(supply|extract)\b", question.lower()))
        if requested_roles:
            records = [r for r in records if r["role"] in requested_roles]
    limitations = list(result["limitations"])
    if intent == "impact":
        limitations += impact["limitations"] if impact else ["Select the old revision, new revision and services sheet, in that order."]
    if intent == "low_ceilings" and limit is None:
        limitations.append("Specify the ceiling height to check, including its unit.")
    cites, boxes = [], []
    def cite(ev):
        b = _box(ev.get("bbox_px"))
        if not b: return None
        n = len(cites)+1
        # A long run can cross several walls; each evidence region needs its
        # own identity while the original source element ids remain cited.
        region_id = f"xdisc-region-{n}"
        ids = [region_id, *(i for i in ev.get("item_ids", []) if i != region_id)]
        quote = ev.get("quote")
        if ev.get("projected"):
            quote = "Projected location from sheet alignment; check the source sheet."
        cites.append({"n": n, "doc_id": ev["doc_id"], "page": ev.get("page", 1), "kind": "region", "bbox_px": b, "item_ids": ids, "quote": quote})
        boxes.append({"doc_id": ev["doc_id"], "item_id": ids[0], "page": ev.get("page", 1), "bbox_px": b, "label": str(n)})
        return n
    bullets = []; calculations = []
    for rec in records:
        ev = rec.get("evidence", [])
        if intent == "rooms":
            ev = [{"doc_id": sheets[0]["doc_id"], "page": sheets[0].get("page", 1), "bbox_px": rec.get("bbox_px"), "quote": rec.get("area_quote"), "item_ids": [rec["item_id"]]}]
            if _matrix(result["alignment"]) is not None and rec.get("bbox_px"):
                ev.append({"doc_id": sheets[1]["doc_id"], "page": sheets[1].get("page", 1), "bbox_px": _mapped_box(rec["bbox_px"], result["alignment"], True), "projected": True})
        marks = " ".join(f"[{n}]" for e in ev if (n := cite(e)))
        if intent == "airflow":
            arithmetic = rec["arithmetic"] or ["airflow unknown; the air terminals and room boundary need checking"]
            text = f"{rec.get('number') or rec['label']}: " + "; ".join(arithmetic)
            if "below_user_threshold" in rec:
                text += f"; {'below' if rec['below_user_threshold'] else 'meets'} the {rec['threshold_source']} threshold of {rec['threshold_ls_m2']:g} l/s/m²"
            calculations.extend(rec["arithmetic"])
        elif intent == "rooms":
            text = f"{rec.get('number') or rec['label']}: {rec.get('area_m2')} m²; ceiling " + (f"{rec.get('ceiling_type') or 'type unknown'}, {rec['ceiling_height_m']:g} m" if rec.get("ceiling_height_m") is not None else "unknown")
            if rec["association"] != "supplied": text += "; check the room name and number"
        elif intent == "crossings":
            unknown = "unverified" in (rec.get("service_classification"), rec.get("barrier_classification"))
            text = ("Unverified line intersection" if unknown else f"{rec['barrier_kind'].capitalize()} crossing candidate") + f"; {rec.get('fire_rating') or 'fire rating unknown'}; confirm service/wall type, elevation and fire seal"
        elif intent == "low_ceilings":
            text = f"Duct in a room with a {rec['ceiling_height_m']:g} m ceiling, below your {rec['user_limit_m']:g} m limit"
        elif intent == "impact":
            text = f"Changed room: {len(rec['terminal_ids'])} recorded terminals and {len(rec['service_ids'])} service runs; wall/plasterboard area " + (f"{rec['wall_area_m2']} / {rec['plasterboard_area_m2']} m²" if rec['wall_area_m2'] is not None and rec['plasterboard_area_m2'] is not None else "unknown")
        else:
            text = f"Room has no recorded {rec['role']} terminal; this does not establish compliance"
        if len(bullets) < 3: bullets.append(f"- {text.rstrip('.')}. {marks}")
    if intent == "airflow" and not records:
        # Text facts remain useful without pretending they are terminals.
        for label in result["airflow_labels"]:
            n = cite({**label, "doc_id": sheets[1]["doc_id"], "page": sheets[1].get("page", 1)})
            if len(bullets) < 3:
                bullets.append(f"- Printed airflow label: {label['quote']}; room and terminal not established. [{n}]")
    title = {"rooms": "printed room records", "airflow": "room geometry records", "missing_air": "missing-air findings",
             "crossings": "2D crossing candidates", "low_ceilings": "service runs in rooms below your ceiling limit", "impact": "changed rooms with stable ids"}[intent]
    verified_airflow = any(r.get("supply_ls") is not None or r.get("extract_ls") is not None for r in records) if intent == "airflow" else True
    if intent == "airflow" and not verified_airflow:
        headline = "**Room airflow totals cannot be verified yet.**"
    elif not records:
        headline = "**This check cannot be established from the available sheet data.**"
    elif intent == "crossings" and any("unverified" in (r.get("service_classification"), r.get("barrier_classification")) for r in records):
        headline = f"**{len(records)} possible line intersections need checking.**"
    else:
        headline = f"**{len(records)} {title}.**"
    if not cites and result["rooms"] and _matrix(result["alignment"]) is not None:
        room = result["rooms"][0]; b = room.get("bbox_px")
        if b:
            n = cite({"doc_id": sheets[0]["doc_id"], "page": sheets[0].get("page", 1), "bbox_px": b, "quote": room.get("area_quote") or room.get("label")})
            m = cite({"doc_id": sheets[1]["doc_id"], "page": sheets[1].get("page", 1), "bbox_px": _mapped_box(b, result["alignment"], True), "projected": True})
            bullets.append(f"- Room labels can be checked on the sheets; this does not establish the missing values. [{n}] [{m}]")
    if limitations:
        note = {"rooms": "Some names, room boundaries and ceiling details still need checking.",
                "airflow": "The air terminals are not fully confirmed, so missing terminals and room totals remain unknown.",
                "missing_air": "The air terminals are not fully confirmed; I cannot say which rooms have none.",
                "crossings": "Some lines may be drawing notes. Confirm each duct, wall, height and fire rating before planning seals.",
                "low_ceilings": "Ceiling heights or service types are unconfirmed; these are not clearance checks.",
                "impact": "Room matching and wall/plasterboard quantities need source data before the impact can be confirmed."}[intent]
        if intent == "low_ceilings" and limit is None:
            note = "Give a ceiling height limit with its unit, and confirm the room heights on the sheet."
        if _matrix(result["alignment"]) is None:
            note = "The sheets could not be aligned reliably. Match the same two grid crossings on both sheets."
        bullets.append("- " + note)
    reg = result["alignment"]
    confidence = .75 if records and reg.get("status") == "aligned" else .35
    if any("unverified" in (r.get("service_classification"), r.get("barrier_classification")) for r in records):
        confidence = .35
    if any(r.get("association") not in (None, "supplied") for r in records):
        confidence = .35
    if intent == "airflow" and any(r.get("supply_ls") is None or r.get("extract_ls") is None for r in records):
        confidence = .35
    steps = [{"kind": "read", "title": "Read both sheets", "text": "Printed values and source linework; projected boxes and unverified detections are labelled.", "cite": 1 if cites else None, "ok": bool(cites)},
             {"kind": "checked", "title": "Check registration", "text": f"{reg.get('anchor_count', 0)} shared labels; residual {reg.get('residual_px')} px. " + reg.get("detail", ""), "cite": None, "ok": reg.get("status") == "aligned"},
             {"kind": "calculated", "title": "Arithmetic and limits", "text": "; ".join(calculations) or "No unsupported quantity was calculated.", "cite": None, "ok": bool(calculations)},
             {"kind": "checked", "title": "Missing evidence", "text": " ".join(limitations) or "Crossings are 2D candidates; inspect source geometry and elevations.", "cite": None, "ok": not limitations}]
    return {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
            "answer": {"text_md": headline + "\n\n" + "\n".join(bullets), "value": len(records) if records and verified_airflow else None,
                       "unit": "count", "confidence": confidence, "abstained": False},
            "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": doc_ids[0], "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": [{"step": "xdisc", "detail": f"Cross-sheet {intent}; cached artifacts; no model call", "ms": 0, "model": None, "cost_usd": 0}],
            "route": "index", "cost": {"usd_total": 0, "calls": []}, "latency_ms": int((time.perf_counter()-t0)*1000),
            "xdisc": impact or result, "reasoning": {"steps": steps, "confidence": {"label": "Cross-checked" if confidence > .5 else "Estimate", "pct": round(confidence*100), "reason": "Evidence-completeness estimate, not measured extraction accuracy.", "improve": "Check projected boxes and supply missing classified geometry."}}}
