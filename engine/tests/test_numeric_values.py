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
