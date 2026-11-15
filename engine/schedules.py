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
    if kind and not room and re.search(r'\b(?:list|read|show|give|each|every|all|total|quantit\w*|types?)\b', q):
        return Request(kind, 'list')
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


def _header_roles(table, end):
    """Keep repeated identity columns: many schedules repeat room no. at right.

    Repetition is only safe when every row agrees, checked in _records(). Other
    duplicate roles stay ambiguous, including two different area columns.
    """
    roles = {}
    directions = {'N': 'NORTH', 'E': 'EAST', 'S': 'SOUTH', 'W': 'WEST'}
    for col in range(table.ncols):
        cells = {id(c): c for r in range(end) if (c := table.cell_at(r, col)) is not None}
        parts = [_norm(c.text) for c in cells.values() if c.text]
        joined = ' '.join(parts)
        role = None
        for direction, full in directions.items():
            if any(p in {direction, full, f'{direction} WALL', f'{full} WALL',
                         f'WALL {direction}', f'WALL {full}'} for p in parts):
                role = direction
        if role is None:
            if 'AREA' in joined.split() or any(_area_unit(c.text) for c in cells.values()):
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
            roles.setdefault(role, []).append(col)
    return roles


def _columns(table, end):
    """Only header cells above the first record, including merged group headings."""
    return {role: cols[0] for role, cols in _header_roles(table, end).items()
            if len(cols) == 1 or role in {'room', 'id'}}


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
                    {'area'} if req.op == 'largest' else set())
        if req.op == 'area' and 'area' not in cols:
            return None
        if not required <= cols.keys():
            return None
        if req.kind != 'room':
            # A generic MARK header is only a door/window schedule if the title
            # or another header explicitly identifies that schedule kind.
            if not re.search(r'\b' + req.kind + r's?\b', heading, re.I):
                return None
        elif re.search(r'\b(?:door|window)\s+schedule\b', table.title, re.I):
            return None
        roles = _header_roles(table, start)
        identities = [group for role, group in roles.items() if role in {'room', 'id'} and len(group) > 1]
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
            # A repeated room-number heading is a check column, never another
            # record or an excuse to silently choose the left-hand value.
            for group in identities:
                checks = [table.cell_at(row, col) for col in group]
                if any(c is None or c.rs != 1 or c.cs != 1 or _record_id(c.text) is None for c in checks):
                    return None
                if len({_record_id(c.text) for c in checks}) != 1:
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


def _area_units(text):
    sf = bool(re.search(r'\b(?:S\.?F\.?|SQ\.?\s*FT\.?|FT[²2]|SQUARE\s+FEET)(?!\w)', text, re.I))
    sqm = bool(re.search(r'\b(?:M[²2]|SQ\.?\s*M\.?|SQUARE\s+MET(?:RE|ER)S)(?!\w)', text, re.I))
    return ({'ft²'} if sf else set()) | ({'m²'} if sqm else set())


def _area_unit(text):
    units = _area_units(text)
    return next(iter(units)) if len(units) == 1 else None


def _area(text, heading):
    number = r'(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:\.\d+)?'
    m = re.fullmatch(r'\s*(' + number + r')\s*(S\.?F\.?|SQ\.?\s*FT\.?|FT[²2]|M[²2]|SQ\.?\s*M\.?)?\s*', text, re.I)
    if not m:
        return None
    # Preserve the printed unit; never relabel square feet as square metres.
    if len(_area_units(heading)) > 1:
        return None
    explicit, header_unit = _area_unit(m[2] or ''), _area_unit(heading)
    if explicit and header_unit and explicit != header_unit:
        return None
    unit = explicit or header_unit
    if unit is None:
        return None
    value = float(re.sub(r'[,\s\u00a0\u202f]', '', m[1]))
    return (value, unit) if value > 0 else None


_LIST_ROLES = (('width', r'\bWIDTH\b|\bWIDE\b|^W$'), ('height', r'\bHEIGHT\b|\bHT\b|^H$'),
               ('qty', r'^(?:QTY|QUANTITY|COUNT|NO OF|NUMBER OF|TOTAL)$|\bQTY\b|\bQUANTITY\b|^COUNT$'),
               ('mark', r'^(?:TYPE MARK|MARK|TYPE|DOOR TYPE|WINDOW TYPE|DOOR NUMBER|DOOR NO|WINDOW NUMBER|NO|TAG|ID|SYMBOL)$'))


def _int_qty(text):
    return int(text) if re.fullmatch(r'[1-9]\d*', text.strip()) else None


def _words_above(pt, table):
    """Text-layer words in the band just above a grid (its header and sheet heading)."""
    x0, y0, x1, y1 = table.bbox_px
    return [w for w in getattr(pt, 'words', None) or []
            if y0 - 150 <= w['bbox_px'][3] <= y0 + 2 and x0 - 20 <= (w['bbox_px'][0] + w['bbox_px'][2]) / 2 <= x1 + 20]


def _col_words(table, col, words):
    cells = [c for c in table.cells if c.c == col and c.cs == 1]
    if not cells or not words:
        return []
    lo, hi = min(c.bbox_px[0] for c in cells), max(c.bbox_px[2] for c in cells)
    top = max((w['bbox_px'][3] for w in words), default=0)
    return [w for w in words if lo - 10 <= (w['bbox_px'][0] + w['bbox_px'][2]) / 2 <= hi + 10
            and w['bbox_px'][3] >= top - 60]


def solve_list(pt, table, req):
    """Read a whole door/window schedule as a table: per type width, height, quantity, total.

    Nothing is guessed: a missing or non-integer quantity, a duplicated type or a
    table that does not name its kind defers to the other routes.
    """
    for start in range(0, min(table.nrows, 6)):
        roles, above = {}, []
        if start == 0:
            above = _words_above(pt, table)  # header printed above the ruled grid
            if not above:
                continue
        for col in range(table.ncols):
            texts = [_norm(c.text) for r in range(start) if (c := table.cell_at(r, col)) is not None and c.text.strip()]
            texts += [_norm(w['text']) for w in _col_words(table, col, above)]
            for role, rx in _LIST_ROLES:
                if role not in roles and any(re.search(rx, t) for t in texts):
                    roles[role] = col
        if not {'width', 'height', 'mark'} <= roles.keys() or len({roles[k] for k in roles}) != len(roles):
            continue
        first = table.cell_at(start, roles['mark'])
        if first is None or not first.text.strip() or _norm(first.text) in {'TOTAL', 'TOTALS'}:
            continue
        body = ' '.join(c.text for c in table.cells)
        heading = table.title + ' ' + ' '.join(c.text for c in table.cells if c.r < start)
        heading += ' ' + ' '.join(w['text'] for w in above)
        if not re.search(r'\b' + req.kind + r's?\b', heading + ' ' + body, re.I):
            return None
        rows, seen = [], set()
        for row in range(start, table.nrows):
            mark = table.cell_at(row, roles['mark'])
            text = mark.text.strip() if mark is not None else ''
            if not text:
                if any(c.text.strip() for c in table.cells if c.r == row):
                    return None
                continue
            if _norm(text) in {'TOTAL', 'TOTALS', 'GRAND TOTAL'}:
                continue
            if _norm(text) in seen:
                return None
            seen.add(_norm(text))
            cells = {k: table.cell_at(row, col) for k, col in roles.items()}
            w, h = (cells[k].text.strip() if cells[k] is not None else '' for k in ('width', 'height'))
            if not w or not h:
                return None
            if 'qty' in roles:
                q = _int_qty(cells['qty'].text if cells['qty'] is not None else '')
                if q is None:
                    return None
            else:
                q = 1
            rows.append((text, w, h, q, row))
        if not rows:
            return None
        total = sum(r[3] for r in rows)
        word = req.kind.capitalize()
        by = f', in {len(rows)} types' if 'qty' in roles else ''
        lines = [f'**{total} {req.kind}s** are listed on this schedule{by}.', '',
                 f'| {word} type | Width | Height | Quantity |', '|---|---|---|---|']
        lines += [f'| {m} | {w} | {h} | {q} |' for m, w, h, q, _ in rows]
        lines.append(f'| **Grand total** | | | **{total}** |')
        if 'qty' not in roles:
            lines += ['', 'The schedule lists one row per opening, so each row counts as one.']
        spans = [Span(pt, ' | '.join(c.text for c in table.cells if c.text), table.bbox_px)]
        spans += [Span(pt, ' | '.join(c.text for c in table.cells if c.r == r[4] and c.text), table.row_bbox(r[4])) for r in rows]
        return total, 'count', '\n'.join(lines), spans
    return None


def solve_table(pt, table, req):
    if req.op == 'list':
        return solve_list(pt, table, req)
    parsed = _records(table, req)
    if parsed is None:
        return None
    cols, records = parsed
    selected = []
    if req.op == 'walls':
        # Unknown finishes cannot be counted as definite nonmatches. Otherwise
        # an unread W7 cell would produce a confident undercount.
        if any(not re.fullmatch(r'[A-Z]+\d+[A-Z]?|-|N/A|NONE', r[1][d].upper())
               for r in records for d in 'NESW'):
            return None
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
        candidates = records if req.op == 'largest' else [r for r in records if r[0] == req.target]
        if not candidates:
            return None
        areas = [(r, _area(r[1].get('area', ''), header)) for r in candidates]
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
            if sheet and not re.search(r'\bpage\s+\d+\b', question, re.I):
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
