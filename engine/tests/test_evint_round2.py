"""Round 2: confidence arithmetic, measured margins and actual-method selection.

Synthetic fixtures are generated for demo. Real artifacts are never rewritten.
"""
import copy
import json
from pathlib import Path

import pytest

from engine import calc, scan_calc, scan_uncertainty
from engine.reasoning_parts import confidence
from engine.tests.test_scan_calc import fixture, response

ROOT = Path(__file__).resolve().parents[2] / 'artifacts'
DOCS = ['cubicasa5k__colorful-11397', 'cubicasa5k__colorful-10052', 'ext_cvcfp__iib-dd0601',
        'ext_resplan__plan-13503', 'swiss_dwellings__site1000-bldg2082-floor9385', 'ifc_bench__ac20-arc']
QUESTIONS = ['what is this', 'How many doors are there?', 'How many windows are there?', 'What is the total area of all rooms?']


@pytest.mark.parametrize('did', DOCS)
@pytest.mark.parametrize('question', QUESTIONS)
def test_real_answers_have_exact_factor_sum_and_method(did, question, monkeypatch):
    from engine.answer import answer
    for key, value in dict(MODELS_FAKE='1', READER='0', RECOUNT='0', EXPLAIN='0', ANSWER_TIMEOUT_S='0', ARTIFACTS_DIR=str(ROOT)).items():
        monkeypatch.setenv(key, value)
    if not (ROOT / did).is_dir():
        pytest.skip('Real artifact not installed')
    r = answer(question, [did])
    c = r['reasoning']['confidence']
    assert sum(f['delta'] for f in c['factors']) == c['pct']
    assert sum(bool(f.get('base')) for f in c['factors']) == 1
    assert c['label'] != 'Verified' or c['pct_kind'] != 'unavailable'
    trace = r['reasoning'].get('calc')
    if did.startswith(('cubicasa5k__', 'ext_')) and trace:
        method = trace['method']
        assert all(method.get(k) for k in ('id', 'label', 'why_chosen'))
        assert all(set(a) >= {'id', 'label', 'value', 'unit', 'rejected_because'} for a in method['alternatives'])
        assert calc.validate(trace, ROOT) == []
        if r['answer'].get('unit') == 'count':
            m_ = r['reasoning']['margin']
            assert isinstance(m_['value'], (int, float)) or m_.get('rule') == 'coverage_only_margin_unknown'
            assert r['reasoning']['margin'].get('is_error_bound') is False
    json.dumps(r, allow_nan=False)


def test_raw_model_score_is_explicitly_uncalibrated_not_an_accuracy_estimate():
    c = confidence.factors({'pct': None, 'label': 'Estimate'}, {'answer': {'confidence': .65}}, '')
    assert c['pct'] == 65 and c['pct_kind'] == 'recorded_engine_score'
    assert 'not measured' in c['factors'][0]['note']
    assert sum(f['delta'] for f in c['factors']) == c['pct']


def test_observed_calibration_and_actual_cap_are_separate_signed_factors():
    c = confidence.factors({'pct': 60, 'calibration': {'pct': 65, 'correct': 13, 'n': 20}}, {'answer': {'confidence': .99}}, '')
    assert [f['delta'] for f in c['factors']] == [65, -5]
    assert sum(f['delta'] for f in c['factors']) == c['pct'] == 60


def test_runtime_coverage_cap_keeps_original_score_and_signed_adjustment(tmp_path):
    r = {'answer': {'confidence': .9, 'unit': 'count', 'value': 2}, 'citations': [], 'evidence': {'boxes': []}}
    card = confidence.factors({'pct': None, 'label': 'Estimate'}, r, 'How many doors?')
    r['answer']['confidence'] = .69
    card['pct'] = None
    r['reasoning'] = {'confidence': card}
    confidence.attach(r, 'How many doors?', tmp_path)
    c = r['reasoning']['confidence']
    assert [f['delta'] for f in c['factors']] == [90, -21]
    assert c['pct'] == sum(f['delta'] for f in c['factors']) == 69


@pytest.mark.parametrize('question,docs', [('asdasdxxyyzzqq', []), ('How many windows?', [])])
def test_public_early_answers_are_finalized(question, docs, monkeypatch):
    from engine.answer import answer
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('READER', '0')
    r = answer(question, docs)
    c = r['reasoning']['confidence']
    assert sum(f['delta'] for f in c['factors']) == c['pct']


def test_missing_numeric_score_stays_unknown():
    c = confidence.factors({'pct': None}, {'answer': {}}, '')
    assert c['pct'] is None and c['pct_kind'] == 'unavailable'


def test_existing_route_card_and_abstention_get_factors_and_retain_labels(tmp_path):
    for label, abstained in [('Estimate', True), ('Cross-checked', False)]:
        r = {'answer': {'confidence': .5, 'abstained': abstained}, 'reasoning': {'confidence': {'label': label, 'pct': 40}}, 'citations': []}
        confidence.attach(r, '', tmp_path)
        assert r['reasoning']['confidence']['label'] == label
        assert sum(f['delta'] for f in r['reasoning']['confidence']['factors']) == 40


def test_real_history_matches_source_kind_scope_and_unit(monkeypatch, tmp_path):
    monkeypatch.setattr(scan_uncertainty, 'REPO', tmp_path)
    path = tmp_path / 'results/history.jsonl'; path.parent.mkdir()
    rows = [{'doc_id': 'source__one', 'source': 'source', 'type': 'count', 'question': 'How many doors are there on this floor plan?',
             'gold': 3, 'value': 5, 'unit': 'count', 'route': 'planmap'},
            {'doc_id': 'other__two', 'source': 'other', 'type': 'count', 'question': 'How many doors?', 'gold': 10, 'value': 100, 'unit': 'count', 'route': 'planmap'}]
    path.write_text('\n'.join(json.dumps(r) for r in rows))
    monkeypatch.setattr(scan_uncertainty, 'HISTORY', path)
    r = {'doc_ids': ['source__unseen'], 'answer': {'unit': 'count'}, 'route': 'planmap'}
    h = scan_uncertainty.historical(r, 'How many doors?')
    assert h['n'] == 1 and h['mae'] == 2
    assert scan_uncertainty.historical(r, 'How many windows?') is None
    r['answer']['unit'] = 'm2'
    assert scan_uncertainty.historical(r, 'What is the total area of all rooms?') is None


def test_disagreement_budget_replays_and_never_claims_a_bound(tmp_path):
    pm = fixture(tmp_path)
    alt = copy.deepcopy(pm); alt['items'] = [pm['items'][0]]
    (tmp_path / 'test' / 'planmap-seg.json').write_text(json.dumps(alt))
    r = response(2)
    r['trace'] = [{'step': 'recount', 'detail': 'plan map 2, drawing re-read 5: kept the plan map'}]
    r['evidence'] = {'boxes': [{'item_id': f'door-{n}', 'page': 1, 'bbox_px': [n, 0, n + 1, 1]} for n in [1, 2]]}
    r['reasoning']['calc'] = calc.summed(r, [{'item_id': f'door-{n}', 'label': 'door', 'values': {'count': 1},
                                            'source': {'kind': 'element', 'doc_id': 'test', 'page': 1, 'artifact': 'planmap-1.json', 'item_id': f'door-{n}'}}
                                           for n in [1, 2]])
    r = scan_calc.attach(r, 'How many doors?', tmp_path)
    budget = r['reasoning']['margin']
    assert budget['value'] == 3 and budget['pct'] == 150
    assert budget['is_error_bound'] is False and budget['complete'] is False
    assert 'not a guaranteed error bound' in budget['why']
    assert not calc.validate(r['reasoning']['calc'], tmp_path)
    before = copy.deepcopy(r)
    assert scan_calc.attach(r, 'How many doors?', tmp_path) == before


def test_zero_coverage_difference_is_explicitly_not_zero_detection_error(tmp_path):
    fixture(tmp_path)
    r = scan_calc.attach(response(0), 'How many doors?', tmp_path)
    m = r['reasoning']['margin']
    # Box coverage alone is never a margin: unknown, not ±0.
    assert m['value'] is None and m['pct'] is None and not m['is_error_bound']
    assert 'not an independent' in m['components'][0]['note'] and 'unknown' in m['why']


def test_scale_sensitivity_is_not_used_for_a_different_selected_scale(tmp_path):
    fixture(tmp_path)
    r = response(10); r['answer']['unit'] = 'm2'
    c = {'steps': [{'operation': 'door_scale_spread', 'value': 5}], 'method': {'scale': {'id': 'dimension'}}}
    scan_uncertainty.attach(r, 'Total room area?', c)
    assert 'margin' not in r['reasoning']
    c['method']['scale']['id'] = 'door-prior'
    scan_uncertainty.attach(r, 'Total room area?', c)
    assert r['reasoning']['margin']['value'] == pytest.approx(10 * (1.05 ** 2 - 1))
    assert not r['reasoning']['margin']['is_error_bound']


def test_reader_chooses_evidenced_dimension_over_planner_scale(tmp_path):
    from engine.reader.tools import Session
    pm = fixture(tmp_path)
    pm['items'].append({'item_id': 'dimension-1', 'kind': 'dimension', 'source': 'ocr', 'label': '2 m', 'bbox_px': [0, 0, 20, 2],
                        'props': {'printed_length': '2 m', 'dimension_line_px': [[0, 0], [20, 0]]}})
    (tmp_path / 'test' / 'planmap-1.json').write_text(json.dumps(pm))
    s = Session(['test'], tmp_path)
    text = s.run('measure', {'doc': 'd1', 'points': [[0, 0], [10, 0]], 'm_per_px': 999})
    assert 'length 1.000 m' in text
    assert s.calculations[0]['scale_origin'].startswith('ranked page scale:')
    assert not s.calculations[0]['supplied_scale']


@pytest.mark.parametrize('trace_step,method_id', [('forced', 'scan-vision-best-effort'), ('read', 'scan-vision-read')])
def test_model_description_is_not_labelled_as_a_deterministic_inventory(trace_step, method_id, tmp_path):
    fixture(tmp_path)
    r = response()
    r['answer']['confidence'] = .2
    r['trace'] = [{'step': trace_step, 'model': 'generated for demo', 'detail': 'model reading with page image and inventory'}]
    scan_calc.attach(r, 'What is this?', tmp_path)
    confidence.attach(r, 'What is this?', tmp_path)
    method = r['reasoning']['calc']['method']
    assert method['id'] == method_id
    assert 'background evidence' in method['why_chosen']
    assert any(f['label'] == 'Source: vision-model reading' for f in r['reasoning']['confidence']['factors'])
