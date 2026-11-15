"""Generated for demo: explicit labels are names, never inferred room types."""
import importlib
import json

import pytest

from engine.solvers import solve
from engine.solvers.data import Item
from engine.solvers.filters import room_filter


@pytest.fixture
def drawing(tmp_path):
    folder = tmp_path / 'generated-for-demo'
    folder.mkdir()
    (folder / 'doc.json').write_text(json.dumps({'title': 'Wohnen', 'kind': 'dxf'}))
    rooms = []
    for n, label in enumerate(['Wohnen', 'Wohnen/Essen', 'Wohnen + Küche', 'Wohnung A', 'Whg. B', 'Zimmer'], 1):
        rooms.append({'item_id': f'room-{n}', 'kind': 'room', 'label': label,
                      'bbox_px': [n * 20, 0, n * 20 + 10, 10], 'source': 'dxf', 'conf': .95,
                      'props': {'room_type': 'living', 'area_m2': 12}})
    # An apartment envelope remains a unit even if an older cache calls it a room.
    rooms.append({'item_id': 'unit', 'kind': 'room', 'label': 'Wohnen',
                  'props': {'role': 'unit'}, 'source': 'dxf', 'conf': 1})
    # Source text inside a differently labelled room must not add that room.
    rooms[5]['polygon_px'] = [[0, 0], [100, 0], [100, 100], [0, 100]]
    rooms.append({'item_id': 'legend', 'kind': 'text', 'label': 'Wohnen', 'source': 'dxf',
                  'bbox_px': [20, 20, 30, 30], 'props': {'dxf_layer': 'LEGEND'}, 'conf': 1})
    (folder / 'planmap-1.json').write_text(json.dumps({'page': 1, 'items': rooms}))
    return tmp_path


@pytest.mark.parametrize('label', ["'Wohnen'", '"Wohnen"', '“Wohnen”', '‘Wohnen’', 'Wohnen'])
def test_exact_label_count_keeps_filter_even_when_title_matches(drawing, label):
    result = solve(f'How many rooms labelled {label} are there on this floor?',
                   'generated-for-demo', root=drawing)
    assert result['answer']['value'] == 1
    assert 'Wohnen' in result['answer']['text_md']
    assert result['evidence']['scene']['highlight_item_ids'] == ['room-1']
    assert {iid for c in result['citations'] for iid in c['item_ids']} == {'room-1'}
    assert result['cost']['usd_total'] == 0


def test_missing_label_never_substitutes_all_rooms(drawing):
    result = solve("How many rooms labelled 'Bad' are there on this floor?",
                   'generated-for-demo', root=drawing)
    assert result['answer']['value'] == 0
    assert not result['evidence']['scene']['highlight_item_ids']


@pytest.mark.parametrize('label', ['Wohnen/Essen', 'Wohnen + Küche'])
def test_complete_compound_label_can_be_requested(drawing, label):
    result = solve(f"How many rooms labelled '{label}' are there on this floor?",
                   'generated-for-demo', root=drawing)
    assert result['answer']['value'] == 1


@pytest.mark.parametrize('label', ['Office', 'Büro', 'Toimisto', 'Vardagsrum', 'Zimmer', 'Bad'])
def test_shared_room_filter_uses_source_name_not_type_or_substring(label):
    rooms = [Item('exact', 'room', props={'long_name': label}, name='101'),
             Item('compound', 'room', label=label + '/Other'),
             Item('type-only', 'room', label='Other', type_name=label, props={'room_type': label}),
             Item('unit', 'room', label=label, props={'role': 'unit'})]
    selected = room_filter(f"How many rooms labelled '{label}' are there?", rooms)
    assert selected is not None
    assert [r.item_id for r in selected[1]] == ['exact']


@pytest.mark.parametrize('quoted', ["'Cage d'escalier'", '"Cage d\'escalier"', '“Cage d\'escalier”', '‘Cage d’escalier’'])
def test_apostrophe_inside_quoted_label_is_not_a_delimiter(quoted):
    label = 'Cage d’escalier' if quoted.startswith('‘') else "Cage d'escalier"
    selected = room_filter(f'How many rooms labelled {quoted} are there on this floor?',
                           [Item('exact', 'room', label=label), Item('other', 'room', label='Cage d')])
    assert selected is not None
    assert [r.item_id for r in selected[1]] == ['exact']


def test_unit_tags_are_not_room_labels(drawing):
    for label in ['Wohnung A', 'Whg. B']:
        result = solve(f"How many rooms labelled '{label}' are there?", 'generated-for-demo', root=drawing)
        assert result['answer']['value'] == 0


def test_source_text_fallback_matches_whole_label_and_preserves_page_scope(drawing):
    folder = drawing / 'generated-for-demo'
    path = folder / 'planmap-1.json'
    pm = json.loads(path.read_text())
    for n, label in enumerate(['Wohnen', 'Wohnen', 'Wohnen/Essen', 'Wohnung A', 'Whg. B'], 1):
        pm['items'].append({'item_id': f'source-text-{n}', 'kind': 'text', 'source': 'dxf',
                            'label': label, 'conf': 1, 'bbox_px': [n * 20, 50, n * 20 + 10, 60],
                            'props': {'dxf_layer': 'ROOM_TEXT'}})
    path.write_text(json.dumps(pm))
    (folder / 'planmap-2.json').write_text(json.dumps({'page': 2, 'items': [
        {'item_id': 'second-floor', 'kind': 'text', 'source': 'dxf', 'label': 'Wohnen',
         'conf': 1, 'bbox_px': [0, 0, 10, 10], 'props': {'dxf_layer': 'ROOM_TEXT'}}]}))
    result = solve("How many rooms labelled 'Wohnen' are there?", 'generated-for-demo', root=drawing, page=1)
    assert result['answer']['value'] == 2
    assert result['evidence']['scene']['highlight_item_ids'] == ['source-text-1', 'source-text-2']
    hidden = solve("How many rooms labelled 'Wohnen' are there?", 'generated-for-demo', root=drawing,
                   page=1, hidden={'room-1': 'R1'})
    assert hidden['answer']['value'] == 0


def test_public_answer_keeps_exact_count_and_reasoning(drawing, monkeypatch):
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('ARTIFACTS_DIR', str(drawing))
    monkeypatch.setenv('MODELS_CACHE_DIR', str(drawing / 'cache'))
    monkeypatch.setenv('MODELS_COSTS_LOG', str(drawing / 'costs.jsonl'))
    module = importlib.import_module('engine.answer')
    result = module.answer("How many rooms labelled 'Wohnen' are there on this floor?", ['generated-for-demo'])
    assert result['answer']['value'] == 1
    assert 'Wohnen' in result['answer']['text_md']
    assert result.get('reasoning')
