import copy
import json

import pytest

from engine import scale_proof as sp
from engine import scale_text
from engine.reasoning import build


def word(text, x, y=10, w=30):
    return {'text': text, 'bbox_px': [x, y, x + w, y + 20]}


def page(scale=None):
    return {'doc_id': 'test', 'page': 1, 'image': {'w': 1000, 'h': 700},
            'scale': scale or {'method': 'door-prior', 'm_per_px': .01, 'confidence': .3},
            'items': [{'item_id': f'd{i}', 'kind': 'door', 'bbox_px': [10 + i * 150, 30, 10 + i * 150 + n, 60]}
                      for i, n in enumerate((80, 90, 100, 110))]}


def test_door_inputs_reproduce_median_and_explicitly_unknown_physical_width():
    pm = page(); original = copy.deepcopy(pm)
    sc = sp.enrich(pm)
    d = next(s for s in sc['proof']['steps'] if s['label'] == 'door prior')
    assert d['value'] == pytest.approx(.9 / 95)
    assert d['sample_count'] == 4 and d['median_width_px'] == 95
    assert not d['uncertainty_known'] and d['spread_pct'] > 0
    assert all(i['source']['doc_id'] == 'test' for i in d['inputs'])
    assert 'assumption' in d['inputs'][0]['source']
    assert sc['proof']['margin']['value'] is None
    assert pm == original and sc['m_per_px'] == .01


def test_crop_limit_and_stable_creation(tmp_path):
    from PIL import Image
    folder = tmp_path / 'test'; folder.mkdir()
    Image.new('RGB', (1000, 700), 'white').save(folder / 'page-1.png')
    pm = page(); (folder / 'planmap-1.json').write_text(json.dumps(pm))
    sc = sp.enrich(pm, folder, save_crops=True)
    inputs = sc['proof']['steps'][0]['inputs']
    cropped = [i['source']['crop'] for i in inputs if i['source'].get('crop')]
    assert len(cropped) == 3
    for name in cropped:
        with Image.open(tmp_path / name) as im:
            assert im.width <= 640 and im.height <= 320
    before = {p: p.stat().st_mtime_ns for p in (folder / 'evidence').glob('*.png')}
    sp.enrich(pm, folder, save_crops=True)
    assert before == {p: p.stat().st_mtime_ns for p in before}


def test_ratio_dpi_every_numeric_input_has_a_source(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    (folder / 'text-1.json').write_text(json.dumps({'dpi': 200, 'words': [word('1:125', 10)]}))
    sc = sp.enrich(page({'method': 'ratio-dpi', 'm_per_px': 125 * .0254 / 200}), folder)
    step = next(s for s in sc['proof']['steps'] if s['label'] == 'ratio dpi')
    assert step['value'] == pytest.approx(125 * .0254 / 200)
    assert {i['unit'] for i in step['inputs']} == {'ratio', 'px/in', 'm/in'}
    assert all(i['source'] for i in step['inputs'])
    assert sc['proof']['derivation_complete']


def test_no_unitless_scale_bar_or_unrelated_feet_unit():
    ws = [word(str(v), 100 + i * 100) for i, v in enumerate((0, 5, 10, 15))]
    assert scale_text.scalebar(ws) is None
    assert scale_text.scalebar(ws + [word("20'", 400, 500)]) is None


def test_two_scale_bar_labels_with_explicit_unit_and_feet_conversion():
    c = scale_text.scalebar([word('0', 100), word('5', 200), word('ft', 250)])
    assert c['m_per_px'] == pytest.approx(5 * .3048 / 100)
    assert c['derivation']['inputs'][-1]['value'] == .3048
    assert c['derivation']['inputs'][-2]['source']['endpoints_px'] == [[115, 20], [215, 20]]


def test_dimension_requires_label_line_link_and_explicit_units():
    pm = page()
    dim = {'item_id': 'dim', 'kind': 'dimension', 'label': '900', 'bbox_px': [0, 0, 50, 20],
           'props': {'dimension_line_px': [[0, 0], [90, 0]]}}
    pm['items'] = [dim]
    assert sp.dimensions(pm) == []
    dim['props']['dimension_unit'] = 'mm'
    c = sp.dimensions(pm)[0]
    assert c['m_per_px'] == pytest.approx(.01)
    del dim['props']['dimension_line_px']
    assert sp.dimensions(pm) == []


@pytest.mark.parametrize(('text', 'metres'), [('900 mm', .9), ('0,9 m', .9), ('3\' - 6"', 3.5 * .3048), ('12 in', .3048), ('90 cm', .9)])
def test_dimension_unit_conversion(text, metres):
    assert sp.printed_length(text) == pytest.approx(metres)


def test_unknown_scale_has_no_fabricated_derivation():
    proof = sp.enrich({'doc_id': 'odd', 'scale': {'method': 'dimension', 'm_per_px': .03}, 'items': []})['proof']
    assert not proof['derivation_complete'] and not proof['steps']
    assert 'unavailable' in proof['selection_rule']


def test_scaled_number_calc_reconciles_with_headline_and_keeps_all_rows(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    pm = page({'method': 'ratio-dpi', 'm_per_px': .01, 'confidence': .8})
    pm['items'] = [{'item_id': 'r', 'kind': 'room', 'label': 'Room', 'bbox_px': [0, 0, 100, 100],
                    'polygon_px': [[0, 0], [100, 0], [100, 100], [0, 100]], 'source': 'seg', 'conf': 1,
                    'props': {'area_px': 10000, 'area_m2': 1}}]
    (folder / 'planmap-1.json').write_text(json.dumps(pm))
    (folder / 'text-1.json').write_text(json.dumps({'dpi': 254, 'words': [word('1:100', 10)]}))
    res = {'doc_ids': ['test'], 'route': 'planmap', 'answer': {'value': 1, 'unit': 'm2', 'text_md': '**1.0 m²**'},
           'citations': [{'n': 1, 'doc_id': 'test', 'page': 1, 'item_ids': ['r']}], 'trace': []}
    reasoning = build(res, 'area of Room', tmp_path)
    calc = reasoning['calc']
    assert calc['result']['value'] == res['answer']['value']
    assert sum(r['values']['m2'] for r in calc['rows']) == calc['result']['value']
    assert any(s['label'] == 'ratio dpi' for s in calc['steps'])
    assert calc['margin'] == reasoning['margin']
    assert calc['margin']['method_spread'][0]['scale_pct'] == pytest.approx(0)
    json.dumps(reasoning, allow_nan=False)


def test_missing_source_sum_never_fabricates_arithmetic(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    pm = page(); pm['items'] = []
    (folder / 'planmap-1.json').write_text(json.dumps(pm))
    res = {'doc_ids': ['test'], 'route': 'planmap', 'answer': {'value': 42, 'unit': 'm2', 'text_md': '**42 m²**'},
           'citations': [], 'trace': []}
    calc = build(res, 'area', tmp_path)['calc']
    assert calc['result']['value'] == 42 and not calc['rows']
    assert any(s['id'] == 'unreconciled-source-terms' for s in calc['steps'])


def test_conflicting_detail_ratios_cannot_choose_arbitrary_first_ratio():
    ws = [word('1:100', 10), word('1:50', 300, 300)]
    assert scale_text.detect(ws, 1000, 700, dpi=200) is None
    candidates = scale_text.evidenced_candidates(ws, 1000, 700, dpi=200)
    assert len(candidates) == 2


def test_refinement_scales_only_items_on_that_page(tmp_path):
    from PIL import Image

    from engine.solvers.data import load_doc
    folder = tmp_path / 'uploads__scales'; folder.mkdir()
    for n, dpi in ((1, 254), (2, 127)):
        Image.new('RGB', (1000, 700), 'white').save(folder / f'page-{n}.png')
        pm = page(); pm['doc_id'] = folder.name; pm['page'] = n
        pm['items'] = [{'item_id': f'r{n}', 'kind': 'room', 'bbox_px': [0, 0, 100, 100],
                        'props': {'area_m2': 1}, 'source': 'seg', 'conf': 1}]
        (folder / f'planmap-{n}.json').write_text(json.dumps(pm))
        (folder / f'text-{n}.json').write_text(json.dumps({'dpi': dpi, 'source': 'pdf-text-layer', 'words': [word('1:100', 10)]}))
        # Avoid OCR: these are existing cached readings, not PDF ingestion.
        (folder / f'scale-ocr-{n}.json').write_text(json.dumps([word('1:100', 10)]))
    doc = load_doc(folder.name, tmp_path)
    assert [i.q['area_m2'] for i in doc.items] == [1, 4]
    assert doc.meta['page_scales'][1]['m_per_px'] == pytest.approx(.01)
    assert doc.meta['page_scales'][2]['m_per_px'] == pytest.approx(.02)


def test_method_spread_propagates_quadratically_as_sensitivity_only(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    pm = page({'method': 'dimension', 'm_per_px': .01})
    pm['items'] = [{'item_id': 'r', 'kind': 'room', 'props': {'area_m2': 100}, 'source': 'seg', 'conf': 1}]
    (folder / 'planmap-1.json').write_text(json.dumps(pm))
    (folder / 'text-1.json').write_text(json.dumps({'dpi': 254, 'words': [word('1:110', 10)]}))
    res = {'doc_ids': ['test'], 'route': 'planmap', 'answer': {'value': 100, 'unit': 'm2', 'text_md': '**100.0 m²**'},
           'citations': [{'n': 1, 'doc_id': 'test', 'item_ids': ['r']}], 'trace': []}
    r = build(res, 'area', tmp_path)
    assert r['margin']['value'] is None  # physical scale error still unknown
    sensitivity = r['margin']['method_spread'][0]
    assert sensitivity['scale_pct'] == pytest.approx(10)
    assert sensitivity['value'] == pytest.approx(21)
    assert 'not a physical error bound' in sensitivity['why']


def test_ratio_tokens_on_unrelated_lines_are_not_a_printed_scale():
    assert scale_text.detect([word('1', 10), word(':', 10, 200), word('100', 10, 400)], 1000, 700, dpi=200) is None


def test_routes_with_their_own_card_also_receive_calc(tmp_path):
    from engine.reasoning import attach
    res = {'doc_ids': [], 'answer': {'value': 12.3, 'unit': 'm2', 'text_md': '**12.3 m²**'},
           'reasoning': {'steps': [{'kind': 'read', 'text': 'A route-specific reading.'}]}, 'citations': [], 'trace': []}
    out = attach(res, 'area', tmp_path)
    assert out['reasoning']['steps'][0]['text'] == 'A route-specific reading.'
    assert out['reasoning']['calc']['result']['value'] == 12.3
    assert not out['reasoning']['calc']['rows']


def test_imperial_ratio_keeps_fractional_denominator_and_mixed_fraction():
    assert scale_text.imperial_ratio([word('5/16"=1\'-0"', 10)]) == pytest.approx(38.4)
    assert scale_text.imperial_ratio([word('1 1/2"=1\'-0"', 10)]) == pytest.approx(8)


def test_dimension_formula_carries_the_actual_conversion_factor():
    pm = page(); pm['items'] = [{'item_id': 'dim', 'kind': 'dimension', 'label': '900 mm', 'bbox_px': [0, 0, 90, 20],
                                'props': {'dimension_line_px': [[0, 0], [90, 0]]}}]
    c = sp.dimensions(pm)[0]
    assert [i['value'] for i in c['inputs']] == [900, .001, 90]
    assert c['inputs'][0]['value'] * c['inputs'][1]['value'] / c['inputs'][2]['value'] == pytest.approx(c['m_per_px'])


def test_uniform_resize_adjusts_resolution_and_records_the_factor(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    (folder / 'text-1.json').write_text(json.dumps({'dpi': 200, 'image': {'w': 500, 'h': 350}, 'words': [word('1:100', 10)]}))
    pm = page({'method': 'ratio-dpi', 'm_per_px': 100 * .0254 / 400})
    sc = sp.enrich(pm, folder)
    step = next(s for s in sc['proof']['steps'] if s['label'] == 'ratio dpi')
    assert step['value'] == pytest.approx(100 * .0254 / 400)
    assert step['inputs'][-1]['name'] == 'uniform image resizing' and step['inputs'][-1]['value'] == 2
    assert step['inputs'][0]['source']['bbox'] == [20, 20, 80, 60]


def test_unequal_resize_does_not_produce_one_fictitious_scale(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    (folder / 'text-1.json').write_text(json.dumps({'dpi': 200, 'image': {'w': 500, 'h': 700}, 'words': [word('1:100', 10)]}))
    sc = sp.enrich(page(), folder)
    assert not any(s['label'] == 'ratio dpi' for s in sc['proof']['steps'])
    assert 'unequal X/Y' in sc['proof']['selection_rule']


def test_display_rounding_explicitly_reconciles_source_rows(tmp_path):
    folder = tmp_path / 'test'; folder.mkdir()
    pm = page({'method': 'dimension', 'm_per_px': .01})
    pm['items'] = [{'item_id': 'r', 'kind': 'room', 'props': {'area_m2': 1.234}, 'source': 'seg', 'conf': 1}]
    (folder / 'planmap-1.json').write_text(json.dumps(pm))
    res = {'doc_ids': ['test'], 'route': 'planmap', 'answer': {'value': 1.23, 'unit': 'm2', 'text_md': '**1.23 m²**'},
           'citations': [{'n': 1, 'doc_id': 'test', 'item_ids': ['r']}], 'trace': []}
    calc = build(res, 'area', tmp_path)['calc']
    total = sum(r['values']['m2'] for r in calc['rows'])
    rounding = next(s for s in calc['steps'] if s['id'] == 'display-rounding')
    assert total + rounding['inputs'][1]['value'] == pytest.approx(calc['result']['value'])
