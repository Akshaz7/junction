"""General request shapes: synthetic dimensions and translated labels, no suite ids in production."""
import time
from pathlib import Path

import pytest

from engine.solvers.data import Doc, Item
from engine.solvers.requests import adjacent_request, dimension_request, quantity_followup, summary_request


def result_ids(r):
    return {i for c in r['citations'] for i in c['item_ids']}


def test_dimension_schedule_keeps_every_size_and_missing_row():
    its = [Item('a','window',q={'width_m':.8,'height_m':1.2}),
           Item('b','window',q={'width_m':.8,'height_m':1.2}),
           Item('c','window',q={'width_m':.8,'height_m':1.8}), Item('d','window')]
    d = Doc('generated-for-demo', 'ifc', its)
    r = dimension_request('How many windows of each size are there?', d, its, None, time.perf_counter())
    assert '| 0.8 × 1.2 m | 2 |' in r['answer']['text_md']
    assert '| 0.8 × 1.8 m | 1 |' in r['answer']['text_md']
    assert '1 windows have incomplete' in r['answer']['text_md']
    assert r['answer']['value'] == 4 and result_ids(r) == {'a','b','c','d'}
    assert r['answer']['confidence'] < 1


@pytest.mark.parametrize('q', ['How many windows are 800 mm wide and 180 cm high?',
                              'How many windows are 0.8 m wide and 1.8 m high?'])
def test_both_dimensions_are_applied(q):
    its = [Item('a','window',q={'width_m':.8,'height_m':1.2}),
           Item('b','window',q={'width_m':.8,'height_m':1.8}), Item('c','window',q={'width_m':.8})]
    d=Doc('generated-for-demo','ifc',its)
    r=dimension_request(q,d,its,None,time.perf_counter())
    assert r['answer']['value'] == 1 and result_ids(r) == {'b'}
    assert '1 have incomplete' in r['answer']['text_md']


def test_takeoff_respects_explicitly_requested_quantities():
    its=[Item('r','room',q={'net_floor_area_m2':32.1}), Item('w','wall',q={'length_m':11.2}),
         Item('d','door'),Item('x','window')]
    d=Doc('generated-for-demo','ifc',its)
    r=summary_request('Make a quantity take-off: floor area, wall length, doors, windows',d,its,'Entry',time.perf_counter())
    assert '| Net floor area | 32.1 | m² |' in r['answer']['text_md']
    assert '| Wall length | 11.2 | m |' in r['answer']['text_md']
    assert '| Doors | 1 | count |' in r['answer']['text_md']
    assert result_ids(r) == {'r','w','d','x'}


def test_adjacency_is_same_level_side_contact_not_diagonals():
    its=[Item('r','room',name='Workshop',bbox_m=[[0,0,0],[4,3,5]],storey='Entry'),
         Item('n','room',name='Pantry',bbox_m=[[4.2,0,0],[6,3,5]],storey='Entry'),
         Item('z','room',name='Other level',bbox_m=[[4.2,3,0],[6,6,5]],storey='Upper'),
         Item('corner','room',name='Diagonal',bbox_m=[[4.2,0,5.2],[6,3,8]],storey='Entry'),
         Item('w','wall',q={'width_m':.2},storey='Entry')]
    d=Doc('generated-for-demo','ifc',its)
    r=adjacent_request('Which rooms are next to the Workshop?',d,its,None,time.perf_counter())
    assert result_ids(r) == {'r','n'}
    assert r['answer']['confidence'] <= .6 and 'need checking' in r['answer']['text_md']


def test_cost_followup_retains_previous_waste():
    prev='How many square metres of tiles for the bathrooms with 7% waste?'
    q='What would those tiles cost at 42 EUR per m2?'
    r=quantity_followup(q,[{'role':'user','content':prev}])
    assert '7% waste' in r and '42 EUR per m2' in r
    assert quantity_followup(q,[]) is None
    assert quantity_followup('How many doors are there?',[{'role':'user','content':prev}]) is None


@pytest.mark.parametrize('q', ['Kuinka monta ovea pohjakerroksessa on?', 'Wie viele Türen gibt es im Erdgeschoss?', 'Hur många dörrar finns det på bottenvåningen?'])
def test_translated_count_keeps_kind_and_floor(q):
    from engine.solvers.requests import translate_count
    assert translate_count(q)=='How many doors are there on the ground floor?'


def test_unknown_foreign_qualifiers_are_not_discarded():
    from engine.solvers.requests import translate_count
    assert translate_count('Kuinka monta ovea on yli 900 mm leveitä?') is None


def test_numeric_reader_result_with_only_citation_marks_gets_prose():
    from engine.solvers.requests import ensure_answer_text
    res={'answer':{'text_md':' [1]','value':13700,'unit':'mm','abstained':False},'citations':[{'n':1}]}
    r=ensure_answer_text(res)
    assert '**13700 mm**' in r['answer']['text_md']
    r=ensure_answer_text({'answer':{'text_md':'[1]','value':None},'citations':[{'n':1}]})
    assert 'could not verify' in r['answer']['text_md'] and r['answer']['value'] is None


def test_schedule_retains_inside_outside_filter_and_missing_flags():
    its=[Item('a','door',q={'width_m':.9},props={'is_external':True}),
         Item('b','door',q={'width_m':1.2},props={'is_external':False})]
    d=Doc('generated-for-demo','ifc',its)
    r=dimension_request('Give a schedule of external doors by width',d,its,None,time.perf_counter())
    assert r['answer']['value']==1 and result_ids(r)=={'a'}
    its[1].props={}
    r=dimension_request('Give a schedule of external doors by width',d,its,None,time.perf_counter())
    assert r['answer']['value'] is None and 'No unfiltered' in r['answer']['text_md']


def test_exact_dimension_handler_does_not_discard_comparator():
    d=Doc('generated-for-demo','ifc',[])
    assert dimension_request('How many windows are at least 0.8 m wide and 1.2 m high?',d,[],None,time.perf_counter()) is None
