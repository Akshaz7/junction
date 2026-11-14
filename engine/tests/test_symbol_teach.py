from engine.symbol_teach import room_for, summary, taught_answer


def symbol(doc='any-sheet', page=1, statuses=('confirmed', 'pending')):
    return dict(id='teaching', doc_id=doc, name='Supply air terminals', page=page,
                matches=[dict(id=str(i), bbox=[i*10, 0, i*10+8, 8], status=s) for i, s in enumerate(statuses)])


def test_rooms_require_polygons():
    assert room_for([2, 2, 4, 4], [dict(label='Nearby text', bbox_px=[0, 0, 20, 20])]) is None
    assert room_for([2, 2, 4, 4], [dict(label='Office', polygon_px=[[0,0],[10,0],[10,10],[0,10]])]) == 'Office'
    assert room_for([20, 20, 24, 24], [dict(label='Office', polygon_px=[[0,0],[10,0],[10,10],[0,10]])]) is None


def test_pending_candidates_are_estimates_with_boxes():
    a = taught_answer('How many supply air terminals?', ['any-sheet'], [symbol()])
    assert a['answer']['value'] == 2
    assert a['reasoning']['confidence']['label'] == 'Estimate'
    assert '1 confirmed by you; 1 auto-matched' in a['answer']['text_md']
    assert len(a['citations']) == len(a['evidence']['boxes']) == 2
    assert a['cost']['usd_total'] == 0
    import json
    from pathlib import Path
    from jsonschema import validate
    validate(a, json.loads(Path('server/schemas/answer.schema.json').read_text()))


def test_rejected_excluded_and_all_confirmed_cross_checked():
    s = symbol(statuses=('confirmed', 'rejected', 'confirmed'))
    a = taught_answer('Count supply air terminals', ['any-sheet'], [s])
    assert a['answer']['value'] == 2
    assert a['reasoning']['confidence']['label'] == 'Cross-checked'
    assert 'may have been missed' in a['answer']['text_md']
    assert summary(s['matches']) == dict(found=2, confirmed=2, pending=0, rejected=1, rooms={'Room unknown': 2})


def test_no_wrong_sheet_or_ambiguous_name_or_cross_doc_boxes():
    assert taught_answer('How many supply air terminals', ['other-sheet'], [symbol()]) is None
    assert taught_answer('How many extract fans', ['any-sheet'], [symbol()]) is None
    assert taught_answer('Locate supply air terminals', ['any-sheet'], [symbol()]) is None
    assert taught_answer('Count supply air terminals', ['any-sheet', 'second'], [symbol(), symbol('second')]) is None


def test_zero_matches_never_claim_verified():
    a = taught_answer('Count supply air terminals', ['any-sheet'], [symbol(statuses=())])
    assert a['answer']['value'] == 0
    assert a['reasoning']['confidence']['label'] == 'Estimate'
    assert not a['citations']


def test_evidence_uses_selected_sheet_not_first_attachment():
    a = taught_answer('Count supply air terminal', ['unrelated', 'any-sheet'], [symbol()])
    assert a['evidence']['scene']['doc_id'] == 'any-sheet'
