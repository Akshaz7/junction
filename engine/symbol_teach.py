"""User-taught symbol evidence. No model calls and no source drawing writes."""
from __future__ import annotations

import re
import unicodedata
import uuid
from collections import Counter
from functools import lru_cache
from threading import Lock
from pathlib import Path


_MATCH_LOCK = Lock()


@lru_cache(maxsize=16)
def _match(path, mtime, box, page, max_matches):
    from engine.symbols import find_similar as matcher
    # One page matcher at a time keeps dense sheets within the host's memory budget.
    with _MATCH_LOCK:
        return matcher(path, box, page=page, max_matches=max_matches)


def find_similar(image_path, box, page=0, max_matches=500):
    p = Path(image_path)
    return _match(str(p), p.stat().st_mtime_ns, tuple(box), page, max_matches)


def room_for(box, rooms):
    """Use an enclosing room polygon, never guess the nearest text label."""
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for room in rooms:
        poly = room.get('polygon_px') or []
        inside = False
        if len(poly) < 3:
            continue
        j = len(poly) - 1
        for i, (xi, yi) in enumerate(poly):
            xj, yj = poly[j]
            if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi:
                inside = not inside
            j = i
        if inside:
            return room.get('label') or room.get('item_id') or 'Unnamed room'
    return None


def summary(matches):
    active = [m for m in matches if m['status'] != 'rejected']
    return {'found': len(active), 'confirmed': sum(m['status'] == 'confirmed' for m in active),
            'pending': sum(m['status'] == 'pending' for m in active),
            'rejected': len(matches) - len(active),
            'rooms': dict(Counter(m.get('room') or 'Room unknown' for m in active))}


def _tokens(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return {w[:-1] if w.endswith('s') and len(w) > 3 else w for w in re.findall(r'[^\W_]+', text)}


def taught_answer(question, doc_ids, symbols):
    """Exact taught-name match only; never combine overlapping classes or imply completeness."""
    if not re.search(r'\b(how many|count|number of)\b', question, re.I):
        return None
    qt = _tokens(question)
    chosen = [s for s in symbols if s['doc_id'] in doc_ids and _tokens(s['name']) and _tokens(s['name']) <= qt]
    if not chosen:
        return None
    # Ambiguous/overlapping teachings must not be silently added together.
    names = {s['name'].casefold() for s in chosen}
    if len(names) != 1 or len({s['doc_id'] for s in chosen}) != 1:
        return None
    name = chosen[0]['name']
    matches = [(s, m) for s in chosen for m in s['matches'] if m['status'] != 'rejected']
    n = len(matches)
    confirmed = sum(m['status'] == 'confirmed' for _, m in matches)
    pending = n - confirmed
    all_checked = n > 0 and pending == 0
    # Percent describes review coverage, not a calibrated probability of exhaustive detection.
    pct = round(100 * confirmed / n) if n else 0
    boxes, cites = [], []
    for i, (s, m) in enumerate(matches, 1):
        item = f"taught-{s['id']}-{m['id']}"
        boxes.append({'item_id': item, 'page': s['page'], 'bbox_px': m['bbox'], 'label': str(i)})
        cites.append({'n': i, 'doc_id': s['doc_id'], 'page': s['page'], 'kind': 'region',
                      'bbox_px': m['bbox'], 'item_ids': [item], 'quote': f"{name}: {m['status']}"})
    text = f'**Found {n} boxes labelled “{name}”.**' + (' [1]' if cites else '')
    text += f'\n\n- Checked: {confirmed} confirmed by you; {pending} auto-matched, not yet confirmed.'
    text += '\n- This is the saved match set; symbols elsewhere on the drawing may have been missed.'
    return {'answer_id': uuid.uuid4().hex, 'question': question, 'doc_ids': list(doc_ids),
            'answer': {'text_md': text, 'value': n, 'unit': 'count', 'confidence': pct/100, 'abstained': False},
            'citations': cites, 'evidence': {'boxes': boxes, 'scene': {'doc_id': chosen[0]['doc_id'], 'highlight_item_ids': [], 'camera_target_item_id': None}},
            'trace': [{'step': 'taught_symbols', 'detail': f'{confirmed} user-confirmed; {pending} pending; no model call', 'ms': 0, 'model': None, 'cost_usd': 0}],
            'route': 'index', 'cost': {'usd_total': 0, 'calls': []}, 'latency_ms': 0,
            'reasoning': {'steps': [
                {'kind': 'found', 'title': 'Found', 'text': f'{n} saved boxes, with numbered drawing evidence', 'cite': 1 if cites else None},
                {'kind': 'checked', 'title': 'Checked', 'text': f'{confirmed} confirmed by you; {pending} not yet confirmed', 'ok': True if all_checked else None}],
                'confidence': {'label': 'Cross-checked' if all_checked else 'Estimate', 'pct': pct,
                               'reason': f'{pct}% of saved candidates reviewed and confirmed. Review coverage, not detection accuracy.',
                               'improve': 'Check for missed symbols outside the saved boxes.'}}}
