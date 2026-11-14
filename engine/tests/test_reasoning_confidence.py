import json

from engine.reasoning_parts import confidence


def _ctx(**kw):
    base = dict(res={}, question="", ans={}, cites=[], route="planmap", trace=[], unit="count", value=None, doc=None, items={}, cited=[],
                first_cite={}, models_used=False, is_ifc=False, sc=None, scale_w="an estimated scale", scale_c=0.5, from_cad=False,
                steps=[{"kind": "found"}], checked=None, area_q=None, rooms=[])
    base.update(kw)
    return base


def test_no_calibration_means_no_percent(tmp_path, monkeypatch):
    monkeypatch.setattr(confidence, 'CALIBRATION_PATH', tmp_path / 'absent.json')
    result = confidence.run(_ctx(is_ifc=True, quantified_exact=True))
    assert result['label'] == 'Verified' and result['pct'] is None
    assert 'No measured accuracy' in result['reason']


def test_exact_source_alone_does_not_verify_calculation():
    assert confidence.run(_ctx(is_ifc=True))['label'] == 'Estimate'
    assert confidence.run(_ctx(from_cad=True))['label'] == 'Estimate'


def test_scan_requires_actual_agreement_for_cross_checked():
    assert confidence.run(_ctx())['label'] == 'Estimate'
    assert confidence.run(_ctx(checked=True))['label'] == 'Cross-checked'
    assert confidence.run(_ctx(checked=False))['label'] == 'Estimate'


def test_scale_confidence_does_not_make_accuracy():
    result = confidence.run(_ctx(unit='m2', sc={'method': 'door-prior', 'confidence': 1}))
    assert result['label'] == 'Estimate' and result['pct'] is None
    assert 'dimension' in result['improve']


def test_calibration_uses_observed_counts_and_cites_sample(tmp_path, monkeypatch):
    path = tmp_path / 'calibration.json'
    path.write_text(json.dumps({'buckets': [{'source': 'scan', 'unit': 'count', 'checked': True, 'n': 20, 'correct': 13, 'accuracy': .99}]}))
    monkeypatch.setattr(confidence, 'CALIBRATION_PATH', path)
    result = confidence.run(_ctx(checked=True))
    assert result['pct'] == 65
    assert result['calibration']['n'] == 20
    assert '13 of 20' in result['reason'] and 'small sample' in result['reason']
    assert confidence.run(_ctx(unit='m2', checked=True))['pct'] is None
    assert confidence.run(_ctx(checked=False))['pct'] is None


def test_qa2_published_schema_matches_format_and_operation(tmp_path, monkeypatch):
    path = tmp_path / 'calibration.json'
    path.write_text(json.dumps({'by_format_and_question_type': [{'format': 'ifc', 'type': 'count', 'n': 2, 'correct': 1}]}))
    monkeypatch.setattr(confidence, 'CALIBRATION_PATH', path)
    assert confidence.run(_ctx(is_ifc=True, quantified_exact=True))['pct'] == 50
    assert confidence.run(_ctx(is_ifc=True, unit='m2'))['pct'] is None
    assert confidence.run(_ctx(route='vision', models_used=True))['pct'] is None


def test_invalid_calibration_fails_without_inventing_probability(tmp_path, monkeypatch):
    path = tmp_path / 'calibration.json'
    monkeypatch.setattr(confidence, 'CALIBRATION_PATH', path)
    for data in ('bad json', '{"buckets": [{"source": "scan", "n": 0, "correct": 0}]}', '{"buckets": [{"source": "scan", "n": 1, "correct": 2}]}'):
        path.write_text(data)
        assert confidence.run(_ctx())['pct'] is None
