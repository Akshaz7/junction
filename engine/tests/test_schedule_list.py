"""Door/window schedules read as tables; named pages are honoured; estimates never read 100%."""
from pathlib import Path

import pytest

from engine.reader.tables import Cell, Table
from engine.reasoning_parts.confidence import ESTIMATE_CAP, factors
from engine.schedules import Request, request_for, solve_list


class _Pt:
    doc_id, page = 'd', 8


def _table(rows, title='DOOR SCHEDULE'):
    cells = [Cell(r, c, 1, 1, t, [c * 10, r * 10, c * 10 + 9, r * 10 + 9])
             for r, row in enumerate(rows) for c, t in enumerate(row) if t != '']
    return Table('t', 8, [0, 0, 100, 100], len(rows), len(rows[0]), title, cells)


ROWS = [['TYPE', 'WIDTH', 'HEIGHT', 'QTY'],
        ['D-1', '72"', '80"', '4'], ['D-2', '36"', '80"', '16'], ['D-3', '36"', '80"', '5'],
        ['D-4', '144"', '80"', '1'], ['D-5', '72"', '80"', '1'], ['G-D', '108"', '96"', '1'], ['G-1', '192"', '96"', '1']]


def test_judge_question_becomes_a_list_request():
    q = 'On sheet A105 (page 8), read the door schedule. List each door type, width, height, quantity, and the grand total.'
    assert request_for(q) == Request('door', 'list')


def test_room_count_requests_are_unchanged():
    assert request_for('How many doors are listed for room 205 in the door schedule?').op == 'count'


def test_schedule_table_gives_each_type_and_the_grand_total():
    value, unit, text, spans = solve_list(_Pt, _table(ROWS), Request('door', 'list'))
    assert (value, unit) == (29, 'count')
    assert '| D-2 | 36" | 80" | 16 |' in text and '| G-1 | 192" | 96" | 1 |' in text
    assert '**29**' in text
    assert len(spans) == 1 + 7  # whole table plus one cited row per type


def test_unreadable_quantity_defers_instead_of_guessing():
    rows = [r[:] for r in ROWS]
    rows[2][3] = 'SEE NOTE'
    assert solve_list(_Pt, _table(rows), Request('door', 'list')) is None


def test_other_kind_of_schedule_is_not_used():
    assert solve_list(_Pt, _table(ROWS, title='FINISH SCHEDULE'), Request('window', 'list')) is None


def test_estimate_never_shows_100():
    card = {'label': 'Estimate', 'pct': 100, 'reason': 'x'}
    factors(card, {'answer': {'confidence': 1.0}}, 'How many doors?', allow_route_score=False)
    assert card['pct'] == ESTIMATE_CAP
    ok = {'label': 'Verified', 'pct': 100, 'reason': 'x'}
    factors(ok, {'answer': {'confidence': 1.0}}, 'How many doors?', allow_route_score=False)
    assert ok['pct'] == 100


def test_named_page_with_unprovable_sheet_still_reads_that_page():
    root = Path('artifacts')
    did = 'opening_design__aalseth-residence-transfer-20190321-to-lumber-yard-latest-plans-with-door-and-window-schedule-sheet-a600-3196-aalseth-lane-schedules'
    if not (root / did).exists():
        pytest.skip('artifact not local')
    from engine.schedules import answer_schedule
    r = answer_schedule('On sheet A105 (page 1), read the door schedule. List each door type, width, height, quantity and the total.', [did], root)
    assert r and r['answer']['value'] == 10 and 'Grand total' in r['answer']['text_md']


def test_window_schedule_with_header_above_the_grid():
    root = Path('artifacts')
    did = 'opening_design__aalseth-residence-transfer-20190321-to-lumber-yard-latest-plans-with-door-and-window-schedule-sheet-a600-3196-aalseth-lane-schedules'
    if not (root / did).exists():
        pytest.skip('artifact not local')
    from engine.schedules import answer_schedule
    r = answer_schedule('On page 1, read the window schedule. List each window type, width, height, quantity and the total.', [did], root)
    assert r and r['answer']['value'] == 39
    assert len(r['citations']) == 9 and all(c['bbox_px'] for c in r['citations'])
    assert len(r['evidence']['boxes']) == 9
