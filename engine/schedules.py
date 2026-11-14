"""Exact PDF schedule lookups. Unsupported or incomplete tables defer to the reader.

Use ruled cell boundaries, not occurrences of a finish/mark elsewhere on a sheet.
Count distinct schedule records; require all four directional wall columns for
an all-wall predicate. No document-specific values or model calls live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
import uuid

from engine.reader.tables import Table, detect_tables
from engine.titleblock import Span, _pages, _sheet


@dataclass
class Request:
    kind: str
    op: str
    target: str | None = None


def request_for(question):
    q = question.casefold()
    if re.search(r'how many rooms|number of rooms', q) and re.search(r'all (?:four|4) walls', q):
        code = re.search(r'\b(?:with|finished with|finish(?:ed)? (?:is|of))\s+([a-z]+\d+[a-z]?)\b', q)
        return Request('room', 'walls', code[1].upper()) if code else None
    if 'schedule' not in q:
        return None
    room = re.search(r'\broom\s+(?:no\.?\s*)?([a-z]*\d+[a-z]?)\b', q)
    kind = next((k for k in ('door', 'window') if re.search(r'\b' + k + r's?\b', q)), None)
    if room and kind and re.search(r'how many|number of', q):
        return Request(kind, 'count', room[1].upper())
    if 'area' in q:
        if re.search(r'largest|greatest|biggest', q):
            return Request('room', 'largest')
        if room:
            return Request('room', 'area', room[1].upper())
    return None


def _norm(text):
    return re.sub(r'[^A-Z0-9]+', ' ', text.upper()).strip()


def _record_id(text):
    s = re.sub(r'\s+', '', text.upper())
    return s if re.fullmatch(r'[A-Z]*\d+(?:[.-]?[A-Z0-9]+)*', s) else None


def _columns(table, end):
    """Only header cells above the first record, including merged group headings."""
    out = {}
    for col in range(table.ncols):
        # A merged WALLS heading belongs to all children; each direction is a
        # separate, unmerged header. Deduplicate repeated merged cell references.
        cells = {id(c): c for r in range(end) if (c := table.cell_at(r, col)) is not None}
        parts = [_norm(c.text) for c in cells.values() if c.text]
        joined = ' '.join(parts)
        role = None
        for direction, variants in {'N': {'N', 'NORTH'}, 'E': {'E', 'EAST'},
                                    'S': {'S', 'SOUTH'}, 'W': {'W', 'WEST'}}.items():
            if any(p in variants for p in parts):
                role = direction
        if role is None:
            if 'AREA' in joined.split():
                role = 'area'
            elif any(p in {'QTY', 'QUANTITY', 'COUNT'} for p in parts):
                role = 'qty'
            elif any(p in {'NAME', 'ROOM NAME', 'DESCRIPTION'} for p in parts):
                role = 'name'
            elif re.search(r'\b(?:MARK|NUMBER|NO|NUM|ID)\b', joined):
                role = 'room' if 'ROOM' in joined.split() else 'id'
            elif parts and parts[-1] in {'ROOM', 'DOOR', 'WINDOW'}:
                role = 'room' if parts[-1] == 'ROOM' else 'id'
        if role:
            if role in out:  # duplicate headings cannot identify a column uniquely
                out[role] = None
            else:
                out[role] = col
    return {k: v for k, v in out.items() if v is not None}


def _records(table, req):
    """Find the record column from its header and reject incomplete/merged rows."""
    for start in range(1, min(table.nrows, 8)):
        cols = _columns(table, start)
        heading = table.title + ' ' + ' '.join(c.text for c in table.cells if c.r < start)
        id_col = cols.get('room') if req.kind == 'room' else cols.get('id')
        if id_col is None and req.kind == 'room' and re.search(r'\b(?:room|finish)\b', heading, re.I):
            id_col = cols.get('id')
        if id_col is None:
            continue
        cell = table.cell_at(start, id_col)
        if cell is None or not _record_id(cell.text):
            continue
        required = ({'N', 'E', 'S', 'W'} if req.op == 'walls' else
                    {'area'} if req.op in {'area', 'largest'} else set())
        if not required <= cols.keys():
            return None
        if req.kind != 'room':
            # A generic MARK header is only a door/window schedule if the title
            # or another header explicitly identifies that schedule kind.
            if not re.search(r'\b' + req.kind + r's?\b', heading, re.I):
                return None
        elif re.search(r'\b(?:door|window)\s+schedule\b', table.title, re.I):
            return None
        records, seen = [], set()
        for row in range(start, table.nrows):
            id_cell = table.cell_at(row, id_col)
            if id_cell is None:
                return None
            if not id_cell.text.strip():
                # Empty trailing rows are harmless; a populated row with no mark
                # may be an unread record, so defer the entire aggregate.
                if any(c.text.strip() for c in table.cells if c.r == row):
                    return None
                continue
            if _norm(id_cell.text) in {'TOTAL', 'TOTALS', 'GRAND TOTAL'}:
                continue
            rid = _record_id(id_cell.text)
            if rid is None or rid in seen or id_cell.rs != 1 or id_cell.cs != 1:
                return None
            seen.add(rid)
            values = {}
            for key, col in cols.items():
                c = table.cell_at(row, col)
                if c is not None and c.rs == 1 and c.cs == 1:
                    values[key] = c.text.strip()
            if any(not values.get(key) for key in required):
                return None
            records.append((rid, values, row))
        return (cols, records) if records else None
    return None


def _area(text, heading):
    m = re.fullmatch(r'\s*([\d,]+(?:\.\d+)?)\s*(SF|SQ\.?\s*FT|FT[²2]|M[²2]|SQ\.?\s*M)?\s*', text, re.I)
    if not m:
        return None
    # Preserve the printed unit; never relabel square feet as square metres.
    units = (m[2] or heading).upper()
    sf = bool(re.search(r'\bSF\b|\bSQ\.?\s*FT\b|FT[²2]', units))
    sqm = bool(re.search(r'\bM[²2]\b|\bSQ\.?\s*M\b', units))
    if sf == sqm:
        return None
    return float(m[1].replace(',', '')), 'ft²' if sf else 'm²'


def solve_table(pt, table, req):
    parsed = _records(table, req)
    if parsed is None:
        return None
    cols, records = parsed
    selected = []
    if req.op == 'walls':
        selected = [r for r in records if all(r[1][d].upper() == req.target for d in 'NESW')]
        value, unit = len(selected), 'count'
        text = f'**{value} rooms** have {req.target} on all four walls.'
    elif req.op == 'count':
        if 'room' in cols:
            # Explicit room identity wins over any numeric prefix in a door mark.
            if any(not _record_id(r[1].get('room', '')) for r in records):
                return None
            selected = [r for r in records if _record_id(r[1]['room']) == req.target]
        else:
            # Conventional room-derived marks: 205, 205A, 205.A, 205-B.
            # Do not match 2050, 1205A or 205AA by numeric substring.
            rx = re.compile(re.escape(req.target) + r'(?:[.-]?[A-Z])?')
            selected = [r for r in records if rx.fullmatch(r[0])]
            if not selected:
                return None  # absence cannot establish a room/mark convention
        amounts = [r[1].get('qty', '') if 'qty' in cols else '1' for r in selected]
        if any(not re.fullmatch(r'[1-9]\d*', amount) for amount in amounts):
            return None
        value, unit = sum(map(int, amounts)), 'count'
        text = f'**{value} {req.kind}s** are listed for room {req.target}.'
    else:
        header = ' '.join(c.text for c in table.cells if c.r < records[0][2] and c.c <= cols['area'] < c.c + c.cs)
        areas = [(r, _area(r[1]['area'], header)) for r in records]
        if any(a is None for _, a in areas) or len({a[1] for _, a in areas}) != 1:
            return None
        if req.op == 'largest':
            top = max(a[0] for _, a in areas)
            best = [(r, a) for r, a in areas if a[0] == top]
            if len(best) != 1:
                return None
            row, (number, unit) = best[0]
            value = None
            text = f'**Room {row[0]} {row[1].get("name", "")} ({number:g} {unit})** has the largest scheduled area.'
        else:
            matches = [(r, a) for r, a in areas if r[0] == req.target]
            if len(matches) != 1:
                return None
            row, (value, unit) = matches[0]
            text = f'**{value:g} {unit}** is the scheduled area of room {req.target}.'
        selected = [row]
    # A count, including zero, cites the full table so the predicate and all
    # excluded rows can be checked. Matching rows have numbered evidence too.
    spans = [Span(pt, ' | '.join(c.text for c in table.cells if c.text), table.bbox_px)]
    spans += [Span(pt, ' | '.join(c.text for c in table.cells if c.r == r[2] and c.text),
                   table.row_bbox(r[2])) for r in selected]
    return value, unit, text, spans


def answer_schedule(question, doc_ids, root, t0=None):
    req = request_for(question)
    if req is None:
        return None
    t0 = t0 or time.perf_counter()
    answers = []
    sheet = re.search(r'\bsheet\s+([A-Z]{1,3}[-.]?\d{2,4})\b', question, re.I)
    for did in doc_ids:
        for pt in _pages(did, root, question):
            if sheet:
                actual = _sheet(pt)
                # A named sheet must be proven, not silently ignored.
                if actual is None or re.sub(r'\W', '', actual['text'].upper()) != re.sub(r'\W', '', sheet[1].upper()):
                    continue
            image = Path(root) / did / f'page-{pt.page}.png'
            if not image.exists():
                continue
            try:
                tables = detect_tables(image, pt)
            except ImportError:  # optional geometry dependency; production ladder remains available
                return None
            for table in tables:
                if (found := solve_table(pt, table, req)) is not None:
                    answers.append(found)
    if len(answers) != 1:
        return None  # multiple schedules need an explicit scope; never sum duplicates
    value, unit, text, spans = answers[0]
    citations, boxes = [], []
    for n, s in enumerate(spans, 1):
        citations.append(dict(n=n, doc_id=s.pt.doc_id, page=s.pt.page, kind='text',
                              bbox_px=s.bbox, item_ids=[], quote=s.text))
        boxes.append(dict(item_id=f'schedule-{s.pt.page}-{n}', page=s.pt.page, bbox_px=s.bbox, label=str(n)))
    ms = int((time.perf_counter() - t0) * 1000)
    return dict(answer_id=uuid.uuid4().hex, question=question, doc_ids=list(doc_ids),
                answer=dict(text_md=text + ' [1]', value=value, unit=unit, confidence=.95, abstained=False),
                citations=citations, evidence=dict(boxes=boxes, scene=dict(doc_id=spans[0].pt.doc_id,
                    highlight_item_ids=[], camera_target_item_id=None)),
                trace=[dict(step='schedule_lookup', detail=f'{req.kind} / {req.op}: exact ruled PDF cells',
                            ms=ms, model=None, cost_usd=0)], route='index',
                cost=dict(usd_total=0.0, calls=[]), latency_ms=ms)
