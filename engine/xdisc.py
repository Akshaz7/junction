"""Cross-discipline checks in page-image pixels; no model calls or PDF ingestion.

``analyse(base, services)`` accepts normalised sheets (see ``load_sheet``).
Only classified geometry is used for quantities/intersections. Text-only rooms
remain label records, never invented polygons. ``prepare_pdf`` is an OFFLINE,
cached adapter; chat only reads ingestion outputs. Pages are contract 1-based.
Optional Awais and F-OVERLAY adapters are imported lazily after integration.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid

VERSION = 1
NUM = r"\d+(?:[.,]\d+)?"
AREA = re.compile(rf"^\s*({NUM})\s*(m[²2]|sq\.?\s*ft|ft[²2]|SF)\s*$", re.I)
FLOW = re.compile(rf"^\s*([+−-]?{NUM})\s*(l\s*/\s*s|m[³3]\s*/\s*h|cfm)\s*$", re.I)
HEIGHT = re.compile(rf"^\s*(.*?)\s*\bh\s*=\s*({NUM})\s*(mm|cm|m|ft|in)?\s*$", re.I)


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
    return out


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
        out.append(r)
    if not out:
        for w in words:
            m = AREA.fullmatch(w["text"])
            if not m:
                continue
            area = _number(m[1]) * (1 if m[2].lower().startswith("m") else .09290304)
            nearby = [v for v in words if v is not w and _near(w["bbox_px"], v["bbox_px"], 4)
                      and len(v["text"]) <= 80 and not AREA.fullmatch(v["text"])]
            # Prefer full-word text. A nearby reference is never silently a room id.
            ids = [v for v in nearby if re.fullmatch(r"(?:[A-ZÅÄÖ]{0,3}\d{1,5}[A-Z]?|\d{1,4}[./-]\d{1,3})", v["text"], re.I)]
            names = [v for v in nearby if re.fullmatch(r"[^\W\d_][^\d=]{1,60}", v["text"], re.UNICODE)]
            order = lambda v: math.dist(_centre(w["bbox_px"]), _centre(v["bbox_px"]))
            num = min(ids, key=order) if ids else None
            name = min(names, key=order) if names else None
            parts = [w, *([num] if num else []), *([name] if name else [])]
            out.append({"item_id": f"room-label-{len(out)+1:03}", "number": num["text"] if num else None,
                        "label": name["text"] if name else "Unidentified room label", "area_m2": area,
                        "area_quote": w["text"], "area_bbox_px": w["bbox_px"],
                        "bbox_px": _union([p["bbox_px"] for p in parts]), "polygon_px": None,
                        "association": "nearby text candidate"})
    for r in out:
        # Only polygon containment can associate detached ceiling tags to a room.
        ceilings = []
        for w in words:
            m = HEIGHT.fullmatch(w["text"])
            if not m or not r.get("polygon_px") or not _inside(_centre(w["bbox_px"]), r["polygon_px"]):
                continue
            unit = m[3] or sheet.get("height_unit")
            h = _number(m[2])
            metres = h * {"mm": .001, "cm": .01, "m": 1, "ft": .3048, "in": .0254}[unit] if unit else None
            ceilings.append({"type": m[1] or None, "height_m": metres, "printed": w["text"], "bbox_px": w["bbox_px"]})
        if ceilings:
            r["ceiling_labels"] = ceilings
            values = {c["height_m"] for c in ceilings}
            types = {c["type"] for c in ceilings}
            if len(values) == 1 and None not in values:
                if r.get("ceiling_height_m") is None:
                    r["ceiling_height_m"] = next(iter(values))
            if len(types) == 1:
                if r.get("ceiling_type") is None:
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
    if min(spread) < tol*4 or np.linalg.svd(dst[best]-dst[best].mean(0), compute_uv=False)[-1] < tol:
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
        p = Polygon(item.get("polygon_px") or [])
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
    from shapely.geometry import LineString, Point, box as rect
    from shapely.ops import transform as geom_transform
    reg = alignment if alignment is not None else align(base, services)
    rooms = room_table(base)
    labels = airflow_labels(services)
    out = {"version": VERSION, "base_doc_id": base.get("doc_id"), "services_doc_id": services.get("doc_id"),
           "alignment": reg, "rooms": rooms, "airflow_labels": labels, "airflow": [], "missing_air": [],
           "crossings": [], "low_ceilings": [], "unassigned_terminals": [], "limitations": []}
    if _matrix(reg) is None or reg.get("status") not in ("aligned", "manual"):
        out["limitations"].append("Sheets are not reliably aligned; room-level checks were not run.")
        return out
    residual = _number(reg.get("residual_px")) or 0
    polygons = {r["item_id"]: _poly(r) for r in rooms}
    if any(p is None for p in polygons.values()):
        out["limitations"].append("Some rooms have labels only; no terminal, duct or ceiling assignment was guessed for them.")
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
            if known and not roles[role] and not out["unassigned_terminals"]:
                out["missing_air"].append({"room_id": r["item_id"], "role": role, "status": "no recorded terminal", "evidence": ev})
        threshold = _number(threshold_ls_m2)
        if threshold is not None and row.get("supply_ls_m2") is not None:
            row["below_user_threshold"] = row["supply_ls_m2"] < threshold
            row["threshold_ls_m2"] = threshold
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
                                     "barrier_kind": wall.get("kind", "wall"), "room_ids": adjacent,
                                     "fire_rating": rating, "fire_rating_source": wall.get("fire_rating_source"),
                                     "status": "2D crossing candidate; check elevation and fire seal", "evidence": proof})
        limit = _number(ceiling_below_m)
        if limit is not None:
            for r in rooms:
                p = polygons[r["item_id"]]; h = _number(r.get("ceiling_height_m"))
                if p is not None and h is not None and h < limit and footprint.intersects(p):
                    out["low_ceilings"].append({"room_id": r["item_id"], "service_id": d.get("item_id"),
                                                "ceiling_height_m": h, "ceiling_type": r.get("ceiling_type"), "user_limit_m": limit,
                                                "status": "Duct in room with low ceiling; duct elevation not checked", "evidence": evidence(r, d)})
    if not lines:
        out["limitations"].append("No classified duct or pipe centrelines are available; crossings and ceiling checks need geometry.")
    return out


def change_impact(before, after, services, *, alignment=None):
    """Stable-id revision changes and affected services; no guessed plasterboard."""
    analysis = analyse(after, services, alignment=alignment)
    old = {r.get("stable_id"): r for r in room_table(before) if r.get("stable_id")}
    impacts = []
    for r in analysis["rooms"]:
        prev = old.get(r.get("stable_id"))
        if not prev:
            continue
        fields = [k for k in ("area_m2", "ceiling_height_m", "ceiling_type", "polygon_px") if prev.get(k) != r.get(k)]
        if not fields:
            continue
        aid = r["item_id"]
        flow = next((f for f in analysis["airflow"] if f["room_id"] == aid), {})
        affected = []
        if _matrix(analysis["alignment"]) is not None and _poly(r) is not None:
            from shapely.geometry import LineString
            for d in services.get("ducts", []) + services.get("pipes", []):
                points = d.get("centreline_px", d.get("centerline_px"))
                if points and d.get("classification") != "candidate" and _poly(r).intersects(LineString(transform(points, analysis["alignment"]))):
                    affected.append(d.get("item_id"))
        impacts.append({"room_id": aid, "stable_id": r["stable_id"], "changed": {k: {"before": prev.get(k), "after": r.get(k)} for k in fields},
                        "terminal_ids": flow.get("terminal_ids", []), "service_ids": affected,
                        "ceiling_height_m": r.get("ceiling_height_m"), "ceiling_type": r.get("ceiling_type"),
                        "wall_area_m2": r.get("wall_area_m2"), "plasterboard_area_m2": r.get("plasterboard_area_m2"),
                        "evidence": [{"doc_id": before.get("doc_id", ""), "page": before.get("page", 1),
                                      "bbox_px": prev["bbox_px"], "item_ids": [prev["item_id"]], "quote": prev.get("label"), "projected": False}]
                                    + flow.get("evidence", [])})
    return {"impacts": impacts, "analysis": analysis, "limitations": ["Change impact requires stable room ids from ingestion.",
            "Wall and plasterboard areas are reported only when explicitly supplied; room floor area is never substituted."]}


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
        data = json.loads(p.read_text())
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
    return s


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


def _intent(q):
    if re.search(r"\bchange impact\b|\b(?:changed?|revis\w+).*(?:affect|touch|impact)\b", q, re.I): return "impact"
    if re.search(r"\b(?:ducts?|pipes?).*\b(?:cross|penetrat|intersect)|\bpenetrations?\b", q, re.I): return "crossings"
    if re.search(r"\b(?:ducts?|pipes?).*\bceiling|\bceiling.*\b(?:ducts?|pipes?)", q, re.I): return "low_ceilings"
    if re.search(r"\b(?:no|without|missing)\s+(?:supply|extract)(?:\s+air)?\b", q, re.I): return "missing_air"
    if re.search(r"\bairflow\b.*\b(?:rooms?|m²|m2)|\b(?:supply|extract)\s+air.*\brooms?", q, re.I): return "airflow"
    if re.search(r"\broom table\b", q, re.I): return "rooms"
    return None


def answer(question, doc_ids, root, t0=None):
    """Small chat hook. Reads cached ingestion outputs only; $0 model cost."""
    intent = _intent(question)
    if not intent or len(doc_ids) < 2:
        return None
    t0 = t0 or time.perf_counter()
    sheets = [load_sheet(d, root) for d in doc_ids]
    # Selected order is explicit: base, services; revisions: before, after, services.
    threshold = re.search(rf"(?:below|under|threshold(?: of)?)\s*({NUM})\s*l/s\s*(?:/|per)\s*m[²2]", question, re.I)
    height = re.search(rf"(?:below|under|less than)\s*({NUM})\s*(mm|cm|m|ft|feet)\b", question, re.I)
    limit = _number(height[1])*{"mm": .001, "cm": .01, "m": 1, "ft": .3048, "feet": .3048}[height[2].lower()] if height else None
    impact = change_impact(*sheets[:3]) if intent == "impact" and len(sheets) >= 3 else None
    result = impact["analysis"] if impact else analyse(sheets[0], sheets[1], threshold_ls_m2=_number(threshold[1]) if threshold else None, ceiling_below_m=limit)
    records = impact["impacts"] if impact else result.get(intent, [])
    limitations = list(result["limitations"])
    if intent == "impact":
        limitations += impact["limitations"] if impact else ["Select the old revision, new revision and services sheet, in that order."]
    if intent == "low_ceilings" and limit is None:
        limitations.append("Specify the ceiling height to check, including its unit.")
    cites, boxes = [], []
    def cite(ev):
        b = _box(ev.get("bbox_px"))
        if not b: return None
        n = len(cites)+1; ids = ev.get("item_ids") or [f"xdisc-region-{n}"]
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
            arithmetic = rec["arithmetic"] or ["Airflow total unknown; complete classified terminals and room polygons are required."]
            text = f"{rec.get('number') or rec['label']}: " + "; ".join(arithmetic)
            if "below_user_threshold" in rec:
                text += f"; {'below' if rec['below_user_threshold'] else 'meets'} your {rec['threshold_ls_m2']:g} l/s/m² threshold"
            calculations.extend(rec["arithmetic"])
        elif intent == "rooms":
            text = f"{rec.get('number') or rec['label']}: {rec.get('area_m2')} m²; ceiling " + (f"{rec.get('ceiling_type') or 'type unknown'}, {rec['ceiling_height_m']:g} m" if rec.get("ceiling_height_m") is not None else "unknown")
            if rec["association"] != "supplied": text += "; name/number association needs checking"
        elif intent == "crossings":
            text = f"{rec['barrier_kind'].capitalize()} crossing candidate; {rec.get('fire_rating') or 'fire rating unknown'}; check elevation and fire seal"
        elif intent == "low_ceilings":
            text = f"Duct in a room with a {rec['ceiling_height_m']:g} m ceiling, below your {rec['user_limit_m']:g} m limit"
        elif intent == "impact":
            text = f"Changed room: {len(rec['terminal_ids'])} recorded terminals and {len(rec['service_ids'])} service runs; wall/plasterboard area " + (f"{rec['wall_area_m2']} / {rec['plasterboard_area_m2']} m²" if rec['wall_area_m2'] is not None and rec['plasterboard_area_m2'] is not None else "unknown")
        else:
            text = f"Room has no recorded {rec['role']} terminal; this does not establish compliance"
        if len(bullets) < 3: bullets.append(f"- {text}. {marks}")
    if intent == "airflow" and not records:
        # Text facts remain useful without pretending they are terminals.
        for label in result["airflow_labels"]:
            n = cite({**label, "doc_id": sheets[1]["doc_id"], "page": sheets[1].get("page", 1)})
            if len(bullets) < 3:
                bullets.append(f"- Printed airflow label: {label['quote']}; room and terminal not established. [{n}]")
    title = {"rooms": "printed room records", "airflow": "room geometry records", "missing_air": "rooms without recorded air terminals",
             "crossings": "2D crossing candidates", "low_ceilings": "service runs below your ceiling limit", "impact": "changed rooms with stable ids"}[intent]
    if not records:
        headline = "**This check cannot be established from the available sheet data.**"
    else:
        headline = f"**{len(records)} {title}.**"
    if limitations: bullets.append("- " + " ".join(dict.fromkeys(limitations)))
    reg = result["alignment"]
    confidence = .75 if records and reg.get("status") == "aligned" else .35
    steps = [{"kind": "read", "title": "Read both sheets", "text": "Printed values and classified geometry only; projected boxes are labelled.", "cite": 1 if cites else None, "ok": bool(cites)},
             {"kind": "checked", "title": "Check registration", "text": f"{reg.get('anchor_count', 0)} shared labels; residual {reg.get('residual_px')} px. " + reg.get("detail", ""), "cite": None, "ok": reg.get("status") == "aligned"},
             {"kind": "calculated", "title": "Arithmetic and limits", "text": "; ".join(calculations) or "No unsupported quantity was calculated.", "cite": None, "ok": bool(calculations)},
             {"kind": "checked", "title": "Missing evidence", "text": " ".join(limitations) or "Crossings are 2D candidates; inspect source geometry and elevations.", "cite": None, "ok": not limitations}]
    return {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
            "answer": {"text_md": headline + "\n\n" + "\n".join(bullets), "value": len(records) if records else None,
                       "unit": "count", "confidence": confidence, "abstained": False},
            "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": doc_ids[0], "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": [{"step": "xdisc", "detail": f"Cross-sheet {intent}; cached artifacts; no model call", "ms": 0, "model": None, "cost_usd": 0}],
            "route": "index", "cost": {"usd_total": 0, "calls": []}, "latency_ms": int((time.perf_counter()-t0)*1000),
            "xdisc": impact or result, "reasoning": {"steps": steps, "confidence": {"label": "Cross-checked" if confidence > .5 else "Estimate", "pct": round(confidence*100), "reason": "Based on sheet registration and explicit source facts.", "improve": "Check projected boxes and supply missing classified geometry."}}}
