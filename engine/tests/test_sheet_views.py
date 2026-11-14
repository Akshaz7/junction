"""Mixed-view regressions. Fixtures are generated for demo, never real gold."""
import json

import pytest
from PIL import Image

from engine import scale_text
from engine.scales import scale_description
from pipeline.scale_regions import annotate_cached


def word(text, x=10, y=10, w=180, h=20):
    return {'text': text, 'bbox_px': [x, y, x+w, y+h]}


@pytest.mark.parametrize('text,ratio', [('1:48', 48), ('1:64', 64), ('1:200', 200), ('1:37.5', 37.5), ('3/16"=1\'-0"', 64)])
def test_printed_ratio_does_not_need_a_standard_scale(text, ratio):
    assert scale_text.ratio_and_sheet([word(text)])[0] == ratio
    assert scale_text.detect([word(text)], 1000, 800, dpi=254)['m_per_px'] == pytest.approx(ratio*.0001)


def test_separate_views_never_pick_first_sheet_scale():
    words = [word('Plan 1:100'), word('Section 1:20', 600, 500)]
    assert scale_text.ratio_and_sheet(words)[0] is None
    assert scale_text.detect(words, 1000, 800, dpi=254) is None


def test_unmeasured_printed_ratio_is_still_visible():
    assert 'printed 1:100' in scale_description({'ratio': 100, 'm_per_px': None})


def test_room_labels_do_not_suppress_scale_ocr(tmp_path, monkeypatch):
    pm = {'image': {'w': 1000, 'h': 800}, 'items': [], 'scale': {'m_per_px': None}}
    Image.new('RGB', (1000, 800), 'white').save(tmp_path/'page-1.png')
    (tmp_path/'text-1.json').write_text(json.dumps({'source': 'vlm', 'words': [word('Kitchen')]}))
    calls = []
    def ocr(path):
        calls.append(path)
        return [word('Plan 1:100', 20, 700)]
    monkeypatch.setattr('engine.reader.text.ocr_words', ocr)
    result = annotate_cached(pm, tmp_path, allow_ocr=True)
    assert result['regions'][0]['scale']['ratio'] == 100
    assert len(calls) == 1
    annotate_cached(pm, tmp_path, allow_ocr=True)
    assert len(calls) == 1

from pipeline.sheet_views import annotate_views, view_type
from engine.solvers.data import load_doc
from engine.solvers import solve


@pytest.mark.parametrize('title,kind', [('Ground floor plan', 'plan'), ('Pohjapiirros', 'plan'), ('Grundriss EG', 'plan'), ('Våningsplan', 'plan'), ('North elevation', 'elevation'), ('Julkisivu etelään', 'elevation'), ('Fasad', 'elevation'), ('Section A-A', 'section'), ('Leikkaus A-A', 'section'), ('Schnitt', 'section'), ('Site plan', 'site'), ('Plans and elevations', 'unknown')])
def test_multilingual_view_titles(title, kind):
    assert view_type(title) == kind


def mixed_map():
    items = []
    for kind in ['door', 'window', 'room']:
        for k, bbox in enumerate([[20, 20, 80, 80], [520, 20, 580, 80], [20, 420, 80, 480], [520, 420, 580, 480], [450, 50, 550, 100]], 1):
            if kind == 'window':
                bbox = [bbox[0]+80, bbox[1], bbox[2]+80, bbox[3]]
            items.append({'item_id': f'{kind}-{k:03}', 'kind': kind, 'bbox_px': bbox, 'props': {}, 'conf': .9, 'source': 'det'})
    return {'doc_id': 'generated__mixed', 'page': 1, 'image': {'w': 1000, 'h': 800}, 'scale': {'m_per_px': .02, 'method': 'door-prior', 'confidence': .3}, 'items': items}


def views():
    return [{'bbox': [0, 0, 490, 390], 'title': 'Pohjapiirros', 'view_type': 'plan', 'printed_scale': '1:100'},
            {'bbox': [500, 0, 1000, 390], 'title': 'Julkisivu', 'view_type': 'elevation', 'printed_scale': '1:200'},
            {'bbox': [0, 400, 490, 800], 'title': 'Upper plan', 'view_type': 'plan', 'printed_scale': '3/16"=1\'-0"'},
            {'bbox': [500, 400, 1000, 800], 'title': 'Leikkaus', 'view_type': 'section', 'printed_scale': '1:48'}]


def test_explicit_views_assign_scales_and_exclude_crossing_items():
    pm = annotate_views(mixed_map(), [], views=views(), dpi=254)
    assert [r['scale']['ratio'] for r in pm['regions']] == [100, 200, 64, 48]
    for kind in ['door', 'window', 'room']:
        its = [i for i in pm['items'] if i['kind'] == kind]
        assert [i['props']['excluded_from_plan_counts'] for i in its] == [False, True, False, True, True]
    assert mixed_map()['items'][0]['props'] == {}  # source map stays intact


def store(tmp_path, pm):
    d = tmp_path / pm['doc_id']
    d.mkdir()
    (d/'doc.json').write_text(json.dumps({'kind': 'raster'}))
    (d/'planmap-1.json').write_text(json.dumps(pm))
    return d


def test_plan_count_per_view_evidence_and_reasoning(tmp_path):
    from engine import reasoning
    from jsonschema import validate
    from pathlib import Path
    pm = annotate_views(mixed_map(), [], views=views())
    d = store(tmp_path, pm)
    result = solve('How many doors?', d.name, root=tmp_path)
    assert result['answer']['value'] == 2
    assert 'Pohjapiirros' in result['answer']['text_md'] and 'Upper plan' in result['answer']['text_md']
    assert 'Elevation' in result['answer']['text_md']
    assert len(result['citations']) == 2
    assert {b['item_id'] for b in result['evidence']['boxes']} == {'door-001', 'door-003'}
    card = reasoning.build(result, 'How many doors?', tmp_path)
    assert any(s['title'] == 'Plan views' for s in card['steps'])
    result['reasoning'] = card
    validate(result, json.loads(Path('server/schemas/answer.schema.json').read_text()))


def test_all_nonplan_views_abstain_instead_of_false_zero(tmp_path):
    vv = views()
    for v in vv:
        v['view_type'] = 'elevation'
    pm = annotate_views(mixed_map(), [], views=vv)
    d = store(tmp_path, pm)
    result = solve('How many windows?', d.name, root=tmp_path)
    assert result['answer']['abstained'] and result['answer']['value'] is None
    assert 'No floor-plan view' in result['answer']['text_md']


def test_titles_without_printed_scales_still_separate_views():
    from PIL import ImageDraw
    im = Image.new('L', (1000, 800), 'white')
    draw = ImageDraw.Draw(im)
    draw.rectangle([30, 40, 400, 600], outline='black', width=3)
    draw.rectangle([600, 40, 950, 600], outline='black', width=3)
    pm = annotate_views(mixed_map(), [word('Floor plan', 30, 650), word('Elevation', 600, 650)], im)
    assert len(pm['regions']) == 2
    assert {r['view_type'] for r in pm['regions']} == {'plan', 'elevation'}


def test_unresolved_boundaries_do_not_assign_nearest_title():
    pm = annotate_views(mixed_map(), [word('Floor plan', 30, 650), word('Elevation', 600, 650)])
    assert pm['regions'][0]['view_type'] == 'unknown'
    assert all(i['props']['excluded_from_plan_counts'] for i in pm['items'])


def test_overlapping_peer_views_do_not_supply_a_plan_count():
    vv = views()
    vv[1]['bbox'] = [30, 0, 1000, 390]
    pm = annotate_views(mixed_map(), [], views=vv)
    assert pm['items'][0]['props']['excluded_from_plan_counts']


def test_legacy_maps_have_unchanged_counts(tmp_path):
    d = store(tmp_path, mixed_map())
    assert solve('How many rooms?', d.name, root=tmp_path)['answer']['value'] == 5


def test_model_view_boxes_flow_into_planmap():
    from server.vlm_planmap import build
    pm = build('generated__model', 1, 1000, 800, {
        'items': [{'kind': 'door', 'box_2d': [20, 20, 100, 100]}, {'kind': 'door', 'box_2d': [20, 600, 100, 700]}],
        'dimensions': [], 'views': [
            {'title': 'Plan', 'view_type': 'plan', 'box_2d': [0, 0, 1000, 490], 'printed_scale': '1:100'},
            {'title': 'Elevation', 'view_type': 'elevation', 'box_2d': [0, 500, 1000, 1000], 'printed_scale': '1:200'}]}, 'fake', 0)
    assert len(pm['regions']) == 2
    assert [i['props']['excluded_from_plan_counts'] for i in pm['items']] == [False, True]


def test_public_answer_does_not_force_a_count_on_nonplan_sheet(tmp_path, monkeypatch):
    from engine import answer
    vv = views()
    for v in vv:
        v['view_type'] = 'elevation'
    d = store(tmp_path, annotate_views(mixed_map(), [], views=vv))
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('MODELS_FAKE', '1')
    result = answer.answer('How many windows?', [d.name])
    assert result['answer']['value'] is None
    assert 'No floor-plan view' in result['answer']['text_md']


def test_reader_planmap_lists_per_view_counts(tmp_path):
    from engine.reader.tools import Session
    d = store(tmp_path, annotate_views(mixed_map(), [], views=views()))
    result = Session([d.name], tmp_path).t_planmap('d1', kind='window')
    assert '2 item(s)' in result
    assert 'Pohjapiirros' in result and 'Upper plan' in result
    assert 'Elevations, sections' in result


@pytest.mark.parametrize('text,ratio', [('1:66 2/3', 200/3), ('Scale 1:100.', 100), ('1:37,5', 37.5)])
def test_fractional_metric_denominator_and_label_punctuation(text, ratio):
    from engine.scales import scale_anchors
    assert scale_anchors([word(text)])[0]['ratio'] == pytest.approx(ratio)


def test_view_scale_uses_only_its_local_dimensions():
    pm = mixed_map()
    pm['dimension_evidence'] = [
        {'bbox_px': [10, 100, 210, 120], 'meters': 2},
        {'bbox_px': [10, 200, 210, 220], 'meters': 2},
        {'bbox_px': [600, 100, 800, 120], 'meters': 20},
        {'bbox_px': [600, 200, 800, 220], 'meters': 20}]
    pm = annotate_views(pm, [], views=views())
    assert pm['regions'][0]['scale']['m_per_px'] == .01
    assert pm['regions'][1]['scale']['m_per_px'] == .1
    assert pm['regions'][2]['scale']['m_per_px'] is None


def test_scale_label_below_frame_uses_uniquely_nearest_view():
    vv = views()[:2]
    for v in vv:
        v['printed_scale'] = ''
    pm = annotate_views(mixed_map(), [word('1:100', 30, 400)], views=vv, dpi=254)
    assert pm['regions'][0]['scale']['ratio'] == 100
    assert 'ratio' not in pm['regions'][1]['scale']


def test_scale_label_between_views_is_not_assigned_arbitrarily():
    vv = views()[:2]
    vv[0]['bbox'] = [0, 0, 400, 390]
    vv[1]['bbox'] = [600, 0, 1000, 390]
    for v in vv:
        v['printed_scale'] = ''
    pm = annotate_views(mixed_map(), [word('1:100', 450, 300, w=100)], views=vv, dpi=254)
    assert all('ratio' not in r['scale'] for r in pm['regions'])


def test_tight_printed_labels_take_precedence_over_model_view_scale_guesses():
    from server.vlm_planmap import build
    raw = {'items': [], 'dimensions': [], 'views': [
        {'view_type': 'plan', 'box_2d': [0, 0, 1000, 490], 'printed_scale': '1:200'},
        {'view_type': 'elevation', 'box_2d': [0, 500, 1000, 1000], 'printed_scale': '1:100'}],
        'scale_labels': [{'text': '1:100', 'box_2d': [800, 100, 830, 200]},
                         {'text': '1:200', 'box_2d': [800, 600, 830, 700]}]}
    pm = build('generated__labels', 1, 1000, 800, raw, 'fake', 0)
    assert [r['scale']['ratio'] for r in pm['regions']] == [100, 200]
    assert pm['regions'][0]['scale']['boxes'] == [[100, 640, 200, 664]]


def test_nonplan_model_read_preserves_boundaries_for_later_count(tmp_path, monkeypatch):
    from server.vlm_planmap import read_page
    from types import SimpleNamespace
    image = tmp_path/'in.png'
    Image.new('RGB', (1000, 800), 'white').save(image)
    raw = {'is_plan': False, 'items': [], 'dimensions': [], 'views': [
        {'view_type': 'elevation', 'box_2d': [0, 0, 1000, 1000]}]}
    monkeypatch.setattr('engine.models.call', lambda *a, **kw: SimpleNamespace(json=raw, cost_usd=0, model='fake'))
    result = read_page('generated__elevation', 1, image, tmp_path)
    assert result['is_plan'] is False
    assert result['planmap']['regions'][0]['view_type'] == 'elevation'
    assert (tmp_path/'planmap-1.json').exists()


def test_model_text_with_some_scales_still_gets_real_ocr(tmp_path, monkeypatch):
    pm = {'image': {'w': 1000, 'h': 800}, 'items': [], 'scale': {'m_per_px': None}}
    Image.new('RGB', (1000, 800), 'white').save(tmp_path/'page-1.png')
    (tmp_path/'text-1.json').write_text(json.dumps({'source': 'vlm', 'words': [word('1:100')]}))
    calls = []
    monkeypatch.setattr('engine.reader.text.ocr_words', lambda p: calls.append(p) or [word('1:200', 700, 700)])
    result = annotate_cached(pm, tmp_path, allow_ocr=True)
    assert len(calls) == 1
    assert result['scale']['m_per_px'] is None


def test_multikind_counts_name_views_with_counts(tmp_path):
    d = store(tmp_path, annotate_views(mixed_map(), [], views=views()))
    result = solve('How many doors and windows?', d.name, root=tmp_path)
    assert result['answer']['value'] == {'door': 2, 'window': 2}
    assert 'Pohjapiirros (page 1): 1 door, 1 window' in result['answer']['text_md']


def test_comma_separated_scale_list_is_not_a_decimal_denominator():
    from engine.scales import scale_anchors
    assert {a['ratio'] for a in scale_anchors([word('1:100,1:20 1:500')])} == {100, 20, 500}


def test_scale_reader_exposes_unassigned_printed_labels(tmp_path):
    from engine.reader.tools import Session
    pm = annotate_views(mixed_map(), [], views=views())
    pm['printed_scale_labels'] = [word('1:100', 10, 780)]
    d = store(tmp_path, pm)
    result = Session([d.name], tmp_path).t_scale('d1')
    assert 'printed scale 1:100' in result and 'physical calibration' in result
