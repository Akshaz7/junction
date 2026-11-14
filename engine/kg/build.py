"""Code-only project knowledge graph, built from readable artifacts of every format."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .schema import Records, finalise, kind_of, norm, readable


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return default


class Builder(Records):
    def __init__(self, project, root):
        super().__init__()
        self.project, self.root = project, Path(root)
        self.pid = str(project.get('id') or project.get('project_id') or 'project')
        self.items = {}                 # node id -> Item, used only during construction
        self.item_nodes = defaultdict(list)  # (doc_id, source item_id) -> [node ids] (IDs may repeat per page)
        self.level_nodes = {}         # (doc_id, level name) -> node id
        self.doc_nodes = {}
        self.warnings = []
        self.counterpart_docs = set()
        self.combined = None

    def level(self, did, name, elevation=None):
        key = (did, norm(name))
        if key not in self.level_nodes:
            nid = self.node('level', did, norm(name), name, level=name,
                            props={'elevation_m': elevation} if elevation is not None else {})
            self.level_nodes[key] = nid
            self.edge('contains', self.doc_nodes[did], nid, 'rule', 1, {'rule': 'document_level', 'level': name})
        return self.level_nodes[key]

    def lookup(self, did, item_id, page=None):
        ids = self.item_nodes.get((did, str(item_id)), [])
        return next((n for n in ids if page is None or self.nodes[n]['source']['page'] == page), None)

    def populate(self):
        from engine.projects.combine import combine
        docs = self.project.get('docs') or self.project.get('doc_ids') or []
        safe = []
        for d in docs:
            d = {'doc_id': d} if isinstance(d, str) else dict(d)
            did = str(d.get('doc_id') or '')
            if not did or Path(did).name != did or did in ('.', '..'):
                self.warnings.append({'doc_id': did, 'note': 'Invalid document identifier; skipped.'})
                continue
            safe.append(d)
        self.combined = combine(safe, self.root)
        pn = self.node('project', self.pid, 'root', self.project.get('name') or 'Project', doc_ids=[])
        for did, info in self.combined.infos.items():
            dn = self.node('doc', did, 'root', info.title, level=info.level,
                           props={'role': info.role, 'format': info.kind, 'derived': info.derived, 'group': info.group})
            self.doc_nodes[did] = dn
            self.edge('contains', pn, dn, 'rule', 1, {'rule': 'project_membership', 'doc_id': did})
            doc = info.doc
            if doc is None:
                self.warnings.append({'doc_id': did, 'note': 'No readable item index; document retained as a reference.'})
                continue
            for st in doc.storeys:
                self.level(did, st['name'], st.get('elevation_m'))
            # Some plan maps contain several pages with the same local item IDs.
            repeated = Counter(str(it.item_id) for it in doc.items)
            for seq, it in enumerate(doc.items):
                kind = kind_of(it.kind)
                if kind in ('project', 'doc', 'level'):
                    continue
                level = it.storey or it.props.get('level') or it.props.get('storey') or info.level
                if isinstance(level, dict):
                    level = level.get('name')
                page = int(it.page or 1)
                local = str(it.item_id)
                if repeated[local] > 1:
                    local += f':p{page}'
                # Broken files can even duplicate an ID on the same page. Preserve every record without overwriting evidence.
                if f'{kind}:{did}:{local}' in self.nodes:
                    local += f':n{seq}'
                props = {**it.props, **it.q, 'original_kind': it.kind, 'source_method': it.source, 'confidence': it.conf}
                if it.bbox_m:
                    props['bbox_m'] = it.bbox_m
                if it.polygon_px:
                    props['polygon_px'] = it.polygon_px
                if it.type_name:
                    props['type'] = it.type_name
                if it.source == 'ifc':
                    props['guid'] = str(it.item_id)
                source = {'doc_id': did, 'page': page, 'item_id': str(it.item_id), 'bbox': it.bbox_px}
                label = readable(it.label or it.props.get('long_name') or it.name, kind.title())
                nid = self.node(kind, did, local, label, level=level, props=props, source=source)
                self.items[nid] = it
                self.item_nodes[did, str(it.item_id)].append(nid)
                self.edge('contains', dn, nid, 'rule', 1, {'rule': 'document_item', 'source': source})
                if level:
                    ln = self.level(did, level)
                    self.edge('on_level', nid, ln, 'ifc_relation' if it.source == 'ifc' else 'level_name',
                              1 if it.source == 'ifc' else .8, {'level': level, 'source': source})
                    if kind == 'room':
                        self.edge('contains', ln, nid, 'ifc_relation' if it.source == 'ifc' else 'level_name',
                                  1 if it.source == 'ifc' else .8, {'level': level, 'source': source})
                self.properties(nid, did, it)
        self.geometry()
        return self

    def properties(self, nid, did, it):
        for field, kind, relation in [('type', 'type', 'has_type'), ('material', 'material', 'made_of'), ('system', 'system', 'part_of_system')]:
            value = it.type_name if field == 'type' else it.props.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            other = self.node(kind, did, norm(value), value)
            self.edge('contains', self.doc_nodes[did], other, 'rule', 1, {'rule': 'document_property'})
            self.edge(relation, nid, other, 'ifc_relation' if it.source == 'ifc' else 'label_text',
                      1 if it.source == 'ifc' else .8, {'property': field, 'value': value, 'source': self.nodes[nid]['source']})

    def geometry(self):
        """Plan geometry uses pixel coordinates only within a page. No invented scale or cross-page proximity."""
        try:
            from shapely.geometry import Point, Polygon, box
            from shapely.strtree import STRtree
        except ImportError:
            self.warnings.append({'note': 'Geometry library unavailable; containment links skipped.'})
            return
        pages = defaultdict(list)
        for nid, it in self.items.items():
            if it.source != 'ifc' and it.bbox_px:
                pages[(self.nodes[nid]['source']['doc_id'], it.page)].append(nid)
        for (_, _), ids in pages.items():
            rooms = [n for n in ids if self.nodes[n]['kind'] == 'room']
            shapes, valid = [], []
            for n in rooms:
                it = self.items[n]
                try:
                    g = Polygon(it.polygon_px).buffer(0) if it.polygon_px and len(it.polygon_px) >= 3 else box(*it.bbox_px)
                    if not g.is_empty and g.area > 0:
                        shapes.append(g)
                        valid.append(n)
                except (ValueError, TypeError):
                    continue
            if not shapes:
                continue
            tree = STRtree(shapes)
            for nid in ids:
                n, it = self.nodes[nid], self.items[nid]
                if n['kind'] in ('room', 'wall'):
                    continue
                try:
                    bb = it.bbox_px
                    p = Point((bb[0]+bb[2])/2, (bb[1]+bb[3])/2)
                    hits = [int(i) for i in tree.query(p) if shapes[int(i)].covers(p)]
                except (ValueError, TypeError, IndexError):
                    continue
                # Ambiguous nested/overlapping rooms are not asserted as a definite relationship.
                if len(hits) == 1:
                    room = valid[hits[0]]
                    polygon = bool(self.items[room].polygon_px)
                    self.edge('in_room', nid, room, 'containment_geom', .7 if polygon else .55,
                              {'rule': 'centre_inside_room_polygon' if polygon else 'centre_inside_room_bbox',
                               'point_px': list(p.coords)[0], 'page': it.page,
                               'item_source': n['source'], 'room_source': self.nodes[room]['source']})

    def graph(self):
        return {'project_id': self.pid, 'version': 1, 'built_at': datetime.now(timezone.utc).isoformat(),
                'nodes': list(self.nodes.values()), 'edges': list(self.edges.values()), 'warnings': self.warnings}


def build_uncached(project, root):
    b = Builder(project, root).populate()
    # Additional modules are deliberately small: workers can merge independently without editing this builder.
    from .ifc import enrich_ifc
    from .matching import match_documents
    from .evidence import comparisons, references, revisions_and_issues
    enrich_ifc(b)
    match_documents(b)
    comparisons(b)
    references(b)
    revisions_and_issues(b)
    graph = b.graph()
    try:
        from .mep import enrich
    except ImportError:
        enrich = None
    if enrich:
        graph = enrich(graph, project, Path(root)) or graph
    return finalise(graph, b.counterpart_docs)
