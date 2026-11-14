"""Source-linked scale calculations. JSON and arithmetic only; no OCR/model calls.

Stored scales remain authoritative for already measured quantities. New readings
are comparisons, never silently applied to an answer computed at another scale.
A door icon is a proxy for a leaf width, not a measured physical door.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import median

PRIOR_M = 0.9
PRIOR_WHY = ('Assumed 0.9 m door leaf for an approximate scale; icon boxes include swing/segmentation error. '
             'The file does not establish actual door widths or their physical variation.')


def positive(value):
    try:
        return float(value) if not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)
            and box[2] > box[0] and box[3] > box[1])


def source(doc_id, page, **extra):
    return {'doc_id': doc_id, 'page': page, **extra}


def operand(name, value, unit, src):
    return {'name': name, 'value': value, 'unit': unit, 'source': src}


def candidate(method, value, formula, inputs, note='', **extra):
    return {'method': method, 'm_per_px': value, 'formula': formula, 'inputs': inputs, 'note': note, **extra}


def doors(pm):
    samples = []
    for i, it in enumerate(pm.get('items') or []):
        box = it.get('bbox_px')
        if it.get('kind') != 'door' or not valid_box(box):
            continue
        width = max(box[2] - box[0], box[3] - box[1])
        samples.append(operand('door icon width', width, 'px', {
            'item_id': it.get('item_id'), 'bbox': box, 'file': f"planmap-{pm.get('page', 1)}.json",
            'pointer': f'/items/{i}/bbox_px'}))
    if len(samples) < 2:
        return None
    width = median(i['value'] for i in samples)
    value = PRIOR_M / width
    vals = [PRIOR_M / i['value'] for i in samples]
    return candidate('door-prior', value, 'scale = assumed door width / median(door icon widths)',
                     [operand('assumed door width', PRIOR_M, 'm', {'assumption': PRIOR_WHY})] + samples,
                     PRIOR_WHY, sample_count=len(samples), median_width_px=width,
                     spread_pct=max(abs(v / value - 1) for v in vals) * 100,
                     uncertainty_known=False, independent=False)


def printed_length(text, unit=None):
    """Length with explicit units only. A bare '900' needs a recorded unit."""
    s = str(text).strip().lower().replace(',', '.').replace('′', "'").replace('’', "'").replace('″', '"')
    feet = re.fullmatch(r'''\s*(\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot)\s*(?:-?\s*(\d+(?:\.\d+)?)\s*(?:"|in))?\s*''', s)
    if feet:
        return (float(feet[1]) + float(feet[2] or 0) / 12) * 0.3048
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch|inches|ft|feet|foot|metres?|meters?)?', s)
    if not m:
        return None
    factor = {'mm': .001, 'cm': .01, 'm': 1, 'in': .0254, 'inch': .0254, 'inches': .0254,
              'ft': .3048, 'feet': .3048, 'foot': .3048, 'meter': 1, 'meters': 1, 'metre': 1, 'metres': 1}.get(m[2] or unit)
    return positive(float(m[1]) * factor) if factor else None


def dimensions(pm):
    """Only an explicit association between a dimension label and its line is usable.

    Hook for non-PDF producers: dimension item props.dimension_line_px = [[x,y],
    [x,y]], props.printed_length = original string, props.dimension_unit optional
    for a bare string. The item's bbox locates the printed label, not the line.
    """
    out = []
    for n, it in enumerate(pm.get('items') or []):
        if it.get('kind') != 'dimension':
            continue
        props = it.get('props') or {}
        pts = props.get('dimension_line_px')
        if not isinstance(pts, list) or len(pts) != 2 or not all(isinstance(p, list) and len(p) == 2 for p in pts):
            continue
        try:
            px = positive(math.dist(*pts))
        except (TypeError, ValueError):
            continue
        length = printed_length(props.get('printed_length', it.get('label', '')), props.get('dimension_unit'))
        if not px or not length or not valid_box(it.get('bbox_px')):
            continue
        src = {'item_id': it.get('item_id'), 'bbox': it['bbox_px'], 'file': f"planmap-{pm.get('page', 1)}.json", 'pointer': f'/items/{n}'}
        out.append(candidate('dimension', length / px, 'scale = printed length in metres / dimension line length in pixels', [
            operand('printed length', length, 'm', {**src, 'text': props.get('printed_length', it.get('label')), 'conversion': 'mm × 0.001; cm × 0.01; in × 0.0254; ft × 0.3048; m × 1'}),
            operand('matched dimension line length', px, 'px', {**src, 'endpoints_px': pts})],
            'The dimension string is explicitly linked to these endpoints.'))
    return out


def page_words(folder, page):
    out = []
    for name in (f'text-{page}.json', f'scale-ocr-{page}.json'):
        raw = read_json(folder / name)
        words = raw.get('words', []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        for i, w in enumerate(words):
            box = w.get('bbox_px', w.get('bbox'))
            if valid_box(box):
                out.append({**w, 'bbox_px': box, '_source': {'file': name, 'pointer': f'/words/{i}' if isinstance(raw, dict) else f'/{i}'}})
    return out


def _crop(folder, page, src):
    box = src.get('bbox')
    if not valid_box(box) or src.get('assumption'):
        return
    try:
        from PIL import Image
        with Image.open(folder / f'page-{page}.png') as im:
            # Stable content-addressed names; create only, never overwrite shared artifacts.
            key = json.dumps([page, box, im.size, (folder / f'page-{page}.png').stat().st_mtime_ns])
            name = f'scale-{page}-{hashlib.sha256(key.encode()).hexdigest()[:20]}.png'
            path = folder / 'evidence' / name
            if not path.exists():
                x0, y0, x1, y1 = box
                rect = (max(0, math.floor(x0) - 8), max(0, math.floor(y0) - 8),
                        min(im.width, math.ceil(x1) + 8), min(im.height, math.ceil(y1) + 8))
                if rect[2] <= rect[0] or rect[3] <= rect[1]:
                    return
                crop = im.crop(rect).convert('RGB')
                crop.thumbnail((640, 320))
                path.parent.mkdir(exist_ok=True)
                try:
                    with path.open('xb') as f:
                        crop.save(f, format='PNG')
                except FileExistsError:
                    pass
            src['crop'] = f'{folder.name}/evidence/{name}'
    except (OSError, ValueError, ImportError):
        return


def enrich(pm, folder=None, *, effective_scale=None, save_crops=False):
    """Return a scale copy with a reproducible proof, without changing its value.

    Missing provenance is reported explicitly. Comparisons are an observed spread,
    not a calibrated confidence interval or a bound on construction tolerances.
    """
    sc = copy.deepcopy(effective_scale if effective_scale is not None else pm.get('scale') or {})
    page, did = pm.get('page', 1), pm.get('doc_id', Path(folder).name if folder else '')
    readings = copy.deepcopy(sc.get('candidates') or [])
    if sc.get('derivation'):
        readings.append({'method': sc.get('method'), 'm_per_px': sc.get('m_per_px'), **copy.deepcopy(sc['derivation'])})
    readings += dimensions(pm)
    prior = doors(pm)
    if prior:
        readings.append(prior)
    if folder:
        folder = Path(folder)
        from engine import scale_text
        words = page_words(folder, page)
        pages = read_json(folder / 'pages.json')
        entry = next((p for p in pages.get('pages', []) if p.get('page') == page), {}) if isinstance(pages, dict) else {}
        text = read_json(folder / f'text-{page}.json')
        dpi = (text.get('dpi') if isinstance(text, dict) else None) or entry.get('dpi')
        readings += scale_text.evidenced_candidates(words, (pm.get('image') or {}).get('w', 0),
                                                   (pm.get('image') or {}).get('h', 0), dpi,
                                                   dpi_source={'file': f'text-{page}.json' if isinstance(text, dict) and text.get('dpi') else 'pages.json',
                                                               'pointer': '/dpi' if isinstance(text, dict) and text.get('dpi') else f"/pages/{next((i for i, p in enumerate(pages.get('pages', [])) if p.get('page') == page), 0)}"})
        # IFC plans already project geometry in metres; do not multiply source units again.
        ppm = positive((pm.get('projection') or {}).get('ppm'))
        if ppm and sc.get('method') == 'ifc':
            readings.append(candidate('ifc', 1 / ppm, 'scale = 1 / rendered pixels per metre', [operand(
                'rendered pixels per metre', ppm, 'px/m', {'file': f'planmap-{page}.json', 'pointer': '/projection/ppm'})],
                'IFC geometry has already been converted to metres. Source unit conversion is recorded separately.'))
    unique, seen = [], set()
    for r in readings:
        if not positive(r.get('m_per_px')) or not r.get('inputs'):
            continue
        key = json.dumps([r.get('method'), r['m_per_px'], r['inputs']], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        for inp in r['inputs']:
            if inp.get('source', {}).get('file') == 'planmap-page.json':
                inp['source']['file'] = f'planmap-{page}.json'
            inp['source'] = source(did, page, **{k: v for k, v in inp.get('source', {}).items() if k not in ('doc_id', 'page')})
        unique.append(r)
    selected = positive(sc.get('m_per_px'))
    method = sc.get('method', 'none')
    checks, deltas = [], []
    for r in unique:
        if selected:
            diff = abs(r['m_per_px'] / selected - 1) * 100
            checks.append({'method': r['method'], 'value': r['m_per_px'], 'unit': 'm/px', 'diff_pct': diff,
                           'agrees': diff <= 1e-7, 'note': 'Equality at recorded precision; no agreement tolerance or accuracy guarantee is assumed.',
                           'independent': r.get('independent', r['method'] != method)})
            if r['method'] != 'door-prior':
                deltas.append(diff)
    measured_spread = max(deltas) if deltas else None
    if measured_spread is not None and measured_spread > 1e-7:
        sc['spread_pct'] = max(sc.get('spread_pct') or 0, measured_spread)
    # Never assign a numeric physical uncertainty from icon scatter.
    matched = [r for r in unique if r['method'] == method and selected and abs(r['m_per_px'] / selected - 1) < 1e-7]
    steps = []
    door_crops = 0
    for n, r in enumerate(unique):
        inputs = r['inputs']
        if save_crops and folder:
            for inp in inputs:
                if r['method'] == 'door-prior' and inp['unit'] == 'px':
                    if door_crops >= 3:
                        continue
                    door_crops += 1
                _crop(folder, page, inp['source'])
        steps.append({'id': f'scale-{page}-{n + 1}', 'label': r['method'].replace('-', ' '), 'expr': r['formula'],
                      'value': r['m_per_px'], 'unit': 'm/px', 'inputs': inputs, 'note': r.get('note', ''),
                      **{k: r[k] for k in ('sample_count', 'median_width_px', 'spread_pct', 'uncertainty_known') if k in r}})
    note = sc.get('selection_rule') or ('Retain the scale used to compute the source quantities; comparisons do not rescale an existing answer.')
    if not matched:
        note += ' The stored scale has no matching source derivation; its original inputs are unavailable.'
    sc['proof'] = {'formula': 'drawing distance in metres = pixel distance × scale', 'steps': steps, 'rows': [],
                   'result': {'value': selected, 'unit': 'm/px', 'rounded_as': 'stored precision'}, 'checks': checks,
                   'selection_rule': note, 'derivation_complete': bool(matched), 'method_spread_pct': measured_spread,
                   'margin': {'value': None, 'unit': 'm/px', 'pct': None,
                              'why': 'Method differences are observed spread only; physical scale error is not bounded.', 'sources': []}}
    return sc
