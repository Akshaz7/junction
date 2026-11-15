"""Source text collection and conservative literal matching for descriptive claims."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

QUOTES = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|(?<!\w)\'([^\'\n]+)\'|`([^`\n]+)`')


def norm(text):
    text = unicodedata.normalize('NFKD', str(text))
    return ' '.join(re.findall(r'[^\W_]+', ''.join(c for c in text if not unicodedata.combining(c)).casefold()))


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def collect(doc_id, root):
    """Read sidecars without invoking ingestion or rewriting shared artifacts."""
    out = {}
    directory = Path(root) / doc_id

    def add(text, page, bbox, source, item_id=None):
        if not isinstance(text, (str, int, float)) or not str(text).strip():
            return
        key = f'src-{len(out)}'
        out[key] = {'doc_id': doc_id, 'page': page, 'item_id': item_id or key,
                    'bbox': bbox, 'crop': None, 'text': str(text), 'origin': source}

    for path in sorted(set(directory.glob('rtext-*.json')) | set(directory.glob('text-*.json')) | {directory / 'text.json'}):
        data = read(path)
        number = re.search(r'-(\d+)\.json$', path.name)
        page = data.get('page', int(number[1]) if number else 1) if isinstance(data, dict) else 1
        if isinstance(data, dict):
            rows = data.get('words') or data.get('items') or data.get('lines') or data.get('texts') or []
        else:
            rows = data if isinstance(data, list) else []
        for row in rows:
            if isinstance(row, dict):
                add(row.get('text') or row.get('label'), row.get('page', page), row.get('bbox_px') or row.get('bbox'), path.name)
        if isinstance(data, dict) and isinstance(data.get('text'), str):
            add(data['text'], page, data.get('bbox_px'), path.name)
    # Title-block fields can be nested, or carry their own pixel boxes.
    def fields(value, page=1, bbox=None):
        if isinstance(value, dict):
            bbox = value.get('bbox_px') or bbox
            for key, child in value.items():
                if key not in ('bbox_px', 'bbox', 'page', 'confidence', 'conf'):
                    fields(child, page, bbox)
        elif isinstance(value, list):
            for child in value:
                fields(child, page, bbox)
        else:
            add(value, page, bbox, 'title-block')
    for path in sorted(directory.glob('planmap-[0-9]*.json')):
        data = read(path)
        if not isinstance(data, dict):
            continue
        page = data.get('page', 1)
        for row in data.get('items', []):
            for field in ('label', 'name', 'text'):
                add(row.get(field), page, row.get('bbox_px'), 'planmap', row.get('item_id'))
        for key in ('title_block', 'titleblock', 'title_block_fields'):
            fields(data.get(key), page)
    for name in ('title-block.json', 'titleblock.json'):
        data = read(directory / name)
        if data:
            fields(data)
    metadata = read(directory / 'doc.json')
    if isinstance(metadata, dict):
        for key in ('title_block', 'titleblock', 'title_block_fields'):
            fields(metadata.get(key))
    return out


def terms(text, vocabulary):
    """Explicit quoted phrases, abbreviations and known source-language terms."""
    quoted = QUOTES.findall(text)
    out = [next(s for s in group if s).strip() for group in quoted]
    out += re.findall(r'\b[A-ZÄÖÅÜ][A-ZÄÖÅÜ0-9-]{1,15}\b', text)
    normalized = f' {norm(text)} '
    out += [key for key in vocabulary if len(key) > 2 and f' {norm(key)} ' in normalized]
    return list(dict.fromkeys(out))


def match(term, evidence):
    """Ignore case/accents; join OCR splits only within an item or nearby boxes.

    Short abbreviations require exact tokens: ET must never match kitchenette.
    No edit-distance substitutions are allowed for room labels.
    """
    query = norm(term)
    if not query:
        return []
    qt = query.split()
    for key, row in evidence.items():
        source = norm(row['text'])
        if f' {query} ' in f' {source} ':
            return [key]
        st = source.split()
        if len(query.replace(' ', '')) >= 5 and any(c.isalpha() for c in query):
            for start in range(len(st)):
                for end in range(start + 1, min(len(st), start + len(qt) + 3) + 1):
                    if ''.join(st[start:end]) == ''.join(qt):
                        return [key]
    # OCR may split one printed word into several word items. Require spatial
    # neighbours on the same page; never concatenate arbitrary document text.
    candidates = [(key, row) for key, row in evidence.items() if row.get('bbox') and norm(row['text'])]
    if len(''.join(qt)) < 5 or not any(c.isalpha() for c in query):
        return []
    target = ''.join(qt)
    for key, row in candidates:
        prefix = norm(row['text']).replace(' ', '')
        if not target.startswith(prefix):
            continue
        ids, current, previous = [key], prefix, row
        for _ in range(5):
            b = previous['bbox']
            nearby = []
            for other, nxt in candidates:
                part = norm(nxt['text']).replace(' ', '')
                if other in ids or nxt['page'] != row['page'] or not target.startswith(current + part):
                    continue
                n = nxt['bbox']
                h = max(b[3] - b[1], n[3] - n[1], 1)
                horizontal = abs((b[1] + b[3] - n[1] - n[3]) / 2) <= h * .6 and -h * .3 <= n[0] - b[2] <= h * 2
                vertical = abs((b[0] + b[2] - n[0] - n[2]) / 2) <= max(b[2]-b[0], n[2]-n[0], 1) and -h * .3 <= n[1] - b[3] <= h
                if horizontal or vertical:
                    nearby.append((other, nxt, part))
            if not nearby:
                break
            other, previous, part = nearby[0]
            ids.append(other)
            current += part
            if current == target:
                return ids
    return []


def recover_rotated_labels(doc, root, missing):
    """Bounded OCR for small rotated labels missed by full-page OCR.

    Read room crops at higher resolution in both orientations, then map all
    detected boxes back to original page pixels. This does not create labels
    from room types or the model's vocabulary.
    """
    if not doc or not missing:
        return {}
    meta = read(Path(root) / doc.doc_id / 'doc.json')
    if meta.get('kind') != 'raster':
        return {}
    try:
        import cv2
        from engine.reader.text import _ocr
        out, images = {}, {}
        rooms = [item for item in doc.items if item.kind == 'room' and item.bbox_px][:12]
        for item in rooms:
            if item.page not in images:
                images[item.page] = cv2.imread(str(Path(root) / doc.doc_id / f'page-{item.page}.png'))
            image = images[item.page]
            if image is None:
                continue
            x0, y0, x1, y1 = [int(v) for v in item.bbox_px]
            x0, y0 = max(0, x0), max(0, y0)
            crop = image[y0:y1, x0:x1]
            if not crop.size:
                continue
            h, w = crop.shape[:2]
            factor = min(3., 1800 / max(h, w))
            for rotation in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
                rotated = crop if rotation is None else cv2.rotate(crop, rotation)
                scaled = cv2.resize(rotated, None, fx=factor, fy=factor)
                detections, _ = _ocr()(scaled, use_cls=False)
                for box, text, confidence in detections or []:
                    if confidence < .8:
                        continue
                    points = []
                    for x, y in box:
                        x, y = x / factor, y / factor
                        if rotation == cv2.ROTATE_90_CLOCKWISE:
                            x, y = y, h - x
                        elif rotation == cv2.ROTATE_90_COUNTERCLOCKWISE:
                            x, y = w - y, x
                        points.append((x + x0, y + y0))
                    key = f'rot-{len(out)}'
                    out[key] = {'doc_id': doc.doc_id, 'page': item.page, 'item_id': key,
                                'bbox': [min(x for x,y in points), min(y for x,y in points), max(x for x,y in points), max(y for x,y in points)],
                                'crop': None, 'text': text, 'origin': 'rotated-ocr'}
            if all(match(term, out) for term in missing):
                break
        return out
    except (ImportError, OSError, ValueError):
        return {}
