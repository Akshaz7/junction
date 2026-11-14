import copy
import json

import pytest

from engine.calc import validate
from engine.scale_calc import steps
from engine.scale_policy import choose, select
from engine.scale_proof import candidate, operand
from engine.solvers.data import load_doc


def reading(method, value, **extra):
    return candidate(method, value, 'recorded candidate',
                     [operand('recorded reading', value, 'm/px', {'definition': 'test reading'})], **extra)


def pm(scale=None):
    return {'doc_id': 'different-origin', 'page': 1, 'image': {'w': 1000, 'h': 700}, 'items': [], 'scale': scale or {}}


def save(tmp_path, page):
    folder = tmp_path / page['doc_id']; folder.mkdir(exist_ok=True)
    (folder / f"planmap-{page['page']}.json").write_text(json.dumps(page))
    return folder


@pytest.mark.parametrize('native', ['ifc', 'dxf_units_fit', 'dxf_render', 'dxf-units'])
def test_native_units_outrank_pixel_inference_even_when_inference_agrees(native):
    winner, method = select([reading('ratio-dpi', .02), reading('scalebar', .02), reading(native, .01)])
    assert winner['method'] == native and method['disagreement']
    assert all(a['rejected_because'] for a in method['alternatives'])


def test_independent_agreement_breaks_equal_rank_tie():
    winner, method = select([reading('dimension', .02), reading('ratio-dpi', .01), reading('scalebar', .01005)])
    assert winner['method'] == 'ratio-dpi' and winner['support'] == 1
    assert method['disagreement']  # rejected dimension disagrees by >5%


def test_duplicates_of_same_printed_ratio_are_not_independent():
    winner, method = select([reading('ratio-dpi', .01), reading('ratio-dpi', .01), reading('ratio-sheet', .01)])
    assert winner['support'] == 0


def test_equally_ranked_conflicting_scales_need_region_scope():
    winner, method = select([reading('dimension', .01), reading('ratio-dpi', .02)])
    assert winner is None and method['id'] == 'ambiguous'


@pytest.mark.parametrize('value', [None, 0, -1, True, float('nan'), float('inf')])
def test_invalid_scales_never_win(value):
    assert select([reading('dimension', value)])[0] is None


def test_printed_dimensions_upgrade_stored_prior_and_keep_original_untouched(tmp_path):
    page = pm({'method': 'door-prior', 'm_per_px': .02})
    page['items'] = [{'item_id': 'dim', 'kind': 'dimension', 'label': '900 mm', 'bbox_px': [0, 0, 100, 20],
                      'props': {'dimension_line_px': [[0, 0], [90, 0]]}}]
    old = copy.deepcopy(page)
    sc = choose(page, save(tmp_path, page))
    assert sc['m_per_px'] == pytest.approx(.01) and sc['selection']['id'] == 'dimension'
    assert page == old
    ss = steps(sc, page['doc_id'], 1)
    c = {'steps': ss + [{'id': 'result', 'value': .01, 'operation': 'source', 'inputs': [
         {'name': 'selected', 'value': .01, 'source': {'kind': 'step', 'step_id': ss[1]['id']}}]}],
         'rows': [], 'result': {'value': .01}}
    assert validate(c, tmp_path) == []


def test_actual_known_object_width_needs_matched_endpoints(tmp_path):
    page = pm(); page['items'] = [{'item_id': 'object', 'kind': 'other', 'props': {'known_width_m': 2}}]
    assert choose(page)['selection']['id'] == 'unknown'
    page['items'][0]['props']['known_width_line_px'] = [[0, 0], [100, 0]]
    assert choose(page)['m_per_px'] == .02


def test_each_page_rescaled_at_its_own_scale_and_printed_areas_unchanged(tmp_path):
    for pg, metres in [(1, 1), (2, 2)]:
        page = pm({'method': 'door-prior', 'm_per_px': .02}); page['page'] = pg
        page['items'] = [{'item_id': 'dim', 'kind': 'dimension', 'label': f'{metres} m', 'bbox_px': [0, 0, 100, 20],
                          'props': {'dimension_line_px': [[0, 0], [100, 0]]}},
                         {'item_id': 'room', 'kind': 'room', 'source': 'dxf', 'conf': 1,
                          'props': {'area_m2': 4}},
                         {'item_id': 'printed', 'kind': 'room', 'source': 'dxf', 'conf': 1,
                          'props': {'area_m2_label': 3}}]
        save(tmp_path, page)
    doc = load_doc('different-origin', tmp_path)
    assert [i.q['area_m2'] for i in doc.items if i.item_id == 'room'] == [1, 4]
    assert [i.q['area_m2'] for i in doc.items if i.item_id == 'printed'] == [3, 3]
    assert doc.meta['page_scales'][1]['selection']['id'] == 'dimension'


def test_method_spread_never_becomes_physical_error_budget(tmp_path):
    page = pm({'method': 'dimension', 'm_per_px': .01})
    folder = save(tmp_path, page)
    (folder / 'text-1.json').write_text(json.dumps({'dpi': 254, 'words': [{'text': '1:110', 'bbox_px': [0, 0, 60, 20]}]}))
    sc = choose(page, folder)
    assert sc['method'] == 'ratio-dpi' and 'spread_pct' not in sc
    assert sc['method_spread_pct'] is not None


def test_recompute_dxf_units_and_signed_registration_without_assuming_metres():
    page = pm({'method': 'dxf_render', 'm_per_px': .02,
               'native_units': {'method': 'dxf-units', 'm_per_unit': .3048}})
    page['registration'] = {'a': -100}
    sc = choose(page)
    assert sc['m_per_px'] == pytest.approx(.3048 / 100)
    assert sc['selection']['disagreement']
    page['scale']['native_units']['m_per_unit'] = None
    assert not any(c['method'] == 'dxf-units' for c in choose(page)['candidates'])
