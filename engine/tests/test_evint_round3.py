"""Round 3 regressions. Small artificial inputs are generated for demo."""
import copy
import json
import math

import pytest

from engine import calc, scan_calc, scan_uncertainty
from engine.reasoning_parts import confidence
from engine.tests.test_scan_calc import fixture, response


def counted(root, *, recount=3):
    pm = fixture(root)
    pm['items'][1]['conf'] = .6
    (root / 'test/planmap-1.json').write_text(json.dumps(pm))
    r = response(2)
    r['answer'].update(confidence=.8, text_md='There are **2 doors**. Generated for demo.')
    r['citations'] = [{'doc_id': 'test', 'page': 1, 'item_ids': ['door-1', 'door-2']}]
    r['evidence'] = {'boxes': [{'item_id': f'door-{n}', 'page': 1, 'bbox_px': [n, 0, n + 1, 1]} for n in [1, 2]]}
    r['trace'] = [{'step': 'load', 'data': {'method': 'score_filter', 'kind': 'door', 'score_threshold': .5, 'before': 2, 'retained': 2, 'rejected': 0}},
                  {'step': 'recount', 'detail': f'plan map 2, drawing re-read {recount}: kept the boxed plan-map count'}]
    r['reasoning']['calc'] = calc.summed(r, [{'item_id': f'door-{n}', 'label': 'door', 'values': {'count': 1},
                                            'source': {'kind': 'element', 'doc_id': 'test', 'page': 1, 'artifact': 'planmap-1.json', 'item_id': f'door-{n}'}}
                                           for n in [1, 2]])
    return r


@pytest.mark.parametrize('alternate_kind,alternate_count', [('door', 100), ('wall', 100), ('door', 0)])
def test_rejected_alternate_failed_and_different_class_inventories_never_inflate_margin(tmp_path, alternate_kind, alternate_count):
    r = counted(tmp_path)
    pm = json.loads((tmp_path / 'test/planmap-1.json').read_text())
    pm['items'] = [{**pm['items'][0], 'item_id': f'alternate-{i}', 'kind': alternate_kind, 'source': 'seg'} for i in range(alternate_count)]
    (tmp_path / 'test/planmap-seg.json').write_text(json.dumps(pm))
    scan_calc.attach(r, 'How many doors?', tmp_path)
    m = r['reasoning']['margin']
    assert m['value'] == 1 and m['pct'] == 50
    assert all(c['label'] != 'Saved extraction count disagreement' for c in m['components'])
    assert not calc.validate(r['reasoning']['calc'], tmp_path)
    if alternate_count:
        assert m['excluded_components'][0]['artifact'] == 'planmap-seg.json'
        assert any(s['label'].startswith('Alternative saved extraction') for s in r['reasoning']['calc']['steps'])


def test_history_and_recount_use_max_with_explicit_outward_count_rounding(tmp_path, monkeypatch):
    r = counted(tmp_path)
    monkeypatch.setattr(scan_uncertainty, 'historical', lambda *a: {'n': 12, 'mae': 19 / 12, 'absolute_error_sum': 19,
                       'correct': 3, 'pct': 25, 'comparisons': [{'doc_id': f'history-{i}', 'predicted': 19 if i == 0 else 0, 'gold': 0} for i in range(12)],
                       'unit': 'count', 'source': 'generated-for-demo-history.json', 'scope': 'Generated for demo'})
    scan_calc.attach(r, 'How many doors?', tmp_path)
    m = r['reasoning']['margin']
    assert m['raw_value'] == 19 / 12 and m['value'] == 2 and m['pct'] == 100
    assert m['value'] != math.ceil(19 / 12 + 1)
    assert len(m['why']) < 180 and not m['is_error_bound']
    assert 'ceil' == next(s['operation'] for s in r['reasoning']['calc']['steps'] if s['id'] == 'scan-margin-total')
    assert not calc.validate(r['reasoning']['calc'], tmp_path)


def test_result_detection_scale_recount_margin_confidence_precede_detail(tmp_path):
    r = counted(tmp_path)
    scan_calc.attach(r, 'How many doors?', tmp_path)
    confidence.attach(r, 'How many doors?', tmp_path)
    c = r['reasoning']['calc']
    prominent = [s for s in c['steps'] if s.get('level') != 'detail']
    assert 1 <= len(prominent) <= 12
    assert prominent[0]['section'] == 'result'
    order = ['result', 'detections', 'scale', 'recount', 'margin', 'confidence']
    assert [order.index(s['section']) for s in prominent] == sorted(order.index(s['section']) for s in prominent)
    assert all(s.get('level') == 'detail' for s in c['steps'][len(prominent):])
    detection = next(s for s in prominent if s['id'] == 'scan-overview-class-door')
    assert 'score ≥ 0.5: 2 kept, 0 dropped' in detection['note']
    assert 'min 0.6, median 0.7' in detection['note']
    assert not calc.validate(c, tmp_path)
    before = copy.deepcopy(r)
    scan_calc.attach(r, 'How many doors?', tmp_path)
    confidence.attach(r, 'How many doors?', tmp_path)
    assert before == r


def test_presentation_order_preserves_missing_tampered_duplicate_and_cycle_checks():
    ref = {'kind': 'policy', 'text': 'Generated for demo'}
    a = calc.step('a', 'Input', 'recorded', 1, 'count', [calc.input_value('a', 1, 'count', ref)])
    b = calc.step('result', 'Result', 'copy input', 1, 'count', [calc.input_value('a', 1, 'count', calc.step_source('a'))])
    c = {'steps': [b, a], 'result': {'value': 1}}
    assert not calc.validate(c)
    c['steps'][0]['inputs'][0]['value'] = 2
    assert any('mismatched' in s for s in calc.validate(c))
    c['steps'][0]['inputs'][0]['value'] = 1
    c['steps'][1]['inputs'][0]['source'] = calc.step_source('result')
    assert any('cycle' in s for s in calc.validate(c))
    c['steps'][1]['inputs'][0]['source'] = calc.step_source('missing')
    assert any('missing' in s for s in calc.validate(c))
    c['steps'].append(copy.deepcopy(b))
    assert any('duplicate' in s for s in calc.validate(c))


def test_small_recount_difference_has_no_unmeasured_confidence_penalty(monkeypatch):
    r = response(11)
    r['answer']['confidence'] = .85
    r['trace'] = [{'step': 'recount', 'detail': 'plan map 11, drawing re-read 12: kept the boxed plan-map count'}]
    monkeypatch.setattr(scan_uncertainty, 'historical', lambda *a: {'pct': 25, 'correct': 3, 'n': 12, 'scope': 'Generated for demo historical cohort'})
    c = confidence.factors({'pct': None}, r, 'How many doors?', source='scan')
    assert c['pct'] == 25 and sum(f['delta'] for f in c['factors']) == 25
    assert not any(f['delta'] < 0 for f in c['factors'])
    assert any(f['label'] == 'Recount differed by 1 (11 vs 12)' for f in c['factors'])


def test_actual_class_extraction_threshold_and_kept_dropped_stats_are_prominent(tmp_path):
    r = counted(tmp_path)
    path = tmp_path / 'test/planmap-1.json'
    pm = json.loads(path.read_text())
    pm['provenance']['extraction'] = {'classes': {'door': {'score_threshold': .45, 'raw_count': 5, 'after_threshold': 3, 'dedupe_merged': 1}}}
    path.write_text(json.dumps(pm))
    scan_calc.attach(r, 'How many doors?', tmp_path)
    c = r['reasoning']['calc']
    door = next(s for s in c['steps'] if s['id'] == 'scan-overview-class-door')
    assert door['level'] == 'main'
    assert all(v in door['note'] for v in ['score threshold 0.45', 'raw count 5', 'after threshold 3', 'dedupe merged 1'])
    assert 'were not recorded' not in door['note']
    assert not calc.validate(c, tmp_path)
