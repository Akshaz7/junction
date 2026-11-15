"""Generated fixtures for residual IFC routing and quantity semantics."""
import json
from pathlib import Path

import pytest

from engine.ifc_queries import answer, query_doc


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('EXPLAIN', '0')


def write_doc(root, did, rows, storeys=('Ground', 'Upper')):
    d = root / did
    d.mkdir()
    (d / 'elements.json').write_text(json.dumps({'elements': rows, 'storeys': [
        {'name': n, 'elevation_m': float(k * 3)} for k, n in enumerate(storeys)]}))
    return d


def element(iid, kind='room', storey='Ground', name='Electrical', **props):
    return {'item_id': iid, 'kind': kind, 'ifc_class': 'IfcSpace' if kind == 'room' else 'IfcDoor',
            'name': name, 'storey': {'name': storey}, 'props': props}


@pytest.mark.parametrize('name', ['Roof', 'Electrical', 'Plumbing', 'Floor', 'Upper', 'Ground'])
def test_scope_labels_do_not_filter_generic_room_counts(tmp_path, name):
    write_doc(tmp_path, 'generated', [element('a', name=name), element('b', name='Office')])
    result = answer(f"How many rooms (spaces) are there in the model '{name}'?", ['generated'], tmp_path)
    assert result['answer']['value'] == 2
    assert {i for c in result['citations'] for i in c['item_ids']} == {'a', 'b'}


def test_linked_sheet_whole_model_and_floor_scopes(tmp_path):
    write_doc(tmp_path, 'generated', [element('a'), element('b', storey='Upper')])
    sheet = tmp_path / 'generated-plan-01-ground'
    sheet.mkdir()
    (sheet / 'doc.json').write_text(json.dumps({'title': 'Generated for demo - Planta: Ground'}))
    did = sheet.name
    assert len(query_doc(did, tmp_path, "How many rooms in the model 'Building'?" ).items) == 2
    assert answer("How many rooms are shown on the floor plan of 'Ground'?", [did], tmp_path)['answer']['value'] == 1
    assert answer("How many rooms are there in the model 'Building'?", [did], tmp_path)['answer']['value'] == 2


def test_hidden_and_aggregate_components_excluded(tmp_path):
    write_doc(tmp_path, 'generated', [element('a', kind='door'), element('b', kind='door'),
                                    element('part', kind='door', count_component_of='a')])
    result = answer('How many doors are there?', ['generated'], tmp_path, hidden=['b'])
    assert result['answer']['value'] == 1
    assert result['citations'][0]['item_ids'] == ['a']


@pytest.mark.parametrize('question', ['How many rooms with windows?', 'How many external doors are there?',
                                     'How many rooms are larger than 20 m2?', 'How many doors of each type?',
                                     'How many rooms and doors are there?',
                                     'How many doors are there in the kitchen?',
                                     'How many rooms are there facing north?',
                                     'How many windows are there in total on the building and how many on the 2nd floor?'])
def test_filtered_and_compound_counts_keep_their_handlers(tmp_path, question):
    write_doc(tmp_path, 'generated', [element('a')])
    assert answer(question, ['generated'], tmp_path) is None


def test_unknown_explicit_floor_does_not_return_whole_model(tmp_path):
    write_doc(tmp_path, 'generated', [element('a')])
    result = answer("How many rooms are shown on the floor plan of 'Unknown'?", ['generated'], tmp_path)
    assert result['answer']['abstained']


def test_light_inventory_excludes_switches_and_hidden_items(monkeypatch, tmp_path):
    write_doc(tmp_path, 'generated', [element('lamp', kind='light'), element('switch', kind='light'),
                                    element('hidden', kind='light')])
    from engine import mep
    monkeypatch.setattr(mep, 'load_index', lambda doc: {'services': [
        {'id': 'lamp', 'k': 'light', 'c': 'IfcLightFixture'}, {'id': 'switch', 'k': 'switch', 'c': 'IfcFlowTerminal'},
        {'id': 'hidden', 'k': 'light', 'c': 'IfcLightFixture'}]})
    result = answer("How many light fixtures are there in the model 'Apartment Electrical'?",
                    ['generated'], tmp_path, hidden=['hidden'])
    assert result['answer']['value'] == 1
    assert result['citations'][0]['item_ids'] == ['lamp']


@pytest.mark.parametrize('noun,own_class,other_class,own_kind,other_kind', [
    ('light fixtures', 'IfcLightFixture', 'IfcSignal', 'light', 'light'),
    ('sanitary fixtures', 'IfcSanitaryTerminal', 'IfcWasteTerminal', 'toilet', 'drain'),
])
def test_typed_service_classes_do_not_include_neighbouring_families(monkeypatch, tmp_path, noun, own_class, other_class, own_kind, other_kind):
    rows = [element('fixture', kind='terminal'), element('other', kind='terminal')]
    rows[0]['ifc_class'], rows[1]['ifc_class'] = own_class, other_class
    write_doc(tmp_path, 'generated', rows)
    from engine import mep
    monkeypatch.setattr(mep, 'load_index', lambda doc: {'services': [
        {'id': 'fixture', 'k': own_kind, 'c': own_class}, {'id': 'other', 'k': other_kind, 'c': other_class}]})
    result = answer(f'How many {noun} are there?', ['generated'], tmp_path)
    assert result['answer']['value'] == 1
    assert result['citations'][0]['item_ids'] == ['fixture']


def test_full_answer_routes_linked_ifc_before_text_sheet(monkeypatch, tmp_path):
    write_doc(tmp_path, 'generated', [element('a'), element('b', storey='Upper')])
    did = 'generated-plan-01-ground'
    (tmp_path / did).mkdir()
    (tmp_path / did / 'doc.json').write_text(json.dumps({'title': 'Generated for demo: Ground'}))
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    from engine.answer import answer as ask
    result = ask("How many rooms (spaces) are there in the model 'Electrical Building'?", [did])
    assert result['answer']['value'] == 2
    assert result['answer']['unit'] == 'count'


def test_both_mep_and_quantity_row_ids_follow_aggregate_hierarchy(tmp_path):
    from engine.ifc_accuracy import count_rows
    from engine.solvers.data import load_doc
    write_doc(tmp_path, 'generated', [element('a'), element('part', count_component_of='a')])
    doc = load_doc('generated', tmp_path)
    assert count_rows([{'id': 'a'}, {'id': 'part'}], doc, tmp_path) == [{'id': 'a'}]
    assert count_rows([{'item_id': 'a'}, {'item_id': 'part'}], doc, tmp_path) == [{'item_id': 'a'}]


def test_explicit_net_floor_area_keeps_stored_operand_and_geometry_check(tmp_path):
    from engine.tests.test_acc_ifc import model, room, document
    f = model()
    room(f, net=10)
    did = document(tmp_path, f)
    result = answer('What is the total net floor area of all rooms (spaces)?', [did], tmp_path)
    assert result['answer']['value'] == 10
    assert result['_calc']['rows'][0]['source']['field'] == 'quantities.net_floor_area_m2'
    assert result['_calc']['rows'][0]['source']['artifact'] == 'elements.json'
    assert any('measured footprint 12' in t['detail'] and 'stored net area 10' in t['detail'] for t in result['trace'])


def test_explicit_net_side_area_does_not_substitute_other_wall_areas(tmp_path):
    row = element('wall', kind='wall')
    row['ifc_class'] = 'IfcWall'
    row['quantities'] = {'net_side_area_m2': 18, 'area_m2': 22, 'gross_side_area_m2': 25}
    write_doc(tmp_path, 'generated', [row])
    result = answer("What is the total net side area of all walls on 'Ground', in m²?", ['generated'], tmp_path)
    assert result['answer']['value'] == 18
    assert result['_calc']['rows'][0]['source']['field'] == 'quantities.net_side_area_m2'


def test_missing_net_quantity_is_unavailable_not_gross_area(tmp_path):
    row = element('wall', kind='wall')
    row['ifc_class'] = 'IfcWall'
    row['quantities'] = {'area_m2': 22, 'gross_side_area_m2': 25}
    write_doc(tmp_path, 'generated', [row])
    result = answer('What is the total net side area of all walls?', ['generated'], tmp_path)
    assert result['answer']['abstained']
    assert result['answer']['value'] is None


def test_missing_net_qto_uses_measured_space_boundary(tmp_path):
    from engine.tests.test_acc_ifc import model, room, document
    f = model()
    room(f)
    did = document(tmp_path, f)
    result = answer('What is the total net floor area of all rooms?', [did], tmp_path)
    assert result['answer']['value'] == 12
    ref = result['_calc']['rows'][0]['source']
    assert ref['kind'] == 'measurement' and ref['record']['measured_m2'] == 12
    from engine.calc import validate
    assert not validate(result['_calc'], tmp_path)


def test_named_room_net_operand_is_preserved_in_calculation(tmp_path):
    from engine.tests.test_acc_ifc import model, room, document
    f = model()
    r = room(f, net=10)
    r.LongName = 'Office'
    did = document(tmp_path, f)
    result = answer('What is the net floor area of the office?', [did], tmp_path)
    assert result['answer']['value'] == 10
    assert result['_calc']['rows'][0]['values']['area_m2'] == 10
    assert result['_calc']['rows'][0]['source']['field'] == 'quantities.net_floor_area_m2'
