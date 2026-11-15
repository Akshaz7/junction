"""ACC-VALUE regressions. All drawing fixtures are generated for demo."""
import json
import time

import pytest

from engine.numeric import count_question, guard_count, headline_value
from engine.solvers.data import Item
from engine.solvers.filters import room_filter
from engine.solvers.solve import solve


@pytest.fixture
def generated_plan(tmp_path, monkeypatch):
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    d = tmp_path / 'generated-for-demo'
    d.mkdir()
    (d / 'doc.json').write_text(json.dumps({'title': 'Generated for demo', 'kind': 'raster', 'pages': 1}))
    (d / 'planmap-1.json').write_text(json.dumps({
        'doc_id': d.name, 'page': 1, 'image': {'w': 100, 'h': 100},
        'scale': {'method': 'dimensions', 'm_per_px': 0.1, 'confidence': 1},
        'items': [
            {'item_id': 'door-a', 'kind': 'door', 'bbox_px': [0, 0, 2, 2], 'conf': 1, 'props': {}},
            {'item_id': 'door-b', 'kind': 'door', 'bbox_px': [5, 5, 7, 7], 'conf': 1, 'props': {}},
            {'item_id': 'room-a', 'kind': 'room', 'label': 'Office', 'bbox_px': [0, 0, 10, 10],
             'conf': 1, 'props': {'area_m2': 12.5}},
        ]}))
    return tmp_path, d.name


@pytest.mark.parametrize('noun', ['rooms (spaces)', 'spaces (rooms)', 'room (space)'])
def test_parenthetical_generic_synonyms_do_not_become_names(noun):
    rooms = [Item('a', 'room', name='Küche'), Item('b', 'room', name='Office')]
    assert room_filter(f'What is the total net floor area of all {noun} on level 1?', rooms) is None


def test_parenthetical_room_identifiers_keep_exact_label_path():
    assert room_filter("Area of 'Toilet (Rum nr. S11)'", [Item('a', 'room', name='Toilet')]) is None


@pytest.mark.parametrize('question,expected', [
    ('How many doors are there?', True),
    ('How many rooms larger than 20 m²?', True),
    ('How many square metres of tiles should I order?', False),
    ('How many m2 of flooring?', False),
    ('What is the area of the room?', False),
])
def test_object_count_and_measured_quantity_are_distinct(question, expected):
    assert count_question(question) is expected


def test_area_sent_to_count_question_is_recomputed_with_its_evidence(generated_plan):
    root, did = generated_plan
    wrong = solve('What is the total area of all rooms?', did, root=root)
    assert wrong['answer']['value'] == 12.5
    out = guard_count(wrong, 'How many doors are there?', [did], root)
    assert out['answer']['value'] == 2 and type(out['answer']['value']) is int
    assert out['answer']['unit'] == 'count' and not out['answer']['abstained']
    assert set(out['citations'][0]['item_ids']) == {'door-a', 'door-b'}


def test_fractional_count_is_never_rounded_into_an_object_count(generated_plan):
    root, did = generated_plan
    wrong = solve('How many doors are there?', did, root=root)
    wrong['answer']['value'] = 151.44
    assert guard_count(wrong, 'How many doors are there?', [did], root)['answer']['value'] == 2


def test_count_without_usable_data_abstains(generated_plan):
    root, did = generated_plan
    wrong = solve('What is the total area of all rooms?', did, root=root)
    out = guard_count(wrong, 'How many plumbing fixtures are there?', [did], root)
    assert out['answer']['abstained'] and out['answer']['value'] is None
    assert '12.5' not in out['answer']['text_md'] and not out['citations']


def test_zero_count_keeps_numeric_value_and_inventory_evidence(generated_plan):
    root, did = generated_plan
    out = solve('How many windows are there?', did, root=root)
    assert out['answer']['value'] == 0 and out['answer']['unit'] == 'count'
    assert not out['answer']['abstained'] and out['citations'][0]['inventory_check']
    assert guard_count(out, 'How many windows are there?', [did], root) is out


@pytest.mark.parametrize('text,computed,unit,want', [
    ('**No sauna (0).** [1]', [{'value': 0, 'unit': 'count'}], 'count', 0),
    ('**76.08 m²** [1]\n- 6 rooms', [{'value': 76.079, 'unit': 'm2'}], 'm²', 76.079),
    ('**1,234.50 m².**', [{'value': 1234.5, 'unit': 'm2'}], 'm²', 1234.5),
    ('**76.08 m² from 6 rooms.**', [{'value': 76.08, 'unit': 'm2'}], 'm²', None),
    ('**Area unavailable.**\nThe possible sum is 76.08.', [{'value': 76.08, 'unit': 'm2'}], 'm²', None),
    ('**76.08 m².**', [{'value': 76.08, 'unit': 'count'}], 'm²', None),
    ('**5 doors.**', [{'value': 6, 'unit': 'count'}], 'count', None),
    ('**151.44 fixtures.**', [{'value': 151.44, 'unit': 'count'}], 'count', None),
    ('**No sauna (0).**', [], 'count', None),
    ('**5 rooms.**', [{'value': True, 'unit': 'count'}], 'count', None),
])
def test_missing_value_requires_one_headline_number_and_typed_computation(text, computed, unit, want):
    assert headline_value(text, computed, unit) == want


def reader_result(root, did, tools, headline, question, value=None, unit=None, evidence=None):
    from engine.reader.agent import _build
    from engine.reader.tools import Session
    sess = Session([did], root)
    for tool, args in tools:
        sess.run(tool, args)
    refs = evidence if evidence is not None else [list(sess.ev)[-1]]
    out = _build(question, [did], sess, {'action': 'final', 'answer': headline, 'value': value,
                 'unit': unit, 'evidence': refs, 'confidence': 0.8}, [], [], time.perf_counter())
    return out, sess


def test_reader_retains_zero_from_cited_inventory(generated_plan):
    root, did = generated_plan
    out, sess = reader_result(root, did, [('planmap', {'kind': 'room', 'name': 'sauna'})],
                              '**No sauna (0).**', 'How many saunas are there?')
    assert out['answer']['value'] == 0 and out['answer']['unit'] == 'count'
    assert not out['answer']['abstained'] and out['citations']
    assert '0 matching room' in out['citations'][0]['quote']
    assert out['trace'][-1]['step'] == 'check'


def test_reader_restores_area_total_from_structured_tool_result(generated_plan):
    root, did = generated_plan
    out, sess = reader_result(root, did, [('planmap', {'kind': 'room'})],
                              '**The combined area is 12.50 m².**', 'What is the total area of all rooms?')
    assert out['answer']['value'] == 12.5 and out['answer']['unit'] == 'm²'
    assert out['citations'][0]['item_ids'] == ['room-a']


def test_reader_restores_computed_area_sum_with_source_citations(generated_plan):
    root, did = generated_plan
    out, sess = reader_result(root, did, [('planmap', {'kind': 'room'}), ('compute', {'expr': '12.5 + 12.5'})],
                              '**The combined area is 25.00 m².**', 'What is the combined floor area?')
    assert out['answer']['value'] == 25 and out['answer']['unit'] == 'm²'


def test_reader_normalizes_zero_in_supplied_object_units(generated_plan):
    root, did = generated_plan
    out, _ = reader_result(root, did, [('planmap', {'kind': 'room', 'name': 'sauna'})],
                           '**No sauna (0).**', 'How many saunas?', value=0, unit='saunas')
    assert out['answer']['value'] == 0 and out['answer']['unit'] == 'count'


@pytest.mark.parametrize('value,unit', [(151.44, 'count'), (12.5, 'm²'), (12, 'm²')])
def test_reader_rejects_area_or_fraction_as_object_count(generated_plan, value, unit):
    root, did = generated_plan
    out, _ = reader_result(root, did, [('planmap', {'kind': 'room'})],
                           f'**{value} fixtures.**', 'How many plumbing fixtures?', value=value, unit=unit)
    assert out['answer']['abstained'] and out['answer']['value'] is None
    assert str(value) not in out['answer']['text_md']


def test_reader_does_not_promote_unrelated_transcript_numbers(generated_plan):
    root, did = generated_plan
    out, sess = reader_result(root, did, [('planmap', {'kind': 'room'})],
                              '**There are 12.5 doors.**', 'How many doors?')
    assert out['answer']['value'] is None
    out, sess = reader_result(root, did, [('planmap', {'kind': 'room'})],
                              '**There are 1 saunas.**', 'How many saunas?')
    assert out['answer']['value'] is None


def test_reader_cannot_recover_arithmetic_area_as_integral_count(generated_plan):
    root, did = generated_plan
    out, _ = reader_result(root, did, [('planmap', {'kind': 'room'}), ('compute', {'expr': '12.5 * 2'})],
                           '**There are 25 doors.**', 'How many doors?')
    assert out['answer']['value'] is None


def test_reader_recovery_requires_citation_to_the_computation_source(generated_plan):
    root, did = generated_plan
    out, _ = reader_result(root, did, [('planmap', {'kind': 'room'})],
                           '**12.5 m².**', 'What is the total floor area?', evidence=['e99'])
    assert out['answer']['abstained'] and out['answer']['value'] is None


def apartment_doc(label='Whg. East-42', missing=False, ambiguous=False):
    from engine.solvers.data import Doc
    unit = Item('unit-a', 'other', label='', polygon_px=[[0, 0], [10, 0], [10, 10], [0, 10]], props={'role': 'unit'})
    rooms = [Item('a', 'room', label='Kitchen', bbox_px=[1, 1, 3, 3], q={'area_m2': 7.25}),
             Item('b', 'room', label='Bedroom', bbox_px=[4, 4, 6, 6], q={} if missing else {'area_m2': 8.5}),
             Item('outside', 'room', label='Terrasse', bbox_px=[6, 6, 8, 8], q={'area_m2': 20}),
             Item('other-page', 'room', page=2, bbox_px=[1, 1, 3, 3], q={'area_m2': 100}),
             Item('anchor', 'text', label=label, bbox_px=[1, 1, 2, 2])]
    units = [unit]
    if ambiguous:
        units.append(Item('unit-b', 'other', label='App. East-42', polygon_px=[[20, 0], [30, 0], [30, 10], [20, 10]], props={'role': 'unit'}))
    return Doc('generated-for-demo', 'planmap', units + rooms)


def solve_apartment(doc, question='What is the net floor area of apartment East-42?'):
    from engine.router.parser import parse
    from engine.solvers.solve import _apartments
    return _apartments(question, doc, parse(question), [], 'planmap', time.perf_counter())


@pytest.mark.parametrize('prefix', ['Whg.', 'App.', 'Apartment', 'Wohnung', 'Asunto', 'Lägenhet'])
def test_apartment_source_label_selects_unique_unlabelled_outline(prefix):
    out = solve_apartment(apartment_doc(label=prefix + ' East-42'))
    assert out['answer']['value'] == 15.75 and out['answer']['unit'] == 'm²'
    assert set(out['citations'][0]['item_ids']) == {'a', 'b'}
    assert not out['answer']['abstained'] and out['trace'][-1]['step'] == 'area'


def test_apartment_missing_room_area_does_not_become_partial_total():
    out = solve_apartment(apartment_doc(missing=True))
    assert out['answer']['abstained'] and out['answer']['value'] is None


def test_apartment_conflicting_labels_abstain_instead_of_picking_first():
    out = solve_apartment(apartment_doc(ambiguous=True))
    assert out['answer']['abstained'] and out['answer']['value'] is None


def test_apartment_missing_label_is_not_inferred_from_outline_order():
    out = solve_apartment(apartment_doc(label='Living'))
    assert out['answer']['abstained'] and out['answer']['value'] is None


@pytest.mark.parametrize('question,want,unit,ids', [
    ('Which door types are installed with quantities?', 2, 'count', {'d1', 'd2'}),
    ('Which room is the largest?', 20, 'm²', {'r1'}),
    ('What is the ceiling height of room 101?', 2.8, 'm', {'r1'}),
    ('What are the heights of each level?', 1, 'count', set()),
    ('What structural elements are present?', 1, 'count', {'b1'}),
])
def test_text_fact_routes_carry_their_computed_scalar(question, want, unit, ids):
    from engine.solvers.data import Doc
    from engine.textqa import text_answer
    doc = Doc('generated-for-demo', 'ifc', [
        Item('d1', 'door', name='Door A', type_name='Type A'),
        Item('d2', 'door', name='Door B', type_name='Type B'),
        Item('r1', 'room', name='101', props={'long_name': 'Office'}, q={'area_m2': 20, 'height_m': 2.8}),
        Item('b1', 'beam', name='Beam'),
    ], storeys=[{'name': 'Entry', 'elevation_m': 0}])
    out = text_answer(question, doc, use_model=False)
    assert out['answer']['value'] == want and out['answer']['unit'] == unit
    assert not out['answer']['abstained'] and out['citations']
    assert set(out['citations'][0]['item_ids']) == ids


def test_text_zero_furniture_count_keeps_zero_and_inventory_evidence():
    from engine.solvers.data import Doc
    from engine.textqa import text_answer
    doc = Doc('generated-for-demo', 'ifc', [
        Item('r', 'room', name='Office', bbox_m=[[0, 0, 0], [10, 3, 10]]),
        Item('f', 'furniture', bbox_m=[[20, 0, 20], [21, 1, 21]]),
    ])
    out = text_answer('What furniture is in the Office?', doc, use_model=False)
    assert out['answer']['value'] == 0 and out['answer']['unit'] == 'count'
    assert not out['answer']['abstained'] and out['citations'][0]['inventory_check']


def test_metadata_numbers_are_not_parsed_as_answer_values():
    from engine.solvers.data import Doc
    from engine.textqa import text_answer
    doc = Doc('generated-for-demo', 'ifc', [], meta={'schema': 'IFC4', 'applications': ['Example 2026']})
    out = text_answer('What authoring software and schema is used?', doc, use_model=False)
    assert out['answer']['value'] is None and out['answer']['unit'] is None


def test_last_resort_assembly_uses_matching_solver_value_and_citations(generated_plan):
    from engine.numeric import guard_answer_value
    root, did = generated_plan
    out = solve('What is the total area of all rooms?', did, root=root)
    out['answer'].update(value=None, unit=None, text_md='**The total area is 12.50 m².** [1]')
    restored = guard_answer_value(out, 'What is the total area of all rooms?', [did], root)
    assert restored['answer']['value'] == 12.5 and restored['answer']['unit'] == 'm²'
    assert restored['citations'][0]['item_ids'] == ['room-a']
    out['answer']['text_md'] = '**The total area is 99 m².**'
    assert guard_answer_value(out, 'What is the total area of all rooms?', [did], root)['answer']['value'] is None


def test_unsupported_numeric_headline_is_withheld_instead_of_left_as_a_claim(generated_plan):
    root, did = generated_plan
    out, _ = reader_result(root, did, [('planmap', {'kind': 'room'})],
                           '**There are 12.5 doors.**', 'How many doors?')
    assert out['answer']['abstained'] and '12.5' not in out['answer']['text_md']


def test_unknown_apartment_shapes_are_flagged_as_unverified():
    doc = apartment_doc()
    doc.items.append(Item('unknown', 'room', label='', bbox_px=[2, 2, 3, 3], q={'area_m2': 2}))
    out = solve_apartment(doc)
    assert out['answer']['value'] == 17.75 and out['answer']['confidence'] <= 0.5
    assert 'unverified' in out['answer']['text_md'] and 'unlabelled' in out['answer']['text_md']


@pytest.mark.parametrize('text', ['**12.5m²**', '**12,5 m²**'])
def test_no_partial_number_tokens_from_joined_units_or_decimal_commas(text):
    assert headline_value(text, [{'value': 12, 'unit': 'm2'}, {'value': 5, 'unit': 'm2'}], 'm2') is None


def test_public_answer_guards_route_and_attaches_schema_valid_evidence(generated_plan, monkeypatch):
    import importlib
    from pathlib import Path
    api = importlib.import_module('engine.answer')
    root, did = generated_plan
    wrong = solve('What is the total area of all rooms?', did, root=root)
    monkeypatch.setattr(api, '_guarded', lambda *args: wrong)
    out = api.answer('How many doors are there?', [did])
    assert out['answer']['value'] == 2 and out['answer']['unit'] == 'count'
    assert out['reasoning']['steps'] and out['reasoning']['confidence']
    schema = json.loads((Path(__file__).resolve().parents[2] / 'server/schemas/answer.schema.json').read_text())
    import jsonschema
    jsonschema.validate(out, schema)


def test_retry_preserves_scene_hidden_selection_without_exposing_internal_ids(generated_plan):
    root, did = generated_plan
    wrong = solve('What is the total area of all rooms?', did, root=root)
    out = guard_count(wrong, 'How many doors are there?', [did], root, hidden=['door-a'])
    assert out['answer']['value'] == 1 and out['citations'][0]['item_ids'] == ['door-b']
    assert 'door-a' not in out['answer']['text_md']


def test_arbitrary_compute_literals_cannot_restore_a_missing_measurement(generated_plan):
    root, did = generated_plan
    out, sess = reader_result(root, did, [('planmap', {'kind': 'room'}), ('compute', {'expr': '999'})],
                              '**999 m².**', 'What is the total floor area?')
    assert out['answer']['abstained'] and out['answer']['value'] is None
    assert not sess.numeric_results[-1]['grounded']


def test_reader_can_cite_every_source_item_instead_of_the_aggregate_ref(generated_plan):
    root, did = generated_plan
    out, _ = reader_result(root, did, [('planmap', {'kind': 'door'})],
                           '**There are 2 doors.**', 'How many doors?', evidence=['e1', 'e2'])
    assert out['answer']['value'] == 2 and out['answer']['unit'] == 'count'
    partial, _ = reader_result(root, did, [('planmap', {'kind': 'door'})],
                               '**There are 2 doors.**', 'How many doors?', evidence=['e1'])
    assert partial['answer']['value'] is None


@pytest.mark.parametrize('text', ['**Room 42.**', '**See A-42.**', '**Level 42.**'])
def test_single_identifier_is_not_an_unambiguous_numeric_headline(text):
    assert headline_value(text, [{'value': 42, 'unit': 'count'}], 'count') is None
