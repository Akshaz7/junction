"""Conservative spatial links. Bounding boxes are explicitly estimates.

Cross-model geometry requires at least three shared room GUID anchors and a
measured registration residual; scene recentering alone is never alignment.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median


def _box(n):
    b = n.get("props", {}).get("world_bbox_m")
    try:
        if len(b) == 2 and all(len(p) == 3 for p in b) and all(math.isfinite(float(v)) for p in b for v in p):
            return b if all(b[1][i] > b[0][i] for i in (0, 2)) else None
    except (TypeError, ValueError):
        pass
    return None


def _center(b):
    return [(a + z) / 2 for a, z in zip(*b)]


def _registration(a_rooms, b_rooms):
    by_item = {n["source"]["item_id"]: n for n in b_rooms if _box(n)}
    anchors = [(a, by_item[a["source"]["item_id"]]) for a in a_rooms
               if _box(a) and a["source"]["item_id"] in by_item]
    if len(anchors) < 3:
        return None
    deltas = [[y - x for x, y in zip(_center(_box(a)), _center(_box(b)))] for a, b in anchors]
    translation = [median(d[i] for d in deltas) for i in range(3)]
    residual = math.sqrt(sum(sum((d[i] - translation[i]) ** 2 for i in range(3)) for d in deltas) / len(deltas))
    # Five centimetres is a physical registration tolerance, independent of file.
    if residual > 0.05:
        return None
    return {"T": [[1, 0, 0, translation[0]], [0, 1, 0, translation[1]], [0, 0, 1, translation[2]], [0, 0, 0, 1]],
            "residual": residual, "matches": len(anchors), "anchor_method": "shared room GUID",
            "anchor_item_ids": [a["source"]["item_id"] for a, _ in anchors]}


def enrich_spatial(writer):
    rooms_by_doc = defaultdict(list)
    services_by_doc = defaultdict(list)
    for n in list(writer.nodes.values()):
        did = (n.get("source") or {}).get("doc_id")
        if did and _box(n):
            if n["kind"] == "room":
                rooms_by_doc[did].append(n)
            elif n["kind"] in {"pipe", "duct", "terminal", "fixture"}:
                services_by_doc[did].append(n)
    explicit = {e["from"] for e in writer.graph["edges"] if e["kind"] == "in_room" and e["method"] == "ifc_relation"}
    registrations = {}
    for did, services in services_by_doc.items():
        own_rooms = rooms_by_doc.get(did, [])
        candidates = [(own_rooms, None)] if own_rooms else []
        # A model without rooms cannot establish a room-anchor alignment itself.
        # Core same_as may provide other measured registrations in the future.
        if own_rooms:
            for target, target_rooms in rooms_by_doc.items():
                if target != did:
                    reg = _registration(own_rooms, target_rooms)
                    if reg:
                        registrations[did, target] = reg
                        candidates.append((target_rooms, reg))
        for n in services:
            if n["id"] in explicit:
                continue
            sb = _box(n)
            for rooms, alignment in candidates:
                shift = [alignment["T"][i][3] for i in range(3)] if alignment else [0, 0, 0]
                bb = [[p[i] + shift[i] for i in range(3)] for p in sb]
                center = _center(bb)
                hits = []
                for room in rooms:
                    rb = _box(room)
                    if n.get("level") and room.get("level") and n["level"] != room["level"]:
                        continue
                    if bb[1][1] < rb[0][1] or bb[0][1] > rb[1][1]:
                        continue
                    if n["kind"] in {"terminal", "fixture"}:
                        # A point on a shared wall is ambiguous; strict interior only.
                        hit = all(rb[0][i] < center[i] < rb[1][i] for i in (0, 2))
                    else:
                        hit = all(min(bb[1][i], rb[1][i]) > max(bb[0][i], rb[0][i]) for i in (0, 2))
                    if hit:
                        hits.append(room)
                if n["kind"] in {"terminal", "fixture"} and len(hits) != 1:
                    continue
                for room in hits:
                    ev = {"rule": "service box overlaps room box; room outline not verified",
                          "service_world_bbox_m": bb, "room_world_bbox_m": _box(room),
                          "length_in_room_m": None, "length_method": "unknown; bounding box is not a centreline"}
                    if alignment:
                        ev.update({"alignment": alignment, "residual_m": alignment["residual"]})
                    writer.edge("in_room", n, room, "containment_geom", 0.5, ev)
                    if n["kind"] == "terminal":
                        writer.edge("serves", n, room, "containment_geom", 0.5,
                                    {**ev, "rule": "terminal lies over one room box; service purpose needs checking"})
    writer.graph.setdefault("mep", {}).setdefault("notes", [])
    if registrations:
        writer.graph["mep"]["registrations"] = [{"from_doc": a, "to_doc": b, **reg}
                                                   for (a, b), reg in registrations.items()]
