import json

import pytest

from engine.calc import attach, evaluate, validate
from engine.order import answer_order
from engine.solvers.data import Doc, Item


def source(tmp_path, doc):
    d = tmp_path / doc.doc_id; d.mkdir()
    (d / 'elements.json').write_text(json.dumps({'units': 'm', 'elements': [
        {'item_id': i.item_id, 'kind': i.kind, 'quantities': i.q,
         'ifc_class': i.props.get('ifc_class'), 'quantity_source': i.props.get('quantity_source'),
         'storey': {'name': i.storey}} for i in doc.items]}))
    return tmp_path


def response(doc, value, unit='count'):
    return {'doc_ids': [doc.doc_id], 'question': 'question', 'answer': {'value': value, 'unit': unit, 'abstained': False},
            'citations': [{'doc_id': doc.doc_id, 'page': 1, 'item_ids': [i.item_id for i in doc.items]}],
            'trace': [{'step': 'scope', 'detail': 'level = Ground; external doors only'}]}


def test_ifc_types_and_actual_filters_not_inferred_from_question(tmp_path):
    doc = Doc('test', 'ifc', [Item('d', 'door', storey='Ground', props={'ifc_class': 'IfcDoor'}),
                              Item('s', 'stairs', props={'ifc_class': 'IfcStairFlight'})])
    root = source(tmp_path, doc)
    res = response(doc, 1); res['citations'][0]['item_ids'] = ['d']
    calc = attach(res, 'an unrelated question', root)['reasoning']['calc']
    scope = calc['scope']['sources'][0]
    assert scope['included_entity_types'] == ['IfcDoor'] and scope['uncited_entity_types'] == ['IfcStairFlight']
    assert calc['scope']['filters'][0]['detail'] == 'level = Ground; external doors only'
    assert calc['status'] == 'complete'


@pytest.mark.parametrize('origin', ['qto', 'geometry', None])
def test_quantity_source_is_preserved_and_never_invented(tmp_path, origin):
    doc = Doc('test', 'ifc', [Item('r', 'room', q={'net_floor_area_m2': 12.3},
                              props={'quantity_source': {'net_floor_area_m2': origin}})])
    res = attach(response(doc, 12.3, 'm2'), 'area', source(tmp_path, doc))
    method = res['reasoning']['calc']['rows'][0]['methods'][0]
    assert method['id'] == 'ifc-' + (origin or 'stored-quantity')
    assert method['field'] == 'quantities.net_floor_area_m2'


def test_skirting_records_perimeter_associated_doors_and_waste(tmp_path):
    doc = Doc('test', 'ifc', [Item('r', 'room', name='Bathroom', q={'perimeter_m': 14}, props={'door_ids': ['d']}),
                              Item('d', 'door', q={'width_m': .9})])
    res = answer_order('Order skirting for the bathrooms with 10% waste', doc)
    calc = attach(res, res['question'], source(tmp_path, doc))['reasoning']['calc']
    assert calc['status'] == 'complete', calc['issues']
    assert calc['result']['value'] == 14.41
    assert [r['values']['length_m'] for r in calc['rows']] == [13.1]
    assert any(s['expr'] == 'room perimeter − associated doorway widths' for s in calc['steps'])
    assert validate(calc, tmp_path) == []


def test_polygon_perimeter_and_shoelace_close_last_edge():
    pts = [0, 0, 4, 0, 4, 3, 0, 3]
    assert evaluate('polygon_perimeter', pts) == 14
    assert evaluate('shoelace', pts) == 12
    assert evaluate('polygon_perimeter', pts + [0]) is None


def test_text_answers_keep_source_trace_without_claiming_a_numeric_calculation(tmp_path):
    doc = Doc('test', 'ifc', [Item('d', 'door')])
    res = response(doc, None, None)
    calc = attach(res, 'what is the door material', source(tmp_path, doc))['reasoning']['calc']
    assert calc['status'] == 'source-only' and calc['result']['value'] is None
    assert calc['sources'][0]['item_ids'] == ['d']


def test_model_count_trace_is_owned_by_scan_worker(tmp_path):
    res = {'doc_ids': [], 'answer': {'value': None}, 'trace': [{'step': 'reader_final', 'detail': 'model answer'}]}
    assert 'reasoning' not in attach(res, '', tmp_path)


def test_runtime_scale_correction_retains_original_operands(tmp_path):
    from engine.solvers.solve import solve
    folder = tmp_path / 'test'; folder.mkdir()
    page = {'doc_id': 'test', 'page': 1, 'image': {'w': 1000, 'h': 700},
            'scale': {'method': 'door-prior', 'm_per_px': .02},
            'items': [{'item_id': 'dim', 'kind': 'dimension', 'label': '1 m', 'bbox_px': [0, 0, 50, 20],
                       'props': {'dimension_line_px': [[0, 0], [100, 0]]}},
                      {'item_id': 'room', 'kind': 'room', 'conf': 1, 'source': 'dxf',
                       'props': {'area_m2': 4}, 'bbox_px': [0, 0, 100, 100]}]}
    original = json.dumps(page)
    (folder / 'planmap-1.json').write_text(original)
    question = 'What is the total area of all rooms?'
    res = attach(solve(question, 'test', root=tmp_path), question, tmp_path)
    calc = res['reasoning']['calc']
    assert res['answer']['value'] == 1
    assert calc['status'] == 'complete', calc['issues']
    assert calc['method']['scales'][0]['id'] == 'dimension'
    assert any(s['expr'] == 'original quantity × correction factor²' and s['inputs'][0]['value'] == 4 for s in calc['steps'])
    assert calc['rows'][0]['source']['kind'] == 'step'
    assert (folder / 'planmap-1.json').read_text() == original
