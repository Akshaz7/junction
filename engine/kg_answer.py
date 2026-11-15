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

AGREEMENT = re.compile(r"\b(?:dis)?agree(?:s|ment)?\b|\b(?:cross[- ]?check|mismatch\w*|discrepanc\w*|consistent|match(?:es)?)\b|\bcompare\b.*\b(?:across|between)\b.*\b(?:files|drawings|documents|plan|model)\b", re.I)
APPEARANCE = re.compile(r"\bwhere else\b|\b(?:other|which) (?:files|sheets|drawings|documents)\b.*\b(?:show|appear|contain|refer)\w*", re.I)
CONNECTION = re.compile(r"\b(?:what|which|how)\b.*\b(?:connected|connections?|linked)\b", re.I)
FILE_LINKS = re.compile(r"\b(?:how|where|which|what)\b.*\b(?:link\w*|connect\w*|relat\w*|appear\w*|show\w*|in)\b.*\b(?:all |its |the |other |which |those |these )?(?:files?|documents?|drawings?|sheets?|models?)\b|\bwhich (?:files?|documents?|drawings?|sheets?|models?)\b", re.I)
IMPACT = re.compile(r"\bif\b.*\b(?:ceiling|wall|door|window|duct|pipe)\b.*\b(?:drop\w*|lower\w*|rais\w*|mov\w*|remov\w*|delet\w*)\b", re.I)
KIND_WORDS = {"door": r"doors?", "window": r"windows?", "room": r"rooms?|spaces?",
              "wall": r"walls?", "duct": r"ducts?", "pipe": r"pipes?", "terminal": r"terminals?",
              "column": r"columns?", "slab": r"slabs?", "stair": r"stairs?|staircases?",
              "fixture": r"fixtures?", "system": r"systems?", "material": r"materials?", "type": r"types?"}


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


ROOM_WORDS = (
    ("entrance", "entry", "eingang", "eingangsbereich", "sisaankaynti", "entre"),
    ("hall", "hallway", "corridor", "flur", "gang", "kaytava", "korridor"),
    ("lobby", "foyer", "aula", "vestibule", "windfang", "eteinen"),
    ("office", "buero", "buro", "toimisto", "kontor"),
    ("kitchen", "kuche", "kueche", "keittio", "kok"),
    ("bedroom", "schlafzimmer", "makuuhuone", "sovrum"),
    ("bathroom", "bad", "badezimmer", "kylpyhuone", "badrum"),
    ("toilet", "wc", "toilette", "toalett"),
    ("meeting room", "conference room", "besprechungsraum", "kokoushuone", "motesrum"),
)


def _candidates(q, graph, kind=None):
    nodes, _, _ = index(graph)
    scoped_docs = {did for n in nodes.values() if n.get("kind") == "doc" and _has(q, n.get("label"))
                   for did in n.get("doc_ids", [])}
    candidates = []
    # Proposed dimensions are not item numbers (room 4 must not match 2.4 m).
    target = re.sub(r"-?\d+(?:\.\d+)?\s*(?:mm|cm|m|metres?|meters?|ft|feet|foot|inches|inch)\b", "", q, flags=re.I)
    concepts = [words for words in ROOM_WORDS if any(_has(target, w) for w in words)]
    for n in nodes.values():
        if n.get("kind") not in KIND_WORDS or (kind and n.get("kind") != kind) or not _on_level(n, _level(q)):
            continue
        if scoped_docs and not scoped_docs.intersection(n.get("doc_ids") or []):
            continue
        p = n.get("props") or {}
        names = [n.get("label"), p.get("tag"), p.get("name"), p.get("long_name"), p.get("number"), p.get("mark"), p.get("room_number")]
        scores = [len(v) for v in {fold(v) for v in names if v is not None}
                  if v not in KIND_WORDS and _has(target, v)]
        if not scores and n.get("kind") == "room" and concepts:
            label = " ".join(str(v) for v in names if v is not None)
            if all(any(_has(label, w) for w in words) for words in concepts):
                scores = [len(concepts)]
        if scores:
            # Redundant label/tag fields must not hide another item carrying
            # the same exact label with fewer metadata fields.
            candidates.append((max(scores), n))
    if not candidates:
        return []
    best = max(s for s, _ in candidates)
    matches = [n for s, n in candidates if s == best]
    return matches


def _clusters(graph, matches):
    parent = {n["id"]: n["id"] for n in graph.get("nodes", [])}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in graph.get("edges", []):
        if e.get("kind") == "same_as" and e.get("from") in parent and e.get("to") in parent:
            parent[find(e["from"])] = find(e["to"])
    # Optional IFC adapters can attach quantities as another page record of
    # the same source element. Its identity is document + IFC item ID, not
    # page. Local plan-map IDs, in contrast, can repeat on unrelated pages.
    source_ids = {}
    for n in graph.get("nodes", []):
        p, s = n.get("props") or {}, n.get("source") or {}
        if not s.get("doc_id") or not s.get("item_id") or not (p.get("guid") or p.get("source_method") == "ifc" or str(p.get("ifc_class") or "").startswith("Ifc")):
            continue
        key = (n.get("kind"), s["doc_id"], s["item_id"])
        if key in source_ids:
            parent[find(n["id"])] = find(source_ids[key])
        source_ids[key] = n["id"]
    groups = defaultdict(list)
    for n in matches:
        groups[find(n["id"])].append(n)
    return [sorted(group, key=lambda n: (bool(n.get("canonical")), -len(n.get("props") or {}), n["id"]))
            for group in groups.values()]


def _resolve(q, graph, kind=None):
    groups = _clusters(graph, _candidates(q, graph, kind))
    if not groups:
        return None, "I cannot identify that item in this project's graph. Use its room number or drawing tag."
    if len(groups) == 1:
        return groups[0][0], None
    return None, "Several unlinked items have that label. Specify the level or document before checking its connections."


def _source(node):
    s = node.get("source") or {}
    return s if isinstance(s, dict) and s.get("doc_id") else None


def _evidence(nodes):
    """Page citations retain every item; box labels follow the primary scene order."""
    cites, all_boxes, seen, marks, groups, source_marks = [], [], set(), defaultdict(list), {}, {}
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
            marks[n["id"]].append(source_marks[key])
            continue
        seen.add(key)
        box = s.get("bbox") or s.get("bbox_px")
        if not isinstance(box, (list, tuple)) or len(box) != 4 or any(number(v) is None for v in box):
            box = None
        else:
            box = [float(v) for v in box]
        iid = s.get("item_id")
        group = (s["doc_id"], page)
        if group not in groups:
            groups[group] = len(cites)
            cites.append({"n": len(cites) + 1, "doc_id": s["doc_id"], "page": page,
                          "kind": "region" if box else "element", "bbox_px": box,
                          "item_ids": [], "quote": (n.get("props") or {}).get("quote"),
                          "label": _label(n), "item_kind": n.get("kind") or "item"})
        cite = cites[groups[group]]
        cn = cite["n"]
        source_marks[key] = cn
        if iid and iid not in cite["item_ids"]:
            cite["item_ids"].append(iid)
        if box:
            old_box = cite["bbox_px"]
            cite["bbox_px"] = [min(old_box[0], box[0]), min(old_box[1], box[1]),
                               max(old_box[2], box[2]), max(old_box[3], box[3])] if old_box else box
            cite["kind"] = "region"
        if cite.get("item_kind") != n.get("kind"):
            cite.pop("item_kind", None)
        marks[n["id"]].append(cn)
        if iid:
            by_doc[s["doc_id"]].append((iid, n.get("kind")))
            if box:
                all_boxes.append({"doc_id": s["doc_id"], "item_id": iid, "page": page,
                                  "bbox_px": box, "label": str(cn), "kind": n.get("kind") or "item"})
    primary = max(by_doc, key=lambda d: len(by_doc[d])) if by_doc else (cites[0]["doc_id"] if cites else "")
    items = list(dict.fromkeys(iid for iid, _ in by_doc[primary]))
    positions = {iid: i + 1 for i, iid in enumerate(items)}
    boxes = [{**{k: v for k, v in b.items() if k != "doc_id"}, "label": str(positions[b["item_id"]])}
             for b in all_boxes if b["doc_id"] == primary][:300]
    scene = {"doc_id": primary, "highlight_item_ids": items, "camera_target_item_id": items[0] if items else None,
             "item_kinds": dict(by_doc[primary])}
    for cite in cites:
        if len(cite["item_ids"]) > 1:
            cite["label"] = f"{len(cite['item_ids'])} indexed items on page {cite['page']}"
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
            steps.append({"from_id": e["from"], "from_label": _label(nodes[e["from"]]), "edge_kind": e["kind"],
                          "to_id": e["to"], "to_label": _label(nodes[e["to"]]), "method": e.get("method") or "rule",
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
    res["answer"]["confidence"] = conf  # Do not round a calibrated link upwards to 100%.
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


def _comparison_sources(graph, endpoints, kind, evidence=None):
    found = list(endpoints)
    explicit = (evidence or {}).get("sources")
    if isinstance(explicit, list) and explicit:
        for s in explicit:
            if not isinstance(s, dict) or not s.get("doc_id"):
                continue
            ids = s.get("item_ids")
            if ids is None:
                ids = [s["item_id"]] if s.get("item_id") else []
            members = [n for n in graph.get("nodes", []) if (ns := _source(n))
                       and ns["doc_id"] == s["doc_id"] and ns.get("item_id") in ids]
            found.extend(members)
            if not members:
                # Zero is a valid indexed count. Preserve that document as a
                # citation without inventing an element or drawing box.
                endpoint = next((n for n in endpoints if s["doc_id"] in n.get("doc_ids", [])), {})
                found.append({"id": f"comparison-source:{s['doc_id']}:{endpoint.get('id', '')}",
                              "kind": endpoint.get("kind", "doc"), "label": _label(endpoint),
                              "source": {"doc_id": s["doc_id"], "page": s.get("page") or 1,
                                         "item_id": None, "bbox": s.get("bbox")}})
        return found
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
    from engine.kg_comparison import count_comparisons, pair_allowed
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
        if not pair_allowed(a, b, roles, named_docs, plan_model):
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
    computed = []
    if not re.search(r"\bareas?\b", q, re.I):
        def comparison_key(e):
            ev = e.get("evidence") or {}
            return (tuple(sorted((e["from"], e["to"]))), ev.get("property") or ev.get("metric") or ev.get("prop"))
        recorded = {comparison_key(e) for e in matches}
        computed = [e for e in count_comparisons(graph, kind=kind, wanted=want, named_docs=named_docs, plan_model=plan_model)
                    if comparison_key(e) not in recorded]
        if computed:
            matches.extend(computed)
            # A local view adds transparent rule steps; source nodes/edges and
            # the persistent project graph are never modified by a chat query.
            graph = {**graph, "edges": [*graph.get("edges", []), *computed]}
    if not matches:
        return _missing(q, project, graph, t0, "No matching cross-file comparison is recorded in this project's graph.")
    agree = sum(e["kind"] == "agrees" for e in matches)
    pct = round(100 * agree / len(matches), 2)
    mismatches, sources = [], []
    for e in matches:
        ends = [nodes[e["from"]], nodes[e["to"]]]
        evidence_nodes = _comparison_sources(graph, ends, kind or _comparison_kind(e, *ends), e.get("evidence"))
        sources.extend(evidence_nodes)
        if e["kind"] == "differs":
            mismatches.append({"edge_id": e["id"], "from_label": _label(ends[0]), "to_label": _label(ends[1]),
                               "evidence": e.get("evidence") or {}, "node_ids": [n["id"] for n in evidence_nodes]})
    _, cites, _, marks = _evidence(sources)
    for m in mismatches:
        m["citations"] = sorted({c for nid in m["node_ids"] for c in marks[nid]})
        m["doc_ids"] = sorted({c["doc_id"] for c in cites if c["n"] in m["citations"]})
    bullets = [f"{agree} of {len(matches)} source-value checks agree; {len(mismatches)} differ."]
    bullets.append("Agreement covers the checked values only; equal counts do not prove every item matches.")
    bullets.append("Unlinked items have not been verified against another file.")
    if any((e.get("evidence") or {}).get("derived") for e in computed):
        bullets.append("Some plans are derived from a model; matching their counts is not an independent drawing check.")
    chains = [[e["id"], *(e.get("evidence") or {}).get("identity_edges", [])] for e in matches]
    comparisons = [{"edge_id": e["id"], "kind": e["kind"], "from_id": e["from"], "to_id": e["to"],
                    "evidence": e.get("evidence") or {}, "confidence": confidence(e)} for e in matches]
    result = _result(q, project, graph, t0, f"{pct:g}% of the checked cross-file values agree.", bullets, sources,
                     chains, {"shape": "agreement", "checks": len(matches), "agree": agree,
                     "mismatches": mismatches, "comparisons": comparisons, "computed_checks": len(computed)}, pct, "%")
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


def _appearances(q, project, graph, t0, kind):
    groups = _clusters(graph, _candidates(q, graph, kind))
    if not groups:
        return _missing(q, project, graph, t0, "I cannot identify that item in this project's graph. Use its room number or drawing tag.")
    data_groups, sources, entries = [], [], []
    for group in groups:
        origin = group[0]
        def appears(a, e, b, depth):
            return (e.get("kind") == "same_as" or
                    (e.get("kind") == "references" and e.get("to") == a["id"] and b.get("kind") == "sheet_ref"))
        hits = paths(graph, origin["id"], appears, max_depth=None)
        origin_docs = set(origin.get("doc_ids") or [])
        items = sorted((h for h in hits.values() if set(h["node"].get("doc_ids") or []) - origin_docs),
                       key=lambda h: h["node"]["id"])
        sources.extend([*group, *(h["node"] for h in items)])
        entries.extend(items)
        data_groups.append({"origin": origin["id"], "label": _label(origin), "level": origin.get("level"),
                            "items": items, "matched_nodes": [n["id"] for n in group]})
    if not entries and len(groups) == 1:
        return _missing(q, project, graph, t0, f"No linked appearance of {_label(groups[0][0])} in another document is recorded.", sources)
    headline = (f"{_label(groups[0][0])} has {len(entries)} linked appearance{'s' if len(entries) != 1 else ''} in other files."
                if len(groups) == 1 else f"{len(groups)} distinct items share this label; their appearances are grouped below.")
    bullets = ["Items are grouped by recorded identity links, not by their shared label.",
               "A sheet reference shows a mention; it does not prove that the physical items are identical.",
               "Missing links may hide further appearances."]
    result = _result(q, project, graph, t0, headline, bullets, sources, [h["why_path"] for h in entries],
                     {"shape": "appearances", "origin": groups[0][0]["id"] if len(groups) == 1 else None,
                      "groups": data_groups, "items": entries}, len(entries), "count", supported=bool(entries))
    # Every ambiguous candidate remains inspectable with a file, page and cite.
    titles = {d: _label(n) for n in graph.get("nodes", []) if n.get("kind") == "doc" for d in n.get("doc_ids", [])}
    _, _, _, marks = _evidence(sources)
    rows = ["| Item group | Level | File and page | Sources |", "|---|---|---|---|"]
    for i, group in enumerate(data_groups, 1):
        members = {n["id"]: n for n in sources if n["id"] in group["matched_nodes"]}
        members.update({h["node"]["id"]: h["node"] for h in group["items"]})
        for n in members.values():
            s = _source(n)
            if not s:
                continue
            cells = [f"{i}: {_label(n)}", n.get("level") or "Not stated",
                     f"{titles.get(s['doc_id'], 'Source document')}, page {s.get('page') or 1}"]
            rows.append("| " + " | ".join(str(c).replace("|", " ").replace("\n", " ") for c in cells)
                        + " | " + "".join(f"[{c}]" for c in marks[n["id"]]) + " |")
    result["answer"]["text_md"] += "\n\n" + "\n".join(rows)
    return result


def _related(q, project, graph, t0, appearances):
    named_kinds = [(m.start(), k) for k, rx in KIND_WORDS.items() if (m := re.search(rf"\b(?:{rx})\b", q, re.I))]
    kind = min(named_kinds)[1] if named_kinds else None
    if appearances:
        return _appearances(q, project, graph, t0, kind)
    origin, why = _resolve(q, graph, kind)
    if origin is None:
        return _missing(q, project, graph, t0, why)
    kinds = {"connects", "in_room", "hosted_by", "bounds", "serves", "part_of_system",
                                           "same_as", "references", "flags", "changed", "has_type", "made_of"}
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
    verb = ("linked appearance in another file" if len(entries) == 1 else "linked appearances in other files") if appearances else ("recorded connection" if len(entries) == 1 else "recorded connections")
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


def _distinct(entries, graph, origin):
    """Group equivalent source records for summaries, retaining every citation."""
    parent = {n["id"]: n["id"] for n in graph.get("nodes", [])}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in graph.get("edges", []):
        if e.get("kind") == "same_as" and e.get("from") in parent and e.get("to") in parent:
            a, b = find(e["from"]), find(e["to"])
            parent[max(a, b)] = min(a, b)
    groups = defaultdict(list)
    for entry in entries:
        key = find(entry["node"]["id"])
        if key != find(origin["id"]):
            groups[key].append(entry)
    selected = []
    for group in groups.values():
        # A supported quantity in the anchor document is easiest to verify.
        pick = max(group, key=lambda e: (bool(e.get("quantity_delta")),
                   bool(set(e["node"].get("doc_ids") or []) & set(origin.get("doc_ids") or [])), e["confidence"]))
        selected.append(pick)
    return selected


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
    distinct = _distinct(entries, graph, origin)
    quantities = [e for e in distinct if e.get("quantity_delta")]
    if quantities:
        for e in quantities[:2]:
            qty = e["quantity_delta"]
            margin = f" ± {qty['margin']:g} m²" if qty.get("margin") is not None else "; uncertainty is not recorded"
            bullets.append(f"{_label(e['node'])}: {qty['value']:+g} m² of {qty['prop'].replace('_m2', '').replace('_', ' ')}{margin}, if its full face follows this ceiling (before openings).")
    tall = [e for e in distinct if e.get("exceeds_ceiling")]
    if tall:
        bullets.append(f"{len(tall)} linked doors exceed the proposed ceiling height; verify their positions.")
    services = [e for e in distinct if e["node"].get("kind") in ("duct", "pipe", "terminal")]
    if services:
        counts = Counter(e["node"]["kind"] for e in services)
        length_rows = [e for e in services if (e.get("affected_quantity") or {}).get("unit") == "m"]
        length_note = ""
        if length_rows:
            e = length_rows[0]
            qty = e["affected_quantity"]
            scope = "inside this room" if qty.get("scope") == "inside_room" else "whole run; in-room length unknown"
            length_note = f" {_label(e['node'])}: {qty['value']:g} m ({scope})."
        bullets.append("Check " + ", ".join(f"{v} {k}" + ("s" if v != 1 else "") for k, v in sorted(counts.items())) + " for clearance and service changes." + length_note)
    if not quantities:
        bullets.append("Recorded ceiling heights disagree; resolve them before calculating quantities." if (origin.get("props") or {}).get("ceiling_height_note")
                       else "The graph lacks the dimensions needed to calculate a material quantity change.")
    bullets.append("Potential effects only. Missing links, openings, lining layers and waste need checking.")
    note_sources = []
    for i, note in enumerate((origin.get("props") or {}).get("ceiling_height_notes") or []):
        s = note.get("source") or {}
        if s.get("doc_id"):
            note_sources.append({"id": f"ceiling-note:{origin['id']}:{i}", "kind": "sheet_ref", "label": "Ceiling height note",
                                 "source": s, "props": {"quote": s.get("quote")}})
    action = f"Setting the ceiling in {_label(origin)} to {change['value']:g} m" if change["prop"] == "ceiling_height_m" else f"Changing {_label(origin)}"
    return _result(q, project, graph, t0, f"{action} has {len(distinct)} distinct linked items to check.", bullets,
                   [origin, *(h["node"] for h in entries), *note_sources], [h["why_path"] for h in entries],
                   {"shape": "impact", "origin": origin["id"], "change": change, "items": entries,
                    "distinct_items": [e["node"]["id"] for e in distinct]}, len(distinct), "count")


def _file_links(q, project, graph, t0, kind=None):
    """How one item links to the project's other files: its node, level, and every cross-file edge, naming the files."""
    matches = _candidates(q, graph, kind)
    if not matches:
        return None
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    titles = {d: _label(n) for n in nodes.values() if n.get("kind") == "doc" for d in n.get("doc_ids", [])}
    edges = graph.get("edges", [])
    by_node = {}
    for e in edges:
        by_node.setdefault(e["from"], []).append(e)
        by_node.setdefault(e["to"], []).append(e)
    rows, linked_files, shown = [], set(), []
    for m in sorted(matches, key=lambda n: n["id"]):
        mdocs = set(m.get("doc_ids") or [])
        file = ", ".join(titles.get(d, d) for d in sorted(mdocs))
        found = False
        for e in by_node.get(m["id"], []):
            other = nodes.get(e["to"] if e["from"] == m["id"] else e["from"])
            if other is None or e.get("kind") not in {"same_as", "references"}:
                continue
            odocs = set(other.get("doc_ids") or []) - mdocs
            if not odocs:
                continue
            found = True
            linked_files |= odocs
            shown.append(other)
            rows.append((file, _label(m), m.get("level") or "Not stated",
                         f"{e['kind'].replace('_', ' ')} ({e.get('method', 'rule').replace('_', ' ')}) -> "
                         f"{_label(other)} in {', '.join(titles.get(d, d) for d in sorted(odocs))}"))
        if not found:
            rows.append((file, _label(m), m.get("level") or "Not stated", "no recorded link to another file"))
    # No identity link: say which other files hold items on the same storey.
    same_level = []
    if not linked_files:
        from engine.kg.matching import level_key
        mdocs = {d for m in matches for d in m.get("doc_ids") or []}
        wanted = {level_key(m.get("level")) for m in matches if m.get("level")}
        counts = {}
        for n in nodes.values():
            d = (n.get("doc_ids") or [None])[0]
            if d is None or d in mdocs or n.get("kind") in {"project", "doc", "level", "sheet_ref", "type", "material", "system", "issue", "change"}:
                continue
            if level_key(n.get("level")) in wanted and wanted != {""}:
                counts.setdefault(d, Counter())[n["kind"]] += 1
        for d, c in sorted(counts.items()):
            same_level.append(f"{titles.get(d, d)} holds " + ", ".join(f"{v} {k}{'s' if v != 1 else ''}" for k, v in sorted(c.items())) + " on the same level")
    label = _label(matches[0])
    if linked_files:
        files = linked_files | {d for m in matches for d in m.get("doc_ids") or []}
        headline = f"{label} is tied together across {len(files)} files: " + ", ".join(sorted(titles.get(d, d) for d in files)) + "."
    else:
        headline = f"No recorded link ties {label} to another file."
    bullets = []
    if same_level:
        bullets.append("Other files with items on the same level (no identity link): " + "; ".join(same_level[:4]) + ".")
    elif not linked_files:
        bullets.append("No other file has items on that level, so there is nothing to link it to.")
    bullets.append("Links are same_as (same item), references (a sheet mentions it) and level matches; missing links may hide others.")
    table = ["| File | Item | Level | Link |", "|---|---|---|---|"] + ["| " + " | ".join(str(c).replace("|", " ") for c in r) + " |" for r in rows[:40]]
    result = _result(q, project, graph, t0, headline, bullets, [*matches, *shown], [],
                     {"shape": "file_links", "origin": matches[0]["id"], "linked_docs": sorted(linked_files),
                      "same_level": same_level, "items": [{"id": n["id"]} for n in shown]},
                     len(linked_files), "count", supported=bool(linked_files or same_level))
    result["answer"]["text_md"] += "\n\n" + "\n".join(table)
    return result


def answer(question: str, project: dict, root: Path, t0=None, *, graph=None):
    """Route only graph-specific questions; builds are code-only and optional."""
    q = question or ""
    route = _impact if IMPACT.search(q) else (_agree if AGREEMENT.search(q) else None)
    appearances = bool(APPEARANCE.search(q))
    file_links = route is None and not appearances and bool(FILE_LINKS.search(q)) and bool(re.search(r"\blinks?\b|\bconnect\w*|\bwhich (?:files?|documents?|drawings?|sheets?|models?)\b|\ball (?:its )?files\b", q, re.I))
    if route is None and not appearances and not file_links and not CONNECTION.search(q):
        return None
    t0 = time.perf_counter() if t0 is None else t0
    if graph is None:
        try:
            from engine.kg import build
            graph = build(project, root)
        except Exception:  # an unreadable source or optional adapter cannot break project chat
            return _missing(q, project, {}, t0, "The project links are unavailable. Check the source documents directly.")
    if not isinstance(graph, dict):
        return _missing(q, project, {}, t0, "The project graph is still being built. Try again once its links are ready.")
    if file_links and not CONNECTION.search(q):
        named = [(m.start(), k) for k, rx in KIND_WORDS.items() if (m := re.search(rf"\b(?:{rx})\b", q, re.I))]
        res = _file_links(q, project, graph, t0, min(named)[1] if named else None)
        if res is not None:
            return res
        return None   # not an identifiable item: leave the question to the normal engine
    return route(q, project, graph, t0) if route else _related(q, project, graph, t0, appearances)
