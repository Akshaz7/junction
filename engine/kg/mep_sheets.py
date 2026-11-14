"""Optional, read-only adapter to Awais's pipeline.pdf_mep API.

No PDF ingestion or default scale/ceiling height lives here. Missing optional
modules, ambiguous alignment and missing real-world scale are reported plainly.
"""
from __future__ import annotations

import importlib
import math
import re
import time
from pathlib import Path

from engine.kg.mep import positive, read_json, resolve_source

MEP_WORDS = re.compile(r"\bmep\b|ventilat|ilmanvaihto|lüftung|\blvi\b|\bhvac\b|\bduct|kanav|vvs|building services", re.I)


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _apply(T, p):
    return [T["s"] * sum(T["R"][i][j] * p[j] for j in range(2)) + T["t"][i] for i in range(2)]


def _m_per_pt(page, planmap):
    scale = (planmap or {}).get("scale") or {}
    image = (planmap or {}).get("image") or {}
    if scale.get("method") not in {"none", "door-prior", None} and scale.get("confidence", 0) >= 0.6:
        mpx, width = positive(scale.get("m_per_px")), positive(image.get("w"))
        if mpx and width:
            return mpx * width / page["W_pt"]
    from engine.scale_text import ratio_and_sheet
    ratio, _ = ratio_and_sheet(page.get("words") or [])
    return 0.0254 / 72 * ratio if positive(ratio) else None


def _room_shape(n, pm, pdf):
    from shapely.geometry import Polygon, box
    items = {x.get("item_id"): x for x in pm.get("items", [])}
    item = items.get((n.get("source") or {}).get("item_id"), {})
    dims = pm.get("image") or {}
    if not positive(dims.get("w")) or not positive(dims.get("h")):
        return None
    sx, sy = pdf["W_pt"] / dims["w"], pdf["H_pt"] / dims["h"]
    poly = item.get("polygon_px")
    if poly:
        try:
            shape = Polygon([(p[0] * sx, p[1] * sy) for p in poly])
            if shape.is_valid and not shape.is_empty:
                return shape, "room polygon"
        except (TypeError, ValueError):
            pass
    bb = item.get("bbox_px")
    if bb and len(bb) == 4:
        return box(bb[0] * sx, bb[1] * sy, bb[2] * sx, bb[3] * sy), "room bounding box"
    return None


def link_sheet_rooms(writer, source_did, target_did, source_pm, target_pm, source_pdf, target_pdf, T, m_per_pt):
    """Match existing underlay rooms after measured alignment; retain both sources."""
    from shapely.geometry import Point
    sources = [n for n in writer.nodes.values() if n["kind"] == "room" and (n.get("source") or {}).get("doc_id") == source_did
               and (n.get("source") or {}).get("page", 1) == source_pm.get("page", 1)]
    targets = [n for n in writer.nodes.values() if n["kind"] == "room" and (n.get("source") or {}).get("doc_id") == target_did
               and (n.get("source") or {}).get("page", 1) == target_pm.get("page", 1)]
    if T.get("matches", T.get("n_inliers", 0)) < 4:
        return
    residual = float(T.get("residual", T.get("rms_pt", math.inf))) * m_per_pt
    if not math.isfinite(residual) or residual > 0.1:
        return
    proposals = []
    for src in sources:
        shape = _room_shape(src, source_pm, source_pdf)
        if not shape:
            continue
        center = _apply(T, list(shape[0].centroid.coords)[0])
        hits = []
        for target in targets:
            dst = _room_shape(target, target_pm, target_pdf)
            if not dst or not dst[0].contains(Point(center)):
                continue
            a, b = src.get("props", {}).get("room_number"), target.get("props", {}).get("room_number")
            # Repeated generic names ("Office") are not unique room identities.
            label_match = bool(a and b and _norm(a) == _norm(b)) or _norm(src["label"]) == _norm(target["label"])
            if not label_match:
                continue
            distance = Point(center).distance(dst[0].centroid) * m_per_pt
            if distance <= max(0.1, 3 * residual):
                hits.append((target, distance))
        if len(hits) == 1:
            proposals.append((src, *hits[0]))
    counts = {}
    for _, dst, _ in proposals:
        counts[dst["id"]] = counts.get(dst["id"], 0) + 1
    for src, dst, distance in proposals:
        if counts[dst["id"]] != 1:
            continue
        writer.edge("same_as", src, dst, "position", 0.59,
                    {"rule": "unique same-label room centres after shared-text sheet alignment",
                     "residual_m": distance, "alignment": {"T": T, "residual": residual,
                     "matches": T.get("matches", T.get("n_inliers"))},
                     "sources": [src["source"], dst["source"]], "calibration": "not yet empirically calibrated"})


def _services(writer, did, page_number, pm, page, target_did, target_pm, target_page, T, scale, api):
    from shapely.geometry import LineString, Point
    # Explicit scale overrides pdf_mep's printed-scale fallback.
    split = api.split_mep(page, target_page, m_per_pt=scale)
    source_scale = scale * T["s"]
    ducts = api.ducts(page, split["mep"], source_scale)
    terms = api.terminals(page, split["mep"], source_scale)
    dims = (pm or {}).get("image") or {}
    sx, sy = dims.get("w", page["W_pt"]) / page["W_pt"], dims.get("h", page["H_pt"]) / page["H_pt"]
    rooms = []
    for n in list(writer.nodes.values()):
        source = n.get("source") or {}
        if n["kind"] == "room" and source.get("doc_id") == target_did and source.get("page", 1) == target_pm.get("page", 1):
            shape = _room_shape(n, target_pm, target_page)
            if shape:
                rooms.append((n, *shape))
    residual = float(T.get("residual", T.get("rms_pt", math.inf))) * scale
    alignment = {"T": T, "residual": residual, "matches": T.get("matches", T.get("n_inliers"))}
    for kind, rows in (("duct", ducts), ("terminal", terms)):
        for i, row in enumerate(rows, 1):
            if kind == "duct":
                points = [row["start_pt"], row["end_pt"]]
                shape = LineString([_apply(T, p) for p in points])
                props = {"length_m": shape.length * scale, "length_m_source": "vector sheet centreline",
                         "width_m": row.get("width_m"), "height_m": row.get("height_m")}
            else:
                points = [row["center_pt"]]
                shape = Point(_apply(T, row["center_pt"]))
                props = {"airflow_ls": row.get("airflow_ls")}
            padding = (positive(row.get("width_m")) or 0) / source_scale / 2 if kind == "duct" else (
                (positive(row.get("size_pt")) or (positive(row.get("size_m")) or 0) / source_scale) / 2)
            bbox = [max(0, min(p[0] for p in points) - padding) * sx,
                    max(0, min(p[1] for p in points) - padding) * sy,
                    min(page["W_pt"], max(p[0] for p in points) + padding) * sx,
                    min(page["H_pt"], max(p[1] for p in points) + padding) * sy]
            props["extraction"] = "vector PDF; unverified symbol/line-pair detection"
            n = writer.node(kind, did, f"mep-{page_number}-{kind}-{i}", row.get("label") or kind.capitalize(),
                            props, page=page_number, bbox=bbox)
            writer.doc_link(n, did)
            hits = [(room, region, method) for room, region, method in rooms if region.intersects(shape)]
            if kind == "terminal" and len(hits) != 1:
                continue
            for room, region, method in hits:
                ev = {"rule": f"aligned vector service intersects {method}", "alignment": alignment,
                      "residual_m": residual, "sources": [n["source"], room["source"]]}
                if kind == "duct" and method == "room polygon":
                    ev.update({"length_in_room_m": region.intersection(shape).length * scale,
                               "length_method": "aligned vector centreline clipped to room polygon"})
                writer.edge("in_room", n, room, "containment_geom", 0.5, ev)
                if kind == "terminal":
                    writer.edge("serves", n, room, "containment_geom", 0.5, ev)
    return {"ducts": len(ducts), "terminals": len(terms), "alignment": alignment}


def enrich_sheets(writer, project, root: Path, deadline):
    docs = []
    for entry in project.get("docs", []):
        entry = {"doc_id": entry} if isinstance(entry, str) else entry
        did = entry.get("doc_id")
        if not did:
            continue
        meta = {**read_json(root / did / "doc.json", {}), **entry}
        if (path := resolve_source(meta, root, "pdf")):
            docs.append((did, meta, path))
    if not docs:
        return
    notes = writer.graph.setdefault("mep", {}).setdefault("notes", [])
    try:
        api = importlib.import_module("pipeline.pdf_mep")
    except ImportError:
        note = "Vector-PDF services skipped: optional pipeline.pdf_mep is not installed; no services or alignment inferred."
        if note not in notes:
            notes.append(note)
        return
    for did, meta, path in docs:
        descriptor = " ".join(str(meta.get(k) or "") for k in ("role", "discipline", "title"))
        if not MEP_WORDS.search(descriptor):
            continue
        pms = [read_json(p, {}) for p in sorted((root / did).glob("planmap-*.json"))]
        if not pms:
            pms = [{"page": i} for i in range(1, int(meta.get("pages") or 1) + 1)]
        for pm in pms:
            if time.monotonic() > deadline:
                notes.append("Vector-PDF services deferred: graph enrichment time budget reached.")
                return
            page_no = int(pm.get("page") or 1)
            try:
                page = api.load(path, page_index=page_no - 1)
                candidates = []
                for tdid, tmeta, tpath in docs:
                    if tdid == did or MEP_WORDS.search(" ".join(str(tmeta.get(k) or "") for k in ("role", "discipline", "title"))):
                        continue
                    if meta.get("level") and tmeta.get("level") and _norm(meta["level"]) != _norm(tmeta["level"]):
                        continue
                    for target_file in sorted((root / tdid).glob("planmap-*.json")):
                        if time.monotonic() > deadline:
                            raise TimeoutError("alignment time budget reached")
                        tpm = read_json(target_file, {})
                        target = api.load(tpath, page_index=int(tpm.get("page") or 1) - 1)
                        scale = _m_per_pt(target, tpm)
                        if not scale:
                            continue
                        T = api.align(page, target)
                        if T and T.get("matches", T.get("n_inliers", 0)) >= 4 and T.get("residual", math.inf) * scale <= 0.1:
                            candidates.append((tdid, tpm, target, T, scale))
                # Do not choose between equally plausible counterpart sheets.
                if len(candidates) != 1:
                    notes.append(f"Services on {meta.get('title') or 'sheet'} page {page_no}: needs one unambiguous aligned architectural sheet with recorded scale (found {len(candidates)}).")
                    continue
                tdid, tpm, target, T, scale = candidates[0]
                link_sheet_rooms(writer, did, tdid, pm, tpm, page, target, T, scale)
                report = _services(writer, did, page_no, pm, page, tdid, tpm, target, T, scale, api)
                writer.graph["mep"].setdefault("documents", {}).setdefault(did, {}).setdefault("pdf_pages", {})[str(page_no)] = report
            except (OSError, RuntimeError, ValueError, ImportError, TimeoutError, AttributeError, TypeError, KeyError) as exc:
                notes.append(f"Vector-PDF services unavailable on page {page_no}: {type(exc).__name__}: {exc}")
