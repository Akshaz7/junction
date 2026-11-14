"""Evidence-preserving what-if traversal over the KG contract. No source edits.

Only physical dependencies and equivalent appearances propagate an edit. A shared
document, storey, material or system is never sufficient to claim an impact.
"""
from __future__ import annotations

import heapq
import math


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def confidence(edge):
    n = number(edge.get("confidence"))
    return min(1.0, max(0.0, n)) if n is not None else 0.0


def index(graph):
    nodes = {n["id"]: n for n in graph.get("nodes", []) if n.get("id")}
    edges, adjacency = {}, {nid: [] for nid in nodes}
    for e in graph.get("edges", []):
        a, b = e.get("from"), e.get("to")
        if a not in nodes or b not in nodes or not e.get("id"):
            continue
        edges[e["id"]] = e
        adjacency[a].append((e, b))
        adjacency[b].append((e, a))
    return nodes, edges, adjacency


def paths(graph, start, allowed, max_depth=4):
    """Widest path, then shortest: confidence is the minimum edge confidence.

    Retain alternatives by (node, depth); a strong longer path must not suppress
    a shorter path needed to reach a neighbour within the traversal budget.
    """
    nodes, _, adjacency = index(graph)
    if start not in nodes:
        return {}
    pending = [(-1.0, 0, start, ())]
    seen, out = {}, {}
    while pending:
        neg, depth, nid, chain = heapq.heappop(pending)
        score = -neg
        state = nid if max_depth is None else (nid, depth)
        if seen.get(state, -1) >= score:
            continue
        seen[state] = score
        if nid != start and (nid not in out or score > out[nid]["confidence"]
                             or (score == out[nid]["confidence"] and depth < len(out[nid]["why_path"]))):
            out[nid] = {"node": nodes[nid], "why_path": list(chain), "confidence": score}
        if max_depth is not None and depth >= max_depth:
            continue
        for edge, other in adjacency[nid]:
            if edge["id"] in chain or not allowed(nodes[nid], edge, nodes[other], depth):
                continue
            heapq.heappush(pending, (-min(score, confidence(edge)), depth + 1, other, (*chain, edge["id"])))
    return out


def _margin(props, key):
    n = number(props.get(key + "_uncertainty_m"))
    return n if n is not None and n >= 0 else None


def impact(graph: dict, node_id: str, change: dict) -> list[dict]:
    """Return potential dependencies with paths and supported quantity deltas.

    change.prop: ceiling_height_m (value in m), position_m/displacement_m
    (movement), or removed (bool). No missing dimension or uncertainty is filled
    with a guessed value. Affected does not mean a clash or a rule violation.
    """
    nodes, _, _ = index(graph)
    origin = nodes.get(node_id)
    if origin is None:
        return []
    prop = change.get("prop")
    target = number(change.get("value"))
    ceiling = prop == "ceiling_height_m" and origin.get("kind") == "room"
    if ceiling and (target is None or target <= 0):
        return []
    if prop not in ("ceiling_height_m", "position_m", "displacement_m", "removed"):
        return []
    if prop == "removed" and change.get("value") is not True:
        return []

    def allowed(current, edge, other, depth):
        kind = edge.get("kind")
        if kind == "same_as":
            return True
        # The anchor may appear in other files before its dependencies are met.
        anchor = current.get("kind") == origin.get("kind")
        if ceiling:
            if anchor:
                return ((kind in ("in_room", "serves", "bounds") and edge.get("to") == current["id"])
                        or (kind == "contains" and edge.get("from") == current["id"]
                            and other.get("kind") in ("door", "duct", "pipe", "terminal", "wall", "fixture")))
            return (current.get("kind") == "wall" and kind == "hosted_by"
                    and edge.get("to") == current["id"] and other.get("kind") in ("door", "window"))
        if not anchor:
            return False
        if origin.get("kind") == "wall":
            return ((kind == "hosted_by" and edge.get("to") == current["id"])
                    or (kind == "bounds" and edge.get("from") == current["id"]))
        return ((kind in ("in_room", "hosted_by", "part_of_system") and edge.get("from") == current["id"])
                or (kind == "serves" and edge.get("from") == current["id"])
                or kind == "connects")

    hits = paths(graph, node_id, allowed)
    old = number((origin.get("props") or {}).get("ceiling_height_m"))
    result = []
    for nid in sorted(hits):
        entry = hits[nid]
        n, p = entry["node"], entry["node"].get("props") or {}
        entry["effect"] = "Also appears in another document" if n.get("kind") == origin.get("kind") else "Check this linked item"
        if ceiling and n.get("kind") == "wall":
            length = number(p.get("length_m"))
            area, height = number(p.get("area_m2")), number(p.get("height_m"))
            # An area and its height support a proportional area change, not a
            # material quantity unless that material is actually specified.
            if length is None and area is not None and height is not None and height > 0:
                length = area / height
            if old is not None and length is not None and length >= 0:
                delta = target - old
                material = str(p.get("material") or "").casefold()
                plaster = any(w in material for w in ("plasterboard", "gypsum", "kipsi", "gips"))
                uncertainty = _margin(p, "length")
                old_margin = _margin(origin.get("props") or {}, "ceiling_height")
                new_margin = number(change.get("uncertainty_m"))
                # Worst-case bound only when ALL input uncertainties are known.
                margin = None
                if all(v is not None and v >= 0 for v in (uncertainty, old_margin, new_margin)):
                    dh = old_margin + new_margin
                    margin = round(abs(delta) * uncertainty + length * dh + uncertainty * dh, 6)
                entry["quantity_delta"] = {
                    "prop": "plasterboard_area_m2" if plaster else "wall_finish_area_m2",
                    "value": round(length * delta, 6), "unit": "m2", "margin": margin,
                    "basis": {"length_m": length, "old_ceiling_height_m": old, "new_ceiling_height_m": target},
                    "note": "One wall face, before openings; lining layers and waste are not included.",
                }
        if ceiling and n.get("kind") == "door":
            height = number(p.get("height_m"))
            if height is not None:
                entry["exceeds_ceiling"] = height > target
                entry["clearance_m"] = round(target - height, 6)
                entry["effect"] = "Door height exceeds the proposed ceiling" if height > target else "Door height fits below the proposed ceiling"
        if ceiling and n.get("kind") in ("duct", "pipe", "terminal", "fixture"):
            entry["effect"] = "Check clearance and service connections at the proposed ceiling"
            if number(p.get("length_m")) is not None:
                entry["affected_quantity"] = {"value": number(p["length_m"]), "unit": "m"}
            elif n.get("kind") in ("terminal", "fixture"):
                entry["affected_quantity"] = {"value": 1, "unit": "count"}
        result.append(entry)
    return result
