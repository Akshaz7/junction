"""Plain-code project answers over the knowledge graph, with source paths.

Public entry point: answer(question, project, root, t0=None, graph=None).
Unrecognised questions return None, leaving existing project solvers in charge.
Recognised but unsupported questions return an honest, zero-cost evidence card.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from engine.kg_impact import confidence, impact, index, number, paths

AGREEMENT = re.compile(r"\b(?:agree|agreement|cross[- ]?check|mismatch|discrepanc\w*|consistent|matches?)\b", re.I)
APPEARANCE = re.compile(r"\bwhere else\b|\b(?:other|which) (?:files|sheets|drawings|documents)\b.*\b(?:show|appear|contain|refer)\w*", re.I)
CONNECTION = re.compile(r"\b(?:what|which|how)\b.*\b(?:connected|connections?|linked)\b", re.I)
IMPACT = re.compile(r"\bif\b.*\b(?:ceiling|wall|door|window|duct|pipe)\b.*\b(?:drop\w*|lower\w*|rais\w*|mov\w*|remov\w*|delet\w*)\b", re.I)
KIND_WORDS = {"door": r"doors?", "window": r"windows?", "room": r"rooms?|spaces?",
              "wall": r"walls?", "duct": r"ducts?", "pipe": r"pipes?", "terminal": r"terminals?"}


def fold(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(text or "")).casefold()
                            if not unicodedata.combining(c)).split())


def _has(q, value):
    return bool(value and re.search(rf"(?<!\w){re.escape(fold(value))}(?!\w)", fold(q)))


def _level(q):
    from engine.projects.roles import level_from_text, level_ordinal
    # Require a level phrase: a room number such as 205 is not a storey.
    return level_ordinal(level_from_text(q))


def _on_level(node, wanted):
    from engine.projects.roles import level_ordinal
    return wanted is None or (node.get("level") is not None and level_ordinal(str(node["level"])) == wanted)


def _label(node):
    """Keep author labels but never expose a bare GUID or implementation id."""
    label = str(node.get("label") or "").strip()
    if not label or re.fullmatch(r"[0-9A-Za-z_$]{22}", label) or re.search(r"Ifc[A-Z]|\bDN0\b", label):
        return str(node.get("kind") or "item").replace("_", " ").capitalize()
    return label


def _resolve(q, graph, kind=None):
    nodes, _, _ = index(graph)
    scoped_docs = {did for n in nodes.values() if n.get("kind") == "doc" and _has(q, n.get("label"))
                   for did in n.get("doc_ids", [])}
    candidates = []
    for n in nodes.values():
        if n.get("kind") not in KIND_WORDS or (kind and n.get("kind") != kind) or not _on_level(n, _level(q)):
            continue
        if scoped_docs and not scoped_docs.intersection(n.get("doc_ids") or []):
            continue
        p = n.get("props") or {}
        names = [n.get("label"), p.get("tag"), p.get("name"), p.get("number"), p.get("mark"), p.get("room_number")]
        scores = [len(v) for v in {fold(v) for v in names if v is not None}
                  if v not in KIND_WORDS and _has(q, v)]
        if scores:
            candidates.append((sum(scores), n))
    if not candidates:
        return None, "I cannot identify that item in this project's graph. Use its room number or drawing tag."
    best = max(s for s, _ in candidates)
    matches = [n for s, n in candidates if s == best]
    if len(matches) == 1:
        return matches[0], None
    equivalent = paths(graph, matches[0]["id"], lambda a, e, b, d: e.get("kind") == "same_as", max_depth=None)
    if all(n["id"] in equivalent for n in matches[1:]):
        # Prefer a canonical member, then one with measured dimensions.
        return min(matches, key=lambda n: (bool(n.get("canonical")), -len(n.get("props") or {}), n["id"])), None
    return None, "Several unlinked items have that label. Specify the level or document before checking its connections."


def _source(node):
    s = node.get("source") or {}
    return s if isinstance(s, dict) and s.get("doc_id") else None


def _evidence(nodes):
    """One citation per source item, numbered across documents; boxes follow the primary document."""
    cites, all_boxes, seen, marks = [], [], set(), defaultdict(list)
    by_doc = defaultdict(list)
    for n in nodes:
        s = _source(n)
        if not s:
            continue
        page = s.get("page") or 1
        if not isinstance(page, int) or page < 1:
            page = 1
        key = (s["doc_id"], page, s.get("item_id"), str(s.get("bbox")))
        if key in seen:
            continue
        seen.add(key)
        box = s.get("bbox") or s.get("bbox_px")
        if not isinstance(box, (list, tuple)) or len(box) != 4 or any(number(v) is None for v in box):
            box = None
        else:
            box = [float(v) for v in box]
        iid = s.get("item_id")
        cn = len(cites) + 1
        cites.append({"n": cn, "doc_id": s["doc_id"], "page": page,
                      "kind": "region" if box else "element", "bbox_px": box,
                      "item_ids": [iid] if iid else [], "quote": None,
                      "label": _label(n), "item_kind": n.get("kind") or "item"})
        marks[n["id"]].append(cn)
        if iid:
            by_doc[s["doc_id"]].append((iid, n.get("kind")))
            if box:
                all_boxes.append({"doc_id": s["doc_id"], "item_id": iid, "page": page,
                                  "bbox_px": box, "label": str(cn), "kind": n.get("kind") or "item"})
    primary = max(by_doc, key=lambda d: len(by_doc[d])) if by_doc else (cites[0]["doc_id"] if cites else "")
    items = list(dict.fromkeys(iid for iid, _ in by_doc[primary]))
    boxes = [{k: v for k, v in b.items() if k != "doc_id"} for b in all_boxes if b["doc_id"] == primary]
    scene = {"doc_id": primary, "highlight_item_ids": items, "camera_target_item_id": items[0] if items else None,
             "item_kinds": dict(by_doc[primary])}
    return boxes, cites, scene, marks


def _path_steps(graph, chains):
    nodes, edges, _ = index(graph)
    steps, seen = [], set()
    for chain in chains:
        for eid in chain:
            if eid in seen or eid not in edges:
                continue
            e = edges[eid]
            seen.add(eid)
            steps.append({"from_label": _label(nodes[e["from"]]), "edge_kind": e["kind"],
                          "to_label": _label(nodes[e["to"]]), "method": e.get("method") or "rule",
                          "confidence": confidence(e)})
    return steps


def _result(q, project, graph, t0, headline, bullets, nodes=(), chains=(), data=None, value=None, unit=None, supported=True):
    from engine.solvers.solve import _answer_obj
    boxes, cites, scene, _ = _evidence(nodes)
    graph_path = _path_steps(graph, chains)
    conf = min((s["confidence"] for s in graph_path), default=0.0)
    if not supported:
        conf = 0.0
    marks = "".join(f"[{c['n']}]" for c in cites)
    # Structured results contain all rows; the prose remains a site-manager summary.
    text = "**" + headline + "**" + marks
    if bullets:
        text += "\n\n" + "\n".join("- " + b for b in bullets[:4])
    docs = [d if isinstance(d, str) else d["doc_id"] for d in project.get("docs", [])]
    trace = [{"step": "knowledge_graph", "detail": "Code-only graph lookup; confidence is the minimum edge confidence in the cited paths.",
              "ms": 0, "model": None, "cost_usd": 0.0}]
    res = _answer_obj(q, docs, text, value, unit, conf, False, boxes, cites, scene, trace, "index", t0)
    reason = (f"Weakest link in the evidence paths: {conf:.1%}. Link confidence is not a measured probability of correctness."
              if graph_path and supported else "No supporting graph path is recorded; this is a statement of missing evidence.")
    res["reasoning"] = {
        "steps": [{"kind": "checked" if supported else "found", "title": "Project links", "text": reason,
                   "cite": cites[0]["n"] if cites else None, "ok": bool(supported and graph_path)}],
        "confidence": {"label": "Estimate" if conf < 0.6 else "Cross-checked", "pct": int(conf * 100),
                       "reason": reason, "improve": None if conf >= 0.6 else "Check the source documents and confirm the missing or uncertain links."},
        "graph_path": graph_path,
    }
    res["graph_answer"] = data or {"shape": "missing"}
    return res


def _missing(q, project, graph, t0, why, nodes=(), chains=()):
    return _result(q, project, graph, t0, why, [], nodes, chains, supported=False)


def _comparison_kind(e, a, b):
    evidence = e.get("evidence") or {}
    props = [evidence, a.get("props") or {}, b.get("props") or {}]
    for p in props:
        k = p.get("item_kind") or p.get("kind")
        if k in KIND_WORDS:
            return k
        metric = str(p.get("metric") or p.get("prop") or p.get("property") or "")
        for kind in KIND_WORDS:
            if kind in metric:
                return kind
        if "area" in metric:
            return "room"
    return a.get("kind") if a.get("kind") == b.get("kind") else None


def _comparison_sources(graph, endpoints, kind):
    found = list(endpoints)
    # Aggregate count comparisons may point at level nodes. Cite the actual
    # member items, rather than fabricating a one-to-one element match.
    for n in endpoints:
        if n.get("kind") not in ("level", "doc", "type"):
            continue
        for item in graph.get("nodes", []):
            if item.get("kind") != kind or not set(item.get("doc_ids") or []) & set(n.get("doc_ids") or []):
                continue
            if n.get("kind") == "level" and fold(item.get("level")) != fold(n.get("level") or n.get("label")):
                continue
            found.append(item)
    return found


def _agree(q, project, graph, t0):
    nodes, _, _ = index(graph)
    doc_nodes = [n for n in nodes.values() if n.get("kind") == "doc"]
    roles = {did: (n.get("props") or {}).get("role") for n in doc_nodes for did in n.get("doc_ids", [])}
    named_docs = {did for n in doc_nodes if _has(q, n.get("label")) for did in n.get("doc_ids", [])}
    plan_model = bool(re.search(r"\bplans?\b", q, re.I) and re.search(r"\bmodels?\b", q, re.I))
    kind = next((k for k, rx in KIND_WORDS.items() if re.search(rf"\b(?:{rx})\b", q, re.I)), None)
    want = _level(q)
    matches = []
    for e in graph.get("edges", []):
        if e.get("kind") not in ("agrees", "differs") or e.get("from") not in nodes or e.get("to") not in nodes:
            continue
        a, b = nodes[e["from"]], nodes[e["to"]]
        dids = set(a.get("doc_ids") or []) | set(b.get("doc_ids") or [])
        if len(dids) < 2:
            continue
        if named_docs and not named_docs.issubset(dids):
            continue
        if plan_model and roles:
            pair_roles = {roles.get(d) for d in dids}
            if "model" not in pair_roles or not pair_roles.intersection({"plan", "scan"}):
                continue
        if kind and _comparison_kind(e, a, b) != kind:
            continue
        if want is not None and not (_on_level(a, want) or _on_level(b, want)):
            continue
        if re.search(r"\bareas?\b", q, re.I):
            evidence = e.get("evidence") or {}
            metric = str(evidence.get("metric") or evidence.get("prop") or evidence.get("property") or "")
            if "area" not in metric:
                continue
        matches.append(e)
    if not matches:
        return _missing(q, project, graph, t0, "No matching cross-file comparison is recorded in this project's graph.")
    agree = sum(e["kind"] == "agrees" for e in matches)
    pct = round(100 * agree / len(matches), 2)
    mismatches, sources = [], []
    for e in matches:
        ends = [nodes[e["from"]], nodes[e["to"]]]
        evidence_nodes = _comparison_sources(graph, ends, kind or _comparison_kind(e, *ends))
        sources.extend(evidence_nodes)
        if e["kind"] == "differs":
            mismatches.append({"edge_id": e["id"], "from_label": _label(ends[0]), "to_label": _label(ends[1]),
                               "evidence": e.get("evidence") or {}, "node_ids": [n["id"] for n in evidence_nodes]})
    _, cites, _, marks = _evidence(sources)
    for m in mismatches:
        m["citations"] = sorted({c for nid in m["node_ids"] for c in marks[nid]})
        m["doc_ids"] = sorted({c["doc_id"] for c in cites if c["n"] in m["citations"]})
    bullets = [f"{agree} of {len(matches)} recorded checks agree; {len(mismatches)} differ."]
    bullets.append("Agreement covers recorded checks only; equal counts do not prove every item matches.")
    bullets.append("Unlinked items have not been verified against another file.")
    result = _result(q, project, graph, t0, f"{pct:g}% of the recorded cross-file checks agree.", bullets, sources,
                     [[e["id"]] for e in matches], {"shape": "agreement", "checks": len(matches), "agree": agree,
                     "mismatches": mismatches}, pct, "%")
    if mismatches:
        rows = ["| Mismatch | Recorded values | Sources |", "|---|---|---|"]
        for m in mismatches:
            ev = m["evidence"]
            vals = ev.get("values")
            if vals is None:
                vals = [ev.get("from_value", ev.get("a")), ev.get("to_value", ev.get("b"))]
            if isinstance(vals, dict):
                vals = list(vals.values())
            values = " versus ".join(str(v) for v in vals) if isinstance(vals, list) and vals and all(number(v) is not None for v in vals) else "See the source values"
            labels = f"{m['from_label']} / {m['to_label']}".replace("|", " ").replace("\n", " ")
            rows.append(f"| {labels} | {values} | " + "".join(f"[{n}]" for n in m["citations"]) + " |")
        result["answer"]["text_md"] += "\n\n" + "\n".join(rows)
    return result


def _related(q, project, graph, t0, appearances):
    origin, why = _resolve(q, graph)
    if origin is None:
        return _missing(q, project, graph, t0, why)
    kinds = {"same_as"} if appearances else {"connects", "in_room", "hosted_by", "bounds", "serves", "part_of_system"}
    if appearances:
        hits = paths(graph, origin["id"], lambda a, e, b, d: e.get("kind") in kinds, max_depth=None)
        origin_docs = set(origin.get("doc_ids") or [])
        hits = {nid: h for nid, h in hits.items() if set(h["node"].get("doc_ids") or []) - origin_docs}
    else:
        hits = paths(graph, origin["id"], lambda a, e, b, d: e.get("kind") in kinds, max_depth=1)
    if not hits:
        why = (f"No linked appearance of {_label(origin)} in another document is recorded." if appearances
               else f"No connection for {_label(origin)} is recorded in this project's graph.")
        return _missing(q, project, graph, t0, why, [origin])
    entries = sorted(hits.values(), key=lambda h: (_label(h["node"]), h["node"]["id"]))
    shape = "appearances" if appearances else "connections"
    bullets = [", ".join(f"{count} {kind.replace('_', ' ')}" + ("s" if count != 1 else "")
                         for kind, count in sorted(Counter(h["node"]["kind"] for h in entries).items())) + ".",
               "; ".join(_label(h["node"]) for h in entries[:6]) + ("; more in the evidence." if len(entries) > 6 else "."),
               "Confidence follows the weakest link along each path; missing links may hide other items."]
    verb = "linked appearances in other files" if appearances else "recorded connections"
    return _result(q, project, graph, t0, f"{_label(origin)} has {len(entries)} {verb}.", bullets,
                   [origin, *(h["node"] for h in entries)], [h["why_path"] for h in entries],
                   {"shape": shape, "origin": origin["id"], "items": entries}, len(entries), "count")


def _change(q):
    if re.search(r"\bceiling\b", q, re.I):
        m = re.search(r"\bto\s+(-?\d+(?:\.\d+)?)\s*(mm|cm|met(?:er|re)s?|m|ft|feet|foot|inches|inch|in|′|')(?=\W|$)", q, re.I)
        if not m:
            return None, "State the proposed ceiling height with a unit, such as 2.4 m."
        factor = {"mm": .001, "cm": .01, "ft": .3048, "feet": .3048, "foot": .3048, "′": .3048, "'": .3048,
                  "in": .0254, "inch": .0254, "inches": .0254}.get(m[2].lower(), 1.0)
        value = float(m[1]) * factor
        if value <= 0:
            return None, "The proposed ceiling height must be greater than zero."
        return {"prop": "ceiling_height_m", "value": value}, None
    if re.search(r"\b(?:remov\w*|delet\w*)\b", q, re.I):
        return {"prop": "removed", "value": True}, None
    return {"prop": "position_m", "value": None}, None


def _impact(q, project, graph, t0):
    kind = "room" if re.search(r"\bceiling\b", q, re.I) else next((k for k in ("wall", "door", "window", "duct", "pipe") if re.search(rf"\b{k}\b", q, re.I)), None)
    origin, why = _resolve(q, graph, kind)
    if origin is None:
        return _missing(q, project, graph, t0, why)
    change, why = _change(q)
    if change is None:
        return _missing(q, project, graph, t0, why, [origin])
    entries = impact(graph, origin["id"], change)
    if not entries:
        return _missing(q, project, graph, t0, f"No affected dependencies for {_label(origin)} are recorded. This does not prove the change is safe.", [origin])
    bullets = []
    quantities = [e for e in entries if e.get("quantity_delta")]
    if quantities:
        for e in quantities[:2]:
            qty = e["quantity_delta"]
            margin = f" ± {qty['margin']:g} m²" if qty.get("margin") is not None else "; uncertainty is not recorded"
            bullets.append(f"{_label(e['node'])}: {qty['value']:+g} m² of {qty['prop'].replace('_m2', '').replace('_', ' ')}{margin} (one face, before openings).")
    tall = [e for e in entries if e.get("exceeds_ceiling")]
    if tall:
        bullets.append(f"{len(tall)} linked doors exceed the proposed ceiling height; verify their positions.")
    services = [e for e in entries if e["node"].get("kind") in ("duct", "pipe", "terminal")]
    if services:
        counts = Counter(e["node"]["kind"] for e in services)
        bullets.append("Check " + ", ".join(f"{v} {k}" + ("s" if v != 1 else "") for k, v in sorted(counts.items())) + " for clearance and service changes.")
    if not quantities:
        bullets.append("The graph lacks the dimensions needed to calculate a material quantity change.")
    bullets.append("Potential effects only. Missing links, openings, lining layers and waste need checking.")
    return _result(q, project, graph, t0, f"Changing {_label(origin)} has {len(entries)} linked items to check.", bullets,
                   [origin, *(h["node"] for h in entries)], [h["why_path"] for h in entries],
                   {"shape": "impact", "origin": origin["id"], "change": change, "items": entries}, len(entries), "count")


def answer(question: str, project: dict, root: Path, t0=None, *, graph=None):
    """Route only graph-specific questions; builds are code-only and optional."""
    q = question or ""
    route = _impact if IMPACT.search(q) else (_agree if AGREEMENT.search(q) else None)
    appearances = bool(APPEARANCE.search(q))
    if route is None and not appearances and not CONNECTION.search(q):
        return None
    t0 = time.perf_counter() if t0 is None else t0
    if graph is None:
        try:
            from engine.kg import build
            graph = build(project, root)
        except (ImportError, OSError, ValueError, TypeError):
            return _missing(q, project, {}, t0, "The project links are unavailable. Check the source documents directly.")
    if not isinstance(graph, dict):
        return _missing(q, project, {}, t0, "The project graph is still being built. Try again once its links are ready.")
    return route(q, project, graph, t0) if route else _related(q, project, graph, t0, appearances)
