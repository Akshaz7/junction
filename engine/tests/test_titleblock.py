"""E-35: generated for demo fixtures; no held-out drawings or model calls."""
import json
from pathlib import Path

import pytest

from engine.titleblock import _pdfminer_page, answer_text, extract, field_for
from engine.reader.text import PageText, build_segments

DOC = 'opening_design__generated-titleblock-demo'


def line(text, x, y, width=None, height=12):
    return {'text': text, 'bbox_px': [x, y, x + (width or len(text) * 6), y + height]}


def page(words, page=1):
    pt = PageText(DOC, page, 1000, 800, words, 'generated for demo')
    pt.segs = build_segments(pt)
    return pt


def write_doc(root, words, page_no=1, image=(1000, 800)):
    d = root / DOC
    d.mkdir(exist_ok=True)
    (d / 'doc.json').write_text(json.dumps({'doc_id': DOC, 'kind': 'pdf', 'pages': page_no}))
    (d / f'text-{page_no}.json').write_text(json.dumps({'words': words, 'image': dict(zip(('w', 'h'), image))}))
    return d


@pytest.mark.parametrize(('question', 'label', 'value'), [
    ('What is the project name?', 'Project name', 'Harbor Library'),
    ('What is the sheet number?', 'Sheet No.', 'A204'),
    ('What scale is printed?', 'Scale', '1:100'),
    ('Who was this drawn by?', 'Drawn by', 'RS / MK'),
    ('Who checked this drawing?', 'Checked by', 'AK'),
    ('What is the drawing title?', 'Drawing title', 'First Floor Plan'),
    ('What is the issue date?', 'Issue date', '2025-09-12'),
])
def test_positioned_fields(question, label, value):
    pt = page([line(label, 710, 650, 100), line(value, 850, 650, 130),
               line('UNRELATED', 500, 650), line('DO NOT USE', 850, 720)])
    spans = extract(pt, question)
    assert [s.text for s in spans] == [value]
    assert spans[0].bbox == [850, 650, 980, 662]


def test_value_below_label_and_inline_field():
    pt = page([line('Architect', 800, 600), line('Demo Studio', 800, 618),
               line('Owner: Harbor Group', 800, 670)])
    assert extract(pt, 'Which architect is listed?')[0].text == 'Demo Studio'
    assert extract(pt, 'Who is the owner?')[0].text == 'Harbor Group'


def test_ambiguous_or_missing_field_defers():
    pt = page([line('Architect: One Studio', 710, 550), line('Architect: Two Studio', 710, 620),
               line('Drawn by', 710, 700), line('Date', 710, 720)])
    assert extract(pt, 'Who is the architect?') == []
    assert extract(pt, 'Who was this drawn by?') == []
    assert extract(pt, 'What scale is printed?') == []
    assert field_for('How many windows are shown?') is None
    assert field_for('What door material is scheduled for D204?') is None


def test_footer_date_is_not_revision_date_or_time_scale():
    pt = page([line('Date', 710, 450), line('01/02/2024', 710, 470),
               line('Date', 710, 700), line('03/04/2025 1:45:32 PM', 850, 700, 145),
               line('Scale', 710, 750), line('As indicated', 850, 750)])
    assert extract(pt, 'What date is printed beside Date in the title block?')[0].text == '03/04/2025 1:45:32 PM'
    assert extract(pt, 'What scale is printed in the title block?')[0].text == 'As indicated'


def test_large_sheet_number_beats_detail_reference():
    pt = page([line('A360', 760, 680, 24, 10), line('A402', 880, 730, 100, 35)])
    spans = extract(pt, 'What sheet number is printed?')
    assert [s.text for s in spans] == ['A402']
    assert spans[0].bbox == [880, 730, 980, 765]


def test_split_project_title_keeps_both_quotes():
    words = [line('normal body text', 100, 100)]
    words += [line('Harbor', 850, 535, 100, 30), line('Library', 850, 573, 120, 30),
              line('Floor Plans', 850, 660, 130, 30), line('A204', 870, 740, 100, 45)]
    pt = page(words)
    assert [s.text for s in extract(pt, 'What is the project name?')] == ['Harbor', 'Library']
    assert [s.text for s in extract(pt, 'What is the sheet title?')] == ['Floor Plans']


def test_numbered_revision_selects_row_not_largest_date():
    pt = page([line('No.', 710, 450), line('Description', 800, 450), line('Date', 930, 450),
               line('1', 710, 480, 8), line('Permit', 800, 480), line('01/02/2024', 930, 480),
               line('3', 710, 520, 8), line('ADDENDUM', 800, 520), line('03/04/2025', 930, 520)])
    spans = extract(pt, 'What is the description of revision 3?')
    assert [s.text for s in spans] == ['ADDENDUM', '03/04/2025']


def test_note_wrap_stops_at_next_note():
    pt = page([line('NOTE 4', 100, 200), line('PROVIDE FIRE CAULK', 100, 220),
               line('AT ALL PENETRATIONS', 100, 240), line('NOTE 5', 100, 260),
               line('USE BLOCKING', 100, 280), line('OTHER COLUMN', 400, 220)])
    spans = extract(pt, 'What does note 4 require?')
    assert [s.text for s in spans] == ['NOTE 4', 'PROVIDE FIRE CAULK', 'AT ALL PENETRATIONS']
    assert extract(pt, 'What does note 99 require?') == []


def test_note_requirement_still_routes_to_reader(tmp_path):
    write_doc(tmp_path, [line('NOTE 4', 100, 200), line('PROVIDE FIRE CAULK', 100, 220)])
    assert answer_text('What does note 4 on this sheet require?', [DOC], tmp_path) is None


def test_legend_requires_exact_entry_and_heading():
    words = [line('LEGEND', 100, 200), line('HM', 100, 240, 20), line('HOLLOW METAL', 170, 240),
             line('HMU', 100, 280, 22), line('OTHER MATERIAL', 170, 280)]
    pt = page(words)
    spans = extract(pt, 'In the legend, what does HM mean?')
    assert [s.text for s in spans] == ['HM', 'HOLLOW METAL']
    assert extract(page(words[1:]), 'In the legend, what does HM mean?') == []


def test_answer_contract_is_grounded_and_model_free(tmp_path, monkeypatch):
    import engine.models
    monkeypatch.setattr(engine.models, 'call', lambda *a, **k: pytest.fail('code route called model'))
    words = [line('Drawn by', 710, 650), line('RS', 850, 650)]
    write_doc(tmp_path, words, page_no=2)
    a = answer_text('Who was this drawn by on page 2?', [DOC], tmp_path)
    assert a['route'] == 'index' and not a['answer']['abstained']
    assert a['cost'] == {'usd_total': 0.0, 'calls': []}
    c = a['citations'][0]
    assert (c['doc_id'], c['page'], c['quote']) == (DOC, 2, 'RS')
    assert c['bbox_px'] == words[1]['bbox_px'] == a['evidence']['boxes'][0]['bbox_px']
    assert '> RS [1]' in a['answer']['text_md']
    assert answer_text('Who was this drawn by on page 1?', [DOC], tmp_path) is None


def test_answer_integration_precedes_model_router(tmp_path, monkeypatch):
    import engine.models
    from engine.answer import answer
    write_doc(tmp_path, [line('Project: Harbor Library', 710, 650)])
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.delenv('MODELS_FAKE', raising=False)
    monkeypatch.setenv('EXPLAIN', '0')   # the optional plain-words explanation (E-77) is a separate, later step
    monkeypatch.setattr(engine.models, 'call', lambda *a, **k: pytest.fail('code route called model'))
    a = answer('What is the project name?', [DOC])
    assert a['answer']['text_md'].startswith('**Harbor Library**')
    assert a['trace'][0]['step'] == 'text_lookup'
    assert a['cost']['calls'] == []


def test_existing_text_boxes_are_scaled_to_page_image(tmp_path):
    from engine.tests.test_reader import _png
    d = write_doc(tmp_path, [line('Architect: Demo Studio', 710, 650)])
    _png(d / 'page-1.png', w=2000, h=1600)
    a = answer_text('Who is the architect?', [DOC], tmp_path)
    # Both dimensions differ: the old text artifact fails its geometry check,
    # so it is deliberately not used as evidence on the resized image.
    assert a is None


def simple_pdf(path):
    # generated for demo: one Helvetica line at PDF coordinates (280, 40).
    stream = b'BT /F1 12 Tf 280 40 Td (Sheet No: A204) Tj ET'
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    content = b'%PDF-1.4\n'
    offsets = [0]
    for n, obj in enumerate(objs, 1):
        offsets.append(len(content))
        content += f'{n} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(content)
    content += b'xref\n0 6\n0000000000 65535 f \n'
    content += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    content += f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    path.write_bytes(content)


def test_pdfminer_fallback_has_top_left_pixel_boxes(tmp_path):
    d = tmp_path / DOC
    d.mkdir()
    pdf = d / 'demo.pdf'
    simple_pdf(pdf)
    pt = _pdfminer_page(pdf, 1, (800, 600), DOC)
    assert ' '.join(w['text'] for w in pt.words) == 'Sheet No: A204'
    assert pt.words[0]['bbox_px'][0] == pytest.approx(560)
    assert 490 < pt.words[0]['bbox_px'][1] < 520
    assert all(0 <= w['bbox_px'][0] < w['bbox_px'][2] <= 800 for w in pt.words)
    (d / 'doc.json').write_text(json.dumps({'doc_id': DOC, 'kind': 'pdf', 'pages': 1}))
    a = answer_text('What is the sheet number?', [DOC], tmp_path)
    assert a['citations'][0]['quote'] == 'A204'
    assert not list(d.glob('text-*.json')) and not list(d.glob('rtext-*.json'))
