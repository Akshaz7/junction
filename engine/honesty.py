"""Evidence gates for quantities: missing source data is a terminal answer.

These checks use document content and physical units, never a document identity.
PDF extraction belongs to ingestion; the optional hook below only reads results.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from engine.solvers.data import Doc, Item, load_doc, load_sheet_parent

FIRE = re.compile(r"fire[ -]rat\w*|fire resistance|feuerwiderstand|paloluokka|brandklass", re.I)
LENGTH = re.compile(r"\blength\b|\bhow long\b|\b(?:linear|running)\s+(?:metres?|meters?|feet)\b|\bmetres?\b|\bmeters?\b", re.I)
DUCT = re.compile(r"\bducts?\b|\bductwork\b|\bventilation (?:runs?|lines?)\b|\bilmanvaihtokanav\w*|\blüftungskan\w*|\bventilationskanal\w*", re.I)
PIPE = re.compile(r"\bpipes?\b|\bpiping\b|\bpipework\b", re.I)


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def unavailable(question, doc_ids, reason, t0=None, *, doc=None, items=()):
    from engine.solvers.solve import _answer_obj, _evidence, _step
    boxes, cites, scene = _evidence(doc, list(items)) if doc else ([], [], {
        "doc_id": doc_ids[0] if doc_ids else "", "highlight_item_ids": [], "camera_target_item_id": None})
    res = _answer_obj(question, doc_ids, reason, None, None, 0., True, boxes, cites, scene,
                      [_step("missing_data", reason)], "planmap" if doc and doc.mode == "planmap" else "index",
                      t0 or time.perf_counter())
    res["reasoning"] = {"steps": [{"kind": "checked", "title": "Missing data", "text": reason.replace("**", ""),
                                    "cite": 1 if cites else None, "ok": False}],
                        "confidence": {"label": "Estimate", "pct": 0, "reason": "The requested source measurement is unavailable.",
                                       "improve": "Provide the drawing or schedule with the missing measurement."}}
    return res


def _json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def room_boundary_problem(rooms):
    """Overlapping/nested room regions cannot be independent skirting outlines."""
    from shapely.geometry import Polygon
    polygons = []
    for room in rooms:
        if not room.polygon_px or len(room.polygon_px) < 3:
            return "Measured room outlines are missing; detection boxes are not wall boundaries."
        try:
            poly = Polygon(room.polygon_px)
            if not poly.is_valid or poly.area <= 0:
                return "A room outline is invalid; no perimeter was substituted."
            for other, page in polygons:
                if page == room.page and poly.intersection(other).area > 1e-6:
                    return "Room outlines overlap or contain one another; open zones cannot be counted as separate wall boundaries."
            polygons.append((poly, room.page))
        except (TypeError, ValueError):
            return "A room outline cannot be measured."
    return None


def pdf_mep_lengths(doc_id: str, root: Path) -> list[dict]:
    """Optional Awais hook, with no PDF imports or extraction at answer time.

    Ingestion may write mep-lengths.json: {"runs": [{"item_id": str,
    "kind": "duct"|"pipe", "length_m": number, "page": int,
    "bbox_px": [x0,y0,x1,y1], "source": "pdf_mep"}]}. Lengths must be
    unit-calibrated centreline lengths; boxes identify the source runs.
    Missing/unavailable sidecars return [], never zero metres.
    """
    rows = _json(Path(root) / doc_id / "mep-lengths.json").get("runs", [])
    return rows if isinstance(rows, list) else []


def plan_services_length(question, doc, root, t0=None):
    """Measure the requested service, never substitute pipes for ducts."""
    if not LENGTH.search(question) or not (DUCT.search(question) or PIPE.search(question)):
        return None
    if doc.mode == "ifc":
        return None  # engine.mep owns IFC systems, units and stored quantities.
    from engine.scales import item_scale
    from engine.solvers.solve import _answer_obj, _evidence, _step
    kinds = ({"duct"} if DUCT.search(question) else set()) | ({"pipe"} if PIPE.search(question) else set())
    noun = " and ".join(k + "s" for k in sorted(kinds))
    items = [i for i in doc.items if i.kind in kinds or i.props.get("mep_kind") in kinds]
    seen = {i.item_id for i in items}
    for row in pdf_mep_lengths(doc.doc_id, root):
        if not isinstance(row, dict) or row.get("kind") not in kinds or not row.get("item_id") or row["item_id"] in seen:
            continue
        bb = row.get("bbox_px")
        if not isinstance(bb, list) or len(bb) != 4:
            continue
        items.append(Item(row["item_id"], row["kind"], page=row.get("page", 1), bbox_px=bb,
                          q={"length_m": row.get("length_m")}, source=row.get("source", "")))
        seen.add(row["item_id"])
    if not items:
        service = " and ".join(sorted(kinds))
        return unavailable(question, [doc.doc_id], f"**The {noun} cannot be measured from this sheet.** No measured {service} runs are indexed; this does not establish that none are drawn.", t0, doc=doc)
    values = []
    for item in items:
        value = positive(item.q.get("length_m") or item.props.get("length_m"))
        if value is None:
            scale = item_scale(item, doc.scale)
            k = positive(scale.get("m_per_px")) if scale.get("method") not in (None, "none", "door-prior") else None
            pts = item.props.get("centerline_px") or item.props.get("polyline_px")
            if k and pts and len(pts) >= 2:
                try:
                    value = positive(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) * k)
                except (ValueError, TypeError):
                    pass
        if value is None or not item.bbox_px:
            return unavailable(question, [doc.doc_id], f"**A total length for {noun} is unavailable.** Some runs have no calibrated centreline length or source box; no partial total was substituted.", t0, doc=doc, items=items)
        values.append(value)
    total = round(sum(values), 2)
    boxes, cites, scene = _evidence(doc, items)
    marks = " ".join(f"[{c['n']}]" for c in cites[:3])
    res = _answer_obj(question, [doc.doc_id], f"**Measured {noun}: {total:g} m.** {marks}", total, "m", .7,
                      False, boxes, cites, scene, [_step("route", f"{noun} -> calibrated centreline lengths"),
                      _step("length", f"Sum of {len(values)} indexed runs = {total:g} m")], "planmap", t0 or time.perf_counter())
    res["reasoning"] = {"steps": [{"kind": "measured", "title": "Measured", "text": f"{len(values)} source runs; sum of centreline lengths = {total:g} m.", "cite": 1, "ok": None}],
                        "confidence": {"label": "Estimate", "pct": 70, "reason": "Measured indexed runs; check extraction completeness against the sheet.", "improve": "Check all branches and drawing scales."}}
    return res


def before(question, doc_ids, root, t0=None, *, hidden=()):
    """Early gates before readers, sheet heuristics and generic numeric routing."""
    if len(doc_ids) != 1:
        return None
    did = doc_ids[0]
    directory = Path(root) / did
    state = _json(directory / "ingest.json")
    if state.get("status") == "failed":
        return unavailable(question, doc_ids, "**This file could not be processed.** " + str(state.get("detail") or "No readable drawing data is available."), t0)
    doc = load_doc(did, Path(root)) or load_sheet_parent(did, Path(root))
    if doc and hidden:
        from dataclasses import replace
        doc = replace(doc, items=[i for i in doc.items if i.item_id not in hidden])
    # Missing properties are not an invitation to offer a typical code rating.
    if FIRE.search(question) and (not doc or doc.mode != "ifc"):
        text = " ".join(i.label or "" for i in doc.items if i.kind == "text") if doc else ""
        text += " " + " ".join(str(w.get("text") or "") for p in directory.glob("text-[0-9]*.json") for w in _json(p).get("words", []))
        recorded = bool(doc and any(i.props.get("fire_rating") for i in doc.items))
        if not recorded and not FIRE.search(text):
            return unavailable(question, doc_ids, "**The requested door fire rating is not recorded in this drawing.**", t0, doc=doc)
    from engine.router.parser import parse
    parsed = parse(question)
    from engine.analytics import BASEQ
    if BASEQ.search(question) and not (doc and any(i.kind == "room" for i in doc.items)):
        return unavailable(question, doc_ids, "**Baseboard length cannot be measured from this sheet.** No usable room outlines are recorded.", t0, doc=doc)
    if re.search(r"\bslabs?\b|\bfloor plates?\b", question, re.I) and re.search(r"\barea\b|\bthickness\b|\bhow much\b", question, re.I):
        if not doc or doc.mode != "ifc":
            return unavailable(question, doc_ids, "**Slab area by thickness is not recorded in this drawing.** Room floor areas do not establish slab thicknesses or slab areas.", t0, doc=doc)
        from engine.slab_quantities import with_source_thickness
        from engine.analytics import slab_by_type
        return slab_by_type(question, with_source_thickness(doc, root), t0)
    if parsed.type == "area" and parsed.kind == "room" and (not doc or doc.mode == "planmap"):
        rooms = [i for i in doc.items if i.kind == "room"] if doc else []
        if not rooms:
            # A printed room-area table can be used even without a geometric plan map.
            from engine.textfile import answer as text_answer
            printed = text_answer(question, doc_ids, root, t0)
            if printed and positive(printed["answer"].get("value")) and printed.get("citations"):
                return printed
            return unavailable(question, doc_ids, "**Floor area cannot be measured from this sheet.** No room boundaries or room-area table are recorded; an equipment drawing or site outline is not a floor plan.", t0, doc=doc)
    if doc:
        return plan_services_length(question, doc, root, t0)
    if LENGTH.search(question) and (DUCT.search(question) or PIPE.search(question)):
        return plan_services_length(question, Doc(did, "planmap", []), root, t0)
    return None


def validate_result(res, question):
    """A length request cannot return a count, even from a model fallback."""
    from engine.analytics import BASEQ
    ans = res.get("answer") or {}
    value = ans.get("value")
    length_request = bool((LENGTH.search(question) and (DUCT.search(question) or PIPE.search(question))) or BASEQ.search(question))
    if length_request and value is not None and str(ans.get("unit") or "").lower() not in {"m", "metre", "metres", "meter", "meters", "ft", "feet", "mm", "cm"}:
        replacement = unavailable(question, res.get("doc_ids") or [], "**Length is unavailable from the drawing data.** An object count is not a measured length.")
        replacement["trace"] = [*res.get("trace", []), *replacement["trace"]]
        replacement["cost"] = res.get("cost", replacement["cost"])
        return replacement
    return res
