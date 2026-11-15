"""Generated-for-demo maps: incomplete detections cannot replace usable counts."""
import importlib
import json

import pytest

api = importlib.import_module('engine.answer')


@pytest.fixture
def plan(tmp_path, monkeypatch):
    did = 'generated-for-demo'
    folder = tmp_path / did
    folder.mkdir()
    (folder / 'doc.json').write_text(json.dumps({'title': 'Generated for demo plan', 'kind': 'png', 'pages': 1}))
    # The recount is stubbed; no model or image decoder reads these bytes.
    (folder / 'page-1.png').write_bytes(b'generated for demo')
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.delenv('MODELS_FAKE', raising=False)
    monkeypatch.setenv('RECOUNT', '1')
    monkeypatch.setenv('DET_BOXES', '0')
    reader_calls = []

    def reader(*args, **kwargs):
        reader_calls.append(args)
        return {'answer': {'value': 99, 'abstained': False}}

    monkeypatch.setattr(api, '_reader', reader)

    def write(items):
        (folder / 'planmap-1.json').write_text(json.dumps({'items': items}))

    return did, write, reader_calls


def room(n, confidence=.7, labelled=False):
    return {'item_id': f'room-{n}', 'kind': 'room', 'source': 'det', 'conf': confidence,
            'bbox_px': [10 * n, 10, 10 * n + 5, 20],
            'props': {'room_type': 'bedroom', **({'label_room_type': 'bedroom'} if labelled else {})}}


@pytest.mark.parametrize('count', [1, 3])
def test_missing_fixture_class_reaches_recount_before_reader(plan, monkeypatch, count):
    from engine import recount
    did, write, reader_calls = plan
    write([room(1)])  # Neither shower nor bath was detected.
    calls = []

    def re_read(question, image, kind):
        calls.append(kind)
        return count, 0., 'generated for demo'

    boxes = [[10 * n, 10, 10 * n + 5, 20] for n in range(count)]
    monkeypatch.setattr(recount, 'recount', re_read)
    monkeypatch.setattr(recount, 'detect', lambda *args: (boxes, 0., 'generated for demo'))
    result = api._answer_core('How many showers and bathtubs are there in total?', [did])
    assert calls == ['shower_bathtub']
    assert result['answer']['value'] == count
    assert len(result['evidence']['boxes']) == count
    assert result['evidence']['scene']['highlight_item_ids']
    assert 'did not detect that item type' not in result['answer']['text_md']
    assert not reader_calls


@pytest.mark.parametrize('labelled', [False, True])
def test_uncertain_room_candidate_does_not_replace_filtered_count(plan, labelled):
    did, write, reader_calls = plan
    write([room(1), *([room(2, .95, labelled=True)] if labelled else [])])
    result = api._answer_core('How many bedrooms are there?', [did])
    assert result['answer']['value'] == int(labelled)
    assert len(result['evidence']['boxes']) == int(labelled)
    assert 'additional possible room' in result['answer']['text_md']
    assert result['reasoning_hint']['pct_cap'] <= 70
    assert not reader_calls


def test_unavailable_recount_retains_qualified_detection_zero(plan, monkeypatch):
    from engine import recount
    did, write, reader_calls = plan
    write([room(1)])
    monkeypatch.setattr(recount, 'recount', lambda *args: (None, 0., ''))
    result = api._answer_core('How many toilet bowls are there?', [did])
    assert result['answer']['value'] == 0
    assert result['answer']['confidence'] <= .3
    assert 'not a verified total' in result['answer']['text_md']
    assert not reader_calls


def test_vector_empty_class_keeps_exact_count_semantics(plan):
    did, write, reader_calls = plan
    write([{**room(1), 'source': 'dxf'}])
    result = api._answer_core('How many toilet bowls are there?', [did])
    assert result['answer']['value'] == 0
    assert 'automatic detection count' not in result['answer']['text_md']
    assert not reader_calls
