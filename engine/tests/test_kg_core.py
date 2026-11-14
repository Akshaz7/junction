"""KG-CORE: evidence integrity, geometry ambiguity, hierarchy and cache invalidation."""
import json
from pathlib import Path

import pytest

from engine.kg import build, load, neighbours
from engine.kg.query import path_to_project, project_graph


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def plan(root, did, items, page=1, **meta):
    write(root / did / 'doc.json', {'doc_id': did, 'kind': 'dxf', 'title': 'Ground floor', **meta})
    write(root / did / f'planmap-{page}.json', {'page': page, 'image': {'w': 1000, 'h': 1000},
          'scale': {'m_per_px': .01, 'method': 'dxf-units', 'confidence': 1}, 'items': items})


def item(i, kind, bb, **kw):
    return dict(item_id=i, kind=kind, bbox_px=bb, props={}, conf=1, source='dxf', **kw)


@pytest.fixture
def sample(tmp_path):
    plan(tmp_path, 'drawing', [item('r', 'room', [0, 0, 100, 100], label='Kitchen', polygon_px=[[0,0],[100,0],[100,100],[0,100]]),
                              item('d', 'door', [10,10,20,20]), item('w', 'window', [200,200,220,220])])
    return tmp_path, {'id': 'sample', 'name': 'Site', 'docs': [{'doc_id': 'drawing', 'role': 'plan', 'level': 'Ground floor'}]}


def valid(g):
    ids = {n['id'] for n in g['nodes']}
    assert len(ids) == len(g['nodes'])
    assert len({e['id'] for e in g['edges']}) == len(g['edges'])
    for e in g['edges']:
        assert e['from'] in ids and e['to'] in ids
        assert e['method'] and isinstance(e['evidence'], dict) and e['evidence']
        assert 0 <= e['confidence'] <= 1
    json.dumps(g, allow_nan=False)


def test_structure_cache_and_filters(sample):
    root, p = sample
    g = build(p, root)
    valid(g)
    door = next(n for n in g['nodes'] if n['kind'] == 'door')
    assert any(x['edge']['kind'] == 'in_room' and x['node']['kind'] == 'room' for x in neighbours(g, door['id']))
    assert path_to_project(g, door['id'])[-1].startswith('project:')
    assert load('sample', root) == g == build(p, root)
    cluster = project_graph(g)
    assert not any(n['kind'] == 'door' for n in cluster['nodes'])
    assert next(n for n in cluster['nodes'] if n['kind'] == 'room')['props']['count_by_kind'] == {'door': 1}
    assert all(n['kind'] in ('project','doc','level','door') for n in project_graph(g, kinds='door', depth='full')['nodes'])
    assert not neighbours(g, 'missing')
    write(root/'drawing'/'planmap-2.json', {'page':2,'items':[item('d','door',[0,0,1,1])],'scale':{}})
    assert load('sample',root) is None
    g2 = build(p,root)
    assert len([n for n in g2['nodes'] if n['kind']=='door']) == 2
    assert build({**p,'docs':[]},root)['stats']['nodes'] == 1
    assert load('sample',root)['stats']['nodes'] == 1


def test_ambiguous_rooms_do_not_claim_containment(tmp_path):
    plan(tmp_path,'a',[item('r1','room',[0,0,100,100]),item('r2','room',[0,0,100,100]),item('d','door',[10,10,20,20])])
    g=build({'id':'x','docs':[{'doc_id':'a','role':'plan'}]},tmp_path)
    assert not any(e['kind']=='in_room' for e in g['edges'])


def test_missing_corrupt_and_invalid_documents(tmp_path):
    (tmp_path/'broken').mkdir()
    (tmp_path/'broken'/'planmap-1.json').write_text('{')
    g=build({'id':'missing','docs':['absent','broken','../elsewhere']},tmp_path)
    valid(g)
    assert g['warnings']
    assert len([n for n in g['nodes'] if n['kind']=='doc']) == 2
    assert g['stats']['linked_pct'] is None and g['stats']['agree_pct'] is None
    with pytest.raises(ValueError):
        load('../bad',tmp_path)
