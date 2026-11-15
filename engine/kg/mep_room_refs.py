"""Cited room-number references across sheets, without inventing room boundaries.

The architectural reader can merge several rooms into one polygon. A printed
room number still identifies the same room across registered sheets. Preserve
that reference separately; an anchor's small text box is never a room outline.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from engine.kg.confidence import confidence

# Functional room labels, not project-specific room names or identifier prefixes.
# The reader's ontology covers English/German; extend it for Finnish/Swedish.
ROOM_HINT = re.compile(r"\b(?:toimisto|kokous(?:tila|huone)|neuvottelu(?:tila|huone)?|käytävä|varasto|"
                       r"pesu(?:huone|tupa)|sähkö|siivous|puku(?:huone)?|porras|makuuhuone|keittiö|"
                       r"kontor|mötesrum|toalett|förråd|tvättstuga|badrum|kök|sovrum|vardagsrum|trapphus)\b", re.I)


def number(props):
    return str(props.get("room_number") or props.get("number") or "").strip().casefold()


def composite(item):
    props = item.get("props") or {}
    return bool(props.get("merged") or props.get("composite") or " / " in str(item.get("label") or "")
                or " / " in number(props))


def _words(page):
    grouped = {}
    for word in page.get("words", []):
        grouped.setdefault(str(word.get("text") or "").strip().casefold(), []).append(word)
    return grouped


def _center(word):
    b = word["bbox"]
    return [(b[0]+b[2])/2, (b[1]+b[3])/2]


def _pixels(bbox, pm, page):
    return [bbox[i] * pm["image"]["w" if i % 2 == 0 else "h"] / page["W_pt" if i % 2 == 0 else "H_pt"]
            for i in range(4)]


def link_number_references(writer, did, tdid, pm, tpm, page, target, T, scale, raw_rooms):
    """Return source-room polygons paired with target room references.

    Only unique room-number records with matching printed text qualify.
    Composite regions cannot supply a boundary. Confidence applies to identity,
    not to the quality of the detected room polygon or service symbols.
    """
    from shapely.geometry import Point, Polygon
    from engine.kg.mep_sheets import _apply
    from pipeline.pdf_rooms import ROOM_WORDS

    source_words, target_words = _words(page), _words(target)
    records = Counter(str(r.get("number") or "").strip().casefold() for r in raw_rooms)
    regions = []
    for index, record in enumerate(raw_rooms, 1):
        key = str(record.get("number") or "").strip().casefold()
        if (not record.get("label") or record.get("merged") or records[key] != 1
                or not (ROOM_WORDS.search(record["label"]) or ROOM_HINT.search(record["label"]))
                or not re.fullmatch(r"[\w.-]+", key) or not any(ch.isdigit() for ch in key)
                # A decimal-only label may be a floor area, not a room number.
                or not (key.isdigit() or any(ch.isalpha() for ch in key))
                or key not in source_words or key not in target_words):
            continue
        poly = record.get("polygon")
        source_shape = Polygon(poly) if poly else None
        label_box = record.get("label_bbox")
        matching = []
        for a in source_words[key]:
            center = _center(a)
            if source_shape is not None and source_shape.is_valid:
                if not source_shape.covers(Point(center)):
                    continue
            elif label_box and not (label_box[0] <= center[0] <= label_box[2] and label_box[1] <= center[1] <= label_box[3]):
                continue
            for b in target_words[key]:
                matching.append((math.dist(_apply(T, center), _center(b)), a, b))
        if not matching:
            continue
        _, a, b = min(matching, key=lambda row: row[0])
        residual = math.dist(_apply(T, _center(a)), _center(b)) * scale
        fit_error = T["residual"] * scale
        if residual > max(.1, 3*fit_error):
            continue
        candidates = [n for n in list(writer.nodes.values()) if n["kind"] == "room"
                      and (n.get("source") or {}).get("doc_id") == did
                      and (n.get("source") or {}).get("page", 1) == pm.get("page", 1)
                      and number(n.get("props") or {}) == key and not composite(n)]
        if len(candidates) > 1:
            continue
        source = candidates[0] if candidates else writer.node(
            "room", did, f"mep-room-ref-{pm.get('page', 1)}-{index}", record["label"],
            {"room_number": record["number"], "reference_only": True}, page=pm.get("page", 1),
            bbox=_pixels(a["bbox"], pm, page))
        targets = [n for n in list(writer.nodes.values()) if n["kind"] == "room"
                   and (n.get("source") or {}).get("doc_id") == tdid
                   and (n.get("source") or {}).get("page", 1) == tpm.get("page", 1)
                   and number(n.get("props") or {}) == key and not composite(n)]
        if len(targets) > 1:
            continue
        dest = targets[0] if targets else writer.node(
            "room", tdid, f"mep-room-ref-{tpm.get('page', 1)}-{key}", f"Room {record['number']}",
            {"room_number": record["number"], "reference_only": True}, page=tpm.get("page", 1),
            bbox=_pixels(b["bbox"], tpm, target))
        writer.doc_link(source, did)
        writer.doc_link(dest, tdid)
        alignment = {"T": T, "residual": fit_error, "matches": T["matches"]}
        evidence = {"rule": "unique room-number record has matching printed text after shared-text alignment",
                    "room_number": record["number"], "residual_m": residual, "alignment": alignment,
                    "number_printings": {"source": len(source_words[key]), "target": len(target_words[key])},
                    "sources": [source["source"], dest["source"]],
                    "text_sources": [{"doc_id": did, "page": pm.get("page",1), "bbox_pt": a["bbox"], "quote": a["text"]},
                                     {"doc_id": tdid, "page": tpm.get("page",1), "bbox_pt": b["bbox"], "quote": b["text"]}],
                    "calibration": "KG-EVAL non-heldout position reference-matcher table; identity only, not room-boundary or service-detection accuracy."}
        writer.edge("same_as", source, dest, "position", confidence("position", evidence=evidence), evidence)
        if not poly:
            continue
        shape = Polygon([_apply(T, p) for p in poly])
        # A label box is never substituted for missing room geometry.
        if shape.is_valid and not shape.is_empty and shape.contains(Point(_apply(T, _center(a)))):
            xs, ys = zip(*poly)
            boundary = {**source["source"], "bbox": _pixels([min(xs), min(ys), max(xs), max(ys)], pm, page),
                        "note": "Read-only room role extraction; boundary is an unverified estimate."}
            regions.append((dest, shape, "MEP room polygon", boundary))
    return regions


def read_rooms(path, page_number):
    """Use Awais's optional role modules read-only; never run or alter ingestion."""
    from pipeline import pdf_rooms, pdf_vector
    try:
        page = pdf_vector.load_page(path, page_number-1)
        return pdf_rooms.rooms(page, pdf_vector.walls(page))
    except Exception as exc:  # optional third-party readers use unrelated parser exception classes
        raise ValueError(f"Room reader failed ({type(exc).__name__}): {exc}") from exc
