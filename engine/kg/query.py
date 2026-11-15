"""Bounded graph traversal and display projection. These never change the cached graph."""
from collections import Counter, defaultdict, deque


def neighbours(graph, node_id, kinds=None, depth=1):
    """Undirected breadth-first traversal; preserve every relationship, including parallel comparisons."""
    if isinstance(kinds, str):
        kinds = {k.strip() for k in kinds.split(',') if k.strip()}
    allowed = set(kinds) if kinds else None
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    if node_id not in nodes:
        return []
    adj = defaultdict(list)
    for e in graph.get('edges', []):
        if allowed is None or e['kind'] in allowed:
            adj[e['from']].append((e, e['to']))
            adj[e['to']].append((e, e['from']))
    seen, seen_edges, todo, out = {node_id}, set(), deque([(node_id, 0)]), []
    while todo:
        nid, d = todo.popleft()
        if d >= max(0, min(int(depth), 20)):
            continue
        for edge, other in adj[nid]:
            if other not in nodes:
                continue
            if edge['id'] not in seen_edges:
                seen_edges.add(edge['id'])
                out.append({'edge': edge, 'node': nodes[other]})
            if other not in seen:
                seen.add(other)
                todo.append((other, d + 1))
    return out


def path_to_project(graph, node_id):
    """Shortest structural parent path, excluding speculative cross-file relationships."""
    nodes = {n['id']: n for n in graph['nodes']}
    parents = defaultdict(list)
    for e in graph['edges']:
        if e['kind'] == 'contains':
            parents[e['to']].append(e['from'])
        elif e['kind'] in ('on_level', 'in_room', 'part_of_system'):
            parents[e['from']].append(e['to'])
    todo, seen = deque([(node_id, [node_id])]), {node_id}
    while todo:
        nid, path = todo.popleft()
        if nodes.get(nid, {}).get('kind') == 'project':
            return path
        for p in parents[nid]:
            if p not in seen:
                seen.add(p)
                todo.append((p, path + [p]))
    return []


def project_graph(graph, *, level=None, kinds=None, doc_id=None, depth='cluster'):
    """Induced subgraph, retaining hierarchy. Room/level summaries count unique source items."""
    if isinstance(kinds, str):
        kinds = {k.strip() for k in kinds.split(',') if k.strip()}
    from engine.kg.schema import norm
    structural = {'project', 'doc'}
    cluster = structural | {'level', 'room', 'system', 'issue', 'change'}
    selected = []
    for n in graph['nodes']:
        if doc_id and n['kind'] != 'project' and doc_id not in n['doc_ids']:
            continue
        if level and n['kind'] not in structural and norm(n.get('level')) != norm(level):
            continue
        if kinds and n['kind'] not in structural | {'level'} and n['kind'] not in kinds:
            continue
        selected.append(n)
    visible = {n['id'] for n in selected}
    counts = defaultdict(Counter)
    by_id = {n['id']: n for n in selected}
    for e in graph['edges']:
        if e['kind'] in ('in_room', 'on_level') and e['from'] in by_id and e['to'] in by_id:
            counts[e['to']][by_id[e['from']]['kind']] += 1
    if depth == 'cluster':
        selected = [{**n, 'props': {**n['props'], 'count_by_kind': dict(counts[n['id']])}} if n['kind'] in ('room', 'level') else n
                    for n in selected if n['kind'] in cluster]
    visible = {n['id'] for n in selected}
    return {**graph, 'nodes': selected, 'edges': [e for e in graph['edges'] if e['from'] in visible and e['to'] in visible],
            'view': {'depth': depth, 'nodes': len(selected), 'level': level, 'doc_id': doc_id}}
