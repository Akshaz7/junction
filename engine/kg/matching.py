"""Conservative identity matching: IFC GUID, unique explicit tag/label, then aligned position.

Position links require a measured metric coordinate frame and at least three non-collinear anchors.
Repeated generic labels and nearest points without a frame never establish identity.
"""
from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations

from .schema import norm


def confidence(method, residual_m=None, evidence=None):
    # KG-EVAL owns the optional calibration module. Uncalibrated inference is deliberately marked estimate.
    try:
        from .confidence import confidence as calibrated
        return float(calibrated(method, residual_m, evidence=evidence))
    except (ImportError, TypeError, ValueError):
        return {'guid': 1., 'tag_text': .85, 'label_text': .7, 'position': .55}.get(method, .5)

_LEVEL_ALIASES = {
    'ground': ('erdgeschoss', 'eg', 'ground floor', 'ground', 'ground level', 'level 0', 'floor 0', 'floor 1', 'level 1', 'rez de chaussee', 'begane grond', 'maaiveld', 'plan terre', 'kerrosta 1', '0', '00', 'l0', 'gf'),
    'first': ('1 obergeschoss', '1 og', '1og', 'obergeschoss', 'first floor', '1st floor', 'floor 2', 'level 2', '1 verdieping', 'eerste verdieping', 'l1', '1'),
    'second': ('2 obergeschoss', '2 og', '2og', 'second floor', '2nd floor', 'floor 3', 'level 3', '2 verdieping', 'tweede verdieping', 'l2', '2'),
    'basement': ('keller', 'kellergeschoss', 'ug', 'untergeschoss', 'basement', 'souterrain', 'kelder', 'cellar', 'level -1', 'b1', 'fundering', '-1', 'foundation', 'untergeschoss 1'),
    'third': ('3 obergeschoss', '3 og', '3og', 'third floor', '3rd floor', 'floor 4', 'level 4', '3 verdieping', 'derde verdieping', 'l3', '3'),
    'roof': ('dachgeschoss', 'dg', 'dach', 'roof', 'attic', 'dak', 'zolder', 'roof level'),
}


def level_key(name):
    """Canonical storey identity across languages and numbering schemes (Erdgeschoss = Ground floor = Floor 1)."""
    import re
    t = re.sub(r'[^a-z0-9\- ]+', ' ', str(name or '').casefold().replace('ü', 'u').replace('ö', 'o').replace('ä', 'a').replace('ß', 'ss').replace('.', ' '))
    t = ' '.join(t.split())
    if not t:
        return ''
    for key, names in _LEVEL_ALIASES.items():
        if t in names:
            return key
    # Numbered storey names ("00 begane grond", "-1 fundering", "04 dak"): match by the words, else by the number.
    m = re.match(r'^(-?\d{1,2}) +([a-z].*)$', t)
    if m:
        for key, names in _LEVEL_ALIASES.items():
            if m.group(2) in names:
                return key
    return t


def same_level(node, info, row):
    """A node is on the row's storey by its own level, or by its single-storey drawing's declared level."""
    own = level_key(node['level'])
    want = level_key(row.name)
    if own:
        return own == want
    return bool(info.level) and level_key(info.level) == want


def _single_level_doc(info):
    doc = info.doc
    return bool(info.level) and doc is not None and len({level_key(s['name']) for s in doc.storeys} | {level_key(it.storey) for it in doc.items if it.storey}) <= 3 and info.role != 'model'


def _key(n, field):
    if field == 'guid':
        return n['props'].get('guid')
    if field == 'tag_text':
        return norm(n['props'].get('tag') or n['props'].get('mark') or n['props'].get('reference'))
    value = norm(n['label'])
    # Fallback labels, names repeated by authoring tools and type names are not unique element tags.
    return value if value and value != n['kind'] and value != n['kind'].title().casefold() else ''


def _unique(ids, nodes, field):
    out = defaultdict(list)
    for nid in ids:
        n = nodes[nid]
        key = _key(n, field)
        if key:
            out[(n['kind'], key)].append(nid)
    return {k: v[0] for k, v in out.items() if len(v) == 1}


def _point(b, nid):
    it = b.items[nid]
    if it.bbox_m:
        bb = it.bbox_m
        return [(bb[0][0] + bb[1][0])/2, (bb[0][2] + bb[1][2])/2]
    # Page scales are looked up per page; a first-page scale must never scale a different page.
    did = b.nodes[nid]['source']['doc_id']
    from .build import read_json
    if not hasattr(b, '_page_maps'):
        b._page_maps = {}
    key = (did, it.page)
    if key not in b._page_maps:
        b._page_maps[key] = read_json(b.root / did / f'planmap-{it.page}.json', {}) or {}
    pm = b._page_maps[key]
    scale = pm.get('scale') or {}
    mpp = scale.get('m_per_px')
    if not isinstance(mpp, (int,float)) or mpp <= 0 or scale.get('method') in ('door-prior','none',None) or (scale.get('confidence') or 0) < .6:
        return None
    if it.bbox_px:
        bb = it.bbox_px
        return [(bb[0]+bb[2])/2*mpp,(bb[1]+bb[3])/2*mpp]
    return None


def fit_similarity(pairs):
    """Least-squares similarity, including reflection for top-left PDF vs IFC plan frames.

    Returns measured transform and RMS in metres; rejects collinear/degenerate anchors and large metric scale changes.
    """
    import numpy as np
    if len(pairs) < 3:
        return None
    a, z = np.asarray([p[0] for p in pairs],dtype=float), np.asarray([p[1] for p in pairs],dtype=float)
    ac, zc = a-a.mean(0), z-z.mean(0)
    if np.linalg.matrix_rank(ac) < 2 or np.linalg.matrix_rank(zc) < 2:
        return None
    u,s,vt = np.linalg.svd(ac.T @ zc)
    rot=u@vt
    den=float((ac*ac).sum())
    scale=float(s.sum()/den) if den else 0
    if not .9 <= scale <= 1.1:  # both frames already in metres; a larger discrepancy is a scale problem
        return None
    shift=z.mean(0)-scale*a.mean(0)@rot
    matrix=scale*rot
    predicted=a@matrix+shift
    rms=float(np.sqrt(((predicted-z)**2).sum(1).mean()))
    return {'T': [[float(matrix[0,0]),float(matrix[1,0]),float(shift[0])],
                  [float(matrix[0,1]),float(matrix[1,1]),float(shift[1])],[0.,0.,1.]],
            'residual': round(rms,6), 'matches':len(pairs), 'scale':round(scale,6)}


def transform(point, alignment):
    t=alignment['T']
    return [t[0][0]*point[0]+t[0][1]*point[1]+t[0][2],t[1][0]*point[0]+t[1][1]*point[1]+t[1][2]]


def _position(b, a, z, anchors, linked_a, linked_z):
    points = {}
    for nid in a+z:
        p = _point(b,nid)
        if p is not None:
            points[nid]=p
    ps=[(points[x],points[y]) for x,y in anchors if x in points and y in points]
    from .alignment import vector_alignment
    alignment=vector_alignment(b, a[0], z[0]) or fit_similarity(ps)
    if not alignment:
        return
    # 10 cm is a building coordination tolerance, not a document-specific threshold.
    tolerance_m=.1
    if alignment['residual'] > tolerance_m:
        return
    from scipy.spatial import cKDTree
    for kind in sorted({b.nodes[n]['kind'] for n in a}):
        left=[n for n in a if n not in linked_a and n in points and b.nodes[n]['kind']==kind]
        right=[n for n in z if n not in linked_z and n in points and b.nodes[n]['kind']==kind]
        if not left or not right:
            continue
        tree=cKDTree([points[n] for n in right])
        transformed=[transform(points[n],alignment) for n in left]
        inverse=cKDTree(transformed)
        for i,nid in enumerate(left):
            near=tree.query_ball_point(transformed[i],tolerance_m)
            if len(near)!=1:
                continue
            j=near[0]
            if len(inverse.query_ball_point(points[right[j]],tolerance_m))!=1:
                continue
            other=right[j]
            residual=math.dist(transformed[i],points[other])
            b.edge('same_as',nid,other,'position',confidence('position',residual, {'alignment': alignment}),
                   {'residual_m':round(residual,6),'alignment':alignment,'tolerance_m':tolerance_m,
                    'sources':[b.nodes[nid]['source'],b.nodes[other]['source']]})
            linked_a.add(nid);linked_z.add(other)


def _match_pair(b,a,z):
    linked_a,linked_z,anchors=set(),set(),[]
    for field,method in [('guid','guid'),('tag_text','tag_text'),('label','label_text')]:
        ka,kz=_unique(a,b.nodes,field),_unique(z,b.nodes,field)
        for key in sorted(ka.keys() & kz.keys()):
            x,y=ka[key],kz[key]
            if x in linked_a or y in linked_z:
                continue
            # Non-room arbitrary element names are frequently instance/type labels, even if unique in a sparse sheet.
            if field=='label' and b.nodes[x]['kind']!='room':
                continue
            b.edge('same_as',x,y,method,confidence(method),
                   {'property':field,'value':key[1],'sources':[b.nodes[x]['source'],b.nodes[y]['source']]})
            linked_a.add(x);linked_z.add(y)
            anchors.append((x,y))
    # Fit independently per page pair to avoid overlaying multi-page plans onto a single coordinate frame.
    pages=defaultdict(list)
    for x,y in anchors:
        pages[(b.nodes[x]['source']['page'],b.nodes[y]['source']['page'])].append((x,y))
    if not pages and len({b.nodes[n]['source']['page'] for n in a}) == 1 and len({b.nodes[n]['source']['page'] for n in z}) == 1:
        pages[(b.nodes[a[0]]['source']['page'], b.nodes[z[0]]['source']['page'])] = []
    for (pa,pz),pairs in pages.items():
        left=[n for n in a if b.nodes[n]['source']['page']==pa]
        right=[n for n in z if b.nodes[n]['source']['page']==pz]
        _position(b,left,right,pairs,linked_a,linked_z)


def match_documents(b):
    by_doc=defaultdict(list)
    for nid in b.items:
        by_doc[b.nodes[nid]['source']['doc_id']].append(nid)
    tested=set()
    # Reuse existing same-building and floor placement, rather than guessing building identity from proximity.
    for row in b.combined.rows:
        docs=list(row.docs)
        # Derived model sheets are not counted by combine; they still provide evidence for identity links.
        for did,info in b.combined.infos.items():
            if info.derived and info.doc and (not row.name or any(norm(s['name'])==norm(row.name) for s in info.doc.storeys)):
                parent=(info.doc.meta or {}).get('sheet_of')
                if parent in row.docs and did not in docs:
                    docs.append(did)
        for da,dz in combinations(docs,2):
            a=[n for n in by_doc[da] if b.combined.infos[da].doc.mode=='planmap' or b.combined.infos[da].derived or norm(b.nodes[n]['level'])==norm(row.name) or (_single_level_doc(b.combined.infos[da]) and same_level(b.nodes[n],b.combined.infos[da],row)) or (not b.nodes[n]['level'] and not row.key)]
            z=[n for n in by_doc[dz] if b.combined.infos[dz].doc.mode=='planmap' or b.combined.infos[dz].derived or norm(b.nodes[n]['level'])==norm(row.name) or (_single_level_doc(b.combined.infos[dz]) and same_level(b.nodes[n],b.combined.infos[dz],row)) or (not b.nodes[n]['level'] and not row.key)]
            key=(da,dz,row.group,row.key)
            if key in tested or not a or not z:
                continue
            tested.add(key)
            b.counterpart_docs.update((da,dz))
            _match_pair(b,a,z)
    # Explicit shared IFC GUIDs prove identity even across discipline models with different storey naming.
    guids=defaultdict(list)
    for nid in b.items:
        guid=b.nodes[nid]['props'].get('guid')
        if guid:
            guids[(b.nodes[nid]['kind'],guid)].append(nid)
    for (_,guid),ids in guids.items():
        for a,z in combinations(ids,2):
            da,dz=b.nodes[a]['source']['doc_id'],b.nodes[z]['source']['doc_id']
            if da!=dz:
                b.counterpart_docs.update((da,dz))
                b.edge('same_as',a,z,'guid',confidence('guid'),{'guid':guid,'sources':[b.nodes[a]['source'],b.nodes[z]['source']]})


def link_levels(b):
    """Same storey across documents (by canonical name): lets any item's neighbourhood reach the other files' items on that level."""
    by_key = defaultdict(list)
    for (did, _), nid in b.level_nodes.items():
        k = level_key(b.nodes[nid]['label'])
        if k:
            by_key[k].append((did, nid))
    for items in by_key.values():
        for (da, a), (dz, z) in combinations(sorted(items), 2):
            if da != dz:
                b.edge('same_level', a, z, 'level_name', .7, {'property': 'level_name', 'sources': [{'doc_id': da}, {'doc_id': dz}]})


def link_rooms_by_name(b):
    """Rooms with the same unique name on the same storey in different files are the same room.

    Independent of the quantity rows: a one-storey drawing and a model rarely share a combine row, yet the name and storey are explicit.
    """
    groups = defaultdict(lambda: defaultdict(list))
    for nid in b.items:
        n = b.nodes[nid]
        if n['kind'] != 'room':
            continue
        label = norm(n['label'])
        if not label or label == 'room':
            continue
        info = b.combined.infos.get(n['source']['doc_id'])
        lvl = level_key(n['level']) or (level_key(info.level) if info is not None else '')
        groups[(lvl, label)][n['source']['doc_id']].append(nid)
    have = {frozenset((e['from'], e['to'])) for e in b.edges.values() if e['kind'] == 'same_as'}
    for (lvl, label), per_doc in groups.items():
        if not lvl or len(per_doc) < 2 or any(len(v) != 1 for v in per_doc.values()):
            continue
        for (da, (x,)), (dz, (y,)) in combinations(sorted(per_doc.items()), 2):
            if frozenset((x, y)) in have:
                continue
            b.edge('same_as', x, y, 'label_text', confidence('label_text'),
                   {'property': 'label', 'value': label, 'level': lvl, 'sources': [b.nodes[x]['source'], b.nodes[y]['source']]})
            b.counterpart_docs.update((da, dz))
