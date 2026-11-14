"""KG regression tests against IFC semantic truth and independently transformed metric drawings."""
import json

import pytest

from engine.kg import build
from engine.kg.matching import fit_similarity, transform
from engine.tests.test_kg_core import item, plan, valid, write


@pytest.mark.parametrize('schema',['IFC2X3','IFC4','IFC4X3'])
def test_ifc_semantics_across_schemas(tmp_path,schema):
    ifc=pytest.importorskip('ifcopenshell')
    import ifcopenshell.guid
    f=ifc.file(schema=schema)
    def entity(cls,**kw):
        return f.create_entity(cls,GlobalId=ifcopenshell.guid.new(),**kw)
    st=entity('IfcBuildingStorey',Name='Pohjakerros')
    room=entity('IfcSpace',Name='R101')
    wall=entity('IfcWall',Name='Wall')
    door=entity('IfcDoor',Name='Door',Tag='D12')
    opening=entity('IfcOpeningElement')
    system=entity('IfcSystem',Name='Ventilation')
    typ=entity('IfcDoorStyle' if schema=='IFC2X3' else 'IfcDoorType',Name='Fire door')
    material=f.create_entity('IfcMaterial',Name='Steel')
    entity('IfcRelAggregates',RelatingObject=st,RelatedObjects=[room])
    entity('IfcRelContainedInSpatialStructure',RelatingStructure=st,RelatedElements=[door,wall])
    entity('IfcRelContainedInSpatialStructure',RelatingStructure=room,RelatedElements=[door])
    entity('IfcRelSpaceBoundary',RelatingSpace=room,RelatedBuildingElement=wall,
           PhysicalOrVirtualBoundary='PHYSICAL',InternalOrExternalBoundary='INTERNAL')
    entity('IfcRelVoidsElement',RelatingBuildingElement=wall,RelatedOpeningElement=opening)
    entity('IfcRelFillsElement',RelatingOpeningElement=opening,RelatedBuildingElement=door)
    entity('IfcRelDefinesByType',RelatingType=typ,RelatedObjects=[door])
    entity('IfcRelAssociatesMaterial',RelatingMaterial=material,RelatedObjects=[door])
    entity('IfcRelAssignsToGroup',RelatingGroup=system,RelatedObjects=[door])
    folder=tmp_path/'model'
    write(folder/'doc.json',{'doc_id':'model','kind':'ifc','title':'Building'})
    write(folder/'elements.json',{'storeys':[{'name':st.Name,'elevation_m':0}],
          'elements':[{'item_id':e.GlobalId,'kind':k,'name':e.Name,'ifc_class':e.is_a(),
                       'storey':{'name':st.Name,'elevation_m':0},'props':{},'quantities':{}}
                      for e,k in [(room,'room'),(door,'door'),(wall,'wall')]]})
    f.write(str(folder/'source.ifc'))
    g=build({'id':'semantic','docs':[{'doc_id':'model','role':'model'}]},tmp_path)
    valid(g)
    kinds={e['kind'] for e in g['edges']}
    assert {'on_level','in_room','hosted_by','bounds','part_of_system','has_type','made_of'} <= kinds
    assert not g['warnings']
    d=next(n for n in g['nodes'] if n['kind']=='door')
    assert d['props']['tag']=='D12'
    assert all(e['method']=='ifc_relation' and e['confidence']==1 for e in g['edges'] if e['kind']=='hosted_by')


def test_metric_alignment_label_and_position(tmp_path):
    # Three uniquely named, non-collinear rooms establish a reflected, rotated and translated frame.
    # The unlabelled door must be linked only through its held-out position, never a local item ID.
    origin=[(1,1),(6,1),(1,7)]
    def rotated(x,y):
        return 20-y,10+x
    def drawing(did,points,door):
        its=[item(f'{did}-room-{i}','room',[x*100-10,y*100-10,x*100+10,y*100+10],label=f'R10{i}') for i,(x,y) in enumerate(points)]
        x,y=door
        its.append(item(f'{did}-door','door',[x*100-5,y*100-5,x*100+5,y*100+5]))
        plan(tmp_path,did,its)
    drawing('a',origin,(4,4))
    drawing('b',[rotated(*p) for p in origin],rotated(4,4))
    p={'id':'alignment','docs':[{'doc_id':d,'role':'plan','level':'Ground floor'} for d in ('a','b')]}
    g=build(p,tmp_path)
    valid(g)
    position=[e for e in g['edges'] if e['kind']=='same_as' and e['method']=='position']
    assert len(position)==1
    e=position[0]
    assert e['evidence']['alignment']['matches']==3
    assert e['evidence']['residual_m'] < 1e-6
    assert any(e['kind']=='agrees' and e['evidence']['property']=='door_count' for e in g['edges'])
    # Dropping one anchor makes a positional identity claim unsupported.
    path=tmp_path/'b'/'planmap-1.json'
    data=json.loads(path.read_text());data['items'][2]['label']=None
    write(path,data)
    assert not any(e['method']=='position' for e in build(p,tmp_path)['edges'])


def test_reflection_and_degenerate_alignment():
    a=[[0,0],[2,0],[0,3],[2,3]]
    z=[[7-x,10+y] for x,y in a]
    fit=fit_similarity(list(zip(a,z)))
    assert fit and fit['residual'] < 1e-6
    assert transform([1,1],fit)==pytest.approx([6,11])
    assert fit_similarity([([x,0],[x+1,0]) for x in (0,1,2)]) is None
    assert fit_similarity([([x,y],[100*x,100*y]) for x,y in a]) is None


def test_revision_issue_and_schedule_citations(tmp_path):
    for did in ('older','newer'):
        it=item('d','door',[10,10,20,20]);it['props']={'tag':'D12'}
        plan(tmp_path,did,[it])
    write(tmp_path/'schedule'/'doc.json',{'kind':'text','title':'Door schedule'})
    (tmp_path/'schedule'/'source.txt').write_text('D12: fire door, steel')
    write(tmp_path/'series'/'series.json',{'series_id':'s','versions':[{'doc_id':'older'},{'doc_id':'newer'}]})
    write(tmp_path/'series'/'diffs'/'diff.json',{'doc_a':'older','doc_b':'newer','changes':[
          {'change_id':'c1','type':'modified','v1_item':'d','v2_item':'d','description':'Door changed'}]})
    write(tmp_path/'newer'/'mistakes.json',{'mistakes':[{'id':'i','title':'Check this door','doc_ids':['newer'],
          'item_ids':['d'],'basis':'exact','evidence':{'kind':'missing_property','values':{}},'check':'Check fire rating'}]})
    g=build({'id':'evidence','docs':[{'doc_id':d,'role':'plan' if d!='schedule' else 'schedule','level':'Ground floor'} for d in ('older','newer','schedule')]},tmp_path)
    valid(g)
    assert {'revision_of','changed','flags','references'} <= {e['kind'] for e in g['edges']}
    assert g['stats']['issues']==1
    assert any(n['kind']=='sheet_ref' and n['props']['quote']=='D12: fire door, steel' for n in g['nodes'])
    flags=next(e for e in g['edges'] if e['kind']=='flags')
    assert flags['evidence']['source']['item_id']=='d'


def test_equal_local_ids_are_not_identity_and_missing_scale_is_not_alignment(tmp_path):
    for did in ('a','b'):
        plan(tmp_path,did,[item('same-local-id','door',[1,1,2,2])])
    g=build({'id':'no-false-link','docs':[{'doc_id':d,'role':'plan'} for d in ('a','b')]},tmp_path)
    assert not any(e['kind']=='same_as' for e in g['edges'])


def test_plan_hosts_and_room_boundaries_have_sources(tmp_path):
    plan(tmp_path,'plan',[
         item('r','room',[0,0,100,100],polygon_px=[[0,0],[100,0],[100,100],[0,100]]),
         item('w','wall',[98,0,102,100],polygon_px=[[98,0],[102,0],[102,100],[98,100]]),
         item('d','door',[99,40,101,60])])
    g=build({'id':'hosts','docs':[{'doc_id':'plan','role':'plan'}]},tmp_path)
    valid(g)
    host=next(e for e in g['edges'] if e['kind']=='hosted_by')
    assert host['confidence']<.6 and host['evidence']['wall_source']['item_id']=='w'
    assert any(e['kind']=='bounds' and e['evidence']['room_source']['item_id']=='r' for e in g['edges'])


def test_same_as_has_one_edge_per_cross_document_pair(tmp_path):
    for did in ('a','b','c'):
        write(tmp_path/did/'doc.json',{'doc_id':did,'kind':'ifc'})
        write(tmp_path/did/'elements.json',{'storeys':[{'name':'Ground floor','elevation_m':0}],
              'building':{'building':{'name':'Building'}},'elements':[
              {'item_id':'0AAAAAAAAAAAAAAAAAAAAA','kind':'door','storey':{'name':'Ground floor'},'quantities':{},'props':{}}]})
    g=build({'id':'twins','docs':[{'doc_id':d,'role':'model'} for d in ('a','b','c')]},tmp_path)
    valid(g)
    identities=[e for e in g['edges'] if e['kind']=='same_as']
    assert len(identities)==3
    assert len({frozenset((e['from'],e['to'])) for e in identities})==3
    assert sum(n['canonical'] is not None for n in g['nodes'])==2
