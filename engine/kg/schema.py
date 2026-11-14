"""Small, dependency-free graph records and deterministic IDs."""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter

KINDS = {'project', 'doc', 'level', 'room', 'door', 'window', 'wall', 'slab', 'stair', 'column', 'duct', 'pipe', 'terminal', 'fixture', 'system', 'type', 'material', 'issue', 'change', 'sheet_ref'}
METHODS = {'ifc_relation', 'guid', 'tag_text', 'position', 'label_text', 'level_name', 'containment_geom', 'legend', 'revision_compare', 'rule', 'model'}


def norm(value) -> str:
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def kind_of(kind: str) -> str:
    return {'space': 'room', 'stairs': 'stair', 'curtain_wall': 'wall', 'air_terminal': 'terminal',
            'duct_fitting': 'duct', 'pipe_fitting': 'pipe', 'text': 'sheet_ref', 'dimension': 'sheet_ref', 'annotation': 'sheet_ref'}.get(kind, kind if kind in KINDS else 'fixture')


def readable(value, fallback: str) -> str:
    s = ' '.join(str(value or '').split())
    if not s or re.fullmatch(r'[0-9A-Za-z_$]{22}|[0-9a-fA-F-]{32,36}', s) or s.lower().startswith('ifc'):
        return fallback
    return s[:160]


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [finite(v) for v in value]
    return value


class Records:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def node(self, kind, doc, local, label, *, doc_ids=None, level=None, props=None, source=None):
        nid = f'{kind}:{doc}:{local}'
        if nid not in self.nodes:
            self.nodes[nid] = {'id': nid, 'kind': kind, 'label': readable(label, kind.title()),
                                   'doc_ids': doc_ids if doc_ids is not None else [doc], 'level': level,
                                   'props': finite(props or {}), 'source': finite(source), 'canonical': None, 'degree': 0}
        return nid

    def edge(self, kind, a, b, method, confidence, evidence, doc_ids=None):
        if not a or not b or a == b or a not in self.nodes or b not in self.nodes:
            return None
        if method not in METHODS:
            raise ValueError(f'Unknown graph method: {method}')
        evidence = finite(evidence or {})
        # Several comparisons (door counts, room counts) legitimately connect the same pair of levels.
        discriminator = str(evidence.get('property') or '') if kind in ('agrees', 'differs') else ''
        ka, kb = sorted((a, b)) if kind in ('same_as', 'connects') else (a, b)
        eid = 'e-' + hashlib.sha256(f'{kind}\0{ka}\0{kb}\0{discriminator}'.encode()).hexdigest()[:24]
        rec = dict(id=eid, kind=kind, **{'from': a, 'to': b}, method=method,
                   confidence=round(max(0., min(1., float(confidence))), 4), evidence=evidence,
                   doc_ids=sorted(set(doc_ids or self.nodes[a]['doc_ids'] + self.nodes[b]['doc_ids'])))
        if eid not in self.edges or self.edges[eid]['confidence'] <= rec['confidence']:
            self.edges[eid] = rec
        return eid


def finalise(graph, counterpart_docs=()):
    """Recompute derived fields after optional enrichment; same-as clusters have stable representatives."""
    nodes = {n['id']: n for n in graph['nodes']}
    degree = Counter()
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != x:
            following = parent[x]
            parent[x] = root
            x = following
        return root

    linked = set()
    counterpart_docs = set(counterpart_docs)
    clean = {}
    for e in graph['edges']:
        if e['from'] not in nodes or e['to'] not in nodes or e['from'] == e['to']:
            continue
        clean[e['id']] = e
    graph['edges'] = list(clean.values())
    for e in graph['edges']:
        a, b = e['from'], e['to']
        degree.update((a, b))
        if e['kind'] == 'same_as':
            ra, rb = find(a), find(b)
            parent[max(ra, rb)] = min(ra, rb)
            if set(nodes[a]['doc_ids']) != set(nodes[b]['doc_ids']):
                linked.update((a, b))
                counterpart_docs.update(nodes[a]['doc_ids'])
                counterpart_docs.update(nodes[b]['doc_ids'])
    for n in nodes.values():
        n['degree'] = degree[n['id']]
        n['canonical'] = find(n['id']) if n['id'] in parent and find(n['id']) != n['id'] else None
    structural = {'project', 'doc', 'level', 'system', 'type', 'material', 'issue', 'change', 'sheet_ref'}
    items = [n for n in nodes.values() if n['kind'] not in structural]
    eligible = [n for n in items if set(n['doc_ids']) & set(counterpart_docs)]
    ek = Counter(e['kind'] for e in graph['edges'])
    compared = ek['agrees'] + ek['differs']
    graph['stats'] = {'nodes': len(nodes), 'edges': len(graph['edges']), 'by_kind': dict(Counter(n['kind'] for n in nodes.values())),
                          'edges_by_kind': dict(ek), 'linked_pct': round(100 * len(linked & {n['id'] for n in eligible}) / len(eligible), 2) if eligible else None,
                          'agree_pct': round(100 * ek['agrees'] / compared, 2) if compared else None,
                          'unlinked': [n['id'] for n in items if n['id'] not in linked][:50], 'issues': sum(n['kind'] == 'issue' for n in nodes.values()),
                          'counterpart_items': len(eligible), 'linked_items': len(linked & {n['id'] for n in eligible})}
    return graph
