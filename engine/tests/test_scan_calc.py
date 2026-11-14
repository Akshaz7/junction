"""Generated for demo: small geometry fixtures for evidence replay invariants."""
import copy
import json
import time

import pytest

from engine import calc, scan_calc
from engine.reader.agent import _build
from engine.reader.tools import Session


def fixture(root, *, scale=True, extraction=None):
    folder = root / 'test'; folder.mkdir()
    pm = {'doc_id': 'test', 'page': 1, 'image': {'w': 100, 'h': 80},
          'scale': {'m_per_px': .06 if scale else None, 'method': 'door-prior' if scale else 'none', 'confidence': .3},
          'items': [
              {'item_id': 'door-1', 'kind': 'door', 'source': 'det', 'conf': .8, 'bbox_px': [0, 0, 10, 2], 'props': {}},
              {'item_id': 'door-2', 'kind': 'door', 'source': 'det', 'conf': .4, 'bbox_px': [20, 0, 40, 2], 'props': {}},
              {'item_id': 'room-1', 'kind': 'room', 'source': 'det', 'conf': .9, 'bbox_px': [0, 5, 10, 15],
               'polygon_px': [[0, 5], [10, 5], [10, 15], [0, 15]], 'props': {}},
              {'item_id': 'wall-1', 'kind': 'wall', 'source': 'seg', 'conf': .95, 'bbox_px': [0, 20, 40, 22], 'props': {'length_px': 40}}],
          'provenance': {'models': {'det': 'generated for demo'}, 'params': {'det_min_px': 20, 'det_size': 1024}, 'extraction': extraction or {}}}
    (folder / 'planmap-1.json').write_text(json.dumps(pm))
    (folder / 'doc.json').write_text(json.dumps({'doc_id': 'test', 'kind': 'raster', 'title': 'generated for demo', 'pages': 1}))
    return pm


def response(value=None):
    return {'doc_ids': ['test'], 'answer': {'value': value, 'unit': 'count' if value is not None else None, 'text_md': 'Generated for demo', 'abstained': False},
            'citations': [], 'trace': [], 'reasoning': {'steps': [], 'confidence': {'label': 'Estimate', 'pct': None}}}


def test_description_has_replayable_class_scores_scale_and_geometry(tmp_path):
    fixture(tmp_path)
    r = scan_calc.attach(response(), 'What is this?', tmp_path)
    c = r['reasoning']['calc']
    assert c['status'] == 'complete' and not calc.validate(c, tmp_path)
    assert len(c['rows']) == 4 and c['result']['value'] is None
    assert {s['operation'] for s in c['steps']} >= {'sum', 'min', 'median', 'door_scale', 'door_scale_spread', 'polygon_area', 'polyline_closed', 'multiply'}
    assert next(s['value'] for s in c['steps'] if s['label'] == 'Room outline area') == 100
    assert any('not recorded' in n for n in c['unavailable'])
    assert any('No independent' in n for n in c['unavailable'])
    assert 'error' in c['scale_proof'][0]['margin']['why']


def test_context_does_not_change_selected_result_or_rows(tmp_path):
    fixture(tmp_path)
    r = response(1)
    ref = {'kind': 'element', 'doc_id': 'test', 'page': 1, 'artifact': 'planmap-1.json', 'item_id': 'door-1'}
    r['reasoning']['calc'] = calc.summed(r, [{'item_id': 'door-1', 'label': 'door', 'values': {'count': 1}, 'source': ref}])
    r['trace'] = [{'step': 'load', 'data': {'method': 'score_filter', 'kind': 'door', 'score_threshold': .5, 'before': 2, 'retained': 1, 'rejected': 1}}]
    scan_calc.attach(r, 'How many doors?', tmp_path)
    c = r['reasoning']['calc']
    assert c['result']['value'] == 1 and len(c['rows']) == 1 and len(c['inventory_rows']) == 4
    assert c['status'] == 'complete', c['issues']
    assert next(s['value'] for s in c['steps'] if s['label'].endswith(': rejected')) == 1


def test_missing_scale_does_not_invent_square_metres(tmp_path):
    fixture(tmp_path, scale=False)
    c = scan_calc.attach(response(), 'What is this?', tmp_path)['reasoning']['calc']
    assert c['status'] == 'complete' and any('No physical scale' in n for n in c['unavailable'])
    assert not any(s['unit'] in ('m2', 'm') for s in c['steps'])


def test_extraction_counts_are_recorded_only_when_available(tmp_path):
    fixture(tmp_path, extraction={'tiles': 4, 'raw_count': 9, 'dedupe_merged': 2, 'classes': {'door': {'score_threshold': .73, 'raw_count': 5, 'after_threshold': 4, 'dedupe_merged': 2}}})
    c = scan_calc.attach(response(), 'What is this?', tmp_path)['reasoning']['calc']
    assert next(s['value'] for s in c['steps'] if s['label'] == 'Detector door: score_threshold') == .73
    assert not any('dedupe_merged: not recorded' in n for n in c['unavailable'])
    assert not calc.validate(c, tmp_path)


def test_alternate_segmentation_is_not_added_to_selected_rows(tmp_path):
    pm = fixture(tmp_path)
    pm['items'] = [{**pm['items'][0], 'source': 'seg'}]
    (tmp_path / 'test' / 'planmap-seg.json').write_text(json.dumps(pm))
    c = scan_calc.attach(response(), 'What is this?', tmp_path)['reasoning']['calc']
    assert len(c['rows']) == 4 and len(c['inventory_rows']) == 5
    assert any(s['label'].startswith('Alternative saved extraction') for s in c['steps'])
    assert not calc.validate(c, tmp_path)


def test_attachment_is_idempotent(tmp_path):
    fixture(tmp_path)
    r = scan_calc.attach(response(), 'What is this?', tmp_path)
    before = copy.deepcopy(r)
    scan_calc.attach(r, 'What is this?', tmp_path)
    assert r == before


def test_observed_calibration_formula_never_uses_detector_scores(tmp_path):
    fixture(tmp_path)
    r = response()
    r['reasoning']['confidence']['calibration'] = {'n': 20, 'correct': 13, 'pct': 65, 'source': 'audit.json', 'scope': 'Observed accuracy'}
    c = scan_calc.attach(r, 'What is this?', tmp_path)['reasoning']['calc']
    s = next(s for s in c['steps'] if s['id'] == 'confidence-calibration')
    assert s['value'] == 65 and [i['value'] for i in s['inputs']] == [13, 20]
    assert not calc.validate(c, tmp_path)


def test_reader_measurement_retains_coordinates_and_arithmetic(tmp_path):
    fixture(tmp_path)
    sess = Session(['test'], tmp_path)
    obs = sess.run('measure', {'doc': 'd1', 'points': [[0, 0], [10, 0], [10, 10], [0, 10]], 'closed': True, 'm_per_px': .1})
    assert 'area 1.00 m2' in obs
    sess.run('compute', {'expr': '2 * (3 + 4)'})
    r = _build('Area?', ['test'], sess, {'answer': '**1 m²**', 'value': 1.0, 'unit': 'm2', 'confidence': .8, 'evidence': ['e1']}, [], [], time.perf_counter())
    calc.attach(r, 'Area?', tmp_path)
    scan_calc.attach(r, 'Area?', tmp_path)
    c = r['reasoning']['calc']
    assert c['status'] == 'complete', c['issues']
    assert c['result']['value'] == 1 and len(c['reader']['tool_calls']) == 2
    assert any(s['expr'] == '2 * (3 + 4)' for s in c['steps'])
    assert any('Planner' in i['source'].get('text', '') for s in c['steps'] for i in s['inputs'])
    before = copy.deepcopy(r)
    scan_calc.attach(r, 'Area?', tmp_path)
    assert before == r


@pytest.mark.parametrize('operation,values,want', [('ratio_dpi', [100, 200, .0254], .0127),
                                                ('ratio_sheet', [100, 420, .001, 2000], .021),
                                                ('dimension_scale', [900, .001, 30], .03),
                                                ('bar_scale', [0, 5, 10, 200, 1], .05),
                                                ('dxf_scale', [.001, -2], .0005)])
def test_scale_math_uses_explicit_conversion_inputs(operation, values, want):
    assert calc.evaluate(operation, values) == pytest.approx(want)


def test_malformed_optional_context_keeps_answer(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'test' / 'planmap-1.json').write_text('{"items": null}')
    r = response()
    assert scan_calc.attach(r, 'What is this?', tmp_path) is r


def test_reader_ratio_conversion_is_explicit_and_planner_input_labelled(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'test' / 'pages.json').write_text(json.dumps({'pages': [{'page': 1, 'dpi': 200}]}))
    sess = Session(['test'], tmp_path)
    sess.run('measure', {'doc': 'd1', 'points': [[0, 0], [100, 0]], 'ratio': 100})
    r = _build('Length?', ['test'], sess, {'answer': '**1.27 m**', 'value': 1.27, 'unit': 'm', 'confidence': .8, 'evidence': ['e1']}, [], [], time.perf_counter())
    calc.attach(r, 'Length?', tmp_path); scan_calc.attach(r, 'Length?', tmp_path)
    c = r['reasoning']['calc']
    assert c['status'] == 'complete', c['issues']
    s = next(s for s in c['steps'] if s.get('operation') == 'ratio_dpi')
    assert [i['value'] for i in s['inputs']] == [100, 200, .0254]
    assert 'planner-supplied' in s['inputs'][0]['name']
    assert c['reader']['evidence']['e1']['bbox_px'] == [0, 0, 100, 0]


def test_reader_view_retains_real_crop_and_model_image_dimensions(tmp_path, monkeypatch):
    from PIL import Image
    from types import SimpleNamespace
    import engine.models
    fixture(tmp_path)
    Image.new('RGB', (2000, 1000), 'white').save(tmp_path / 'test' / 'page-1.png')
    monkeypatch.setattr(engine.models, 'call', lambda *a, **kw: SimpleNamespace(text='Generated for demo visual observation', provider='fake', model='fake', cost_usd=0))
    sess = Session(['test'], tmp_path)
    sess.run('view', {'doc': 'd1', 'ask': 'What is this?'})
    entry = sess.calculations[0]
    assert (entry['crop_width_px'], entry['crop_height_px'], entry['model_width_px'], entry['model_height_px']) == (2000, 1000, 1600, 800)
    r = _build('What is this?', ['test'], sess, {'answer': 'Generated for demo description', 'confidence': .65, 'evidence': ['e1']}, [], [], time.perf_counter())
    scan_calc.attach(r, 'What is this?', tmp_path)
    c = r['reasoning']['calc']
    assert c['status'] == 'complete', c['issues']
    assert c['reader']['tool_calls'][0]['tool'] == 'view'
    assert r['reasoning']['confidence']['pct'] is None
    assert next(s['value'] for s in c['steps'] if s['id'] == 'reader-confidence') == .65


def test_recount_reports_original_independent_final_and_difference(tmp_path):
    fixture(tmp_path)
    r = response(2)
    r['trace'] = [{'step': 'recount', 'detail': 'plan map 2, drawing re-read 4: no boxes from vision, kept the plan map'}]
    r['evidence'] = {'boxes': [{'item_id': f'door-{n}', 'page': 1, 'bbox_px': [n, 0, n + 1, 1]} for n in [1, 2]]}
    c = scan_calc.attach(r, 'How many doors?', tmp_path)['reasoning']['calc']
    assert next(s['value'] for s in c['steps'] if s['id'] == 'scan-recount-difference') == 2
    assert next(s['value'] for s in c['steps'] if s['id'] == 'scan-recount-reported') == 2
    assert any('headline reports' in s.get('note', '') for s in c['steps'] if s['id'].startswith('scan-recount-'))


def test_withheld_area_keeps_source_rows_without_scalar_claim(tmp_path):
    from engine.solvers.data import load_doc
    fixture(tmp_path)
    doc = load_doc('test', tmp_path)
    r = response(.36); r['answer']['unit'] = 'm2'
    room = next(i for i in doc.items if i.kind == 'room')
    calc.record_items(r, doc, [(room, .36)], 'm2')
    r['answer']['value'] = None
    r['citations'] = [{'doc_id': 'test', 'page': 1, 'item_ids': ['room-1']}]
    r['trace'] = [{'step': 'sanity', 'detail': 'area withheld: scale not established'}]
    calc.attach(r, 'Area?', tmp_path)
    c = r['reasoning']['calc']
    assert c['result']['mode'] == 'per-element' and c['result']['value'] is None
    assert 'area withheld' in c['result']['reason']


def test_report_exports_include_missing_provenance(tmp_path):
    from engine.calc_export import to_markdown, to_html
    fixture(tmp_path)
    r = scan_calc.attach(response(), 'What is this?', tmp_path)
    assert 'dedupe_merged: not recorded' in to_markdown(r)
    assert 'dedupe_merged: not recorded' in to_html(r)


@pytest.mark.parametrize('args', [{'m_per_px': -1}, {'m_per_px': float('nan')}, {'ratio': 0}, {'points': [[0, 0], [float('inf'), 0]]}])
def test_invalid_reader_measurements_fail_plainly(args, tmp_path):
    fixture(tmp_path)
    sess = Session(['test'], tmp_path)
    obs = sess.run('measure', {'doc': 'd1', 'points': [[0, 0], [10, 0]], **args})
    assert obs.startswith('error:') and not sess.calculations
