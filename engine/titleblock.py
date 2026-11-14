"""Position-aware PDF title-block, note and legend answers, without model calls.

Read existing page text, or pdfminer positions when no usable text artifact exists.
Every returned fact is a verbatim source span with a page-image pixel box. No
gold answers, document-specific names or dataset questions are used here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from statistics import median
import time
import uuid

from engine.reader.text import PageText, _geometry_ok, build_segments, png_size, source_pdf


LABELS = {
    'sheet_number': r'(?:sheet|drawing|dwg)\s*(?:number|no\.?|#)',
    'sheet_title': r'(?:sheet|drawing)\s*(?:title|name)',
    'project_name': r'project(?:\s*(?:name|title))?',
    'scale': r'(?:drawing\s+)?scale',
    'drawn_by': r'(?:drawn|drafter|designed)(?:\s*by)?',
    'checked_by': r'(?:checked|approved)(?:\s*by)?',
    'date': r'(?:issue\s+|drawing\s+|plot\s+)?date',
    'revision': r'rev(?:ision)?\.?',
    'architect': r'architect',
    'owner': r'(?:project\s+)?owner',
}
SHEET = re.compile(r'[A-Z]{1,3}[-.]?\d{2,4}(?:[.-]\d+)?', re.I)
DATE = re.compile(r'\b\d{1,4}[./-]\d{1,2}[./-]\d{2,4}\b')
SCALE = re.compile(r'\b(?:as indicated|n\.?t\.?s\.?|not to scale)\b|\d\s*:\s*\d|["\u2033]\s*=\s*\d', re.I)


@dataclass
class Span:
    pt: PageText
    text: str
    bbox: list[float]


def _span(pt, seg, text=None):
    return Span(pt, text if text is not None else seg['text'], seg['bbox_px'])


def _pdfminer_page(pdf, page, size, doc_id):
    """pdfminer applies the page rotation; map its bottom-left coords to pixels."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextLine
    layout = next(iter(extract_pages(str(pdf), page_numbers=[page - 1], laparams=LAParams())))
    w, h = size or (round(layout.width * 150 / 72), round(layout.height * 150 / 72))
    sx, sy = w / layout.width, h / layout.height
    words = []

    def visit(obj):
        if isinstance(obj, LTTextLine):
            chars = []

            def flush():
                if not chars:
                    return
                words.append({'text': ''.join(c.get_text() for c in chars), 'bbox_px': [
                    min(c.x0 for c in chars) * sx, (layout.height - max(c.y1 for c in chars)) * sy,
                    max(c.x1 for c in chars) * sx, (layout.height - min(c.y0 for c in chars)) * sy]})
                chars.clear()

            for c in obj:
                if isinstance(c, LTChar) and not c.get_text().isspace():
                    chars.append(c)
                else:
                    flush()
            flush()
        elif hasattr(obj, '__iter__'):
            for child in obj:
                visit(child)

    visit(layout)
    return PageText(doc_id, page, w, h, words, 'pdfminer-text-layer')


def _pages(doc_id, root, question):
    d = Path(root) / doc_id
    try:
        meta = json.loads((d / 'doc.json').read_text())
    except (OSError, ValueError):
        return
    if meta.get('kind') != 'pdf' and 'pdf' not in (meta.get('files') or {}):
        return
    m = re.search(r'\bpage\s+(\d+)\b', question, re.I)
    pages = [int(m[1])] if m else range(1, int(meta.get('pages') or 1) + 1)
    for page in pages:
        size = png_size(d / f'page-{page}.png')
        pt = None
        for prefix in ('text', 'rtext'):
            try:
                t = json.loads((d / f'{prefix}-{page}.json').read_text())
                if not t.get('words') or not _geometry_ok(t, size):
                    continue
                image = t.get('image') or {}
                w, h = size or (image.get('w', 0), image.get('h', 0))
                if not w or not h:
                    continue
                sx, sy = w / (image.get('w') or w), h / (image.get('h') or h)
                words = [{'text': x['text'], 'bbox_px': [v * (sx if j % 2 == 0 else sy)
                          for j, v in enumerate(x['bbox_px'])]} for x in t['words'] if x.get('bbox_px')]
                pt = PageText(doc_id, page, w, h, words, t.get('source') or 'text-layer')
                break
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if pt is None:
            pdf = source_pdf(doc_id, root)
            if pdf is not None:
                try:
                    pt = _pdfminer_page(pdf, page, size, doc_id)
                except (OSError, ValueError, StopIteration):
                    continue
        if pt is not None and pt.words:
            pt.segs = build_segments(pt)
            yield pt


def field_for(question):
    q = question.lower()
    if re.search(r'\b(?:note|legend|abbreviation)\b', q):
        return 'lookup'
    if re.search(r'\brev(?:ision)?\.?\s*(?:number|no\.?|#)?\s*\d+\b|\b(?:latest|current) revision\b', q):
        return 'revision'
    for field, pattern in [
        ('drawn_by', r'\bdrawn\b|\bdrafter\b|\bdesigned by\b'),
        ('checked_by', r'\bchecked\b|\bapproved by\b'),
        ('architect', r'\barchitect\b'), ('owner', r'\bowner\b'),
        ('project_name', r'\bproject (?:name|title)\b|\bname of (?:the |this )?project\b'),
        ('sheet_number', r'\b(?:sheet|drawing|dwg)\s*(?:number|no\.?|#)\b'),
        ('sheet_title', r'\b(?:sheet|drawing)\s*(?:title|name)\b'),
        ('scale', r'\bscale\b'), ('date', r'\bdate\b'),
    ]:
        if re.search(pattern, q):
            return field
    return None


def _is_label(text):
    s = text.strip().rstrip(':').strip()
    return any(re.fullmatch(p, s, re.I) for p in LABELS.values()) or s.lower() in {'description', 'no.', 'no'}


def _near(pt, seg, field):
    b = seg['bbox_px']
    cy, height = (b[1] + b[3]) / 2, max(b[3] - b[1], 1)
    candidates = []
    for s in pt.segs:
        if s is seg or _is_label(s['text']):
            continue
        bb = s['bbox_px']
        sh = max(bb[3] - bb[1], 1)
        if field == 'date' and not DATE.search(s['text']):
            continue
        if field == 'scale' and not SCALE.search(s['text']):
            continue
        # Same row to the right, or the next aligned row below the label.
        dy = abs((bb[1] + bb[3]) / 2 - cy)
        if bb[0] >= b[2] - 1 and dy <= .65 * max(height, sh) and bb[0] - b[2] < pt.w * .18:
            score = dy / height + (bb[0] - b[2]) / (pt.w * .18)
        elif bb[1] >= b[3] - 1 and bb[1] - b[3] < 5 * height and (
                abs(bb[0] - b[0]) < 3 * height or bb[0] <= (b[0] + b[2]) / 2 <= bb[2]):
            score = 2 + (bb[1] - b[3]) / height + abs(bb[0] - b[0]) / (3 * height)
        else:
            continue
        candidates.append((score, s))
    if candidates:
        return min(candidates, key=lambda x: x[0])[1]
    return None


def _labelled(pt, field, question):
    found = []
    for s in pt.segs:
        m = re.fullmatch(r'\s*' + LABELS[field] + r'\s*(?::\s*(.+))?\s*', s['text'], re.I)
        if not m:
            continue
        if m[1] and not _is_label(m[1]):
            found.append((_span(pt, s, m[1].strip()), s['bbox_px'][1]))
        else:
            value = _near(pt, s, field)
            if value:
                found.append((_span(pt, value), s['bbox_px'][1]))
    if not found:
        return []
    # A footer's Date field is distinct from the revision table's Date header.
    if field == 'date' and 'issue' not in question.lower():
        return [max(found, key=lambda v: v[1])[0]]
    values = {x.text.casefold() for x, _ in found}
    return [found[0][0]] if len(values) == 1 else []


def _sheet(pt):
    matches = [s for s in pt.segs if SHEET.fullmatch(s['text'].strip()) and
               s['bbox_px'][0] > pt.w * .7 and s['bbox_px'][1] > pt.h * .65]
    if not matches:
        return None
    # A sheet identifier is much larger than nearby detail references.
    return max(matches, key=lambda s: (s['bbox_px'][3] - s['bbox_px'][1], s['bbox_px'][1]))


def _heading(pt, field):
    sheet = _sheet(pt)
    if sheet is None:
        return []
    typical = min(median(max(s['bbox_px'][3] - s['bbox_px'][1], 1) for s in pt.segs),
                  (sheet['bbox_px'][3] - sheet['bbox_px'][1]) / 3)
    large = [s for s in pt.segs if s is not sheet and len(s['text']) > 3 and not _is_label(s['text'])
             and s['bbox_px'][3] - s['bbox_px'][1] >= typical * 2
             and s['bbox_px'][0] > pt.w * .35 and s['bbox_px'][1] > pt.h * .65]
    # A long footer project/address line to the left of the sheet number.
    footer = [s for s in large if s['bbox_px'][2] < sheet['bbox_px'][0] and
              abs(s['bbox_px'][1] - sheet['bbox_px'][1]) < 2 * (sheet['bbox_px'][3] - sheet['bbox_px'][1])]
    if footer and field == 'project_name':
        s = max(footer, key=lambda s: s['bbox_px'][2] - s['bbox_px'][0])
        return [_span(pt, s, s['text'].split('|')[0].strip())]
    titles = sorted([s for s in large if s['bbox_px'][0] > pt.w * .8 and
                     s['bbox_px'][3] < sheet['bbox_px'][1]], key=lambda s: s['bbox_px'][1])
    groups = []
    for s in titles:
        if groups and s['bbox_px'][1] - groups[-1][-1]['bbox_px'][3] < 1.5 * typical * 2:
            groups[-1].append(s)
        else:
            groups.append([s])
    if not groups:
        return []
    # Only distinguish project and drawing titles when two heading groups exist.
    if len(groups) < 2:
        return []
    group = groups[0] if field == 'project_name' else groups[-1]
    return [_span(pt, s) for s in group]


def _revision(pt, question):
    m = re.search(r'\brev(?:ision)?\.?\s*(?:number|no\.?|#)?\s*(\d+)\b', question, re.I)
    if not m:
        return []
    headers = [s for s in pt.segs if s['text'].strip().lower() == 'description']
    for header in headers:
        hb = header['bbox_px']
        numbers = [s for s in pt.segs if s['text'].strip() == m[1] and s['bbox_px'][0] < hb[0]
                   and s['bbox_px'][0] > pt.w * .65 and hb[3] < s['bbox_px'][1] < hb[3] + pt.h * .18]
        for number in numbers:
            b = number['bbox_px']
            row = [s for s in pt.segs if s is not number and s['bbox_px'][0] > b[2]
                   and abs((s['bbox_px'][1] + s['bbox_px'][3] - b[1] - b[3]) / 2) < (b[3] - b[1]) * .7]
            row.sort(key=lambda s: s['bbox_px'][0])
            if row:
                return [_span(pt, s) for s in row]
    return []


def _lookup(pt, question):
    m = re.search(r'\bnote\s*#?\s*(\d+[A-Za-z]?)\b', question, re.I)
    if m:
        rx = re.compile(r'(?:NOTE\s*)?' + re.escape(m[1]) + r'[.):]?\s*(.*)', re.I)
        hits = [(s, rx.fullmatch(s['text'].strip())) for s in pt.segs]
        hits = [(s, match) for s, match in hits if match and
                (s['text'].lower().startswith('note') or s['text'].startswith(m[1] + '.'))]
        if len(hits) != 1:
            return []
        s, match = hits[0]
        # Include wrapped lines in the same column until the next note/heading.
        b = s['bbox_px']
        height = max(b[3] - b[1], 1)
        after = sorted([t for t in pt.segs if t is not s and t['bbox_px'][1] >= b[3] - 1
                        and b[0] - height <= t['bbox_px'][0] <= b[0] + 4 * height],
                       key=lambda t: t['bbox_px'][1])
        spans = [_span(pt, s)]
        bottom = b[3]
        for t in after:
            if t['bbox_px'][1] - bottom > height * 1.8 or re.match(r'(?:NOTE\s*\d+\b|\d+[.)]\s*)', t['text'], re.I) or _is_label(t['text']):
                break
            spans.append(_span(pt, t))
            bottom = t['bbox_px'][3]
        return spans if match[1] or len(spans) > 1 else []
    m = re.search(r'["“\']([^"”\']+)["”\']', question)
    if not m:
        m = re.search(r'\b(?:does|is)\s+([A-Z][A-Z0-9.-]*)\s+(?:mean|stand for)\b', question)
    if not m:
        return []
    term = m[1].strip()
    heads = [s for s in pt.segs if re.search(r'\b(?:legend|abbreviations?)\b', s['text'], re.I)]
    matches = []
    for s in pt.segs:
        # Exact token or prefix only; a word embedded in general notes is not a legend entry.
        if not re.match(re.escape(term) + r'(?:\s*[-:=]\s*|\s+|$)', s['text'], re.I):
            continue
        if not any(h['bbox_px'][1] < s['bbox_px'][1] < h['bbox_px'][1] + pt.h * .4 and
                   abs(s['bbox_px'][0] - h['bbox_px'][0]) < pt.w * .12 for h in heads):
            continue
        if s['text'].strip().casefold() != term.casefold():
            matches.append([_span(pt, s)])
        elif (value := _near(pt, s, 'lookup')) is not None:
            matches.append([_span(pt, s), _span(pt, value)])
    return matches[0] if len(matches) == 1 else []


def extract(pt, question, field=None):
    field = field or field_for(question)
    if field == 'lookup':
        return _lookup(pt, question)
    if field == 'revision':
        return _revision(pt, question) or _labelled(pt, field, question)
    if field not in LABELS:
        return []
    if found := _labelled(pt, field, question):
        return found
    if field == 'sheet_number' and (s := _sheet(pt)) is not None:
        return [_span(pt, s)]
    if field in ('project_name', 'sheet_title'):
        return _heading(pt, field)
    return []


def answer_text(question, doc_ids, root, t0=None):
    """Return a grounded answer for supported PDF fields, else defer to the reader."""
    field = field_for(question)
    # The reader owns note/requirement interpretation; early routing is only
    # for title-block fields (LEAD handoff). extract() remains available to tools.
    if field is None or field == 'lookup':
        return None
    t0 = t0 or time.perf_counter()
    spans = []
    for doc_id in doc_ids:
        for pt in _pages(doc_id, root, question):
            selected_sheet = re.search(r'\bsheet\s+([A-Z]{1,3}[-.]?\d{2,4})\b', question, re.I)
            if selected_sheet:
                sheet = _sheet(pt)
                if sheet and sheet['text'].casefold() != selected_sheet[1].casefold():
                    continue
            found = extract(pt, question, field)
            if found:
                spans.extend(found)
    if not spans:
        return None
    citations, boxes = [], []
    for n, span in enumerate(spans, 1):
        iid = f'text-{span.pt.page}-{n}'
        citations.append(dict(n=n, doc_id=span.pt.doc_id, page=span.pt.page, kind='text',
                              bbox_px=span.bbox, item_ids=[], quote=span.text))
        boxes.append(dict(item_id=iid, page=span.pt.page, bbox_px=span.bbox, label=str(n)))
    value = ' '.join(s.text for s in spans)
    text = '**' + value + '** ' + ' '.join(f'[{n}]' for n in range(1, len(spans) + 1))
    text += '\n\n' + '\n'.join(f'> {s.text} [{n}]' for n, s in enumerate(spans, 1))
    ms = int((time.perf_counter() - t0) * 1000)
    return dict(answer_id=uuid.uuid4().hex, question=question, doc_ids=list(doc_ids),
                answer=dict(text_md=text, value=None, unit=None, confidence=.9, abstained=False),
                citations=citations, evidence=dict(boxes=boxes, scene=dict(doc_id=spans[0].pt.doc_id,
                    highlight_item_ids=[], camera_target_item_id=None)),
                trace=[dict(step='text_lookup', detail=f'{field}: exact PDF text with page and pixel boxes',
                            ms=ms, model=None, cost_usd=0)], route='index',
                cost=dict(usd_total=0.0, calls=[]), latency_ms=ms)
