"""E-41/E-48: generated for demo schedules only; never inspect held-out PDFs here."""
import json
from pathlib import Path

import pytest

from engine.reader.tables import Cell, Table
from engine.reader.text import PageText
from engine.schedules import Request, answer_schedule, request_for, solve_table

DOC = 'opening_design__generated-schedules-demo'


def table(headers, records, title='ROOM FINISH SCHEDULE'):
    cells = [Cell(r, c, 1, 1, text, [100 + c * 100, 130 + r * 35,
                                    200 + c * 100, 165 + r * 35])
             for r, row in enumerate([headers, *records]) for c, text in enumerate(row)]
    return Table('tbl1.1', 1, [100, 130, 100 + 100 * len(headers), 165 + 35 * len(records)],
                 1 + len(records), len(headers), title, cells)


def pt():
    return PageText(DOC, 1, 1000, 800, [], 'generated for demo')


HEAD = ['ROOM', 'NAME', 'AREA (SF)', 'N', 'E', 'S', 'W']
ROWS = [['302', 'Reading', '1,240 SF', 'W7', 'W7', 'W7', 'W7'],
        ['303', 'Office', '360 SF', 'W7', 'W7', 'W70', 'W7'],
        ['304', 'Lobby', '825 SF', 'W7', 'W7', 'W7', 'W7']]


@pytest.mark.parametrize('question', [
    'How many rooms have all four walls finished with W7 (paint)?',
    'In the finish room schedule, how many rooms have all 4 walls finished with W7?',
])
def test_all_four_walls_count_records_and_exact_codes(question):
    req = request_for(question)
    assert req == Request('room', 'walls', 'W7')
    result = solve_table(pt(), table(HEAD, ROWS), req)
    assert result[:2] == (2, 'count')
    assert len(result[3]) == 3  # full schedule + the two matching source records
    assert '303' in result[3][0].text  # excluded record remains checkable too


@pytest.mark.parametrize('bad', ['missing_wall', 'merged_wall', 'duplicate_room', 'missing_room', 'missing_direction'])
def test_incomplete_or_ambiguous_aggregate_defers(bad):
    t = table(HEAD, ROWS)
    if bad == 'missing_wall':
        t.cell_at(2, 5).text = ''
    elif bad == 'merged_wall':
        t.cell_at(2, 5).cs = 2
    elif bad == 'duplicate_room':
        t.cell_at(2, 0).text = '302'
    elif bad == 'missing_room':
        t.cell_at(2, 0).text = ''
    else:
        t.cell_at(0, 5).text = 'CEILING'
    assert solve_table(pt(), t, Request('room', 'walls', 'W7')) is None


def test_zero_cites_complete_table_and_unrelated_codes_do_not_count():
    t = table(HEAD, [ROWS[1]])
    result = solve_table(pt(), t, Request('room', 'walls', 'W7'))
    assert result[0] == 0 and len(result[3]) == 1


@pytest.mark.parametrize('kind', ['door', 'window'])
def test_room_marks_match_exact_boundary_and_one_record_once(kind):
    marks = ['302', '302A', '302.B', '302-C', '3020A', '1302A', '303A']
    t = table(['MARK', 'WIDTH'], [[m, '36'] for m in marks], f'{kind.upper()} SCHEDULE')
    req = request_for(f'How many {kind}s does the {kind} schedule list for room 302?')
    assert solve_table(pt(), t, req)[0] == 4
    assert solve_table(pt(), t, Request(kind, 'count', '999')) is None
    t.cells[-2].text = '302A'
    assert solve_table(pt(), t, req) is None


def test_explicit_room_wins_over_mark_prefix_and_quantities_are_checked():
    t = table(['DOOR MARK', 'ROOM', 'QTY'], [['D1', '302', '2'], ['302A', '303', '1'], ['D2', '302', '1']], 'DOOR SCHEDULE')
    req = Request('door', 'count', '302')
    assert solve_table(pt(), t, req)[0] == 3
    t.cell_at(3, 2).text = ''
    assert solve_table(pt(), t, req) is None
    t.cell_at(3, 2).text = '1'
    t.cell_at(2, 1).text = ''
    assert solve_table(pt(), t, req) is None


def test_room_area_keeps_printed_unit_and_largest_room():
    t = table(HEAD, ROWS)
    assert solve_table(pt(), t, Request('room', 'area', '302'))[:2] == (1240, 'ft²')
    top = solve_table(pt(), t, Request('room', 'largest'))
    assert top[0] is None and 'Room 302 Reading (1240 ft²)' in top[2]
    t.cell_at(2, 2).text = '1,240 SF'
    assert solve_table(pt(), t, Request('room', 'largest')) is None
    t.cell_at(1, 2).text = '1240 m²'
    assert solve_table(pt(), t, Request('room', 'area', '302')) is None


def test_multirow_merged_wall_header_and_number_column():
    t = table(HEAD, ROWS)
    for c in t.cells:
        c.r += 1
    t.cells += [Cell(0, 0, 1, 1, 'ROOM NUMBER', [100, 90, 200, 125]),
                Cell(0, 3, 1, 4, 'WALLS', [400, 90, 800, 125])]
    t.nrows += 1
    t.cell_at(1, 0).text = 'NUMBER'
    assert solve_table(pt(), t, Request('room', 'walls', 'W7'))[0] == 2


def make_pdf(path, headers=HEAD, records=ROWS, title='ROOM FINISH SCHEDULE', rotated_headers=()):
    """Tiny generated PDF with real vector grid and positioned Helvetica text."""
    commands = ['0.5 w']
    x, y, width, height = 100, 130, 100 * len(headers), 35 * (len(records) + 1)
    for col in range(len(headers) + 1):
        xx = x + col * 100
        commands.append(f'{xx} {800-y} m {xx} {800-y-height} l S')
    for row in range(len(records) + 2):
        yy = 800 - y - row * 35
        commands.append(f'{x} {yy} m {x+width} {yy} l S')

    def text(s, xx, yy, size=10, rotated=False):
        s = s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        position = f'0 1 -1 0 {xx} {800-yy} Tm' if rotated else f'{xx} {800-yy-size} Td'
        commands.append(f'BT /F1 {size} Tf {position} ({s}) Tj ET')

    text(title, 100, 95)
    for r, row in enumerate([headers, *records]):
        for c, value in enumerate(row):
            if r == 0 and c in rotated_headers:
                text(value, x + c * 100 + 30, y + 30, 5, rotated=True)
            else:
                text(value, x + c * 100 + 8, y + r * 35 + 10)
    text('W7 W7 W7 W7 - LEGEND ONLY', 100, 600)
    text('A909', 880, 735, 30)
    text('generated for demo', 100, 750)
    stream = '\n'.join(commands).encode()
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1000 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    content, offsets = b'%PDF-1.4\n', [0]
    for n, obj in enumerate(objs, 1):
        offsets.append(len(content))
        content += f'{n} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(content)
    content += b'xref\n0 6\n0000000000 65535 f \n'
    content += b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])
    content += f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    path.write_bytes(content)


def write_doc(root, records=ROWS):
    import pypdfium2 as pdfium
    d = root / DOC
    d.mkdir()
    make_pdf(d / 'generated.pdf', records=records)
    with pdfium.PdfDocument(d / 'generated.pdf') as pdf:
        pdf[0].render(scale=1).to_pil().save(d / 'page-1.png')
    (d / 'doc.json').write_text(json.dumps({'doc_id': DOC, 'kind': 'pdf', 'pages': 1,
                                         'title': 'generated for demo schedule'}))
    return d


def test_pdfminer_grid_lookup_runs_before_models_and_has_valid_evidence(tmp_path, monkeypatch):
    import engine.models
    from engine.answer import answer
    import jsonschema
    d = write_doc(tmp_path)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setattr(engine.models, 'call', lambda *a, **k: pytest.fail('schedule called model'))
    a = answer('On sheet A-909, how many rooms have all four walls finished with W7?', [DOC])
    assert a['answer']['value'] == 2 and a['route'] == 'index'
    assert a['answer']['confidence'] == .95
    assert a['trace'][0]['step'] == 'schedule_lookup' and a['cost']['usd_total'] == 0
    assert len(a['citations']) == len(a['evidence']['boxes']) == 3
    for citation, box in zip(a['citations'], a['evidence']['boxes']):
        assert citation['bbox_px'] == box['bbox_px']
        assert citation['doc_id'] == DOC and citation['page'] == 1 and citation['quote']
        assert 0 <= box['bbox_px'][0] < box['bbox_px'][2] <= 1000
        assert 0 <= box['bbox_px'][1] < box['bbox_px'][3] <= 800
    schema = Path(__file__).resolve().parents[2] / 'server/schemas/answer.schema.json'
    jsonschema.validate(a, json.loads(schema.read_text()))
    assert answer_schedule('On sheet A910, how many rooms have all four walls finished with W7?', [DOC], tmp_path) is None
    assert not list(d.glob('*text-*.json'))  # no artifact writes in the PDF fallback


@pytest.mark.parametrize('reader_answers', [False, True])
def test_bad_schedule_reaches_reader_without_forcing_missing_cells(tmp_path, monkeypatch, reader_answers):
    import engine.answer as mod
    import engine.forced
    from engine.answer import _abstained
    incomplete = [list(row) for row in ROWS]
    incomplete[1][5] = ''
    write_doc(tmp_path, records=incomplete)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('FORCE_ANSWER', '1')
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('TEXT_WITH_MODEL', '0')
    calls = []

    def reader(q, ids, root, trace, costs, t0, emit):
        calls.append('reader')
        out = _abstained(q, ids, 'Table needs visual interpretation.', trace, t0)
        if reader_answers:
            out['answer'].update(value=8, confidence=.5, abstained=False)
        return out

    def forced(q, ids, root, parsed, trace, costs):
        calls.append('forced')
        out = _abstained(q, ids, 'Model fallback result', trace, 1)
        out['answer'].update(value=8, confidence=.2, abstained=False)
        return out

    monkeypatch.setattr(mod, '_reader', reader)
    monkeypatch.setattr(engine.forced, 'forced_answer', forced)
    # This is a supported request on an incomplete table: code must defer,
    # then the reader checks the source. An unread cell is never a forced guess.
    a = mod.answer('How many rooms in the schedule have all four walls finished with W7?', [DOC])
    assert calls == ['reader']
    assert a['answer']['value'] == (8 if reader_answers else None)
    assert a['answer']['abstained'] is not reader_answers


def test_mirrored_room_numbers_are_verified_for_wall_and_area_routes():
    headers = ['ROOM NO.', 'ROOM NAME', 'SQ.FT.', 'NORTH WALL', 'EAST WALL', 'SOUTH WALL', 'WEST WALL', 'ROOM NO.']
    records = [[*r, r[0]] for r in ROWS]
    t = table(headers, records)
    assert solve_table(pt(), t, Request('room', 'walls', 'W7'))[0] == 2
    assert solve_table(pt(), t, Request('room', 'area', '302'))[:2] == (1240, 'ft²')
    assert 'Reading' in solve_table(pt(), t, Request('room', 'largest'))[2]
    t.cell_at(2, 7).text = '399'
    for request in (Request('room', 'walls', 'W7'), Request('room', 'area', '302'), Request('room', 'largest')):
        assert solve_table(pt(), t, request) is None


def test_scoped_area_does_not_require_unrelated_room_areas_but_largest_does():
    t = table(HEAD, ROWS)
    t.cell_at(2, 2).text = ''
    assert solve_table(pt(), t, Request('room', 'area', '302'))[:2] == (1240, 'ft²')
    assert solve_table(pt(), t, Request('room', 'largest')) is None
    assert solve_table(pt(), t, Request('room', 'area', '303')) is None


@pytest.mark.parametrize('unknown', ['?', 'W7?', 'SEE NOTE 3', 'W7/W70', 'DITTO', 'W7*'])
def test_unread_or_qualified_wall_cells_defer_instead_of_undercounting(unknown):
    t = table(HEAD, ROWS)
    t.cell_at(1, 3).text = unknown
    assert solve_table(pt(), t, Request('room', 'walls', 'W7')) is None


@pytest.mark.parametrize('area', ['1,24 SF', ',1240 SF', '1240, SF', '0 SF', '1240 m²', '1240 SF / 115 m²'])
def test_malformed_or_conflicting_area_values_defer(area):
    t = table(HEAD, ROWS)
    t.cell_at(1, 2).text = area
    assert solve_table(pt(), t, Request('room', 'area', '302')) is None


@pytest.mark.parametrize('header,value,expected', [
    ('AREA (SF)', '1 240', (1240, 'ft²')),
    ('S.F.', '1,240', (1240, 'ft²')),
    ('AREA (m²)', '124.5', (124.5, 'm²')),
    ('AREA', '124.5 SQ. M.', (124.5, 'm²')),
])
def test_area_units_are_grounded_in_the_column_or_cell(header, value, expected):
    t = table(['ROOM', 'NAME', header], [['302', 'Reading', value]])
    assert solve_table(pt(), t, Request('room', 'area', '302'))[:2] == expected


def test_ambiguous_area_columns_or_mixed_header_units_defer():
    t = table(['ROOM', 'NAME', 'AREA SF', 'AREA m²'], [['302', 'Reading', '1240', '115.2']])
    assert solve_table(pt(), t, Request('room', 'area', '302')) is None
    t = table(['ROOM', 'NAME', 'AREA SF / m²'], [['302', 'Reading', '1240 SF']])
    assert solve_table(pt(), t, Request('room', 'area', '302')) is None


def test_rotated_pdf_headers_and_mirrored_identity_have_grounded_zero_cost_answers(tmp_path, monkeypatch):
    import pypdfium2 as pdfium
    import engine.models
    from engine.answer import answer
    d = tmp_path / DOC
    d.mkdir()
    headers = ['ROOM NO.', 'NAME', 'SQ.FT.', 'NORTH', 'EAST', 'SOUTH', 'WEST', 'ROOM NO.']
    make_pdf(d / 'generated.pdf', headers, [[*r, r[0]] for r in ROWS], rotated_headers=range(2, 7))
    with pdfium.PdfDocument(d / 'generated.pdf') as pdf:
        pdf[0].render(scale=1).to_pil().save(d / 'page-1.png')
    (d / 'doc.json').write_text(json.dumps({'doc_id': DOC, 'kind': 'pdf', 'pages': 1,
                                         'title': 'generated for demo: rotated schedule'}))
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setattr(engine.models, 'call', lambda *a, **k: pytest.fail('schedule called model'))
    questions = [
        ('On sheet A-909, how many rooms have all four walls finished with W7?', 2, 'count'),
        ('On sheet A-909, what is the area of room 302 in the room finish schedule?', 1240, 'ft²'),
        ('On sheet A-909, which room in the room finish schedule has the largest area?', None, 'ft²'),
    ]
    for question, value, unit in questions:
        a = answer(question, [DOC])
        assert a['route'] == 'index' and not a['answer']['abstained']
        assert (a['answer']['value'], a['answer']['unit']) == (value, unit)
        assert a['cost']['usd_total'] == 0 and not a['cost']['calls']
        assert a['citations'][0]['quote'] and a['evidence']['boxes']
        assert a['trace'][0]['step'] == 'schedule_lookup'
        if value is None:
            assert 'Room 302 Reading (1240 ft²)' in a['answer']['text_md']
    assert not list(d.glob('*text-*.json'))


@pytest.mark.parametrize('question', [
    'What is the area of room 302 in the finish room schedule?',
    'Which room in the finish room schedule has the largest area?',
])
@pytest.mark.parametrize('reader_answers', [False, True])
def test_unread_area_reaches_reader_without_forcing_an_area(tmp_path, monkeypatch, question, reader_answers):
    import engine.answer as mod
    import engine.forced
    incomplete = [list(row) for row in ROWS]
    incomplete[0][2] = '? SF'
    write_doc(tmp_path, records=incomplete)
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('FORCE_ANSWER', '1')
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('TEXT_WITH_MODEL', '0')
    calls = []

    def fallback(name, answered):
        def respond(q, ids, *args):
            calls.append(name)
            out = mod._abstained(q, ids, 'Generated for demo model fallback.', [], 1)
            if answered:
                out['answer'].update(value=1240, confidence=.2, abstained=False)
            return out
        return respond

    monkeypatch.setattr(mod, '_reader', fallback('reader', reader_answers))
    monkeypatch.setattr(engine.forced, 'forced_answer', fallback('forced', True))
    a = mod.answer(question, [DOC])
    assert calls == ['reader']
    assert a['answer']['value'] == (1240 if reader_answers else None)
    assert a['answer']['abstained'] is not reader_answers
