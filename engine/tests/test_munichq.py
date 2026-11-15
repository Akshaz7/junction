"""F-MUNICHQ regression geometry generated for demo/testing; no real-file tuning."""
import json
import math
from pathlib import Path
from unittest.mock import Mock

import pytest

from engine.answer import answer
from engine.ifc_levels import unique_levels
from engine.ifc_overview import answer as overview
from engine.numeric import count_question, guard_count
from engine.solvers.data import Doc, Item
from engine.solvers.solve import resolve_storey
from engine.tests.test_ifc_quantities import model, entity, room_shape, ask, quantity
from pipeline import ifc_quantities as P
from engine import ifc_quantities as Q


LEVELS = [{'name':'0. Foundation','elevation_m':-6.5},
          {'name':'1. Kellergeschoss','elevation_m':-3},
          {'name':'Kellergeschoss','elevation_m':-3},
          {'name':'Kellergeschoss','elevation_m':-3},
          {'name':'2. Erdgeschoss','elevation_m':0},
          {'name':'Erdgeschoss','elevation_m':0}]


def test_level_aliases_and_foundation_are_not_extra_basements():
    assert len(unique_levels(LEVELS)) == 3
    assert resolve_storey('first basement', LEVELS) == '1. Kellergeschoss'
    assert resolve_storey('third basement', LEVELS) is None
    assert resolve_storey('ground floor', LEVELS) == '2. Erdgeschoss'
    assert len(unique_levels([{'name':'East wing','elevation_m':0},{'name':'West wing','elevation_m':0}])) == 2


@pytest.mark.parametrize('names', [('Keller','Untergeschoss'),('Kellari','Kellari 2'),('Källare','Källare 2'),('Basement','Cellar')])
def test_basement_order_nearest_to_ground(names):
    levels=[{'name':names[0],'elevation_m':-3},{'name':names[1],'elevation_m':-6}]
    assert resolve_storey('first basement',levels)==names[0]
    assert resolve_storey('second basement',levels)==names[1]
    assert resolve_storey('third basement',levels) is None


def test_missing_numbered_basement_does_not_relabel_b3_as_b2():
    levels=[{'name':'B1','elevation_m':-3},{'name':'B3','elevation_m':-9}]
    assert resolve_storey('basement 2',levels) is None
    assert resolve_storey('third basement',levels)=='B3'


def test_missing_elevations_are_unavailable_not_zero():
    from engine.ifc_levels import available_levels
    levels=[{'name':'Keller','elevation_m':None}]
    assert 'elevation not recorded' in available_levels(levels)
    assert '(0 m)' not in available_levels(levels)
    assert resolve_storey('ground floor',levels) is None
    assert resolve_storey('first basement',levels) is None


@pytest.mark.parametrize('q',['How many linear metres of baseboard do I need?', 'How many running meters of pipe?', 'How many linear feet of skirting?'])
def test_lengths_survive_the_object_count_guard(q):
    assert not count_question(q)
    res={'answer':{'value':12.25,'unit':'m','abstained':False}}
    assert guard_count(res,q,['test'],Path('/nonexistent')) is res


def test_ifc_overview_is_cited_deduped_and_does_not_invent_missing_area():
    doc=Doc('generated-for-demo','ifc',[
        Item('r1','room',q={'area_m2':12.5},props={'ifc_class':'IfcSpace'}),
        Item('r2','room',props={'ifc_class':'IfcSpace'}),
        Item('d','door',props={'ifc_class':'IfcDoor'})],storeys=LEVELS,
        meta={'building':{'name':'Generated for demo'},'project':{'name':'Demo project'},
              'applications':['Demo exporter'],'schema':'IFC4X3','indexed_units':'m'})
    res=overview('What is this drawing?',doc)
    assert res['ifc_overview']['class_counts']=={'IfcSpace':2,'IfcDoor':1}
    assert res['ifc_overview']['room_area_m2']==12.5
    assert len(res['ifc_overview']['levels'])==3
    assert 'subtotal; 1 rooms' in res['answer']['text_md']
    assert 'Demo exporter' in res['answer']['text_md'] and 'IFC4X3' in res['answer']['text_md']
    assert len(res['citations'])==4 and res['reasoning']['steps']
    assert overview('What is the fire rating?',doc) is None
    assert overview('What is this drawing?',Doc('demo','planmap',[])) is None


@pytest.mark.parametrize('schema',['IFC2X3','IFC4','IFC4X3'])
@pytest.mark.parametrize('unit',['m','mm','ft'])
def test_derived_doors_use_real_outline_units_and_vertical_scope(monkeypatch,schema,unit):
    f=model(schema,unit)
    factor={'m':1,'mm':.001,'ft':.3048}[unit]
    angle=.47
    def rot(x,y):
        return ((x*math.cos(angle)-y*math.sin(angle))/factor,(x*math.sin(angle)+y*math.cos(angle))/factor)
    r=entity(f,'IfcSpace','Generated for demo room')
    # Concave footprint has perimeter 16 m; its bounding box is not the outline.
    room_shape(r,[rot(x,y) for x,y in [(0,0),(4,0),(4,1),(1,1),(1,4),(0,4)]],height=3/factor)
    d=entity(f,'IfcDoor','Boundary door',OverallWidth=1.2/factor)
    room_shape(d,[rot(x,y) for x,y in [(1,-.05),(2.2,-.05),(2.2,.05),(1,.05)]],height=2/factor)
    upper=entity(f,'IfcDoor','Door on floor above',OverallWidth=.9/factor)
    room_shape(upper,[rot(x,y) for x,y in [(1,-.05),(1.9,-.05),(1.9,.05),(1,.05)]],height=2/factor)
    upper.Representation.Representations[0].Items[0].Position.Location.Coordinates=(0.,0.,3/factor)
    res=ask(monkeypatch,f,'What is the baseboard length?',geometry=True)
    assert res['answer']['value']==pytest.approx(14.8)
    assert res['quantity_rows'][0]['door_item_ids']==[d.GlobalId]
    assert res['reasoning']['confidence']['label']=='Estimate'
    from engine.calc import validate
    assert not validate(res['_calc'])
    assert res['_calc']['rows'][0]['values']['perimeter_m']==pytest.approx(16)
    assert '| Room | Level |' in res['answer']['text_md']


def test_inferred_boundary_door_missing_width_abstains(monkeypatch):
    f=model(length='m')
    r=entity(f,'IfcSpace','Generated for demo')
    room_shape(r,[(0,0),(3,0),(3,2),(0,2)])
    d=entity(f,'IfcDoor','Unknown width')
    room_shape(d,[(1,-.05),(2,-.05),(2,.05),(1,.05)],height=2)
    res=ask(monkeypatch,f,'What is the baseboard length?',geometry=True)
    assert res['answer']['value'] is None and res['answer']['abstained']


def test_source_unavailable_does_not_turn_stored_perimeter_into_complete_baseboard(monkeypatch):
    f=model(length='m')
    r=entity(f,'IfcSpace','Generated for demo')
    quantity(r,'Perimeter',10)
    res=ask(monkeypatch,f,'What is the baseboard length?')
    assert res['answer']['value'] is None


@pytest.mark.parametrize('q',['What is the total length of pipes or ducts?', 'How many linear metres of pipes do I need?', 'What is the total duct length?'])
def test_no_mep_has_inventory_evidence_and_never_a_zero_length(monkeypatch,q):
    f=model(length='m')
    entity(f,'IfcWall','Generated for demo wall')
    res=ask(monkeypatch,f,q)
    assert res['answer']['value'] is None and res['answer']['abstained']
    assert 'no pipe' in res['answer']['text_md'] or 'no duct' in res['answer']['text_md']
    assert 'architectural model' in res['answer']['text_md']
    assert '0.00 m' not in res['answer']['text_md']
    assert res['citations'][0]['inventory_check']


def test_missing_basement_is_terminal_cited_and_lists_levels(tmp_path,monkeypatch):
    d=tmp_path/'generated-for-demo';d.mkdir()
    (d/'doc.json').write_text(json.dumps({'kind':'ifc','title':'Generated for demo'}))
    (d/'elements.json').write_text(json.dumps({'schema':'IFC4','units':'m','storeys':LEVELS,
        'elements':[{'item_id':'door','kind':'door','ifc_class':'IfcDoor','storey':{'name':'1. Kellergeschoss'},'props':{'fire_rating':'EI30'}}]}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(tmp_path))
    monkeypatch.setenv('MODELS_FAKE','1')
    monkeypatch.setenv('EXPLAIN','0')
    model_call=Mock(side_effect=AssertionError('A missing level needs no model call'))
    monkeypatch.setattr('engine.models.call',model_call)
    res=answer('What is the fire rating of the doors in the third basement?',[d.name])
    assert res['answer']['abstained'] and res['answer']['value'] is None
    assert 'No matching level' in res['answer']['text_md'] and 'Recorded levels:' in res['answer']['text_md']
    assert 'EI30' not in res['answer']['text_md'] and res['citations']
    model_call.assert_not_called()
