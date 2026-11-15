import json
from pathlib import Path

import pytest

from engine.reasoning import build
from engine.reasoning_parts import margin
from engine.solvers.data import Doc, Item


def ctx(items, value=10, unit='m2', *, mode='ifc', scale=None, **extra):
    doc = Doc('test', mode, items, scale=scale)
    res = {'doc_ids': ['test']}
    base = dict(doc=doc, res=res, cites=[{'n': 1, 'doc_id': 'test', 'item_ids': [i.item_id for i in items]}],
                value=value, unit=unit, ans={'value': value, 'text_md': f'**{value:.1f} {unit}**' if isinstance(value, (int, float)) else ''}, steps=[], models_used=False)
    base.update(extra)
    return base


def room(area, iid='room', source='ifc'):
    return Item(iid, 'room', q={'area_m2': area}, source=source)


def test_exact_area_rounding_and_full_terms():
    c = ctx([room(3, 'a'), room(7, 'b')])
    out = margin.run(c)
    assert out['margin']['value'] == pytest.approx(.05)
    assert out['margin']['pct'] == pytest.approx(.5)
    assert out['based_on']['estimated'] == 0
    assert [t['value'] for t in out['arithmetic'][0]['terms']] == [3, 7]
    assert '3 + 7 = 10' in c['steps'][0]['text']
    assert c['quantified_exact']


def test_counts_zero_rounding_and_numeric_zero():
    out = margin.run(ctx([Item('d', 'door', source='ifc')], 1, 'count'))
    assert out['margin']['value'] == 0
    assert out['margin']['pct'] == 0
    out = margin.run(ctx([room(0)], 0))
    assert out['margin']['value'] is None  # zero room quantity is missing, as in solver


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 10 ** 1000])
def test_non_finite_source_values_have_an_explicit_unknown_margin(value):
    c = ctx([]); c['value'] = value
    out = margin.run(c)
    assert out['margin']['value'] is None
    json.dumps(out, allow_nan=False)


def test_six_term_preview_keeps_full_export():
    c = ctx([room(1, f'r{i}') for i in range(10)])
    out = margin.run(c)
    assert '+ 4 more' in c['steps'][0]['text']
    assert len(out['arithmetic'][0]['terms']) == 10


def test_wrong_citation_sum_is_not_a_rounding_only_margin():
    out = margin.run(ctx([room(3)], 10))
    assert out['margin']['value'] is None and 'arithmetic' not in out


def test_source_readings_disagree():
    out = margin.run(ctx([room(10)], checked=False))
    assert out['margin']['value'] is None and 'disagree' in out['margin']['why']


def test_bbox_has_no_exact_quantity():
    item = Item('r', 'room', bbox_m=[[0, 0, 0], [4, 2, 5]])
    out = margin.run(ctx([item], 20))
    assert out['margin']['value'] is None


@pytest.mark.parametrize(('unit', 'qty', 'power'), [('m', 'length_m', 1), ('m2', 'area_m2', 2), ('m3', 'volume_m3', 3)])
def test_scale_errors_propagate_with_dimension(unit, qty, power):
    item = Item('x', 'wall', q={qty: 100}, source='seg')
    out = margin.run(ctx([item], 100, unit, mode='planmap', scale={'method': 'scalebar', 'confidence': .8, 'relative_error': .03}))
    assert out['margin']['value'] == pytest.approx(100 * power * .03 + .05)
    assert 'not an error bound' in out['margin']['why']


def test_scale_bar_fit_residual():
    out = margin.run(ctx([room(100, source='seg')], 100, mode='planmap', scale={'method': 'scalebar', 'fit_residual_px': 2, 'scale_bar_px': 100}))
    assert out['margin']['value'] == pytest.approx(4.05)


def test_confidence_without_spread_is_unknown():
    out = margin.run(ctx([room(10, source='seg')], mode='planmap', scale={'method': 'printed-ratio', 'confidence': .99}))
    assert out['margin']['value'] is None


def test_door_spread_does_not_hide_unknown_physical_prior():
    items = [room(100, source='seg')]
    c = ctx(items, 100, mode='planmap', scale={'method': 'door-prior', 'confidence': .3})
    c['doc'].items += [Item('d1', 'door', bbox_px=[0, 0, 90, 50]), Item('d2', 'door', bbox_px=[0, 0, 110, 50])]
    out = margin.run(c)
    assert out['margin']['value'] is None
    assert '2 door widths' in out['margin']['why'] and 'sample spread' in out['margin']['why']


def test_measured_outline_arithmetic_includes_pixels_and_scale():
    item = room(100, source='seg')
    item.props['area_px'] = 10000
    c = ctx([item], 100, mode='planmap', scale={'method': 'scalebar', 'm_per_px': .1, 'relative_error': .01})
    out = margin.run(c)
    assert '10,000 px² × 0.1 m/px × 0.1 m/px = 100 m²' in c['steps'][0]['text']
    assert len(out['arithmetic'][0]['terms'][0]['measurement']['operands']) == 3


@pytest.mark.parametrize('has_page_scale', [True, False])
def test_later_page_never_borrows_first_pages_exact_cad_scale(tmp_path, has_page_scale):
    item = room(100, source='dxf'); item.page = 2
    c = ctx([item], 100, mode='planmap', root=tmp_path, scale={'method': 'dxf_units_fit', 'm_per_px': .1})
    c['doc'].pages = 2
    if has_page_scale:
        folder = tmp_path / 'test'; folder.mkdir()
        (folder / 'planmap-2.json').write_text(json.dumps({'scale': {'method': 'scalebar', 'relative_error': .02}}))
    out = margin.run(c)
    assert not c['quantified_exact']
    if has_page_scale:
        assert out['margin']['value'] == pytest.approx(4.05)
    else:
        assert out['margin']['value'] is None


def test_count_margin_never_uses_item_confidence_as_precision():
    item = Item('d', 'door', source='det', conf=.99)
    out = margin.run(ctx([item], 1, 'count', mode='planmap', checked=True))
    assert out['margin']['value'] is None


def test_detector_budget_matches_model_source_and_measured_cohort(tmp_path, monkeypatch):
    monkeypatch.setattr(margin, 'REPO', tmp_path)
    report = tmp_path / 'results/vision/evaluation.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'model': 'active', 'source': 'scan', 'per_kind': {'door': {
        'precision': .8, 'recall': .5, 'n': 100, 'recount_agrees': {'precision': .9, 'recall': .9, 'n': 40}}}}))
    doc = Doc('scan__test', 'planmap', [Item(f'd{i}', 'door', source='det') for i in range(10)])
    root = tmp_path / 'artifacts'
    p = root / doc.doc_id / 'planmap-1.json'
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'doc_id': doc.doc_id, 'provenance': {'models': {'det': 'active'}, 'detector_evaluation': 'results/vision/evaluation.json'}}))
    c = ctx([], 10, 'count', doc=doc, root=root, cites=[{'n': 1, 'doc_id': doc.doc_id, 'item_ids': [i.item_id for i in doc.items]}])
    out = margin.run(c)
    assert out['margin']['value'] == pytest.approx(10)  # 2 false positives + 8 missed
    assert out['margin']['sources'] == ['results/vision/evaluation.json']
    c['checked'] = True
    assert margin.run(c)['margin']['value'] == pytest.approx(2)
    data = json.loads(report.read_text()); data['model'] = 'other'; report.write_text(json.dumps(data))
    assert margin.run(c)['margin']['value'] is None


def test_documents_with_repeated_item_ids_remain_distinct(tmp_path):
    for did, value in [('a', 3), ('b', 7)]:
        folder = tmp_path / did
        folder.mkdir()
        (folder / 'elements.json').write_text(json.dumps({'elements': [{'item_id': 'same', 'kind': 'room', 'quantities': {'area_m2': value}}]}))
    response = {'answer': {'value': 10, 'unit': 'm2', 'text_md': '**10.0 m²**'}, 'doc_ids': ['a', 'b'],
                'citations': [{'n': i + 1, 'doc_id': did, 'item_ids': ['same']} for i, did in enumerate(('a', 'b'))], 'route': 'index'}
    out = build(response, 'total area', tmp_path)
    assert out['based_on']['elements'] == 2
    assert [t['value'] for t in out['arithmetic'][0]['terms']] == [3, 7]
    assert out['margin']['value'] == pytest.approx(.05)


def test_missing_item_is_counted_and_prevents_verification():
    c = ctx([room(10)])
    c['cites'][0]['item_ids'].append('missing')
    out = margin.run(c)
    assert out['based_on']['unresolved'] == 1 and out['margin']['value'] is None


def test_multi_kind_margins_are_separate():
    out = margin.run(ctx([Item('d', 'door'), Item('w', 'window')], {'door': 1, 'window': 1}, 'count', ans={'text_md': ''}))
    assert out['margin']['by_kind']['door']['value'] == 0
    assert out['margin']['by_kind']['window']['value'] == 0


@pytest.mark.parametrize(('value', 'text', 'expected'), [(12.34, '**12.3 m²**', .05), (1234.5, '**1,234.50 m²**', .005), (.00123, '**0.00123 m**', .000005), (343.27, 'The **43 rooms** have **343.3 m²**.', .05)])
def test_rounding_follows_visible_digits(value, text, expected):
    assert margin.rounding(value, text, 'm2') == pytest.approx(expected)


@pytest.mark.parametrize(('doc_id', 'question', 'exact'), [
    ('ifc_bench__fzk-house-arc', 'How many windows are there?', True),
    ('swiss_dwellings__site1000-bldg2082-floor9385', 'What is the total net floor area of all rooms?', True),
    ('cubicasa5k__colorful-11397', 'How many windows are there?', False),
    ('cubicasa5k__colorful-11397', 'What is the total area of all rooms?', False),
])
def test_real_artifact_budgets(doc_id, question, exact):
    from engine.solvers import solve
    root = Path(__file__).resolve().parents[2] / 'artifacts'
    if not (root / doc_id).exists():
        pytest.skip('Local real artifact not available')
    response = solve(question, doc_id, root=root)
    out = build(response, question, root)
    assert out is not None and out['based_on']['elements'] > 0
    assert out['arithmetic'][0]['result'] == response['answer']['value']
    assert len(out['arithmetic'][0]['terms']) == out['based_on']['elements']
    if exact:
        assert out['margin']['value'] is not None
        # Reproducing source arithmetic is distinct from independently checking
        # the quantity. These real indices may lack a complete second reading.
        if not out['calc']['checks']:
            # An exact count of the model's own elements is labelled as such; other exact quantities stay Estimate.
            expected = 'Verified (counted from the model)' if response['answer'].get('unit') == 'count' else 'Estimate'
            assert out['confidence']['label'] == expected
    else:
        assert out['margin']['value'] is None
        assert not out['confidence']['label'].startswith('Verified')
    json.dumps(out, allow_nan=False)
