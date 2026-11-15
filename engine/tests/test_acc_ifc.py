"""Small generated-for-test IFC fixtures; no dataset or benchmark documents."""
import json
import math
from pathlib import Path
import time

import ifcopenshell
import pytest

from pipeline.ifc_accuracy import build, count_metadata, space_area, stored_net_area
from engine.ifc_accuracy import guard, prepare_doc
from engine.solvers.data import Doc, Item, load_doc
from engine.solvers.solve import solve, _answer_obj, _qty


def entity(f, cls, name=None, **kw):
    return f.create_entity(cls, GlobalId=ifcopenshell.guid.new(), Name=name, **kw)


def model(schema='IFC4', length='m', area='m2'):
    f = ifcopenshell.file(schema=schema)
    metre = f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE')
    square = f.create_entity('IfcSIUnit', UnitType='AREAUNIT', Name='SQUARE_METRE')
    if length == 'mm':
        metre.Prefix = 'MILLI'
    elif length == 'ft':
        metre = f.create_entity('IfcConversionBasedUnit',
            Dimensions=f.create_entity('IfcDimensionalExponents', 1, 0, 0, 0, 0, 0, 0),
            UnitType='LENGTHUNIT', Name='foot',
            ConversionFactor=f.create_entity('IfcMeasureWithUnit', f.create_entity('IfcLengthMeasure', .3048), metre))
    if area == 'ft2':
        square = f.create_entity('IfcConversionBasedUnit',
            Dimensions=f.create_entity('IfcDimensionalExponents', 2, 0, 0, 0, 0, 0, 0),
            UnitType='AREAUNIT', Name='square foot',
            ConversionFactor=f.create_entity('IfcMeasureWithUnit', f.create_entity('IfcAreaMeasure', .3048**2), square))
    elif area == 'mm2':
        square.Prefix = 'MILLI'
    units = [metre, square] if length else [square]
    entity(f, 'IfcProject', 'Generated for test', UnitsInContext=f.create_entity('IfcUnitAssignment', units))
    return f


def aggregate(f, parent, *children):
    return entity(f, 'IfcRelAggregates', RelatingObject=parent, RelatedObjects=children)


def room(f, points=((0, 0), (4, 0), (4, 3), (0, 3)), *, holes=(), net=None, unit=None, name='101', tilt=0):
    zero = f.create_entity('IfcCartesianPoint', (0., 0., 0.))
    axis = f.create_entity('IfcAxis2Placement3D', Location=zero)
    ctx = f.create_entity('IfcGeometricRepresentationContext', ContextType='Model',
                         CoordinateSpaceDimension=3, Precision=1e-5, WorldCoordinateSystem=axis)
    def curve(vertices):
        vertices = list(vertices)
        return f.create_entity('IfcPolyline', [f.create_entity('IfcCartesianPoint', tuple(map(float, xy))) for xy in vertices + vertices[:1]])
    outer = curve(points)
    profile = (f.create_entity('IfcArbitraryProfileDefWithVoids', ProfileType='AREA', OuterCurve=outer, InnerCurves=[curve(p) for p in holes]) if holes else
               f.create_entity('IfcArbitraryClosedProfileDef', ProfileType='AREA', OuterCurve=outer))
    solid = f.create_entity('IfcExtrudedAreaSolid', SweptArea=profile, Position=axis,
                            ExtrudedDirection=f.create_entity('IfcDirection', (0., 0., 1.)), Depth=2.)
    rep = f.create_entity('IfcShapeRepresentation', ctx, 'Body', 'SweptSolid', [solid])
    placement = f.create_entity('IfcAxis2Placement3D', Location=zero,
                               Axis=f.create_entity('IfcDirection', (math.sin(tilt), 0., math.cos(tilt))))
    space = entity(f, 'IfcSpace', name, Representation=f.create_entity('IfcProductDefinitionShape', Representations=[rep]),
                   ObjectPlacement=f.create_entity('IfcLocalPlacement', RelativePlacement=placement))
    if net is not None:
        q = f.create_entity('IfcQuantityArea', Name='NetFloorArea', AreaValue=float(net), Unit=unit)
        qt = entity(f, 'IfcElementQuantity', 'Qto_SpaceBaseQuantities', Quantities=[q])
        entity(f, 'IfcRelDefinesByProperties', RelatedObjects=[space], RelatingPropertyDefinition=qt)
    return space


def document(tmp_path, f, *, omit=(), q=None):
    did = 'synthetic__generated-for-test'
    d = tmp_path / did
    d.mkdir(exist_ok=True)
    f.write(str(d / 'source.ifc'))
    from pipeline.ifc_scene import kind_of, quantities_of, storey_of
    els = []
    for e in f.by_type('IfcProduct'):
        if not (e.is_a('IfcElement') or e.is_a('IfcSpace')) or e.GlobalId in omit:
            continue
        st = storey_of(e)
        els.append({'item_id': e.GlobalId, 'ifc_class': e.is_a(), 'kind': kind_of(e),
                    'name': e.Name, 'props': {}, 'quantities': q if q is not None else quantities_of(e, 1.),
                    'storey': {'name': st.Name, 'elevation_m': st.Elevation or 0.} if st else None})
    (d / 'elements.json').write_text(json.dumps({'elements': els, 'storeys': [{'name': e.Name, 'elevation_m': e.Elevation or 0.} for e in f.by_type('IfcBuildingStorey')]}))
    return did


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('EXPLAIN', '0')


@pytest.mark.parametrize('schema', ['IFC2X3', 'IFC4', 'IFC4X3'])
def test_related_flights_only_and_nested_same_class(schema, tmp_path):
    f = model(schema)
    stair = entity(f, 'IfcStair', 'Stair assembly')
    child = entity(f, 'IfcStair', 'Part of assembly')
    flight = entity(f, 'IfcStairFlight', 'Related flight')
    solo = entity(f, 'IfcStairFlight', 'Independent flight')
    aggregate(f, stair, child)
    aggregate(f, child, flight)
    assert count_metadata(flight)['count_component_of'] == stair.GlobalId
    assert count_metadata(solo)['count_component_of'] is None
    did = document(tmp_path, f)
    result = solve('How many stairs are in this model?', did, root=tmp_path)
    assert result['answer']['value'] == 2
    assert {g for c in result['citations'] for g in c['item_ids']} == {stair.GlobalId, solo.GlobalId}


def test_same_family_subtypes_but_not_other_products(tmp_path):
    f = model()
    wall = entity(f, 'IfcWall', 'Assembly')
    part = entity(f, 'IfcWallStandardCase', 'Part')
    door = entity(f, 'IfcDoor', 'Door')
    aggregate(f, wall, part, door)
    assert count_metadata(part)['count_component_of'] == wall.GlobalId
    assert count_metadata(door)['count_component_of'] is None
    did = document(tmp_path, f)
    assert solve('How many walls?', did, root=tmp_path)['answer']['value'] == 1
    assert solve('How many doors?', did, root=tmp_path)['answer']['value'] == 1


def test_stair_type_is_not_an_occurrence(tmp_path):
    f = model()
    entity(f, 'IfcStair', 'Occurrence')
    typ = entity(f, 'IfcStairType', 'Type', PredefinedType='NOTDEFINED')
    assert typ.GlobalId not in {r['item_id'] for r in build(f)['rows']}
    did = document(tmp_path, f)
    assert solve('How many stairs?', did, root=tmp_path)['answer']['value'] == 1


@pytest.mark.parametrize('name', ['Staircase', 'Treppe', 'Porras', 'Trappa'])
def test_clear_proxies_are_separate(name, tmp_path):
    f = model()
    entity(f, 'IfcStair', 'Native')
    proxy = entity(f, 'IfcBuildingElementProxy', name)
    entity(f, 'IfcBuildingElementProxy', 'Stair railing')
    did = document(tmp_path, f)
    res = solve('How many stairs?', did, root=tmp_path)
    assert res['answer']['value'] == 1
    assert res['proxy_candidates'] == [{'item_id': proxy.GlobalId, 'kind': 'stairs'}]
    assert 'Separately' in res['answer']['text_md']
    assert res['answer']['confidence'] <= .6


@pytest.mark.parametrize('schema', ['IFC2X3', 'IFC4', 'IFC4X3'])
@pytest.mark.parametrize('length,area', [('m', 'm2'), ('mm', 'm2'), ('mm', 'mm2'), ('ft', 'ft2')])
def test_geometry_and_quantities_use_independent_si_units(schema, length, area):
    f = model(schema, length, area)
    scale = {'m': 1., 'mm': .001, 'ft': .3048}[length]
    area_scale = {'m2': 1., 'mm2': 1e-6, 'ft2': .3048**2}[area]
    points = [(x / scale, y / scale) for x, y in ((0, 0), (4, 0), (4, 3), (0, 3))]
    r = room(f, points, net=12 / area_scale)
    measured = space_area(r)
    assert measured['measured_m2'] == pytest.approx(12.)
    assert measured['stored_net_m2'] == pytest.approx(12.)
    assert measured['status'] == 'agree'


def test_explicit_area_unit_wins_over_project_area():
    f = model(area='ft2')
    metre2 = f.create_entity('IfcSIUnit', UnitType='AREAUNIT', Name='SQUARE_METRE')
    r = room(f, net=12, unit=metre2)
    assert stored_net_area(r)[0] == 12
    assert space_area(r)['status'] == 'agree'


@pytest.mark.parametrize('net,status', [(12., 'agree'), (12.24, 'agree'), (12.25, 'flag'), (0., 'flag')])
def test_two_percent_policy(net, status):
    f = model()
    assert space_area(room(f, net=net))['status'] == status


def test_nonrectangular_footprint_and_holes():
    f = model()
    l = room(f, ((0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)), net=6)
    assert space_area(l)['measured_m2'] == pytest.approx(6)
    ring = room(f, holes=[((1, 1), (2, 1), (2, 2), (1, 2))], net=11)
    assert space_area(ring)['measured_m2'] == pytest.approx(11)


def test_measured_area_beats_bad_quantity_and_reaches_trace(tmp_path):
    f = model()
    r = room(f, net=100)
    did = document(tmp_path, f)
    result = solve('What is the total area of the rooms (spaces)?', did, root=tmp_path)
    assert result['answer']['value'] == pytest.approx(12)
    assert any('-> flag' in t['detail'] for t in result['trace'])
    assert any(c['item_ids'] == [r.GlobalId] for c in result['citations'])
    assert result['reasoning']['steps'][-1]['ok'] is False
    assert result['reasoning']['confidence']['label'] == 'Cross-checked'
    assert 'over 2%' in result['answer']['text_md']


def test_missing_spaces_recovered_on_all_levels_and_sheet_scope(tmp_path):
    f = model()
    a, b = room(f, name='A'), room(f, name='B')
    ground = entity(f, 'IfcBuildingStorey', 'Ground', Elevation=0.)
    upper = entity(f, 'IfcBuildingStorey', 'Upper', Elevation=3.)
    aggregate(f, ground, a)
    aggregate(f, upper, b)
    did = document(tmp_path, f, omit=[b.GlobalId])
    assert solve('How many rooms (spaces) are there?', did, root=tmp_path)['answer']['value'] == 2
    assert solve('How many rooms on Upper?', did, root=tmp_path)['answer']['value'] == 1
    raw = load_doc(did, tmp_path)
    sheet = Doc('sheet', 'ifc', [], storeys=[{'name': 'Upper', 'elevation_m': 3}], meta={'sheet_of': did})
    checked = prepare_doc(sheet, tmp_path)
    assert [i.item_id for i in checked.items] == [b.GlobalId]
    assert len(raw.items) == 1  # no mutation of another request's loaded document


def test_no_spaces_means_model_coverage_not_whole_building(tmp_path):
    f = model()
    entity(f, 'IfcPipeSegment', 'Plumbing pipe')
    did = document(tmp_path, f)
    result = solve('How many rooms?', did, root=tmp_path)
    assert result['answer']['value'] == 0
    assert 'discipline model may omit rooms' in result['answer']['text_md']


def test_missing_geometry_falls_back_with_explicit_low_confidence(tmp_path):
    f = model()
    r = room(f, net=12)
    r.Representation = None
    did = document(tmp_path, f)
    res = solve('What is the area of the room?', did, root=tmp_path)
    assert res['answer']['value'] == 12
    assert res['answer']['confidence'] <= .6
    assert 'could not be cross-checked' in res['answer']['text_md']


def test_missing_length_units_never_promotes_geometry():
    f = model(length=None)
    check = space_area(room(f, net=12))
    assert check['measured_m2'] is None and check['status'] == 'unavailable'


def test_count_guard_retries_area_as_real_count(tmp_path):
    f = model()
    room(f, net=151.44)
    did = document(tmp_path, f)
    wrong = _answer_obj('How many rooms?', [did], '151.44 m²', 151.44, 'm²', 1., False,
                        [], [], {}, [], 'index', time.perf_counter())
    fixed = guard(wrong, 'How many rooms?', [did], tmp_path)
    assert fixed['answer']['value'] == 1 and fixed['answer']['unit'] == 'count'
    assert any(s['step'] == 'count_guard' for s in fixed['trace'])


def test_count_guard_cleans_components_from_old_quantity_route(tmp_path):
    f = model()
    a, b = entity(f, 'IfcWall', 'A'), entity(f, 'IfcWall', 'B')
    aggregate(f, a, b)
    did = document(tmp_path, f)
    wrong = _answer_obj('How many walls?', [did], '2 walls', 2, 'count', 1., False,
                        [], [{'n': 1, 'doc_id': did, 'page': 1, 'kind': 'element', 'item_ids': [a.GlobalId, b.GlobalId]}], {}, [], 'index', time.perf_counter())
    fixed = guard(wrong, 'How many walls?', [did], tmp_path)
    assert fixed['answer']['value'] == 1
    assert fixed['citations'][0]['item_ids'] == [a.GlobalId]


def test_fractional_count_is_never_rounded_to_an_instance(tmp_path):
    f = model()
    entity(f, 'IfcWall', 'A')
    did = document(tmp_path, f)
    wrong = _answer_obj('How many unknown gadgets?', [did], '1.25', 1.25, 'count', 1., False,
                        [], [], {}, [], 'index', time.perf_counter())
    fixed = guard(wrong, 'How many unknown gadgets?', [did], tmp_path)
    assert fixed['answer']['abstained'] and fixed['answer']['value'] is None


def test_measurement_count_is_not_rejected(tmp_path):
    f = model()
    did = document(tmp_path, f)
    res = _answer_obj('How many square metres?', [did], '12.5 m²', 12.5, 'm²', 1., False,
                      [], [], {}, [], 'index', time.perf_counter())
    assert guard(res, res['question'], [did], tmp_path)['answer']['value'] == 12.5


def test_actual_answer_room_count_and_area(monkeypatch, tmp_path):
    f = model()
    room(f, net=100)
    did = document(tmp_path, f)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    from engine.answer import answer
    assert answer('How many rooms (spaces) are in this model?', [did])['answer']['value'] == 1
    result = answer('What is the total area of the rooms (spaces)?', [did])
    assert result['answer']['value'] == pytest.approx(12)
    assert any('-> flag' in t['detail'] for t in result['trace'])


def test_named_room_analytics_keeps_cross_check(monkeypatch, tmp_path):
    f = model()
    r = room(f, net=100)
    r.LongName = 'Office'
    did = document(tmp_path, f)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    from engine.answer import answer
    result = answer('What is the area of the office?', [did])
    assert result['answer']['value'] == pytest.approx(12)
    assert any('-> flag' in t['detail'] for t in result['trace'])
    assert result['reasoning']['steps'][-1]['ok'] is False


def test_persisted_measurements_work_without_optional_ifc_parser(monkeypatch, tmp_path):
    f = model()
    r = room(f, net=100)
    did = document(tmp_path, f)
    from pipeline.ifc_accuracy import enrich_elements
    p = tmp_path / did / 'elements.json'
    raw = json.loads(p.read_text())
    enrich_elements(raw['elements'], build(f, geometry=True))
    p.write_text(json.dumps(raw))
    (tmp_path / did / 'source.ifc').unlink()
    assert solve('What is the area of the room?', did, root=tmp_path)['answer']['value'] == pytest.approx(12)
    result = solve('How many rooms?', did, root=tmp_path)
    assert result['answer']['value'] == 1 and result['answer']['confidence'] == 1


def test_typed_net_area_pset_units_and_untyped_real():
    f = model(length='mm')
    r = room(f)
    prop = f.create_entity('IfcPropertySingleValue', Name='NetFloorArea', NominalValue=f.create_entity('IfcAreaMeasure', 12.))
    ps = entity(f, 'IfcPropertySet', 'Pset_ExportedArea', HasProperties=[prop])
    entity(f, 'IfcRelDefinesByProperties', RelatedObjects=[r], RelatingPropertyDefinition=ps)
    assert stored_net_area(r)[0] == 12
    prop.NominalValue = f.create_entity('IfcReal', 12000000.)
    assert stored_net_area(r)[0] is None


def test_invalid_optional_sidecar_falls_through(tmp_path):
    f = model()
    room(f, net=12)
    did = document(tmp_path, f)
    (tmp_path / did / 'ifc-accuracy.json').write_text('{broken')
    result = solve('How many rooms?', did, root=tmp_path)
    assert result['answer']['value'] == 1
    assert result['answer']['confidence'] <= .6


def test_unknown_hierarchy_preserves_independent_flights(tmp_path):
    did = 'synthetic__legacy'
    d = tmp_path / did
    d.mkdir()
    (d / 'elements.json').write_text(json.dumps({'elements': [
        {'item_id': 'stair', 'kind': 'stairs', 'ifc_class': 'IfcStair'},
        {'item_id': 'flight', 'kind': 'stairs', 'ifc_class': 'IfcStairFlight'}]}))
    result = solve('How many stairs?', did, root=tmp_path)
    assert result['answer']['value'] == 2
    assert result['answer']['confidence'] <= .6
    assert any('hierarchy could not be verified' in s['detail'] for s in result['trace'])


def test_area_filter_counts_measured_rooms(monkeypatch, tmp_path):
    f = model()
    room(f, net=100)
    did = document(tmp_path, f)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    from engine.answer import answer
    result = answer('How many rooms are larger than 15 m2?', [did])
    assert result['answer']['value'] == 0 and result['answer']['unit'] == 'count'


def test_mep_rows_use_same_aggregate_count_rule(monkeypatch, tmp_path):
    f = model()
    a, b = entity(f, 'IfcPipeSegment', 'Parent pipe'), entity(f, 'IfcPipeSegment', 'Part')
    aggregate(f, a, b)
    did = document(tmp_path, f)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    from engine.ifc_accuracy import count_index
    idx = {'services': [{'item_id': a.GlobalId, 'length': 10}, {'item_id': b.GlobalId, 'length': 2}], 'structure': []}
    result = count_index(idx, load_doc(did, tmp_path))
    assert result['services'] == [{'item_id': a.GlobalId, 'length': 10}]
    assert len(idx['services']) == 2


def test_native_and_proxy_evidence_stay_distinct(tmp_path):
    f = model()
    a = entity(f, 'IfcStair', 'Native')
    b = entity(f, 'IfcBuildingElementProxy', 'Staircase')
    did = document(tmp_path, f)
    result = solve('How many stairs?', did, root=tmp_path)
    native = {g for c in result['citations'] if c.get('item_kind') != 'proxy' for g in c['item_ids']}
    proxy = {g for c in result['citations'] if c.get('item_kind') == 'proxy' for g in c['item_ids']}
    assert native == {a.GlobalId} and proxy == {b.GlobalId}


def test_rotated_footprint_uses_world_vertical():
    f = model()
    # Projection of this tilted 4 x 3 x 2 prism: width 4*cos(t)+2*sin(t), depth 3.
    angle = math.pi / 6
    r = room(f, tilt=angle)
    assert space_area(r)['measured_m2'] == pytest.approx((4*math.cos(angle)+2*math.sin(angle))*3)


def test_partial_room_total_is_explicit_and_not_verified(tmp_path):
    f = model()
    room(f, net=12, name='A')
    b = room(f, name='B')
    b.Representation = None
    did = document(tmp_path, f)
    result = solve('What is the total area of all rooms?', did, root=tmp_path)
    assert result['answer']['value'] == 12
    assert result['measurement_coverage'] == {'requested': 2, 'available': 1, 'missing': 1}
    assert result['answer']['confidence'] <= .6
    assert result['reasoning']['confidence']['label'] == 'Estimate'
    assert any('sum is partial' in s['detail'] for s in result['trace'])


def test_evidence_card_uses_the_measured_operands(tmp_path):
    f = model()
    room(f, net=100)
    did = document(tmp_path, f)
    result = solve('What is the area of the room?', did, root=tmp_path)
    text = next(s['text'] for s in result['reasoning']['steps'] if s['kind'] == 'measured')
    assert 'source geometry: 12 m²' in text
    assert 'Stored net areas' in text and '100 m²' in text


def test_missing_project_and_missing_global_id_are_honest():
    f = ifcopenshell.file()
    s = entity(f, 'IfcSpace', 'No units/project')
    assert space_area(s)['status'] == 'unavailable'
    s.GlobalId = None
    result = build(f)
    assert not result['rows'] and result['errors'][0]['reason'] == 'Missing GlobalId'
    assert not result['space_inventory_complete']


def test_cyclic_aggregate_is_preserved_as_uncertain(tmp_path):
    f = model()
    a, b = room(f, name='A'), room(f, name='B')
    aggregate(f, a, b)
    aggregate(f, b, a)
    idx = build(f)
    assert not idx['errors']
    assert all(r['count_status'] == 'cyclic aggregate hierarchy' and r['count_component_of'] is None for r in idx['rows'])
    did = document(tmp_path, f)
    result = solve('How many rooms?', did, root=tmp_path)
    assert result['answer']['value'] == 2 and result['answer']['confidence'] <= .6


def test_largest_room_ranks_measured_areas(monkeypatch, tmp_path):
    f = model()
    room(f, net=100, name='A')  # Actual 12 m².
    bigger = room(f, ((0, 0), (8, 0), (8, 3), (0, 3)), net=50, name='B')
    did = document(tmp_path, f)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    from engine.answer import answer
    result = answer('Which is the largest room?', [did])
    assert any(bigger.GlobalId in c['item_ids'] for c in result['citations'])
    assert '24' in result['answer']['text_md']
    assert any('-> flag' in t['detail'] for t in result['trace'])
    assert not any('None' in s['text'] for s in result['reasoning']['steps'])
