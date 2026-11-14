"""On-demand source-index count comparisons, anchored by measured same_as links.

No cache/source mutation. Derived sheets may be compared but are explicitly
identified: agreement with their parent is not independent verification.
"""
from collections import defaultdict
from hashlib import sha256

from engine.kg_impact import confidence, index, number
from engine.projects.roles import level_ordinal


def level_key(value):
    ordinal = level_ordinal(str(value or ""))
    return ("ordinal", ordinal) if ordinal is not None else ("label", str(value or "").casefold().strip())


def pair_allowed(a, b, roles, named_docs, plan_model):
    docs = set(a.get("doc_ids") or []) | set(b.get("doc_ids") or [])
    if len(docs) < 2 or (named_docs and not named_docs.issubset(docs)):
        return False
    if plan_model and roles:
        pair_roles = {roles.get(d) for d in docs}
        return "model" in pair_roles and bool(pair_roles & {"plan", "scan"})
    return True


def count_comparisons(graph, *, kind=None, wanted=None, named_docs=(), plan_model=False):
    """Return transient count edges for linked documents with known kind coverage.

    A missing extraction is never zero. Zero on a particular level requires a
    level node plus extraction of that kind elsewhere in the same document.
    """
    nodes, _, _ = index(graph)
    docs = {d: n for n in nodes.values() if n.get("kind") == "doc" for d in n.get("doc_ids", [])}
    roles = {d: (n.get("props") or {}).get("role") for d, n in docs.items()}
    witnesses = defaultdict(list)
    for e in graph.get("edges", []):
        if e.get("kind") != "same_as" or e.get("from") not in nodes or e.get("to") not in nodes:
            continue
        a, b = nodes[e["from"]], nodes[e["to"]]
        if not pair_allowed(a, b, roles, set(named_docs), plan_model):
            continue
        for da in a.get("doc_ids") or []:
            for db in b.get("doc_ids") or []:
                if da != db:
                    witnesses[tuple(sorted((da, db)))].append(e)
    levels, pools, coverage = {}, defaultdict(dict), set()
    kinds = [kind] if kind else ["room", "door", "window"]
    for n in nodes.values():
        for d in n.get("doc_ids") or []:
            key = level_key(n.get("level") or (n.get("label") if n.get("kind") == "level" else None))
            if n.get("kind") == "level":
                levels[d, key] = n
            elif n.get("kind") in kinds and n.get("source"):
                conf = number((n.get("props") or {}).get("confidence"))
                if conf is not None and conf < .5:
                    continue
                coverage.add((d, n["kind"]))
                s = n["source"]
                pools[d, key, n["kind"]][(s.get("page") or 1, s.get("item_id") or n["id"])] = n
    result = []
    for (da, db), links in sorted(witnesses.items()):
        for d, key in sorted(levels, key=str):
            if d != da or (db, key) not in levels or (wanted is not None and key != ("ordinal", wanted)):
                continue
            # Anchor this floor to an identity link on the same floor; a match
            # somewhere else in the building cannot establish floor alignment.
            local = [e for e in links if level_key(nodes[e["from"]].get("level")) == key
                     and level_key(nodes[e["to"]].get("level")) == key]
            if not local:
                continue
            witness = max(local, key=confidence)
            for k in kinds:
                if (da, k) not in coverage or (db, k) not in coverage:
                    continue
                a, b = levels[da, key], levels[db, key]
                members = [list(pools[d, key, k].values()) for d in (da, db)]
                values = [len(m) for m in members]
                confs = [confidence(witness)]
                for m in members:
                    for n in m:
                        c = number((n.get("props") or {}).get("confidence"))
                        confs.append(min(1, max(0, c)) if c is not None else 1)
                evidence = {"rule": "per_level_index_counts", "property": k + "_count", "values": values,
                            "level": a.get("level") or a["label"], "identity_edges": [witness["id"]],
                            "diff_pct": 100 * abs(values[0]-values[1]) / max(values) if max(values) else 0,
                            "sources": [{"doc_id": d, "item_ids": [n["source"].get("item_id") for n in group]}
                                        for d, group in zip((da, db), members)],
                            "derived": any((docs.get(d, {}).get("props") or {}).get("derived") for d in (da, db))}
                eid = "computed-count-" + sha256(f"{a['id']}|{b['id']}|{k}".encode()).hexdigest()[:24]
                result.append({"id": eid, "kind": "agrees" if values[0] == values[1] else "differs",
                               "from": a["id"], "to": b["id"], "method": "rule", "confidence": min(confs),
                               "doc_ids": [da, db], "evidence": evidence})
    return result
