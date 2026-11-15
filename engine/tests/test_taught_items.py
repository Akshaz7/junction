import json
from pathlib import Path
import pytest
from engine.taught_items import canonical_kind, project, query
from engine.solvers.data import load_doc
from engine.solvers.solve import solve
from engine.router.parser import Parsed
from engine import kg, reasoning


def symbol(name='ovi', box=(10,10,20,20), sid='one', page=1, **kwargs):
    return dict(id=sid, name=name, page=page, manual_selection=True, template_bbox=list(box),
                matches=[{'id':'1', 'status':'confirmed'}], **kwargs)


def save(tmp_path, plan, name='sheet', page=1):
    d = tmp_path / name; d.mkdir(exist_ok=True)
    (d / f'planmap-{page}.json').write_text(json.dumps(plan))
    return d


@pytest.mark.parametrize('name,kind', [('dr','door'),('ovi','door'),('Tür','door'),('dörr','door'),('WC','toilet'),
    ('TP','terminal'), ('tilluftsdon','terminal'), ('ilmakanava','duct'), ('Brandschutzklappe','valve'),
    ('treppe','stairs'), ('FÖNSTER','window'), ('not a door','custom'), ('widget','custom')])
def test_synonyms_are_multilingual_exact_phrases(name,kind):
    assert canonical_kind(name) == (None if kind == 'custom' else kind)


def test_dedupe_retains_detector_and_links_repeated_marks(tmp_path):
    base = {'items':[{'item_id':'detected','kind':'door','source':'det','bbox_px':[10,10,20,20],'conf':.6,'props':{'width_m':.8}}]}
    labels = [symbol(), symbol(sid='two'), symbol(box=[40,40,50,50],sid='three')]
    plan = project(base, labels, 1)
    assert len(base['items']) == 1 and base['items'][0]['conf'] == .6
    assert len(plan['items']) == 2
    detected = plan['items'][0]
    assert detected['item_id'] == 'detected' and detected['source'] == 'det'
    assert detected['props']['width_m'] == .8
    assert detected['props']['linked_item_ids'] == ['detected','taught-one','taught-two']
    assert len(project(plan, labels, 1)['items']) == 2
    removed = project(plan, [], 1)
    assert removed['items'] == base['items']
    save(tmp_path, plan)
    assert len(load_doc('sheet', tmp_path).items) == 2
    answer = solve('Count doors', 'sheet', root=tmp_path)
    assert answer['answer']['value'] == 2
    assert '1 detected + 1 added by you; 2 marked by you' in answer['answer']['text_md']
    card = reasoning.build(answer, 'Count doors', tmp_path)
    assert card['steps'][0]['title'] == 'Marked by you'
    assert card['confidence']['pct'] == 100
    assert 'not proof' in card['confidence']['reason']
    assert len(kg.build('sheet', tmp_path)['nodes']) == 2


def test_ignore_legacy_matches_wrong_page_and_rejected():
    one = symbol(); legacy = symbol(sid='old'); legacy['manual_selection'] = False
    rejected = symbol(sid='removed'); rejected['matches'][0]['status'] = 'rejected'
    other = symbol(sid='page2', page=2)
    plan = project({'items':[]}, [one,legacy,rejected,other], 1)
    assert [i['item_id'] for i in plan['items']] == ['taught-one']


def test_counts_alias_custom_page_and_hidden_no_models(tmp_path, monkeypatch):
    monkeypatch.setenv('MODELS_FAKE','1')
    plan = project({'items':[]}, [symbol('Zig zag special'), symbol('door',sid='two',box=[40,40,50,50])], 1)
    save(tmp_path, plan)
    a = query('How many Zig zag specials?', ['sheet'], tmp_path)
    assert a['answer']['value'] == 1
    assert a['evidence']['boxes'][0]['item_id'] == 'taught-one'
    assert query('Count Türen', ['sheet'], tmp_path)['answer']['value'] == 1
    assert query('How many doors on page 2?', ['sheet'], tmp_path)['answer']['value'] == 0
    assert query('Count doors', ['sheet'], tmp_path, {'taught-two':'D1'})['answer']['value'] == 0
    assert query('How many doors wider than 2 metres?', ['sheet'], tmp_path) is None
    assert query('Count doors', ['other'], tmp_path) is None


def test_missing_scale_never_supplies_measured_quantity(tmp_path):
    save(tmp_path, project({'items':[]}, [symbol('duct')], 1))
    a = solve('Total length of ducts', 'sheet', parsed=Parsed('length','duct',None,True),root=tmp_path)
    assert a['answer']['abstained'] is True


def test_ifc_uses_same_items_and_dedupes_plan_identity(tmp_path):
    d = save(tmp_path, project({'items':[{'item_id':'native','kind':'door','bbox_px':[10,10,20,20],'conf':1,'source':'ifc'}]},[symbol()],1))
    (d/'elements.json').write_text(json.dumps({'elements':[{'item_id':'native','kind':'door'}]}))
    doc = load_doc('sheet',tmp_path)
    assert len(doc.items) == 1 and doc.items[0].props['confirmed_by_user']
    assert doc.items[0].item_id == 'native'


def test_engine_uses_manual_count_even_with_recount_enabled(tmp_path,monkeypatch):
    from engine.answer import answer
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    monkeypatch.setenv('RECOUNT','1')
    def no_call(*a,**kw): raise AssertionError('manual counts must not call models')
    monkeypatch.setattr('engine.models.call',no_call)
    save(tmp_path,project({'items':[]},[symbol('door')],1))
    a = answer('How many doors?', ['sheet'])
    assert a['answer']['value'] == 1
    assert a['cost']['usd_total'] == 0
    assert a['reasoning']['steps'][0]['title'] == 'Marked by you'


def test_per_room_counts_use_polygons_and_missing_room_abstains(tmp_path):
    room = {'item_id':'r','kind':'room','label':'Studio','conf':1,'props':{},'polygon_px':[[0,0],[30,0],[30,30],[0,30]]}
    save(tmp_path, project({'items':[room]}, [symbol(),symbol(sid='two',box=[50,50,60,60])], 1))
    a = query('How many doors in the Studio?', ['sheet'], tmp_path)
    assert a['answer']['value'] == 1 and a['evidence']['boxes'][0]['item_id'] == 'taught-one'
    a = query('Count doors per room', ['sheet'], tmp_path)
    assert a['answer']['value'] == 1 and '1 items have no enclosing room' in a['answer']['text_md']
    assert query('Count doors in the missing room', ['sheet'],tmp_path)['answer']['abstained'] is True
    assert query('Count doors in this drawing', ['sheet'],tmp_path)['answer']['value'] == 2


def test_canonical_terminal_count_and_specific_subtypes(tmp_path):
    labels = [symbol('Supply air terminal'),symbol('Extract air terminal',sid='two',box=[40,40,50,50])]
    save(tmp_path, project({'items':[]},labels,1))
    assert query('Count terminals',['sheet'],tmp_path)['answer']['value'] == 2
    assert query('How many supply air terminals?',['sheet'],tmp_path)['answer']['value'] == 1
    assert query('Count extract air terminals',['sheet'],tmp_path)['answer']['value'] == 1
    assert query('Count TP',['sheet'],tmp_path)['answer']['value'] == 1


def test_loose_box_around_detected_door_merges_by_centre():
    detected = {'item_id': 'door-003', 'kind': 'door', 'source': 'det', 'bbox_px': [40, 40, 256, 44], 'conf': .6, 'props': {}}
    plan = project({'items': [detected]}, [symbol(box=(25, 22, 270, 74))], 1)
    from engine.taught_items import iou, existing_links
    assert iou([40, 40, 256, 44], [25, 22, 270, 74]) < .5
    assert len(plan['items']) == 1 and plan['items'][0]['item_id'] == 'door-003'
    assert existing_links(plan) == {'one': 'door-003'}


def test_taught_mark_on_other_kind_or_far_away_still_adds():
    base = {'items': [{'item_id': 'w1', 'kind': 'window', 'source': 'det', 'bbox_px': [10, 10, 20, 20], 'conf': .6, 'props': {}},
                      {'item_id': 'd1', 'kind': 'door', 'source': 'det', 'bbox_px': [100, 100, 110, 110], 'conf': .6, 'props': {}}]}
    plan = project(base, [symbol(box=(8, 8, 22, 22))], 1)
    assert len(plan['items']) == 3


def test_label_containing_a_class_word_counts_taught_items_not_rooms(tmp_path):
    plan = project({'items': [{'item_id': f'r{i}', 'kind': 'room', 'source': 'det', 'bbox_px': [i*100, 0, i*100+50, 50], 'conf': .9, 'props': {}} for i in range(5)]},
                   [symbol('cylinder storage room', box=(1000, 1000, 1050, 1050))], 1)
    save(tmp_path, plan)
    for q in ('How many cylinder storage room marks are on this drawing?', 'Count the marks named "cylinder storage room" on this drawing',
              'how many cylinder storage rooms are there'):
        a = query(q, ['sheet'], tmp_path)
        assert a is not None and a['answer']['value'] == 1, q
        assert a['evidence']['boxes'][0]['item_id'] == 'taught-one'
