"""Regressions through the public engine path, including real data and missing data."""
from pathlib import Path
import json
import pytest

from engine.answer import answer

ROOT=Path(__file__).resolve().parents[2]
AC='ifc_bench__ac20-arc'


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv('MODELS_FAKE','1')


def ask(q,docs=None,**kwargs):
    r=answer(q,[AC] if docs is None else docs,**kwargs)
    assert not any(t['step']=='error' for t in r['trace']),r['trace']
    assert r['cost']['usd_total']==0
    return r


def test_storey_area_is_not_a_room_named_ground_floor():
    r=ask('What is the total net floor area of the ground floor?')
    assert r['answer']['value']==pytest.approx(442.1296,abs=.01)
    assert 'No room matching' not in r['answer']['text_md']


def test_compound_dimensions_and_size_schedules():
    r=ask('How many windows are 0.9 m wide and 2.0 m high?')
    assert r['answer']['value']==3
    r=ask('Give me a door schedule: how many doors of each width do I need to order?')
    for row in ('| 1 m | 67 |','| 1.8 m | 9 |','| 2 m | 1 |'):
        assert row in r['answer']['text_md']
    r=ask('How many windows of each size are there?')
    for n in (196,6,3,1): assert f'| {n} |' in r['answer']['text_md']
    assert r.get('reasoning')


def test_tag_dimension_and_ifc_scale_are_code():
    assert ask('How wide is door D34?')['answer']['value']==2
    r=ask('What is the scale of this drawing?')
    assert 'real-world size in metres' in r['answer']['text_md']
    assert not any(t.get('model') for t in r['trace'])


def test_takeoff_keeps_all_four_requested_quantities_and_storey():
    r=ask('Make a quantity take-off for Erdgeschoss: floor area, wall length, doors, windows.')
    for value in ('442.1','256.8','| Doors | 18 |','| Windows | 54 |'):
        assert value in r['answer']['text_md']
    assert all('Keller' not in c.get('label','') for c in r['citations'])


def test_single_wall_face_and_structural_question_are_not_properties():
    r=ask('What is the net area of one face of the external walls on Erdgeschoss, after openings?')
    assert r['answer']['value']==pytest.approx(216.6,abs=.1)
    r=ask('Can we remove the internal wall next to the Seminarraum without propping?')
    assert 'load-bearing' in r['answer']['text_md'] or 'structural engineer' in r['answer']['text_md']


def test_room_neighbours_are_candidates_with_evidence_and_estimate_card():
    r=ask('Which rooms are next to the Seminarraum?')
    assert 'Technikraum III' in r['answer']['text_md'] and 'Flur Keller Ost' in r['answer']['text_md']
    assert r['answer']['value'] is None and r['citations']
    assert r['reasoning']['confidence']['label']=='Estimate'
    assert r['reasoning']['confidence']['pct']<=60


def test_unit_cost_followup_carries_waste_and_documents():
    previous='How many m2 of tiles do I need for all WCs including 10% waste?'
    r=ask('What would those tiles cost at 35 EUR per m2?',history=[{'role':'user','content':previous,'doc_ids':[AC]}])
    assert 108 < r['answer']['value'] < 110
    assert 'EUR' in r['answer']['text_md'] and '10%' in r['answer']['text_md']
    assert '3,812.20' in r['answer']['text_md']  # order quantity rounds coverage up to 0.01 m² before pricing


def test_relative_numeric_question_without_selection_cannot_pick_a_drawing():
    r=ask('How many windows are there?',[])
    assert r['answer']['value'] is None
    assert 'Which drawing' in r['answer']['text_md'] and not r['doc_ids']


def test_no_structured_pdf_does_not_crash(monkeypatch,tmp_path):
    d=tmp_path/'generated-for-demo';d.mkdir()
    (d/'doc.json').write_text(json.dumps({'title':'Generated for demo','kind':'pdf','pages':1}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    r=ask('What is the U-value of the external wall assembly?',['generated-for-demo'])
    assert r['answer']['value'] is None


def test_brand_question_does_not_become_an_order_area():
    r=ask('Which tile brand should I buy for the WCs?')
    assert r['answer']['value'] is None and r['answer']['unit'] not in ('m2','m²')


def test_missing_raster_class_does_not_return_floor_count_or_zero(monkeypatch,tmp_path):
    d=tmp_path/'generated-for-demo';d.mkdir()
    (d/'doc.json').write_text(json.dumps({'title':'Generated for demo classroom plan','kind':'png','pages':1}))
    (d/'planmap-1.json').write_text(json.dumps({'items':[{'item_id':'door-1','kind':'door','conf':.9,'source':'det'}]}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    for q in ('How many classrooms are on this level?','How many windows are there?'):
        r=ask(q,['generated-for-demo'])
        assert r['answer']['value'] is None
        assert 'not' in r['answer']['text_md'] or 'cannot' in r['answer']['text_md']


def test_translated_raster_room_is_specific_and_missing_areas_are_unknown(monkeypatch,tmp_path):
    d=tmp_path/'generated-for-demo';d.mkdir()
    (d/'doc.json').write_text(json.dumps({'title':'Generated for demo','kind':'png','pages':1}))
    rooms=[{'item_id':'bed','kind':'room','label':'MH','conf':.9,'source':'det','props':{'room_type':'bedroom','area_m2':14.4}},
           {'item_id':'living','kind':'room','label':'Living Rm','conf':.9,'source':'det','props':{'room_type':'living'}}]
    (d/'planmap-1.json').write_text(json.dumps({'scale':{'method':'dimension','m_per_px':.01,'confidence':.8},'items':rooms}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    r=ask('How big is the makuuhuone?',['generated-for-demo'])
    assert r['answer']['value']==14.4
    r=ask('What is the area of the living room?',['generated-for-demo'])
    assert r['answer']['value'] is None and '0.00' not in r['answer']['text_md']


def test_printed_floor_total_does_not_depend_on_detector_scale(monkeypatch,tmp_path):
    from engine.tests.test_suite_printed import page
    d=tmp_path/'generated-for-demo';d.mkdir()
    (d/'doc.json').write_text(json.dumps({'title':'Building_third_floor_plan','kind':'png','pages':1}))
    (d/'planmap-1.json').write_text(json.dumps({'scale':{'method':'door-prior','m_per_px':.1,'confidence':.3},'items':[]}))
    pt=page(['TOTAL NORTH WING = 500 SF','TOTALTHIRDFLOOR= 21000 SF'])
    (d/'text-1.json').write_text(json.dumps({'image':{'w':800,'h':800},'words':pt.words,'source':'generated for demo'}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    r=ask('What is the total third floor area in square metres?',['generated-for-demo'])
    assert r['answer']['value']==pytest.approx(21000*.09290304,abs=.0001)
    assert 'scale looks wrong' not in r['answer']['text_md'] and 'door sizes' not in r['answer']['text_md']


def test_named_sheet_set_qualifier_selects_the_right_issue(monkeypatch,tmp_path):
    for suffix,title,n in [('a','Harbour Block pricing exercise',9),('b','Harbour Block permit drawings',13)]:
        d=tmp_path/suffix;d.mkdir()
        (d/'doc.json').write_text(json.dumps({'doc_id':suffix,'title':title,'kind':'pdf','formats':['pdf'],'pages':n}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    r=ask('How many sheets are in the Harbour Block pricing set?',[])
    assert r['answer']['value']==9 and r['doc_ids']==['a']


@pytest.mark.parametrize('q', ['How many windows are 0.9 m wide and 2.0 m high?',
                              'Give me a door schedule by width',
                              'Which rooms are next to the Seminarraum?',
                              'Make a quantity take-off for Erdgeschoss: floor area, wall length, doors, windows.',
                              'How wide is door D34?'])
def test_new_routes_validate_against_answer_schema(q):
    from server.schema import validate_answer
    validate_answer(ask(q))


def test_uncertain_room_types_are_not_presented_as_a_verified_total(monkeypatch,tmp_path):
    from engine.solvers.solve import solve
    d=tmp_path/'generated-for-demo';d.mkdir()
    items=[{'item_id':'room-a','kind':'room','label':'Bedroom','conf':.95,'source':'det','props':{'room_type':'bedroom','label_room_type':'bedroom'}},
           {'item_id':'room-b','kind':'room','conf':.7,'source':'det','props':{'room_type':'bedroom'}}]
    (d/'planmap-1.json').write_text(json.dumps({'items':items}))
    r=solve('How many bedrooms are there?',d.name,root=tmp_path)
    assert r['answer']['value']==1 and r['answer']['confidence']<=.5
    assert '1 additional possible room' in r['answer']['text_md']
    assert 'not a verified total' in r['answer']['text_md']
