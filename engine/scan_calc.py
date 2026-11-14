"""Technical, source-linked scan inventory. No inference or artifact writes.

Inventory is context, not the selected answer scope. Saved scores describe
retained items, never all pre-filter proposals or calibrated answer accuracy.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from pathlib import Path

from engine.calc import input_value, number, step, step_source, validate
from engine.scale_proof import enrich, read_json


def _ref(did, page, artifact, field='', item=None):
    return {'kind': 'document' if item is None else 'element', 'doc_id': did, 'page': page,
            'artifact': artifact, 'field': field, 'item_id': (item or {}).get('item_id'),
            'bbox': (item or {}).get('bbox_px')}


def _observation(sid, label, value, unit, ref, note='', expr='recorded source value'):
    return step(sid, label, expr, value, unit, [input_value(label, value, unit, ref)], note, 'source')


def _scale_steps(proof, prefix, did, page):
    """Replay the door-prior derivation; retain other methods' original proof."""
    out = []
    for index, original in enumerate(proof.get('steps', [])):
        s = copy.deepcopy(original)
        s['id'] = f'{prefix}-scale-{index}'
        for inp in s['inputs']:
            src = inp['source']
            if 'assumption' in src:
                src.update(kind='assumption', text=src['assumption'])
            elif 'definition' in src:
                src.update(kind='conversion', text=src['definition'])
            elif src.get('file'):
                src.update(kind='element' if src.get('item_id') else 'document', artifact=src['file'], field=src.get('pointer', ''))
            else:
                src.update(kind='measurement', record={'doc_id': did, 'input': copy.deepcopy(inp)},
                           text='Recorded scale operand: ' + inp['name'])
        if original.get('median_width_px') is not None:
            s['operation'] = 'door_scale'
            out.append(s)
            widths = [i for i in s['inputs'] if i['unit'] == 'px']
            out.append(step(s['id'] + '-median', 'Median door icon width', 'median(all door icon widths)',
                            original['median_width_px'], 'px', widths, operation='median'))
            if number(original.get('spread_pct')):
                out.append(step(s['id'] + '-spread', 'Door-prior scale spread',
                                'max(abs((assumed width / icon width) / median-derived scale − 1)) × 100',
                                original['spread_pct'], '%', s['inputs'],
                                'Observed proxy variation; actual door widths and physical error remain unknown.', 'door_scale_spread'))
        else:
            operation = {'ratio dpi': 'ratio_dpi', 'ratio sheet': 'ratio_sheet', 'dimension': 'dimension_scale',
                         'scalebar': 'bar_scale', 'scale bar': 'bar_scale', 'ifc': 'inverse'}.get(s['label'])
            if operation:
                s['operation'] = operation
                out.append(s)
            elif s['label'] in ('dxf units', 'dxf_units_fit'):
                factor = next((i for i in s['inputs'] if i['name'] == 'metres per drawing unit'), None)
                pixels = next((i for i in s['inputs'] if i['name'] == 'registered signed pixels per drawing unit'), None)
                if factor and pixels:
                    s['inputs'] = [factor, pixels]
                    s['operation'] = 'dxf_scale'
                    out.append(s)
    return out


def _inventory(did, page, pm, folder, filename=None):
    filename = filename or f'planmap-{page}.json'
    prefix = f'scan-{did}-{filename}'
    image, provenance = pm.get('image') or {}, pm.get('provenance') or {}
    ref = _ref(did, page, filename)
    out, rows, unavailable = [], [], []
    for key, label in [('w', 'Page image width'), ('h', 'Page image height')]:
        if number(image.get(key)):
            out.append(_observation(f'{prefix}-{key}', label, image[key], 'px', {**ref, 'field': f'image.{key}'}))
    embedded_dpi = None
    try:
        from PIL import Image
        with Image.open(folder / f'page-{page}.png') as actual:
            actual_size = actual.size
            dpi_pair = actual.info.get('dpi')
            if isinstance(dpi_pair, (list, tuple)) and len(dpi_pair) == 2 and all(number(v) and v > 0 for v in dpi_pair) and math.isclose(dpi_pair[0], dpi_pair[1], rel_tol=1e-6):
                embedded_dpi = dpi_pair[0]
        for key, value in zip(('width', 'height'), actual_size):
            out.append(_observation(f'{prefix}-actual-{key}', 'Actual page image ' + key, value, 'px',
                                    _ref(did, page, f'page-{page}.png', 'image header ' + key)))
        if image.get('w') and image.get('h') and actual_size != (image['w'], image['h']):
            unavailable.append('The saved plan-map coordinate size differs from the current image; box alignment and scale require checking. No coordinate correction was inferred.')
    except (ImportError, OSError, ValueError):
        unavailable.append('The current page image header is unavailable; dimensions above come from the saved plan map.')
    pages = read_json(folder / 'pages.json')
    page_meta = next((p for p in pages.get('pages', []) if p.get('page') == page), {}) if isinstance(pages, dict) else {}
    dpi = image.get('dpi') or page_meta.get('dpi') or embedded_dpi
    if number(dpi):
        out.append(_observation(f'{prefix}-dpi', 'Recorded page resolution', dpi, 'dpi',
                                ref if image.get('dpi') else _ref(did, page, 'pages.json', f'pages[page={page}].dpi') if page_meta.get('dpi') else _ref(did, page, f'page-{page}.png', 'embedded DPI metadata'),
                                'DPI is metadata; it establishes physical scale only with a source scale ratio.'))
    else:
        unavailable.append('Image DPI was not recorded; pixel size alone does not establish real-world size.')
    groups = defaultdict(list)
    for item in pm.get('items', []):
        if not isinstance(item, dict):
            continue
        groups[(str(item.get('source') or 'unknown'), str(item.get('kind') or 'other'))].append(item)
        sref = _ref(did, page, filename, 'items', item)
        rows.append({'item_id': item.get('item_id'), 'label': item.get('label') or item.get('kind'),
                     'values': {'kind': item.get('kind'), 'origin': item.get('source'), 'score': item.get('conf'),
                                'inventory_artifact': filename,
                                **{k: v for k, v in (item.get('props') or {}).items() if number(v)}}, 'source': sref})
    for (origin, kind), items in sorted(groups.items()):
        sid = f'{prefix}-{origin}-{kind}'
        operands = [input_value('retained ' + kind, 1, 'count', _ref(did, page, filename, 'items', i)) for i in items]
        out.append(step(sid, f'Retained {kind} items ({origin})', 'Σ(1 per saved item)', len(items), 'count', operands,
                        'Saved page inventory before this question’s filters. Model: ' + str((provenance.get('models') or {}).get(origin, 'not recorded')), 'sum'))
        scores = [input_value('retained item score', i['conf'], 'score', _ref(did, page, filename, 'conf', i)) for i in items if number(i.get('conf'))]
        if scores:
            from statistics import median
            for operation, fn in [('min', min), ('median', median)]:
                out.append(step(sid + '-' + operation, f'{kind}: {operation} retained score ({origin})',
                                operation + '(retained item scores)', fn(i['value'] for i in scores), 'score', scores,
                                'Model score on retained detections; not the probability that the answer is correct.', operation))
    for name, value in sorted((provenance.get('params') or {}).items()):
        if number(value):
            out.append(_observation(f'{prefix}-param-{name}', 'Recorded extraction parameter: ' + name, value,
                                    'px' if name.endswith(('_size', '_px')) else 'fraction' if name.endswith('_frac') else 'parameter',
                                    {**ref, 'field': 'provenance.params.' + name},
                                    'Recorded at extraction time; a component-area parameter is not a detection-score threshold.'))
    if number((provenance.get('params') or {}).get('det_min_px')) and number((provenance.get('params') or {}).get('det_size')) and image.get('w') and image.get('h'):
        p = provenance['params']; threshold = p['det_min_px'] * (max(image['w'], image['h']) / p['det_size']) ** 2
        out.append(step(prefix + '-component-area', 'Detector connected-component area floor',
                        'det_min_px × (max(image width, image height) / det_size)²', threshold, 'px2',
                        [input_value(n, v, u, {**ref, 'field': f}) for n, v, u, f in [
                            ('component area at inference resolution', p['det_min_px'], 'px2', 'provenance.params.det_min_px'),
                            ('longest image side', max(image['w'], image['h']), 'px', 'image'),
                            ('inference side', p['det_size'], 'px', 'provenance.params.det_size')]], operation='component_area'))
    extraction = provenance.get('extraction') or {}
    for name in ['score_threshold', 'tiles', 'raw_count', 'after_threshold', 'dedupe_merged', 'nms_iou']:
        value = extraction.get(name)
        if number(value):
            out.append(_observation(f'{prefix}-extract-{name}', 'Recorded extraction: ' + name, value,
                                    'score' if 'threshold' in name or 'iou' in name else 'count', {**ref, 'field': 'provenance.extraction.' + name}))
        elif name in ('score_threshold', 'tiles', 'dedupe_merged'):
            if name != 'score_threshold' or not extraction.get('classes'):
                unavailable.append(f'{name}: not recorded for this page; cannot reconstruct the pre-filter detector run from retained items.')
    for kind, stats in sorted((extraction.get('classes') or {}).items()):
        for name, value in stats.items():
            if number(value):
                out.append(_observation(f'{prefix}-extract-{kind}-{name}', f'{extraction.get("label", "Detector")} {kind}: {name}', value,
                                        'score' if 'score' in name else 'count',
                                        {**ref, 'field': f'provenance.extraction.classes.{kind}.{name}'},
                                        extraction.get('raw_scope', '') + '. ' + extraction.get('note', 'Recorded extraction observations.')))
    for name, value in (extraction.get('dedupe') or {}).items():
        if number(value):
            out.append(_observation(f'{prefix}-dedupe-{name}', 'Dedupe parameter: ' + name, value, 'fraction',
                                    {**ref, 'field': 'provenance.extraction.dedupe.' + name}))
    proof = enrich({**pm, 'doc_id': did, 'page': page}, folder, save_crops=False)['proof']
    out.extend(_scale_steps(proof, prefix, did, page))
    chosen = proof['result']['value']
    if number(chosen):
        out.append(_observation(prefix + '-chosen-scale', 'Stored scale used for this page', chosen, 'm/px',
                                {**ref, 'field': 'scale.m_per_px'}, proof['selection_rule']))
    else:
        unavailable.append('No physical scale is established for this page; areas and lengths in metres cannot be inferred.')
    for index, item in enumerate(pm.get('items', [])):
        if item.get('kind') not in ('room', 'space', 'wall'):
            continue
        sref = _ref(did, page, filename, 'polygon_px', item)
        poly = item.get('polygon_px')
        sid = f'{prefix}-geometry-{index}'
        props = item.get('props') or {}
        if item.get('kind') == 'wall' and number(props.get('length_px')):
            out.append(_observation(sid + '-length-pixels', 'Wall segment length in pixels', props['length_px'], 'px',
                                    {**sref, 'field': 'props.length_px'}, 'Mask bar length, not a surveyed wall centreline.'))
            if number(chosen):
                out.append(step(sid + '-length', 'Scale wall segment', 'segment pixels × stored scale', props['length_px'] * chosen, 'm',
                                [input_value('segment pixels', props['length_px'], 'px', step_source(sid + '-length-pixels')),
                                 input_value('stored scale', chosen, 'm/px', {**ref, 'field': 'scale.m_per_px'})],
                                'Uses the stored page scale; scale uncertainty remains separate.', 'multiply'))
        elif isinstance(poly, list) and len(poly) >= 3 and all(isinstance(p, (list, tuple)) and len(p) == 2 and all(number(v) for v in p) for p in poly):
            from engine.reader.geom import polygon_area, polyline_length
            operands = [input_value(f'outline point {i // 2 + 1} {"x" if i % 2 == 0 else "y"}', v, 'px', sref)
                        for i, v in enumerate(v for p in poly for v in p)]
            for metric, value, unit, operation, expr in [('area', polygon_area(poly), 'px2', 'polygon_area', '½ |Σ(xᵢ yᵢ₊₁ − xᵢ₊₁ yᵢ)|'),
                                                       ('perimeter', polyline_length(poly, True), 'px', 'polyline_closed', 'Σ sqrt((x₂−x₁)² + (y₂−y₁)²), closed outline')]:
                out.append(step(sid + '-' + metric + '-pixels', 'Room outline ' + metric, expr, value, unit, operands,
                                'Detected outline; this is not a separate independent measurement.', operation))
                if number(chosen):
                    scale_inputs = [input_value('stored page scale', chosen, 'm/px', {**ref, 'field': 'scale.m_per_px'})] * (2 if metric == 'area' else 1)
                    out.append(step(sid + '-' + metric, 'Scale room outline ' + metric,
                                    'outline pixels × scale²' if metric == 'area' else 'outline pixel perimeter × scale',
                                    value * chosen ** len(scale_inputs), 'm2' if metric == 'area' else 'm',
                                    [input_value('outline pixel ' + metric, value, unit, step_source(sid + '-' + metric + '-pixels')), *scale_inputs],
                                    'Context measurement at the stored page scale; printed quantities or refined scales in the selected answer can differ.', 'multiply'))
    return out, rows, unavailable, proof


def _attach(res, question, root):
    """Append scan context after final arithmetic; preserve its selected rows/result."""
    if (res.get('answer') or {}).get('abstained'):
        return res
    root = Path(root)
    card = res.setdefault('reasoning', {'steps': [], 'confidence': {'label': 'Estimate', 'pct': None}})
    existing = card.get('calc')
    new_steps, inventory, unavailable, proofs = [], [], [], []
    for did in res.get('doc_ids') or []:
        folder = root / did
        elements = read_json(folder / 'elements.json')
        native = elements.get('unit_provenance') if isinstance(elements, dict) else None
        if isinstance(native, dict) and number(native.get('m_per_unit')):
            by_assignment = defaultdict(list)
            for inp in native.get('inputs') or []:
                by_assignment[str(inp.get('source', {}).get('assignment') or '')].append(inp)
            for index, inputs in enumerate(by_assignment.values()):
                factors = []
                for inp in inputs:
                    original = inp.get('source') or {}
                    ref = {'kind': 'measurement', 'doc_id': did, 'artifact': 'elements.json', 'field': 'unit_provenance.inputs',
                           'record': {'doc_id': did, **original, 'value': inp['value']},
                           'text': 'Declared native-unit factor; original IFC entity and assignment retained in this snapshot.'}
                    factors.append(input_value(inp['name'], inp['value'], inp['unit'], ref))
                new_steps.append(step(f'scan-{did}-native-units-{index}', 'Native model units', native.get('formula') or 'product of declared conversion factors',
                                      native['m_per_unit'], 'm/native unit', factors, native.get('note', ''), 'multiply'))
        for path in sorted(folder.glob('planmap-[0-9]*.json')):
            pm = read_json(path)
            if not isinstance(pm, dict):
                continue
            page = pm.get('page', 1)
            if not any(i.get('source') in ('det', 'seg', 'vlm', 'vision') for i in pm.get('items', []) if isinstance(i, dict)):
                proof = enrich({**pm, 'doc_id': did, 'page': page}, folder, save_crops=False)['proof']
                new_steps.extend(_scale_steps(proof, f'scan-{did}-p{page}', did, page))
                proofs.append({'doc_id': did, 'page': page, **proof})
                continue
            steps, rows, missing, proof = _inventory(did, page, pm, folder)
            new_steps.extend(steps); inventory.extend(rows); unavailable.extend(missing)
            proofs.append({'doc_id': did, 'page': page, **proof})
        for name in ('planmap-seg.json', 'planmap-det.json'):
            path = folder / name
            if not path.is_file():
                continue
            pm = read_json(path)
            if not isinstance(pm, dict) or not pm.get('items'):
                continue
            steps, rows, _, _ = _inventory(did, pm.get('page', 1), pm, folder, name)
            # Alternate extractions are comparison context, never added to the
            # final count or selected-row total.
            for s in steps:
                if '-extract-' in s['id'] or s.get('operation') in ('sum', 'min', 'median') and not '-scale-' in s['id']:
                    s['label'] = 'Alternative saved extraction: ' + s['label']
                    s['note'] = f'{name}; not the selected answer inventory. ' + s.get('note', '')
                    new_steps.append(s)
            for r in rows:
                r['values']['alternative'] = True
            inventory.extend(rows)
    reader = res.pop('_reader_evidence', None) or (existing or {}).get('reader')
    if reader:
        from engine.reader.calc_trace import steps as reader_steps
        new_steps.extend(reader_steps(reader))
        if number(reader.get('model_confidence')):
            new_steps.append(_observation('reader-confidence', 'Reader self-reported confidence', reader['model_confidence'], 'score',
                                          {'kind': 'model', 'doc_id': next(iter(reader.get('doc_ids') or []), ''),
                                           'field': 'reader.model_confidence', 'record': reader.get('model_confidence')},
                                          'Self-report only; excluded from observed audit accuracy and physical error margins.'))
    if not new_steps and not reader:
        return res
    for index, trace in enumerate(res.get('trace') or []):
        data = trace.get('data') or {}
        if data.get('method') == 'score_filter':
            ref = {'kind': 'measurement', 'doc_id': next(iter(res.get('doc_ids') or []), ''),
                   'record': {'doc_id': next(iter(res.get('doc_ids') or []), ''), **trace}, 'text': 'Actual runtime solver score-filter observations'}
            for key in ('score_threshold', 'before', 'retained', 'rejected'):
                new_steps.append(_observation(f'scan-filter-{index}-{key}', f'Question selection ({data.get("kind")}): {key}',
                                              data[key], 'score' if key == 'score_threshold' else 'count', ref,
                                              'Threshold used by the answer solver; separate from any detector extraction threshold.'))
    from engine.reasoning_parts.counts import facts, recount_step
    count_facts = facts(res, question)
    if count_facts and count_facts.get('reread'):
        original, reread = count_facts['reread']
        detail = recount_step(count_facts)['text']
        for key, value in [('original', original), ('second-look', reread), ('reported', count_facts['total']), ('boxed', count_facts['boxes'])]:
            ref = {'kind': 'model' if key == 'second-look' else 'measurement',
                   'doc_id': next(iter(res.get('doc_ids') or []), ''), 'field': 'trace.recount / answer.value / evidence.boxes',
                   'record': {'doc_id': next(iter(res.get('doc_ids') or []), ''), 'value': value, 'policy': detail}, 'text': detail}
            new_steps.append(_observation('scan-recount-' + key, 'Recount: ' + key, value, 'count', ref, detail))
        new_steps.append(step('scan-recount-difference', 'Second-look disagreement', 'second-look count − original plan-map count', reread - original, 'count',
                              [input_value('second-look count', reread, 'count', step_source('scan-recount-second-look')),
                               input_value('original count', original, 'count', step_source('scan-recount-original'))], detail, 'subtract'))
    elif inventory:
        unavailable.append('No independent second-look count was recorded for this answer; saved model scores are not a recount.')
    if existing is None:
        ans = res.get('answer') or {}
        existing = {'formula': 'Inventory: Σ(1 per saved class item); measured area = outline pixels × scale²',
                    'steps': [], 'rows': [r for r in inventory if not r['values'].get('alternative')], 'result': {'value': ans.get('value'), 'unit': ans.get('unit'),
                                                             'rounded_as': 'No scalar total requested', 'mode': 'per-element'},
                    'row_note': 'Inventory contains all saved items. It is context for the description, not a verified building-wide count.',
                    'checks': [], 'margin': card.get('margin') or {'value': None, 'unit': None, 'pct': None,
                                                                 'why': 'No measured error budget is available.', 'sources': []}}
    # Idempotent finalizer: do not accumulate the same context on reattachment.
    existing['steps'] = new_steps + [s for s in existing['steps'] if not str(s.get('id')).startswith(('scan-', 'reader-', 'confidence-'))]
    existing['inventory_rows'] = inventory
    existing['scale_proof'] = (existing.get('scale_proof') or []) + [p for p in proofs if p not in existing.get('scale_proof', [])]
    existing['unavailable'] = list(dict.fromkeys([*(existing.get('unavailable') or []), *unavailable]))
    if reader:
        existing['reader'] = reader
    from engine.scan_method import describe
    method = describe(res, question, root, reader)
    if method:
        existing['method'] = method
    from engine.scan_uncertainty import attach as uncertainty, steps as uncertainty_steps
    if inventory or reader:
        uncertainty(res, question, existing)
        existing['steps'].extend(uncertainty_steps(card.get('margin') or {}, next(iter(res.get('doc_ids') or []), '')))
    confidence = card.get('confidence') or {}
    calibration = confidence.get('calibration')
    if calibration:
        ref = {'kind': 'measurement', 'doc_id': next(iter(res.get('doc_ids') or []), ''),
               'record': calibration, 'artifact': calibration.get('source'), 'text': calibration.get('scope')}
        existing['steps'].append(step('confidence-calibration', 'Observed audit accuracy', 'correct comparable answers / audited answers × 100, rounded',
                                      calibration['pct'], '%', [input_value('correct', calibration['correct'], 'count', ref),
                                      input_value('audited', calibration['n'], 'count', ref)],
                                      'Descriptive cohort accuracy; not a per-answer probability. No fixed vision-model baseline is added.', 'accuracy_pct'))
    else:
        note = 'Answer accuracy percentage: no matching measured calibration. A fixed vision heuristic is not used.'
        if note not in existing['unavailable']:
            existing['unavailable'].append(note)
    issues = validate(existing, root)
    existing['issues'], existing['status'] = issues, 'incomplete' if issues else 'complete'
    card['calc'] = existing
    return res


def attach(res, question, root):
    try:
        return _attach(res, question, root)
    except (ArithmeticError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # A malformed optional extraction must not lose the original answer.
        calc = (res.get('reasoning') or {}).get('calc')
        if calc is not None:
            calc.setdefault('unavailable', []).append(f'Scan/reader context could not be reconstructed ({type(exc).__name__}); source data is incomplete or malformed.')
        res.pop('_reader_evidence', None)
        return res
