"""IFC quantity semantics across schemas, units, classification and geometry."""
from pathlib import Path
import json
import math
import time

import pytest

ifcopenshell = pytest.importorskip('ifcopenshell')
from ifcopenshell import guid
from pipeline import ifc_quantities as P
from engine import ifc_quantities as Q
from engine.solvers.data import Doc, Item


def model(schema='IFC4', length='mm'):
    f=ifcopenshell.file(schema=schema)
    project=f.create_entity('IfcProject',GlobalId=guid.new(),Name='Quantity tests')
    units=[]
    if length == 'ft':
        metre=f.create_entity('IfcSIUnit',UnitType='LENGTHUNIT',Name='METRE')
        factor=f.create_entity('IfcMeasureWithUnit',ValueComponent=f.create_entity('IfcLengthMeasure',.3048),UnitComponent=metre)
        dims=f.create_entity('IfcDimensionalExponents',1,0,0,0,0,0,0)
        units.append(f.create_entity('IfcConversionBasedUnit',Dimensions=dims,UnitType='LENGTHUNIT',Name='FOOT',ConversionFactor=factor))
    elif length:
        units.append(f.create_entity('IfcSIUnit',UnitType='LENGTHUNIT',Prefix='MILLI' if length=='mm' else None,Name='METRE'))
    units.extend([f.create_entity('IfcSIUnit',UnitType='AREAUNIT',Name='SQUARE_METRE'),
                  f.create_entity('IfcSIUnit',UnitType='VOLUMEUNIT',Name='CUBIC_METRE'),
                  f.create_entity('IfcSIUnit',UnitType='MASSUNIT',Prefix='KILO',Name='GRAM')])
    project.UnitsInContext=f.create_entity('IfcUnitAssignment',Units=units)
    return f


def entity(f,cls,name,**kw):
    return f.create_entity(cls,GlobalId=guid.new(),Name=name,**kw)


def pset(el, name, values):
    f=el.file
    props=[f.create_entity('IfcPropertySingleValue',Name=k,NominalValue=f.create_entity(t,v),Unit=unit)
           for k,(t,v,unit) in values.items()]
    ps=f.create_entity('IfcPropertySet',GlobalId=guid.new(),Name=name,HasProperties=props)
    f.create_entity('IfcRelDefinesByProperties',GlobalId=guid.new(),RelatedObjects=[el],RelatingPropertyDefinition=ps)
    return ps


def quantity(el, name, val, unit=None, quantity_type='IfcQuantityLength', value_attr='LengthValue'):
    f=el.file
    q=f.create_entity(quantity_type,Name=name,Unit=unit,**{value_attr:val})
    ps=f.create_entity('IfcElementQuantity',GlobalId=guid.new(),Name='Qto_TestBaseQuantities',Quantities=[q])
    f.create_entity('IfcRelDefinesByProperties',GlobalId=guid.new(),RelatedObjects=[el],RelatingPropertyDefinition=ps)


def attach_type(el, cls, name, predefined=None):
    f=el.file
    typ=entity(f,cls,name,**({'PredefinedType':predefined} if predefined else {}))
    f.create_entity('IfcRelDefinesByType',GlobalId=guid.new(),RelatedObjects=[el],RelatingType=typ)
    return typ


def ask(monkeypatch,f,q,*,geometry=False,index=None,storeys=()):
    idx=P.build(f,space_geometry=geometry) if index is None else index
    assert not idx.get('errors'),idx.get('errors')
    monkeypatch.setattr(Q,'load_index',lambda doc:idx)
    monkeypatch.setattr(Q,'_source',lambda *a:None)
    items=[Item(r['item_id'],r['kind'],name=r.get('name'),q=r['quantities']) for r in idx['rows']]
    doc=Doc('test-model','ifc',items,title='Quantity tests',storeys=list(storeys))
    result=Q.answer(q,doc,time.perf_counter())
    assert result is not None
    assert any(t['step']=='calc' for t in result['trace'])
    assert result['reasoning']['steps']
    return result


@pytest.mark.parametrize('schema',['IFC2X3','IFC4','IFC4X3'])
@pytest.mark.parametrize('length,value',[('mm',200.),('m',.2),('ft',.2/.3048)])
def test_count_thickness_uses_units_and_returns_count(monkeypatch,schema,length,value):
    f=model(schema,length)
    wall=entity(f,'IfcWall','Wall')
    quantity(wall,'Width',value)
    quantity(entity(f,'IfcWall','Other wall'),'Width',value*2)
    r=ask(monkeypatch,f,'How many walls are 200 mm thick?')
    assert r['answer']['value']==1 and r['answer']['unit']=='count'
    assert r['citations'][0]['item_ids']==[wall.GlobalId]
    assert '200 mm' in r['trace'][1]['detail']


def test_material_layers_inherited_from_type(monkeypatch):
    f=model()
    wall=entity(f,'IfcWall','Wall')
    typ=attach_type(wall,'IfcWallType','WK200')
    mat=f.create_entity('IfcMaterial',Name='Concrete')
    layers=[f.create_entity('IfcMaterialLayer',Material=mat,LayerThickness=v) for v in (120.,80.)]
    layer_set=f.create_entity('IfcMaterialLayerSet',MaterialLayers=layers,LayerSetName='Layered wall')
    f.create_entity('IfcRelAssociatesMaterial',GlobalId=guid.new(),RelatedObjects=[typ],RelatingMaterial=layer_set)
    r=ask(monkeypatch,f,'How many walls of type WK200 are 200 mm thick?')
    assert r['answer']['value']==1
    assert 'type/size WK200' in r['trace'][1]['detail']


def test_slab_depth_count_and_partial_type_code(monkeypatch):
    f=model()
    s=entity(f,'IfcSlab','Floor')
    attach_type(s,'IfcSlabType','FLOATING_SCREED 90',predefined='FLOOR')
    quantity(s,'Depth',90.)
    quantity(s,'GrossArea',19.,quantity_type='IfcQuantityArea',value_attr='AreaValue')
    other=entity(f,'IfcSlab','Other floor')
    attach_type(other,'IfcSlabType','STRUCTURAL 90',predefined='FLOOR')
    quantity(other,'Depth',90.)
    for q in ('How many slabs are 90 mm thick?', 'How many 90 mm slabs (FLOATING_SCREED) are there?'):
        r=ask(monkeypatch,f,q)
        assert r['answer']['value']==(2 if 'thick' in q else 1)
        assert r['answer']['unit']=='count'


def test_external_predefined_and_type_filters_are_combined(monkeypatch):
    f=model()
    for outside in (True,False):
        e=entity(f,'IfcWall','Wall')
        attach_type(e,'IfcWallType','Panel',predefined='STANDARD')
        pset(e,'Pset_WallCommon',{'IsExternal':('IfcBoolean',outside,None)})
    r=ask(monkeypatch,f,'How many external walls of predefined type STANDARD are there?')
    assert r['answer']['value']==1


def test_recorded_matches_disclose_unknown_thickness(monkeypatch):
    f=model()
    quantity(entity(f,'IfcWall','Known'),'Width',200.)
    entity(f,'IfcWall','Unknown')
    r=ask(monkeypatch,f,'How many walls are 200 mm thick?')
    assert r['answer']['value']==1
    assert 'excluded' in r['answer']['text_md'] and r['answer']['confidence']<.92


@pytest.mark.parametrize('cls,word',[('IfcReinforcingBar','reinforcing bars'),('IfcReinforcingMesh','reinforcing meshes'),('IfcTendon','tendons')])
def test_reinforcement_kinds_count(monkeypatch,cls,word):
    f=model()
    el=entity(f,cls,'Reinforcement')
    r=ask(monkeypatch,f,f'How many {word} are in the model?')
    assert r['answer']['value']==1
    assert el.GlobalId in r['citations'][0]['item_ids']


def test_rebar_typed_length_diameter_role_and_mass(monkeypatch):
    f=model()
    b=entity(f,'IfcReinforcingBar','Bar',NominalDiameter=16.,BarLength=2000.)
    pset(b,'Pset_ReinforcingBarCommon',{'BarRole':('IfcLabel','MAIN',None)})
    mass_unit=f.create_entity('IfcSIUnit',UnitType='MASSUNIT',Name='GRAM')
    pset(b,'Quantities',{'Mass':('IfcMassMeasure',3200.,mass_unit)})
    assert ask(monkeypatch,f,'How many reinforcing bars are 16 mm diameter?')['answer']['value']==1
    assert ask(monkeypatch,f,'How many reinforcing bars of role MAIN?')['answer']['value']==1
    assert ask(monkeypatch,f,'What is the total length of reinforcing bars?')['answer']['value']==2.
    assert ask(monkeypatch,f,'What is the total weight of reinforcing bars?')['answer']['value']==3.2


def test_no_default_steel_density(monkeypatch):
    f=model()
    entity(f,'IfcReinforcingBar','Bar',NominalDiameter=16.,BarLength=2000.)
    r=ask(monkeypatch,f,'What is the total weight of reinforcing bars?')
    assert r['answer']['value'] is None and r['answer']['abstained']
    assert 'no steel density' in r['answer']['text_md']


def test_weight_from_recorded_density(monkeypatch):
    f=model(length='m')
    b=entity(f,'IfcReinforcingBar','Bar',NominalDiameter=.02,BarLength=2.)
    kg=f.by_type('IfcSIUnit')[-1]
    metre=next(x for x in f.by_type('IfcSIUnit') if x.UnitType=='LENGTHUNIT')
    du=f.create_entity('IfcDerivedUnit',Elements=[f.create_entity('IfcDerivedUnitElement',Unit=kg,Exponent=1),
                                                f.create_entity('IfcDerivedUnitElement',Unit=metre,Exponent=-3)],UnitType='MASSDENSITYUNIT')
    pset(b,'Material',{'MassDensity':('IfcMassDensityMeasure',7800.,du)})
    r=ask(monkeypatch,f,'What is the total mass of reinforcing bars?')
    assert r['answer']['value']==pytest.approx(math.pi*.01**2*2*7800,abs=.0001)


def test_unknown_index_does_not_claim_zero_even_with_force_answer(monkeypatch,tmp_path):
    root=tmp_path/'artifacts';d=root/'test-model';d.mkdir(parents=True)
    (d/'doc.json').write_text(json.dumps({'title':'Quantity tests','kind':'ifc','formats':['ifc']}))
    (d/'elements.json').write_text(json.dumps({'elements':[{'item_id':'wall','kind':'wall','ifc_class':'IfcWall','name':'Wall'}]}))
    monkeypatch.setenv('ARTIFACTS_DIR',str(root))
    monkeypatch.setenv('MODELS_FAKE','1')
    monkeypatch.setenv('FORCE_ANSWER','1')
    from engine.answer import answer
    r=answer('How many reinforcing bars are in this model?',['test-model'])
    assert r['answer']['value'] is None and r['answer']['abstained']
    assert 'not indexed' in r['answer']['text_md']
    assert r['cost']['usd_total']==0


def test_known_empty_rebar_coverage_can_return_model_zero(monkeypatch):
    f=model()
    r=ask(monkeypatch,f,'How many reinforcing bars are in this model?')
    assert r['answer']['value']==0 and not r['answer']['abstained']


def test_quoted_storey_is_not_a_type(monkeypatch):
    f=model()
    w=entity(f,'IfcWall','Wall')
    st=entity(f,'IfcBuildingStorey','Upper floor',Elevation=3000.)
    f.create_entity('IfcRelContainedInSpatialStructure',GlobalId=guid.new(),RelatedElements=[w],RelatingStructure=st)
    idx=P.build(f)
    rows, label=Q._type_filter("How many walls on the floor plan of 'Upper floor'?",idx['rows'],['Upper floor'])
    assert len(rows)==1 and label is None


def room_shape(space, points, height=3.):
    f=space.file
    axis=f.create_entity('IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=(0.,0.,0.)))
    context=f.create_entity('IfcGeometricRepresentationContext',ContextIdentifier='Model',ContextType='Model',CoordinateSpaceDimension=3,Precision=1e-7,WorldCoordinateSystem=axis)
    pts=[f.create_entity('IfcCartesianPoint',Coordinates=tuple(map(float,p))) for p in [*points,points[0]]]
    profile=f.create_entity('IfcArbitraryClosedProfileDef',ProfileType='AREA',OuterCurve=f.create_entity('IfcPolyline',Points=pts))
    solid=f.create_entity('IfcExtrudedAreaSolid',SweptArea=profile,Position=axis,ExtrudedDirection=f.create_entity('IfcDirection',DirectionRatios=(0.,0.,1.)),Depth=height)
    rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=context,RepresentationIdentifier='Body',RepresentationType='SweptSolid',Items=[solid])
    space.Representation=f.create_entity('IfcProductDefinitionShape',Representations=[rep])


def boundary(room,door=None):
    return room.file.create_entity('IfcRelSpaceBoundary',GlobalId=guid.new(),RelatingSpace=room,RelatedBuildingElement=door,
                                   PhysicalOrVirtualBoundary='PHYSICAL',InternalOrExternalBoundary='INTERNAL')


def test_floor_geometry_is_not_a_box_and_doors_deduplicate(monkeypatch):
    f=model(length='m')
    a=entity(f,'IfcSpace','101',LongName='Office')
    # Rotated rectangle: a bounding box would overestimate its perimeter.
    angle=.4
    rot=lambda p:(p[0]*math.cos(angle)-p[1]*math.sin(angle),p[0]*math.sin(angle)+p[1]*math.cos(angle))
    room_shape(a,[rot(p) for p in [(0,0),(4,0),(4,2),(0,2)]])
    d=entity(f,'IfcDoor','Door',OverallWidth=.9)
    boundary(a,d);boundary(a,d)
    b=entity(f,'IfcSpace','102',LongName='Office')
    room_shape(b,[(0,0),(2,0),(2,1),(1,1),(1,3),(0,3)])
    boundary(b)
    r=ask(monkeypatch,f,'How many linear metres of baseboard for room 101 (Office)?',geometry=True)
    assert r['answer']['value']==pytest.approx(11.1)
    assert r['quantity_rows'][0]['door_width_m']==.9
    assert len(r['quantity_rows'][0]['door_item_ids'])==1
    r=ask(monkeypatch,f,'How many linear metres of skirting per room?',geometry=True)
    assert sorted(x['value'] for x in r['quantity_rows'])==pytest.approx([10.,11.1])
    assert r['answer']['value']==pytest.approx(21.1)


def test_room_without_boundaries_uses_geometry_and_is_estimate(monkeypatch):
    f=model(length='m')
    a=entity(f,'IfcSpace','201')
    room_shape(a,[(0,0),(2,0),(2,3),(0,3)])
    r=ask(monkeypatch,f,'What is the baseboard length for room 201?',geometry=True)
    assert r['answer']['value'] == pytest.approx(10.)
    assert r['reasoning']['confidence']['label'] == 'Estimate'
    assert r['quantity_rows'][0]['boundary_method'].startswith('derived:')


def test_unknown_apartment_prefix_is_not_a_verified_group(monkeypatch):
    f=model(length='m')
    a=entity(f,'IfcSpace','C101')
    room_shape(a,[(0,0),(2,0),(2,3),(0,3)])
    boundary(a)
    r=ask(monkeypatch,f,'What is the baseboard length for all rooms in unit C?',geometry=True)
    assert r['answer']['value'] is None and 'prefixes' in r['answer']['text_md']


@pytest.mark.parametrize('schema',['IFC2X3','IFC4','IFC4X3'])
def test_all_terminal_descendants_and_families(monkeypatch,schema):
    f=model(schema)
    entity(f,'IfcFlowTerminal','Other outlet')
    entity(f,'IfcAirTerminal','Diffuser') if schema!='IFC2X3' else attach_type(entity(f,'IfcFlowTerminal','Diffuser'),'IfcAirTerminalType','Supply diffuser',predefined='DIFFUSER')
    p=entity(f,'IfcFlowSegment','Rectangular Duct:Type A',ObjectType='Rectangular Duct')
    quantity(p,'Length',2000.)
    p=entity(f,'IfcFlowSegment','Round Duct:Type B',ObjectType='Round Duct')
    quantity(p,'Length',3000.)
    p=entity(f,'IfcFlowSegment','Flex Duct:Type C',ObjectType='Flex Duct')
    quantity(p,'Length',4000.)
    quantity(p,'Diameter',100.)
    r=ask(monkeypatch,f,'How many air terminals and other flow terminals are there?')
    assert r['answer']['value']==2
    r=ask(monkeypatch,f,'What is the total length of round duct?')
    assert r['answer']['value']==3.
    r=ask(monkeypatch,f,'What is the total length of all ductwork (rectangular, round and flexible)?')
    assert r['answer']['value']==9.


def test_typed_mep_family_wins_over_fitting_words(monkeypatch):
    f=model()
    d=entity(f,'IfcDuctSegment','Rectangular Duct:Mitered Elbows / Taps')
    quantity(d,'Length',2500.)
    # This is a segment, even though the Revit family contains "Elbows".
    r=ask(monkeypatch,f,'How many rectangular duct segments are there?')
    assert r['answer']['value']==1
    assert ask(monkeypatch,f,'What is the total length of rectangular duct?')['answer']['value']==2.5


def test_mep_grouped_by_system_no_double_count(monkeypatch):
    f=model()
    p=entity(f,'IfcPipeSegment','Pipe')
    quantity(p,'Length',2000.)
    sy=entity(f,'IfcDistributionSystem','Supply',PredefinedType='DOMESTICCOLDWATER')
    f.create_entity('IfcRelAssignsToGroup',GlobalId=guid.new(),RelatedObjects=[p],RelatingGroup=sy)
    r=ask(monkeypatch,f,'What is the total length of pipe by system?')
    assert r['answer']['value']==2.
    assert r['quantity_rows'][0]['label']=='Supply'


def test_untyped_internal_units_are_not_assumed(monkeypatch):
    f=model()
    p=entity(f,'IfcPipeSegment','Pipe')
    pset(p,'Dimensions',{'Length':('IfcReal',10.,None)})
    r=ask(monkeypatch,f,'What is the total length of pipe?')
    assert r['answer']['value'] is None


def test_bent_bar_uses_centreline_not_box(monkeypatch):
    f=model(length='m')
    b=entity(f,'IfcReinforcingBar','Bent bar')
    origin=f.create_entity('IfcAxis2Placement3D',Location=f.create_entity('IfcCartesianPoint',Coordinates=(0.,0.,0.)))
    context=f.create_entity('IfcGeometricRepresentationContext',ContextType='Model',CoordinateSpaceDimension=3,Precision=1e-7,WorldCoordinateSystem=origin)
    points=[f.create_entity('IfcCartesianPoint',Coordinates=p) for p in ((0.,0.,0.),(2.,0.,0.),(2.,1.,0.))]
    solid=f.create_entity('IfcSweptDiskSolid',Directrix=f.create_entity('IfcPolyline',Points=points),Radius=.01)
    rep=f.create_entity('IfcShapeRepresentation',ContextOfItems=context,RepresentationIdentifier='Body',RepresentationType='AdvancedSweptSolid',Items=[solid])
    b.Representation=f.create_entity('IfcProductDefinitionShape',Representations=[rep])
    r=ask(monkeypatch,f,'What is the total length of reinforcing bars?')
    assert r['answer']['value']==3.
    assert 'centreline' in r['trace'][-1]['detail']


def test_parenthesized_type_beats_predefined_class(monkeypatch):
    f=model()
    for name in ('ROOF_PANEL R=4,00 206','ROOF_PANEL R=5,00 250'):
        e=entity(f,'IfcSlab','Roof')
        attach_type(e,'IfcSlabType',name,predefined='ROOF')
    r=ask(monkeypatch,f,'How many roof slabs (ROOF_PANEL R=4,00) are there?')
    assert r['answer']['value']==1
    assert 'R=4,00' in r['trace'][1]['detail']


def test_apartment_assignment_allows_baseboard_total(monkeypatch):
    f=model(length='m')
    a=entity(f,'IfcSpace','C101')
    room_shape(a,[(0,0),(2,0),(2,3),(0,3)])
    boundary(a)
    zone=entity(f,'IfcZone','Unit C')
    f.create_entity('IfcRelAssignsToGroup',GlobalId=guid.new(),RelatedObjects=[a],RelatingGroup=zone)
    r=ask(monkeypatch,f,'What is the baseboard length for all rooms in unit C?',geometry=True)
    assert r['answer']['value']==10.


def test_sidecar_is_durable_before_page_images(monkeypatch,tmp_path):
    from server import artifact_store as store
    monkeypatch.setattr(store.config,'artifacts_dir',lambda:tmp_path)
    monkeypatch.setattr(store,'MAX_DOC_BYTES',1)
    d=tmp_path/'test-model';d.mkdir()
    (d/'ifc-quantities.json').write_text('{}')
    (d/'page-1.png').write_bytes(b'not-a-real-image')
    assert [name for name,p in store.doc_files('test-model')]==['ifc-quantities.json']


def test_mep_named_system_and_diameter_are_filters(monkeypatch):
    f=model()
    p=entity(f,'IfcPipeSegment','Pipe',PredefinedType='RIGIDSEGMENT')
    quantity(p,'Length',2000.)
    quantity(p,'Diameter',100.)
    other=entity(f,'IfcPipeSegment','Other',PredefinedType='FLEXIBLESEGMENT')
    quantity(other,'Length',3000.)
    quantity(other,'Diameter',50.)
    sy=entity(f,'IfcDistributionSystem','Service X',PredefinedType='DOMESTICCOLDWATER')
    f.create_entity('IfcRelAssignsToGroup',GlobalId=guid.new(),RelatedObjects=[p],RelatingGroup=sy)
    for question in ('What is the length of pipe in system "Service X"?', 'What is the length of pipe in the "Service X" system?',
                     'What is the total length of DN100 pipe?', 'What is the length of pipe of predefined type RIGIDSEGMENT?'):
        r=ask(monkeypatch,f,question)
        assert r['answer']['value']==2.,question
        assert r['citations'][0]['item_ids']==[p.GlobalId]


def test_floor_words_in_a_type_do_not_set_storey_scope(monkeypatch):
    f=model()
    for name in ('Floor 2 - concrete','Basement roof'):
        s=entity(f,'IfcSlab','Slab')
        attach_type(s,'IfcSlabType',name,predefined='FLOOR')
        r=ask(monkeypatch,f,f'How many slabs of type "{name}" are there?')
        assert r['answer']['value']==1
    st=entity(f,'IfcBuildingStorey','Ground level',Elevation=0.)
    f.create_entity('IfcRelContainedInSpatialStructure',GlobalId=guid.new(),RelatedElements=[s],RelatingStructure=st)
    r=ask(monkeypatch,f,'How many slabs of type "Basement roof" are on the ground floor?',storeys=[{'name':'Ground level','elevation_m':0.}])
    assert r['answer']['value']==1
    assert 'floor Ground level' in r['trace'][1]['detail']


def test_literal_type_words_are_not_extra_property_filters(monkeypatch):
    f=model()
    e=entity(f,'IfcWall','Wall')
    attach_type(e,'IfcWallType',"Builder's exterior wall, 200 mm thick")
    r=ask(monkeypatch,f,'How many walls of type "Builder\'s exterior wall, 200 mm thick" are there?')
    assert r['answer']['value']==1
    assert 'thickness 200 mm' not in r['trace'][1]['detail']


def test_ingested_sidecar_answers_without_source_and_validates(monkeypatch,tmp_path):
    import jsonschema
    f=model()
    b=entity(f,'IfcReinforcingBar','Bar',BarLength=1250.)
    root=tmp_path/'artifacts';d=root/'test-model';d.mkdir(parents=True)
    (d/'doc.json').write_text(json.dumps({'title':'Quantity tests','kind':'ifc','formats':['ifc']}))
    (d/'elements.json').write_text(json.dumps({'elements':[{'item_id':b.GlobalId,'kind':'other','ifc_class':'IfcReinforcingBar','name':'Bar'}]}))
    sidecar=d/'ifc-quantities.json'
    index=P.build(f)
    sidecar.write_text(json.dumps(index))
    monkeypatch.setenv('ARTIFACTS_DIR',str(root))
    monkeypatch.setenv('MODELS_FAKE','1')
    from engine.answer import answer
    r=answer('What is the total length of reinforcing bars?',['test-model'])
    assert r['answer']['value']==1.25
    assert r['citations'][0]['item_ids']==[b.GlobalId]
    schema=Path(__file__).resolve().parents[2]/'server/schemas/answer.schema.json'
    jsonschema.validate(r,json.loads(schema.read_text()))
    index['rows'][0]['quantities']['length_m']=2.5
    sidecar.write_text(json.dumps(index))
    assert answer('What is the total length of reinforcing bars?',['test-model'])['answer']['value']==2.5
